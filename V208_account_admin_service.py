# -*- coding: utf-8 -*-
"""Schema 214 administration for account binding slots and identity discoveries."""
import sqlite3, uuid
from V207_shared_db import now_ms, dumps

class AccountAdminError(Exception):
 def __init__(self,code,message,status=400):
  super().__init__(message); self.code=code; self.message=message; self.status=status

def _one(c,sql,args=()):
 r=c.execute(sql,args).fetchone(); return dict(r) if r else None

def _rows(c,sql,args=()): return [dict(r) for r in c.execute(sql,args)]
def _text(v): return str(v or '').strip()
def _send_error(h,e): return h.sendj({'ok':False,'code':e.code,'message':e.message},e.status) or True

def _audit(c,a,org,workspace,team,operation,entity_type,entity_id,before,after,reason=None):
 c.execute("""INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at,organization_id,team_id,scope_type,scope_id)
 VALUES(?,?,NULL,?,?,?,?,?,?,?,?,?,'team',?)""",
  (workspace,a['user_id'],operation,entity_type,entity_id,dumps(before or {}),dumps(after or {}),reason,now_ms(),org,team,team))

def _scope(c,org,workspace,team,user,platform):
 if not c.execute("SELECT 1 FROM workspaces WHERE workspace_id=? AND organization_id=? AND status='active'",(workspace,org)).fetchone(): raise AccountAdminError('WORKSPACE_INVALID','工作区不存在或已禁用')
 if not c.execute("SELECT 1 FROM teams WHERE team_id=? AND organization_id=? AND status='active'",(team,org)).fetchone(): raise AccountAdminError('TEAM_INVALID','团队不存在或已禁用')
 if not c.execute("SELECT 1 FROM workspace_teams WHERE workspace_id=? AND team_id=? AND organization_id=? AND status='active'",(workspace,team,org)).fetchone(): raise AccountAdminError('SCOPE_INVALID','团队不属于该工作区')
 if not c.execute("SELECT 1 FROM users WHERE user_id=? AND organization_id=? AND status='active'",(user,org)).fetchone(): raise AccountAdminError('USER_INVALID','用户不存在或已禁用')
 if not c.execute("SELECT 1 FROM team_memberships WHERE user_id=? AND team_id=? AND status='active'",(user,team)).fetchone(): raise AccountAdminError('MEMBERSHIP_INVALID','用户不是该团队的有效成员')
 if not c.execute("SELECT 1 FROM platforms WHERE platform_id=? AND status='active'",(platform,)).fetchone(): raise AccountAdminError('PLATFORM_INVALID','平台不存在或已禁用')

def _account(c,org,platform,aid):
 r=_one(c,"SELECT * FROM channel_accounts WHERE channel_account_id=? AND organization_id=? AND platform_id=? AND status='active' AND collection_enabled=1",(aid,org,platform))
 if not r: raise AccountAdminError('CHANNEL_ACCOUNT_INVALID','渠道账号不存在、平台不匹配或采集已禁用')
 return r

def _slot_detail(c,org,sid):
 return _one(c,"""SELECT s.*,p.platform_code,p.platform_name,ca.display_name channel_account_name,u.display_name user_name,t.name team_name,w.name workspace_name
 FROM account_binding_slots s JOIN platforms p ON p.platform_id=s.platform_id JOIN users u ON u.user_id=s.user_id
 JOIN teams t ON t.team_id=s.team_id JOIN workspaces w ON w.workspace_id=s.workspace_id
 LEFT JOIN channel_accounts ca ON ca.channel_account_id=s.channel_account_id WHERE s.organization_id=? AND s.slot_id=?""",(org,sid))

