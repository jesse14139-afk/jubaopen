# -*- coding: utf-8 -*-
import json,sqlite3,uuid
from V207_shared_db import now_ms,dumps
from V207_security import can,is_platform_admin
def one(c,s,a=()):
 r=c.execute(s,a).fetchone();return dict(r) if r else None
def rows(c,s,a=()):return [dict(r) for r in c.execute(s,a)]
def err(code,msg,status=400,**extra):return ({'ok':False,'code':code,'message':msg,**extra},status)
def allowed(db,a,org,perm):return bool(org) and (is_platform_admin(db,a) or (a.get('organization_id')==org and can(db,a,perm)))
def audit(c,a,op,typ,eid,before,after,wid,reason=None):c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(wid,a['user_id'],None,op,typ,eid,dumps(before or {}),dumps(after or {}),reason,now_ms()))
def obj(v):
 if v is None:return {}
 if not isinstance(v,dict):raise ValueError
 return v

DIRECTIONS={'inbound','outbound','bidirectional','unknown'}
INITIATORS={'customer','business','system','unknown'}
def handle(db,a,org,m,ident,q,b):
 perm='touchpoint.read' if m=='GET' else 'touchpoint.manage'
 if not (allowed(db,a,org,perm) or (m=='GET' and allowed(db,a,org,'touchpoint.manage'))):return err('FORBIDDEN','无触点读取权限' if m=='GET' else '无触点管理权限',403)
 if m=='GET':
  with db.tx(False) as c:
   base='SELECT x.*,s.source_name,ct.display_name contact_name FROM source_touchpoints x JOIN sources s ON s.source_id=x.source_id LEFT JOIN contacts ct ON ct.contact_id=x.contact_id'
   if ident:
    x=one(c,base+' WHERE x.touchpoint_id=? AND x.organization_id=?',(ident,org));return ({'ok':True,'item':x},200) if x else err('TOUCHPOINT_NOT_FOUND','触点不存在',404)
   wh=['x.organization_id=?'];args=[org]
   for key,col in [('workspaceId','x.workspace_id'),('contactId','x.contact_id'),('sourceId','x.source_id'),('campaignId','x.campaign_id'),('sessionId','x.session_id')]:
    if q.get(key) not in (None,''):wh.append(col+'=?');args.append(str(q[key]))
   return {'ok':True,'items':rows(c,base+' WHERE '+' AND '.join(wh)+' ORDER BY x.occurred_at DESC,x.touchpoint_id DESC LIMIT 1000',args)},200
 if m=='POST' and not ident:
  sid=str(b.get('sourceId') or '').strip();cid=str(b.get('contactId') or '').strip() or None;direction=str(b.get('direction') or 'inbound');initiated=str(b.get('initiatedBy') or 'unknown');typ=str(b.get('type') or 'unknown').strip();ext=str(b.get('externalEventId') or '').strip() or None
  if not sid:return err('SOURCE_REQUIRED','sourceId 必填')
  if not typ or len(typ)>64:return err('INVALID_TOUCHPOINT_TYPE','触点类型无效')
  if direction not in DIRECTIONS:return err('INVALID_DIRECTION','触点方向无效')
  if initiated not in INITIATORS:return err('INVALID_INITIATED_BY','触点发起方无效')
  try:meta=obj(b.get('metadata'));occurred=int(b.get('occurredAt') or now_ms())
  except (ValueError,TypeError):return err('INVALID_TOUCHPOINT','metadata 必须是对象且 occurredAt 必须为整数')
  try:
   with db.tx() as c:
    sr=one(c,'SELECT * FROM sources WHERE source_id=? AND organization_id=?',(sid,org))
    if not sr:return err('SOURCE_NOT_FOUND','来源不存在',404)
    wid=sr['workspace_id']
    if cid and not one(c,'SELECT 1 FROM contacts WHERE contact_id=? AND organization_id=? AND workspace_id=?',(cid,org,wid)):return err('CONTACT_SCOPE_MISMATCH','联系人不存在或不属于来源工作区',409)
    for key,table,idcol,label in [('campaignId','campaigns','campaign_id','活动'),('channelAccountId','channel_accounts','channel_account_id','渠道账号')]:
     supplied=b.get(key);expected=sr.get('campaign_id' if key=='campaignId' else 'channel_account_id')
     if supplied and str(supplied)!=str(expected or ''):return err('SOURCE_REFERENCE_MISMATCH',label+'必须与来源一致',409)
    if b.get('platformId') and str(b['platformId'])!=str(sr.get('platform_id') or ''):return err('SOURCE_REFERENCE_MISMATCH','平台必须与来源一致',409)
    if ext:
     old=one(c,'SELECT * FROM source_touchpoints WHERE organization_id=? AND workspace_id=? AND external_event_id=?',(org,wid,ext))
     if old:return {'ok':True,'touchpointId':old['touchpoint_id'],'item':old,'idempotent':True},200
    tid='tch_'+uuid.uuid4().hex;n=now_ms();c.execute('INSERT INTO source_touchpoints(touchpoint_id,organization_id,workspace_id,source_id,contact_id,platform_id,channel_account_id,campaign_id,touchpoint_type,direction,initiated_by,external_event_id,session_id,occurred_at,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(tid,org,wid,sid,cid,sr.get('platform_id'),sr.get('channel_account_id'),sr.get('campaign_id'),typ,direction,initiated,ext,b.get('sessionId'),occurred,dumps(meta),n));new=one(c,'SELECT * FROM source_touchpoints WHERE touchpoint_id=?',(tid,));audit(c,a,'create','source_touchpoint',tid,{},new,wid,b.get('reason'))
   return {'ok':True,'touchpointId':tid,'item':new},201
  except sqlite3.IntegrityError:return err('TOUCHPOINT_CONFLICT','触点数据冲突',409)
 if m=='PATCH' and ident and b.get('contactId'):
  cid=str(b['contactId'])
  with db.tx() as c:
   old=one(c,'SELECT * FROM source_touchpoints WHERE touchpoint_id=? AND organization_id=?',(ident,org))
   if not old:return err('TOUCHPOINT_NOT_FOUND','触点不存在',404)
   if not one(c,'SELECT 1 FROM contacts WHERE contact_id=? AND organization_id=? AND workspace_id=?',(cid,org,old['workspace_id'])):return err('CONTACT_SCOPE_MISMATCH','联系人不存在或不属于触点工作区',409)
   c.execute('UPDATE source_touchpoints SET contact_id=? WHERE touchpoint_id=?',(cid,ident));new=one(c,'SELECT * FROM source_touchpoints WHERE touchpoint_id=?',(ident,));audit(c,a,'bind_contact','source_touchpoint',ident,old,new,old['workspace_id'],b.get('reason'))
  return {'ok':True,'item':new},200
 return err('METHOD_NOT_ALLOWED','触点接口不支持该方法',405)
