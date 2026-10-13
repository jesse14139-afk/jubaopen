# -*- coding: utf-8 -*-
"""V207 企业渠道账号领域服务。"""
import json, re, sqlite3, uuid
from V207_shared_db import now_ms, dumps
from V207_security import can, is_platform_admin
from V208_identity import normalize_identity
from V208_account_policy import normalize_account_policy

STATUSES={'active','disabled'}
IDENTITY_TYPES={'external_id','email','login','username','handle','phone','mobile','whatsapp','telegram','instagram','facebook','messenger','line','wechat','tiktok','whatsapp_jid','whatsapp_lid','telegram_user_id','telegram_phone','telegram_username'}
def _one(c,s,a=()):
 x=c.execute(s,a).fetchone();return dict(x) if x else None
def _rows(c,s,a=()):return [dict(x) for x in c.execute(s,a)]
def _err(code,msg,status=400,**x):return ({'ok':False,'code':code,'message':msg,**x},status)
def _allowed(db,a,perm,org):return bool(a and org and (is_platform_admin(db,a) or (a.get('organization_id')==org and can(db,a,perm))))
def _audit(c,a,op,typ,eid,before,after,reason=None,wid=None):
 if not wid:raise RuntimeError('AUDIT_SCOPE_REQUIRED')
 c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(wid,a['user_id'],None,op,typ,eid,dumps(before or {}),dumps(after or {}),reason,now_ms()))
def _canonical(typ,value):
 return normalize_identity('',typ,value)
def _identity(body,old=None):
 old=old or {};typ,v,cv=_canonical(body.get('identityType',old.get('identity_type')),body.get('identityValue',body.get('identity',old.get('identity_value'))))
 if typ not in IDENTITY_TYPES or not re.fullmatch(r'[a-z][a-z0-9_]{1,63}',typ) or not v or not cv or len(v)>512:return None,_err('INVALID_IDENTITY','身份类型或身份值无效')
 st=str(body.get('status',old.get('status','active'))).lower()
 if st not in STATUSES:return None,_err('INVALID_IDENTITY_STATUS','身份状态无效')
 meta=body.get('metadata',None)
 if meta is None:
  try:meta=json.loads(old.get('metadata_json') or '{}')
  except Exception:meta={}
 if not isinstance(meta,dict):return None,_err('INVALID_METADATA','metadata 必须是对象')
 return {'type':typ,'value':v,'canonical':cv,'status':st,'metadata':meta},None
def _org_exists(c,org):return _one(c,'SELECT organization_id FROM organizations WHERE organization_id=? AND status=\'active\'',(org,))
def _account(c,org,aid):return _one(c,'SELECT * FROM channel_accounts WHERE channel_account_id=? AND organization_id=?',(aid,org))
def _workspace_for_account(c,aid):
 x=_one(c,'SELECT t.workspace_id FROM team_channel_accounts g JOIN teams t ON t.team_id=g.team_id WHERE g.channel_account_id=? ORDER BY g.granted_at LIMIT 1',(aid,));return x.get('workspace_id') if x else None
def _account_defaults(c,org,body,old=None):
 old=old or {}; market=str(body.get('defaultMarketId',old.get('default_market_id') or '') or '').strip() or None
 source_type=str(body.get('suggestedSourceTypeId',old.get('suggested_source_type_id') or '') or '').strip() or None
 if market and not _one(c,"SELECT 1 FROM markets WHERE market_id=? AND organization_id=? AND status='active'",(market,org)):
  return None,_err('DEFAULT_MARKET_INVALID','默认市场不存在、未启用或不属于当前企业',409)
 if source_type and not _one(c,"SELECT 1 FROM source_type_definitions WHERE source_type_id=? AND is_active=1",(source_type,)):
  return None,_err('SUGGESTED_SOURCE_TYPE_INVALID','建议来源类型不存在或未启用',409)
 return {'market':market,'source_type':source_type},None