def _enrich_discovery_matches(c,org,items):
 # Resolve the whole page in one query. Never infer identities from display text.
 for item in items:
  item['recommended_account_id']=None;item['recommended_account_name']=None
  if item.get('channel_account_id'):
   item['match_status']='assigned';item['match_reason']='discovery_already_has_account'
 pending=[i for i in items if not i.get('channel_account_id')]
 keys=list(dict.fromkeys((i.get('platform_id'),i.get('identity_type'),i.get('canonical_value')) for i in pending))
 matches={k:[] for k in keys}
 if keys:
  clauses=[];args=[org]
  for platform,identity_type,canonical in keys:
   clauses.append('(i.platform_id=? AND i.identity_type=? AND i.canonical_value=?)')
   args.extend([platform,identity_type,canonical])
  rows=_rows(c,"SELECT i.platform_id,i.identity_type,i.canonical_value,ca.channel_account_id,ca.display_name,i.is_primary,i.valid_from FROM channel_account_identities i JOIN channel_accounts ca ON ca.channel_account_id=i.channel_account_id WHERE ca.organization_id=? AND ca.status='active' AND i.status='active' AND ca.platform_id=i.platform_id AND ("+' OR '.join(clauses)+") ORDER BY i.is_primary DESC,i.valid_from DESC",args)
  for row in rows:
   key=(row['platform_id'],row['identity_type'],row['canonical_value'])
   if row['channel_account_id'] not in {x['channel_account_id'] for x in matches[key]}:matches[key].append(row)
 for item in pending:
  found=matches.get((item.get('platform_id'),item.get('identity_type'),item.get('canonical_value')),[])
  if len(found)==1:
   item['match_status']='exact_match';item['match_reason']='tenant_platform_canonical_identity_exact';item['recommended_account_id']=found[0]['channel_account_id'];item['recommended_account_name']=found[0]['display_name']
  elif len(found)>1:
   item['match_status']='conflict';item['match_reason']='multiple_tenant_exact_identity_matches'
  else:item['match_status']='unbound';item['match_reason']='no_tenant_exact_identity_match'
 return items

def _discovery_detail(c,org,did):
 item=_one(c,"SELECT d.*,p.platform_code,p.platform_name,ca.display_name channel_account_name,u.display_name user_name,t.name team_name,w.name workspace_name FROM account_identity_discoveries d JOIN platforms p ON p.platform_id=d.platform_id JOIN users u ON u.user_id=d.user_id JOIN teams t ON t.team_id=d.team_id JOIN workspaces w ON w.workspace_id=d.workspace_id LEFT JOIN channel_accounts ca ON ca.channel_account_id=d.channel_account_id WHERE d.organization_id=? AND d.discovery_id=?",(org,did))
 return _enrich_discovery_matches(c,org,[item])[0] if item else None

def create_slot(db,a,org,b):
 workspace=_text(b.get('workspaceId')); team=_text(b.get('teamId')); user=_text(b.get('userId')); platform=_text(b.get('platformId'))
 aid=_text(b.get('channelAccountId')) or None; policy=_text(b.get('claimPolicy') or 'auto')
 if policy not in ('auto','approval'): raise AccountAdminError('CLAIM_POLICY_INVALID','claimPolicy 只能是 auto 或 approval')
 if policy=='auto' and not aid: raise AccountAdminError('CHANNEL_ACCOUNT_REQUIRED','auto 槽位必须指定渠道账号')
 n=now_ms(); sid='abs_'+uuid.uuid4().hex
 try:
  with db.tx() as c:
   _scope(c,org,workspace,team,user,platform)
   if aid:_account(c,org,platform,aid)
   c.execute("""INSERT INTO account_binding_slots(slot_id,organization_id,workspace_id,team_id,user_id,platform_id,channel_account_id,expected_phone,expected_username,claim_policy,status,created_by,created_at,updated_at,reason)
   VALUES(?,?,?,?,?,?,?,?,?,?,'pending',?,?,?,?)""",(sid,org,workspace,team,user,platform,aid,_text(b.get('expectedPhone')) or None,_text(b.get('expectedUsername')) or None,policy,a['user_id'],n,n,_text(b.get('reason')) or None))
   after=_slot_detail(c,org,sid); _audit(c,a,org,workspace,team,'create','account_binding_slot',sid,{},after,_text(b.get('reason')) or None)
  return after
 except sqlite3.IntegrityError as e:
  if 'uq_binding_slot_active_user_platform' in str(e) or 'UNIQUE constraint failed' in str(e): raise AccountAdminError('BINDING_SLOT_CONFLICT','该用户在此平台已有 pending 槽位',409)
  raise

