# -*- coding: utf-8 -*-
"""S4 touchpoint service: scoped access, conflict-aware idempotency and nullable event time."""
import json,sqlite3,uuid
from V207_shared_db import now_ms,dumps
from V207_security import can,is_platform_admin

def one(c,s,a=()):
 r=c.execute(s,a).fetchone();return dict(r) if r else None
def rows(c,s,a=()):return [dict(r) for r in c.execute(s,a)]
def err(code,msg,status=400,**extra):return ({'ok':False,'code':code,'message':msg,**extra},status)
def audit(c,a,op,typ,eid,before,after,wid,reason=None):c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(wid,a['user_id'],None,op,typ,eid,dumps(before or {}),dumps(after or {}),reason,now_ms()))
def obj(v):
 if v is None:return {}
 if not isinstance(v,dict):raise ValueError
 return v
def _scope_allowed(db,a,org,perm,wid=None,team=None):
 return bool(org) and (is_platform_admin(db,a) or (a.get('organization_id')==org and can(db,a,perm,workspace_id=wid,team_id=team,organization_id=org)))
def _read_allowed(db,a,org,wid=None,team=None):
 return _scope_allowed(db,a,org,'touchpoint.read',wid,team) or _scope_allowed(db,a,org,'touchpoint.manage',wid,team)
def _integer(v,name,minimum=0,maximum=None):
 try:n=int(v)
 except (TypeError,ValueError):raise ValueError(name)
 if n<minimum or (maximum is not None and n>maximum):raise ValueError(name)
 return n
def _canonical_meta(v):return json.dumps(v or {},ensure_ascii=False,separators=(',',':'),sort_keys=True)
def _same(old,want):
 try:old_meta=json.loads(old.get('metadata_json') or '{}')
 except Exception:return False
 actual={'source_id':old.get('source_id'),'contact_id':old.get('contact_id'),'touchpoint_type':old.get('touchpoint_type'),'direction':old.get('direction'),'initiated_by':old.get('initiated_by'),'external_event_id':old.get('external_event_id'),'event_key':old.get('event_key'),'session_id':old.get('session_id'),'occurred_at':old.get('occurred_at'),'metadata':old_meta}
 return _canonical_meta(actual)==_canonical_meta(want)

DIRECTIONS={'inbound','outbound','bidirectional','unknown'}
INITIATORS={'customer','business','system','unknown'}

