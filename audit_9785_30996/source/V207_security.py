import sqlite3
# -*- coding: utf-8 -*-
"""V207 身份、会话、登录锁定与 RBAC。"""
import hashlib,hmac,secrets,json
from V207_shared_db import now_ms,dumps,default_workspace_id
SESSION_MS=7*24*60*60*1000; LOCK_MS=15*60*1000; MAX_FAILURES=5
def canonical(v):return ''.join(str(v or '').strip().lower().split())
def _confirmation_context(v):return json.dumps(v or {},ensure_ascii=False,separators=(',',':'),sort_keys=True)
def password_strong(v):
 v=str(v or '');return len(v)>=12 and any(x.isalpha() for x in v) and any(x.isdigit() for x in v)
def verify_password(password,row):return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(row['salt']),row['iterations']).hex(),row['password_hash'])
def _security(c,u,org,typ,ip,ua,detail=None):c.execute('INSERT INTO security_events(user_id,organization_id,event_type,ip,user_agent,detail_json,created_at) VALUES(?,?,?,?,?,?,?)',(u,org,typ,ip,ua,dumps(detail or {}),now_ms()))
def login(db,organization_id,login_name,password,ip='',ua=''):
 with db.tx() as c:
  t=now_ms();u=c.execute("SELECT * FROM users WHERE organization_id=? AND login_name=? COLLATE NOCASE AND status='active'",(organization_id,login_name)).fetchone();cr=c.execute('SELECT * FROM user_credentials WHERE user_id=?',(u['user_id'],)).fetchone() if u else None
  if cr and cr['locked_until'] and cr['locked_until']>t:_security(c,u['user_id'],organization_id,'login_blocked',ip,ua);return {'ok':False,'code':'ACCOUNT_LOCKED','message':'登录失败次数过多，请 15 分钟后重试','lockedUntil':cr['locked_until']},423
  if not u or not cr or not verify_password(password,cr):
   if cr:
    failures=int(cr['failed_attempts'] or 0)+1;locked=t+LOCK_MS if failures>=MAX_FAILURES else None;c.execute('UPDATE user_credentials SET failed_attempts=?,locked_until=?,last_failed_at=? WHERE user_id=?',(failures,locked,t,u['user_id']));_security(c,u['user_id'],organization_id,'login_failed',ip,ua,{'failures':failures,'locked':bool(locked)})
    if locked:return {'ok':False,'code':'ACCOUNT_LOCKED','message':'登录失败次数过多，请 15 分钟后重试','lockedUntil':locked},423
   return {'ok':False,'code':'INVALID_CREDENTIALS','message':'用户名或密码错误'},401
  c.execute('UPDATE user_credentials SET failed_attempts=0,locked_until=NULL,last_failed_at=NULL WHERE user_id=?',(u['user_id'],));token=secrets.token_urlsafe(40);sid='ses_'+secrets.token_hex(16);c.execute('INSERT INTO sessions(session_id,user_id,access_token_hash,expires_at,ip,user_agent,created_at,last_seen_at,revoked_at) VALUES(?,?,?,?,?,?,?,?,NULL)',(sid,u['user_id'],hashlib.sha256(token.encode()).hexdigest(),t+SESSION_MS,ip,ua,t,t));_security(c,u['user_id'],organization_id,'login_success',ip,ua)
  return {'ok':True,'accessToken':token,'tokenType':'Bearer','expiresAt':t+SESSION_MS,'mustChangePassword':bool(cr['must_change']),'user':dict(u)},200
def actor_from_token(db,token):
 if not token:return None
 h=hashlib.sha256(token.encode()).hexdigest();t=now_ms()
 # Token validation is read traffic; do not reserve SQLite's single writer.
 with db.read() as c:
  r=c.execute("SELECT s.*,u.organization_id,u.login_name,u.display_name,cr.must_change FROM sessions s JOIN users u ON u.user_id=s.user_id JOIN user_credentials cr ON cr.user_id=u.user_id WHERE s.access_token_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.status='active'",(h,t)).fetchone()
  if not r:return None
  actor=dict(r)
 # Presence telemetry is throttled and best-effort, never authorization-critical.
 if t-int(actor.get('last_seen_at') or 0)>=120000:
  try:
   with db.write() as c:c.execute('UPDATE sessions SET last_seen_at=? WHERE session_id=? AND last_seen_at<?',(t,actor['session_id'],t-120000))
  except sqlite3.OperationalError as exc:
   if 'locked' not in str(exc).lower() and 'busy' not in str(exc).lower():raise
 return actor