def patch_slot(db,a,org,sid,b):
 allowed={'channelAccountId','expectedPhone','expectedUsername','claimPolicy','reason','status'}
 if not any(k in b for k in allowed): raise AccountAdminError('NO_CHANGES','没有可更新字段')
 with db.tx() as c:
  before=_slot_detail(c,org,sid)
  if not before: raise AccountAdminError('BINDING_SLOT_NOT_FOUND','槽位不存在',404)
  if before['status']!='pending': raise AccountAdminError('BINDING_SLOT_STATE_CONFLICT','只有 pending 槽位可以修改',409)
  status=_text(b.get('status') or 'pending')
  if status not in ('pending','disabled'): raise AccountAdminError('BINDING_SLOT_STATE_INVALID','只能将 pending 槽位置为 disabled')
  aid=(_text(b.get('channelAccountId')) or None) if 'channelAccountId' in b else before['channel_account_id']
  policy=_text(b.get('claimPolicy') or before['claim_policy'])
  if policy not in ('auto','approval'): raise AccountAdminError('CLAIM_POLICY_INVALID','claimPolicy 只能是 auto 或 approval')
  if policy=='auto' and not aid: raise AccountAdminError('CHANNEL_ACCOUNT_REQUIRED','auto 槽位必须指定渠道账号')
  if aid:_account(c,org,before['platform_id'],aid)
  n=now_ms(); disabled=status=='disabled'
  changed=c.execute("""UPDATE account_binding_slots SET channel_account_id=?,expected_phone=?,expected_username=?,claim_policy=?,status=?,reason=?,updated_at=?,disabled_at=?,disabled_by=?
   WHERE slot_id=? AND organization_id=? AND status='pending'""",(aid,(_text(b.get('expectedPhone')) or None) if 'expectedPhone' in b else before['expected_phone'],(_text(b.get('expectedUsername')) or None) if 'expectedUsername' in b else before['expected_username'],policy,status,(_text(b.get('reason')) or None) if 'reason' in b else before['reason'],n,n if disabled else None,a['user_id'] if disabled else None,sid,org)).rowcount
  if changed!=1: raise AccountAdminError('BINDING_SLOT_STATE_CONFLICT','槽位已被并发处理',409)
  after=_slot_detail(c,org,sid); _audit(c,a,org,before['workspace_id'],before['team_id'],'disable' if disabled else 'update','account_binding_slot',sid,before,after,_text(b.get('reason')) or None)
 return after

def _identity_conflict(c,org,before,aid=None):
 """Identity uniqueness is tenant-scoped; the same external ID may exist in another organization."""
 sql="""SELECT i.channel_account_id FROM channel_account_identities i
 JOIN channel_accounts ca ON ca.channel_account_id=i.channel_account_id
 WHERE ca.organization_id=? AND i.platform_id=? AND i.identity_type=? AND i.canonical_value=? AND i.status='active'"""
 args=[org,before['platform_id'],before['identity_type'],before['canonical_value']]
 if aid:sql+=' AND i.channel_account_id<>?';args.append(aid)
 return _one(c,sql+' LIMIT 1',args)

