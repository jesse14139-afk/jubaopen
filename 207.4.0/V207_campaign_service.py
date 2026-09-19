# -*- coding: utf-8 -*-
"""V207.1 活动领域服务。"""
import json,sqlite3,uuid
from V207_shared_db import now_ms,dumps
from V207_security import can
STATUSES={'draft','active','paused','completed','disabled'}
TYPES={'marketing','paid','organic','referral','event','promotion','retention','other'}
def one(c,s,a=()):
 x=c.execute(s,a).fetchone();return dict(x) if x else None
def rows(c,s,a=()):return [dict(x) for x in c.execute(s,a)]
def err(code,msg,status=400,**extra):return {'ok':False,'code':code,'message':msg,**extra},status
def admin(a):return bool(a and a.get('user_id')=='usr_admin')
def allowed(db,a,org,perm):return bool(org) and (admin(a) or (a.get('organization_id')==org and can(db,a,perm)))
def audit(c,a,op,eid,before,after,wid,reason=None):c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(wid,a['user_id'],None,op,'campaign',eid,dumps(before or {}),dumps(after or {}),reason,now_ms()))
def metadata(v):
 if v is None:return {}
 if not isinstance(v,dict):raise ValueError
 return v
def validate(c,org,wid,platform,account):
 w=one(c,"SELECT * FROM workspaces WHERE workspace_id=? AND organization_id=? AND status='active'",(wid,org))
 if not w:return ('WORKSPACE_NOT_FOUND','工作区不存在或未启用',404)
 acc=None
 if platform:
  if not one(c,"SELECT 1 FROM platforms WHERE platform_id=? AND status='active'",(platform,)):return ('PLATFORM_NOT_FOUND','平台不存在或未启用',404)
 if account:
  acc=one(c,"SELECT * FROM channel_accounts WHERE channel_account_id=? AND organization_id=? AND status='active'",(account,org))
  if not acc:return ('ACCOUNT_NOT_FOUND','渠道账号不存在或未启用',404)
  if platform and acc.get('platform_id')!=platform:return ('PLATFORM_MISMATCH','活动平台必须与渠道账号平台一致',409)
  if not platform:platform=acc.get('platform_id')
  granted=c.execute('SELECT count(*) FROM team_channel_accounts g JOIN teams t ON t.team_id=g.team_id WHERE g.channel_account_id=? AND t.organization_id=? AND t.workspace_id=? AND t.status=?',(account,org,wid,'active')).fetchone()[0]
  if not granted:return ('ACCOUNT_NOT_GRANTED','渠道账号未授权给目标工作区的团队',409)
 return platform,acc
