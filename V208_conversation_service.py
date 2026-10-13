import logging
LOG = logging.getLogger('jubaopen.conversation')
IG_UNRESOLVED_NOISE_FILTER="NOT (json_valid(m.metadata_json) AND json_extract(m.metadata_json,'$.timestampResolved')=0 AND (json_extract(m.metadata_json,'$.identityVersion') LIKE 'ig-message-%' OR json_extract(m.metadata_json,'$.platformCode')='instagram') AND (lower(COALESCE(m.external_message_id,'')) GLOB '*:dom.*' OR lower(COALESCE(m.external_message_id,'')) GLOB '*:dom2.*' OR lower(COALESCE(m.external_message_id,'')) GLOB '*:dom3.*' OR lower(COALESCE(m.external_message_id,'')) GLOB '*:dom4.*' OR lower(COALESCE(m.client_event_id,'')) GLOB '*:dom.*' OR lower(COALESCE(m.client_event_id,'')) GLOB '*:dom2.*' OR lower(COALESCE(m.client_event_id,'')) GLOB '*:dom3.*' OR lower(COALESCE(m.client_event_id,'')) GLOB '*:dom4.*'))"
# -*- coding: utf-8 -*-
"""Schema 222 跨平台会话查询、生命周期、原文审计和正文删除。"""
from V207_shared_db import now_ms,dumps
from V208_privacy import public_message
from V209_validation import ValidationError,decode_cursor,encode_cursor,limit as valid_limit,version as valid_version,write_audit

def err(c,m,s=400,**extra):
 out={'ok':False,'code':c,'message':m};out.update(extra);return out,s

def _value(v):return v[-1] if isinstance(v,list) and v else v

def _scope(a):return (a['organization_id'],a['workspace_id'],a['team_id'])

def _conversation(c,a,conversation_id):
 sql='SELECT * FROM conversations WHERE conversation_id=? AND organization_id=? AND workspace_id=? AND team_id=?'
 params=[conversation_id]+list(_scope(a))
 if a.get('_conversation_access')=='self':
  sql+=' AND assigned_user_id=?';params.append(a['user_id'])
 return c.execute(sql,tuple(params)).fetchone()

def _conversation_public(r):
 return {k:r[k] for k in ('conversation_id','contact_id','contact_identity_id','channel_account_id','platform_id','external_conversation_id','status','assigned_user_id','first_message_at','last_message_at','last_message_id','last_message_direction','last_message_type','last_message_preview','message_count','inbound_count','outbound_count','closed_at','closed_by','archived_at','archived_by','version','created_at','updated_at')}

def _conversation_joined_public(r):
 item=_conversation_public(r)
 keys=('contact_name','contact_phone','contact_email','contact_avatar_url','platform_name','platform_code','channel_account_name','assigned_user_name','device_id','device_name','device_color')
 for key in keys:
  try:item[key]=r[key]
  except (KeyError,IndexError):item[key]=None
 return item

