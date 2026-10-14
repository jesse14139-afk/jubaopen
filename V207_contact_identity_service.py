# -*- coding: utf-8 -*-
"""V207 联系人外部身份领域服务。负责租户隔离、验证、事务与审计。"""
import re, sqlite3, uuid
from V207_shared_db import now_ms, dumps, loads
from V207_security import can,is_platform_admin,data_scope_clause_in_tx
from V207_scope import resolve_scope

IDENTITY_TYPES={'external_id','email','login','username','handle','phone','mobile','whatsapp','telegram','instagram','facebook','messenger','line','wechat','tiktok'}
VERIFICATION_STATUSES={'unverified','pending','verified','rejected'}

def one(c,sql,args=()):
 r=c.execute(sql,args).fetchone();return dict(r) if r else None

def rows(c,sql,args=()):return [dict(x) for x in c.execute(sql,args)]

def bad(h,code,msg,status=400):return h.sendj({'ok':False,'code':code,'message':msg},status) or True

def platform(db,a):return is_platform_admin(db,a)

def allowed(db,a,permission,org):
 return bool(org) and (platform(db,a) or (org==a.get('organization_id') and can(db,a,permission)))

def scoped_contact(c,a,org,contact_id):
 # Exact-row authorization: no target-derived workspace/team and no broad org fallback.
 if not org or org!=a.get('organization_id'):return None
 clause,args,_=data_scope_clause_in_tx(c,a,'contact.read',org,alias='c')
 return one(c,'SELECT c.* FROM contacts c WHERE c.organization_id=? AND c.contact_id=? AND c.deleted_at IS NULL AND ('+clause+')',[org,contact_id]+args)

def canonical_identity(identity_type,value):
 v=str(value or '').strip();typ=str(identity_type or 'external_id').strip().lower()
 # JUBAOPEN_THREADS_IDENTITY_ALIAS_210_3_22
 if typ=='threads_username':typ='username'
 if typ in ('email','login','username','handle'):return typ,''.join(v.lower().split())
 if typ in ('phone','mobile','whatsapp'):
  prefix='+' if v.startswith('+') else '';return typ,prefix+''.join(x for x in v if x.isdigit())
 return typ,' '.join(v.lower().split())

# JUBAOPEN_THREADS_IDENTITY_ALIAS_210_3_23
def validate_identity(identity_type,value,status,metadata):
 typ,canonical=canonical_identity(identity_type,value)
 if typ not in IDENTITY_TYPES or not re.fullmatch(r'[a-z][a-z0-9_]{1,63}',typ):return None,'INVALID_IDENTITY_TYPE','身份类型无效'
 if not value or len(value)>512 or not canonical or len(canonical)>512:return None,'INVALID_IDENTITY','身份值无效或长度超过 512'
 if status not in VERIFICATION_STATUSES:return None,'INVALID_VERIFICATION_STATUS','身份验证状态无效'
 if not isinstance(metadata,dict):return None,'INVALID_METADATA','metadata 必须是对象'
 return (typ,canonical),None,None

def audit(c,a,op,eid,before,after,reason=None,wid=None):
 if not wid:raise RuntimeError('AUDIT_SCOPE_REQUIRED')
 c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(wid,a['user_id'],None,op,'contact_identity',eid,dumps(before or {}),dumps(after or {}),reason,now_ms()))