def _scope_context(c, actor, workspace_id=None, team_id=None, department_id=None, resource_user_id=None, organization_id=None):
 """Resolve and validate an authorization target. Any cross-tenant or inconsistent context is invalid."""
 org=organization_id or actor.get('organization_id')
 if not org or org!=actor.get('organization_id'):return None
 ctx={'organization_id':org,'workspace_id':workspace_id,'team_id':team_id,'department_id':department_id,'resource_user_id':resource_user_id}
 if workspace_id:
  r=c.execute("SELECT organization_id FROM workspaces WHERE workspace_id=? AND status='active'",(workspace_id,)).fetchone()
  if not r or r[0]!=org:return None
 if team_id:
  r=c.execute("SELECT organization_id,workspace_id FROM teams WHERE team_id=? AND status='active'",(team_id,)).fetchone()
  if not r or r[0]!=org or (workspace_id and r[1]!=workspace_id):return None
  ctx['workspace_id']=ctx['workspace_id'] or r[1]
 if not ctx['workspace_id']:
  ctx['workspace_id']=default_workspace_id(c,org)
 if department_id:
  r=c.execute("SELECT organization_id FROM departments WHERE department_id=? AND status='active'",(department_id,)).fetchone()
  if not r or r[0]!=org:return None
 if resource_user_id:
  r=c.execute("SELECT organization_id FROM users WHERE user_id=? AND status='active'",(resource_user_id,)).fetchone()
  if not r or r[0]!=org:return None
 return ctx

def _binding_applies(row, ctx, platform_admin):
 typ,sid=row['scope_type'],row['scope_id']
 if typ=='platform':return platform_admin and sid=='*'
 if row['organization_id']!=ctx['organization_id']:return False
 if typ=='organization':return sid==ctx['organization_id']
 if typ=='workspace':return bool(ctx['workspace_id']) and sid==ctx['workspace_id']
 if typ=='department':return bool(ctx['department_id']) and sid==ctx['department_id']
 if typ=='team':return bool(ctx['team_id']) and sid==ctx['team_id']
 if typ=='self':return bool(ctx['resource_user_id']) and sid==ctx['resource_user_id']
 return False

def _binding_time_clause(alias='b'):
 return f"{alias}.status='active' AND ({alias}.valid_from IS NULL OR {alias}.valid_from<=?) AND ({alias}.expires_at IS NULL OR {alias}.expires_at>?)"

def effective_scope_bindings_in_tx(c,actor,permission,organization_id=None):
 """Return effective RBAC scopes without opening a nested transaction."""
 if not actor or not permission:return []
 uid=actor.get('user_id');org=organization_id or actor.get('organization_id');n=now_ms()
 if not uid or not org:return []
 if c.execute("SELECT 1 FROM platform_administrators WHERE user_id=?",(uid,)).fetchone():return [{'scope_type':'platform','scope_id':'*','role_id':'role_superadmin','role_name':'平台超级管理员'}]
 if org!=actor.get('organization_id'):return []
 sql="""SELECT DISTINCT b.scope_type,b.scope_id,b.role_id,r.name role_name
 FROM role_bindings b
 JOIN roles r ON r.role_id=b.role_id AND r.status='active'
 JOIN role_permissions rp ON rp.role_id=b.role_id
 JOIN permissions p ON p.permission_key=rp.permission_key
 WHERE b.user_id=? AND b.organization_id=? AND rp.permission_key=?
 AND b.status='active' AND (b.valid_from IS NULL OR b.valid_from<=?)
 AND (b.expires_at IS NULL OR b.expires_at>?)
 ORDER BY b.scope_type,b.scope_id,b.role_id"""
 params=(uid,org,permission,n,n)
 if sql.count('?')!=len(params):raise RuntimeError('RBAC_SCOPE_QUERY_BINDING_MISMATCH')
 return [dict(x) for x in c.execute(sql,params).fetchall()]

