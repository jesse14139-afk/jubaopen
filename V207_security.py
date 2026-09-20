# -*- coding: utf-8 -*-
"""V207 身份、会话、登录锁定与 RBAC。"""
import hashlib,hmac,secrets,json
from V207_shared_db import now_ms,dumps
SESSION_MS=8*60*60*1000; LOCK_MS=15*60*1000; MAX_FAILURES=5
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
 with db.tx() as c:
  r=c.execute("SELECT s.*,u.organization_id,u.login_name,u.display_name,cr.must_change FROM sessions s JOIN users u ON u.user_id=s.user_id JOIN user_credentials cr ON cr.user_id=u.user_id WHERE s.access_token_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.status='active'",(h,t)).fetchone()
  if not r:return None
  c.execute('UPDATE sessions SET last_seen_at=? WHERE session_id=?',(t,r['session_id']));return dict(r)
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

def permissions(db,user_id,team_id=None,workspace_id=None,department_id=None,resource_user_id=None,organization_id=None):
 """Return effective permissions from Schema 210 role_bindings only."""
 with db.tx(False) as c:
  u=c.execute("SELECT user_id,organization_id FROM users WHERE user_id=? AND status='active'",(user_id,)).fetchone()
  if not u:return set()
  actor={'user_id':u['user_id'],'organization_id':u['organization_id']}
  ctx=_scope_context(c,actor,workspace_id,team_id,department_id,resource_user_id,organization_id)
  if ctx is None:return set()
  platform_admin=bool(c.execute("SELECT 1 FROM platform_administrators WHERE user_id=?",(user_id,)).fetchone())
  rows=c.execute("SELECT b.organization_id,b.scope_type,b.scope_id,rp.permission_key FROM role_bindings b JOIN roles r ON r.role_id=b.role_id AND r.status='active' JOIN role_permissions rp ON rp.role_id=b.role_id JOIN permissions p ON p.permission_key=rp.permission_key WHERE b.user_id=? AND b.status='active'",(user_id,)).fetchall()
  return {r['permission_key'] for r in rows if _binding_applies(r,ctx,platform_admin)}

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

def grant_binding_in_tx(c,user_id,role_id,organization_id,scope_type,scope_id,granted_by):
 if scope_type not in ('organization','workspace','department','team','self'):raise ValueError('RBAC_SCOPE_INVALID')
 u=c.execute("SELECT organization_id FROM users WHERE user_id=? AND status='active'",(user_id,)).fetchone();r=c.execute("SELECT organization_id FROM roles WHERE role_id=? AND status='active'",(role_id,)).fetchone()
 if not u or u[0]!=organization_id or not r or (r[0] is not None and r[0]!=organization_id):raise ValueError('RBAC_SUBJECT_OR_ROLE_INVALID')
 if scope_type=='organization' and scope_id!=organization_id:raise ValueError('RBAC_SCOPE_INVALID')
 specs={'workspace':('workspaces','workspace_id'),'department':('departments','department_id'),'team':('teams','team_id')}
 if scope_type in specs:
  table,key=specs[scope_type];x=c.execute(f"SELECT organization_id FROM {table} WHERE {key}=? AND status='active'",(scope_id,)).fetchone()
  if not x or x[0]!=organization_id:raise ValueError('RBAC_SCOPE_INVALID')
 if scope_type=='self' and scope_id!=user_id:raise ValueError('RBAC_SCOPE_INVALID')
 t=now_ms();bid='rbd_'+secrets.token_hex(16)
 c.execute("INSERT INTO role_bindings(binding_id,user_id,role_id,organization_id,scope_type,scope_id,status,granted_by,created_at,updated_at) VALUES(?,?,?,?,?,?,'active',?,?,?) ON CONFLICT(user_id,role_id,scope_type,scope_id) DO UPDATE SET organization_id=excluded.organization_id,status='active',granted_by=excluded.granted_by,updated_at=excluded.updated_at",(bid,user_id,role_id,organization_id,scope_type,scope_id,granted_by,t,t))
 actual=c.execute("SELECT binding_id FROM role_bindings WHERE user_id=? AND role_id=? AND scope_type=? AND scope_id=?",(user_id,role_id,scope_type,scope_id)).fetchone()
 revoke_sessions_in_tx(c,user_id,granted_by,'authorization_changed')
 return actual[0]

def is_platform_admin(db,actor):
 if not actor:return False
 with db.tx(False) as c:
  return bool(c.execute("SELECT 1 FROM platform_administrators WHERE user_id=?",(actor['user_id'],)).fetchone())