def _complete_approval(c,a,org,did,before,aid,reason,slot_id=None):
 """Complete identity, authorization, slot claim and discovery resolution in the caller transaction."""
 conflict=_identity_conflict(c,org,before,aid)
 if conflict: raise AccountAdminError('ACCOUNT_IDENTITY_CONFLICT','该身份已归属当前企业的其他渠道账号',409)
 sid=_text(slot_id) or before.get('slot_id'); n=now_ms()
 if sid:
  slot=_one(c,"SELECT * FROM account_binding_slots WHERE slot_id=? AND organization_id=?",(sid,org))
  if not slot: raise AccountAdminError('BINDING_SLOT_NOT_FOUND','审批槽位不存在',404)
  if any(slot[k]!=before[k] for k in ('workspace_id','team_id','user_id','platform_id')): raise AccountAdminError('BINDING_SLOT_SCOPE_CONFLICT','槽位与身份发现范围不一致',409)
  if slot['channel_account_id'] and slot['channel_account_id']!=aid: raise AccountAdminError('BINDING_SLOT_ACCOUNT_CONFLICT','槽位绑定了其他渠道账号',409)
  if slot['status']=='pending':
   changed=c.execute("""UPDATE account_binding_slots SET channel_account_id=?,status='claimed',claimed_identity_type=?,claimed_canonical_value=?,claimed_device_id=?,claimed_at=?,updated_at=? WHERE slot_id=? AND organization_id=? AND status='pending'""",(aid,before['identity_type'],before['canonical_value'],before['device_id'],n,n,sid,org)).rowcount
   if changed!=1: raise AccountAdminError('BINDING_SLOT_STATE_CONFLICT','槽位已被并发处理',409)
  elif not (slot['status']=='claimed' and slot['channel_account_id']==aid and slot['claimed_canonical_value']==before['canonical_value']):
   raise AccountAdminError('BINDING_SLOT_STATE_CONFLICT','审批槽位已被处理',409)
 else:
  sid='abs_'+uuid.uuid4().hex
  c.execute("""INSERT INTO account_binding_slots(slot_id,organization_id,workspace_id,team_id,user_id,platform_id,channel_account_id,claim_policy,status,claimed_identity_type,claimed_canonical_value,claimed_device_id,claimed_at,created_by,created_at,updated_at,reason)
   VALUES(?,?,?,?,?,?,?,'approval','claimed',?,?,?,?,?,?,?,?)""",(sid,org,before['workspace_id'],before['team_id'],before['user_id'],before['platform_id'],aid,before['identity_type'],before['canonical_value'],before['device_id'],n,a['user_id'],n,n,reason or '管理员批准'))
 old=_one(c,"SELECT identity_id FROM channel_account_identities WHERE channel_account_id=? AND identity_type=? AND canonical_value=?",(aid,before['identity_type'],before['canonical_value']))
 if old:c.execute("UPDATE channel_account_identities SET platform_id=?,identity_value=?,status='active',valid_to=NULL WHERE identity_id=?",(before['platform_id'],before['identity_value'],old['identity_id']))
 else:c.execute("""INSERT INTO channel_account_identities(identity_id,channel_account_id,identity_type,identity_value,canonical_value,created_at,platform_id,is_primary,status,valid_from,metadata_json) VALUES(?,?,?,?,?,?,?,1,'active',?,'{}')""",('cai_'+uuid.uuid4().hex,aid,before['identity_type'],before['identity_value'],before['canonical_value'],n,before['platform_id'],n))
 c.execute("INSERT OR IGNORE INTO team_channel_accounts(team_id,channel_account_id,granted_by,granted_at) VALUES(?,?,?,?)",(before['team_id'],aid,a['user_id'],n))
 c.execute("INSERT OR IGNORE INTO user_channel_account_grants(user_id,channel_account_id,permission_scope,granted_by,granted_at) VALUES(?,?,'use',?,?)",(before['user_id'],aid,a['user_id'],n))
 changed=c.execute("""UPDATE account_identity_discoveries SET status='approved',reason_code='admin_approved',slot_id=?,channel_account_id=?,resolved_at=?,resolved_by=?,resolution_reason=? WHERE discovery_id=? AND organization_id=? AND status='pending'""",(sid,aid,n,a['user_id'],reason or 'admin_approved',did,org)).rowcount
 if changed!=1: raise AccountAdminError('DISCOVERY_STATE_CONFLICT','身份发现已被并发处理',409)
 after=_discovery_detail(c,org,did)
 _audit(c,a,org,before['workspace_id'],before['team_id'],'approve','account_identity_discovery',did,before,after,reason or '管理员批准')
 return after

def approve(db,a,org,did,b):
 aid=_text(b.get('channelAccountId')); reason=_text(b.get('reason'))
 if not aid: raise AccountAdminError('CHANNEL_ACCOUNT_REQUIRED','审批必须指定渠道账号')
 with db.tx() as c:
  before=_discovery_detail(c,org,did)
  if not before: raise AccountAdminError('DISCOVERY_NOT_FOUND','身份发现不存在',404)
  if before['status']!='pending': raise AccountAdminError('DISCOVERY_STATE_CONFLICT','身份发现已被处理',409)
  _scope(c,org,before['workspace_id'],before['team_id'],before['user_id'],before['platform_id']); _account(c,org,before['platform_id'],aid)
  return _complete_approval(c,a,org,did,before,aid,reason,b.get('slotId'))