def has_permission_in_any_scope(db,actor,permission,organization_id=None):
 """Feature-entry gate: true when a permission has at least one effective binding.
 This does not authorize a row; callers must still apply a target/row scope check.
 """
 if not actor or not permission:return False
 org=organization_id or actor.get('organization_id')
 if not org or org!=actor.get('organization_id'):return False
 with db.tx(False) as c:return bool(effective_scope_bindings_in_tx(c,actor,permission,org))

def has_permission_in_any_scope_in_tx(c,actor,permission,organization_id=None):
 org=organization_id or (actor or {}).get('organization_id')
 return bool(org and actor and org==actor.get('organization_id') and effective_scope_bindings_in_tx(c,actor,permission,org))

def data_scope_clause_in_tx(c,actor,permission,organization_id,alias='c',owner_column='owner_user_id',team_column='team_id',workspace_column='workspace_id',department_column=None):
 """Build a fail-closed row predicate. Request filters may only further narrow this predicate."""
 grants=effective_scope_bindings_in_tx(c,actor,permission,organization_id)
 if any(x['scope_type']=='platform' for x in grants):return '1=1',[],{'level':'platform','grants':grants}
 clauses=[];args=[];uid=actor.get('user_id') if actor else None
 for g in grants:
  typ,sid=g['scope_type'],g['scope_id']
  if typ=='organization' and sid==organization_id:clauses.append('1=1')
  elif typ=='workspace' and workspace_column:clauses.append(f'{alias}.{workspace_column}=?');args.append(sid)
  elif typ=='department':
   if department_column:clauses.append(f'{alias}.{department_column}=?');args.append(sid)
   elif team_column:clauses.append(f'{alias}.{team_column} IN (SELECT team_id FROM teams WHERE organization_id=? AND department_id=?)');args.extend([organization_id,sid])
  elif typ=='team' and team_column:clauses.append(f'{alias}.{team_column}=?');args.append(sid)
  elif typ=='self' and owner_column and sid==uid:clauses.append(f'{alias}.{owner_column}=?');args.append(uid)
 if not clauses:return '0=1',[],{'level':'none','grants':[]}
 level='organization' if '1=1' in clauses else ('team' if any(x['scope_type']=='team' for x in grants) else 'restricted')
 return '('+' OR '.join(clauses)+')',args,{'level':level,'grants':grants}

def permissions(db,user_id,team_id=None,workspace_id=None,department_id=None,resource_user_id=None,organization_id=None):
 """Return permissions effective for one validated target context. Platform administrators own every registered permission."""
 with db.tx(False) as c:
  u=c.execute("SELECT user_id,organization_id FROM users WHERE user_id=? AND status='active'",(user_id,)).fetchone()
  if not u:return set()
  platform_admin=bool(c.execute("SELECT 1 FROM platform_administrators WHERE user_id=?",(user_id,)).fetchone())
  if platform_admin:return {r[0] for r in c.execute('SELECT permission_key FROM permissions')}
  actor={'user_id':u['user_id'],'organization_id':u['organization_id']}
  ctx=_scope_context(c,actor,workspace_id,team_id,department_id,resource_user_id,organization_id)
  if ctx is None:return set()
  n=now_ms()
  rows=c.execute("SELECT b.organization_id,b.scope_type,b.scope_id,rp.permission_key FROM role_bindings b JOIN roles r ON r.role_id=b.role_id AND r.status='active' JOIN role_permissions rp ON rp.role_id=b.role_id JOIN permissions p ON p.permission_key=rp.permission_key WHERE b.user_id=? AND "+_binding_time_clause('b'),(user_id,n,n)).fetchall()
  return {r['permission_key'] for r in rows if _binding_applies(r,ctx,False)}

