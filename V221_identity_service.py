# -*- coding: utf-8 -*-
"""Schema 221：联系人团队授权、身份关联、查重与原子合并。"""
import json,re,sqlite3,uuid,logging
from V207_shared_db import now_ms,dumps,loads
from V207_security import can,is_platform_admin,data_scope_clause_in_tx,effective_scope_bindings_in_tx,has_permission_in_any_scope
from V208_identity import normalize_identity

def _dict(r):return dict(r) if r else None
def _rows(c,sql,args=()):return [dict(x) for x in c.execute(sql,args)]
def _result(ok=True,status=200,**x):return ({'ok':ok,**x},status)
def _send(h,payload,status=200):
    # HTTP status must always be an integer. Fail explicitly at the service boundary.
    if not isinstance(status,int) or isinstance(status,bool):
        logging.error('invalid contact governance response contract: status=%r payload=%r',status,payload)
        payload={'ok':False,'code':'INVALID_RESPONSE_CONTRACT','message':'客户治理响应格式错误'};status=500
    h.sendj(payload,status);return True
def _bad(h,code,message,status=400,**extra):return _send(h,{'ok':False,'code':code,'message':message,**extra},status)
def _level_rank(v):return {'read':1,'edit':2,'manage':3}.get(v,0)
def _mask(v):
 v=str(v or '');return v if len(v)<7 else v[:3]+'*'*(len(v)-7)+v[-4:]
def _contact_access(c,a,cid,level='read'):
 org=a.get('organization_id')
 if not org:return None
 clause,args,_=data_scope_clause_in_tx(c,a,'contact.read',org,alias='c')
 if a.get('workspace_id'):
  clause='(('+clause+') OR (c.owner_user_id=? AND c.workspace_id=?))';args=args+[a.get('user_id'),a.get('workspace_id')]
 return c.execute('SELECT c.* FROM contacts c WHERE c.contact_id=? AND c.organization_id=? AND c.deleted_at IS NULL AND ('+clause+')',[cid,org]+args).fetchone()

def _contact_scope(c,a,alias='c'):
 clause,args,_=data_scope_clause_in_tx(c,a,'contact.read',a['organization_id'],alias=alias)
 if a.get('workspace_id'):
  clause='(('+clause+') OR ('+alias+'.owner_user_id=? AND '+alias+'.workspace_id=?))';args=args+[a.get('user_id'),a.get('workspace_id')]
 return clause,args

def _row_permission(c,a,permission,row):
 grants=effective_scope_bindings_in_tx(c,a,permission,a.get('organization_id'))
 uid=a.get('user_id')
 # SAME_OWNER_DIRECT_LINK：同企业同工作区本人客户，仍要求存在有效关联授权。
 if permission=='contact.identity.link' and row.get('owner_user_id')==a.get('user_id') and row.get('organization_id')==a.get('organization_id') and row.get('workspace_id')==a.get('workspace_id') and grants:return True
 for g in grants:
  typ,sid=g['scope_type'],g['scope_id']
  if typ=='platform' or (typ=='organization' and sid==a.get('organization_id')):return True
  if typ=='workspace' and sid==row.get('workspace_id'):return True
  if typ=='team' and sid==row.get('team_id'):return True
  if typ=='self' and sid==uid and row.get('owner_user_id')==uid:return True
 return False

def grant_access_in_tx(c,a,contact,team_id,level='edit',source='manual_link',reason=''):
 team=c.execute("SELECT team_id FROM teams WHERE team_id=? AND organization_id=? AND workspace_id=? AND status='active'",(team_id,contact['organization_id'],contact['workspace_id'])).fetchone()
 if not team:raise ValueError('TEAM_SCOPE_INVALID')
 old=c.execute("SELECT * FROM contact_team_access WHERE organization_id=? AND workspace_id=? AND contact_id=? AND team_id=?",(contact['organization_id'],contact['workspace_id'],contact['contact_id'],team_id)).fetchone();n=now_ms()
 if old:
  best=level if _level_rank(level)>_level_rank(old['access_level']) else old['access_level']
  c.execute("UPDATE contact_team_access SET access_level=?,source_type=?,granted_by=?,granted_at=?,revoked_by=NULL,revoked_at=NULL,reason=? WHERE access_id=?",(best,source,a['user_id'],n,reason,old['access_id']));return old['access_id']
 aid='cta_'+uuid.uuid4().hex;c.execute("INSERT INTO contact_team_access(access_id,organization_id,workspace_id,contact_id,team_id,access_level,source_type,granted_by,granted_at,reason) VALUES(?,?,?,?,?,?,?,?,?,?)",(aid,contact['organization_id'],contact['workspace_id'],contact['contact_id'],team_id,level,source,a['user_id'],n,reason));return aid