def _list_conversations_legacy_210027(db,a,args=None):
 args=args or {}
 try:
  size=valid_limit(_value(args.get('limit')),50,200)
  status=str(_value(args.get('status')) or '').strip()
  if status and status not in ('active','closed','archived'):raise ValidationError('INVALID_ENUM','status 无效','status')
  platform=str(_value(args.get('platformId') or args.get('platform_id')) or '').strip()
  contact=str(_value(args.get('contactId') or args.get('contact_id')) or '').strip()
  account=str(_value(args.get('channelAccountId') or args.get('channel_account_id')) or '').strip()
  owner=str(_value(args.get('assignedUserId') or args.get('assigned_user_id')) or '').strip()
  direction=str(_value(args.get('direction')) or '').strip()
  keyword=str(_value(args.get('keyword') or args.get('q')) or '').strip()
  if direction and direction not in ('inbound','outbound'):raise ValidationError('INVALID_ENUM','direction 无效','direction')
  if len(keyword)>120:raise ValidationError('KEYWORD_TOO_LONG','搜索关键词不得超过 120 字符','keyword')
  cursor=_value(args.get('cursor'));point=decode_cursor(cursor,'conversation') if cursor else None
 except ValidationError as e:return err(e.code,str(e),400,field=e.field)
 where=['v.organization_id=?','v.workspace_id=?','v.team_id=?'];params=list(_scope(a))
 if a.get('_conversation_access')=='self':where.append('v.assigned_user_id=?');params.append(a['user_id'])
 if status:where.append('v.status=?');params.append(status)
 if platform:where.append('v.platform_id=?');params.append(platform)
 if contact:where.append('v.contact_id=?');params.append(contact)
 if account:where.append('v.channel_account_id=?');params.append(account)
 if owner:where.append('v.assigned_user_id=?');params.append(owner)
 if direction:where.append('v.last_message_direction=?');params.append(direction)
 if keyword:
  like='%'+keyword+'%'
  where.append("(v.conversation_id LIKE ? OR v.external_conversation_id LIKE ? OR v.last_message_preview LIKE ? OR ct.display_name LIKE ? OR ct.manual_name LIKE ? OR ct.observed_phone LIKE ? OR ca.display_name LIKE ?)")
  params.extend([like]*7)
 if point:
  where.append('(COALESCE(v.last_message_at,0)<? OR (COALESCE(v.last_message_at,0)=? AND v.conversation_id<?))');params.extend((point[0],point[0],point[1]))
 params.append(size+1)
 sql="""SELECT v.*,ct.display_name contact_name,COALESCE(NULLIF(ct.manual_phone,''),ct.observed_phone,'') contact_phone,'' contact_email,ct.avatar_url contact_avatar_url,p.platform_name,p.platform_code,ca.display_name channel_account_name,u.display_name assigned_user_name,
 d.device_id,COALESCE(NULLIF(d.admin_device_name,''),NULLIF(d.user_device_alias,''),NULLIF(d.system_device_name,''),NULLIF(d.device_name,''),d.device_id) device_name,
 COALESCE(NULLIF(json_extract(d.metadata_json,'$.color'),''),'#64748b') device_color
 FROM conversations v
 LEFT JOIN contacts ct ON ct.contact_id=v.contact_id AND ct.workspace_id=v.workspace_id
 LEFT JOIN platforms p ON p.platform_id=v.platform_id
 LEFT JOIN channel_accounts ca ON ca.channel_account_id=v.channel_account_id AND ca.organization_id=v.organization_id
 LEFT JOIN users u ON u.user_id=v.assigned_user_id AND u.organization_id=v.organization_id
 LEFT JOIN devices d ON d.device_id=ct.last_observed_device_id AND d.organization_id=v.organization_id AND d.workspace_id=v.workspace_id AND d.team_id=v.team_id
 WHERE """+' AND '.join(where)+' ORDER BY COALESCE(v.last_message_at,0) DESC,v.conversation_id DESC LIMIT ?'
 with db.tx(False) as c:
  rows=c.execute(sql,tuple(params)).fetchall()
  option_devices=c.execute("""SELECT d.device_id,COALESCE(NULLIF(d.admin_device_name,''),NULLIF(d.user_device_alias,''),NULLIF(d.system_device_name,''),NULLIF(d.device_name,''),d.device_id) device_name,COALESCE(NULLIF(json_extract(d.metadata_json,'$.color'),''),'#64748b') device_color FROM devices d WHERE d.organization_id=? AND d.workspace_id=? AND d.team_id=? AND d.status='active' ORDER BY device_name COLLATE NOCASE,d.device_id""",_scope(a)).fetchall()
  option_platforms=c.execute("""SELECT DISTINCT p.platform_id,p.platform_code,p.platform_name FROM platforms p JOIN channel_accounts ca ON ca.platform_id=p.platform_id AND ca.organization_id=? AND ca.workspace_id=? AND ca.team_id=? WHERE p.status='active' ORDER BY p.platform_name COLLATE NOCASE""",_scope(a)).fetchall()
 has_more=len(rows)>size;rows=rows[:size]
 next_cursor=encode_cursor(rows[-1]['last_message_at'] or 0,rows[-1]['conversation_id'],'conversation') if has_more and rows else None
 return {'ok':True,'items':[_conversation_joined_public(r) for r in rows],'availableDevices':[dict(x) for x in option_devices],'availablePlatforms':[dict(x) for x in option_platforms],'nextCursor':next_cursor,'hasMore':has_more,'filtersApplied':{'keyword':keyword,'platformId':platform,'contactId':contact,'channelAccountId':account,'assignedUserId':owner,'status':status,'direction':direction}},200

def get_conversation(db,a,conversation_id):
 with db.tx(False) as c:
  r=_conversation(c,a,conversation_id)
  if not r:return err('CONVERSATION_SCOPE_INVALID','会话不存在或无权访问',404)
  contact=c.execute("SELECT contact_id,display_name,manual_name,COALESCE(NULLIF(manual_phone,''),observed_phone,'') phone,avatar_url,status,version FROM contacts WHERE contact_id=? AND workspace_id=? AND deleted_at IS NULL",(r['contact_id'],a['workspace_id'])).fetchone()
  platform=c.execute('SELECT platform_id,platform_name FROM platforms WHERE platform_id=?',(r['platform_id'],)).fetchone()
  account=c.execute('SELECT channel_account_id,display_name,platform_id,status,collection_enabled FROM channel_accounts WHERE channel_account_id=? AND organization_id=?',(r['channel_account_id'],a['organization_id'])).fetchone()
  owner=c.execute('SELECT user_id,display_name,login_name,status FROM users WHERE user_id=? AND organization_id=?',(r['assigned_user_id'],a['organization_id'])).fetchone() if r['assigned_user_id'] else None
  identities=c.execute('SELECT contact_identity_id,platform_id,external_user_id,external_username,display_name,verified_at,last_seen_at,status FROM contact_identities WHERE contact_id=? AND organization_id=? AND workspace_id=? AND team_id=? ORDER BY COALESCE(last_seen_at,0) DESC',(r['contact_id'],)+_scope(a)).fetchall()
  transfers=c.execute("SELECT transfer_id,status,from_platform_id,to_platform_id,from_channel_account_id,to_channel_account_id,transfer_method,requested_at,expires_at,version FROM contact_transfers WHERE contact_id=? AND organization_id=? AND workspace_id=? AND team_id=? ORDER BY requested_at DESC LIMIT 20",(r['contact_id'],)+_scope(a)).fetchall()
 return {'ok':True,'conversation':_conversation_public(r),'contact':dict(contact) if contact else None,'platform':dict(platform) if platform else None,'channelAccount':dict(account) if account else None,'assignedUser':dict(owner) if owner else None,'identities':[dict(x) for x in identities],'transfers':[dict(x) for x in transfers]},200

