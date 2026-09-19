# -*- coding: utf-8 -*-
"""V207 身份、会话、登录锁定与 RBAC。"""
import hashlib,hmac,secrets
from V207_shared_db import now_ms,dumps
SESSION_MS=8*60*60*1000; LOCK_MS=15*60*1000; MAX_FAILURES=5
def canonical(v):return ''.join(str(v or '').strip().lower().split())
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
def permissions(db,user_id,team_id=None):
 with db.tx(False) as c:
  rows=list(c.execute("SELECT DISTINCT rp.permission_key FROM role_permissions rp JOIN organization_memberships m ON m.role_id=rp.role_id WHERE m.user_id=? AND m.status='active'",(user_id,)))
  if team_id:rows+=list(c.execute("SELECT DISTINCT rp.permission_key FROM role_permissions rp JOIN team_memberships m ON m.role_id=rp.role_id WHERE m.user_id=? AND m.team_id=? AND m.status='active'",(user_id,team_id)))
  return {x[0] for x in rows}
def can(db,actor,permission,workspace_id=None,team_id=None):
 if not actor:return False
 with db.tx(False) as c:
  if workspace_id:
   w=c.execute('SELECT organization_id FROM workspaces WHERE workspace_id=?',(workspace_id,)).fetchone()
   if not w or w[0]!=actor['organization_id']:return False
  if team_id and not c.execute("SELECT 1 FROM team_memberships WHERE user_id=? AND team_id=? AND status='active' UNION SELECT 1 FROM organization_memberships WHERE user_id=? AND organization_id=? AND role_id IN ('role_superadmin','role_orgadmin') AND status='active'",(actor['user_id'],team_id,actor['user_id'],actor['organization_id'])).fetchone():return False
 return permission in permissions(db,actor['user_id'],team_id)
