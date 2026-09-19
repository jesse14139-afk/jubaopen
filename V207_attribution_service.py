# -*- coding: utf-8 -*-
import json,sqlite3,uuid
from V207_shared_db import now_ms,dumps
from V207_security import can
def one(c,s,a=()):
 r=c.execute(s,a).fetchone();return dict(r) if r else None
def rows(c,s,a=()):return [dict(r) for r in c.execute(s,a)]
def err(code,msg,status=400,**extra):return ({'ok':False,'code':code,'message':msg,**extra},status)
def allowed(db,a,org,perm):return bool(org) and (a.get('user_id')=='usr_admin' or (a.get('organization_id')==org and can(db,a,perm)))
def audit(c,a,op,typ,eid,before,after,wid,reason=None):c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(wid,a['user_id'],None,op,typ,eid,dumps(before or {}),dumps(after or {}),reason,now_ms()))
def obj(v):
 if v is None:return {}
 if not isinstance(v,dict):raise ValueError
 return v

TYPES={'first_touch','last_touch','conversion','primary','assisted','referral'}
def _insert(c,org,wid,cid,tp,typ,primary,meta,confidence='deterministic',weight=None):
 aid='atr_'+uuid.uuid4().hex;c.execute('INSERT INTO contact_attributions(attribution_id,organization_id,workspace_id,contact_id,source_id,touchpoint_id,attribution_type,attribution_weight,confidence,is_primary,attributed_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(aid,org,wid,cid,tp['source_id'],tp.get('touchpoint_id'),typ,weight,confidence,primary,now_ms(),dumps(meta)));return aid
def recalculate_tx(c,a,org,cid):
 cr=one(c,'SELECT * FROM contacts WHERE contact_id=? AND organization_id=?',(cid,org))
 if not cr:raise LookupError
 tps=rows(c,'SELECT * FROM source_touchpoints WHERE organization_id=? AND workspace_id=? AND contact_id=? ORDER BY occurred_at,touchpoint_id',(org,cr['workspace_id'],cid))
 old=rows(c,"SELECT * FROM contact_attributions WHERE organization_id=? AND contact_id=? AND json_extract(metadata_json,'$.generatedBy')='deterministic_engine'",(org,cid))
 c.execute("DELETE FROM contact_attributions WHERE organization_id=? AND contact_id=? AND json_extract(metadata_json,'$.generatedBy')='deterministic_engine'",(org,cid))
 ids=[];meta={'generatedBy':'deterministic_engine','ruleVersion':'207.2.0-1','calculatedAt':now_ms()}
 if tps:
  ids.append(_insert(c,org,cr['workspace_id'],cid,tps[0],'first_touch',0,meta))
  ids.append(_insert(c,org,cr['workspace_id'],cid,tps[-1],'last_touch',0,meta))
  mids=[];seen={tps[0]['source_id'],tps[-1]['source_id']}
  for tp in tps[1:-1]:
   if tp['source_id'] not in seen:mids.append(tp);seen.add(tp['source_id'])
  for tp in mids:ids.append(_insert(c,org,cr['workspace_id'],cid,tp,'assisted',0,meta))
 audit(c,a,'recalculate','contact_attribution',cid,{'automatic':len(old)},{'automatic':len(ids)},cr['workspace_id'])
 return ids
def handle(db,a,org,m,ident,q,b):
 recalc=(m=='POST' and (ident=='recalculate' or b.get('recalculate')))
 perm='attribution.recalculate' if recalc else ('attribution.read' if m=='GET' else 'attribution.manage')
 if not (allowed(db,a,org,perm) or (m=='GET' and allowed(db,a,org,'attribution.manage'))):return err('FORBIDDEN','无归因权限',403)
 if m=='GET':
  with db.tx(False) as c:
   wh=['a.organization_id=?'];args=[org]
   if q.get('contactId'):wh.append('a.contact_id=?');args.append(str(q['contactId']))
   its=rows(c,'SELECT a.*,s.source_name,ct.display_name contact_name FROM contact_attributions a JOIN sources s ON s.source_id=a.source_id JOIN contacts ct ON ct.contact_id=a.contact_id WHERE '+' AND '.join(wh)+' ORDER BY a.attributed_at DESC LIMIT 1000',args)
  return {'ok':True,'items':its},200
 if recalc:
  cid=str(b.get('contactId') or q.get('contactId') or '').strip()
  if not cid:return err('CONTACT_REQUIRED','contactId 必填')
  try:
   with db.tx() as c:ids=recalculate_tx(c,a,org,cid)
   return {'ok':True,'contactId':cid,'attributionIds':ids,'count':len(ids)},200
  except LookupError:return err('CONTACT_NOT_FOUND','联系人不存在',404)
 if m=='POST' and not ident:
  cid=str(b.get('contactId') or '');sid=str(b.get('sourceId') or '');tpid=str(b.get('touchpointId') or '').strip() or None;typ=str(b.get('type') or 'primary')
  if typ not in TYPES:return err('INVALID_ATTRIBUTION_TYPE','归因类型无效')
  try:meta=obj(b.get('metadata'))
  except ValueError:return err('INVALID_ATTRIBUTION_JSON','metadata 必须是对象')
  with db.tx() as c:
   cr=one(c,'SELECT * FROM contacts WHERE contact_id=? AND organization_id=?',(cid,org));sr=one(c,'SELECT * FROM sources WHERE source_id=? AND organization_id=?',(sid,org))
   if not cr or not sr or cr['workspace_id']!=sr['workspace_id']:return err('SCOPE_MISMATCH','联系人和来源必须属于同一企业工作区',409)
   tp=None
   if tpid:
    tp=one(c,'SELECT * FROM source_touchpoints WHERE touchpoint_id=? AND organization_id=? AND workspace_id=?',(tpid,org,cr['workspace_id']))
    if not tp or tp.get('contact_id')!=cid or tp['source_id']!=sid:return err('TOUCHPOINT_SCOPE_MISMATCH','触点必须属于同一联系人和来源',409)
   primary=1 if typ=='primary' or b.get('isPrimary') else 0
   if primary:c.execute('UPDATE contact_attributions SET is_primary=0 WHERE organization_id=? AND workspace_id=? AND contact_id=?',(org,cr['workspace_id'],cid))
   aid='atr_'+uuid.uuid4().hex;n=now_ms();meta={**meta,'generatedBy':'manual','ruleVersion':'manual'};c.execute('INSERT INTO contact_attributions(attribution_id,organization_id,workspace_id,contact_id,source_id,touchpoint_id,attribution_type,attribution_weight,confidence,is_primary,attributed_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(aid,org,cr['workspace_id'],cid,sid,tpid,typ,b.get('weight'),str(b.get('confidence') or 'manual'),primary,n,dumps(meta)));new=one(c,'SELECT * FROM contact_attributions WHERE attribution_id=?',(aid,));audit(c,a,'create','contact_attribution',aid,{},new,cr['workspace_id'],b.get('reason'))
  return {'ok':True,'attributionId':aid,'item':new},201
 return err('METHOD_NOT_ALLOWED','归因接口不支持该方法',405)