def list_contact_timeline(db,a,contact_id,args=None,allow_raw=False):
 args=args or {}
 try:
  size=valid_limit(_value(args.get('limit')),100,500)
  cursor=_value(args.get('cursor'));point=decode_cursor(cursor,'contact-timeline-v2') if cursor else None
  platform=str(_value(args.get('platformId') or args.get('platform_id')) or '').strip()
  direction=str(_value(args.get('direction')) or '').strip()
  if direction and direction not in ('inbound','outbound','system'):raise ValidationError('INVALID_ENUM','direction 无效','direction')
 except ValidationError as e:return err(e.code,str(e),400,field=e.field)
 with db.tx(bool(allow_raw)) as c:
  contact=c.execute('SELECT 1 FROM contacts WHERE contact_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND deleted_at IS NULL',(contact_id,)+_scope(a)).fetchone()
  if not contact:return err('CONTACT_SCOPE_INVALID','客户不存在或无权访问',404)
  mw=['m.contact_id=?','m.organization_id=?','m.workspace_id=?','m.team_id=?','m.deleted_at IS NULL',IG_UNRESOLVED_NOISE_FILTER];mp=[contact_id]+list(_scope(a))
  if a.get('_conversation_access')=='self':mw.append('v.assigned_user_id=?');mp.append(a['user_id'])
  if platform:mw.append('v.platform_id=?');mp.append(platform)
  if direction:mw.append('m.direction=?');mp.append(direction)
  message_sql="""SELECT 'message' event_kind,m.occurred_at effective_time,m.message_id sort_id,m.message_id,m.conversation_id,m.direction,m.sender_type,m.content_type,m.text_content,m.redacted_text,m.occurred_at,m.collected_at,m.edited_at,m.status,m.content_deleted_at,v.platform_id,v.channel_account_id,v.assigned_user_id,NULL transfer_id,NULL transfer_event_type,NULL from_status,NULL to_status,NULL actor_id,NULL reason
  FROM conversation_messages m JOIN conversations v ON v.conversation_id=m.conversation_id AND v.organization_id=m.organization_id AND v.workspace_id=m.workspace_id AND v.team_id=m.team_id WHERE """+' AND '.join(mw)
  tw=['e.contact_id=?','e.organization_id=?','e.workspace_id=?','e.team_id=?'];tp=[contact_id]+list(_scope(a))
  if a.get('_transfer_access')=='self':tw.append('t.requested_by=?');tp.append(a['user_id'])
  if platform:tw.append('(t.from_platform_id=? OR t.to_platform_id=?)');tp.extend((platform,platform))
  if direction:tw.append('1=0')
  transfer_sql="""SELECT 'transfer' event_kind,e.created_at effective_time,e.event_id sort_id,NULL message_id,e.conversation_id,'system' direction,'system' sender_type,'transfer' content_type,NULL text_content,NULL redacted_text,e.created_at occurred_at,e.created_at collected_at,NULL edited_at,e.to_status status,NULL content_deleted_at,COALESCE(t.to_platform_id,t.from_platform_id) platform_id,e.channel_account_id,NULL assigned_user_id,e.transfer_id,e.event_type transfer_event_type,e.from_status,e.to_status,e.actor_id,e.reason
  FROM contact_transfer_events e JOIN contact_transfers t ON t.transfer_id=e.transfer_id WHERE """+' AND '.join(tw)
  union='SELECT * FROM ('+message_sql+' UNION ALL '+transfer_sql+') z'
  params=mp+tp
  if point:union+=' WHERE (effective_time<? OR (effective_time=? AND sort_id<?))';params.extend((point[0],point[0],point[1]))
  union+=' ORDER BY effective_time DESC,sort_id DESC LIMIT ?';params.append(size+1)
  rows=c.execute(union,tuple(params)).fetchall();has_more=len(rows)>size;rows=rows[:size]
  items=[]
  for row in rows:
   if row['event_kind']=='message':
    item=public_message(row,allow_raw);item.update({'eventType':'message','effectiveTime':row['effective_time'],'platformId':row['platform_id'],'channelAccountId':row['channel_account_id'],'assignedUserId':row['assigned_user_id']})
   else:item={'eventType':'transfer','effectiveTime':row['effective_time'],'transferId':row['transfer_id'],'transferEventType':row['transfer_event_type'],'fromStatus':row['from_status'],'toStatus':row['to_status'],'actorId':row['actor_id'],'conversationId':row['conversation_id'],'channelAccountId':row['channel_account_id'],'platformId':row['platform_id'],'reason':row['reason']}
   items.append(item)
  next_cursor=encode_cursor(rows[-1]['effective_time'],rows[-1]['sort_id'],'contact-timeline-v2') if has_more and rows else None
  if allow_raw:write_audit(c,a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'],'message.read.raw','contact',contact_id,after={'returnedCount':len(rows),'cursor':cursor,'limit':size,'platformId':platform or None,'includesTransferEvents':True},reason='查看客户连续时间线原文',device_id=a.get('device_id'))
 return {'ok':True,'contactId':contact_id,'items':items,'nextCursor':next_cursor,'hasMore':has_more,'includesTransferEvents':True},200

def transition_conversation(db,a,conversation_id,action,body=None):
 body=body or {}
 try:base=valid_version(body.get('baseVersion'))
 except ValidationError as e:return err(e.code,str(e),400,field=e.field)
 reason=str(body.get('reason') or '').strip()
 if len(reason)>1000:return err('REASON_TOO_LONG','原因不得超过 1000 字符')
 rules={'close':(('active',),'closed'),'reopen':(('closed',),'active'),'archive':(('active','closed'),'archived')}
 if action not in rules:return err('INVALID_ACTION','会话操作无效')
 allowed,target=rules[action]
 with db.tx() as c:
  row=_conversation(c,a,conversation_id)
  if not row:return err('CONVERSATION_SCOPE_INVALID','会话不存在或无权访问',404)
  if row['version']!=base:return err('CONVERSATION_VERSION_CONFLICT','会话已被更新，请刷新后重试',409,currentVersion=row['version'])
  if row['status'] not in allowed:return err('INVALID_CONVERSATION_STATE','当前状态不允许执行该操作',409,currentStatus=row['status'])
  n=now_ms();sets=['status=?','version=version+1','updated_at=?'];values=[target,n]
  if action=='close':sets+=['closed_at=?','closed_by=?'];values += [n,a['user_id']]
  elif action=='reopen':sets+=['closed_at=NULL','closed_by=NULL','archived_at=NULL','archived_by=NULL']
  else:sets+=['archived_at=?','archived_by=?'];values += [n,a['user_id']]
  values += [conversation_id]+list(_scope(a))+[base]
  changed=c.execute('UPDATE conversations SET '+','.join(sets)+' WHERE conversation_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND version=?',tuple(values))
  if changed.rowcount!=1:return err('CONVERSATION_VERSION_CONFLICT','会话已被更新，请刷新后重试',409)
  fresh=_conversation(c,a,conversation_id)
  write_audit(c,a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'],'conversation.'+action,'conversation',conversation_id,before={'status':row['status'],'version':row['version']},after={'status':target,'version':fresh['version']},reason=reason or None,device_id=a.get('device_id'))
 return {'ok':True,'conversation':_conversation_public(fresh)},200

def delete_content(db,a,message_id,reason):
 reason=str(reason or '').strip()
 if not reason:return err('REASON_REQUIRED','删除正文必须填写原因')
 if len(reason)>1000:return err('REASON_TOO_LONG','删除原因不得超过 1000 字符')
 with db.tx() as c:
  sql='SELECT m.* FROM conversation_messages m JOIN conversations v ON v.conversation_id=m.conversation_id AND v.organization_id=m.organization_id AND v.workspace_id=m.workspace_id AND v.team_id=m.team_id WHERE m.message_id=? AND m.organization_id=? AND m.workspace_id=? AND m.team_id=? AND m.deleted_at IS NULL'
  params=[message_id]+list(_scope(a))
  if a.get('_conversation_access')=='self':sql+=' AND v.assigned_user_id=?';params.append(a['user_id'])
  m=c.execute(sql,tuple(params)).fetchone()
  if not m:return err('MESSAGE_SCOPE_INVALID','消息不存在或无权访问',404)
  if m['content_deleted_at'] is not None:return err('CONTENT_ALREADY_DELETED','消息正文已经删除',409)
  n=now_ms();updated=c.execute("UPDATE conversation_messages SET text_content=NULL,redacted_text=NULL,status='content_deleted',content_deleted_at=?,content_deleted_by=?,content_delete_reason=? WHERE message_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND deleted_at IS NULL AND content_deleted_at IS NULL",(n,a['user_id'],reason,message_id)+_scope(a))
  if updated.rowcount!=1:return err('CONTENT_DELETE_CONFLICT','消息状态已变化，请刷新后重试',409)
  write_audit(c,a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'],'message.delete.content','message',message_id,before={'hadText':m['text_content'] is not None},after={'status':'content_deleted'},reason=reason,device_id=a.get('device_id'))
 return {'ok':True,'messageId':message_id,'contentDeletedAt':n},200

# Schema 222 management-center query overrides.
def list_conversations(db,a,args=None):
 """Return scoped conversations with the effective contact device and filter facets.

 The device is defined by contacts.last_observed_device_id -> devices.device_id.
 Do not require the device's current team to equal the conversation team: Schema 221
 can expose a contact to another team through contact_team_access while preserving
 the device's original assignment.
 """
 args=args or {}
 try:
  size=valid_limit(_value(args.get('limit')),50,200)
  status_value=str(_value(args.get('status')) or '').strip()
  if status_value and status_value not in ('active','closed','archived'):raise ValidationError('INVALID_ENUM','status 无效','status')
  direction=str(_value(args.get('direction')) or '').strip()
  if direction and direction not in ('inbound','outbound','system'):raise ValidationError('INVALID_ENUM','direction 无效','direction')
  started_from=int(_value(args.get('startedFrom') or args.get('started_from'))) if _value(args.get('startedFrom') or args.get('started_from')) not in (None,'') else None
  started_to=int(_value(args.get('startedTo') or args.get('started_to'))) if _value(args.get('startedTo') or args.get('started_to')) not in (None,'') else None
  active_from=int(_value(args.get('activeFrom') or args.get('active_from'))) if _value(args.get('activeFrom') or args.get('active_from')) not in (None,'') else None
  active_to=int(_value(args.get('activeTo') or args.get('active_to'))) if _value(args.get('activeTo') or args.get('active_to')) not in (None,'') else None
  cursor=_value(args.get('cursor'));point=decode_cursor(cursor,'conversation') if cursor else None
 except ValidationError as e:return err(e.code,str(e),400,field=e.field)
 except (TypeError,ValueError):return err('INVALID_TIME_RANGE','时间筛选必须是毫秒时间戳')
 scope_where=['v.organization_id=?','v.workspace_id=?','v.team_id=?'];scope_params=list(_scope(a))
 if a.get('_conversation_access')=='self':scope_where.append('v.assigned_user_id=?');scope_params.append(a['user_id'])
 where=list(scope_where);params=list(scope_params)
 if status_value:where.append('v.status=?');params.append(status_value)
 values=(
  (('platformId','platform_id'),'v.platform_id'),
  (('channelAccountId','channel_account_id'),'v.channel_account_id'),
  (('contactId','contact_id'),'v.contact_id'),
  (('assignedUserId','assigned_user_id'),'v.assigned_user_id'),
  (('contentType','content_type'),'v.last_message_type'))
 filters={}
 for keys,col in values:
  value=str(_value(next((args.get(k) for k in keys if args.get(k) not in (None,'')),'')) or '').strip()
  filters[keys[0]]=value
  if value:where.append(col+'=?');params.append(value)
 keyword=str(_value(args.get('keyword') or args.get('q')) or '').strip()
 if len(keyword)>120:return err('KEYWORD_TOO_LONG','搜索关键词不得超过 120 字符',400,field='keyword')
 email_expr="CASE WHEN json_valid(COALESCE(ct.observed_json,'{}')) THEN COALESCE(NULLIF(json_extract(ct.observed_json,'$.email'),''),NULLIF(json_extract(ct.observed_json,'$.emailAddress'),''),'') ELSE '' END"
 if keyword:
  where.append("(v.conversation_id LIKE ? OR v.external_conversation_id LIKE ? OR v.last_message_preview LIKE ? OR ct.display_name LIKE ? OR ct.manual_name LIKE ? OR COALESCE(NULLIF(ct.manual_phone,''),NULLIF(ct.observed_phone,''),'') LIKE ? OR "+email_expr+" LIKE ? OR ca.display_name LIKE ?)")
  params.extend(['%'+keyword+'%']*8)
 if direction:where.append('v.last_message_direction=?');params.append(direction)
 # conversations has first_message_at, not the non-existent started_at column.
 for value,op,col in ((started_from,'>=','v.first_message_at'),(started_to,'<=','v.first_message_at'),(active_from,'>=','COALESCE(v.last_message_at,0)'),(active_to,'<=','COALESCE(v.last_message_at,0)')):
  if value is not None:where.append(col+op+'?');params.append(value)
 if point:where.append('(COALESCE(v.last_message_at,0)<? OR (COALESCE(v.last_message_at,0)=? AND v.conversation_id<?))');params.extend((point[0],point[0],point[1]))
 sql="""SELECT COALESCE(mc.message_count,0) message_count,COALESCE(mc.inbound_count,0) inbound_count,COALESCE(mc.outbound_count,0) outbound_count,
  v.*,COALESCE(NULLIF(ct.manual_name,''),NULLIF(ct.display_name,''),v.contact_id) contact_name,
  ct.manual_name manual_contact_name,ct.display_name observed_contact_name,ct.avatar_url contact_avatar_url,
  (SELECT COUNT(*) FROM contact_identities ci WHERE ci.contact_id=v.contact_id) contact_identity_count,
  COALESCE(NULLIF(ct.manual_phone,''),NULLIF(ct.observed_phone,''),'') contact_phone,"""+email_expr+""" contact_email,
  p.platform_name,p.platform_code,p.platform_abbr,ca.display_name channel_account_name,u.display_name assigned_user_name,
  d.device_id,COALESCE(NULLIF(d.admin_device_name,''),NULLIF(d.user_device_alias,''),NULLIF(d.system_device_name,''),NULLIF(d.device_name,''),d.device_id) device_name,
  COALESCE(NULLIF(json_extract(d.metadata_json,'$.color'),''),'#64748b') device_color
  FROM conversations v
  LEFT JOIN contacts ct ON ct.contact_id=v.contact_id AND ct.organization_id=v.organization_id AND ct.workspace_id=v.workspace_id
  LEFT JOIN platforms p ON p.platform_id=v.platform_id
  LEFT JOIN channel_accounts ca ON ca.channel_account_id=v.channel_account_id AND ca.organization_id=v.organization_id
  LEFT JOIN users u ON u.user_id=v.assigned_user_id AND u.organization_id=v.organization_id
  LEFT JOIN devices d ON d.device_id=ct.last_observed_device_id AND d.organization_id=v.organization_id AND d.workspace_id=v.workspace_id
  LEFT JOIN (SELECT conversation_id,COUNT(*) message_count,SUM(CASE WHEN direction='inbound' THEN 1 ELSE 0 END) inbound_count,SUM(CASE WHEN direction='outbound' THEN 1 ELSE 0 END) outbound_count FROM conversation_messages WHERE deleted_at IS NULL GROUP BY conversation_id) mc ON mc.conversation_id=v.conversation_id
  WHERE """+' AND '.join(where)+' ORDER BY COALESCE(v.last_message_at,0) DESC,v.conversation_id DESC LIMIT ?'
 facet_where=' AND '.join(x.replace('v.','fv.') for x in scope_where)
 with db.tx(False) as c:
  rows=c.execute(sql,tuple(params+[size+1])).fetchall()
  # Facets are based on conversations visible in the authorized scope, not on
  # channel_accounts columns (channel_accounts has no workspace_id/team_id).
  option_devices=c.execute("""SELECT DISTINCT d.device_id,
   COALESCE(NULLIF(d.admin_device_name,''),NULLIF(d.user_device_alias,''),NULLIF(d.system_device_name,''),NULLIF(d.device_name,''),d.device_id) device_name,
   COALESCE(NULLIF(json_extract(d.metadata_json,'$.color'),''),'#64748b') device_color
   FROM conversations fv
   JOIN contacts fc ON fc.contact_id=fv.contact_id AND fc.organization_id=fv.organization_id AND fc.workspace_id=fv.workspace_id
   JOIN devices d ON d.device_id=fc.last_observed_device_id AND d.organization_id=fv.organization_id AND d.workspace_id=fv.workspace_id
   WHERE """+facet_where+" ORDER BY device_name COLLATE NOCASE,d.device_id",tuple(scope_params)).fetchall()
  option_platforms=c.execute("""SELECT DISTINCT p.platform_id,p.platform_code,p.platform_abbr,p.platform_name
   FROM conversations fv JOIN platforms p ON p.platform_id=fv.platform_id
   WHERE """+facet_where+" AND p.status='active' ORDER BY p.platform_name COLLATE NOCASE,p.platform_id",tuple(scope_params)).fetchall()
 has_more=len(rows)>size;rows=rows[:size];items=[]
 for row in rows:
  item=_conversation_joined_public(row)
  item.update({'contact':{'contactId':row['contact_id'],'displayName':row['contact_name'],'manualName':row['manual_contact_name'] or '','observedName':row['observed_contact_name'] or '','phone':row['contact_phone'],'email':row['contact_email'],'avatarUrl':row['contact_avatar_url'] or '','identityCount':int(row['contact_identity_count'] or 0)},
   'platform':{'platformId':row['platform_id'],'code':row['platform_code'],'abbr':row['platform_abbr'],'name':row['platform_name']},
   'channelAccount':{'channelAccountId':row['channel_account_id'],'name':row['channel_account_name']},
   'assignedUser':{'userId':row['assigned_user_id'],'name':row['assigned_user_name']},
   'device':({'id':row['device_id'],'name':row['device_name'],'color':row['device_color']} if row['device_id'] else None)})
  items.append(item)
 next_cursor=encode_cursor(rows[-1]['last_message_at'] or 0,rows[-1]['conversation_id'],'conversation') if has_more and rows else None
 return {'ok':True,'items':items,'availableDevices':[dict(x) for x in option_devices],'availablePlatforms':[dict(x) for x in option_platforms],
  'nextCursor':next_cursor,'hasMore':has_more,'filtersApplied':{'keyword':keyword,'platformId':filters.get('platformId',''),'channelAccountId':filters.get('channelAccountId',''),'contactId':filters.get('contactId',''),'assignedUserId':filters.get('assignedUserId',''),'status':status_value,'direction':direction}},200

def get_conversation(db,a,conversation_id):
 with db.tx(False) as c:
  r=_conversation(c,a,conversation_id)
  if not r:return err('CONVERSATION_SCOPE_INVALID','会话不存在或无权访问',404)
  contact=c.execute("SELECT contact_id,display_name,manual_name,COALESCE(NULLIF(manual_phone,''),NULLIF(observed_phone,''),'') phone,CASE WHEN json_valid(COALESCE(observed_json,'{}')) THEN COALESCE(NULLIF(json_extract(observed_json,'$.email'),''),NULLIF(json_extract(observed_json,'$.emailAddress'),''),'') ELSE '' END email,avatar_url,remark,status,business_json,last_seen_at FROM contacts WHERE contact_id=?",(r['contact_id'],)).fetchone()
  identities=c.execute('SELECT contact_identity_id,platform_id,identity_type,identity_value,verification_status,is_primary,last_seen_at FROM contact_identities WHERE contact_id=? AND organization_id=? AND workspace_id=? ORDER BY is_primary DESC,last_seen_at DESC',(r['contact_id'],a['organization_id'],a['workspace_id'])).fetchall()
  platform=c.execute('SELECT platform_id,platform_code,platform_name,platform_kind FROM platforms WHERE platform_id=?',(r['platform_id'],)).fetchone()
  account=c.execute('SELECT channel_account_id,display_name,status,platform_id FROM channel_accounts WHERE channel_account_id=?',(r['channel_account_id'],)).fetchone()
  assigned=c.execute('SELECT user_id,display_name,login_name,status FROM users WHERE user_id=?',(r['assigned_user_id'],)).fetchone() if r['assigned_user_id'] else None
  transfers=c.execute("SELECT transfer_id,status,contact_id,from_channel_account_id,from_conversation_id,from_platform_id,to_channel_account_id,to_conversation_id,to_platform_id,transfer_method,requested_by,requested_at,accepted_by,accepted_at,rejected_by,rejected_at,cancelled_by,cancelled_at,failed_at,expired_at,expires_at,reason,rejection_reason,failure_code,failure_reason,matched_identity_id,match_confidence,version,created_at,updated_at FROM contact_transfers WHERE organization_id=? AND workspace_id=? AND team_id=? AND (from_conversation_id=? OR to_conversation_id=?) ORDER BY requested_at DESC LIMIT 50",_scope(a)+(conversation_id,conversation_id)).fetchall()
  counts=c.execute("SELECT COUNT(*) message_count,SUM(CASE WHEN direction='inbound' THEN 1 ELSE 0 END) inbound_count,SUM(CASE WHEN direction='outbound' THEN 1 ELSE 0 END) outbound_count FROM conversation_messages WHERE conversation_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND deleted_at IS NULL",(conversation_id,)+_scope(a)).fetchone()
 conversation=_conversation_public(r)
 conversation.update({'message_count':int(counts['message_count'] or 0),'inbound_count':int(counts['inbound_count'] or 0),'outbound_count':int(counts['outbound_count'] or 0)})
 return {'ok':True,'conversation':conversation,'contact':dict(contact) if contact else None,'identities':[dict(x) for x in identities],'platform':dict(platform) if platform else None,'channelAccount':dict(account) if account else None,'assignedUser':dict(assigned) if assigned else None,'transfers':[dict(x) for x in transfers]},200

def list_messages(db,a,conversation_id,limit=100,before=None,allow_raw=False,cursor=None,direction=None,content_type=None):
 """Return newest-first by authoritative message time.

 platformOrder is only a capture-snapshot ordinal and is allowed to restart when
 Meta virtualises/reloads the pane.  It must therefore never be the primary
 database sort key.  occurred_at matches the date groups shown by the platform;
 collected_at is used only for genuinely unresolved legacy timestamps.
 """
 try:
  size=valid_limit(_value(limit),100,500);cursor=_value(cursor)
  point=decode_cursor(cursor,'message-time-v2') if cursor else None
  direction=str(_value(direction) or '').strip();content_type=str(_value(content_type) or '').strip()
  if direction and direction not in ('inbound','outbound','system'):raise ValidationError('INVALID_ENUM','direction 无效','direction')
  if not point and before not in (None,''):point=(int(_value(before)),'~')
 except ValidationError as e:return err(e.code,str(e),400,field=e.field)
 except (TypeError,ValueError):return err('INVALID_BEFORE','before 必须是非负消息时间',400)
 with db.tx(bool(allow_raw)) as c:
  if not _conversation(c,a,conversation_id):return err('CONVERSATION_SCOPE_INVALID','会话不存在或无权访问',404)
  effective_expr='COALESCE(m.occurred_at,m.collected_at)'
  platform_expr="CASE WHEN json_valid(m.metadata_json) THEN CAST(json_extract(m.metadata_json,'$.platformOrder') AS INTEGER) END"
  chronology_expr="CASE WHEN json_valid(m.metadata_json) THEN COALESCE(CAST(json_extract(m.metadata_json,'$.chronologyOrdinal') AS INTEGER),0) ELSE 0 END"
  where=['m.conversation_id=?','m.organization_id=?','m.workspace_id=?','m.team_id=?','m.deleted_at IS NULL',IG_UNRESOLVED_NOISE_FILTER];params=[conversation_id]+list(_scope(a))
  if direction:where.append('m.direction=?');params.append(direction)
  if content_type:where.append('m.content_type=?');params.append(content_type)
  if point:where.append('('+effective_expr+'<? OR ('+effective_expr+'=? AND m.message_id<?))');params.extend((point[0],point[0],point[1]))
  cols='m.message_id,m.conversation_id,m.direction,m.sender_type,m.content_type,m.text_content,m.redacted_text,m.occurred_at,m.collected_at,m.edited_at,m.status,m.content_deleted_at,m.reply_to_message_id,m.attachment_count,m.has_sensitive_content,m.metadata_json,'+platform_expr+' platform_order,'+effective_expr+' effective_order_time,'+chronology_expr+' chronology_ordinal'
  rows=c.execute('SELECT '+cols+' FROM conversation_messages m WHERE '+' AND '.join(where)+' ORDER BY '+effective_expr+' DESC,COALESCE('+platform_expr+',0) DESC,'+chronology_expr+' DESC,m.collected_at DESC,m.message_id DESC LIMIT ?',tuple(params+[size+1])).fetchall();has_more=len(rows)>size;rows=rows[:size]
  if allow_raw:write_audit(c,a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'],'message.read.raw','conversation',conversation_id,after={'returnedCount':len(rows)},reason='查看消息原文',device_id=a.get('device_id'))
 next_cursor=encode_cursor(rows[-1]['effective_order_time'],rows[-1]['message_id'],'message-time-v2') if has_more and rows else None
 items=[dict(public_message(x,allow_raw),eventType='message',platformOrder=x['platform_order'],effectiveTime=x['occurred_at'],orderTime=x['effective_order_time'],orderBasis='occurredAt' if x['occurred_at'] is not None else 'collectedAt',chronologyOrdinal=x['chronology_ordinal']) for x in rows]
 translated=sum(bool((x.get('metadata') or {}).get('translation',{}).get('text')) for x in items)
 import hashlib
 LOG.info('WA_TRANSLATION_API_DIAGNOSTIC version=210.2.75 conversation=%s returned=%d translated=%d rawAllowed=%s',hashlib.sha256(str(conversation_id).encode()).hexdigest()[:12],len(items),translated,bool(allow_raw))
 return {'ok':True,'items':items,'nextCursor':next_cursor,'hasMore':has_more,'ordering':'occurred_at_platform_order_desc','translationDiagnostics':{'version':'210.2.63','returnedMessages':len(items),'translatedMessages':translated,'permissionMode':'raw' if allow_raw else 'redacted'}},200

def list_contact_timeline(db,a,contact_id,args=None,allow_raw=False):
 args=args or {}
 try:
  size=valid_limit(_value(args.get('limit')),100,500);cursor=_value(args.get('cursor'));point=decode_cursor(cursor,'contact-timeline') if cursor else None
  platform=str(_value(args.get('platformId')) or '').strip();account=str(_value(args.get('channelAccountId')) or '').strip();direction=str(_value(args.get('direction')) or '').strip();event_type=str(_value(args.get('eventType')) or '').strip()
  started_from=int(_value(args.get('startedFrom'))) if _value(args.get('startedFrom')) not in (None,'') else None;started_to=int(_value(args.get('startedTo'))) if _value(args.get('startedTo')) not in (None,'') else None
  if event_type and event_type not in ('message','transfer'):raise ValidationError('INVALID_ENUM','eventType 无效','eventType')
 except ValidationError as e:return err(e.code,str(e),400,field=e.field)
 except (TypeError,ValueError):return err('INVALID_TIME_RANGE','时间筛选必须是毫秒时间戳')
 with db.tx(bool(allow_raw)) as c:
  if not c.execute('SELECT 1 FROM contacts WHERE contact_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND deleted_at IS NULL',(contact_id,)+_scope(a)).fetchone():return err('CONTACT_SCOPE_INVALID','客户不存在或无权访问',404)
  items=[]
  if event_type in ('','message'):
   w=['m.contact_id=?','m.organization_id=?','m.workspace_id=?','m.team_id=?','m.deleted_at IS NULL'];p=[contact_id]+list(_scope(a))
   if a.get('_conversation_access')=='self':w.append('v.assigned_user_id=?');p.append(a['user_id'])
   for val,col in ((platform,'v.platform_id'),(account,'v.channel_account_id'),(direction,'m.direction')):
    if val:w.append(col+'=?');p.append(val)
   if started_from is not None:w.append('m.occurred_at>=?');p.append(started_from)
   if started_to is not None:w.append('m.occurred_at<=?');p.append(started_to)
   rows=c.execute('SELECT m.*,v.platform_id,v.channel_account_id,v.assigned_user_id FROM conversation_messages m JOIN conversations v ON v.conversation_id=m.conversation_id WHERE '+' AND '.join(w),tuple(p)).fetchall()
   for r in rows:
    t=r['occurred_at']
    if t is None:continue
    x=public_message(r,allow_raw);x.update({'eventType':'message','effectiveTime':t,'eventId':r['message_id'],'platformId':r['platform_id'],'channelAccountId':r['channel_account_id'],'assignedUserId':r['assigned_user_id']});items.append(x)
  if event_type in ('','transfer') and not direction:
   w=['e.contact_id=?','e.organization_id=?','e.workspace_id=?','e.team_id=?'];p=[contact_id]+list(_scope(a))
   if platform:w.append('(t.from_platform_id=? OR t.to_platform_id=?)');p.extend((platform,platform))
   if account:w.append('(e.channel_account_id=? OR t.from_channel_account_id=? OR t.to_channel_account_id=?)');p.extend((account,account,account))
   if started_from is not None:w.append('e.created_at>=?');p.append(started_from)
   if started_to is not None:w.append('e.created_at<=?');p.append(started_to)
   rows=c.execute('SELECT e.*,t.from_platform_id,t.to_platform_id,t.from_channel_account_id,t.to_channel_account_id FROM contact_transfer_events e JOIN contact_transfers t ON t.transfer_id=e.transfer_id WHERE '+' AND '.join(w),tuple(p)).fetchall()
   for r in rows:items.append({'eventType':'transfer','eventId':r['event_id'],'effectiveTime':r['created_at'],'transferId':r['transfer_id'],'transferEventType':r['event_type'],'fromStatus':r['from_status'],'toStatus':r['to_status'],'actorId':r['actor_id'],'conversationId':r['conversation_id'],'channelAccountId':r['channel_account_id'],'fromPlatformId':r['from_platform_id'],'toPlatformId':r['to_platform_id'],'reason':r['reason']})
  items.sort(key=lambda x:(int(x.get('effectiveTime') or 0),str(x.get('eventId') or '')),reverse=True)
  if point:items=[x for x in items if (int(x.get('effectiveTime') or 0),str(x.get('eventId') or ''))<(point[0],point[1])]
  has_more=len(items)>size;items=items[:size];next_cursor=encode_cursor(items[-1]['effectiveTime'],items[-1]['eventId'],'contact-timeline') if has_more and items else None
  if allow_raw:write_audit(c,a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'],'message.read.raw','contact',contact_id,after={'returnedCount':len(items)},reason='查看客户连续时间线原文',device_id=a.get('device_id'))
 return {'ok':True,'contactId':contact_id,'items':items,'nextCursor':next_cursor,'hasMore':has_more},200


def recollect_conversation(db,a,conversation_id,payload):
 """Physically clear one scoped conversation so stable platform IDs can be collected again."""
 if not isinstance(payload,dict):return err('INVALID_BODY','请求正文必须是对象',400)
 reason='管理员确认删除消息并重新采集'
 try:base_version=int(payload.get('baseVersion'))
 except (TypeError,ValueError):return err('BASE_VERSION_REQUIRED','必须提供有效的会话版本',400)
 with db.tx() as c:
  row=_conversation(c,a,conversation_id)
  if not row:return err('CONVERSATION_NOT_FOUND','会话不存在或不在授权范围',404)
  if int(row['version'] or 1)!=base_version:return err('VERSION_CONFLICT','会话已被其他操作更新，请刷新后重试',409,currentVersion=int(row['version'] or 1))
  summary=c.execute("""SELECT COUNT(*) total,SUM(CASE WHEN direction='inbound' THEN 1 ELSE 0 END) inbound,
   SUM(CASE WHEN direction='outbound' THEN 1 ELSE 0 END) outbound,
   MIN(occurred_at) first_at,MAX(occurred_at) last_at
   FROM conversation_messages WHERE conversation_id=? AND organization_id=? AND workspace_id=? AND team_id=?""",
   (conversation_id,a['organization_id'],a['workspace_id'],a['team_id'])).fetchone()
  try:meta=__import__('json').loads(row['metadata_json'] or '{}')
  except Exception:meta={}
  previous=max(1,int(meta.get('collectionGeneration') or 1));generation=previous+1;n=now_ms()
  meta.update({'collectionGeneration':generation,'recollectRequestedAt':n,'recollectRequestedBy':a['user_id']})
  meta.pop('awaitingReply',None)
  deleted=c.execute('DELETE FROM conversation_messages WHERE conversation_id=? AND organization_id=? AND workspace_id=? AND team_id=?',(conversation_id,a['organization_id'],a['workspace_id'],a['team_id'])).rowcount
  c.execute("""UPDATE conversations SET first_message_at=NULL,last_message_at=NULL,last_collected_at=NULL,last_message_id=NULL,
   last_message_direction=NULL,last_message_type=NULL,last_message_preview='',message_count=0,inbound_count=0,outbound_count=0,
   metadata_json=?,version=version+1,updated_at=? WHERE conversation_id=? AND organization_id=? AND workspace_id=? AND team_id=?""",
   (dumps(meta),n,conversation_id,a['organization_id'],a['workspace_id'],a['team_id']))
  audit={'deletedCount':int(deleted),'inboundCount':int(summary['inbound'] or 0),'outboundCount':int(summary['outbound'] or 0),
   'firstMessageAt':summary['first_at'],'lastMessageAt':summary['last_at'],'previousGeneration':previous,
   'collectionGeneration':generation,'channelAccountId':row['channel_account_id'],'platformId':row['platform_id']}
  write_audit(c,a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'],'conversation.messages.recollect','conversation',conversation_id,before={'messageCount':int(summary['total'] or 0),'collectionGeneration':previous},after=audit,reason=reason,device_id=a.get('device_id'))
  return {'ok':True,'conversationId':conversation_id,'deletedCount':int(deleted),'previousGeneration':previous,'collectionGeneration':generation,'version':base_version+1},200
