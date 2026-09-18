# -*- coding: utf-8 -*-
"""V207 身份、会话与 RBAC。"""
import hashlib,hmac,secrets
from V207_shared_db import now_ms
SESSION_MS=8*60*60*1000
def canonical(v):return ''.join(str(v or '').strip().lower().split())
def verify_password(password,row):return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(row['salt']),row['iterations']).hex(),row['password_hash'])
def login(db,organization_id,login_name,password,ip='',ua=''):
 with db.tx() as c:
  u=c.execute("SELECT * FROM users WHERE organization_id=? AND login_name=? COLLATE NOCASE AND status='active'",(organization_id,login_name)).fetchone()
  cr=c.execute('SELECT * FROM user_credentials WHERE user_id=?',(u['user_id'],)).fetchone() if u else None
  if not u or not cr or not verify_password(password,cr):return {'ok':False,'code':'INVALID_CREDENTIALS','message':'用户名或密码错误'},401
  token=secrets.token_urlsafe(40);sid='ses_'+secrets.token_hex(16);t=now_ms();c.execute('INSERT INTO sessions(session_id,user_id,access_token_hash,expires_at,ip,user_agent,created_at,last_seen_at,revoked_at) VALUES(?,?,?,?,?,?,?,?,NULL)',(sid,u['user_id'],hashlib.sha256(token.encode()).hexdigest(),t+SESSION_MS,ip,ua,t,t))
  return {'ok':True,'accessToken':token,'tokenType':'Bearer','expiresAt':t+SESSION_MS,'mustChangePassword':bool(cr['must_change']),'user':dict(u)},200
def actor_from_token(db,token):
 if not token:return None
 h=hashlib.sha256(token.encode()).hexdigest();t=now_ms()
 with db.tx() as c:
  r=c.execute("SELECT s.*,u.organization_id,u.login_name,u.display_name FROM sessions s JOIN users u ON u.user_id=s.user_id WHERE s.access_token_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.status='active'",(h,t)).fetchone()
  if not r:return None
  c.execute('UPDATE sessions SET last_seen_at=? WHERE session_id=?',(t,r['session_id']));return dict(r)
def permissions(db,user_id,team_id=None):
 with db.tx(False) as c:
  q="SELECT DISTINCT rp.permission_key FROM role_permissions rp JOIN organization_memberships m ON m.role_id=rp.role_id WHERE m.user_id=? AND m.status='active'";args=[user_id]
  rows=list(c.execute(q,args))
  if team_id:rows+=list(c.execute("SELECT DISTINCT rp.permission_key FROM role_permissions rp JOIN team_memberships m ON m.role_id=rp.role_id WHERE m.user_id=? AND m.team_id=? AND m.status='active'",(user_id,team_id)))
  return {x[0] for x in rows}
def can(db,actor,permission,workspace_id=None,team_id=None):
 if not actor:return False
 with db.tx(False) as c:
  if workspace_id:
   w=c.execute('SELECT organization_id FROM workspaces WHERE workspace_id=?',(workspace_id,)).fetchone()
   if not w or w[0]!=actor['organization_id']:return False
  if team_id and not c.execute("SELECT 1 FROM team_memberships WHERE user_id=? AND team_id=? AND status='active' UNION SELECT 1 FROM organization_memberships WHERE user_id=? AND organization_id=? AND role_id='role_superadmin' AND status='active'",(actor['user_id'],team_id,actor['user_id'],actor['organization_id'])).fetchone():return False
 return permission in permissions(db,actor['user_id'],team_id)
# V207.0.0：actor 仅从 Bearer 会话产生，请求体 actor_id 永不可信。