def _audit(c,a,op,etype,eid,before,after,reason=''):
 c.execute("INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at,organization_id,team_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(a.get('workspace_id'),a['user_id'],a.get('device_id'),op,etype,eid,dumps(before),dumps(after),reason,now_ms(),a['organization_id'],a.get('team_id')))
def _phone(v):return re.sub(r'\D','',str(v or ''))
def _candidate_rows(c,a,p,exclude=''):
 identity=p.get('contactIdentity') or p.get('identity') or {};platform_value=str(p.get('platformId') or p.get('platformCode') or '').lower();platform=c.execute("SELECT * FROM platforms WHERE status='active' AND (lower(platform_id)=? OR lower(platform_code)=?)",(platform_value,platform_value)).fetchone()
 typ=str(identity.get('identityType') or p.get('identityType') or 'external_id');raw=str(identity.get('identityValue') or p.get('identityValue') or '');canonical=''
 if platform and raw:typ,_,canonical=normalize_identity(platform['platform_code'],typ,raw)
 phone=_phone(identity.get('phone') or p.get('phone') or (raw if typ in ('phone','mobile','whatsapp','whatsapp_jid') else ''));scope,sa=_contact_scope(c,a,'c');found={}
 if platform and canonical:
  sql="SELECT c.*,ci.contact_identity_id FROM contact_identities ci JOIN contacts c ON c.contact_id=ci.contact_id WHERE ci.organization_id=? AND c.organization_id=? AND ci.platform_id=? AND ci.identity_type=? AND ci.canonical_value=? AND c.deleted_at IS NULL AND ("+scope+")"
  for r in c.execute(sql,[a['organization_id'],a['organization_id'],platform['platform_id'],typ,canonical]+sa):found[r['contact_id']]=(dict(r),'platform_identity','exact')
 if phone:
  sql="SELECT DISTINCT c.* FROM contacts c LEFT JOIN contact_identities ci ON ci.contact_id=c.contact_id WHERE c.organization_id=? AND c.deleted_at IS NULL AND ("+scope+") AND (replace(replace(replace(replace(c.manual_phone,'+',''),' ',''),'-',''),'(', '') LIKE ? OR replace(replace(replace(replace(c.observed_phone,'+',''),' ',''),'-',''),'(', '') LIKE ? OR (ci.identity_type IN ('phone','mobile','whatsapp','whatsapp_jid','whatsapp_lid') AND replace(replace(replace(ci.canonical_value,'+',''),' ',''),'-','') LIKE ?))"
  like='%'+phone[-10:]
  for r in c.execute(sql,[a['organization_id']]+sa+[like,like,like]):found.setdefault(r['contact_id'],(dict(r),'phone_exact','high'))
 out=[]
 for cid,(r,mt,confidence) in found.items():
  if cid==exclude:continue
  plats=[x[0] for x in c.execute("SELECT DISTINCT p.platform_code FROM contact_identities i LEFT JOIN platforms p ON p.platform_id=i.platform_id WHERE i.contact_id=?",(cid,)) if x[0]]
  caps={'canLink':_row_permission(c,a,'contact.identity.link',r),'canMerge':_row_permission(c,a,'contact.merge',r),'canRequestReview':_row_permission(c,a,'contact.duplicate.review',r)};out.append({'contactId':cid,'displayName':r['manual_name'] or r['display_name'] or '未命名客户','maskedPhone':_mask(r['manual_phone'] or r['observed_phone']),'workspaceId':r['workspace_id'],'sameWorkspace':r['workspace_id']==a.get('workspace_id'),'sameTeam':r['team_id']==a.get('team_id'),'accessible':True,'sameOwner':r['owner_user_id']==a.get('user_id'),'ownerUserId':r['owner_user_id'],'linkDecision':('allow' if _row_permission(c,a,'contact.identity.link',r) else ('request' if _row_permission(c,a,'contact.duplicate.review',r) else 'deny')),'linkReasonCode':('SAME_OWNER' if r['owner_user_id']==a.get('user_id') else 'OTHER_OWNER'),'matchType':mt,'confidence':confidence,'platforms':plats,'state':'visible_match','canReadProfile':True,**caps})
 return sorted(out,key=lambda x:({'exact':0,'high':1,'medium':2,'weak':3}.get(x['confidence'],9),x['displayName']))

def find_candidates(db,a,p):
 with db.tx(False) as c:return _result(items=_candidate_rows(c,a,p,str(p.get('excludeContactId') or '')))
def search_contacts(db,a,p):
 query=str(p.get('query') or '').strip();exclude=str(p.get('excludeContactId') or '');safe=query.replace('%','').replace('_','').strip()
 if len(safe)<2:return _result(False,400,code='SEARCH_QUERY_TOO_SHORT',message='请至少输入 2 个有效字符')
 like='%'+safe+'%';digits=_phone(safe);phone_like='%'+digits[-10:]+'%' if len(digits)>=4 else like
 with db.tx(False) as c:
  scope,sa=_contact_scope(c,a,'c')
  sql="SELECT DISTINCT c.* FROM contacts c LEFT JOIN contact_identities i ON i.contact_id=c.contact_id WHERE c.organization_id=? AND c.deleted_at IS NULL AND c.contact_id<>? AND ("+scope+") AND (c.contact_id LIKE ? OR COALESCE(c.manual_name,'') LIKE ? OR COALESCE(c.display_name,'') LIKE ? OR COALESCE(c.manual_phone,'') LIKE ? OR COALESCE(c.observed_phone,'') LIKE ? OR COALESCE(i.identity_value,'') LIKE ? OR COALESCE(i.canonical_value,'') LIKE ?) ORDER BY COALESCE(c.updated_at,0) DESC LIMIT 20"
  rs=c.execute(sql,[a['organization_id'],exclude]+sa+[like,like,like,phone_like,phone_like,like,like]).fetchall();items=[]
  for r in rs:
   plats=[x[0] for x in c.execute("SELECT DISTINCT p.platform_code FROM contact_identities i LEFT JOIN platforms p ON p.platform_id=i.platform_id WHERE i.contact_id=? ORDER BY p.platform_code",(r['contact_id'],)) if x[0]]
   items.append({'contactId':r['contact_id'],'displayName':r['manual_name'] or r['display_name'] or '未命名客户','maskedPhone':_mask(r['manual_phone'] or r['observed_phone']),'workspaceId':r['workspace_id'],'teamId':r['team_id'],'platforms':plats,'version':r['version'],'accessible':True,'sameOwner':r['owner_user_id']==a.get('user_id'),'sameWorkspace':r['workspace_id']==a.get('workspace_id'),'sameTeam':r['team_id']==a.get('team_id'),'ownerUserId':r['owner_user_id'],'linkDecision':('allow' if _row_permission(c,a,'contact.identity.link',dict(r)) else ('request' if _row_permission(c,a,'contact.duplicate.review',dict(r)) else 'deny')),'linkReasonCode':('SAME_OWNER' if r['owner_user_id']==a.get('user_id') else 'OTHER_OWNER'),'canLink':_row_permission(c,a,'contact.identity.link',dict(r)),'canMerge':_row_permission(c,a,'contact.merge',dict(r)),'canRequestReview':_row_permission(c,a,'contact.duplicate.review',dict(r)),'matchType':'manual_search','confidence':'manual'})
  return _result(items=items)

def _link_identity(c,a,contact,p):
 pv=str(p.get('platformId') or p.get('platformCode') or '').lower();platform=c.execute("SELECT * FROM platforms WHERE status='active' AND (lower(platform_id)=? OR lower(platform_code)=?)",(pv,pv)).fetchone()
 if not platform:raise ValueError('PLATFORM_NOT_FOUND')
 typ,raw,canonical=normalize_identity(platform['platform_code'],p.get('identityType'),p.get('identityValue'))
 if not canonical:raise ValueError('IDENTITY_REQUIRED')
 conflict=c.execute("SELECT contact_id FROM contact_identities WHERE organization_id=? AND workspace_id=? AND platform_id=? AND identity_type=? AND canonical_value=?",(a['organization_id'],contact['workspace_id'],platform['platform_id'],typ,canonical)).fetchone()
 if conflict and conflict['contact_id']!=contact['contact_id']:raise ValueError('IDENTITY_CONFLICT')
 if conflict:return None
 n=now_ms();iid='cid_'+uuid.uuid4().hex;primary=0 if c.execute('SELECT 1 FROM contact_identities WHERE contact_id=?',(contact['contact_id'],)).fetchone() else 1
 c.execute("INSERT INTO contact_identities(contact_identity_id,organization_id,workspace_id,contact_id,platform_id,identity_type,identity_value,canonical_value,verification_status,is_primary,first_seen_at,last_seen_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(iid,a['organization_id'],contact['workspace_id'],contact['contact_id'],platform['platform_id'],typ,raw,canonical,str(p.get('verificationStatus') or 'verified'),primary,n,n,dumps(p.get('metadata') or {})))
 return iid
def link_identity(db,a,cid,p,current=False):
 try:
  with db.tx() as c:
   # Linking an identity is a management operation. Never grant access as a side effect:
   # otherwise a caller could acquire contact access merely by knowing an identity.
   contact=_contact_access(c,a,cid,'manage')
   if not contact:return _result(False,404,code='CONTACT_NOT_FOUND',message='客户不存在或无管理权限')
   if not _row_permission(c,a,'contact.identity.link',dict(contact)):return _result(False,403,code='FORBIDDEN',message='客户超出身份关联授权范围')
   reason=str(p.get('reason') or '').strip()
   if not reason:return _result(False,400,code='LINK_REASON_REQUIRED',message='关联原因必填')
   iid=_link_identity(c,a,contact,p)
   conv=None
   if current and p.get('externalConversationId') and p.get('channelAccountId'):
    from V208_collector_service import _platform,_account_allowed,_create_conversation
    platform=_platform(c,p);account=_account_allowed(c,a,str(p['channelAccountId']),platform['platform_id']) if platform else None
    if not account:return _result(False,403,code='ACCOUNT_NOT_AUTHORIZED',message='渠道账号未授权')
    conv,_=_create_conversation(c,a,account,platform,cid,iid,str(p['externalConversationId']),now_ms());conv=dict(conv)
   _audit(c,a,'link-identity','contact',cid,{}, {'identityId':iid},reason)
   return _result(contactId=cid,contactIdentityId=iid,conversation=conv,entryState='registered')
 except ValueError as e:
  code=str(e);status=409 if code in ('IDENTITY_CONFLICT','CROSS_WORKSPACE_LINK_FORBIDDEN') else 400
  return _result(False,status,code=code,message={'IDENTITY_CONFLICT':'该身份已绑定其他客户','PLATFORM_NOT_FOUND':'平台不存在','IDENTITY_REQUIRED':'稳定身份缺失','TEAM_SCOPE_INVALID':'团队范围无效'}.get(code,code))
def access_list(db,a,cid):
 with db.tx(False) as c:
  contact=_contact_access(c,a,cid)
  if not contact:return _result(False,404,code='CONTACT_NOT_FOUND',message='客户不存在或无权访问')
  if not _row_permission(c,a,'contact.team_access',dict(contact)):return _result(False,403,code='FORBIDDEN',message='客户超出团队访问管理范围')
  items=_rows(c,"SELECT x.*,t.name AS team_name,u.display_name granted_by_name FROM contact_team_access x JOIN teams t ON t.team_id=x.team_id LEFT JOIN users u ON u.user_id=x.granted_by WHERE x.contact_id=? ORDER BY x.revoked_at IS NOT NULL,x.access_level DESC,x.granted_at",(cid,));return _result(items=items)
def set_access(db,a,cid,p):
 with db.tx() as c:
  contact=_contact_access(c,a,cid,'manage')
  if not contact:return _result(False,404,code='CONTACT_NOT_FOUND',message='客户不存在或无管理权限')
  if not _row_permission(c,a,'contact.team_access',dict(contact)):return _result(False,403,code='FORBIDDEN',message='客户超出团队访问管理范围')
  team=str(p.get('teamId') or '');level=str(p.get('accessLevel') or 'read');reason=str(p.get('reason') or '')[:500]
  if level not in ('read','edit','manage'):return _result(False,400,code='ACCESS_LEVEL_INVALID',message='访问级别无效')
  aid=grant_access_in_tx(c,a,contact,team,level,'manual_link',reason);_audit(c,a,'grant-team-access','contact',cid,{}, {'teamId':team,'accessLevel':level},reason);return _result(accessId=aid)
def revoke_access(db,a,cid,team,reason=''):
 with db.tx() as c:
  contact=_contact_access(c,a,cid,'manage')
  if not contact:return _result(False,404,code='CONTACT_NOT_FOUND',message='客户不存在或无管理权限')
  if not _row_permission(c,a,'contact.team_access',dict(contact)):return _result(False,403,code='FORBIDDEN',message='客户超出团队访问管理范围')
  if team==contact['team_id']:return _result(False,409,code='PRIMARY_TEAM_ACCESS_REQUIRED',message='不能撤销主团队访问')
  n=now_ms();changed=c.execute("UPDATE contact_team_access SET revoked_at=?,revoked_by=?,reason=? WHERE contact_id=? AND team_id=? AND revoked_at IS NULL",(n,a['user_id'],str(reason)[:500],cid,team)).rowcount
  _audit(c,a,'revoke-team-access','contact',cid,{'teamId':team},{'revoked':bool(changed)},reason);return _result(revoked=bool(changed))
def duplicates(db,a,cid):
 with db.tx(False) as c:
  contact=_contact_access(c,a,cid)
  if not contact:return _result(False,404,code='CONTACT_NOT_FOUND',message='客户不存在或无权访问')
  if not _row_permission(c,a,'contact.duplicate.review',dict(contact)):return _result(False,403,code='FORBIDDEN',message='客户超出查重审核范围')
  identities=_rows(c,"SELECT i.*,p.platform_code FROM contact_identities i LEFT JOIN platforms p ON p.platform_id=i.platform_id WHERE i.contact_id=?",(cid,));all_items={}
  for it in identities:
   p={'platformId':it['platform_id'],'contactIdentity':{'identityType':it['identity_type'],'identityValue':it['identity_value']},'excludeContactId':cid}
   for x in _candidate_rows(c,a,p,cid):all_items[x['contactId']]=x
  for ph in (contact['manual_phone'],contact['observed_phone']):
   if ph:
    for x in _candidate_rows(c,a,{'phone':ph},cid):all_items[x['contactId']]=x
  return _result(items=list(all_items.values()))
def ignore_match(db,a,p):
 x,y=sorted((str(p.get('contactIdA') or ''),str(p.get('contactIdB') or '')));reason=str(p.get('reason') or '').strip()
 if not x or not y or x==y or not reason:return _result(False,400,code='MATCH_REVIEW_INVALID',message='联系人和忽略原因必填')
 with db.tx() as c:
  ca=_contact_access(c,a,x);cb=_contact_access(c,a,y)
  if not ca or not cb:return _result(False,404,code='CONTACT_NOT_FOUND',message='客户不存在或无权访问')
  if not (_row_permission(c,a,'contact.duplicate.review',dict(ca)) and _row_permission(c,a,'contact.duplicate.review',dict(cb))):return _result(False,403,code='FORBIDDEN',message='客户超出查重审核范围')
  n=now_ms();rid='cmr_'+uuid.uuid4().hex
  c.execute("INSERT INTO contact_match_reviews(review_id,organization_id,workspace_id,contact_id_a,contact_id_b,match_type,confidence,evidence_json,status,reviewed_by,reviewed_at,reason,created_at,updated_at) VALUES(?,?,?,?,?,?,'high','{}','ignored',?,?,?,?,?) ON CONFLICT(organization_id,workspace_id,contact_id_a,contact_id_b,match_type) DO UPDATE SET status='ignored',reviewed_by=excluded.reviewed_by,reviewed_at=excluded.reviewed_at,reason=excluded.reason,updated_at=excluded.updated_at",(rid,a['organization_id'],ca['workspace_id'],x,y,str(p.get('matchType') or 'manual'),a['user_id'],n,reason,n,n));return _result(reviewed=True)
def _ensure_merge_requests(c):
 # 运行时自愈：兼容未执行补丁、旧补丁只创建一张表以及重复执行。
 c.executescript("""
 CREATE TABLE IF NOT EXISTS contact_merge_requests(
  request_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,
  target_contact_id TEXT NOT NULL,source_contact_id TEXT NOT NULL,requested_by TEXT NOT NULL,
  requested_team_id TEXT,reason TEXT NOT NULL,evidence_json TEXT NOT NULL DEFAULT '{}',
  suggested_resolution_json TEXT NOT NULL DEFAULT '{}',status TEXT NOT NULL DEFAULT 'pending'
   CHECK(status IN ('pending','executing','rejected','merged','failed','cancelled')),
  target_version INTEGER NOT NULL,source_version INTEGER NOT NULL,reviewed_by TEXT,reviewed_at INTEGER,
  review_comment TEXT NOT NULL DEFAULT '',executed_merge_id TEXT,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
 CREATE INDEX IF NOT EXISTS idx_merge_requests_queue ON contact_merge_requests(organization_id,status,workspace_id,updated_at);
 CREATE UNIQUE INDEX IF NOT EXISTS uq_merge_request_pending_pair ON contact_merge_requests(organization_id,workspace_id,target_contact_id,source_contact_id) WHERE status='pending';
 CREATE TABLE IF NOT EXISTS contact_merge_request_events(
  event_id TEXT PRIMARY KEY,request_id TEXT NOT NULL,event_type TEXT NOT NULL,actor_id TEXT NOT NULL,
  detail_json TEXT NOT NULL DEFAULT '{}',created_at INTEGER NOT NULL);
 CREATE INDEX IF NOT EXISTS idx_merge_request_events ON contact_merge_request_events(request_id,created_at);
 """)
 required={'contact_merge_requests':{'request_id','organization_id','workspace_id','target_contact_id','source_contact_id','requested_by','status','target_version','source_version'},'contact_merge_request_events':{'event_id','request_id','event_type','actor_id','detail_json','created_at'}}
 for table,columns in required.items():
  actual={r[1] for r in c.execute('PRAGMA table_info('+table+')')}
  missing=columns-actual
  if missing:raise RuntimeError('MERGE_GOVERNANCE_SCHEMA_INVALID:'+table+':'+','.join(sorted(missing)))

def _table_columns(c, table):
    """Return SQLite column names without assuming a specific historical schema."""
    try:
        return {str(r[1]) for r in c.execute("PRAGMA table_info(" + table + ")").fetchall()}
    except sqlite3.Error:
        return set()

def _active_admin_predicate(columns):
    """Build a compatible active-row predicate for old/new administrator schemas."""
    if 'status' in columns:
        return " AND LOWER(COALESCE(status,'active'))='active'"
    if 'is_active' in columns:
        return " AND COALESCE(is_active,1)=1"
    if 'enabled' in columns:
        return " AND COALESCE(enabled,1)=1"
    if 'disabled' in columns:
        return " AND COALESCE(disabled,0)=0"
    return ''

def _is_active_admin(c, table, user_id, organization_id=None):
    columns=_table_columns(c,table)
    if not columns or 'user_id' not in columns:return False
    sql="SELECT 1 FROM "+table+" WHERE user_id=?"
    args=[user_id]
    if organization_id is not None and 'organization_id' in columns:
        sql+=" AND organization_id=?";args.append(organization_id)
    sql+=_active_admin_predicate(columns)+" LIMIT 1"
    return c.execute(sql,tuple(args)).fetchone() is not None

def _supervisor_level(c,a):
 # Route permission remains necessary; service authorization is independently enforced here.
 uid=a.get('user_id');org=a.get('organization_id')
 if not uid or not org:return None
 # Reuse the module's schema-compatible administrator detector.
 if _is_active_admin(c,'platform_administrators',uid,org):return 'platform'
 if _is_active_admin(c,'organization_administrators',uid,org):return 'organization'
 try:
  permitted=c.execute("SELECT 1 FROM role_bindings rb JOIN role_permissions rp ON rp.role_id=rb.role_id WHERE rb.user_id=? AND rb.organization_id=? AND rb.status='active' AND rp.permission_key='contact.merge.review' LIMIT 1",(uid,org)).fetchone()
  if permitted and c.execute("SELECT 1 FROM team_memberships tm JOIN teams t ON t.team_id=tm.team_id WHERE tm.user_id=? AND tm.status='active' AND t.organization_id=? LIMIT 1",(uid,org)).fetchone():return 'team'
 except sqlite3.DatabaseError:pass
 try:role_ids={r[0] for r in c.execute("SELECT role_id FROM role_bindings WHERE user_id=? AND organization_id=? AND status='active'",(uid,org))}
 except sqlite3.DatabaseError:return None
 if role_ids & {'role_superadmin','role_orgadmin'}:return 'organization'
 if role_ids & {'role_teamlead','role-jbp-teamlead'}:return 'team'
 return None


def _merge_supervisor(c,a):return bool(_supervisor_level(c,a))
def _mre(c,rid,event,a,data=None):c.execute("INSERT INTO contact_merge_request_events VALUES(?,?,?,?,?,?)",('cmre_'+uuid.uuid4().hex,rid,event,a['user_id'],dumps(data or {}),now_ms()))
def create_merge_request(db,a,p):
 target=str(p.get('targetContactId') or '').strip();source=str(p.get('sourceContactId') or '').strip();reason=str(p.get('reason') or '').strip()
 if not target or not source or not reason:return _result(False,400,code='MERGE_REQUEST_INPUT_REQUIRED',message='主客户、来源客户和申请原因必填')
 if len(reason)>1000:return _result(False,400,code='MERGE_REASON_TOO_LONG',message='申请原因不能超过1000字')
 suggested=p.get('suggestedResolution',{})
 if not isinstance(suggested,dict) or not isinstance(suggested.get('fieldResolution',{}),dict) or not isinstance(suggested.get('basicResolution',{}),dict):return _result(False,400,code='MERGE_RESOLUTION_INVALID',message='冲突处理策略格式无效')
 with db.tx() as c:
  _ensure_merge_requests(c);t=_contact_access(c,a,target);x=_contact_access(c,a,source)
  if not t or not x:return _result(False,404,code='CONTACT_NOT_FOUND',message='客户不存在或无权访问')
  if not (_row_permission(c,a,'contact.merge.request',dict(t)) and _row_permission(c,a,'contact.merge.request',dict(x))):return _result(False,403,code='FORBIDDEN',message='客户超出合并申请授权范围')
  if target==source or t['organization_id']!=x['organization_id'] or t['workspace_id']!=x['workspace_id']:return _result(False,409,code='MERGE_SCOPE_INVALID',message='只能申请合并同企业同工作区的两个不同客户')
  old=c.execute("SELECT request_id FROM contact_merge_requests WHERE organization_id=? AND workspace_id=? AND ((target_contact_id=? AND source_contact_id=?) OR (target_contact_id=? AND source_contact_id=?)) AND status IN ('pending','executing')",(a['organization_id'],t['workspace_id'],target,source,source,target)).fetchone()
  if old:return _result(requestId=old[0],requestStatus='pending',deduplicated=True)
  rid='cmr_'+uuid.uuid4().hex;n=now_ms()
  c.execute("INSERT INTO contact_merge_requests(request_id,organization_id,workspace_id,target_contact_id,source_contact_id,requested_by,requested_team_id,reason,evidence_json,suggested_resolution_json,status,target_version,source_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,'pending',?,?,?,?)",(rid,a['organization_id'],t['workspace_id'],target,source,a['user_id'],a.get('team_id'),reason,dumps(p.get('evidence') if isinstance(p.get('evidence'),dict) else {}),dumps(suggested),t['version'],x['version'],n,n));_mre(c,rid,'submitted',a,{'reason':reason});return _result(requestId=rid,requestStatus='pending')
def list_merge_requests(db,a,q):
 with db.tx() as c:
  _ensure_merge_requests(c);level=_supervisor_level(c,a);where='r.organization_id=?';args=[a['organization_id']]
  if not level:where+=' AND r.requested_by=?';args.append(a['user_id'])
  elif level=='team':
   teams=[z[0] for z in c.execute("SELECT team_id FROM team_memberships WHERE user_id=? AND status='active'",(a['user_id'],))]
   if not teams:where+=' AND 0'
   else:
    marks=','.join('?'*len(teams));where+=f' AND (r.requested_team_id IN ({marks}) OR t.team_id IN ({marks}) OR s.team_id IN ({marks}))';args+=teams+teams+teams
  status=str(q.get('status') or '').strip()
  if status=='actionable':where+=" AND r.status IN ('pending','failed','executing')"
  elif status:where+=' AND r.status=?';args.append(status)
  items=_rows(c,"SELECT r.*,COALESCE(NULLIF(t.manual_name,''),NULLIF(t.display_name,''),t.contact_id) target_display_name,COALESCE(NULLIF(s.manual_name,''),NULLIF(s.display_name,''),s.contact_id) source_display_name,u.display_name requester_name,tt.name target_team_name,st.name source_team_name,tu.display_name target_owner_name,su.display_name source_owner_name FROM contact_merge_requests r JOIN contacts t ON t.contact_id=r.target_contact_id JOIN contacts s ON s.contact_id=r.source_contact_id LEFT JOIN users u ON u.user_id=r.requested_by LEFT JOIN teams tt ON tt.team_id=t.team_id LEFT JOIN teams st ON st.team_id=s.team_id LEFT JOIN users tu ON tu.user_id=t.owner_user_id LEFT JOIN users su ON su.user_id=s.owner_user_id WHERE "+where+" ORDER BY r.updated_at DESC LIMIT 500",args);return _result(items=items,canReview=bool(level),reviewLevel=level or 'self')
def _merge_preview_for_approval(db,a,target,source):
 try:
  with db.tx() as c:return _merge_preview_in_tx(c,a,target,source,approval_execution=True)
 except sqlite3.DatabaseError:
  logging.exception('approval merge preview failed');return _result(False,500,code='MERGE_PREVIEW_FAILED',message='审批前重新核对客户失败')

def review_merge_request(db,a,rid,p):
 action=str(p.get('action') or '');comment=str(p.get('comment') or '').strip()
 if action not in ('approve','reject') or not comment:return _result(False,400,code='REVIEW_INPUT_INVALID',message='审批动作和意见必填')
 with db.tx() as c:
  _ensure_merge_requests(c);level=_supervisor_level(c,a)
  if not level:return _result(False,403,code='FORBIDDEN',message='仅主管以上可审批')
  r=c.execute("SELECT r.*,t.team_id target_team_id,s.team_id source_team_id,s.deleted_at source_deleted_at,s.delete_reason source_delete_reason FROM contact_merge_requests r JOIN contacts t ON t.contact_id=r.target_contact_id AND t.organization_id=r.organization_id JOIN contacts s ON s.contact_id=r.source_contact_id AND s.organization_id=r.organization_id WHERE r.request_id=? AND r.organization_id=? AND r.status IN ('pending','failed','executing')",(rid,a['organization_id'])).fetchone()
  if not r:return _result(False,409,code='MERGE_REQUEST_STATE_CONFLICT',message='申请不存在、已完成或不可处理')
  if r['requested_by']==a['user_id']:return _result(False,403,code='SELF_APPROVAL_FORBIDDEN',message='申请人不能审批自己的合并申请')
  if level=='team':
   teams={z[0] for z in c.execute("SELECT team_id FROM team_memberships WHERE user_id=? AND status='active'",(a['user_id'],))}
   if not teams or not ({r['requested_team_id'],r['target_team_id'],r['source_team_id']} & teams):return _result(False,403,code='FORBIDDEN',message='申请超出主管团队范围')
  # Reconcile a merge committed before request-state bookkeeping completed.
  if action=='approve' and r['source_deleted_at'] and r['source_delete_reason']=='merged:'+r['target_contact_id']:
   hist=c.execute("SELECT merge_id FROM contact_merge_history WHERE target_contact_id=? AND source_contact_id=? AND status='completed' ORDER BY created_at DESC LIMIT 1",(r['target_contact_id'],r['source_contact_id'])).fetchone()
   if hist:
    c.execute("UPDATE contact_merge_requests SET status='merged',reviewed_by=COALESCE(reviewed_by,?),reviewed_at=COALESCE(reviewed_at,?),review_comment=COALESCE(review_comment,?),executed_merge_id=?,updated_at=? WHERE request_id=?",(a['user_id'],now_ms(),comment,hist[0],now_ms(),rid));_mre(c,rid,'reconciled',a,{'mergeId':hist[0]});return _result(requestId=rid,requestStatus='merged',mergeId=hist[0],merged=True,reconciled=True)
  if action=='reject':
   c.execute("UPDATE contact_merge_requests SET status='rejected',reviewed_by=?,reviewed_at=?,review_comment=?,updated_at=? WHERE request_id=?",(a['user_id'],now_ms(),comment,now_ms(),rid));_mre(c,rid,'rejected',a,{'comment':comment});return _result(requestId=rid,requestStatus='rejected')
  c.execute("UPDATE contact_merge_requests SET status='executing',reviewed_by=?,reviewed_at=?,review_comment=?,updated_at=? WHERE request_id=?",(a['user_id'],now_ms(),comment,now_ms(),rid));_mre(c,rid,'executing',a,{'comment':comment,'retryFrom':r['status']})
 resolution=loads(r['suggested_resolution_json']) or {}
 # Re-read and re-preview at approval time. A stale request may be retried safely, but newly introduced conflicts require review.
 with db.tx() as c:
  current_t=c.execute("SELECT version FROM contacts WHERE contact_id=? AND organization_id=? AND deleted_at IS NULL",(r['target_contact_id'],a['organization_id'])).fetchone();current_s=c.execute("SELECT version FROM contacts WHERE contact_id=? AND organization_id=? AND deleted_at IS NULL",(r['source_contact_id'],a['organization_id'])).fetchone()
  if not current_t or not current_s:
   current_t=current_s=None
 if not current_t or not current_s:
  result={'ok':False,'code':'CONTACT_NOT_FOUND','message':'待合并客户不存在或已经被处理'};http=409
 else:
  preview,http=_merge_preview_for_approval(db,a,r['target_contact_id'],r['source_contact_id'])
  selected=resolution.get('fieldResolution') or {};basic=resolution.get('basicResolution') or {}
  unresolved=[x.get('fieldKey') for x in (preview.get('fieldConflicts') or []) if x.get('fieldKey') not in selected]
  unresolved += [x.get('field') for x in (preview.get('basicConflicts') or []) if x.get('field') not in basic]
  if not preview.get('ok') or unresolved:
   result={'ok':False,'code':'MERGE_REVIEW_REQUIRED_AGAIN','message':'客户资料在申请后发生变化，请重新核对冲突策略','unresolvedFields':unresolved,'preview':preview};http=409
  else:
   payload={'sourceContactId':r['source_contact_id'],'reason':'审批合并：'+comment,'baseTargetVersion':current_t[0],'baseSourceVersion':current_s[0],'fieldResolution':selected,'basicResolution':basic}
   result=http=None
 if result is None:
  try:result,http=merge_contacts(db,a,r['target_contact_id'],payload,approval_execution=True)
  except Exception:
   logging.exception('approved contact merge execution failed');result={'ok':False,'code':'MERGE_EXECUTION_ERROR','message':'审批已记录，但合并执行异常且已回滚'};http=500
 with db.tx() as c:
  state='merged' if result.get('ok') and result.get('mergeId') else 'failed';c.execute("UPDATE contact_merge_requests SET status=?,executed_merge_id=?,updated_at=? WHERE request_id=?",(state,result.get('mergeId'),now_ms(),rid));_mre(c,rid,state,a,result)
 if not result.get('ok'):return ({**result,'requestId':rid,'requestStatus':'failed'},http)
 return _result(requestId=rid,requestStatus='merged',mergeId=result['mergeId'],targetContactId=result.get('targetContactId'),sourceContactId=result.get('sourceContactId'),merged=True)

def _count(c,table,cid):
 try:return c.execute('SELECT count(*) FROM '+table+' WHERE contact_id=?',(cid,)).fetchone()[0]
 except sqlite3.OperationalError:return 0
def _merge_preview_in_tx(c,a,target,source,request_mode=False,approval_execution=False):
 if approval_execution:
  t=c.execute("SELECT * FROM contacts WHERE contact_id=? AND organization_id=? AND deleted_at IS NULL",(target,a['organization_id'])).fetchone();s=c.execute("SELECT * FROM contacts WHERE contact_id=? AND organization_id=? AND deleted_at IS NULL",(source,a['organization_id'])).fetchone()
 else:t=_contact_access(c,a,target,'manage');s=_contact_access(c,a,source,'manage')
 if not t or not s:return _result(False,404,code='CONTACT_NOT_FOUND',message='客户不存在或无权访问')
 can_merge=bool(approval_execution) or (_row_permission(c,a,'contact.merge',dict(t)) and _row_permission(c,a,'contact.merge',dict(s)))
 can_request=_row_permission(c,a,'contact.merge.request',dict(t)) and _row_permission(c,a,'contact.merge.request',dict(s))
 if not can_merge and not (request_mode and can_request):return _result(False,403,code='FORBIDDEN',message='客户超出合并或合并申请授权范围')
 if target==source or t['workspace_id']!=s['workspace_id']:return _result(False,409,code='MERGE_SCOPE_INVALID',message='只能合并同工作区的两个不同客户')
 tables=('contact_identities','contact_custom_values','contact_tags','conversations','conversation_messages','source_touchpoints','contact_attributions','contact_transfers','contact_conversions')
 impact={x:{'target':_count(c,x,target),'source':_count(c,x,source)} for x in tables}
 tv={r['field_key']:loads(r['value_json']) for r in c.execute('SELECT field_key,value_json FROM contact_custom_values WHERE contact_id=?',(target,))};sv={r['field_key']:loads(r['value_json']) for r in c.execute('SELECT field_key,value_json FROM contact_custom_values WHERE contact_id=?',(source,))}
 conflicts=[{'fieldKey':k,'targetValue':tv.get(k),'sourceValue':sv.get(k)} for k in sorted(set(tv)&set(sv)) if tv[k]!=sv[k]]
 basic=[]
 for col in ('manual_name','manual_phone','remark','status'):
  if t[col] and s[col] and t[col]!=s[col]:basic.append({'field':col,'targetValue':t[col],'sourceValue':s[col]})
 tp=c.execute('SELECT attribution_id FROM contact_attributions WHERE contact_id=? AND is_primary=1 ORDER BY attributed_at DESC,attribution_id DESC LIMIT 1',(target,)).fetchone()
 sp=c.execute('SELECT attribution_id FROM contact_attributions WHERE contact_id=? AND is_primary=1 ORDER BY attributed_at DESC,attribution_id DESC LIMIT 1',(source,)).fetchone()
 attribution_policy={'targetPrimaryId':tp[0] if tp else None,'sourcePrimaryId':sp[0] if sp else None,'keptPrimaryId':tp[0] if tp else (sp[0] if sp else None),'sourcePrimaryWillBeDemoted':bool(tp and sp)}
 return _result(target={'contactId':target,'name':t['manual_name'] or t['display_name'],'version':t['version']},source={'contactId':source,'name':s['manual_name'] or s['display_name'],'version':s['version']},impact=impact,fieldConflicts=conflicts,basicConflicts=basic,attributionPolicy=attribution_policy,canMerge=bool(can_merge),canRequestMerge=bool(can_request))
def merge_preview(db,a,p):
 target=str(p.get('targetContactId') or '');source=str(p.get('sourceContactId') or '')
 with db.tx(False) as c:return _merge_preview_in_tx(c,a,target,source,True)

def _qi(name):return '"'+str(name).replace('"','""')+'"'

def _conversation_fk_columns(c,table):
 cols=[]
 for fk in c.execute('PRAGMA foreign_key_list('+_qi(table)+')').fetchall():
  # SQLite reports None for an implicit reference to the sole conversations PK.
  if fk[2]=='conversations' and fk[4] in ('conversation_id',None):cols.append(fk[3])
 return sorted(set(cols))

def _repoint_conversation_references(c,source_conversation,target_conversation,target_contact):
 """Move every declared conversation FK in one statement per table.
 Updating contact_id in the same statement is required by scope triggers."""
 tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
 for table in sorted(tables):
  if table in ('conversation_messages','conversations'):continue
  fkcols=_conversation_fk_columns(c,table)
  if not fkcols:continue
  cols={r[1] for r in c.execute('PRAGMA table_info('+_qi(table)+')')}
  sets=[];args=[]
  for col in fkcols:
   sets.append(_qi(col)+'=CASE WHEN '+_qi(col)+'=? THEN ? ELSE '+_qi(col)+' END');args += [source_conversation,target_conversation]
  where=' OR '.join(_qi(col)+'=?' for col in fkcols);args += [source_conversation]*len(fkcols)
  if 'contact_id' in cols:
   sets.append(_qi('contact_id')+'=CASE WHEN '+_qi('contact_id')+'=? THEN ? ELSE '+_qi('contact_id')+' END');args += [None,None]
   # contact arguments belong before WHERE arguments.
   args=args[:-2-len(fkcols)]+[source_conversation,target_conversation]*(0) if False else args
   # Rebuild args in SQL placeholder order for clarity.
   args=[]
   for col in fkcols:args += [source_conversation,target_conversation]
   args += [None] if False else []
   args += []
   # contact SET precedes WHERE only after all FK SET placeholders.
   args += [None,None]
   args[-2:]=['__SOURCE_CONTACT__',target_contact]
   args += [source_conversation]*len(fkcols)
  try:
   # Replace sentinel with the row's current source contact through SQL predicate-independent CASE.
   if 'contact_id' in cols:
    sql='UPDATE '+_qi(table)+' SET '+','.join(sets)+' WHERE '+where
    # Source contact is obtained from referenced source conversation.
    source_contact=c.execute('SELECT contact_id FROM conversations WHERE conversation_id=?',(source_conversation,)).fetchone()[0]
    args=[source_contact if x=='__SOURCE_CONTACT__' else x for x in args]
   else:sql='UPDATE '+_qi(table)+' SET '+','.join(sets)+' WHERE '+where
   c.execute(sql,tuple(args))
  except sqlite3.IntegrityError as e:raise ValueError('MERGE_CONVERSATION_REFERENCE_CONFLICT:'+table+':'+str(e))

def _rebuild_conversation_summary(c,conversation_id):
 cols={r[1] for r in c.execute('PRAGMA table_info(conversations)')}
 mcols={r[1] for r in c.execute('PRAGMA table_info(conversation_messages)')}
 rows=c.execute("SELECT * FROM conversation_messages WHERE conversation_id=? ORDER BY COALESCE(occurred_at,collected_at,0),message_id",(conversation_id,)).fetchall()
 active=[r for r in rows if ('deleted_at' not in mcols or r['deleted_at'] is None)]
 first=active[0] if active else None;last=active[-1] if active else None
 values={}
 if 'message_count' in cols:values['message_count']=len(active)
 if 'inbound_count' in cols:values['inbound_count']=sum(1 for r in active if r['direction']=='inbound')
 if 'outbound_count' in cols:values['outbound_count']=sum(1 for r in active if r['direction']=='outbound')
 if 'first_message_at' in cols:values['first_message_at']=(first['occurred_at'] if first else None)
 if 'last_message_at' in cols:values['last_message_at']=(last['occurred_at'] if last else None)
 if 'last_message_id' in cols:values['last_message_id']=(last['message_id'] if last else None)
 if 'last_message_direction' in cols:values['last_message_direction']=(last['direction'] if last else None)
 if 'last_message_type' in cols:values['last_message_type']=(last['content_type'] if last else None)
 if 'last_message_preview' in cols:
  text=((last['redacted_text'] if last and 'redacted_text' in mcols else None) or (last['text_content'] if last and 'text_content' in mcols else None) or '')
  values['last_message_preview']=str(text)[:500]
 if 'updated_at' in cols:values['updated_at']=now_ms()
 if values:c.execute('UPDATE conversations SET '+','.join(_qi(k)+'=?' for k in values)+' WHERE conversation_id=?',tuple(values.values())+(conversation_id,))

def _merge_contact_conversations(c,target,source):
 """Migrate conversations without disabling Schema 222 scope triggers."""
 source_rows=list(c.execute("SELECT * FROM conversations WHERE contact_id=? ORDER BY created_at,conversation_id",(source,)))
 for conv in source_rows:
  sid=conv['conversation_id'];collision=None
  if str(conv['conversation_type'] or 'direct')=='direct':
   collision=c.execute("SELECT * FROM conversations WHERE organization_id=? AND channel_account_id=? AND contact_id=? AND conversation_type='direct' AND conversation_id<>? ORDER BY created_at,conversation_id LIMIT 1",(conv['organization_id'],conv['channel_account_id'],target,sid)).fetchone()
  if not collision:
   # Conversation first: the message update trigger can then see the target scope.
   try:c.execute('UPDATE conversations SET contact_id=?,updated_at=? WHERE conversation_id=?',(target,now_ms(),sid))
   except sqlite3.IntegrityError as e:raise ValueError('MERGE_CONVERSATION_CONFLICT:'+sid+':'+str(e))
   c.execute('UPDATE conversation_messages SET contact_id=? WHERE conversation_id=? AND contact_id=?',(target,sid,source))
   _rebuild_conversation_summary(c,sid);continue
  tid=collision['conversation_id']
  # Message conversation_id and contact_id must change atomically for MESSAGE_SCOPE_MISMATCH.
  try:c.execute('UPDATE conversation_messages SET conversation_id=?,contact_id=? WHERE conversation_id=?',(tid,target,sid))
  except sqlite3.IntegrityError as e:raise ValueError('MERGE_CONVERSATION_MESSAGE_CONFLICT:'+sid+':'+str(e))
  _repoint_conversation_references(c,sid,tid,target)
  remain=c.execute('SELECT 1 FROM conversation_messages WHERE conversation_id=? LIMIT 1',(sid,)).fetchone()
  if remain:raise ValueError('MERGE_CONVERSATION_NOT_EMPTY:'+sid)
  try:c.execute('DELETE FROM conversations WHERE conversation_id=?',(sid,))
  except sqlite3.IntegrityError as e:raise ValueError('MERGE_CONVERSATION_REFERENCE_CONFLICT:'+sid+':'+str(e))
  _rebuild_conversation_summary(c,tid)
 # Strong postcondition while source contact is still present.
 if c.execute('SELECT 1 FROM conversations WHERE contact_id=? LIMIT 1',(source,)).fetchone():raise ValueError('MERGE_CONVERSATION_SOURCE_REMAINS')
 mismatch=c.execute("SELECT 1 FROM conversation_messages m LEFT JOIN conversations v ON v.conversation_id=m.conversation_id AND v.organization_id=m.organization_id AND v.workspace_id=m.workspace_id AND v.team_id=m.team_id AND v.channel_account_id=m.channel_account_id AND v.contact_id=m.contact_id WHERE (m.contact_id=? OR v.contact_id=?) AND v.conversation_id IS NULL LIMIT 1",(target,target)).fetchone()
 if mismatch:raise ValueError('MERGE_MESSAGE_SCOPE_INVARIANT')

def _tables_with_contact_id(c):
 out=[]
 for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
  cols=[x[1] for x in c.execute('PRAGMA table_info("'+r[0].replace('"','""')+'")')]
  if 'contact_id' in cols:out.append(r[0])
 return out
def merge_contacts(db,a,target,p,approval_execution=False):
 source=str(p.get('sourceContactId') or '');reason=str(p.get('reason') or '').strip();res=p.get('fieldResolution') or {};basic=p.get('basicResolution') or {}
 if not source or not reason:return _result(False,400,code='MERGE_REASON_REQUIRED',message='来源客户和合并原因必填')
 try:
  with db.tx() as c:
   if approval_execution:
    t=c.execute("SELECT * FROM contacts WHERE contact_id=? AND organization_id=? AND deleted_at IS NULL",(target,a['organization_id'])).fetchone();s=c.execute("SELECT * FROM contacts WHERE contact_id=? AND organization_id=? AND deleted_at IS NULL",(source,a['organization_id'])).fetchone()
   else:t=_contact_access(c,a,target,'manage');s=_contact_access(c,a,source,'manage')
   if not t or not s:return _result(False,404,code='CONTACT_NOT_FOUND',message='客户不存在或无管理权限')
   if not approval_execution and not (_row_permission(c,a,'contact.merge',dict(t)) and _row_permission(c,a,'contact.merge',dict(s))):return _result(False,403,code='FORBIDDEN',message='客户超出合并授权范围')
   if target==source or t['workspace_id']!=s['workspace_id']:return _result(False,409,code='MERGE_SCOPE_INVALID',message='只能合并同工作区客户')
   if int(p.get('baseTargetVersion',-1))!=t['version'] or int(p.get('baseSourceVersion',-1))!=s['version']:return _result(False,409,code='CONTACT_VERSION_CONFLICT',message='客户资料已变化，请重新预览')
   preview=_merge_preview_in_tx(c,a,target,source,approval_execution=approval_execution)[0]
   if not preview.get('ok'):return preview,404
   # Refuse unknown references before the first write. Adding a new contact_id table
   # must be accompanied by an explicit, reviewed migration strategy.
   reference_tables=set(_tables_with_contact_id(c))
   handled={'contacts','contact_identities','contact_custom_values','contact_tags','contact_team_access','contact_attributions','conversations','conversation_messages'}
   direct_move={'source_touchpoints','contact_transfers','contact_transfer_events','contact_conversions','contact_events','contact_notes','contact_tasks','conversation_external_aliases','follow_up_notifications','whatsapp_identity_links'}
   unsupported=sorted(reference_tables-handled-direct_move)
   if unsupported:raise ValueError('MERGE_REFERENCE_TABLE_UNSUPPORTED:'+','.join(unsupported))
   # Resolve basic fields explicitly; empty target automatically receives source.
   updates={}
   for col in ('manual_name','manual_phone','remark','status'):
    if not t[col] and s[col]:updates[col]=s[col]
    elif t[col] and s[col] and t[col]!=s[col]:
     choice=basic.get(col)
     if choice=='source':updates[col]=s[col]
     elif choice=='combine' and col=='remark':updates[col]=(t[col]+'\n'+s[col])[:4000]
     elif choice not in ('target',):raise ValueError('UNRESOLVED_BASIC_CONFLICT:'+col)
   # identities: redirect conversations, remove exact duplicate, then move remaining.
   for it in list(c.execute('SELECT * FROM contact_identities WHERE contact_id=?',(source,))):
    dup=c.execute("SELECT * FROM contact_identities WHERE contact_id=? AND platform_id IS ? AND identity_type=? AND canonical_value=?",(target,it['platform_id'],it['identity_type'],it['canonical_value'])).fetchone()
    if dup:
     c.execute('UPDATE conversations SET contact_identity_id=? WHERE contact_identity_id=?',(dup['contact_identity_id'],it['contact_identity_id']));c.execute('DELETE FROM contact_identities WHERE contact_identity_id=?',(it['contact_identity_id'],))
    else:c.execute('UPDATE contact_identities SET contact_id=?,is_primary=0 WHERE contact_identity_id=?',(target,it['contact_identity_id']))
   if not c.execute('SELECT 1 FROM contact_identities WHERE contact_id=? AND is_primary=1',(target,)).fetchone():
    first=c.execute('SELECT contact_identity_id FROM contact_identities WHERE contact_id=? ORDER BY first_seen_at LIMIT 1',(target,)).fetchone()
    if first:c.execute('UPDATE contact_identities SET is_primary=1 WHERE contact_identity_id=?',(first[0],))
   # values and tags
   for v in list(c.execute('SELECT * FROM contact_custom_values WHERE contact_id=?',(source,))):
    old=c.execute('SELECT * FROM contact_custom_values WHERE contact_id=? AND field_key=?',(target,v['field_key'])).fetchone()
    if not old:c.execute('UPDATE contact_custom_values SET contact_id=? WHERE contact_id=? AND field_key=?',(target,source,v['field_key']))
    else:
     a_val,b_val=loads(old['value_json']),loads(v['value_json']);choice=res.get(v['field_key'])
     if a_val!=b_val:
      if choice=='source':c.execute('UPDATE contact_custom_values SET value_json=?,updated_at=?,updated_by=? WHERE contact_id=? AND field_key=?',(v['value_json'],now_ms(),a['user_id'],target,v['field_key']))
      elif choice=='union' and isinstance(a_val,list) and isinstance(b_val,list):c.execute('UPDATE contact_custom_values SET value_json=?,updated_at=?,updated_by=? WHERE contact_id=? AND field_key=?',(dumps(list(dict.fromkeys(a_val+b_val))),now_ms(),a['user_id'],target,v['field_key']))
      elif choice!='target':raise ValueError('UNRESOLVED_FIELD_CONFLICT:'+v['field_key'])
     c.execute('DELETE FROM contact_custom_values WHERE contact_id=? AND field_key=?',(source,v['field_key']))
   c.execute('INSERT OR IGNORE INTO contact_tags(contact_id,tag_id,created_at) SELECT ?,tag_id,created_at FROM contact_tags WHERE contact_id=?',(target,source));c.execute('DELETE FROM contact_tags WHERE contact_id=?',(source,))
   # team grants deduplicated
   for x in list(c.execute('SELECT * FROM contact_team_access WHERE contact_id=?',(source,))):
    old=c.execute('SELECT * FROM contact_team_access WHERE contact_id=? AND team_id=?',(target,x['team_id'])).fetchone()
    if old:
     if _level_rank(x['access_level'])>_level_rank(old['access_level']):c.execute('UPDATE contact_team_access SET access_level=?,source_type=\'merge\' WHERE access_id=?',(x['access_level'],old['access_id']))
     c.execute('DELETE FROM contact_team_access WHERE access_id=?',(x['access_id'],))
    else:c.execute("UPDATE contact_team_access SET contact_id=?,source_type='merge' WHERE access_id=?",(target,x['access_id']))
   # Attribution has a partial unique index: one primary attribution per contact.
   # Resolve both primaries before changing contact_id and preserve every row.
   attribution_resolution=dict(preview.get('attributionPolicy') or {})
   target_primary=c.execute('SELECT attribution_id FROM contact_attributions WHERE contact_id=? AND is_primary=1 ORDER BY attributed_at DESC,attribution_id DESC LIMIT 1',(target,)).fetchone()
   source_primaries=list(c.execute('SELECT attribution_id FROM contact_attributions WHERE contact_id=? AND is_primary=1 ORDER BY attributed_at DESC,attribution_id DESC',(source,)))
   demoted=[]
   if target_primary and source_primaries:
    demoted=[x[0] for x in source_primaries];c.execute('UPDATE contact_attributions SET is_primary=0 WHERE contact_id=? AND is_primary=1',(source,))
   c.execute('UPDATE contact_attributions SET contact_id=? WHERE contact_id=?',(target,source))
   primaries=list(c.execute('SELECT attribution_id FROM contact_attributions WHERE contact_id=? AND is_primary=1 ORDER BY attributed_at DESC,attribution_id DESC',(target,)))
   if len(primaries)>1:raise ValueError('MERGE_ATTRIBUTION_PRIMARY_INVARIANT')
   attribution_resolution.update({'keptPrimaryId':primaries[0][0] if primaries else None,'demotedSourcePrimaryIds':demoted,'movedCount':preview.get('impact',{}).get('contact_attributions',{}).get('source',0)})
   # Trigger-safe conversation migration, including same-account direct-conversation collisions.
   _merge_contact_conversations(c,target,source)
   for table in sorted((reference_tables & direct_move)-{'conversations','conversation_messages'}):
    try:c.execute('UPDATE "'+table.replace('"','""')+'" SET contact_id=? WHERE contact_id=?',(target,source))
    except sqlite3.IntegrityError:raise ValueError('MERGE_REFERENCE_CONFLICT:'+table)
   if updates:c.execute('UPDATE contacts SET '+','.join(k+'=?' for k in updates)+',version=version+1,updated_at=? WHERE contact_id=?',tuple(updates.values())+(now_ms(),target))
   else:c.execute('UPDATE contacts SET version=version+1,updated_at=? WHERE contact_id=?',(now_ms(),target))
   c.execute("UPDATE contacts SET deleted_at=?,deleted_by=?,delete_reason=?,updated_at=? WHERE contact_id=?",(now_ms(),a['user_id'],'merged:'+target,now_ms(),source))
   mid='cmh_'+uuid.uuid4().hex;after={'targetVersion':t['version']+1,'movedFrom':source,'attribution':attribution_resolution}
   c.execute("INSERT INTO contact_merge_history(merge_id,organization_id,workspace_id,target_contact_id,source_contact_id,target_version_before,source_version_before,resolution_json,impact_json,before_json,after_json,status,merged_by,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,'completed',?,?,?)",(mid,a['organization_id'],t['workspace_id'],target,source,t['version'],s['version'],dumps({'basic':basic,'fields':res,'attribution':attribution_resolution}),dumps(preview.get('impact',{})),dumps({'target':dict(t),'source':dict(s)}),dumps(after),a['user_id'],reason,now_ms()))
   x,y=sorted((target,source));c.execute("UPDATE contact_match_reviews SET status='merged',reviewed_by=?,reviewed_at=?,updated_at=?,reason=? WHERE organization_id=? AND workspace_id=? AND contact_id_a=? AND contact_id_b=?",(a['user_id'],now_ms(),now_ms(),reason,a['organization_id'],t['workspace_id'],x,y))
   _audit(c,dict(a,workspace_id=t['workspace_id']),'merge-contact','contact',target,{'source':source},after,reason)
   verified=c.execute("SELECT deleted_at,delete_reason FROM contacts WHERE contact_id=? AND organization_id=?",(source,a['organization_id'])).fetchone();history=c.execute("SELECT 1 FROM contact_merge_history WHERE merge_id=? AND status='completed'",(mid,)).fetchone()
   if not verified or not verified['deleted_at'] or verified['delete_reason']!='merged:'+target or not history:raise ValueError('MERGE_PERSISTENCE_VERIFICATION_FAILED')
   return _result(mergeId=mid,targetContactId=target,sourceContactId=source,merged=True)
 except ValueError as e:return _result(False,409,code=str(e).split(':')[0],message=str(e))
 except sqlite3.IntegrityError as e:
  logging.exception('contact merge integrity conflict');return _result(False,409,code='MERGE_INTEGRITY_CONFLICT',message='客户关联数据存在唯一性冲突，合并已完整回滚')
 except sqlite3.DatabaseError as e:
  logging.exception('contact merge database failure');return _result(False,500,code='MERGE_DATABASE_ERROR',message='合并事务失败，全部变更已回滚')

def _governance_allowed(db,a,permission,org):
 return bool(a and org==a.get('organization_id') and (is_platform_admin(db,a) or has_permission_in_any_scope(db,a,permission,org)))

def _governance_forbidden(h):
 return _bad(h,'FORBIDDEN','无此客户治理操作权限',403)

def _handle_admin_impl(h,m,seg,q,a,db,org):
 # seg starts with contact-center; every governance route has a dedicated RBAC gate.
 if len(seg)==2 and seg[1]=='merge-requests' and m=='POST':
  if not _governance_allowed(db,a,'contact.merge.request',org):return _governance_forbidden(h)
  r,status=create_merge_request(db,a,h.body());return _send(h,r,status)
 if len(seg)==2 and seg[1]=='merge-requests' and m=='GET':
  if not (_governance_allowed(db,a,'contact.merge.request',org) or _governance_allowed(db,a,'contact.merge.review',org)):return _governance_forbidden(h)
  r,status=list_merge_requests(db,a,q);return _send(h,r,status)
 if len(seg)==4 and seg[1]=='merge-requests' and seg[3]=='review' and m=='POST':
  if not _governance_allowed(db,a,'contact.merge.review',org):return _governance_forbidden(h)
  r,status=review_merge_request(db,a,seg[2],h.body());return _send(h,r,status)
 if len(seg)==2 and seg[1]=='merge-preview' and m=='POST':
  if not (_governance_allowed(db,a,'contact.merge',org) or _governance_allowed(db,a,'contact.merge.request',org)):return _governance_forbidden(h)
  r,s=merge_preview(db,a,h.body());return _send(h,r,s)
 if len(seg)==2 and seg[1]=='contact-search' and m=='POST':
  if not (_governance_allowed(db,a,'contact.identity.link',org) or _governance_allowed(db,a,'contact.merge',org) or _governance_allowed(db,a,'contact.merge.request',org)):return _governance_forbidden(h)
  r,s=search_contacts(db,a,h.body());return _send(h,r,s)
 if len(seg)==2 and seg[1]=='match-reviews' and m=='POST':
  if not _governance_allowed(db,a,'contact.duplicate.review',org):return _governance_forbidden(h)
  r,s=ignore_match(db,a,h.body());return _send(h,r,s)
 if len(seg)>=3 and seg[1]=='contacts':
  cid=seg[2]
  if len(seg)==4 and seg[3]=='duplicates' and m=='GET':
   if not _governance_allowed(db,a,'contact.duplicate.review',org):return _governance_forbidden(h)
   r,s=duplicates(db,a,cid);return _send(h,r,s)
  if len(seg)==4 and seg[3]=='team-access' and m=='GET':
   if not _governance_allowed(db,a,'contact.team_access',org):return _governance_forbidden(h)
   r,s=access_list(db,a,cid);return _send(h,r,s)
  if len(seg)==4 and seg[3]=='team-access' and m=='POST':
   if not _governance_allowed(db,a,'contact.team_access',org):return _governance_forbidden(h)
   r,s=set_access(db,a,cid,h.body());return _send(h,r,s)
  if len(seg)==5 and seg[3]=='team-access' and m=='DELETE':
   if not _governance_allowed(db,a,'contact.team_access',org):return _governance_forbidden(h)
   r,s=revoke_access(db,a,cid,seg[4],(h.body() or {}).get('reason',''));return _send(h,r,s)
  if len(seg)==5 and seg[3]=='identities' and seg[4]=='link' and m=='POST':
   if not _governance_allowed(db,a,'contact.identity.link',org):return _governance_forbidden(h)
   r,s=link_identity(db,a,cid,h.body());return _send(h,r,s)
  if len(seg)==4 and seg[3]=='merge' and m=='POST':
   if not _governance_allowed(db,a,'contact.merge',org):return _governance_forbidden(h)
   r,s=merge_contacts(db,a,cid,h.body());return _send(h,r,s)
 return False

def handle_admin(h,m,seg,q,a,db,org):
 try:
  # Never mutate the authenticated session object while resolving target scope.
  request_actor=dict(a)
  return _handle_admin_impl(h,m,seg,q,request_actor,db,org)
 except sqlite3.OperationalError:
  logging.exception('contact governance schema/database operation failed')
  return _bad(h,'GOVERNANCE_SCHEMA_ERROR','客户治理数据库结构不完整或暂时不可用，请执行数据库修复后重试',503)
 except sqlite3.DatabaseError:
  logging.exception('contact governance database failed')
  return _bad(h,'GOVERNANCE_DATABASE_ERROR','客户治理数据操作失败，请稍后重试',500)
 except Exception:
  logging.exception('contact governance unexpected failure')
  return _bad(h,'GOVERNANCE_INTERNAL_ERROR','客户治理操作失败，请查看服务端日志',500)