def authorization_profile(db,user_id):
 """Return capability union plus each scoped source for navigation and administrator explanation."""
 with db.tx(False) as c:
  u=c.execute("SELECT user_id,organization_id FROM users WHERE user_id=? AND status='active'",(user_id,)).fetchone()
  if not u:return {'permissions':set(),'roles':[],'effective_scopes':{}}
  if c.execute('SELECT 1 FROM platform_administrators WHERE user_id=?',(user_id,)).fetchone():
   keys={r[0] for r in c.execute('SELECT permission_key FROM permissions')}
   return {'permissions':keys,'roles':[{'role_id':'role_superadmin','role_code':'platform_admin','role_name':'平台超级管理员','scope_type':'platform','scope_id':'*'}],'effective_scopes':{k:[{'scope_type':'platform','scope_id':'*','role_id':'role_superadmin'}] for k in keys}}
  n=now_ms(); rows=c.execute("""SELECT b.binding_id,b.role_id,r.role_code,r.name role_name,b.scope_type,b.scope_id,b.valid_from,b.expires_at,rp.permission_key
   FROM role_bindings b JOIN roles r ON r.role_id=b.role_id AND r.status='active' JOIN role_permissions rp ON rp.role_id=b.role_id
   WHERE b.user_id=? AND b.organization_id=? AND """+_binding_time_clause('b')+" ORDER BY r.name,b.scope_type,b.scope_id,rp.permission_key",(user_id,u['organization_id'],n,n)).fetchall()
  roles=[];seen=set();scopes={}
  for x in rows:
   key=(x['binding_id'],x['role_id'],x['scope_type'],x['scope_id'])
   if key not in seen:
    seen.add(key);roles.append({k:x[k] for k in ('binding_id','role_id','role_code','role_name','scope_type','scope_id','valid_from','expires_at')})
   scopes.setdefault(x['permission_key'],[]).append({'scope_type':x['scope_type'],'scope_id':x['scope_id'],'role_id':x['role_id'],'role_name':x['role_name']})
  return {'permissions':set(scopes),'roles':roles,'effective_scopes':scopes}


# Permission scope-mask contract. Bit order is stable and shared by API/UI metadata.
SCOPE_MASK_BITS={'self':1,'team':2,'department':4,'workspace':8,'organization':16,'platform':32}
def scope_mask_names(mask):
 try: value=int(mask)
 except Exception: value=0
 return [name for name in ('self','team','department','workspace','organization','platform') if value & SCOPE_MASK_BITS[name]]
def validate_role_permissions_in_tx(c,scope_level,permission_keys):
 """Fail closed when a role contains an unknown permission or a permission forbidden at its declared scope."""
 if scope_level not in SCOPE_MASK_BITS:raise ValueError('RBAC_ROLE_SCOPE_INVALID')
 keys=sorted(set(str(x) for x in (permission_keys or []) if str(x)))
 if not keys:return keys
 marks=','.join('?' for _ in keys)
 found={r['permission_key']:int(r['scope_mask'] or 0) for r in c.execute('SELECT permission_key,scope_mask FROM permissions WHERE permission_key IN ('+marks+')',keys)}
 missing=[x for x in keys if x not in found]
 if missing:raise ValueError('RBAC_PERMISSION_UNKNOWN:'+','.join(missing))
 bit=SCOPE_MASK_BITS[scope_level];invalid=[x for x in keys if not(found[x]&bit)]
 if invalid:raise ValueError('RBAC_PERMISSION_SCOPE_FORBIDDEN:'+','.join(invalid))
 return keys

PAGE_CAPABILITY_CATALOG={
 'roles':{'name':'角色与授权','portal':'admin','read':['role.read'],'write':['role.manage']},
 'sources':{'name':'客户来源','portal':'business','read':['source.read'],'write':['source.manage']},
 'contacts':{'name':'客户档案','portal':'business','read':['contact.read'],'write':['contact.update']},
 'users':{'name':'用户管理','portal':'admin','read':['user.read'],'write':['user.manage']},
 'teams':{'name':'团队管理','portal':'admin','read':['team.read'],'write':['team.manage']},
 'audit':{'name':'审计日志','portal':'admin','read':['audit.read'],'write':[]},
 'platforms':{'name':'平台管理','portal':'admin','read':['platform.read'],'write':['platform.manage']},
}
def page_capabilities_from_profile(profile,platform_admin=False):
 permissions=set(profile.get('permissions') or ());scopes=profile.get('effective_scopes') or {};out={}
 for code,item in PAGE_CAPABILITY_CATALOG.items():
  read=[k for k in item['read'] if platform_admin or (k in permissions and scopes.get(k))]
  write=[k for k in item['write'] if platform_admin or (k in permissions and scopes.get(k))]
  visible=bool(platform_admin or read or write);mode='read-write' if write else ('read-only' if read else 'hidden')
  effective=[]
  for key in read+write:
   for grant in scopes.get(key,[]):
    token=str(grant.get('scope_type') or '')+(':'+str(grant.get('scope_id')) if grant.get('scope_id') not in (None,'','*') else '')
    if token and token not in effective:effective.append(token)
  out[code]={'name':item['name'],'portal':item['portal'],'visible':visible,'mode':mode,'scopes':effective,'reason':('平台管理员' if platform_admin else (' / '.join(read+write) if visible else '缺少有效权限范围'))}
 return out

