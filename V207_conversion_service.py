# -*- coding: utf-8 -*-
"""S5 conversion service: scoped CRUD, idempotency, state transitions and atomic stage/audit linkage."""
import json,re,sqlite3,uuid
from V207_shared_db import now_ms,dumps
from V207_security import can,is_platform_admin

def one(c,s,a=()):
 r=c.execute(s,a).fetchone();return dict(r) if r else None
def rows(c,s,a=()):return [dict(r) for r in c.execute(s,a)]
def err(code,msg,status=400,**extra):return ({'ok':False,'code':code,'message':msg,**extra},status)
def integer(v,name,minimum=0,maximum=None):
 try:
  if isinstance(v,bool):raise ValueError
  n=int(v)
 except (TypeError,ValueError):raise ValueError(name)
 if n<minimum or (maximum is not None and n>maximum):raise ValueError(name)
 return n
def obj(v):
 if v is None:return {}
 if not isinstance(v,dict):raise ValueError
 return v
def permitted(db,a,org,perm,wid=None,team=None):
 return bool(org) and (is_platform_admin(db,a) or (a.get('organization_id')==org and can(db,a,perm,workspace_id=wid,team_id=team,organization_id=org)))
def readable(db,a,org,wid=None,team=None):return permitted(db,a,org,'conversion.read',wid,team) or permitted(db,a,org,'conversion.manage',wid,team)
def audit(c,a,op,eid,before,after,wid,reason=None):
 c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(wid,a['user_id'],None,op,'contact_conversion',eid,dumps(before or {}),dumps(after or {}),reason,now_ms()))
def stage_for(status):return {'pending':'方案确认','won':'成交','lost':'流失','cancelled':'流失','refunded':'流失'}[status]
def set_stage(c,a,cid,status,n):
 c.execute("INSERT INTO contact_custom_values(contact_id,field_key,value_json,updated_at,updated_by) VALUES(?,'conversion_stage',?,?,?) ON CONFLICT(contact_id,field_key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by",(cid,dumps(stage_for(status)),n,a['user_id']))
def canonical(x):return json.dumps(x,ensure_ascii=False,separators=(',',':'),sort_keys=True)
def comparable(row):
 try:meta=json.loads(row.get('metadata_json') or '{}')
 except Exception:meta={}
 return {'contact_id':row.get('contact_id'),'team_id':row.get('team_id'),'owner_user_id':row.get('owner_user_id'),'source_id':row.get('source_id'),'attribution_id':row.get('attribution_id'),'conversion_status':row.get('conversion_status'),'amount_minor':row.get('amount_minor'),'currency_code':row.get('currency_code'),'converted_at':row.get('converted_at'),'external_conversion_key':row.get('external_conversion_key'),'metadata':meta}

STATUSES={'pending','won','lost','cancelled','refunded'}
TRANSITIONS={'pending':{'won','lost','cancelled'},'won':{'refunded'},'lost':set(),'cancelled':set(),'refunded':set()}

def _scope_predicate(c,a,org,args,alias='v'):
 if c.execute('SELECT 1 FROM platform_administrators WHERE user_id=?',(a.get('user_id'),)).fetchone():return ''
 grants=rows(c,"SELECT DISTINCT b.scope_type,b.scope_id FROM role_bindings b JOIN roles r ON r.role_id=b.role_id AND r.status='active' JOIN role_permissions rp ON rp.role_id=b.role_id WHERE b.user_id=? AND b.status='active' AND b.organization_id=? AND rp.permission_key IN ('conversion.read','conversion.manage')",(a.get('user_id'),org))
 if any(g['scope_type']=='organization' and g['scope_id']==org for g in grants):return ''
 ws=sorted({g['scope_id'] for g in grants if g['scope_type']=='workspace'});teams=sorted({g['scope_id'] for g in grants if g['scope_type']=='team'});parts=[]
 if ws:parts.append(alias+'.workspace_id IN ('+','.join('?'*len(ws))+')');args.extend(ws)
 if teams:parts.append(alias+'.team_id IN ('+','.join('?'*len(teams))+')');args.extend(teams)
 return ' AND ('+' OR '.join(parts)+')' if parts else ' AND 0'

