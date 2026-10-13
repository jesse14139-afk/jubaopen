# -*- coding: utf-8 -*-
"""V207.1 来源领域服务：企业/工作区隔离、引用一致性与事务审计。"""
import json, sqlite3, uuid
from V207_shared_db import now_ms, dumps
from V207_security import can,is_platform_admin,data_scope_clause_in_tx
STATUSES={'active','disabled'}
DIRECTIONS={'inbound','outbound','bidirectional','unknown'}
INITIATORS={'customer','business','system','unknown'}
def one(c,s,a=()):
 x=c.execute(s,a).fetchone();return dict(x) if x else None
def rows(c,s,a=()):return [dict(x) for x in c.execute(s,a)]
def err(code,msg,status=400,**extra):return {'ok':False,'code':code,'message':msg,**extra},status
def is_admin(db,a):return is_platform_admin(db,a)
def allowed(db,a,org,perm):return bool(org) and (is_admin(db,a) or (a.get('organization_id')==org and can(db,a,perm)))
def audit(c,a,op,eid,before,after,wid,reason=None):
 if not wid:raise RuntimeError('AUDIT_SCOPE_REQUIRED')
 c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(wid,a['user_id'],None,op,'source',eid,dumps(before or {}),dumps(after or {}),reason,now_ms()))
def obj(v):
 if v is None:return {}
 if not isinstance(v,dict):raise ValueError
 return v
def scope(c,org,wid,team=None,account=None,platform=None,campaign=None,parent=None):
 w=one(c,"SELECT * FROM workspaces WHERE workspace_id=? AND organization_id=? AND status='active'",(wid,org))
 if not w:raise LookupError(('WORKSPACE_NOT_FOUND','工作区不存在或未启用',404))
 t=None
 if team:
  t=one(c,"SELECT * FROM teams WHERE team_id=? AND organization_id=? AND workspace_id=? AND status='active'",(team,org,wid))
  if not t:raise LookupError(('TEAM_NOT_FOUND','团队不存在、未启用或不属于目标工作区',404))
 acc=None
 if account:
  acc=one(c,"SELECT * FROM channel_accounts WHERE channel_account_id=? AND organization_id=? AND status='active'",(account,org))
  if not acc:raise LookupError(('ACCOUNT_NOT_FOUND','渠道账号不存在或未启用',404))
  if team and not one(c,'SELECT 1 FROM team_channel_accounts WHERE team_id=? AND channel_account_id=?',(team,account)):
   raise LookupError(('ACCOUNT_NOT_GRANTED','渠道账号未授权给目标团队',409))
 if platform:
  p=one(c,"SELECT * FROM platforms WHERE platform_id=? AND status='active'",(platform,))
  if not p:raise LookupError(('PLATFORM_NOT_FOUND','平台不存在或未启用',404))
  if acc and acc.get('platform_id')!=platform:raise LookupError(('PLATFORM_MISMATCH','来源平台必须与渠道账号平台一致',409))
 elif acc: platform=acc.get('platform_id')
 if campaign:
  cp=one(c,'SELECT * FROM campaigns WHERE campaign_id=? AND organization_id=? AND workspace_id=?',(campaign,org,wid))
  if not cp:raise LookupError(('CAMPAIGN_NOT_FOUND','活动不存在或不属于目标工作区',404))
  if platform and cp.get('platform_id') and cp['platform_id']!=platform:raise LookupError(('PLATFORM_MISMATCH','活动平台与来源平台不一致',409))
  if account and cp.get('channel_account_id') and cp['channel_account_id']!=account:raise LookupError(('ACCOUNT_MISMATCH','活动账号与来源账号不一致',409))
 if parent:
  ps=one(c,'SELECT * FROM sources WHERE source_id=? AND organization_id=? AND workspace_id=?',(parent,org,wid))
  if not ps:raise LookupError(('PARENT_SOURCE_NOT_FOUND','父来源不存在或不属于目标工作区',404))
 return platform,acc