def approve_create(db,a,org,did,b):
 """Atomically create a channel account and approve the discovered identity."""
 name=_text(b.get('displayName')); reason=_text(b.get('reason'))
 account_type=_text(b.get('accountType') or 'chat').lower(); purpose=_text(b.get('businessPurpose') or 'acquisition').lower()
 collection=b.get('collectionEnabled',True)
 if not name: raise AccountAdminError('DISPLAY_NAME_REQUIRED','账号名称不能为空')
 if account_type not in ('chat','internal','login','service','marketing','advertising','attribution'): raise AccountAdminError('INVALID_ACCOUNT_TYPE','账号用途无效')
 if purpose not in ('acquisition','conversion','hybrid'): raise AccountAdminError('INVALID_BUSINESS_PURPOSE','业务目的无效')
 if not isinstance(collection,bool): raise AccountAdminError('INVALID_COLLECTION_ENABLED','采集开关必须是布尔值')
 with db.tx() as c:
  before=_discovery_detail(c,org,did)
  if not before: raise AccountAdminError('DISCOVERY_NOT_FOUND','身份发现不存在',404)
  if before['status']!='pending': raise AccountAdminError('DISCOVERY_STATE_CONFLICT','身份发现已被处理',409)
  _scope(c,org,before['workspace_id'],before['team_id'],before['user_id'],before['platform_id'])
  conflict=_identity_conflict(c,org,before)
  if conflict: raise AccountAdminError('ACCOUNT_IDENTITY_CONFLICT','当前企业已存在使用该身份的渠道账号，请改为绑定已有账号',409)
  platform=_one(c,"SELECT platform_code FROM platforms WHERE platform_id=? AND status='active'",(before['platform_id'],))
  if not platform: raise AccountAdminError('PLATFORM_INVALID','平台不存在或已禁用')
  n=now_ms(); aid='acc_'+uuid.uuid4().hex
  c.execute("""INSERT INTO channel_accounts(channel_account_id,organization_id,channel,display_name,status,created_at,updated_at,platform_id,channel_type_id,account_type,metadata_json,business_purpose,collection_enabled)
   VALUES(?,?,?,?,'active',?,?,?,?,?,'{}',?,?)""",(aid,org,_text(platform['platform_code']).lower(),name,n,n,before['platform_id'],None,account_type,purpose,1 if collection else 0))
  created=_one(c,'SELECT * FROM channel_accounts WHERE channel_account_id=?',(aid,))
  _audit(c,a,org,before['workspace_id'],before['team_id'],'create','channel_account',aid,{},created,reason or '身份审批创建账号')
  after=_complete_approval(c,a,org,did,before,aid,reason,b.get('slotId'))
  after['created_channel_account_id']=aid
  return after

def reject(db,a,org,did,b):
 reason=_text(b.get('reason'))
 if not reason: raise AccountAdminError('REASON_REQUIRED','拒绝原因不能为空')
 with db.tx() as c:
  before=_discovery_detail(c,org,did)
  if not before: raise AccountAdminError('DISCOVERY_NOT_FOUND','身份发现不存在',404)
  if before['status']!='pending': raise AccountAdminError('DISCOVERY_STATE_CONFLICT','身份发现已被处理',409)
  n=now_ms(); changed=c.execute("UPDATE account_identity_discoveries SET status='rejected',reason_code='admin_rejected',resolved_at=?,resolved_by=?,resolution_reason=? WHERE discovery_id=? AND organization_id=? AND status='pending'",(n,a['user_id'],reason,did,org)).rowcount
  if changed!=1: raise AccountAdminError('DISCOVERY_STATE_CONFLICT','身份发现已被并发处理',409)
  after=_discovery_detail(c,org,did); _audit(c,a,org,before['workspace_id'],before['team_id'],'reject','account_identity_discovery',did,before,after,reason)
 return after

