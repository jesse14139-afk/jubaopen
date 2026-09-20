# -*- coding: utf-8 -*-
"""V207.3 企业组织、业务线、市场及业务空间关系领域服务。"""
import sqlite3, uuid
from V207_shared_db import now_ms, dumps
from V207_security import can

STATUS={'active','disabled'}
REL_TYPES={'primary','collaborator','compliance','support'}
ACCESS={'read','operate','manage'}
MARKET_TYPES={'region','country','state','city','segment','other'}

def _one(c,sql,args=()):
 r=c.execute(sql,args).fetchone();return dict(r) if r else None
def _rows(c,sql,args=()):return [dict(x) for x in c.execute(sql,args)]
def _ok(**x):return ({'ok':True,**x},200)
def _err(code,msg,status=400,**x):return ({'ok':False,'code':code,'message':msg,**x},status)
def _id(prefix):return prefix+'_'+uuid.uuid4().hex
def _read(db,a,org):return bool(a and a.get('organization_id')==org and (can(db,a,'organization.structure.read') or can(db,a,'organization.read')))
def _manage(db,a,org):return bool(a and a.get('organization_id')==org and (can(db,a,'organization.structure.manage') or can(db,a,'organization.manage')))
def _audit(c,a,op,typ,eid,before,after,wid=None,reason=None):
 if not wid:raise RuntimeError('AUDIT_SCOPE_REQUIRED')
 c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at,organization_id,team_id,request_id,ip_address,user_agent,scope_type,scope_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(wid,a['user_id'],None,op,typ,eid,dumps(before or {}),dumps(after or {}),reason,now_ms(),a.get('organization_id'),None,None,None,None,'workspace',wid))
def _cycle(c,table,key,node,parent,org):
 seen={node};cur=parent
 while cur:
  if cur in seen:return True
  seen.add(cur);r=c.execute(f'SELECT parent_{key} FROM {table} WHERE {key}=? AND organization_id=?',(cur,org)).fetchone();cur=r[0] if r else None
 return False