def refs(c,sid):
 return {'touchpoints':c.execute('SELECT count(*) FROM source_touchpoints WHERE source_id=?',(sid,)).fetchone()[0], 'attributions':c.execute('SELECT count(*) FROM contact_attributions WHERE source_id=?',(sid,)).fetchone()[0], 'contacts':c.execute('SELECT count(*) FROM contacts WHERE source_id=? AND deleted_at IS NULL',(sid,)).fetchone()[0], 'sourceLinks':c.execute('SELECT count(*) FROM source_links WHERE from_source_id=? OR to_source_id=?',(sid,sid)).fetchone()[0], 'childSources':c.execute("SELECT count(*) FROM sources WHERE parent_source_id=? AND status='active'",(sid,)).fetchone()[0]}
def handle(db,a,org,m,ident,q,b):
 if not org or a.get('organization_id')!=org:return err('FORBIDDEN','企业范围不匹配',403)
 if m=='GET':
  with db.tx(False) as c:
   access_sql,access_args,access_meta=data_scope_clause_in_tx(c,a,'source.read',org,alias='s',owner_column=None,team_column='team_id',workspace_column='workspace_id')
   if access_meta['level']=='none':return err('FORBIDDEN','无来源读取权限',403)
   if ident:
    x=one(c,'SELECT s.*,t.name team_name,w.name workspace_name,ca.display_name account_name,p.platform_name,st.name source_type_name,st.source_type_code,ct.name channel_type_name,ct.channel_type_code FROM sources s LEFT JOIN teams t ON t.team_id=s.team_id LEFT JOIN workspaces w ON w.workspace_id=s.workspace_id LEFT JOIN channel_accounts ca ON ca.channel_account_id=s.channel_account_id LEFT JOIN platforms p ON p.platform_id=s.platform_id LEFT JOIN source_type_definitions st ON st.source_type_id=s.source_type_id LEFT JOIN channel_types ct ON ct.channel_type_id=s.channel_type_id WHERE s.source_id=? AND s.organization_id=? AND '+access_sql,(ident,org,*access_args))
    return ({'ok':True,'item':x},200) if x else err('SOURCE_NOT_FOUND','来源不存在或超出授权范围',404)
   where=['s.organization_id=?',access_sql];args=[org,*access_args]
   mapping={'workspace_id':'s.workspace_id','workspaceId':'s.workspace_id','team_id':'s.team_id','teamId':'s.team_id','platform_id':'s.platform_id','platformId':'s.platform_id','channel_account_id':'s.channel_account_id','channelAccountId':'s.channel_account_id','status':'s.status','source_type':'s.source_type','sourceType':'s.source_type','source_type_id':'s.source_type_id','sourceTypeId':'s.source_type_id'}
   for k,col in mapping.items():
    if q.get(k) not in (None,''):where.append(col+'=?');args.append(str(q[k]))
   its=rows(c,'SELECT s.*,t.name team_name,w.name workspace_name,ca.display_name account_name,p.platform_name,st.name source_type_name,st.source_type_code,ct.name channel_type_name,ct.channel_type_code FROM sources s LEFT JOIN teams t ON t.team_id=s.team_id LEFT JOIN workspaces w ON w.workspace_id=s.workspace_id LEFT JOIN channel_accounts ca ON ca.channel_account_id=s.channel_account_id LEFT JOIN platforms p ON p.platform_id=s.platform_id LEFT JOIN source_type_definitions st ON st.source_type_id=s.source_type_id LEFT JOIN channel_types ct ON ct.channel_type_id=s.channel_type_id WHERE '+' AND '.join(where)+' ORDER BY s.last_seen_at DESC',args)
   return {'ok':True,'items':its},200
 if m=='POST' and not ident:
  wid=str(b.get('workspaceId') or b.get('workspace_id') or '').strip();team=str(b.get('teamId') or b.get('team_id') or '').strip() or None;account=str(b.get('channelAccountId') or b.get('channel_account_id') or '').strip() or None;platform=str(b.get('platformId') or b.get('platform_id') or '').strip() or None
  name=str(b.get('name') or b.get('sourceName') or '').strip();identity=str(b.get('accountIdentity') or b.get('account_identity') or '').strip()
  type_id=str(b.get('sourceTypeId') or b.get('source_type_id') or '').strip();channel_type_id=str(b.get('channelTypeId') or b.get('channel_type_id') or '').strip() or None
  if not wid:return err('WORKSPACE_REQUIRED','所属工作区必填')
  if not (is_admin(db,a) or can(db,a,'source.manage',workspace_id=wid,team_id=team,organization_id=org)):return err('FORBIDDEN','无目标范围的来源管理权限',403)
  if not name or len(name)>128:return err('INVALID_SOURCE_NAME','来源名称不能为空且不得超过 128 字符')
  if not type_id:return err('SOURCE_TYPE_REQUIRED','请选择来源类型')
  if len(identity)>512:return err('INVALID_ACCOUNT_IDENTITY','外部入口标识不得超过 512 字符')
  direction=str(b.get('direction') or 'inbound');initiated=str(b.get('initiatedBy') or 'unknown');status=str(b.get('status') or 'active')
  if direction not in DIRECTIONS:return err('INVALID_DIRECTION','来源方向无效')
  if initiated not in INITIATORS:return err('INVALID_INITIATED_BY','发起方无效')
  if status not in STATUSES:return err('INVALID_SOURCE_STATUS','来源状态无效')
  try:metadata=obj(b.get('metadata'))
  except ValueError:return err('INVALID_SOURCE_JSON','metadata 必须是 JSON 对象')
  try:
   with db.tx() as c:
    platform,acc=scope(c,org,wid,team,account,platform,b.get('campaignId'),b.get('parentSourceId'))
    st=one(c,'SELECT * FROM source_type_definitions WHERE source_type_id=? AND is_active=1',(type_id,))
    if not st:return err('INVALID_SOURCE_TYPE_ID','来源类型不存在或未启用',404)
    typ=st['source_type_code']
    channel=''
    if acc:
     acc_platform=acc.get('platform_id');acc_ct=acc.get('channel_type_id')
     if platform and acc_platform and platform!=acc_platform:return err('PLATFORM_MISMATCH','所选平台与关联账号不一致',409)
     if channel_type_id and acc_ct and channel_type_id!=acc_ct:return err('CHANNEL_TYPE_MISMATCH','所选渠道类型与关联账号不一致',409)
     platform=acc_platform or platform;channel_type_id=acc_ct or channel_type_id
     channel=str(acc.get('channel') or '')
     if not identity:
      ai=one(c,"SELECT identity_value FROM channel_account_identities WHERE channel_account_id=? AND status='active' ORDER BY is_primary DESC,created_at LIMIT 1",(account,))
      identity=str((ai or {}).get('identity_value') or '')
    if channel_type_id:
     ct=one(c,'SELECT * FROM channel_types WHERE channel_type_id=? AND is_active=1',(channel_type_id,))
     if not ct:return err('INVALID_CHANNEL_TYPE','渠道类型不存在或未启用',404)
     if platform and ct.get('platform_id') and platform!=ct.get('platform_id'):return err('CHANNEL_TYPE_MISMATCH','渠道类型不属于所选平台',409)
     platform=platform or ct.get('platform_id');channel=ct['channel_type_code']
    if platform:
     pl=one(c,"SELECT platform_code FROM platforms WHERE platform_id=? AND status='active'",(platform,))
     if not pl:return err('INVALID_PLATFORM','平台不存在或未启用',404)
    else:pl=None
    # channel 是非空兼容快照；权威字段为 channel_type_id/source_type_id。
    channel=(channel or (pl or {}).get('platform_code') or typ or 'unclassified').lower()
    sid='src_'+uuid.uuid4().hex;n=now_ms()
    c.execute('INSERT INTO sources(source_id,workspace_id,channel,account_identity,source_name,status,first_seen_at,last_seen_at,metadata_json,organization_id,team_id,channel_account_id,platform_id,source_type,source_subtype,direction,initiated_by,campaign_id,parent_source_id,external_key,landing_url,tracking_code,source_type_id,channel_type_id,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(sid,wid,channel,identity,name,status,n,n,dumps(metadata),org,team,account,platform,typ,b.get('sourceSubtype'),direction,initiated,b.get('campaignId'),b.get('parentSourceId'),b.get('externalKey'),b.get('landingUrl'),b.get('trackingCode'),type_id,channel_type_id,n))
    new=one(c,'SELECT * FROM sources WHERE source_id=?',(sid,));audit(c,a,'create',sid,{},new,wid,b.get('reason'))
   return {'ok':True,'sourceId':sid,'item':new},201
  except LookupError as e:return err(*e.args[0])
  except sqlite3.IntegrityError as e:return err('SOURCE_CONFLICT','来源数据冲突：'+str(e),409)
 if m=='PATCH' and ident:
  try:metadata=obj(b.get('metadata')) if 'metadata' in b else None
  except ValueError:return err('INVALID_SOURCE_JSON','metadata 必须是 JSON 对象')
  try:
   with db.tx() as c:
    old=one(c,'SELECT * FROM sources WHERE source_id=? AND organization_id=?',(ident,org))
    if not old:return err('SOURCE_NOT_FOUND','来源不存在',404)
    if not (is_admin(db,a) or can(db,a,'source.manage',workspace_id=old.get('workspace_id'),team_id=old.get('team_id'),organization_id=org)):return err('FORBIDDEN','来源超出管理范围',403)
    name=str(b.get('name') if 'name' in b else b.get('sourceName') if 'sourceName' in b else old['source_name']).strip();status=str(b.get('status',old['status']))
    if not name or len(name)>128:return err('INVALID_SOURCE_NAME','来源名称不能为空且不得超过 128 字符')
    if status not in STATUSES:return err('INVALID_SOURCE_STATUS','来源状态无效')
    c.execute('UPDATE sources SET source_name=?,status=?,metadata_json=?,updated_at=? WHERE source_id=?',(name,status,dumps(metadata) if metadata is not None else old['metadata_json'],now_ms(),ident))
    new=one(c,'SELECT * FROM sources WHERE source_id=?',(ident,));audit(c,a,'update',ident,old,new,old['workspace_id'],b.get('reason'))
   return {'ok':True,'item':new},200
  except sqlite3.IntegrityError:return err('SOURCE_CONFLICT','来源数据冲突',409)
 if m=='DELETE' and ident:
  with db.tx() as c:
   old=one(c,'SELECT * FROM sources WHERE source_id=? AND organization_id=?',(ident,org))
   if not old:return err('SOURCE_NOT_FOUND','来源不存在',404)
   if not (is_admin(db,a) or can(db,a,'source.manage',workspace_id=old.get('workspace_id'),team_id=old.get('team_id'),organization_id=org)):return err('FORBIDDEN','来源超出管理范围',403)
   rr=refs(c,ident)
   if any(rr.values()):return err('SOURCE_IN_USE','来源仍被业务对象引用，无法删除',409,references=rr)
   c.execute('DELETE FROM source_devices WHERE source_id=?',(ident,))
   c.execute('DELETE FROM sources WHERE source_id=?',(ident,))
   audit(c,a,'delete',ident,old,{},old['workspace_id'],b.get('reason'))
  return {'ok':True},200
 return err('METHOD_NOT_ALLOWED','来源接口不支持该方法',405)