def handle(h,m,root,ident,action,q,a,db,authorize,org):
 if root not in ('account-binding-slots','account-identity-discoveries'): return False
 perm='account.read' if m=='GET' else 'account.bind'
 if not authorize(db,a,perm,org): return h.sendj({'ok':False,'code':'FORBIDDEN','message':'无账号管理权限'},403) or True
 try:
  if root=='account-binding-slots':
   if m=='GET' and ident:
    with db.tx(False) as c:r=_slot_detail(c,org,ident)
    if not r:raise AccountAdminError('BINDING_SLOT_NOT_FOUND','槽位不存在',404)
    return h.sendj({'ok':True,'item':r}) or True
   if m=='GET':
    p=max(1,int(q.get('page',1))); size=min(200,max(1,int(q.get('pageSize',q.get('limit',50))))); off=(p-1)*size
    where=['s.organization_id=?']; args=[org]
    for key,col in [('status','s.status'),('workspaceId','s.workspace_id'),('teamId','s.team_id'),('userId','s.user_id'),('platformId','s.platform_id'),('channelAccountId','s.channel_account_id')]:
     if q.get(key):where.append(col+'=?');args.append(str(q[key]))
    w=' AND '.join(where)
    with db.tx(False) as c:
     total=c.execute('SELECT count(*) FROM account_binding_slots s WHERE '+w,args).fetchone()[0]
     items=_rows(c,"""SELECT s.*,p.platform_code,ca.display_name channel_account_name,u.display_name user_name,t.name team_name,w.name workspace_name FROM account_binding_slots s JOIN platforms p ON p.platform_id=s.platform_id JOIN users u ON u.user_id=s.user_id JOIN teams t ON t.team_id=s.team_id JOIN workspaces w ON w.workspace_id=s.workspace_id LEFT JOIN channel_accounts ca ON ca.channel_account_id=s.channel_account_id WHERE """+w+' ORDER BY s.created_at DESC,s.slot_id LIMIT ? OFFSET ?',args+[size,off])
    return h.sendj({'ok':True,'items':items,'pagination':{'page':p,'pageSize':size,'total':total,'pages':(total+size-1)//size}}) or True
   if m=='POST' and not ident:return h.sendj({'ok':True,'item':create_slot(db,a,org,h.body())},201) or True
   if m=='PATCH' and ident:return h.sendj({'ok':True,'item':patch_slot(db,a,org,ident,h.body())}) or True
  else:
   if m=='GET' and ident:
    with db.tx(False) as c:r=_discovery_detail(c,org,ident)
    if not r:raise AccountAdminError('DISCOVERY_NOT_FOUND','身份发现不存在',404)
    return h.sendj({'ok':True,'item':r}) or True
   if m=='GET':
    p=max(1,int(q.get('page',1))); size=min(200,max(1,int(q.get('pageSize',q.get('limit',50))))); off=(p-1)*size
    where=['d.organization_id=?'];args=[org]
    for key,col in [('status','d.status'),('workspaceId','d.workspace_id'),('teamId','d.team_id'),('userId','d.user_id'),('platformId','d.platform_id'),('channelAccountId','d.channel_account_id')]:
     if q.get(key):where.append(col+'=?');args.append(str(q[key]))
    match_status=_text(q.get('matchStatus'))
    match_count="(SELECT count(DISTINCT mca.channel_account_id) FROM channel_account_identities mi JOIN channel_accounts mca ON mca.channel_account_id=mi.channel_account_id WHERE mca.organization_id=d.organization_id AND mca.platform_id=d.platform_id AND mca.status='active' AND mi.platform_id=d.platform_id AND mi.identity_type=d.identity_type AND mi.canonical_value=d.canonical_value AND mi.status='active')"
    if match_status=='unbound':where.extend(["d.status='pending'",'d.channel_account_id IS NULL',match_count+'=0'])
    elif match_status=='exact_match':where.extend(["d.status='pending'",'d.channel_account_id IS NULL',match_count+'=1'])
    elif match_status=='conflict':where.extend(["d.status='pending'",'d.channel_account_id IS NULL',match_count+'>1'])
    elif match_status=='assigned':where.append('d.channel_account_id IS NOT NULL')
    elif match_status:raise AccountAdminError('MATCH_STATUS_INVALID','matchStatus 无效')
    w=' AND '.join(where)
    with db.tx(False) as c:
     total=c.execute('SELECT count(*) FROM account_identity_discoveries d WHERE '+w,args).fetchone()[0]
     items=_rows(c,"""SELECT d.*,p.platform_code,p.platform_name,ca.display_name channel_account_name,u.display_name user_name,t.name team_name,w.name workspace_name FROM account_identity_discoveries d JOIN platforms p ON p.platform_id=d.platform_id JOIN users u ON u.user_id=d.user_id JOIN teams t ON t.team_id=d.team_id JOIN workspaces w ON w.workspace_id=d.workspace_id LEFT JOIN channel_accounts ca ON ca.channel_account_id=d.channel_account_id WHERE """+w+' ORDER BY d.last_seen_at DESC,d.discovery_id LIMIT ? OFFSET ?',args+[size,off])
     _enrich_discovery_matches(c,org,items)
    return h.sendj({'ok':True,'items':items,'pagination':{'page':p,'pageSize':size,'total':total,'pages':(total+size-1)//size}}) or True
   if m=='POST' and ident and action=='approve':return h.sendj({'ok':True,'item':approve(db,a,org,ident,h.body())}) or True
   if m=='POST' and ident and action=='approve-create':return h.sendj({'ok':True,'item':approve_create(db,a,org,ident,h.body())},201) or True
   if m=='POST' and ident and action=='reject':return h.sendj({'ok':True,'item':reject(db,a,org,ident,h.body())}) or True
  raise AccountAdminError('METHOD_NOT_ALLOWED','不支持该资源操作',405)
 except AccountAdminError as e:return _send_error(h,e)
 except sqlite3.IntegrityError as e:
  return h.sendj({'ok':False,'code':'DATA_CONFLICT','message':'数据约束冲突'},409) or True