def handle(h,m,seg,q,a,db,org):
 """处理 /admin/contacts/{contactId}/identities[/{identityId}]；不匹配返回 False。"""
 if not (len(seg)>=3 and seg[0]=='contacts' and seg[2]=='identities'):return False
 contact_id=seg[1];identity_id=seg[3] if len(seg)==4 else None
 if len(seg) not in (3,4):return bad(h,'NOT_FOUND','联系人身份接口不存在',404)
 if m=='GET':
  if identity_id:return bad(h,'METHOD_NOT_ALLOWED','身份详情不支持 GET',405)
  if not allowed(db,a,'contact.read',org):return bad(h,'FORBIDDEN','无联系人读取权限',403)
  with db.tx(False) as c:
   scope=scoped_contact(c,a,org,contact_id)
   if not scope:return bad(h,'CONTACT_NOT_FOUND','联系人不存在或无权访问',404)
   its=rows(c,'SELECT i.*,p.platform_name,p.platform_code FROM contact_identities i LEFT JOIN platforms p ON p.platform_id=i.platform_id WHERE i.organization_id=? AND i.workspace_id=? AND i.contact_id=? ORDER BY i.is_primary DESC,i.first_seen_at,i.contact_identity_id',(org,scope['workspace_id'],contact_id))
  return h.sendj({'ok':True,'items':its}) or True
 if m=='POST' and identity_id!='merge':
  if identity_id:return bad(h,'METHOD_NOT_ALLOWED','身份详情不支持 POST',405)
  if not allowed(db,a,'contact.identity.manage',org):return bad(h,'FORBIDDEN','无联系人身份管理权限',403)
  b=h.body();value=str(b.get('identityValue') or b.get('identity') or '').strip();status=str(b.get('verificationStatus') or 'unverified');metadata=b.get('metadata') if 'metadata' in b else {}
  if 'isPrimary' in b and not isinstance(b['isPrimary'],bool):return bad(h,'INVALID_IS_PRIMARY','isPrimary 必须是布尔值')
  validated,code,msg=validate_identity(b.get('identityType'),value,status,metadata)
  if code:return bad(h,code,msg)
  typ,canonical=validated;pid=str(b.get('platformId') or '').strip() or None
  try:
   with db.tx() as c:
    scope=scoped_contact(c,a,org,contact_id)
    if not scope:return bad(h,'CONTACT_NOT_FOUND','联系人不存在或无权访问',404)
    wid=scope['workspace_id']
    if pid and not one(c,"SELECT platform_id FROM platforms WHERE platform_id=? AND status='active'",(pid,)):return bad(h,'PLATFORM_NOT_FOUND','平台不存在或未启用',404)
    if one(c,'SELECT contact_identity_id FROM contact_identities WHERE organization_id=? AND platform_id IS ? AND identity_type=? AND canonical_value=?',(org,pid,typ,canonical)):return bad(h,'IDENTITY_CONFLICT','该外部身份已绑定联系人',409)
    n=now_ms();iid='cid_'+uuid.uuid4().hex;primary=1 if b.get('isPrimary') or not one(c,'SELECT contact_identity_id FROM contact_identities WHERE organization_id=? AND workspace_id=? AND contact_id=?',(org,wid,contact_id)) else 0
    if primary:c.execute('UPDATE contact_identities SET is_primary=0 WHERE organization_id=? AND workspace_id=? AND contact_id=?',(org,wid,contact_id))
    c.execute('INSERT INTO contact_identities(contact_identity_id,organization_id,workspace_id,contact_id,platform_id,identity_type,identity_value,canonical_value,verification_status,is_primary,first_seen_at,last_seen_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(iid,org,wid,contact_id,pid,typ,value,canonical,status,primary,n,n,dumps(metadata)))
    new=one(c,'SELECT * FROM contact_identities WHERE contact_identity_id=?',(iid,));audit(c,a,'create',iid,{},new,wid=wid)
  except LookupError:return bad(h,'CONTACT_NOT_FOUND','联系人不存在',404)
  except sqlite3.IntegrityError:return bad(h,'IDENTITY_CONFLICT','身份或主身份约束冲突',409)
  return h.sendj({'ok':True,'item':new},201) or True
 if identity_id and m=='PATCH':
  if not allowed(db,a,'contact.identity.manage',org):return bad(h,'FORBIDDEN','无联系人身份管理权限',403)
  b=h.body()
  if 'isPrimary' in b and not isinstance(b['isPrimary'],bool):return bad(h,'INVALID_IS_PRIMARY','isPrimary 必须是布尔值')
  try:
   with db.tx() as c:
    scope=scoped_contact(c,a,org,contact_id)
    if not scope:return bad(h,'CONTACT_NOT_FOUND','联系人不存在或无权访问',404)
    wid=scope['workspace_id'];old=one(c,'SELECT * FROM contact_identities WHERE contact_identity_id=? AND organization_id=? AND workspace_id=? AND contact_id=?',(identity_id,org,wid,contact_id))
    if not old:return bad(h,'IDENTITY_NOT_FOUND','联系人身份不存在',404)
    if old.get('is_primary') and b.get('isPrimary') is False:return bad(h,'PRIMARY_REQUIRED','不能直接取消主身份，请将其他身份设为主身份',409)
    value=str(b.get('identityValue') if 'identityValue' in b else old['identity_value']).strip();status=str(b.get('verificationStatus',old.get('verification_status') or 'unverified'));metadata=b.get('metadata') if 'metadata' in b else loads(old.get('metadata_json'),{})
    validated,code,msg=validate_identity(b.get('identityType',old['identity_type']),value,status,metadata)
    if code:return bad(h,code,msg)
    typ,canonical=validated;pid=(str(b.get('platformId') or '').strip() or None) if 'platformId' in b else old.get('platform_id')
    if pid and not one(c,"SELECT platform_id FROM platforms WHERE platform_id=? AND status='active'",(pid,)):return bad(h,'PLATFORM_NOT_FOUND','平台不存在或未启用',404)
    if one(c,'SELECT contact_identity_id FROM contact_identities WHERE organization_id=? AND platform_id IS ? AND identity_type=? AND canonical_value=? AND contact_identity_id<>?',(org,pid,typ,canonical,identity_id)):return bad(h,'IDENTITY_CONFLICT','该外部身份已绑定联系人',409)
    primary=1 if b.get('isPrimary') is True else int(old.get('is_primary') or 0)
    if primary:c.execute('UPDATE contact_identities SET is_primary=0 WHERE organization_id=? AND workspace_id=? AND contact_id=? AND contact_identity_id<>?',(org,wid,contact_id,identity_id))
    c.execute('UPDATE contact_identities SET platform_id=?,identity_type=?,identity_value=?,canonical_value=?,verification_status=?,is_primary=?,last_seen_at=?,metadata_json=? WHERE contact_identity_id=?',(pid,typ,value,canonical,status,primary,now_ms(),dumps(metadata),identity_id))
    new=one(c,'SELECT * FROM contact_identities WHERE contact_identity_id=?',(identity_id,));audit(c,a,'update',identity_id,old,new,b.get('reason'),wid)
  except LookupError:return bad(h,'CONTACT_NOT_FOUND','联系人不存在',404)
  except sqlite3.IntegrityError:return bad(h,'IDENTITY_CONFLICT','身份或主身份约束冲突',409)
  return h.sendj({'ok':True,'item':new}) or True
 if identity_id and m=='DELETE':
  if not allowed(db,a,'contact.identity.manage',org):return bad(h,'FORBIDDEN','无联系人身份管理权限',403)
  try:
   with db.tx() as c:
    scope=scoped_contact(c,a,org,contact_id)
    if not scope:return bad(h,'CONTACT_NOT_FOUND','联系人不存在或无权访问',404)
    wid=scope['workspace_id'];old=one(c,'SELECT * FROM contact_identities WHERE contact_identity_id=? AND organization_id=? AND workspace_id=? AND contact_id=?',(identity_id,org,wid,contact_id))
    if not old:return bad(h,'IDENTITY_NOT_FOUND','联系人身份不存在',404)
    count=c.execute('SELECT count(*) FROM contact_identities WHERE organization_id=? AND workspace_id=? AND contact_id=?',(org,wid,contact_id)).fetchone()[0]
    if count<=1:return bad(h,'LAST_IDENTITY','不能删除联系人的最后一个身份',409)
    c.execute('DELETE FROM contact_identities WHERE contact_identity_id=?',(identity_id,))
    if old.get('is_primary'):
     replacement=c.execute('SELECT contact_identity_id FROM contact_identities WHERE organization_id=? AND workspace_id=? AND contact_id=? ORDER BY first_seen_at,contact_identity_id LIMIT 1',(org,wid,contact_id)).fetchone();c.execute('UPDATE contact_identities SET is_primary=1 WHERE contact_identity_id=?',(replacement[0],))
    audit(c,a,'delete',identity_id,old,{},wid=wid)
  except LookupError:return bad(h,'CONTACT_NOT_FOUND','联系人不存在',404)
  except sqlite3.IntegrityError:return bad(h,'IDENTITY_CONFLICT','身份或主身份约束冲突',409)
  return h.sendj({'ok':True}) or True
 if len(seg)==4 and seg[3]=='merge' and m=='POST':
  return bad(h,'LEGACY_MERGE_DISABLED','旧版身份迁移式合并已停用，请使用客户原子合并或提交审批申请',410)
  if not allowed(db,a,'contact.identity.manage',org):return bad(h,'FORBIDDEN','无联系人身份管理权限',403)
  b=h.body();src=str(b.get('sourceContactId') or '').strip()
  if not src:return bad(h,'INVALID_SOURCE','sourceContactId 不能为空')
  if src==contact_id:return bad(h,'INVALID_SOURCE','不能合并自身')
  try:
   with db.tx() as c:
    scope=scoped_contact(c,a,org,contact_id)
    if not scope:return bad(h,'CONTACT_NOT_FOUND','联系人不存在或无权访问',404)
    wid=scope['workspace_id']
    src_row=scoped_contact(c,a,org,src)
    if not src_row:return bad(h,'CONTACT_NOT_FOUND','来源联系人不存在或无权访问',404)
    if src_row['workspace_id']!=wid:return bad(h,'WORKSPACE_MISMATCH','两个联系人不在同一工作区，无法合并',409)
    if src_row.get('deleted_at'):return bad(h,'CONTACT_DELETED','来源联系人已删除',409)
    moved=0;dedup=0
    for it in rows(c,'SELECT * FROM contact_identities WHERE organization_id=? AND workspace_id=? AND contact_id=? ORDER BY is_primary DESC,first_seen_at',(org,wid,src)):
     dup=one(c,'SELECT contact_identity_id FROM contact_identities WHERE organization_id=? AND platform_id IS ? AND identity_type=? AND canonical_value=? AND contact_id<>?',(org,it.get('platform_id'),it['identity_type'],it['canonical_value'],src))
     if dup:dedup+=1;continue
     moved+=1;c.execute('UPDATE contact_identities SET contact_id=?,last_seen_at=? WHERE contact_identity_id=?',(contact_id,now_ms(),it['contact_identity_id']))
    tgt_has_primary=one(c,'SELECT contact_identity_id FROM contact_identities WHERE organization_id=? AND workspace_id=? AND contact_id=? AND is_primary=1',(org,wid,contact_id))
    if not tgt_has_primary:
     first=one(c,'SELECT contact_identity_id FROM contact_identities WHERE organization_id=? AND workspace_id=? AND contact_id=? ORDER BY is_primary DESC,first_seen_at,contact_identity_id LIMIT 1',(org,wid,contact_id))
     if first:c.execute('UPDATE contact_identities SET is_primary=1 WHERE contact_identity_id=?',(first[0],))
    remaining=c.execute('SELECT count(*) FROM contact_identities WHERE organization_id=? AND workspace_id=? AND contact_id=?',(org,wid,src)).fetchone()[0]
    c.execute('UPDATE contacts SET deleted_at=?,deleted_by=?,delete_reason=?,updated_at=? WHERE contact_id=?',(now_ms(),a['user_id'],'merged:'+contact_id,now_ms(),src))
    if remaining==0 and one(c,'SELECT contact_id FROM contacts WHERE contact_id=? AND organization_id=? AND workspace_id=?',(contact_id,org,wid)):
     f=one(c,'SELECT contact_identity_id FROM contact_identities WHERE organization_id=? AND workspace_id=? AND contact_id=? ORDER BY is_primary DESC,first_seen_at LIMIT 1',(org,wid,contact_id))
     if f and not one(c,'SELECT contact_identity_id FROM contact_identities WHERE contact_identity_id=? AND is_primary=1',(f[0],)):c.execute('UPDATE contact_identities SET is_primary=1 WHERE contact_identity_id=?',(f[0],))
    audit(c,a,'merge',contact_id,{'source':src,'source_name':src_row.get('display_name')},{'moved':moved,'deduped':dedup,'deleted_source':True},str(b.get('reason') or 'identity merge'),wid)
  except LookupError:return bad(h,'CONTACT_NOT_FOUND','联系人不存在',404)
  except sqlite3.IntegrityError:return bad(h,'IDENTITY_CONFLICT','身份或主身份约束冲突',409)
  return h.sendj({'ok':True,'moved':moved,'deduped':dedup,'mergedFrom':src}) or True
 return bad(h,'METHOD_NOT_ALLOWED','不支持的联系人身份操作',405)