def can(db,actor,permission,workspace_id=None,team_id=None,department_id=None,resource_user_id=None,organization_id=None):
 if not actor or not permission:return False
 return permission in permissions(db,actor.get('user_id'),team_id,workspace_id,department_id,resource_user_id,organization_id)

def issue_confirmation(db,actor,action_key,context=None,ttl_ms=300000):
 """Issue a short-lived one-time confirmation; only its digest is stored."""
 if not actor or not action_key:raise ValueError('RBAC_CONFIRMATION_INVALID')
 ttl=int(ttl_ms)
 if ttl<1000 or ttl>900000:raise ValueError('RBAC_CONFIRMATION_TTL_INVALID')
 token=secrets.token_urlsafe(32);digest=hashlib.sha256(token.encode()).hexdigest();t=now_ms();cid='rbc_'+secrets.token_hex(16)
 with db.tx() as c:
  u=c.execute("SELECT organization_id FROM users WHERE user_id=? AND status='active'",(actor.get('user_id'),)).fetchone()
  if not u or u[0]!=actor.get('organization_id'):raise ValueError('RBAC_SUBJECT_INVALID')
  c.execute('INSERT INTO rbac_confirmations(confirmation_id,user_id,action_key,token_digest,context_json,expires_at,consumed_at,created_at) VALUES(?,?,?,?,?,?,NULL,?)',(cid,actor['user_id'],action_key,digest,_confirmation_context(context),t+ttl,t))
  _security(c,actor['user_id'],actor['organization_id'],'rbac_confirmation_issued','','',{'action_key':action_key,'confirmation_id':cid})
 return {'confirmationToken':token,'expiresAt':t+ttl,'actionKey':action_key}

def consume_confirmation(db,actor,action_key,token,context=None):
 """Atomically validate and consume a confirmation token. Returns False on every mismatch."""
 if not actor or not action_key or not token:return False
 digest=hashlib.sha256(str(token).encode()).hexdigest();t=now_ms();expected=_confirmation_context(context)
 with db.tx() as c:
  row=c.execute("SELECT confirmation_id,context_json FROM rbac_confirmations WHERE token_digest=? AND user_id=? AND action_key=? AND consumed_at IS NULL AND expires_at>?",(digest,actor.get('user_id'),action_key,t)).fetchone()
  if not row or not hmac.compare_digest(row['context_json'],expected):return False
  changed=c.execute("UPDATE rbac_confirmations SET consumed_at=? WHERE confirmation_id=? AND consumed_at IS NULL AND expires_at>?",(t,row['confirmation_id'],t)).rowcount
  if changed!=1:return False
  _security(c,actor['user_id'],actor.get('organization_id'),'rbac_confirmation_consumed','','',{'action_key':action_key,'confirmation_id':row['confirmation_id']})
  return True


def revoke_sessions_in_tx(c,user_id,actor_id,reason='authorization_changed',exclude_session_id=None):
 t=now_ms();sql="UPDATE sessions SET revoked_at=?,revoked_reason=?,revoked_by=? WHERE user_id=? AND revoked_at IS NULL";args=[t,str(reason or 'authorization_changed'),actor_id,user_id]
 if exclude_session_id:sql+=' AND session_id<>?';args.append(exclude_session_id)
 return c.execute(sql,tuple(args)).rowcount

def revoke_session_in_tx(c,session_id,actor_id,reason='session_revoked',user_id=None):
 t=now_ms();sql="UPDATE sessions SET revoked_at=?,revoked_reason=?,revoked_by=? WHERE session_id=? AND revoked_at IS NULL";args=[t,str(reason or 'session_revoked'),actor_id,session_id]
 if user_id is not None:sql+=' AND user_id=?';args.append(user_id)
 return c.execute(sql,tuple(args)).rowcount