def _entity(db,a,org,m,kind,ident,q,b):
 specs={
  'departments':('departments','department_id','dept','parent_department_id'),
  'business-lines':('business_lines','business_line_id','bl','parent_business_line_id'),
  'markets':('markets','market_id','mkt','parent_market_id')}
 table,key,prefix,parent_col=specs[kind]
 if m=='GET':
  if not _read(db,a,org):return _err('FORBIDDEN','无组织结构读取权限',403)
  with db.tx(False) as c:
   if ident:
    item=_one(c,f'SELECT * FROM {table} WHERE {key}=? AND organization_id=?',(ident,org))
    return _ok(item=item) if item else _err('NOT_FOUND','对象不存在',404)
   return _ok(items=_rows(c,f'SELECT * FROM {table} WHERE organization_id=? ORDER BY name,{key}',(org,)))
 if m=='POST':
  if not _manage(db,a,org):return _err('FORBIDDEN','无组织结构管理权限',403)
  name=str(b.get('name') or '').strip();code=str(b.get('code') or '').strip().lower();parent=str(b.get('parentId') or b.get(parent_col) or '').strip() or None
  if not name or not code:return _err('INVALID_INPUT','名称和编码不能为空')
  eid=str(b.get('id') or b.get(key) or _id(prefix));n=now_ms()
  try:
   with db.tx() as c:
    if parent and not c.execute(f'SELECT 1 FROM {table} WHERE {key}=? AND organization_id=?',(parent,org)).fetchone():return _err('PARENT_NOT_FOUND','上级对象不存在',404)
    if kind=='departments':
     c.execute('INSERT INTO departments(department_id,organization_id,parent_department_id,name,code,description,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(eid,org,parent,name,code,str(b.get('description') or ''),'active',n,n))
    elif kind=='business-lines':
     c.execute('INSERT INTO business_lines(business_line_id,organization_id,parent_business_line_id,name,code,description,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(eid,org,parent,name,code,str(b.get('description') or ''),'active',n,n))
    else:
     mt=str(b.get('marketType') or 'country');
     if mt not in MARKET_TYPES:return _err('INVALID_MARKET_TYPE','市场类型无效')
     c.execute('INSERT INTO markets(market_id,organization_id,parent_market_id,name,code,market_type,country_code,region_code,timezone,description,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(eid,org,parent,name,code,mt,str(b.get('countryCode') or '').upper(),str(b.get('regionCode') or ''),str(b.get('timezone') or ''),str(b.get('description') or ''),'active',n,n))
    item=_one(c,f'SELECT * FROM {table} WHERE {key}=?',(eid,));aw=c.execute('SELECT workspace_id FROM workspaces WHERE organization_id=? ORDER BY workspace_id LIMIT 1',(org,)).fetchone();
    if not aw:raise RuntimeError('AUDIT_WORKSPACE_REQUIRED')
    _audit(c,a,'create',kind,eid,{},item,aw[0])
   return ({'ok':True,'item':item},201)
  except sqlite3.IntegrityError:return _err('CONFLICT','编码、名称或 ID 已存在',409)
 if m=='PATCH' and ident:
  if not _manage(db,a,org):return _err('FORBIDDEN','无组织结构管理权限',403)
  try:
   with db.tx() as c:
    old=_one(c,f'SELECT * FROM {table} WHERE {key}=? AND organization_id=?',(ident,org))
    if not old:return _err('NOT_FOUND','对象不存在',404)
    parent=b.get('parentId',b.get(parent_col,old.get(parent_col)));parent=str(parent).strip() if parent else None
    if parent and not c.execute(f'SELECT 1 FROM {table} WHERE {key}=? AND organization_id=?',(parent,org)).fetchone():return _err('PARENT_NOT_FOUND','上级对象不存在',404)
    if _cycle(c,table,key,ident,parent,org):return _err('HIERARCHY_CYCLE','层级关系不能形成循环')
    name=str(b.get('name',old['name'])).strip();code=str(b.get('code',old['code'])).strip().lower();status=str(b.get('status',old['status']))
    if not name or not code or status not in STATUS:return _err('INVALID_INPUT','名称、编码或状态无效')
    if kind=='markets':
     mt=str(b.get('marketType',old['market_type']))
     if mt not in MARKET_TYPES:return _err('INVALID_MARKET_TYPE','市场类型无效')
     c.execute('UPDATE markets SET parent_market_id=?,name=?,code=?,market_type=?,country_code=?,region_code=?,timezone=?,description=?,status=?,updated_at=? WHERE market_id=?',(parent,name,code,mt,str(b.get('countryCode',old['country_code'])),str(b.get('regionCode',old['region_code'])),str(b.get('timezone',old['timezone'])),str(b.get('description',old['description'])),status,now_ms(),ident))
    else:
     c.execute(f'UPDATE {table} SET {parent_col}=?,name=?,code=?,description=?,status=?,updated_at=? WHERE {key}=?',(parent,name,code,str(b.get('description',old['description'])),status,now_ms(),ident))
    new=_one(c,f'SELECT * FROM {table} WHERE {key}=?',(ident,));aw=c.execute('SELECT workspace_id FROM workspaces WHERE organization_id=? ORDER BY workspace_id LIMIT 1',(org,)).fetchone();
    if not aw:raise RuntimeError('AUDIT_WORKSPACE_REQUIRED')
    _audit(c,a,'update',kind,ident,old,new,aw[0],b.get('reason'))
   return _ok(item=new)
  except sqlite3.IntegrityError:return _err('CONFLICT','编码或名称已存在',409)
 return _err('METHOD_NOT_ALLOWED','不支持的操作',405)

def _workspace_rel(db,a,org,m,wid,kind,q,b):
 specs={
  'teams':('workspace_teams','team_id','teams','team_id'),
  'business-lines':('workspace_business_lines','business_line_id','business_lines','business_line_id'),
  'markets':('workspace_markets','market_id','markets','market_id')}
 join,key,parent,pkey=specs[kind]
 if not _read(db,a,org):return _err('FORBIDDEN','无业务空间读取权限',403)
 with db.tx(False) as c:
  if not c.execute('SELECT 1 FROM workspaces WHERE workspace_id=? AND organization_id=?',(wid,org)).fetchone():return _err('WORKSPACE_NOT_FOUND','业务空间不存在',404)
 if m=='GET':
  with db.tx(False) as c:return _ok(items=_rows(c,f'SELECT r.*,e.name FROM {join} r JOIN {parent} e ON e.{pkey}=r.{key} WHERE r.workspace_id=? AND r.organization_id=? ORDER BY r.is_primary DESC,e.name',(wid,org)))
 if not _manage(db,a,org):return _err('FORBIDDEN','无业务空间关系管理权限',403)
 entity=str(b.get({'teams':'teamId','business-lines':'businessLineId','markets':'marketId'}[kind]) or q.get(key) or '')
 if not entity:return _err('REFERENCE_REQUIRED','关联对象不能为空')
 if m in ('POST','PATCH'):
  primary=1 if b.get('isPrimary') else 0;status=str(b.get('status') or 'active')
  if status not in STATUS:return _err('INVALID_STATUS','状态无效')
  n=now_ms()
  try:
   with db.tx() as c:
    if not c.execute(f'SELECT 1 FROM {parent} WHERE {pkey}=? AND organization_id=?',(entity,org)).fetchone():return _err('REFERENCE_NOT_FOUND','关联对象不存在或不属于当前企业',404)
    old=_one(c,f'SELECT * FROM {join} WHERE workspace_id=? AND {key}=?',(wid,entity))
    if primary:c.execute(f'UPDATE {join} SET is_primary=0,updated_at=? WHERE workspace_id=? AND organization_id=? AND is_primary=1',(n,wid,org))
    if kind=='teams':
     rel=str(b.get('relationType') or 'collaborator');access=str(b.get('accessLevel') or 'operate')
     if rel not in REL_TYPES or access not in ACCESS:return _err('INVALID_RELATION','团队关系类型或访问级别无效')
     if rel=='primary':primary=1;c.execute('UPDATE workspace_teams SET is_primary=0,updated_at=? WHERE workspace_id=? AND organization_id=? AND is_primary=1',(n,wid,org))
     c.execute("INSERT INTO workspace_teams(workspace_id,team_id,organization_id,relation_type,is_primary,access_level,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(workspace_id,team_id) DO UPDATE SET relation_type=excluded.relation_type,is_primary=excluded.is_primary,access_level=excluded.access_level,status=excluded.status,updated_at=excluded.updated_at",(wid,entity,org,rel,primary,access,status,n,n))
    elif kind=='business-lines':c.execute("INSERT INTO workspace_business_lines(workspace_id,business_line_id,organization_id,is_primary,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(workspace_id,business_line_id) DO UPDATE SET is_primary=excluded.is_primary,status=excluded.status,updated_at=excluded.updated_at",(wid,entity,org,primary,status,n,n))
    else:c.execute("INSERT INTO workspace_markets(workspace_id,market_id,organization_id,is_primary,scope_type,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(workspace_id,market_id) DO UPDATE SET is_primary=excluded.is_primary,scope_type=excluded.scope_type,status=excluded.status,updated_at=excluded.updated_at",(wid,entity,org,primary,str(b.get('scopeType') or 'direct'),status,n,n))
    new=_one(c,f'SELECT * FROM {join} WHERE workspace_id=? AND {key}=?',(wid,entity));_audit(c,a,'link' if not old else 'update_link','workspace_'+kind,entity,old,new,wid,b.get('reason'))
   return _ok(item=new)
  except sqlite3.IntegrityError:return _err('RELATION_CONFLICT','关联关系冲突',409)
 if m=='DELETE':
  with db.tx() as c:
   old=_one(c,f'SELECT * FROM {join} WHERE workspace_id=? AND {key}=? AND organization_id=?',(wid,entity,org))
   if not old:return _err('NOT_FOUND','关联关系不存在',404)
   c.execute(f'DELETE FROM {join} WHERE workspace_id=? AND {key}=?',(wid,entity));_audit(c,a,'unlink','workspace_'+kind,entity,old,{},wid,b.get('reason'))
  return _ok()
 return _err('METHOD_NOT_ALLOWED','不支持的操作',405)

def handle(db,a,org,m,root,ident,action,q,b):
 if root in ('departments','business-lines','markets'):return _entity(db,a,org,m,root,ident,q,b)
 if root=='workspaces' and ident and action in ('teams','business-lines','markets'):return _workspace_rel(db,a,org,m,ident,action,q,b)
 return None

# V207.3.0-dev 更新说明（2026-09-19）：新增部门、业务线、市场及业务空间多维关联 API，统一执行企业隔离、层级循环校验、RBAC、事务和审计。