def handle(db,a,org,m,ident,q,b):
 if not org or (a.get('organization_id')!=org and not is_platform_admin(db,a)):return err('FORBIDDEN','无触点权限',403)
 if m=='GET':
  wid=str(q.get('workspaceId') or '').strip() or None;team=str(q.get('teamId') or '').strip() or None
  try:limit=_integer(q.get('limit',100),'limit',1,200);offset=_integer(q.get('offset',0),'offset',0,1000000)
  except ValueError:return err('INVALID_PAGINATION','limit 必须为 1..200，offset 必须为 0..1000000')
  with db.tx(False) as c:
   base='SELECT x.*,s.source_name,s.team_id,ct.display_name contact_name FROM source_touchpoints x JOIN sources s ON s.source_id=x.source_id LEFT JOIN contacts ct ON ct.contact_id=x.contact_id'
   if ident:
    x=one(c,base+' WHERE x.touchpoint_id=? AND x.organization_id=?',(ident,org))
    if not x:return err('TOUCHPOINT_NOT_FOUND','触点不存在',404)
    if not _read_allowed(db,a,org,x['workspace_id'],x.get('team_id')):return err('FORBIDDEN','无触点读取权限',403)
    return {'ok':True,'item':x},200
   wh=['x.organization_id=?'];args=[org]
   if wid or team:
    if not _read_allowed(db,a,org,wid,team):return err('FORBIDDEN','无触点读取权限',403)
   else:
    # An unscoped list must not turn the default-workspace permission check into
    # organization-wide access. Build the row predicate from active bindings.
    platform=bool(c.execute('SELECT 1 FROM platform_administrators WHERE user_id=?',(a.get('user_id'),)).fetchone())
    grants=rows(c,"SELECT DISTINCT b.scope_type,b.scope_id FROM role_bindings b JOIN roles r ON r.role_id=b.role_id AND r.status='active' JOIN role_permissions rp ON rp.role_id=b.role_id WHERE b.user_id=? AND b.status='active' AND b.organization_id=? AND rp.permission_key IN ('touchpoint.read','touchpoint.manage')",(a.get('user_id'),org))
    if not platform and not any(g['scope_type']=='organization' and g['scope_id']==org for g in grants):
     workspaces=sorted({g['scope_id'] for g in grants if g['scope_type']=='workspace'})
     teams=sorted({g['scope_id'] for g in grants if g['scope_type']=='team'})
     scoped=[]
     if workspaces:scoped.append('x.workspace_id IN ('+','.join('?'*len(workspaces))+')');args.extend(workspaces)
     if teams:scoped.append('s.team_id IN ('+','.join('?'*len(teams))+')');args.extend(teams)
     if not scoped:return err('FORBIDDEN','无触点读取权限',403)
     wh.append('('+' OR '.join(scoped)+')')
   for key,col in [('workspaceId','x.workspace_id'),('teamId','s.team_id'),('contactId','x.contact_id'),('sourceId','x.source_id'),('campaignId','x.campaign_id'),('sessionId','x.session_id')]:
    if q.get(key) not in (None,''):wh.append(col+'=?');args.append(str(q[key]))
   where=' WHERE '+' AND '.join(wh);total=c.execute('SELECT count(*) FROM source_touchpoints x JOIN sources s ON s.source_id=x.source_id'+where,args).fetchone()[0]
   sql=base+where+' ORDER BY x.occurred_at IS NULL ASC,x.occurred_at DESC,x.created_at DESC,x.touchpoint_id DESC LIMIT ? OFFSET ?'
   its=rows(c,sql,args+[limit,offset])
  return {'ok':True,'items':its,'page':{'limit':limit,'offset':offset,'total':total,'hasMore':offset+len(its)<total}},200
 if m=='POST' and not ident:
  sid=str(b.get('sourceId') or '').strip();cid=str(b.get('contactId') or '').strip() or None;direction=str(b.get('direction') or 'inbound');initiated=str(b.get('initiatedBy') or 'unknown').strip().lower();initiated='customer' if initiated=='contact' else initiated;typ=str(b.get('type') or 'unknown').strip();ext=str(b.get('externalEventId') or '').strip() or None;event_key=str(b.get('eventKey') or '').strip() or None;session=str(b.get('sessionId') or '').strip() or None
  if not sid:return err('SOURCE_REQUIRED','sourceId 必填')
  if not typ or len(typ)>64:return err('INVALID_TOUCHPOINT_TYPE','触点类型无效')
  if direction not in DIRECTIONS:return err('INVALID_DIRECTION','触点方向无效')
  if initiated not in INITIATORS:return err('INVALID_INITIATED_BY','触点发起方无效')
  if ext and len(ext)>255:return err('INVALID_EXTERNAL_EVENT_ID','externalEventId 过长')
  if event_key and len(event_key)>255:return err('INVALID_EVENT_KEY','eventKey 过长')
  try:
   meta=obj(b.get('metadata'));occurred=None if b.get('occurredAt') in (None,'') else _integer(b.get('occurredAt'),'occurredAt',0)
  except ValueError:return err('INVALID_TOUCHPOINT','metadata 必须是对象且 occurredAt 必须为非负整数或空')
  try:
   with db.tx() as c:
    sr=one(c,'SELECT * FROM sources WHERE source_id=? AND organization_id=?',(sid,org))
    if not sr:return err('SOURCE_NOT_FOUND','来源不存在',404)
    wid=sr['workspace_id'];team=sr.get('team_id')
    if not _scope_allowed(db,a,org,'touchpoint.manage',wid,team):return err('FORBIDDEN','无触点管理权限',403)
    if cid and not one(c,'SELECT 1 FROM contacts WHERE contact_id=? AND organization_id=? AND workspace_id=?',(cid,org,wid)):return err('CONTACT_SCOPE_MISMATCH','联系人不存在或不属于来源工作区',409)
    for key,label,col in [('campaignId','活动','campaign_id'),('channelAccountId','渠道账号','channel_account_id')]:
     supplied=b.get(key);expected=sr.get(col)
     if supplied and str(supplied)!=str(expected or ''):return err('SOURCE_REFERENCE_MISMATCH',label+'必须与来源一致',409)
    if b.get('platformId') and str(b['platformId'])!=str(sr.get('platform_id') or ''):return err('SOURCE_REFERENCE_MISMATCH','平台必须与来源一致',409)
    want={'source_id':sid,'contact_id':cid,'touchpoint_type':typ,'direction':direction,'initiated_by':initiated,'external_event_id':ext,'event_key':event_key,'session_id':session,'occurred_at':occurred,'metadata':meta}
    found=[]
    if event_key:found+=rows(c,'SELECT * FROM source_touchpoints WHERE organization_id=? AND workspace_id=? AND event_key=?',(org,wid,event_key))
    if ext:found+=rows(c,'SELECT * FROM source_touchpoints WHERE organization_id=? AND workspace_id=? AND external_event_id=?',(org,wid,ext))
    unique={x['touchpoint_id']:x for x in found}
    if len(unique)>1:return err('TOUCHPOINT_IDEMPOTENCY_KEY_COLLISION','eventKey 与 externalEventId 指向不同触点',409)
    if unique:
     old=next(iter(unique.values()))
     if not _same(old,want):return err('TOUCHPOINT_IDEMPOTENCY_CONFLICT','幂等键已被不同请求使用',409,touchpointId=old['touchpoint_id'])
     return {'ok':True,'touchpointId':old['touchpoint_id'],'item':old,'idempotent':True},200
    tid='tch_'+uuid.uuid4().hex;n=now_ms();c.execute('INSERT INTO source_touchpoints(touchpoint_id,organization_id,workspace_id,source_id,contact_id,platform_id,channel_account_id,campaign_id,touchpoint_type,direction,initiated_by,external_event_id,event_key,session_id,occurred_at,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(tid,org,wid,sid,cid,sr.get('platform_id'),sr.get('channel_account_id'),sr.get('campaign_id'),typ,direction,initiated,ext,event_key,session,occurred,dumps(meta),n));new=one(c,'SELECT * FROM source_touchpoints WHERE touchpoint_id=?',(tid,));audit(c,a,'create','source_touchpoint',tid,{},new,wid,b.get('reason'))
   return {'ok':True,'touchpointId':tid,'item':new},201
  except sqlite3.IntegrityError:return err('TOUCHPOINT_CONFLICT','触点数据冲突',409)
 if m=='PATCH' and ident and b.get('contactId'):
  cid=str(b['contactId'])
  with db.tx() as c:
   old=one(c,'SELECT x.*,s.team_id FROM source_touchpoints x JOIN sources s ON s.source_id=x.source_id WHERE x.touchpoint_id=? AND x.organization_id=?',(ident,org))
   if not old:return err('TOUCHPOINT_NOT_FOUND','触点不存在',404)
   if not _scope_allowed(db,a,org,'touchpoint.manage',old['workspace_id'],old.get('team_id')):return err('FORBIDDEN','无触点管理权限',403)
   if not one(c,'SELECT 1 FROM contacts WHERE contact_id=? AND organization_id=? AND workspace_id=?',(cid,org,old['workspace_id'])):return err('CONTACT_SCOPE_MISMATCH','联系人不存在或不属于触点工作区',409)
   c.execute('UPDATE source_touchpoints SET contact_id=? WHERE touchpoint_id=?',(cid,ident));new=one(c,'SELECT * FROM source_touchpoints WHERE touchpoint_id=?',(ident,));audit(c,a,'bind_contact','source_touchpoint',ident,old,new,old['workspace_id'],b.get('reason'))
  return {'ok':True,'item':new},200
 return err('METHOD_NOT_ALLOWED','触点接口不支持该方法',405)
