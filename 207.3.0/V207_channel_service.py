# -*- coding: utf-8 -*-
"""V207 企业渠道账号领域服务。"""
import json, re, sqlite3, uuid
from V207_shared_db import now_ms, dumps
from V207_security import can

ADMIN='usr_admin'; STATUSES={'active','disabled'}
IDENTITY_TYPES={'external_id','email','login','username','handle','phone','mobile','whatsapp','telegram','instagram','facebook','messenger','line','wechat','tiktok'}
def _one(c,s,a=()):
 x=c.execute(s,a).fetchone();return dict(x) if x else None
def _rows(c,s,a=()):return [dict(x) for x in c.execute(s,a)]
def _err(code,msg,status=400,**x):return ({'ok':False,'code':code,'message':msg,**x},status)
def _admin(a):return bool(a and a.get('user_id')==ADMIN)
def _allowed(db,a,perm,org):return bool(a and org and (_admin(a) or (a.get('organization_id')==org and can(db,a,perm))))
def _audit(c,a,op,typ,eid,before,after,reason=None,wid=None):
 c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(wid or 'default',a['user_id'],None,op,typ,eid,dumps(before or {}),dumps(after or {}),reason,now_ms()))
def _canonical(typ,value):
 typ=str(typ or 'external_id').strip().lower();v=str(value or '').strip()
 if typ in ('email','login','username','handle'):cv=''.join(v.lower().split())
 elif typ in ('phone','mobile','whatsapp'):cv=('+' if v.startswith('+') else '')+''.join(x for x in v if x.isdigit())
 else:cv=' '.join(v.lower().split())
 return typ,v,cv
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
     if _one(c,'SELECT identity_id FROM channel_account_identities WHERE channel_account_id=? AND identity_type=? AND canonical_value=?',(account_id,data['type'],data['canonical'])):return _err('IDENTITY_CONFLICT','该账号身份已存在',409)
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
    if _one(c,'SELECT identity_id FROM channel_account_identities WHERE channel_account_id=? AND identity_type=? AND canonical_value=? AND identity_id<>?',(account_id,data['type'],data['canonical'],child_id)):return _err('IDENTITY_CONFLICT','该账号身份已存在',409)
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
 if action=='grants':
  with db.tx(False) as c:acc=_account(c,org,account_id)
  if not acc:return _err('ACCOUNT_NOT_FOUND','账号不存在',404)
  if method=='GET':
   with db.tx(False) as c:return {'ok':True,'items':_rows(c,'SELECT g.*,t.name team_name,t.workspace_id FROM team_channel_accounts g JOIN teams t ON t.team_id=g.team_id WHERE g.channel_account_id=? AND t.organization_id=? ORDER BY g.granted_at',(account_id,org))},200
  team_id=str(body.get('teamId') or query.get('teamId') or query.get('team_id') or '')
  if not team_id:return _err('TEAM_REQUIRED','缺少团队 ID')
  with db.tx() as c:
   team=_one(c,"SELECT * FROM teams WHERE team_id=? AND organization_id=? AND status='active'",(team_id,org))
   if not team:return _err('TEAM_NOT_FOUND','团队不存在',404)
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
   items=_rows(c,"SELECT ca.*,group_concat(DISTINCT i.identity_value) identities,group_concat(DISTINCT t.name) teams,(SELECT count(*) FROM sources s WHERE s.channel_account_id=ca.channel_account_id) source_count FROM channel_accounts ca LEFT JOIN channel_account_identities i ON i.channel_account_id=ca.channel_account_id LEFT JOIN team_channel_accounts x ON x.channel_account_id=ca.channel_account_id LEFT JOIN teams t ON t.team_id=x.team_id WHERE ca.organization_id=? GROUP BY ca.channel_account_id ORDER BY ca.created_at",(org,))
  return {'ok':True,'items':items},200
 if method=='GET' and account_id:
  with db.tx(False) as c:item=_account(c,org,account_id)
  return ({'ok':True,'item':item},200) if item else _err('ACCOUNT_NOT_FOUND','账号不存在',404)
 if method=='POST' and account_id is None:
  ch=str(body.get('channel') or '').strip().lower();pid=str(body.get('platformId') or '').strip();team_id=str(body.get('teamId') or '');idata,e=_identity({'identityType':body.get('identityType','login'),'identityValue':body.get('identity'),'metadata':body.get('identityMetadata',{})})
  if e or not ch:return _err('INVALID_ACCOUNT','平台代码或身份无效')
  meta=body.get('metadata',{})
  if not isinstance(meta,dict):return _err('INVALID_METADATA','metadata 必须是对象')
  with db.tx() as c:
   team=_one(c,"SELECT * FROM teams WHERE team_id=? AND organization_id=? AND status='active'",(team_id,org))
   if not team:return _err('TEAM_NOT_FOUND','团队不存在',404)
   platform=_one(c,"SELECT * FROM platforms WHERE status='active' AND (platform_id=? OR (?='' AND platform_code=?))",(pid,pid,ch))
   if not platform:return _err('PLATFORM_NOT_FOUND','平台不存在或未启用',404)
   if pid and platform['platform_code']!=ch:return _err('PLATFORM_MISMATCH','平台 ID 与平台代码不一致',409)
   n=now_ms();aid='acc_'+uuid.uuid4().hex;iid='idn_'+uuid.uuid4().hex;sid='src_'+uuid.uuid4().hex;pid=platform['platform_id'];ch=platform['platform_code']
   c.execute('INSERT INTO channel_accounts(channel_account_id,organization_id,channel,display_name,status,created_at,updated_at,platform_id,account_type,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?)',(aid,org,ch,str(body.get('displayName') or idata['value']).strip(), 'active',n,n,pid,str(body.get('accountType') or 'business_account'),dumps(meta)))
   c.execute('INSERT INTO channel_account_identities(identity_id,channel_account_id,identity_type,identity_value,canonical_value,created_at,platform_id,is_primary,status,valid_from,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(iid,aid,idata['type'],idata['value'],idata['canonical'],n,pid,1,'active',n,dumps(idata['metadata'])))
   c.execute('INSERT INTO team_channel_accounts(team_id,channel_account_id,granted_by,granted_at) VALUES(?,?,?,?)',(team_id,aid,actor['user_id'],n))
   c.execute("INSERT INTO sources(source_id,workspace_id,channel,account_identity,source_name,status,first_seen_at,last_seen_at,metadata_json,organization_id,team_id,channel_account_id,platform_id,updated_at) VALUES(?,?,?,?,?,'active',?,?,'{}',?,?,?,?,?)",(sid,team['workspace_id'],ch,idata['value'],str(body.get('sourceName') or body.get('displayName') or idata['value']),n,n,org,team_id,aid,pid,n))
   new=_one(c,'SELECT * FROM channel_accounts WHERE channel_account_id=?',(aid,));_audit(c,actor,'create','channel_account',aid,{},new,body.get('reason'),team['workspace_id'])
  return {'ok':True,'channelAccountId':aid,'sourceId':sid},201
 if method=='PATCH' and account_id:
  st=str(body.get('status') or '').lower() if 'status' in body else None
  if st and st not in STATUSES:return _err('INVALID_ACCOUNT_STATUS','账号状态无效')
  with db.tx() as c:
   old=_account(c,org,account_id)
   if not old:return _err('ACCOUNT_NOT_FOUND','账号不存在',404)
   newst=st or old['status']
   if old['status']=='active' and newst=='disabled':
    refs={'sources':c.execute("SELECT count(*) FROM sources WHERE channel_account_id=? AND organization_id=? AND status='active'",(account_id,org)).fetchone()[0]}
    if any(refs.values()):return _err('ACCOUNT_IN_USE','账号仍被活跃业务对象引用',409,references=refs)
   name=str(body.get('displayName',old['display_name'])).strip()
   if not name:return _err('INVALID_ACCOUNT','账号名称不能为空')
   c.execute('UPDATE channel_accounts SET display_name=?,status=?,updated_at=? WHERE channel_account_id=?',(name,newst,now_ms(),account_id));new=_one(c,'SELECT * FROM channel_accounts WHERE channel_account_id=?',(account_id,));_audit(c,actor,'update','channel_account',account_id,old,new,body.get('reason'),_workspace_for_account(c,account_id))
  return {'ok':True,'item':new},200
 return _err('METHOD_NOT_ALLOWED','不支持的账号操作',405)