def handle(db,a,org,m,ident,q,b):
 if not org or (a.get('organization_id')!=org and not is_platform_admin(db,a)):return err('FORBIDDEN','无转化权限',403)
 if m=='GET':
  try:limit=integer(q.get('limit',100),'limit',1,200);offset=integer(q.get('offset',0),'offset',0,1000000)
  except ValueError:return err('INVALID_PAGINATION','limit 必须为 1..200，offset 必须为 0..1000000')
  with db.tx(False) as c:
   base='SELECT v.*,ct.display_name contact_name,s.source_name,u.display_name owner_name,t.name team_name FROM contact_conversions v JOIN contacts ct ON ct.contact_id=v.contact_id LEFT JOIN sources s ON s.source_id=v.source_id LEFT JOIN users u ON u.user_id=v.owner_user_id LEFT JOIN teams t ON t.team_id=v.team_id'
   if ident:
    x=one(c,base+' WHERE v.conversion_id=? AND v.organization_id=?',(ident,org))
    if not x:return err('CONVERSION_NOT_FOUND','转化不存在',404)
    if not readable(db,a,org,x['workspace_id'],x.get('team_id')):return err('FORBIDDEN','无转化读取权限',403)
    return {'ok':True,'item':x},200
   wh=['v.organization_id=?'];args=[org]
   for key,col in [('workspaceId','v.workspace_id'),('teamId','v.team_id'),('contactId','v.contact_id'),('ownerUserId','v.owner_user_id'),('sourceId','v.source_id'),('status','v.conversion_status')]:
    if q.get(key) not in (None,''):wh.append(col+'=?');args.append(str(q[key]))
   scope_args=[];scope=_scope_predicate(c,a,org,scope_args)
   if scope==' AND 0':return err('FORBIDDEN','无转化读取权限',403)
   where=' WHERE '+' AND '.join(wh)+scope;allargs=args+scope_args
   total=c.execute('SELECT count(*) FROM contact_conversions v'+where,allargs).fetchone()[0]
   its=rows(c,base+where+' ORDER BY v.converted_at DESC,v.created_at DESC,v.conversion_id DESC LIMIT ? OFFSET ?',allargs+[limit,offset])
  return {'ok':True,'items':its,'page':{'limit':limit,'offset':offset,'total':total,'hasMore':offset+len(its)<total}},200
 if m=='POST' and not ident:
  cid=str(b.get('contactId') or '').strip();team=str(b.get('teamId') or '').strip() or None;owner=str(b.get('ownerUserId') or '').strip() or None;sid=str(b.get('sourceId') or '').strip() or None;aid=str(b.get('attributionId') or '').strip() or None;status=str(b.get('status') or 'won').strip().lower();key=str(b.get('externalConversionKey') or '').strip() or None
  if not cid:return err('CONTACT_REQUIRED','contactId 必填')
  if status not in STATUSES:return err('INVALID_CONVERSION_STATUS','转化状态无效')
  if key and len(key)>255:return err('INVALID_EXTERNAL_CONVERSION_KEY','externalConversionKey 过长')
  try:
   amount=None if b.get('amountMinor') in (None,'') else integer(b.get('amountMinor'),'amountMinor',0,9223372036854775807)
   currency=str(b.get('currencyCode') or '').strip().upper();converted=integer(b.get('convertedAt',now_ms()),'convertedAt',0);meta=obj(b.get('metadata'))
  except ValueError:return err('INVALID_CONVERSION','金额、时间或 metadata 无效')
  if amount is not None and not re.fullmatch(r'[A-Z]{3}',currency):return err('INVALID_CURRENCY','有金额时 currencyCode 必须是三位大写币种代码')
  if amount is None and currency and not re.fullmatch(r'[A-Z]{3}',currency):return err('INVALID_CURRENCY','currencyCode 必须是三位大写币种代码')
  try:
   with db.tx() as c:
    ct=one(c,'SELECT * FROM contacts WHERE contact_id=? AND organization_id=?',(cid,org))
    if not ct:return err('CONTACT_NOT_FOUND','联系人不存在',404)
    wid=ct['workspace_id'];team=team or ct.get('team_id');owner=owner or ct.get('owner_user_id')
    if not permitted(db,a,org,'conversion.manage',wid,team):return err('FORBIDDEN','无转化管理权限',403)
    if team:
     tr=one(c,'SELECT * FROM teams WHERE team_id=? AND organization_id=?',(team,org))
     if not tr or (tr.get('workspace_id') and tr['workspace_id']!=wid):return err('TEAM_SCOPE_MISMATCH','团队不属于联系人企业工作区',409)
    if owner and not one(c,'SELECT 1 FROM users WHERE user_id=? AND organization_id=?',(owner,org)):return err('OWNER_SCOPE_MISMATCH','负责人不属于同一企业',409)
    sr=None
    if sid:
     sr=one(c,'SELECT * FROM sources WHERE source_id=? AND organization_id=?',(sid,org))
     if not sr or sr['workspace_id']!=wid:return err('SOURCE_SCOPE_MISMATCH','来源不属于联系人企业工作区',409)
    ar=None
    if aid:
     ar=one(c,'SELECT * FROM contact_attributions WHERE attribution_id=? AND organization_id=?',(aid,org))
     if not ar or ar['workspace_id']!=wid or ar['contact_id']!=cid:return err('ATTRIBUTION_SCOPE_MISMATCH','归因不属于同一联系人企业工作区',409)
     if sid and ar['source_id']!=sid:return err('ATTRIBUTION_SOURCE_MISMATCH','归因来源与转化来源不一致',409)
     if not sid:sid=ar['source_id']
    want={'contact_id':cid,'team_id':team,'owner_user_id':owner,'source_id':sid,'attribution_id':aid,'conversion_status':status,'amount_minor':amount,'currency_code':currency,'converted_at':converted,'external_conversion_key':key,'metadata':meta}
    if key:
     old=one(c,'SELECT * FROM contact_conversions WHERE organization_id=? AND external_conversion_key=?',(org,key))
     if old:
      if canonical(comparable(old))!=canonical(want):return err('CONVERSION_IDEMPOTENCY_CONFLICT','幂等键已被不同请求使用',409,conversionId=old['conversion_id'])
      return {'ok':True,'conversionId':old['conversion_id'],'item':old,'idempotent':True},200
    vid='cv_'+uuid.uuid4().hex;n=now_ms()
    c.execute('INSERT INTO contact_conversions(conversion_id,organization_id,workspace_id,team_id,contact_id,owner_user_id,source_id,attribution_id,conversion_status,amount_minor,currency_code,converted_at,external_conversion_key,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(vid,org,wid,team,cid,owner,sid,aid,status,amount,currency,converted,key,dumps(meta),n,n))
    set_stage(c,a,cid,status,n);new=one(c,'SELECT * FROM contact_conversions WHERE conversion_id=?',(vid,));audit(c,a,'create',vid,{},new,wid,b.get('reason'))
   return {'ok':True,'conversionId':vid,'item':new},201
  except sqlite3.IntegrityError:return err('CONVERSION_CONFLICT','转化数据冲突',409)
 if m=='PATCH' and ident:
  status=str(b.get('status') or '').strip().lower()
  if status not in STATUSES:return err('INVALID_CONVERSION_STATUS','status 必填且必须是有效转化状态')
  try:
   with db.tx() as c:
    old=one(c,'SELECT * FROM contact_conversions WHERE conversion_id=? AND organization_id=?',(ident,org))
    if not old:return err('CONVERSION_NOT_FOUND','转化不存在',404)
    if not permitted(db,a,org,'conversion.manage',old['workspace_id'],old.get('team_id')):return err('FORBIDDEN','无转化管理权限',403)
    current=old['conversion_status']
    if status!=current and status not in TRANSITIONS.get(current,set()):return err('INVALID_STATUS_TRANSITION','不允许从 '+current+' 流转到 '+status,409)
    if status==current:return {'ok':True,'item':old,'idempotent':True},200
    n=now_ms();c.execute('UPDATE contact_conversions SET conversion_status=?,updated_at=? WHERE conversion_id=?',(status,n,ident));set_stage(c,a,old['contact_id'],status,n);new=one(c,'SELECT * FROM contact_conversions WHERE conversion_id=?',(ident,));audit(c,a,'status_transition',ident,old,new,old['workspace_id'],b.get('reason'))
   return {'ok':True,'item':new},200
  except sqlite3.IntegrityError:return err('CONVERSION_CONFLICT','转化状态更新冲突',409)
 return err('METHOD_NOT_ALLOWED','转化接口不支持该方法',405)