def handle(db,actor,org,method,account_id=None,action=None,child_id=None,query=None,body=None):
 query=query or {};body=body or {}
 if not org:return _err('ORGANIZATION_REQUIRED','缺少目标企业')
 with db.tx(False) as c:
  if not _org_exists(c,org):return _err('ORGANIZATION_NOT_FOUND','目标企业不存在',404)
 perm='account.read' if method=='GET' else 'account.bind'
 if not _allowed(db,actor,perm,org):return _err('FORBIDDEN','无账号读取权限' if method=='GET' else '无账号管理权限',403)
 if action=='identities':
  with db.tx(False) as c:acc=_account(c,org,account_id)
  if not acc:return _err('ACCOUNT_NOT_FOUND','账号不存在',404)
  if method=='GET' and not child_id:
   with db.tx(False) as c:return {'ok':True,'items':_rows(c,'SELECT * FROM channel_account_identities WHERE channel_account_id=? ORDER BY is_primary DESC,created_at',(account_id,))},200
  if method=='POST' and not child_id:
   data,e=_identity(body)
   if e:return e
   pid=str(body.get('platformId') or acc.get('platform_id') or '') or None
   if pid!=acc.get('platform_id'):return _err('PLATFORM_MISMATCH','身份平台必须与账号平台一致',409)
   try:
    with db.tx() as c:
     conflict=_one(c,"SELECT i.identity_id,i.channel_account_id FROM channel_account_identities i JOIN channel_accounts ca ON ca.channel_account_id=i.channel_account_id WHERE ca.organization_id=? AND ca.platform_id=? AND i.identity_type=? AND i.canonical_value=? AND i.status='active' LIMIT 1",(org,pid,data['type'],data['canonical']))
     if conflict:return _err('ACCOUNT_IDENTITY_CONFLICT','当前企业在该平台已存在相同稳定身份',409,conflict=conflict)
     iid='idn_'+uuid.uuid4().hex;n=now_ms();primary=1 if body.get('isPrimary') or not _one(c,'SELECT identity_id FROM channel_account_identities WHERE channel_account_id=?',(account_id,)) else 0
     if primary:c.execute('UPDATE channel_account_identities SET is_primary=0 WHERE channel_account_id=?',(account_id,))
     c.execute('INSERT INTO channel_account_identities(identity_id,channel_account_id,identity_type,identity_value,canonical_value,created_at,platform_id,is_primary,status,valid_from,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(iid,account_id,data['type'],data['value'],data['canonical'],n,pid,primary,data['status'],n,dumps(data['metadata'])))
     new=_one(c,'SELECT * FROM channel_account_identities WHERE identity_id=?',(iid,));_audit(c,actor,'create','channel_account_identity',iid,{},new,body.get('reason'),_workspace_for_account(c,account_id))
    return {'ok':True,'item':new},201
   except sqlite3.IntegrityError:return _err('IDENTITY_CONFLICT','该账号身份已存在',409)
  if method=='PATCH' and child_id:
   with db.tx() as c:
    old=_one(c,'SELECT * FROM channel_account_identities WHERE identity_id=? AND channel_account_id=?',(child_id,account_id))
    if not old:return _err('IDENTITY_NOT_FOUND','账号身份不存在',404)
    data,e=_identity(body,old)
    if e:return e
    pid=str(body.get('platformId',old.get('platform_id')) or '') or None
    if pid!=acc.get('platform_id'):return _err('PLATFORM_MISMATCH','身份平台必须与账号平台一致',409)
    conflict=_one(c,"SELECT i.identity_id,i.channel_account_id FROM channel_account_identities i JOIN channel_accounts ca ON ca.channel_account_id=i.channel_account_id WHERE ca.organization_id=? AND ca.platform_id=? AND i.identity_type=? AND i.canonical_value=? AND i.status='active' AND i.identity_id<>? LIMIT 1",(org,pid,data['type'],data['canonical'],child_id))
    if conflict:return _err('ACCOUNT_IDENTITY_CONFLICT','当前企业在该平台已存在相同稳定身份',409,conflict=conflict)
    primary=1 if body.get('isPrimary') else int(old.get('is_primary') or 0)
    if primary:c.execute('UPDATE channel_account_identities SET is_primary=0 WHERE channel_account_id=?',(account_id,))
    c.execute('UPDATE channel_account_identities SET identity_type=?,identity_value=?,canonical_value=?,platform_id=?,is_primary=?,status=?,metadata_json=? WHERE identity_id=?',(data['type'],data['value'],data['canonical'],pid,primary,data['status'],dumps(data['metadata']),child_id))
    new=_one(c,'SELECT * FROM channel_account_identities WHERE identity_id=?',(child_id,));_audit(c,actor,'update','channel_account_identity',child_id,old,new,body.get('reason'),_workspace_for_account(c,account_id))
   return {'ok':True,'item':new},200
  if method=='DELETE' and child_id:
   with db.tx() as c:
    old=_one(c,'SELECT * FROM channel_account_identities WHERE identity_id=? AND channel_account_id=?',(child_id,account_id))
    if not old:return _err('IDENTITY_NOT_FOUND','账号身份不存在',404)
    if c.execute('SELECT count(*) FROM channel_account_identities WHERE channel_account_id=?',(account_id,)).fetchone()[0]<=1:return _err('LAST_IDENTITY','不能删除账号的最后一个身份',409)
    c.execute('DELETE FROM channel_account_identities WHERE identity_id=?',(child_id,))
    if old.get('is_primary'):
     x=c.execute("SELECT identity_id FROM channel_account_identities WHERE channel_account_id=? ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END,created_at LIMIT 1",(account_id,)).fetchone();c.execute('UPDATE channel_account_identities SET is_primary=1 WHERE identity_id=?',(x[0],))
    _audit(c,actor,'delete','channel_account_identity',child_id,old,{},body.get('reason'),_workspace_for_account(c,account_id))
   return {'ok':True},200
  return _err('METHOD_NOT_ALLOWED','不支持的账号身份操作',405)
 if action=='owners':
  with db.tx(False) as c:acc=_account(c,org,account_id)
  if not acc:return _err('ACCOUNT_NOT_FOUND','账号不存在',404)
  if method=='GET':
   with db.tx(False) as c:
    items=_rows(c,"""SELECT g.user_id,g.permission_scope,g.granted_by,g.granted_at,u.display_name,u.login_name,
      (SELECT group_concat(DISTINCT t.name) FROM team_memberships tm JOIN teams t ON t.team_id=tm.team_id JOIN team_channel_accounts tca ON tca.team_id=t.team_id AND tca.channel_account_id=g.channel_account_id WHERE tm.user_id=g.user_id AND tm.status='active' AND t.status='active') team_names
      FROM user_channel_account_grants g JOIN users u ON u.user_id=g.user_id
      WHERE g.channel_account_id=? AND u.organization_id=? ORDER BY u.display_name""",(account_id,org))
    eligible=_rows(c,"""SELECT DISTINCT u.user_id,u.display_name,u.login_name,
      (SELECT group_concat(DISTINCT t2.name) FROM team_memberships tm2 JOIN teams t2 ON t2.team_id=tm2.team_id JOIN team_channel_accounts g2 ON g2.team_id=t2.team_id AND g2.channel_account_id=? WHERE tm2.user_id=u.user_id AND tm2.status='active' AND t2.status='active') team_names
      FROM users u JOIN team_memberships tm ON tm.user_id=u.user_id AND tm.status='active'
      JOIN teams t ON t.team_id=tm.team_id AND t.organization_id=u.organization_id AND t.status='active'
      JOIN team_channel_accounts g ON g.team_id=t.team_id AND g.channel_account_id=?
      WHERE u.organization_id=? AND u.status='active' ORDER BY u.display_name""",(account_id,account_id,org))
   return {'ok':True,'items':items,'eligibleUsers':eligible},200
  if method in ('PUT','PATCH','POST'):
   uid=str(body.get('ownerUserId') or body.get('userId') or '').strip();reason=str(body.get('reason') or '').strip()
   if not uid:return _err('OWNER_USER_REQUIRED','请选择账号负责人')
   if not reason:return _err('REASON_REQUIRED','操作原因必填')
   with db.tx() as c:
    user=_one(c,"SELECT * FROM users WHERE user_id=? AND organization_id=? AND status='active'",(uid,org))
    if not user:return _err('OWNER_USER_INVALID','负责人不存在、已停用或不属于当前企业',404)
    membership=_one(c,"""SELECT t.team_id,t.workspace_id FROM team_memberships tm JOIN teams t ON t.team_id=tm.team_id JOIN team_channel_accounts g ON g.team_id=t.team_id AND g.channel_account_id=? WHERE tm.user_id=? AND tm.status='active' AND t.status='active' AND t.organization_id=? ORDER BY t.created_at LIMIT 1""",(account_id,uid,org))
    if not membership:return _err('OWNER_AUTHORIZED_TEAM_REQUIRED','负责人必须是账号已授权团队的有效成员',409)
    old=_rows(c,'SELECT * FROM user_channel_account_grants WHERE channel_account_id=?',(account_id,))
    c.execute('DELETE FROM user_channel_account_grants WHERE channel_account_id=?',(account_id,))
    n=now_ms();c.execute("INSERT INTO user_channel_account_grants(user_id,channel_account_id,permission_scope,granted_by,granted_at) VALUES(?,?,'use',?,?)",(uid,account_id,actor['user_id'],n))
    new=_rows(c,'SELECT * FROM user_channel_account_grants WHERE channel_account_id=?',(account_id,));_audit(c,actor,'replace_owner','channel_account_owner',account_id,old,new,reason,membership['workspace_id'])
   return {'ok':True,'items':new},200
  return _err('METHOD_NOT_ALLOWED','不支持的负责人操作',405)
 if action=='grants':
  with db.tx(False) as c:acc=_account(c,org,account_id)
  if not acc:return _err('ACCOUNT_NOT_FOUND','账号不存在',404)
  if method=='GET':
   with db.tx(False) as c:return {'ok':True,'items':_rows(c,'SELECT g.*,t.name team_name,t.workspace_id,w.name workspace_name FROM team_channel_accounts g JOIN teams t ON t.team_id=g.team_id LEFT JOIN workspaces w ON w.workspace_id=t.workspace_id WHERE g.channel_account_id=? AND t.organization_id=? ORDER BY w.name,t.name,g.granted_at',(account_id,org))},200
  team_id=str(body.get('teamId') or query.get('teamId') or query.get('team_id') or '')
  if not team_id:return _err('TEAM_REQUIRED','缺少团队 ID')
  reason=str(body.get('reason') or '').strip()
  if not reason:return _err('REASON_REQUIRED','操作原因必填')
  with db.tx() as c:
   team=_one(c,"SELECT * FROM teams WHERE team_id=? AND organization_id=? AND status='active'",(team_id,org)) if team_id else None
   if team_id and not team:return _err('TEAM_NOT_FOUND','团队不存在',404)
   old=_one(c,'SELECT * FROM team_channel_accounts WHERE team_id=? AND channel_account_id=?',(team_id,account_id))
   if method=='POST':
    if not old:c.execute('INSERT INTO team_channel_accounts(team_id,channel_account_id,granted_by,granted_at) VALUES(?,?,?,?)',(team_id,account_id,actor['user_id'],now_ms()))
    new=_one(c,'SELECT * FROM team_channel_accounts WHERE team_id=? AND channel_account_id=?',(team_id,account_id));_audit(c,actor,'grant','team_channel_account',account_id+':'+team_id,old or {},new,body.get('reason'),team['workspace_id'])
    return {'ok':True,'item':new},201 if not old else 200
   if method=='DELETE':
    if not old:return _err('GRANT_NOT_FOUND','团队授权不存在',404)
    others=c.execute('SELECT count(*) FROM team_channel_accounts g JOIN teams t ON t.team_id=g.team_id WHERE g.channel_account_id=? AND t.workspace_id=? AND g.team_id<>?',(account_id,team['workspace_id'],team_id)).fetchone()[0]
    active=c.execute("SELECT count(*) FROM sources WHERE organization_id=? AND workspace_id=? AND channel_account_id=? AND status='active'",(org,team['workspace_id'],account_id)).fetchone()[0]
    if active and not others:return _err('GRANT_IN_USE','工作区仍有活跃来源使用该账号',409,references={'sources':active})
    c.execute('DELETE FROM team_channel_accounts WHERE team_id=? AND channel_account_id=?',(team_id,account_id));_audit(c,actor,'revoke','team_channel_account',account_id+':'+team_id,old,{},body.get('reason'),team['workspace_id']);return {'ok':True},200
  return _err('METHOD_NOT_ALLOWED','不支持的账号授权操作',405)
 if method=='GET' and account_id is None:
  with db.tx(False) as c:
   # P2: 关联 platforms 表，返回完整平台信息
    items=_rows(c,"""SELECT ca.*,
      p.platform_code,p.platform_name,p.platform_kind,
      CASE
       WHEN lower(coalesce(p.platform_code,p.platform_kind,p.platform_name,'')) IN ('facebook','fb','messenger') THEN 'FB'
       WHEN lower(coalesce(p.platform_code,p.platform_kind,p.platform_name,'')) IN ('instagram','ig') THEN 'IG'
       WHEN lower(coalesce(p.platform_code,p.platform_kind,p.platform_name,'')) IN ('whatsapp','wa') THEN 'WA'
       WHEN lower(coalesce(p.platform_code,p.platform_kind,p.platform_name,'')) IN ('telegram','tg') THEN 'TG'
       ELSE upper(substr(coalesce(nullif(p.platform_code,''),nullif(p.platform_kind,''),nullif(p.platform_name,''),'--'),1,4))
      END platform_abbr,
      ct.name channel_type_name,m.name market_name,
      (SELECT group_concat(z.identity_value) FROM (SELECT DISTINCT i.identity_value FROM channel_account_identities i WHERE i.channel_account_id=ca.channel_account_id ORDER BY i.created_at) z) identities,
      (SELECT group_concat(z.canonical_value) FROM (SELECT DISTINCT i.canonical_value FROM channel_account_identities i WHERE i.channel_account_id=ca.channel_account_id ORDER BY i.created_at) z) canonical_identities,
      (SELECT group_concat(z.identity_type) FROM (SELECT DISTINCT i.identity_type FROM channel_account_identities i WHERE i.channel_account_id=ca.channel_account_id ORDER BY i.identity_type) z) identity_types,
      (SELECT group_concat(z.team_id) FROM (SELECT t.team_id FROM team_channel_accounts x JOIN teams t ON t.team_id=x.team_id WHERE x.channel_account_id=ca.channel_account_id ORDER BY t.name) z) team_ids,
      (SELECT group_concat(z.name) FROM (SELECT t.name FROM team_channel_accounts x JOIN teams t ON t.team_id=x.team_id WHERE x.channel_account_id=ca.channel_account_id ORDER BY t.name) z) teams,
      (SELECT group_concat(z.workspace_id) FROM (SELECT DISTINCT w.workspace_id FROM team_channel_accounts x JOIN teams t ON t.team_id=x.team_id JOIN workspaces w ON w.workspace_id=t.workspace_id WHERE x.channel_account_id=ca.channel_account_id ORDER BY w.name) z) workspace_ids,
      (SELECT group_concat(z.name) FROM (SELECT DISTINCT w.name FROM team_channel_accounts x JOIN teams t ON t.team_id=x.team_id JOIN workspaces w ON w.workspace_id=t.workspace_id WHERE x.channel_account_id=ca.channel_account_id ORDER BY w.name) z) workspace_names,
      (SELECT group_concat(z.user_id) FROM (SELECT u.user_id FROM user_channel_account_grants g JOIN users u ON u.user_id=g.user_id WHERE g.channel_account_id=ca.channel_account_id ORDER BY u.display_name) z) owner_user_id,
      (SELECT group_concat(z.display_name) FROM (SELECT u.display_name FROM user_channel_account_grants g JOIN users u ON u.user_id=g.user_id WHERE g.channel_account_id=ca.channel_account_id ORDER BY u.display_name) z) owner_name,
      (SELECT count(*) FROM sources src WHERE src.channel_account_id=ca.channel_account_id) source_count,
      (SELECT group_concat(z.device_id) FROM (SELECT DISTINCT b.device_id FROM device_channel_account_bindings b WHERE b.channel_account_id=ca.channel_account_id AND b.status='active' ORDER BY b.device_id) z) bound_device_ids,
      (SELECT group_concat(z.device_name) FROM (SELECT DISTINCT b.device_id,coalesce(nullif(trim(d.admin_device_name),''),nullif(trim(d.user_device_alias),''),nullif(trim(d.system_device_name),''),nullif(trim(d.device_name),''),nullif(trim(d.admin_computer_name),''),nullif(trim(d.user_computer_alias),''),nullif(trim(d.system_computer_name),''),nullif(trim(d.computer_name),''),b.device_id) device_name FROM device_channel_account_bindings b LEFT JOIN devices d ON d.device_id=b.device_id WHERE b.channel_account_id=ca.channel_account_id AND b.status='active' ORDER BY b.device_id) z) bound_device_names,
      (SELECT count(DISTINCT b.device_id) FROM device_channel_account_bindings b WHERE b.channel_account_id=ca.channel_account_id AND b.status='active') active_device_count
    FROM channel_accounts ca
    LEFT JOIN platforms p ON p.platform_id=ca.platform_id
    LEFT JOIN channel_types ct ON ct.channel_type_id=ca.channel_type_id
    LEFT JOIN markets m ON m.market_id=ca.default_market_id
    WHERE ca.organization_id=? ORDER BY ca.created_at""",(org,))
  return {'ok':True,'items':items},200
 if method=='GET' and account_id:
  with db.tx(False) as c:
   # P2: 关联 platforms 表返回完整平台信息
   item=_one(c,"""SELECT ca.*, p.platform_code, p.platform_name, p.platform_kind,
      (SELECT count(DISTINCT x.device_id) FROM (
       SELECT b.device_id FROM device_channel_account_bindings b
       WHERE b.channel_account_id=ca.channel_account_id AND b.status='active'
       UNION
       SELECT ad.device_id FROM account_identity_discoveries ad
       WHERE ad.channel_account_id=ca.channel_account_id AND ad.status='approved'
      ) x) active_device_count
      FROM channel_accounts ca
      LEFT JOIN platforms p ON p.platform_id=ca.platform_id
      WHERE ca.channel_account_id=? AND ca.organization_id=?""",(account_id,org))
  return ({'ok':True,'item':item},200) if item else _err('ACCOUNT_NOT_FOUND','账号不存在',404)
 if method=='POST' and account_id is None:
  pid=str(body.get('platformId') or '').strip()
  team_id=str(body.get('teamId') or '').strip()
  owner_user_id=str(body.get('ownerUserId') or '').strip()
  display_name=str(body.get('displayName') or '').strip()
  if not pid:return _err('PLATFORM_ID_REQUIRED','platformId 必填')
  if not team_id:return _err('TEAM_ID_REQUIRED','teamId 必填')
  if not owner_user_id:return _err('OWNER_USER_REQUIRED','ownerUserId 必填')
  if not display_name:return _err('DISPLAY_NAME_REQUIRED','账号显示名不能为空')
  try:policy=normalize_account_policy(body)
  except ValueError as e:return _err(str(e),'业务场景与建档策略无效')
  channel_type_id=str(body.get('channelTypeId') or body.get('channel_type_id') or '').strip() or None
  raw_identity=str(body.get('identity') or '').strip()
  idata=None
  if raw_identity:
   idata,e=_identity({'identityType':body.get('identityType','login'),'identityValue':raw_identity,'metadata':body.get('identityMetadata',{})})
   if e:return e
  meta=body.get('metadata',{})
  if not isinstance(meta,dict):return _err('INVALID_METADATA','metadata 必须是对象')
  with db.tx() as c:
   team=_one(c,"SELECT * FROM teams WHERE team_id=? AND organization_id=? AND status='active'",(team_id,org))
   if not team:return _err('TEAM_NOT_FOUND','团队不存在、未启用或不属于当前企业',404)
   owner=_one(c,"SELECT * FROM users WHERE user_id=? AND organization_id=? AND status='active'",(owner_user_id,org))
   if not owner:return _err('OWNER_USER_INVALID','负责业务员不存在、未启用或不属于当前企业',404)
   if not _one(c,"SELECT 1 FROM team_memberships WHERE user_id=? AND team_id=? AND status='active'",(owner_user_id,team_id)):
    return _err('OWNER_TEAM_MEMBERSHIP_REQUIRED','负责业务员不是所选团队的有效成员',409)
   platform=_one(c,"SELECT * FROM platforms WHERE platform_id=? AND status='active'",(pid,))
   if not platform:return _err('INVALID_PLATFORM','平台不存在或未启用',404)
   if channel_type_id and not _one(c,"SELECT 1 FROM channel_types WHERE channel_type_id=? AND platform_id=? AND is_active=1",(channel_type_id,pid)):
    return _err('INVALID_CHANNEL_TYPE','渠道类型不存在、未启用或不属于所选平台',404)
   defaults,de=_account_defaults(c,org,body)
   if de:return de
   if policy['business_scene']=='social_acquisition' and not defaults['market']:
    return _err('SOCIAL_MARKET_REQUIRED','社交获客账号必须设置当前默认市场')
   if idata:
    conflict=_one(c,"SELECT i.identity_id,i.channel_account_id FROM channel_account_identities i JOIN channel_accounts ca ON ca.channel_account_id=i.channel_account_id WHERE ca.organization_id=? AND ca.platform_id=? AND i.identity_type=? AND i.canonical_value=? AND i.status='active' LIMIT 1",(org,pid,idata['type'],idata['canonical']))
    if conflict:return _err('ACCOUNT_IDENTITY_CONFLICT','当前企业在该平台已存在相同稳定身份',409,conflict=conflict)
   n=now_ms(); aid='acc_'+uuid.uuid4().hex; ch=platform['platform_code'].lower()
   c.execute('INSERT INTO channel_accounts(channel_account_id,organization_id,channel,display_name,status,created_at,updated_at,platform_id,channel_type_id,account_type,metadata_json,business_purpose,collection_enabled,business_scene,contact_entry_policy,default_market_id,suggested_source_type_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(aid,org,ch,display_name,'active',n,n,pid,channel_type_id,policy['account_type'],dumps(meta),policy['business_purpose'],policy['collection_enabled'],policy['business_scene'],policy['contact_entry_policy'],defaults['market'],defaults['source_type']))
   if idata:
    iid='idn_'+uuid.uuid4().hex
    c.execute('INSERT INTO channel_account_identities(identity_id,channel_account_id,identity_type,identity_value,canonical_value,created_at,platform_id,is_primary,status,valid_from,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(iid,aid,idata['type'],idata['value'],idata['canonical'],n,pid,1,'active',n,dumps(idata['metadata'])))
   c.execute('INSERT INTO team_channel_accounts(team_id,channel_account_id,granted_by,granted_at) VALUES(?,?,?,?)',(team_id,aid,actor['user_id'],n))
   c.execute("INSERT INTO user_channel_account_grants(user_id,channel_account_id,permission_scope,granted_by,granted_at) VALUES(?,?,'use',?,?)",(owner_user_id,aid,actor['user_id'],n))
   new=_one(c,'SELECT * FROM channel_accounts WHERE channel_account_id=?',(aid,))
   _audit(c,actor,'create','channel_account',aid,{},dict(new,owner_user_id=owner_user_id,identity_pending=not bool(idata)),body.get('reason'),team['workspace_id'])
  return {'ok':True,'channelAccountId':aid,'identityPending':not bool(idata)},201
 if method=='PATCH' and account_id:
  reason=str(body.get('reason') or '').strip()
  if not reason:return _err('REASON_REQUIRED','操作原因必填')
  st=str(body.get('status') or '').lower() if 'status' in body else None
  if st and st not in STATUSES:return _err('INVALID_ACCOUNT_STATUS','账号状态无效')
  with db.tx() as c:
   old=_account(c,org,account_id)
   if not old:return _err('ACCOUNT_NOT_FOUND','账号不存在',404)
   defaults,de=_account_defaults(c,org,body,old)
   if de:return de
   policy_input=dict(body);policy_input.setdefault('businessScene',old['business_scene']);policy_input.setdefault('contactEntryPolicy',old['contact_entry_policy'])
   try:policy=normalize_account_policy(policy_input)
   except ValueError as e:return _err(str(e),'业务场景与建档策略无效')
   if policy['business_scene']=='social_acquisition' and not defaults['market']:
    return _err('SOCIAL_MARKET_REQUIRED','社交获客账号必须设置当前默认市场')
   newst=st or old['status']
   if old['status']=='active' and newst=='disabled':
    refs={'sources':c.execute("SELECT count(*) FROM sources WHERE channel_account_id=? AND organization_id=? AND status='active'",(account_id,org)).fetchone()[0]}
    if any(refs.values()):return _err('ACCOUNT_IN_USE','账号仍被活跃业务对象引用',409,references=refs)
   name=str(body.get('displayName',old['display_name'])).strip()
   if not name:return _err('INVALID_ACCOUNT','账号名称不能为空')
   c.execute('UPDATE channel_accounts SET display_name=?,status=?,business_scene=?,contact_entry_policy=?,business_purpose=?,account_type=?,collection_enabled=?,default_market_id=?,suggested_source_type_id=?,updated_at=? WHERE channel_account_id=? AND organization_id=?',(name,newst,policy['business_scene'],policy['contact_entry_policy'],policy['business_purpose'],policy['account_type'],policy['collection_enabled'],defaults['market'],defaults['source_type'],now_ms(),account_id,org));new=_one(c,'SELECT * FROM channel_accounts WHERE channel_account_id=?',(account_id,));_audit(c,actor,'update','channel_account',account_id,old,new,body.get('reason'),_workspace_for_account(c,account_id))
  return {'ok':True,'item':new},200
 return _err('METHOD_NOT_ALLOWED','不支持的账号操作',405)