def refs(c,cid):return {'activeSources':c.execute("SELECT count(*) FROM sources WHERE campaign_id=? AND status='active'",(cid,)).fetchone()[0],'touchpoints':c.execute('SELECT count(*) FROM source_touchpoints WHERE campaign_id=?',(cid,)).fetchone()[0]}
def handle(db,a,org,m,ident,q,b):
 perm='campaign.read' if m=='GET' else 'campaign.manage'
 # 兼容旧角色模型：具备 manage 即可读；平台管理员不受企业 RBAC 限制
 if not (allowed(db,a,org,perm) or (m=='GET' and allowed(db,a,org,'campaign.manage'))):return err('FORBIDDEN','无活动读取权限' if m=='GET' else '无活动管理权限',403)
 if m=='GET':
  with db.tx(False) as c:
   base='SELECT c.*,p.platform_name,ca.display_name account_name,w.name workspace_name FROM campaigns c LEFT JOIN platforms p ON p.platform_id=c.platform_id LEFT JOIN channel_accounts ca ON ca.channel_account_id=c.channel_account_id LEFT JOIN workspaces w ON w.workspace_id=c.workspace_id'
   if ident:
    x=one(c,base+' WHERE c.campaign_id=? AND c.organization_id=?',(ident,org));return ({'ok':True,'item':x},200) if x else err('CAMPAIGN_NOT_FOUND','活动不存在',404)
   wh=['c.organization_id=?'];args=[org]
   for k,col in [('workspaceId','c.workspace_id'),('workspace_id','c.workspace_id'),('platformId','c.platform_id'),('platform_id','c.platform_id'),('channelAccountId','c.channel_account_id'),('channel_account_id','c.channel_account_id'),('status','c.status'),('type','c.campaign_type')]:
    if q.get(k) not in (None,''):wh.append(col+'=?');args.append(str(q[k]))
   return {'ok':True,'items':rows(c,base+' WHERE '+' AND '.join(wh)+' ORDER BY c.created_at DESC',args)},200
 if m=='POST' and not ident:
  wid=str(b.get('workspaceId') or b.get('workspace_id') or '').strip();name=str(b.get('name') or b.get('campaignName') or '').strip();code=str(b.get('code') or b.get('campaignCode') or '').strip() or None;typ=str(b.get('type') or 'marketing');status=str(b.get('status') or 'draft');platform=str(b.get('platformId') or '').strip() or None;account=str(b.get('channelAccountId') or '').strip() or None
  if not wid:return err('WORKSPACE_REQUIRED','workspaceId 必填')
  if not name or len(name)>128:return err('INVALID_CAMPAIGN_NAME','活动名称不能为空且不得超过 128 字符')
  if code and len(code)>128:return err('INVALID_CAMPAIGN_CODE','活动代码不得超过 128 字符')
  if typ not in TYPES:return err('INVALID_CAMPAIGN_TYPE','活动类型无效')
  if status not in STATUSES:return err('INVALID_CAMPAIGN_STATUS','活动状态无效')
  try:meta=metadata(b.get('metadata'))
  except ValueError:return err('INVALID_CAMPAIGN_JSON','metadata 必须是 JSON 对象')
  start=b.get('startAt');end=b.get('endAt')
  if start is not None and end is not None and int(end)<int(start):return err('INVALID_CAMPAIGN_PERIOD','活动结束时间不得早于开始时间')
  try:
   with db.tx() as c:
    vr=validate(c,org,wid,platform,account)
    if isinstance(vr,tuple) and len(vr)==3 and isinstance(vr[2],int):return err(*vr)
    platform,_=vr
    if code and one(c,'SELECT 1 FROM campaigns WHERE organization_id=? AND workspace_id=? AND campaign_code=?',(org,wid,code)):return err('CAMPAIGN_CODE_CONFLICT','活动代码在目标工作区已存在',409)
    cid='cmp_'+uuid.uuid4().hex;n=now_ms();c.execute('INSERT INTO campaigns(campaign_id,organization_id,workspace_id,platform_id,channel_account_id,campaign_code,campaign_name,campaign_type,status,start_at,end_at,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(cid,org,wid,platform,account,code,name,typ,status,start,end,dumps(meta),n,n));new=one(c,'SELECT * FROM campaigns WHERE campaign_id=?',(cid,));audit(c,a,'create',cid,{},new,wid,b.get('reason'))
   return {'ok':True,'campaignId':cid,'item':new},201
  except (ValueError,TypeError):return err('INVALID_CAMPAIGN_PERIOD','活动时间必须为整数时间戳')
  except sqlite3.IntegrityError:return err('CAMPAIGN_CONFLICT','活动数据冲突',409)
 if m=='PATCH' and ident:
  try:
   with db.tx() as c:
    old=one(c,'SELECT * FROM campaigns WHERE campaign_id=? AND organization_id=?',(ident,org))
    if not old:return err('CAMPAIGN_NOT_FOUND','活动不存在',404)
    name=str(b.get('name') if 'name' in b else b.get('campaignName') if 'campaignName' in b else old['campaign_name']).strip();code=(str(b.get('code')).strip() or None) if 'code' in b else old['campaign_code'];typ=str(b.get('type',old['campaign_type']));status=str(b.get('status',old['status']));platform=(str(b.get('platformId')).strip() or None) if 'platformId' in b else old['platform_id'];account=(str(b.get('channelAccountId')).strip() or None) if 'channelAccountId' in b else old['channel_account_id'];start=b.get('startAt',old['start_at']);end=b.get('endAt',old['end_at'])
    if not name or len(name)>128:return err('INVALID_CAMPAIGN_NAME','活动名称不能为空且不得超过 128 字符')
    if typ not in TYPES:return err('INVALID_CAMPAIGN_TYPE','活动类型无效')
    if status not in STATUSES:return err('INVALID_CAMPAIGN_STATUS','活动状态无效')
    if start is not None and end is not None and int(end)<int(start):return err('INVALID_CAMPAIGN_PERIOD','活动结束时间不得早于开始时间')
    meta=metadata(b.get('metadata')) if 'metadata' in b else json.loads(old['metadata_json'] or '{}')
    vr=validate(c,org,old['workspace_id'],platform,account)
    if isinstance(vr,tuple) and len(vr)==3 and isinstance(vr[2],int):return err(*vr)
    platform,_=vr
    if code and one(c,'SELECT 1 FROM campaigns WHERE organization_id=? AND workspace_id=? AND campaign_code=? AND campaign_id<>?',(org,old['workspace_id'],code,ident)):return err('CAMPAIGN_CODE_CONFLICT','活动代码在目标工作区已存在',409)
    if old['status'] in ('active','paused') and status in ('completed','disabled'):
     rr=refs(c,ident)
     if any(rr.values()):return err('CAMPAIGN_IN_USE','活动仍被业务对象引用',409,references=rr)
    c.execute('UPDATE campaigns SET platform_id=?,channel_account_id=?,campaign_code=?,campaign_name=?,campaign_type=?,status=?,start_at=?,end_at=?,metadata_json=?,updated_at=? WHERE campaign_id=?',(platform,account,code,name,typ,status,start,end,dumps(meta),now_ms(),ident));new=one(c,'SELECT * FROM campaigns WHERE campaign_id=?',(ident,));audit(c,a,'update',ident,old,new,old['workspace_id'],b.get('reason'))
   return {'ok':True,'item':new},200
  except ValueError:return err('INVALID_CAMPAIGN_JSON','metadata 必须是 JSON 对象，且时间必须合法')
  except (TypeError,sqlite3.IntegrityError):return err('CAMPAIGN_CONFLICT','活动数据冲突',409)
 return err('METHOD_NOT_ALLOWED','活动接口不支持该方法',405)
