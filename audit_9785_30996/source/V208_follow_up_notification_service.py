# -*- coding: utf-8 -*-
"""统一跟进通知：计划、扫描、回执、完成及紧凑 DTO。"""
from V207_security import effective_scope_bindings_in_tx
import json,uuid,time,threading,logging
from V207_shared_db import now_ms,dumps
OPEN=('scheduled','due','overdue')

class FollowUpPlanConflict(Exception):
 """A completed plan at the exact timestamp is immutable audit history."""
 pass
LOG=logging.getLogger(__name__)
_SCANNER_LOCK=threading.Lock();_SCANNERS={}

def _reason(row):
 try:return str((json.loads(row.get('business_json') or '{}') or {}).get('nextFollowUpReason') or '')[:500]
 except Exception:return ''
def _dict(row):return dict(row) if row is not None else None

def _table_columns(c,table):
 try:return {str(x[1]) for x in c.execute("PRAGMA table_info('"+str(table).replace("'", "''")+"')")}
 except Exception:return set()

def _snapshot(c,contact):
 """Build a notification snapshot without assuming every post-210.2.64 optional column exists."""
 cid=contact['contact_id'];out={'customer_name':contact.get('manual_name') or contact.get('display_name') or '未命名客户'}
 row=c.execute("SELECT manual_name,display_name,last_observed_device_id FROM contacts WHERE contact_id=?",(cid,)).fetchone()
 if row:
  out['customer_name']=row['manual_name'] or row['display_name'] or out['customer_name'];device_id=row['last_observed_device_id']
 else:device_id=contact.get('last_observed_device_id')
 out['device_name']=''
 dcols=_table_columns(c,'devices')
 if device_id and dcols:
  choices=[x for x in ('admin_device_name','user_device_alias','system_device_name','device_name') if x in dcols]
  if choices:
   expr='COALESCE('+','.join("NULLIF(trim("+x+"),'')" for x in choices)+",device_id)"
   d=c.execute('SELECT '+expr+' FROM devices WHERE device_id=?',(device_id,)).fetchone();out['device_name']=d[0] if d else ''
 out.update({'platform_id':None,'platform_code':None,'platform_abbr':None,'channel_account_id':None,'channel_account_name':None})
 vcols=_table_columns(c,'conversations')
 if {'conversation_id','contact_id'}.issubset(vcols):
  selected=[x for x in ('platform_id','channel_account_id') if x in vcols]
  if selected:
   order=[]
   for x in ('last_message_at','last_collected_at','updated_at'):
    if x in vcols:order.append('COALESCE('+x+',0) DESC')
   order.append('conversation_id DESC')
   v=c.execute('SELECT '+','.join(selected)+' FROM conversations WHERE contact_id=? ORDER BY '+','.join(order)+' LIMIT 1',(cid,)).fetchone()
   if v:
    data=dict(v);out['platform_id']=data.get('platform_id');out['channel_account_id']=data.get('channel_account_id')
 pcols=_table_columns(c,'platforms')
 if out['platform_id'] and pcols:
  selected=[x for x in ('platform_code','platform_abbr') if x in pcols]
  if selected:
   r=c.execute('SELECT '+','.join(selected)+' FROM platforms WHERE platform_id=?',(out['platform_id'],)).fetchone()
   if r:
    data=dict(r);out['platform_code']=data.get('platform_code');out['platform_abbr']=data.get('platform_abbr') or (str(out['platform_code']).upper() if out['platform_code'] else None)
 acols=_table_columns(c,'channel_accounts')
 if out['channel_account_id'] and 'display_name' in acols:
  r=c.execute('SELECT display_name FROM channel_accounts WHERE channel_account_id=?',(out['channel_account_id'],)).fetchone();out['channel_account_name']=r[0] if r else None
 return out

def _reminder_preferences(c,organization_id,user_id):
 row=c.execute("SELECT preferences_json FROM user_contact_center_preferences WHERE organization_id=? AND user_id=?",(organization_id,user_id)).fetchone()
 try:data=json.loads(row[0] or '{}') if row else {}
 except Exception:data={}
 pref=data.get('followUpReminder') if isinstance(data,dict) else {}
 pref=pref if isinstance(pref,dict) else {}
 return {'firstDelayMinutes':_bounded_int(pref.get('firstDelayMinutes'),10,0,1440),'repeatMinutes':_bounded_int(pref.get('repeatMinutes'),10,1,1440),'snoozeMinutes':_bounded_int(pref.get('snoozeMinutes'),10,1,1440),'privacyMode':pref.get('privacyMode') is not False}

