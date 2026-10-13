# -*- coding: utf-8 -*-
"""Schema 221 administration for account binding slots and identity discoveries."""
import sqlite3, uuid
from V207_shared_db import now_ms, dumps
from V208_account_policy import normalize_account_policy

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

PLATFORM_IDENTITY_TYPES={
 'whatsapp':{'whatsapp_jid','whatsapp_lid','whatsapp_phone','phone'},
 'telegram':{'telegram_user_id','telegram_peer_id','telegram_username','telegram_phone'},
 'instagram':{'instagram_user_id','instagram_username'},
 'messenger':{'facebook_user_id'},
 'facebook':{'facebook_user_id'},
}

def _validate_discovery_identity(c,before):
 platform=_one(c,"SELECT platform_code,status FROM platforms WHERE platform_id=?",(before['platform_id'],))
 if not platform or platform['status']!='active': raise AccountAdminError('PLATFORM_INVALID','平台不存在或已禁用')
 code=_text(platform['platform_code']).lower(); identity_type=_text(before.get('identity_type')).lower(); canonical=_text(before.get('canonical_value'))
 allowed=PLATFORM_IDENTITY_TYPES.get(code)
 if allowed is not None and identity_type not in allowed: raise AccountAdminError('IDENTITY_TYPE_PLATFORM_MISMATCH','身份类型与平台不匹配',409)
 if code in ('messenger','facebook') and identity_type!='facebook_user_id': raise AccountAdminError('META_IDENTITY_TYPE_INVALID','Messenger/Facebook 仅允许 facebook_user_id',409)
 if code=='instagram' and identity_type not in ('instagram_user_id','instagram_username'): raise AccountAdminError('META_IDENTITY_TYPE_INVALID','Instagram 身份类型无效',409)
 if not canonical: raise AccountAdminError('CANONICAL_IDENTITY_REQUIRED','规范身份不能为空',409)
 return code

def _reject_ambiguous_match(before):
 if before.get('match_status')=='conflict': raise AccountAdminError('DISCOVERY_MATCH_CONFLICT','当前身份匹配多个有效渠道账号，请先解决冲突',409)

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
 _validate_discovery_identity(c,before); _reject_ambiguous_match(before)
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
 binding_activated=False
 if before['device_id']:
  device=_one(c,"SELECT * FROM devices WHERE device_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND status='active'",(before['device_id'],org,before['workspace_id'],before['team_id']))
  if not device: raise AccountAdminError('DEVICE_SCOPE_INVALID','发现记录对应设备不存在、已停用或作用域已变化',409)
  if device['assigned_user_id'] and device['assigned_user_id']!=before['user_id']: raise AccountAdminError('DEVICE_USER_MISMATCH','发现记录对应设备已分配给其他用户',409)
  binding_id='dcab_'+uuid.uuid4().hex
  metadata=dumps({'source':'admin_approval','discovery_id':did})
  c.execute("INSERT INTO device_channel_account_bindings(binding_id,organization_id,workspace_id,team_id,device_id,user_id,channel_account_id,platform_id,external_account_key,status,bound_at,bound_by,last_verified_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,'active',?,?,?,?) ON CONFLICT(device_id,platform_id,external_account_key) DO UPDATE SET organization_id=excluded.organization_id,workspace_id=excluded.workspace_id,team_id=excluded.team_id,user_id=excluded.user_id,channel_account_id=excluded.channel_account_id,status='active',bound_by=excluded.bound_by,last_verified_at=excluded.last_verified_at,metadata_json=excluded.metadata_json",(binding_id,org,before['workspace_id'],before['team_id'],before['device_id'],before['user_id'],aid,before['platform_id'],before['canonical_value'],n,a['user_id'],n,metadata))
  binding_activated=True
 changed=c.execute("""UPDATE account_identity_discoveries SET status='approved',reason_code='admin_approved',slot_id=?,channel_account_id=?,resolved_at=?,resolved_by=?,resolution_reason=? WHERE discovery_id=? AND organization_id=? AND status='pending'""",(sid,aid,n,a['user_id'],reason or 'admin_approved',did,org)).rowcount
 if changed!=1: raise AccountAdminError('DISCOVERY_STATE_CONFLICT','身份发现已被并发处理',409)
 after=_discovery_detail(c,org,did)
 after['binding_activated']=binding_activated
 after['requires_plugin_recheck']=not binding_activated
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
 name=_text(b.get('displayName')); reason=_text(b.get('reason')); market=_text(b.get('defaultMarketId')) or None; source_type=_text(b.get('suggestedSourceTypeId')) or None
 if not name: raise AccountAdminError('DISPLAY_NAME_REQUIRED','账号名称不能为空')
 try:policy=normalize_account_policy(b)
 except ValueError as e:raise AccountAdminError(str(e),'业务场景与建档策略无效')
 with db.tx() as c:
  before=_discovery_detail(c,org,did)
  if not before: raise AccountAdminError('DISCOVERY_NOT_FOUND','身份发现不存在',404)
  if before['status']!='pending': raise AccountAdminError('DISCOVERY_STATE_CONFLICT','身份发现已被处理',409)
  _scope(c,org,before['workspace_id'],before['team_id'],before['user_id'],before['platform_id'])
  _validate_discovery_identity(c,before); _reject_ambiguous_match(before)
  conflict=_identity_conflict(c,org,before)
  if conflict: raise AccountAdminError('ACCOUNT_IDENTITY_CONFLICT','当前企业已存在使用该身份的渠道账号，请改为绑定已有账号',409)
  platform=_one(c,"SELECT platform_code FROM platforms WHERE platform_id=? AND status='active'",(before['platform_id'],))
  if not platform: raise AccountAdminError('PLATFORM_INVALID','平台不存在或已禁用')
  if policy['business_scene']=='social_acquisition' and not market: raise AccountAdminError('SOCIAL_MARKET_REQUIRED','社交获客账号必须设置当前默认市场')
  if market and not _one(c,"SELECT 1 ok FROM markets WHERE market_id=? AND organization_id=? AND status='active'",(market,org)): raise AccountAdminError('DEFAULT_MARKET_INVALID','默认市场不存在、未启用或不属于当前企业',409)
  if source_type and not _one(c,"SELECT 1 ok FROM source_type_definitions WHERE source_type_id=? AND is_active=1",(source_type,)): raise AccountAdminError('SUGGESTED_SOURCE_TYPE_INVALID','建议来源类型不存在或未启用',409)
  n=now_ms(); aid='acc_'+uuid.uuid4().hex
  c.execute("""INSERT INTO channel_accounts(channel_account_id,organization_id,channel,display_name,status,created_at,updated_at,platform_id,channel_type_id,account_type,metadata_json,business_purpose,collection_enabled,business_scene,contact_entry_policy,default_market_id,suggested_source_type_id)
   VALUES(?,?,?,?,'active',?,?,?,?,?,'{}',?,?,?,?,?,?)""",(aid,org,_text(platform['platform_code']).lower(),name,n,n,before['platform_id'],None,policy['account_type'],policy['business_purpose'],policy['collection_enabled'],policy['business_scene'],policy['contact_entry_policy'],market,source_type))
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