def revoke_token_session_in_tx(c,token,user_id,actor_id=None,reason='logout'):
 digest=hashlib.sha256(str(token or '').encode()).hexdigest()
 return c.execute("UPDATE sessions SET revoked_at=?,revoked_reason=?,revoked_by=? WHERE access_token_hash=? AND user_id=? AND revoked_at IS NULL",(now_ms(),str(reason or 'logout'),actor_id or user_id,digest,user_id)).rowcount

def grant_binding_in_tx(c,user_id,role_id,organization_id,scope_type,scope_id,granted_by,valid_from=None,expires_at=None,grant_reason='',grant_type='standard',approved_by=None):
 if scope_type not in ('organization','workspace','department','team','self'):raise ValueError('RBAC_SCOPE_INVALID')
 u=c.execute("SELECT organization_id FROM users WHERE user_id=? AND status='active'",(user_id,)).fetchone();r=c.execute("SELECT organization_id,scope_level FROM roles WHERE role_id=? AND status='active'",(role_id,)).fetchone()
 if not u or u[0]!=organization_id or not r or (r[0] is not None and r[0]!=organization_id):raise ValueError('RBAC_SUBJECT_OR_ROLE_INVALID')
 allowed={'organization':{'organization','workspace','department','team','self'},'workspace':{'workspace','team','self'},'department':{'department','team','self'},'team':{'team','self'},'self':{'self'}}
 if scope_type not in allowed.get(r['scope_level'],set()):raise ValueError('RBAC_ROLE_SCOPE_ESCALATION')
 if scope_type=='organization' and scope_id!=organization_id:raise ValueError('RBAC_SCOPE_INVALID')
 specs={'workspace':('workspaces','workspace_id'),'department':('departments','department_id'),'team':('teams','team_id')}
 if scope_type in specs:
  table,key=specs[scope_type];x=c.execute(f"SELECT organization_id FROM {table} WHERE {key}=? AND status='active'",(scope_id,)).fetchone()
  if not x or x[0]!=organization_id:raise ValueError('RBAC_SCOPE_INVALID')
 if scope_type=='self' and scope_id!=user_id:raise ValueError('RBAC_SCOPE_INVALID')
 t=now_ms();start=int(valid_from) if valid_from not in (None,'') else t;end=int(expires_at) if expires_at not in (None,'') else None
 if end is not None and (end <= start or end <= now_ms()):raise ValueError('RBAC_EXPIRY_INVALID')
 if grant_type not in ('standard','temporary','acting','emergency'):raise ValueError('RBAC_GRANT_TYPE_INVALID')
 if grant_type!='standard' and end is None:raise ValueError('RBAC_EXPIRY_REQUIRED')
 bid='rbd_'+secrets.token_hex(16)
 c.execute("INSERT INTO role_bindings(binding_id,user_id,role_id,organization_id,scope_type,scope_id,status,granted_by,created_at,updated_at,valid_from,expires_at,grant_reason,grant_type,approved_by) VALUES(?,?,?,?,?,?,'active',?,?,?,?,?,?,?,?) ON CONFLICT(user_id,role_id,scope_type,scope_id) DO UPDATE SET organization_id=excluded.organization_id,status='active',granted_by=excluded.granted_by,updated_at=excluded.updated_at,valid_from=excluded.valid_from,expires_at=excluded.expires_at,grant_reason=excluded.grant_reason,grant_type=excluded.grant_type,approved_by=excluded.approved_by",(bid,user_id,role_id,organization_id,scope_type,scope_id,granted_by,t,t,start,end,str(grant_reason or '')[:500],grant_type,approved_by))
 actual=c.execute("SELECT binding_id FROM role_bindings WHERE user_id=? AND role_id=? AND scope_type=? AND scope_id=?",(user_id,role_id,scope_type,scope_id)).fetchone()
 revoke_sessions_in_tx(c,user_id,granted_by,'authorization_changed')
 return actual[0]

def is_platform_admin(db,actor):
 if not actor:return False
 with db.tx(False) as c:
  return bool(c.execute("SELECT 1 FROM platform_administrators WHERE user_id=?",(actor['user_id'],)).fetchone())