def _recipients(c,contact,fallback=None):
 """负责人为主接收人；平台超级管理员可按企业订阅负责人并获得独立回执。"""
 org=contact['organization_id'];owner=contact.get('owner_user_id');recipients=[]
 if owner:
  row=c.execute("SELECT 1 FROM users WHERE user_id=? AND organization_id=? AND status='active'",(owner,org)).fetchone()
  if row:
   recipients.append(owner)
   # 三重约束：订阅启用、管理员身份仍有效、目标负责人仍属于当前企业且启用。
   rows=c.execute("""SELECT DISTINCT s.admin_user_id FROM platform_admin_notification_subscriptions s
    JOIN platform_administrators pa ON pa.user_id=s.admin_user_id
    JOIN users au ON au.user_id=s.admin_user_id AND au.status='active'
    WHERE s.organization_id=? AND s.owner_user_id=? AND s.enabled=1 ORDER BY s.admin_user_id""",(org,owner)).fetchall()
   recipients.extend(x[0] for x in rows)
 if recipients:return list(dict.fromkeys(recipients))
 if contact.get('team_id'):
  rows=c.execute("""SELECT DISTINCT b.user_id FROM role_bindings b JOIN users u ON u.user_id=b.user_id AND u.status='active' JOIN roles ro ON ro.role_id=b.role_id AND ro.status='active' JOIN role_permissions rp ON rp.role_id=b.role_id AND rp.permission_key='contact.read' WHERE b.organization_id=? AND b.status='active' AND (b.valid_from IS NULL OR b.valid_from<=?) AND (b.expires_at IS NULL OR b.expires_at>?) AND (b.scope_type='organization' OR (b.scope_type='team' AND b.scope_id=?)) ORDER BY b.user_id""",(org,now_ms(),now_ms(),contact['team_id'])).fetchall()
  if rows:return [x[0] for x in rows]
 if fallback:
  row=c.execute("SELECT 1 FROM users WHERE user_id=? AND organization_id=? AND status='active'",(fallback,org)).fetchone()
  if row:return [fallback]
 rows=c.execute("""SELECT DISTINCT u.user_id FROM users u LEFT JOIN role_bindings b ON b.user_id=u.user_id AND b.status='active'
  LEFT JOIN platform_administrators pa ON pa.user_id=u.user_id
  WHERE u.organization_id=? AND u.status='active' AND ((b.role_id='role_orgadmin' AND b.organization_id=?) OR pa.user_id IS NOT NULL)
  ORDER BY CASE WHEN b.role_id='role_orgadmin' THEN 0 ELSE 1 END,u.user_id""",(org,org)).fetchall()
 return [x[0] for x in rows]


def _close_receipts(c,notification_id,n):
 """Close every active receipt without deleting audit history."""
 c.execute("UPDATE follow_up_notification_receipts SET status='closed',claimed_by_consumer=NULL,claim_expires_at=NULL,version=version+1,updated_at=? WHERE notification_id=? AND status!='closed'",(n,notification_id))

def _sync_recipients(c,nid,contact,fallback,n):
 """Synchronize receipts without requiring a legacy table to have an UPSERT unique key."""
 expected=set(_recipients(c,contact,fallback))
 if expected:
  marks=','.join('?' for _ in expected)
  c.execute(f"UPDATE follow_up_notification_receipts SET status='closed',claimed_by_consumer=NULL,claim_expires_at=NULL,version=version+1,updated_at=? WHERE notification_id=? AND recipient_user_id NOT IN ({marks}) AND status!='closed'",[n,nid,*sorted(expected)])
 else:_close_receipts(c,nid,n)
 for uid in expected:
  pref=_reminder_preferences(c,contact['organization_id'],uid);first_at=int(contact.get('next_follow_up_at') or n)+pref['firstDelayMinutes']*60000
  rows=c.execute("SELECT receipt_id,status,first_alerted_at FROM follow_up_notification_receipts WHERE notification_id=? AND recipient_user_id=? ORDER BY created_at,receipt_id",(nid,uid)).fetchall()
  if rows:
   keep=rows[0];was_closed=keep['status']=='closed'
   c.execute("""UPDATE follow_up_notification_receipts SET status=CASE WHEN status='closed' THEN 'unread' ELSE status END,
    next_alert_at=CASE WHEN status='closed' OR (status='unread' AND first_alerted_at IS NULL) THEN ? ELSE next_alert_at END,
    snooze_until=CASE WHEN status='closed' THEN NULL ELSE snooze_until END,
    claimed_by_consumer=CASE WHEN status='closed' THEN NULL ELSE claimed_by_consumer END,
    claim_expires_at=CASE WHEN status='closed' THEN NULL ELSE claim_expires_at END,version=version+1,updated_at=? WHERE receipt_id=?""",(first_at,n,keep['receipt_id']))
   for duplicate in rows[1:]:c.execute("UPDATE follow_up_notification_receipts SET status='closed',claimed_by_consumer=NULL,claim_expires_at=NULL,version=version+1,updated_at=? WHERE receipt_id=?",(n,duplicate['receipt_id']))
  else:
   c.execute("INSERT INTO follow_up_notification_receipts(receipt_id,notification_id,organization_id,recipient_user_id,status,next_alert_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",('fur_'+uuid.uuid4().hex,nid,contact['organization_id'],uid,'unread',first_at,n,n))
 return len(expected)

