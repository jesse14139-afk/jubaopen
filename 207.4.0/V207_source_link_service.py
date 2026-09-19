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

TYPES={'redirects_to','lands_on','converts_to','routes_to','belongs_to','derived_from','referred_by'}
def cycle(c,org,wid,fr,to,exclude=None):
 if fr==to:return True
 seen=set();stack=[to]
 while stack:
  cur=stack.pop()
  if cur==fr:return True
  if cur in seen:continue
  seen.add(cur)
  sql='SELECT to_source_id FROM source_links WHERE organization_id=? AND workspace_id=? AND from_source_id=?';args=[org,wid,cur]
  if exclude:sql+=' AND source_link_id<>?';args.append(exclude)
  stack.extend(x[0] for x in c.execute(sql,args))
 return False
def handle(db,a,org,m,ident,q,b):
 perm='source.path.read' if m=='GET' else 'source.path.manage'
 if not (allowed(db,a,org,perm) or (m=='GET' and allowed(db,a,org,'source.path.manage'))):return err('FORBIDDEN','无来源路径权限',403)
 if m=='GET':
  with db.tx(False) as c:
   wh=['l.organization_id=?'];args=[org]
   if q.get('workspaceId'):wh.append('l.workspace_id=?');args.append(str(q['workspaceId']))
   its=rows(c,'SELECT l.*,f.source_name from_source_name,t.source_name to_source_name FROM source_links l JOIN sources f ON f.source_id=l.from_source_id JOIN sources t ON t.source_id=l.to_source_id WHERE '+' AND '.join(wh)+' ORDER BY l.sort_order,l.created_at',args)
  return {'ok':True,'items':its},200
 if m=='POST' and not ident:
  fr=str(b.get('fromSourceId') or '');to=str(b.get('toSourceId') or '');typ=str(b.get('type') or b.get('linkType') or '')
  if typ not in TYPES:return err('INVALID_LINK_TYPE','来源关系类型无效')
  try:meta=obj(b.get('metadata'));order=int(b.get('sortOrder') or 0)
  except (ValueError,TypeError):return err('INVALID_SOURCE_LINK','metadata 或排序值无效')
  try:
   with db.tx() as c:
    fs=one(c,'SELECT * FROM sources WHERE source_id=? AND organization_id=?',(fr,org));ts=one(c,'SELECT * FROM sources WHERE source_id=? AND organization_id=?',(to,org))
    if not fs or not ts or fs['workspace_id']!=ts['workspace_id']:return err('SCOPE_MISMATCH','来源节点必须属于同一企业工作区',409)
    if cycle(c,org,fs['workspace_id'],fr,to):return err('SOURCE_LINK_CYCLE','来源路径不能形成环',409)
    lid='lnk_'+uuid.uuid4().hex;n=now_ms();c.execute('INSERT INTO source_links(source_link_id,organization_id,workspace_id,from_source_id,to_source_id,link_type,sort_order,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(lid,org,fs['workspace_id'],fr,to,typ,order,dumps(meta),n,n));new=one(c,'SELECT * FROM source_links WHERE source_link_id=?',(lid,));audit(c,a,'create','source_link',lid,{},new,fs['workspace_id'],b.get('reason'))
   return {'ok':True,'sourceLinkId':lid,'item':new},201
  except sqlite3.IntegrityError:return err('SOURCE_LINK_CONFLICT','来源关系已存在',409)
 if m=='DELETE' and ident:
  with db.tx() as c:
   old=one(c,'SELECT * FROM source_links WHERE source_link_id=? AND organization_id=?',(ident,org))
   if not old:return err('SOURCE_LINK_NOT_FOUND','来源关系不存在',404)
   c.execute('DELETE FROM source_links WHERE source_link_id=?',(ident,));audit(c,a,'delete','source_link',ident,old,{},old['workspace_id'],b.get('reason'))
  return {'ok':True},200
 return err('METHOD_NOT_ALLOWED','来源路径接口不支持该方法',405)