def _audit(c,actor,workspace,operation,nid,before,after,reason=None):
 c.execute("INSERT INTO audit_logs(workspace_id,actor_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(workspace,actor or 'system',operation,'follow_up_notification',nid,dumps(before or {}),dumps(after or {}),reason,now_ms()))

def _is_platform_admin_in_tx(c,actor):
 return bool(actor and c.execute("SELECT 1 FROM platform_administrators WHERE user_id=?",(actor.get('user_id'),)).fetchone())

def notification_subscription_settings(db,actor,organization_id):
 org=str(organization_id or '').strip()
 with db.tx(False) as c:
  if not _is_platform_admin_in_tx(c,actor):return ({'ok':False,'code':'FORBIDDEN','message':'仅平台超级管理员可管理通知代管'},403)
  if not c.execute("SELECT 1 FROM organizations WHERE organization_id=? AND status='active'",(org,)).fetchone():return ({'ok':False,'code':'ORGANIZATION_NOT_FOUND','message':'企业不存在或已停用'},404)
  rows=c.execute("""SELECT u.user_id,u.display_name,u.login_name,u.status,
   CASE WHEN s.admin_user_id IS NULL THEN 0 ELSE 1 END selected
   FROM users u LEFT JOIN platform_admin_notification_subscriptions s
    ON s.owner_user_id=u.user_id AND s.organization_id=u.organization_id AND s.admin_user_id=? AND s.enabled=1
   WHERE u.organization_id=? AND u.status='active' AND NOT EXISTS(SELECT 1 FROM platform_administrators p WHERE p.user_id=u.user_id)
   ORDER BY u.display_name,u.login_name,u.user_id""",(actor['user_id'],org)).fetchall()
 return ({'ok':True,'organizationId':org,'items':[{'userId':x['user_id'],'displayName':x['display_name'],'loginName':x['login_name'],'selected':bool(x['selected'])} for x in rows]},200)

def save_notification_subscriptions(db,actor,organization_id,payload):
 org=str(organization_id or '').strip();payload=payload if isinstance(payload,dict) else {};raw=payload.get('ownerUserIds');reason=str(payload.get('reason') or '').strip()
 if not isinstance(raw,list):return ({'ok':False,'code':'INVALID_OWNER_USER_IDS','message':'ownerUserIds 必须是数组'},400)
 ids=[]
 for value in raw:
  uid=str(value or '').strip()
  if uid and uid not in ids:ids.append(uid)
 if len(ids)>1000:return ({'ok':False,'code':'TOO_MANY_SUBSCRIPTIONS','message':'单个企业最多选择 1000 位业务员'},400)
 if not reason or len(reason)>500:return ({'ok':False,'code':'INVALID_REASON','message':'请填写 1 至 500 字的变更原因'},400)
 n=now_ms()
 with db.tx() as c:
  if not _is_platform_admin_in_tx(c,actor):return ({'ok':False,'code':'FORBIDDEN','message':'仅平台超级管理员可管理通知代管'},403)
  if not c.execute("SELECT 1 FROM organizations WHERE organization_id=? AND status='active'",(org,)).fetchone():return ({'ok':False,'code':'ORGANIZATION_NOT_FOUND','message':'企业不存在或已停用'},404)
  if ids:
   marks=','.join('?' for _ in ids);valid={x[0] for x in c.execute(f"SELECT user_id FROM users WHERE organization_id=? AND status='active' AND user_id IN ({marks}) AND NOT EXISTS(SELECT 1 FROM platform_administrators p WHERE p.user_id=users.user_id)",[org,*ids]).fetchall()}
   if valid!=set(ids):return ({'ok':False,'code':'OWNER_SCOPE_MISMATCH','message':'所选业务员不存在、已停用、不属于当前企业或属于平台管理员'},409)
  before=[x[0] for x in c.execute("SELECT owner_user_id FROM platform_admin_notification_subscriptions WHERE admin_user_id=? AND organization_id=? AND enabled=1 ORDER BY owner_user_id",(actor['user_id'],org)).fetchall()]
  c.execute("DELETE FROM platform_admin_notification_subscriptions WHERE admin_user_id=? AND organization_id=?",(actor['user_id'],org))
  for uid in ids:c.execute("INSERT INTO platform_admin_notification_subscriptions(admin_user_id,organization_id,owner_user_id,enabled,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(actor['user_id'],org,uid,1,actor['user_id'],n,n))
  # 即时同步当前企业全部开放计划；不等待后台扫描器。
  rows=c.execute("""SELECT f.notification_id,ct.* FROM follow_up_notifications f JOIN contacts ct ON ct.contact_id=f.contact_id
   WHERE f.organization_id=? AND f.status IN ('scheduled','due','overdue')""",(org,)).fetchall()
  for row in rows:_sync_recipients(c,row['notification_id'],dict(row),None,n)
  workspace=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? ORDER BY workspace_id LIMIT 1",(org,)).fetchone()
  _audit(c,actor['user_id'],workspace[0] if workspace else 'system','notification-subscriptions.update',actor['user_id'],{'ownerUserIds':before},{'ownerUserIds':ids},reason)
 return ({'ok':True,'organizationId':org,'ownerUserIds':ids,'syncedOpenNotifications':len(rows)},200)

def sync_follow_up_plan_in_tx(c,contact,follow_up_at,reason=None,actor_user_id=None,now=None):
 contact=_dict(contact);n=now or now_ms();cid=contact['contact_id'];org=contact['organization_id'];reason=_reason(contact) if reason is None else str(reason or '')[:500]
 open_rows=c.execute("SELECT notification_id,follow_up_at,status FROM follow_up_notifications WHERE organization_id=? AND contact_id=? AND status IN ('scheduled','due','overdue')",(org,cid)).fetchall()
 if follow_up_at is None:
  for x in open_rows:
   c.execute("UPDATE follow_up_notifications SET status='cancelled',cancelled_at=?,cancellation_reason='follow_up_cleared',version=version+1,updated_at=? WHERE notification_id=?",(n,n,x['notification_id']));_close_receipts(c,x['notification_id'],n)
  return None
 follow_up_at=int(follow_up_at);contact['next_follow_up_at']=follow_up_at
 # Check all statuses against the table's actual UNIQUE business key.
 existing_rows=c.execute("SELECT notification_id,follow_up_at,status FROM follow_up_notifications WHERE organization_id=? AND contact_id=? AND follow_up_at=? ORDER BY CASE WHEN status IN ('scheduled','due','overdue') THEN 0 WHEN status='completed' THEN 1 ELSE 2 END,updated_at DESC,notification_id",(org,cid,follow_up_at)).fetchall();existing=existing_rows[0] if existing_rows else None
 same=next((x for x in open_rows if int(x['follow_up_at'])==follow_up_at),None)
 for x in open_rows:
  if int(x['follow_up_at'])!=follow_up_at:
   c.execute("UPDATE follow_up_notifications SET status='cancelled',cancelled_at=?,cancellation_reason='follow_up_rescheduled',version=version+1,updated_at=? WHERE notification_id=?",(n,n,x['notification_id']));_close_receipts(c,x['notification_id'],n)
 snap=_snapshot(c,contact)
 values=(contact.get('team_id'),reason,snap.get('customer_name'),contact.get('owner_user_id'),snap.get('platform_id'),snap.get('platform_code'),snap.get('platform_abbr'),snap.get('channel_account_id'),snap.get('channel_account_name'),contact.get('last_observed_device_id'),snap.get('device_name'),contact.get('version') or 0,n)
 update_sql="UPDATE follow_up_notifications SET team_id=?,follow_up_reason=?,customer_name=?,owner_user_id=?,platform_id=?,platform_code=?,platform_abbr=?,channel_account_id=?,channel_account_name=?,source_device_id=?,source_device_name=?,contact_version=?,version=version+1,updated_at=? WHERE notification_id=?"
 if same:
  nid=same['notification_id'];c.execute(update_sql,values+(nid,));_sync_recipients(c,nid,contact,actor_user_id,n);return nid
 if existing:
  # UNIQUE(organization, contact, time) makes an exact-time record canonical.
  # Completed history is immutable; cancelled/superseded plans may be explicitly reactivated.
  if existing['status']=='completed':raise FollowUpPlanConflict('FOLLOW_UP_TIME_ALREADY_COMPLETED')
  nid=existing['notification_id']
  c.execute("UPDATE follow_up_notifications SET status='scheduled',cancelled_at=NULL,cancellation_reason=NULL,first_due_at=NULL,last_scanned_at=NULL,version=version+1,updated_at=? WHERE notification_id=?",(n,nid))
  c.execute(update_sql,values+(nid,));_sync_recipients(c,nid,contact,actor_user_id,n);return nid
 nid='fun_'+uuid.uuid4().hex
 c.execute("INSERT INTO follow_up_notifications(notification_id,organization_id,workspace_id,team_id,contact_id,owner_user_id,follow_up_at,follow_up_reason,customer_name,platform_id,platform_code,platform_abbr,channel_account_id,channel_account_name,source_device_id,source_device_name,status,contact_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(nid,org,contact['workspace_id'],contact.get('team_id'),cid,contact.get('owner_user_id'),follow_up_at,reason,snap.get('customer_name'),snap.get('platform_id'),snap.get('platform_code'),snap.get('platform_abbr'),snap.get('channel_account_id'),snap.get('channel_account_name'),contact.get('last_observed_device_id'),snap.get('device_name'),'scheduled',contact.get('version') or 0,n,n))
 _sync_recipients(c,nid,contact,actor_user_id,n);return nid
def complete_follow_up_in_tx(c,contact_id,event_at,completed_by=None,message_id=None,mode='outbound_message',evidence=None):
 """Complete every due plan atomically and clear only the matching current contact plan.

 A delayed/replayed message must never erase a newer follow-up which an agent scheduled
 concurrently.  The contact compare-and-set below is therefore part of the same transaction.
 """
 if event_at is None:return 0
 event_at=int(event_at);n=now_ms()
 rows=c.execute("SELECT notification_id,follow_up_at FROM follow_up_notifications WHERE contact_id=? AND status IN ('scheduled','due','overdue') AND follow_up_at<=? ORDER BY follow_up_at",(contact_id,event_at)).fetchall()
 completed=[]
 for x in rows:
  cur=c.execute("UPDATE follow_up_notifications SET status='completed',completed_at=?,completed_by_user_id=?,completion_mode=?,completion_message_id=?,completion_evidence_json=?,version=version+1,updated_at=? WHERE notification_id=? AND status IN ('scheduled','due','overdue')",(event_at,completed_by,str(mode or 'manual')[:40],message_id,dumps(evidence or {}),n,x['notification_id']))
  if cur.rowcount:
   completed.append(int(x['follow_up_at']));_close_receipts(c,x['notification_id'],n)
 if completed:
  contact=c.execute("SELECT next_follow_up_at,business_json FROM contacts WHERE contact_id=? AND deleted_at IS NULL",(contact_id,)).fetchone()
  if contact and contact['next_follow_up_at'] is not None and int(contact['next_follow_up_at']) in completed:
   try:business=json.loads(contact['business_json'] or '{}')
   except Exception:business={}
   if not isinstance(business,dict):business={}
   business.pop('nextFollowUpReason',None)
   c.execute("UPDATE contacts SET next_follow_up_at=NULL,business_json=?,version=version+1,updated_at=? WHERE contact_id=? AND next_follow_up_at=?",(dumps(business),n,contact_id,int(contact['next_follow_up_at'])))
 return len(completed)

def scan_due_notifications(db,batch_size=200):
 n=now_ms();changed=0;limit=_bounded_int(batch_size,200,1,1000)
 # Discover candidates without taking the writer slot, then use small writes.
 with db.read() as c:contact_ids=[x['contact_id'] for x in c.execute("SELECT contact_id FROM contacts WHERE deleted_at IS NULL AND next_follow_up_at IS NOT NULL ORDER BY next_follow_up_at LIMIT ?",(limit,)).fetchall()]
 for offset in range(0,len(contact_ids),25):
  ids=contact_ids[offset:offset+25];marks=','.join('?' for _ in ids)
  with db.write() as c:
   for raw in c.execute("SELECT * FROM contacts WHERE contact_id IN ("+marks+")",ids).fetchall():
    contact=dict(raw);reason=_reason(contact);row=c.execute("SELECT notification_id,status,contact_version FROM follow_up_notifications WHERE organization_id=? AND contact_id=? AND follow_up_at=?",(contact['organization_id'],contact['contact_id'],contact['next_follow_up_at'])).fetchone()
    if not row or int(row['contact_version'] or 0)!=int(contact.get('version') or 0):sync_follow_up_plan_in_tx(c,contact,contact['next_follow_up_at'],reason,None,n);changed+=1
    elif row['status'] in OPEN:
     before=c.execute("SELECT count(*) FROM follow_up_notification_receipts WHERE notification_id=? AND status!='closed'",(row['notification_id'],)).fetchone()[0];recipients=_sync_recipients(c,row['notification_id'],contact,None,n)
     if before==0 and recipients:changed+=1
 with db.write() as c:
  stale=c.execute("SELECT f.notification_id FROM follow_up_notifications f LEFT JOIN contacts ct ON ct.contact_id=f.contact_id WHERE f.status IN ('scheduled','due','overdue') AND (ct.contact_id IS NULL OR ct.deleted_at IS NOT NULL OR ct.next_follow_up_at IS NULL OR ct.next_follow_up_at!=f.follow_up_at) LIMIT ?",(limit,)).fetchall()
  for x in stale:
   cur=c.execute("UPDATE follow_up_notifications SET status='cancelled',cancelled_at=?,cancellation_reason='source_plan_inactive',version=version+1,updated_at=? WHERE notification_id=? AND status IN ('scheduled','due','overdue')",(n,n,x['notification_id']));_close_receipts(c,x['notification_id'],n);changed+=cur.rowcount
 with db.write() as c:
  cur=c.execute("UPDATE follow_up_notifications SET status='due',first_due_at=COALESCE(first_due_at,follow_up_at),last_scanned_at=?,version=version+1,updated_at=? WHERE status='scheduled' AND follow_up_at<?",(n,n,n));changed+=cur.rowcount
  cur=c.execute("UPDATE follow_up_notifications SET status='overdue',last_scanned_at=?,version=version+1,updated_at=? WHERE status='due' AND follow_up_at<?",(n,n,n-10*60000));changed+=cur.rowcount
 with db.read() as c:completions=[dict(x) for x in c.execute("SELECT f.notification_id,f.contact_id,MAX(COALESCE(m.occurred_at,m.collected_at)) done_at FROM follow_up_notifications f JOIN conversation_messages m ON m.contact_id=f.contact_id JOIN conversations cv ON cv.conversation_id=m.conversation_id LEFT JOIN platforms pl ON pl.platform_id=cv.platform_id WHERE m.direction='outbound' AND m.sender_type='agent' AND m.status='active' AND m.deleted_at IS NULL AND COALESCE(m.occurred_at,m.collected_at)>=f.follow_up_at AND (LOWER(COALESCE(pl.platform_code,'')) NOT IN ('facebook','instagram','messenger') OR m.metadata_json LIKE '%\"followUpTriggerEligible\":true%') AND f.status IN ('scheduled','due','overdue') GROUP BY f.notification_id,f.contact_id LIMIT ?",(limit,)).fetchall()]
 for offset in range(0,len(completions),25):
  with db.write() as c:
   for x in completions[offset:offset+25]:changed+=complete_follow_up_in_tx(c,x['contact_id'],x['done_at'],None,None,'reconciliation',{'note':'检测到跟进时间后的业务员消息','source':'scanner'})
 return changed
def _completion_reason(r):
 try:evidence=json.loads(r.get('completion_evidence_json') or '{}')
 except Exception:evidence={}
 note=str(evidence.get('note') or evidence.get('reason') or '').strip()[:500] if isinstance(evidence,dict) else ''
 if note:return note
 return {'outbound_message':'检测到业务员发送消息','reconciliation':'根据已采集的业务员出站消息自动完成','manual':'人工标记完成','workbench':'工作台标记完成'}.get(str(r.get('completion_mode') or ''),'')

def _dto(row,n):
 r=dict(row);due=int(r['follow_up_at']);status=r['notification_status']
 return {'notificationId':r['notification_id'],'version':r['notification_version'],'status':status,'shouldAlert':bool(r.get('should_alert')),'contactId':r['contact_id'],'customerName':r['customer_name'] or '未命名客户','owner':{'id':r['owner_user_id'],'name':r['owner_name'] or '未分配负责人'} if r['owner_user_id'] else None,'sourceDevice':{'id':r['source_device_id'],'name':r['source_device_name'] or '未知设备'} if r['source_device_id'] else None,'platform':{'id':r['platform_id'],'code':r['platform_code'],'abbr':r['platform_abbr'] or (r['platform_code'] or '').upper() or '—'},'channelAccount':{'id':r['channel_account_id'],'name':r['channel_account_name'] or '未命名账号'} if r['channel_account_id'] else None,'followUpReason':r['follow_up_reason'],'followUpAt':due,'overdueSeconds':max(0,(n-due)//1000),'receipt':{'status':r.get('receipt_status'),'alertCount':r.get('alert_count') or 0,'lastAlertedAt':r.get('last_alerted_at'),'snoozeUntil':r.get('snooze_until')},'canAct':bool(r.get('can_act',1)),'recipientCount':int(r.get('recipient_count') or 0),'unassigned':int(r.get('recipient_count') or 0)==0,'completedAt':r.get('completed_at'),'completionMode':r.get('completion_mode'),'completionReason':_completion_reason(r),'cancelledAt':r.get('cancelled_at'),'cancellationReason':r.get('cancellation_reason')}

def _bounded_int(value,default,lo,hi):
 try:value=int(value)
 except (TypeError,ValueError):value=default
 return max(lo,min(hi,value))

def poll_notifications(db,actor,payload,organization_id=None):
 payload=payload if isinstance(payload,dict) else {};uid=actor['user_id'];org=str(organization_id or actor['organization_id']);n=now_ms();limit=_bounded_int(payload.get('limit'),100,1,100);ctype=str(payload.get('consumerType') or 'admin')[:30];cid=str(payload.get('consumerId') or '')[:160] or 'anonymous';pref=None;repeat=0
 with db.tx() as c:
  pref=_reminder_preferences(c,org,uid);repeat=pref['repeatMinutes']*60000
  rows=c.execute("""SELECT f.*,f.status notification_status,f.version notification_version,r.status receipt_status,r.alert_count,r.last_alerted_at,r.snooze_until,u.display_name owner_name
   FROM follow_up_notification_receipts r JOIN follow_up_notifications f ON f.notification_id=r.notification_id LEFT JOIN users u ON u.user_id=f.owner_user_id
   WHERE r.organization_id=? AND r.recipient_user_id=? AND f.status IN ('due','overdue') AND r.status NOT IN ('dismissed','closed')
   ORDER BY f.follow_up_at,f.notification_id LIMIT ?""",(org,uid,limit)).fetchall()
  out=[]
  for raw in rows:
   r=dict(raw);eligible=int(r.get('next_alert_at') or 0)<=n and int(r.get('snooze_until') or 0)<=n
   claimed=False
   if eligible:
    cur=c.execute("""UPDATE follow_up_notification_receipts SET status='alerted',first_alerted_at=COALESCE(first_alerted_at,?),last_alerted_at=?,next_alert_at=?,alert_count=alert_count+1,claimed_by_consumer=?,claim_expires_at=?,last_consumer_type=?,last_consumer_id=?,version=version+1,updated_at=?
     WHERE notification_id=? AND recipient_user_id=? AND status NOT IN ('dismissed','closed') AND COALESCE(next_alert_at,0)<=? AND COALESCE(snooze_until,0)<=? AND (claim_expires_at IS NULL OR claim_expires_at<=? OR claimed_by_consumer=?)""",(n,n,n+repeat,ctype+':'+cid,n+60000,ctype,cid,n,r['notification_id'],uid,n,n,n,ctype+':'+cid))
    claimed=cur.rowcount==1
    if claimed:r.update({'receipt_status':'alerted','alert_count':int(r['alert_count'] or 0)+1,'last_alerted_at':n})
   r['should_alert']=claimed;out.append(_dto(r,n))
  unread=c.execute("SELECT count(*) FROM follow_up_notification_receipts r JOIN follow_up_notifications f ON f.notification_id=r.notification_id WHERE r.organization_id=? AND r.recipient_user_id=? AND f.status IN ('due','overdue') AND r.status NOT IN ('dismissed','closed')",(org,uid)).fetchone()[0]
 return ({'ok':True,'serverTime':n,'unreadCount':unread,'preferences':pref,'items':out},200)

def _query_scalar(query,key,default=''):
 value=(query or {}).get(key,default)
 if isinstance(value,list):value=value[-1] if value else default
 return str(value or default).strip()

def _management_scope(c,actor,organization_id=None):
 org=str(organization_id or actor['organization_id']);grants=effective_scope_bindings_in_tx(c,actor,'contact.read',org)
 if any(x['scope_type'] in ('platform','organization') for x in grants):return 'organization',[]
 teams=sorted({x['scope_id'] for x in grants if x['scope_type']=='team'})
 return ('teams',teams) if teams else ('personal',[])

def list_notifications(db,actor,query=None,organization_id=None):
 query=query or {};org=str(organization_id or actor['organization_id']);uid=actor['user_id'];state=_query_scalar(query,'status','open');view=_query_scalar(query,'view','mine');receipt_state=_query_scalar(query,'receiptStatus','');search=_query_scalar(query,'q','')[:100];page=_bounded_int(_query_scalar(query,'page','1'),1,1,100000);size=_bounded_int(_query_scalar(query,'pageSize','50'),50,1,100)
 states=('scheduled','due','overdue') if state=='open' else (('scheduled','due','overdue','completed','cancelled','superseded') if state=='all' else ((state,) if state in ('scheduled','due','overdue','completed','cancelled','superseded') else ('scheduled','due','overdue')))
 marks=','.join('?' for _ in states);n=now_ms()
 with db.tx(False) as c:
  management,teams=_management_scope(c,actor,org);team_view=view in ('team','organization') and management!='personal'
  where=["f.organization_id=?",f"f.status IN ({marks})"];args=[org,*states]
  if team_view:
   if management=='teams':
    tmarks=','.join('?' for _ in teams);where.append(f"f.team_id IN ({tmarks})");args.extend(teams)
   join="LEFT JOIN follow_up_notification_receipts r ON r.notification_id=f.notification_id AND r.recipient_user_id=?";join_args=[uid]
  else:
   join="JOIN follow_up_notification_receipts r ON r.notification_id=f.notification_id AND r.recipient_user_id=?";join_args=[uid]
  if receipt_state in ('unread','alerted','read','snoozed','dismissed','closed'):where.append("r.status=?");args.append(receipt_state)
  if search:where.append("(f.customer_name LIKE ? OR f.follow_up_reason LIKE ? OR f.contact_id LIKE ?)");like='%'+search+'%';args.extend([like,like,like])
  condition=' AND '.join(where);params=join_args+args
  total=c.execute(f"SELECT count(*) FROM follow_up_notifications f {join} WHERE {condition}",params).fetchone()[0]
  rows=c.execute(f"""SELECT f.*,f.status notification_status,f.version notification_version,COALESCE(r.status,'') receipt_status,COALESCE(r.alert_count,0) alert_count,r.last_alerted_at,r.snooze_until,u.display_name owner_name,0 should_alert,CASE WHEN r.receipt_id IS NULL OR r.status='closed' THEN 0 ELSE 1 END can_act,(SELECT count(*) FROM follow_up_notification_receipts rr WHERE rr.notification_id=f.notification_id AND rr.status!='closed') recipient_count
   FROM follow_up_notifications f {join} LEFT JOIN users u ON u.user_id=f.owner_user_id WHERE {condition} ORDER BY CASE f.status WHEN 'overdue' THEN 0 WHEN 'due' THEN 1 WHEN 'scheduled' THEN 2 ELSE 3 END,f.follow_up_at DESC LIMIT ? OFFSET ?""",params+[size,(page-1)*size]).fetchall()
 return ({'ok':True,'view':'team' if team_view else 'mine','managementScope':management,'page':page,'pageSize':size,'total':total,'items':[_dto(dict(x),n) for x in rows]},200)

def notification_summary(db,actor,organization_id=None):
 org=str(organization_id or actor['organization_id']);uid=actor['user_id'];n=now_ms();start=n-(n%86400000)
 with db.tx(False) as c:
  counts={x['status']:x['n'] for x in c.execute("SELECT f.status,count(*) n FROM follow_up_notification_receipts r JOIN follow_up_notifications f ON f.notification_id=r.notification_id WHERE r.organization_id=? AND r.recipient_user_id=? GROUP BY f.status",(org,uid))}
  unread=c.execute("SELECT count(*) FROM follow_up_notification_receipts r JOIN follow_up_notifications f ON f.notification_id=r.notification_id WHERE r.organization_id=? AND r.recipient_user_id=? AND f.status IN ('due','overdue') AND r.status IN ('unread','alerted','snoozed','read')",(org,uid)).fetchone()[0]
  completed_today=c.execute("SELECT count(*) FROM follow_up_notification_receipts r JOIN follow_up_notifications f ON f.notification_id=r.notification_id WHERE r.organization_id=? AND r.recipient_user_id=? AND f.status='completed' AND f.completed_at>=?",(org,uid,start)).fetchone()[0]
  management,teams=_management_scope(c,actor,org);scope_sql='';scope_args=[]
  if management=='teams':scope_sql=' AND f.team_id IN ('+','.join('?' for _ in teams)+')';scope_args=teams
  if management=='personal':team_due=unread;unassigned=0
  else:
   team_due=c.execute("SELECT count(*) FROM follow_up_notifications f WHERE f.organization_id=? AND f.status IN ('due','overdue')"+scope_sql,[org,*scope_args]).fetchone()[0]
   unassigned=c.execute("SELECT count(*) FROM follow_up_notifications f WHERE f.organization_id=? AND f.status IN ('scheduled','due','overdue') AND NOT EXISTS(SELECT 1 FROM follow_up_notification_receipts r WHERE r.notification_id=f.notification_id AND r.status!='closed')"+scope_sql,[org,*scope_args]).fetchone()[0]
 return ({'ok':True,'scheduled':counts.get('scheduled',0),'due':counts.get('due',0),'overdue':counts.get('overdue',0),'completedToday':completed_today,'unread':unread,'teamDue':team_due,'unassigned':unassigned,'managementScope':management},200)

def receipt_action(db,actor,nid,action,payload=None,organization_id=None):
 payload=payload if isinstance(payload,dict) else {};uid=actor['user_id'];org=str(organization_id or actor['organization_id']);n=now_ms()
 with db.tx() as c:
  row=c.execute("SELECT f.*,r.status receipt_status,r.version receipt_version FROM follow_up_notifications f JOIN follow_up_notification_receipts r ON r.notification_id=f.notification_id WHERE f.notification_id=? AND f.organization_id=? AND r.recipient_user_id=?",(nid,org,uid)).fetchone()
  if not row or row['receipt_status']=='closed':return ({'ok':False,'code':'NOTIFICATION_NOT_FOUND','message':'通知不存在或无权处理'},404)
  before={'notificationStatus':row['status'],'receiptStatus':row['receipt_status'],'receiptVersion':row['receipt_version']}
  if action=='complete':
   changed=complete_follow_up_in_tx(c,row['contact_id'],n,uid,None,str(payload.get('completionMode') or 'manual')[:40],{'note':str(payload.get('note') or '')[:500]}) if row['status'] in OPEN else 0
   final='completed' if changed else row['status'];_audit(c,uid,row['workspace_id'],'follow-up.complete',nid,before,{'notificationStatus':final},str(payload.get('note') or '')[:500] or None)
   return ({'ok':True,'notificationId':nid,'status':final,'unchanged':not bool(changed)},200)
  if row['status'] not in OPEN:return ({'ok':True,'notificationId':nid,'status':row['status'],'unchanged':True},200)
  if action=='snooze':
   minutes=_reminder_preferences(c,org,uid)['snoozeMinutes'];until=n+minutes*60000;c.execute("UPDATE follow_up_notification_receipts SET status='snoozed',snooze_until=?,next_alert_at=?,claimed_by_consumer=NULL,claim_expires_at=NULL,version=version+1,updated_at=? WHERE notification_id=? AND recipient_user_id=?",(until,until,n,nid,uid));state='snoozed';after={'receiptStatus':state,'snoozeUntil':until}
  elif action=='dismiss':c.execute("UPDATE follow_up_notification_receipts SET status='dismissed',dismissed_at=?,claimed_by_consumer=NULL,claim_expires_at=NULL,version=version+1,updated_at=? WHERE notification_id=? AND recipient_user_id=?",(n,n,nid,uid));state='dismissed';after={'receiptStatus':state}
  elif action=='read':c.execute("UPDATE follow_up_notification_receipts SET status='read',read_at=COALESCE(read_at,?),version=version+1,updated_at=? WHERE notification_id=? AND recipient_user_id=? AND status NOT IN ('dismissed','closed')",(n,n,nid,uid));state='read';after={'receiptStatus':state}
  else:return ({'ok':False,'code':'INVALID_NOTIFICATION_ACTION','message':'不支持的通知操作'},400)
  _audit(c,uid,row['workspace_id'],'follow-up.'+action,nid,before,after)
 return ({'ok':True,'notificationId':nid,'status':state},200)

def start_scanner(db,interval=15):
 key=str(getattr(db,'path',getattr(db,'db_path',id(db))))
 with _SCANNER_LOCK:
  current=_SCANNERS.get(key)
  if current and current.is_alive():return current
  def run():
   while True:
    try:scan_due_notifications(db)
    except Exception:LOG.exception('follow-up notification scan failed')
    time.sleep(max(5,int(interval)))
  t=threading.Thread(target=run,name='follow-up-notification-scanner',daemon=True);_SCANNERS[key]=t;t.start();return t

