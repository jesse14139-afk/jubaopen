# -*- coding: utf-8 -*-
"""V207 企业综合管理 API。Schema 210；所有范围与写入均由服务端校验。"""
import json, uuid, os, sqlite3, secrets
from V207_shared_db import now_ms,dumps,loads,hash_password
from V207_security import can,permissions,verify_password,password_strong,is_platform_admin,grant_binding_in_tx,revoke_sessions_in_tx,revoke_session_in_tx,issue_confirmation,consume_confirmation
from V207_schema_catalog import build_schema_catalog
from V207_version import PRODUCT_VERSION,SCHEMA_VERSION
from V207_scope import resolve_scope, require_platform, require_account_grant
from V207_platform_service import handle as handle_platform
from V207_channel_service import handle as handle_channel
from V207_source_service import handle as handle_source
from V207_campaign_service import handle as handle_campaign
from V207_contact_identity_service import handle as handle_contact_identity
from V207_touchpoint_service import handle as handle_touchpoint
from V207_attribution_service import handle as handle_attribution
from V207_source_link_service import handle as handle_source_link
from V207_organization_service import handle as handle_organization_model
CHANNELS=('whatsapp','instagram','facebook','messenger','telegram')

def rows(c,sql,args=()): return [dict(x) for x in c.execute(sql,args)]
def one(c,sql,args=()):
 r=c.execute(sql,args).fetchone(); return dict(r) if r else None
def platform(db,a):
 # 平台级权限不得由企业角色隐式提升；仅内置系统管理员具备跨企业能力。
 return is_platform_admin(db,a)
def org_ok(db,a,org):return bool(org) and (platform(db,a) or org==a['organization_id'])
def manage(db,a,perm,org):return org_ok(db,a,org) and (platform(db,a) or can(db,a,perm))
def target(q,a,b=None):return str((b or {}).get('organizationId') or (b or {}).get('organization_id') or q.get('organization_id') or a['organization_id'])
def page(q):
 try:p=max(1,int(q.get('page',1)));size=min(200,max(1,int(q.get('pageSize',q.get('limit',50)))))
 except:p,size=1,50
 return p,size,(p-1)*size
def pack(items,total,p,size,**extra):return {'ok':True,'items':items,'pagination':{'page':p,'pageSize':size,'total':total,'pages':(total+size-1)//size},**extra}
def bad(h,code,msg,status=400):return h.sendj({'ok':False,'code':code,'message':msg},status) or True
def _audit_workspace(c,a,wid=None):
 if wid:
  row=c.execute("SELECT workspace_id FROM workspaces WHERE workspace_id=?",(wid,)).fetchone()
  if row:return row[0]
 rows=c.execute("SELECT DISTINCT t.workspace_id FROM role_bindings b JOIN teams t ON b.scope_type='team' AND b.scope_id=t.team_id JOIN workspaces w ON w.workspace_id=t.workspace_id AND w.organization_id=t.organization_id WHERE b.user_id=? AND b.organization_id=? AND b.status='active' AND t.status='active'",(a['user_id'],a['organization_id'])).fetchall()
 if len(rows)!=1:raise RuntimeError('AUDIT_SCOPE_REQUIRED')
 return rows[0][0]
def audit(db,a,op,typ,eid,before,after,reason=None,wid=None):
 with db.tx() as c:audit_in_tx(c,a,op,typ,eid,before,after,reason,wid)
def audit_in_tx(c,a,op,typ,eid,before,after,reason=None,wid=None):
 wid=_audit_workspace(c,a,wid)
 c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at,organization_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(wid,a['user_id'],None,op,typ,eid,dumps(before or {}),dumps(after or {}),reason,now_ms(),a['organization_id']))
def find_org_for(db,kind,eid):
 specs={'team':('teams','team_id'),'user':('users','user_id'),'workspace':('workspaces','workspace_id'),'account':('channel_accounts','channel_account_id'),'source':('sources','source_id'),'device':('devices','device_id')}
 if kind not in specs:return None
 t,k=specs[kind]
 with db.tx(False) as c:
  r=c.execute(f'SELECT organization_id FROM {t} WHERE {k}=?',(eid,)).fetchone();return r[0] if r else None
def clean_status(v):return v if v in ('active','disabled') else None
def creates_cycle(c,org,workspace_id,from_source,to_source):
 if from_source==to_source:return True
 seen=set();stack=[to_source]
 while stack:
  cur=stack.pop()
  if cur==from_source:return True
  if cur in seen:continue
  seen.add(cur)
  stack.extend(r[0] for r in c.execute('SELECT to_source_id FROM source_links WHERE organization_id=? AND workspace_id=? AND from_source_id=?',(org,workspace_id,cur)))
 return False

def dispatch(h,m,p,q,a,db):
 if not p.startswith('/api/v207/admin/'):return False
 seg=[x for x in p[len('/api/v207/admin/'):].split('/') if x]
 if not seg:return bad(h,'NOT_FOUND','管理接口不存在',404)
 root=seg[0];ident=seg[1] if len(seg)>1 else None; action=seg[2] if len(seg)>2 else None
 # session/security
 if root=='profile' and m=='GET':
  with db.tx(False) as c:
   org=one(c,'SELECT * FROM organizations WHERE organization_id=?',(a['organization_id'],)); cr=one(c,'SELECT must_change,updated_at FROM user_credentials WHERE user_id=?',(a['user_id'],)); pa=one(c,'SELECT is_builtin,onboarding_completed FROM platform_administrators WHERE user_id=?',(a['user_id'],)); ws=one(c,"SELECT * FROM workspaces WHERE organization_id=? ORDER BY created_at LIMIT 1",(a['organization_id'],)); tm=one(c,"SELECT * FROM teams WHERE organization_id=? ORDER BY created_at LIMIT 1",(a['organization_id'],))
  return h.sendj({'ok':True,'user':{k:a[k] for k in ('user_id','login_name','display_name','organization_id')},'organization':org,'platformAdmin':platform(db,a),'permissions':sorted(permissions(db,a['user_id'])),'credential':cr,'platformIdentity':pa,'onboardingRequired':bool(pa and not pa['onboarding_completed']),'workspace':ws,'team':tm}) or True
 if root=='change-password' and m=='POST':
  b=h.body();old=str(b.get('oldPassword') or b.get('currentPassword') or b.get('current_password') or '');new=str(b.get('newPassword') or b.get('new_password') or '')
  if not password_strong(new):return bad(h,'WEAK_PASSWORD','新密码至少 12 位，且必须同时包含字母和数字')
  with db.tx() as c:
   cr=c.execute('SELECT * FROM user_credentials WHERE user_id=?',(a['user_id'],)).fetchone()
   if not cr or not verify_password(old,cr):return bad(h,'INVALID_PASSWORD','当前密码错误',400)
   ph,salt,it=hash_password(new);c.execute('UPDATE user_credentials SET password_hash=?,salt=?,iterations=?,must_change=0,updated_at=? WHERE user_id=?',(ph,salt,it,now_ms(),a['user_id']))
   revoke_sessions_in_tx(c,a['user_id'],a['user_id'],'password_changed',a['session_id'])
   audit_in_tx(c,a,'change_password','user',a['user_id'],{},{})
  return h.sendj({'ok':True}) or True
 if root=='onboarding' and m=='POST':
  if not platform(db,a):return bad(h,'FORBIDDEN','仅平台超级管理员可完成首次设置',403)
  b=h.body(); org_name=str(b.get('organizationName') or '').strip(); ws_name=str(b.get('workspaceName') or '').strip(); team_name=str(b.get('teamName') or '').strip(); display=str(b.get('displayName') or '').strip()
  if not all((org_name,ws_name,team_name,display)):return bad(h,'INVALID_INPUT','企业、业务空间、团队和管理员名称均不能为空')
  with db.tx() as c:
   pa=c.execute("SELECT onboarding_completed FROM platform_administrators WHERE user_id=?",(a['user_id'],)).fetchone()
   if not pa:return bad(h,'FORBIDDEN','平台管理员身份不存在',403)
   w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? ORDER BY created_at LIMIT 1",(a['organization_id'],)).fetchone()
   if not w:return bad(h,'WORKSPACE_REQUIRED','当前企业缺少有效业务空间',409)
   t=c.execute('SELECT team_id FROM teams WHERE organization_id=? ORDER BY created_at LIMIT 1',(a['organization_id'],)).fetchone(); n=now_ms()
   c.execute('UPDATE organizations SET name=?,updated_at=? WHERE organization_id=?',(org_name,n,a['organization_id'])); c.execute('UPDATE users SET display_name=?,updated_at=? WHERE user_id=?',(display,n,a['user_id']))
   c.execute('UPDATE workspaces SET name=?,updated_at=? WHERE workspace_id=?',(ws_name,n,w[0]))
   if t:c.execute('UPDATE teams SET name=?,updated_at=? WHERE team_id=?',(team_name,n,t[0]))
   c.execute('UPDATE platform_administrators SET onboarding_completed=1,updated_at=? WHERE user_id=?',(n,a['user_id']))
   audit_in_tx(c,a,'complete_onboarding','organization',a['organization_id'],{},b,wid=w[0])
  return h.sendj({'ok':True}) or True
 # organizations
 if root=='organizations':
  if m=='GET':
   if not platform(db,a):
    with db.tx(False) as c:its=rows(c,'SELECT * FROM organizations WHERE organization_id=?',(a['organization_id'],))
   else:
    with db.tx(False) as c:its=rows(c,'SELECT * FROM organizations ORDER BY created_at')
   return h.sendj({'ok':True,'items':its}) or True
  if m=='POST':
   if not platform(db,a):return bad(h,'FORBIDDEN','仅平台超级管理员可创建企业',403)
   b=h.body();name=str(b.get('name') or '').strip();oid=str(b.get('organizationId') or ('org_'+uuid.uuid4().hex))
   if not name:return bad(h,'NAME_REQUIRED','企业名称不能为空')
   n=now_ms();wid='ws_'+uuid.uuid4().hex;tid='team_'+uuid.uuid4().hex
   try:
    with db.tx() as c:
     c.execute('INSERT INTO organizations(organization_id,name,status,created_at,updated_at) VALUES(?,?,?,?,?)',(oid,name,'active',n,n));c.execute('INSERT INTO workspaces(workspace_id,name,status,created_at,updated_at,organization_id) VALUES(?,?,\'active\',?,?,?)',(wid,name+'工作区',n,n,oid));c.execute('INSERT INTO workspace_configs(workspace_id,revision,items_json,updated_at,updated_by) VALUES(?,0,\'[]\',?,?)',(wid,n,a['user_id']));c.execute('INSERT INTO teams(team_id,organization_id,workspace_id,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(tid,oid,wid,'默认团队','active',n,n));c.execute("INSERT INTO workspace_teams(workspace_id,team_id,organization_id,relation_type,is_primary,access_level,status,created_at,updated_at) VALUES(?,?,?,'primary',1,'manage','active',?,?)",(wid,tid,oid,n,n))
     audit_in_tx(c,a,'create','organization',oid,{},b,wid=wid)
   except Exception as e:return bad(h,'ORGANIZATION_CONFLICT','企业 ID 已存在或数据冲突',409)
   return h.sendj({'ok':True,'organizationId':oid,'workspaceId':wid,'teamId':tid},201) or True
  if ident and m=='PATCH':
   if not platform(db,a):return bad(h,'FORBIDDEN','仅平台超级管理员可修改企业',403)
   b=h.body();st=clean_status(b.get('status'))
   with db.tx() as c:
    old=one(c,'SELECT * FROM organizations WHERE organization_id=?',(ident,))
    if not old:return bad(h,'NOT_FOUND','企业不存在',404)
    c.execute('UPDATE organizations SET name=?,status=?,updated_at=? WHERE organization_id=?',(str(b.get('name') or old['name']).strip(),st or old['status'],now_ms(),ident));new=one(c,'SELECT * FROM organizations WHERE organization_id=?',(ident,))
    audit_in_tx(c,a,'update','organization',ident,old,new, b.get('reason'))
   return h.sendj({'ok':True,'item':new}) or True
 # common organization scope
 org=target(q,a)
 if not org_ok(db,a,org):return bad(h,'FORBIDDEN','无权访问目标企业',403)
 if root=='rbac' and ident=='confirmations' and m=='POST':
  if not (platform(db,a) or can(db,a,'user.manage',organization_id=org)):return bad(h,'FORBIDDEN','无权限管理权限',403)
  b=h.body(); action=str(b.get('actionKey') or '').strip(); context=b.get('context') or {}
  allowed=('role.create','role.update','role.delete','role.copy','binding.grant','binding.revoke')
  if action not in allowed:return bad(h,'INVALID_ACTION','不支持的高风险确认操作')
  if not isinstance(context,dict):return bad(h,'INVALID_CONTEXT','确认上下文必须为对象')
  context={**context,'organizationId':org}
  try:result=issue_confirmation(db,a,action,context,int(b.get('ttlMs') or 300000))
  except ValueError as e:return bad(h,str(e),'无法签发确认凭证')
  return h.sendj({'ok':True,**result}) or True
 # V207.3 organization operating model APIs (Admin UI deferred).
 if root in ('departments','business-lines','markets') or (root=='workspaces' and ident and action in ('teams','business-lines','markets')):
  body=h.body() if m in ('POST','PUT','PATCH','DELETE') else {}
  result=handle_organization_model(db,a,org,m,root,ident,action,q,body)
  if result:
   payload,status=result;return h.sendj(payload,status) or True
 # database schema catalog: metadata only, never returns row contents or accepts SQL
 if root in ('database-schema','schema'):
  if m!='GET':return bad(h,'METHOD_NOT_ALLOWED','数据库结构接口只允许只读访问',405)
  if not (platform(db,a) or can(db,a,'audit.read')):return bad(h,'FORBIDDEN','需要审计读取权限',403)
  return h.sendj(build_schema_catalog(db)) or True
 # dashboard
 if root=='dashboard' and m=='GET':
  with db.tx(False) as c:
   names={'teams':'teams','users':'users','workspaces':'workspaces','accounts':'channel_accounts','sources':'sources','devices':'devices','contacts':'contacts'}
   counts={k:c.execute(f'SELECT count(*) FROM {t} WHERE organization_id=?',(org,)).fetchone()[0] for k,t in names.items()}
   counts['activeSessions']=c.execute('SELECT count(*) FROM sessions s JOIN users u ON u.user_id=s.user_id WHERE u.organization_id=? AND s.revoked_at IS NULL AND s.expires_at>?',(org,now_ms())).fetchone()[0]
   counts['audit']=c.execute('SELECT count(*) FROM audit_logs l JOIN users u ON u.user_id=l.actor_id WHERE u.organization_id=?',(org,)).fetchone()[0]
   channel=rows(c,'SELECT channel name,count(*) value FROM channel_accounts WHERE organization_id=? GROUP BY channel',(org,));status=rows(c,'SELECT status name,count(*) value FROM devices WHERE organization_id=? GROUP BY status',(org,))
   recent=rows(c,'SELECT l.*,u.display_name actor_name FROM audit_logs l JOIN users u ON u.user_id=l.actor_id WHERE u.organization_id=? ORDER BY audit_id DESC LIMIT 8',(org,))
  return h.sendj({'ok':True,'counts':counts,'channelDistribution':channel,'deviceStatus':status,'recentAudit':recent,'database':db.quick_check(),'schemaVersion':SCHEMA_VERSION,'version':PRODUCT_VERSION}) or True
 # teams
 if root=='teams':
  if m=='GET':
   with db.tx(False) as c:its=rows(c,"SELECT t.*,w.name workspace_name,(SELECT count(DISTINCT b.user_id) FROM role_bindings b WHERE b.scope_type='team' AND b.scope_id=t.team_id AND b.organization_id=t.organization_id AND b.status='active') member_count,(SELECT count(*) FROM team_channel_accounts x WHERE x.team_id=t.team_id) account_count FROM teams t JOIN workspaces w ON w.workspace_id=t.workspace_id WHERE t.organization_id=? ORDER BY t.created_at",(org,))
   return h.sendj({'ok':True,'items':its}) or True
  if m=='POST':
   if not manage(db,a,'team.manage',org):return bad(h,'FORBIDDEN','无团队管理权限',403)
   b=h.body();name=str(b.get('name') or '').strip()
   if not name:return bad(h,'NAME_REQUIRED','团队名称不能为空')
   n=now_ms();tid='team_'+uuid.uuid4().hex;wid='ws_'+uuid.uuid4().hex
   with db.tx() as c:
    c.execute('INSERT INTO workspaces(workspace_id,name,status,created_at,updated_at,organization_id) VALUES(?,?,\'active\',?,?,?)',(wid,str(b.get('workspaceName') or name),n,n,org));c.execute('INSERT INTO workspace_configs(workspace_id,revision,items_json,updated_at,updated_by) VALUES(?,0,\'[]\',?,?)',(wid,n,a['user_id']));c.execute('INSERT INTO teams(team_id,organization_id,workspace_id,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(tid,org,wid,name,'active',n,n));c.execute("INSERT INTO workspace_teams(workspace_id,team_id,organization_id,relation_type,is_primary,access_level,status,created_at,updated_at) VALUES(?,?,?,'primary',1,'manage','active',?,?)",(wid,tid,org,n,n))
    audit_in_tx(c,a,'create','team',tid,{},b,wid=wid)
   return h.sendj({'ok':True,'teamId':tid,'workspaceId':wid},201) or True
  if ident and not action and m=='PATCH':
   if not manage(db,a,'team.manage',org):return bad(h,'FORBIDDEN','无团队管理权限',403)
   b=h.body();
   with db.tx() as c:
    old=one(c,'SELECT * FROM teams WHERE team_id=? AND organization_id=?',(ident,org))
    if not old:return bad(h,'NOT_FOUND','团队不存在',404)
    c.execute('UPDATE teams SET name=?,status=?,updated_at=? WHERE team_id=?',(str(b.get('name') or old['name']),clean_status(b.get('status')) or old['status'],now_ms(),ident));new=one(c,'SELECT * FROM teams WHERE team_id=?',(ident,))
    audit_in_tx(c,a,'update','team',ident,old,new,b.get('reason'),old['workspace_id'])
   return h.sendj({'ok':True,'item':new}) or True
  if ident and action=='members':
   if m=='GET':
    with db.tx(False) as c:its=rows(c,"SELECT b.binding_id,b.user_id,b.role_id,b.status,b.created_at,b.updated_at,u.login_name,u.display_name,u.status user_status,r.name role_name FROM role_bindings b JOIN users u ON u.user_id=b.user_id JOIN roles r ON r.role_id=b.role_id WHERE b.scope_type='team' AND b.scope_id=? AND b.organization_id=? AND u.organization_id=b.organization_id",(ident,org))
    return h.sendj({'ok':True,'items':its}) or True
   if m=='POST':
    if not manage(db,a,'team.manage',org):return bad(h,'FORBIDDEN','无成员管理权限',403)
    b=h.body();uid=str(b.get('userId') or '');role=str(b.get('roleId') or 'role_operator')
    with db.tx() as c:
     if not c.execute('SELECT 1 FROM users WHERE user_id=? AND organization_id=?',(uid,org)).fetchone():return bad(h,'USER_NOT_FOUND','用户不属于目标企业',404)
     grant_binding_in_tx(c,uid,role,org,'team',ident,a['user_id'])
     audit_in_tx(c,a,'grant','team_membership',uid,{},b)
    return h.sendj({'ok':True}) or True
 # users
 if root=='users':
  if m=='GET':
   with db.tx(False) as c:its=rows(c,"SELECT u.*,group_concat(DISTINCT CASE WHEN b.scope_type='team' AND b.status='active' THEN t.name END) teams,group_concat(DISTINCT CASE WHEN b.status='active' THEN r.name END) roles FROM users u LEFT JOIN role_bindings b ON b.user_id=u.user_id AND b.organization_id=u.organization_id LEFT JOIN teams t ON b.scope_type='team' AND t.team_id=b.scope_id AND t.organization_id=b.organization_id LEFT JOIN roles r ON r.role_id=b.role_id WHERE u.organization_id=? GROUP BY u.user_id ORDER BY u.created_at",(org,))
   return h.sendj({'ok':True,'items':its}) or True
  if m=='POST':
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无用户管理权限',403)
   b=h.body();ln=str(b.get('loginName') or '').strip();pwd=str(b.get('password') or '');team=str(b.get('teamId') or '');role=str(b.get('roleId') or 'role_operator')
   if not ln or not password_strong(pwd):return bad(h,'INVALID_USER','登录名必填；密码至少 12 位且必须同时包含字母和数字')
   with db.tx() as c:
    tr=c.execute('SELECT 1 FROM teams WHERE team_id=? AND organization_id=?',(team,org)).fetchone()
    if not tr:return bad(h,'TEAM_NOT_FOUND','团队不存在',404)
    rr=c.execute("SELECT scope_level FROM roles WHERE role_id=? AND status='active' AND (organization_id IS NULL OR organization_id=?)",(role,org)).fetchone()
    if not rr or rr[0] not in ('organization','team'):return bad(h,'INVALID_ROLE','角色不存在、已停用或范围不适用于企业用户',400)
    scope_type=rr[0];scope_id=org if scope_type=='organization' else team
    uid='usr_'+uuid.uuid4().hex;n=now_ms();ph,salt,it=hash_password(pwd)
    try:
     c.execute('INSERT INTO users(user_id,organization_id,login_name,display_name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(uid,org,ln,str(b.get('displayName') or ln),'active',n,n))
     c.execute('INSERT INTO user_credentials(user_id,password_hash,salt,iterations,must_change,updated_at) VALUES(?,?,?,?,?,?)',(uid,ph,salt,it,1,n))
     grant_binding_in_tx(c,uid,role,org,scope_type,scope_id,a['user_id'])
    except Exception:
     return bad(h,'USER_CONFLICT','登录名冲突或数据无效',409)
    audit_in_tx(c,a,'create','user',uid,{},dict(b,password='***'))
   return h.sendj({'ok':True,'userId':uid},201) or True
  if ident and not action and m=='PATCH':
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无用户管理权限',403)
   b=h.body()
   with db.tx() as c:
    old=one(c,'SELECT * FROM users WHERE user_id=? AND organization_id=?',(ident,org))
    if not old:return bad(h,'NOT_FOUND','用户不存在',404)
    c.execute('UPDATE users SET display_name=?,status=?,updated_at=? WHERE user_id=?',(str(b.get('displayName') or old['display_name']),clean_status(b.get('status')) or old['status'],now_ms(),ident));new=one(c,'SELECT * FROM users WHERE user_id=?',(ident,))
    if new['status']!='active':revoke_sessions_in_tx(c,ident,a['user_id'],'user_disabled')
    audit_in_tx(c,a,'update','user',ident,old,new,b.get('reason'))
   return h.sendj({'ok':True,'item':new}) or True
  if ident and action=='reset-password' and m=='POST':
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无密码重置权限',403)
   b=h.body();pwd=str(b.get('password') or '')
   if not password_strong(pwd):return bad(h,'WEAK_PASSWORD','密码至少 12 位，且必须同时包含字母和数字')
   ph,salt,it=hash_password(pwd)
   with db.tx() as c:
    if not c.execute('SELECT 1 FROM users WHERE user_id=? AND organization_id=?',(ident,org)).fetchone():return bad(h,'NOT_FOUND','用户不存在',404)
    c.execute('UPDATE user_credentials SET password_hash=?,salt=?,iterations=?,must_change=1,updated_at=? WHERE user_id=?',(ph,salt,it,now_ms(),ident));revoke_sessions_in_tx(c,ident,a['user_id'],'password_reset')
    audit_in_tx(c,a,'reset_password','user',ident,{},{})
   return h.sendj({'ok':True}) or True
  if ident and action=='revoke-sessions' and m=='POST':
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无会话管理权限',403)
   with db.tx() as c:
    revoke_sessions_in_tx(c,ident,a['user_id'],'admin_revocation')
    audit_in_tx(c,a,'revoke_sessions','user',ident,{},{})
   return h.sendj({'ok':True}) or True
 # positions
 if root=='positions':
  if m=='GET':
   with db.tx(False) as c:its=rows(c,"SELECT p.*,d.name department_name,(SELECT count(*) FROM user_positions up WHERE up.position_id=p.position_id AND up.status='active') user_count FROM positions p LEFT JOIN departments d ON d.department_id=p.department_id WHERE p.organization_id=? ORDER BY p.sort_order,p.name",(org,))
   return h.sendj({'ok':True,'items':its}) or True
  if m=='POST':
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无职位管理权限',403)
   b=h.body(); name=str(b.get('name') or '').strip(); code=str(b.get('code') or '').strip(); dep=str(b.get('departmentId') or '').strip() or None
   if not name or not code:return bad(h,'INVALID_INPUT','职位名称和代码不能为空')
   pid='pos_'+uuid.uuid4().hex; n=now_ms()
   try:
    with db.tx() as c:
     w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? ORDER BY created_at LIMIT 1",(org,)).fetchone()
     if not w:return bad(h,'WORKSPACE_REQUIRED','当前企业缺少有效业务空间',409)
     c.execute("INSERT INTO positions(position_id,organization_id,department_id,name,code,description,status,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,'active',?,?,?)",(pid,org,dep,name,code,str(b.get('description') or ''),int(b.get('sortOrder') or 0),n,n))
     audit_in_tx(c,a,'create','position',pid,{},b,wid=w[0])
   except sqlite3.IntegrityError:return bad(h,'POSITION_CONFLICT','职位代码冲突或部门不属于当前企业',409)
   return h.sendj({'ok':True,'positionId':pid},201) or True
  if ident and m=='PATCH':
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无职位管理权限',403)
   b=h.body()
   with db.tx() as c:
    old=one(c,'SELECT * FROM positions WHERE position_id=? AND organization_id=?',(ident,org))
    if not old:return bad(h,'NOT_FOUND','职位不存在',404)
    w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? ORDER BY created_at LIMIT 1",(org,)).fetchone()
    if not w:return bad(h,'WORKSPACE_REQUIRED','当前企业缺少有效业务空间',409)
    status=str(b.get('status') if b.get('status') is not None else old['status']).strip().lower()
    if status=='inactive':status='disabled'
    if status not in ('active','disabled','archived'):return bad(h,'INVALID_POSITION_STATUS','职位状态必须为 active、disabled 或 archived',400)
    c.execute('UPDATE positions SET name=?,description=?,status=?,sort_order=?,updated_at=? WHERE position_id=?',(str(b.get('name') or old['name']).strip(),str(b.get('description') if b.get('description') is not None else old['description']),status,int(b.get('sortOrder') if b.get('sortOrder') is not None else old['sort_order']),now_ms(),ident)); new=one(c,'SELECT * FROM positions WHERE position_id=?',(ident,))
    audit_in_tx(c,a,'update','position',ident,old,new,wid=w[0])
   return h.sendj({'ok':True,'item':new}) or True
 # enterprise role bindings (platform grants intentionally excluded)
 if root=='role-bindings':
  if m=='GET' and not ident:
   if not (platform(db,a) or can(db,a,'user.read',organization_id=org)):return bad(h,'FORBIDDEN','无授权读取权限',403)
   status=str(q.get('status') or 'active').strip(); user_id=str(q.get('userId') or q.get('user_id') or '').strip(); role_id=str(q.get('roleId') or q.get('role_id') or '').strip(); scope_type=str(q.get('scopeType') or q.get('scope_type') or '').strip()
   if status not in ('active','disabled','archived','all'):return bad(h,'INVALID_STATUS','授权状态不合法')
   if scope_type and scope_type not in ('organization','workspace','department','team','self'):return bad(h,'INVALID_SCOPE','授权作用域不合法')
   pno,psz,off=page(q);where=['b.organization_id=?',"b.scope_type<>'platform'"];args=[org]
   if status!='all':where.append('b.status=?');args.append(status)
   if user_id:where.append('b.user_id=?');args.append(user_id)
   if role_id:where.append('b.role_id=?');args.append(role_id)
   if scope_type:where.append('b.scope_type=?');args.append(scope_type)
   clause=' AND '.join(where)
   with db.tx(False) as c:
    total=c.execute('SELECT count(*) FROM role_bindings b WHERE '+clause,tuple(args)).fetchone()[0]
    its=rows(c,"SELECT b.*,u.login_name,u.display_name,r.name role_name,r.role_code FROM role_bindings b JOIN users u ON u.user_id=b.user_id JOIN roles r ON r.role_id=b.role_id WHERE "+clause+' ORDER BY b.updated_at DESC,b.binding_id LIMIT ? OFFSET ?',tuple(args+[psz,off]))
   return h.sendj(pack(its,total,pno,psz)) or True
  if m=='POST' and not ident:
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无授权管理权限',403)
   b=h.body();user_id=str(b.get('userId') or '').strip();role_id=str(b.get('roleId') or '').strip();scope_type=str(b.get('scopeType') or '').strip();scope_id=str(b.get('scopeId') or '').strip()
   if not all((user_id,role_id,scope_type,scope_id)):return bad(h,'INVALID_INPUT','用户、角色、作用域类型和作用域 ID 均不能为空')
   if scope_type not in ('organization','workspace','department','team','self'):return bad(h,'INVALID_SCOPE','通用授权接口不允许平台作用域')
   ctx={'organizationId':org,'roleId':role_id,'scopeId':scope_id,'scopeType':scope_type,'userId':user_id}
   if not consume_confirmation(db,a,'binding.grant',h.headers.get('X-RBAC-Confirmation',''),ctx):return bad(h,'CONFIRMATION_REQUIRED','高风险确认凭证无效或已过期',428)
   try:
    with db.tx() as c:
     w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? AND status='active' ORDER BY created_at LIMIT 1",(org,)).fetchone()
     if not w:return bad(h,'WORKSPACE_REQUIRED','当前企业缺少有效业务空间',409)
     active_sessions=c.execute("SELECT count(*) FROM sessions WHERE user_id=? AND revoked_at IS NULL AND expires_at>?",(user_id,now_ms())).fetchone()[0]
     bid=grant_binding_in_tx(c,user_id,role_id,org,scope_type,scope_id,a['user_id'])
     item=one(c,'SELECT * FROM role_bindings WHERE binding_id=?',(bid,));audit_in_tx(c,a,'grant','role_binding',bid,{},item,str(b.get('reason') or ''),w[0])
   except ValueError as e:return bad(h,str(e),'授权主体、角色或作用域无效',400)
   except sqlite3.IntegrityError as e:return bad(h,'BINDING_CONFLICT','授权与租户或作用域约束冲突',409)
   return h.sendj({'ok':True,'bindingId':bid,'item':item,'revokedSessionCount':active_sessions},201) or True
  if ident and m=='DELETE' and action is None:
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无授权管理权限',403)
   with db.tx(False) as c:old=one(c,"SELECT * FROM role_bindings WHERE binding_id=? AND organization_id=? AND scope_type<>'platform' AND status='active'",(ident,org))
   if not old:return bad(h,'NOT_FOUND','有效授权不存在',404)
   ctx={'bindingId':ident,'organizationId':org,'roleId':old['role_id'],'scopeId':old['scope_id'],'scopeType':old['scope_type'],'userId':old['user_id']}
   if not consume_confirmation(db,a,'binding.revoke',h.headers.get('X-RBAC-Confirmation',''),ctx):return bad(h,'CONFIRMATION_REQUIRED','高风险确认凭证无效或已过期',428)
   b=h.body();reason=str(b.get('reason') or '')
   with db.tx() as c:
    current=one(c,"SELECT * FROM role_bindings WHERE binding_id=? AND organization_id=? AND scope_type<>'platform' AND status='active'",(ident,org))
    if not current:return bad(h,'BINDING_CHANGED','授权已变更或撤销，请刷新后重试',409)
    w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? AND status='active' ORDER BY created_at LIMIT 1",(org,)).fetchone()
    if not w:return bad(h,'WORKSPACE_REQUIRED','当前企业缺少有效业务空间',409)
    revoked=revoke_sessions_in_tx(c,current['user_id'],a['user_id'],'authorization_changed')
    c.execute("UPDATE role_bindings SET status='archived',updated_at=? WHERE binding_id=? AND status='active'",(now_ms(),ident));after=one(c,'SELECT * FROM role_bindings WHERE binding_id=?',(ident,));audit_in_tx(c,a,'revoke','role_binding',ident,current,after,reason,w[0])
   return h.sendj({'ok':True,'bindingId':ident,'revokedSessionCount':revoked}) or True
  return bad(h,'METHOD_NOT_ALLOWED','授权接口方法不受支持',405)
 # roles and permission matrix
 if root=='permissions' and m=='GET':
  if not (platform(db,a) or can(db,a,'user.read',organization_id=org)):return bad(h,'FORBIDDEN','无权限读取权限',403)
  with db.tx(False) as c:its=rows(c,'SELECT * FROM permissions ORDER BY permission_key')
  return h.sendj({'ok':True,'items':its}) or True
 if root=='roles':
  if not (platform(db,a) or can(db,a,'user.read',organization_id=org)):return bad(h,'FORBIDDEN','无角色读取权限',403)
  if m=='GET' and not ident:
   with db.tx(False) as c:its=rows(c,"SELECT r.*,group_concat(rp.permission_key) permissions,(SELECT count(DISTINCT b.user_id) FROM role_bindings b WHERE b.role_id=r.role_id AND (b.organization_id=? OR b.organization_id IS NULL) AND b.status='active') member_count FROM roles r LEFT JOIN role_permissions rp ON rp.role_id=r.role_id WHERE r.organization_id IS NULL OR r.organization_id=? GROUP BY r.role_id ORDER BY r.is_system DESC,r.scope_level,r.name",(org,org))
   return h.sendj({'ok':True,'items':its}) or True
  if ident and m=='GET' and action is None:
   with db.tx(False) as c:
    item=one(c,'SELECT * FROM roles WHERE role_id=? AND (organization_id IS NULL OR organization_id=?)',(ident,org))
    if item:item['permissionKeys']=[x[0] for x in c.execute('SELECT permission_key FROM role_permissions WHERE role_id=? ORDER BY permission_key',(ident,))]
   if not item:return bad(h,'NOT_FOUND','角色不存在',404)
   return h.sendj({'ok':True,'item':item}) or True
  if ident and action=='members' and m=='GET':
   with db.tx(False) as c:
    role=one(c,'SELECT role_id FROM roles WHERE role_id=? AND (organization_id IS NULL OR organization_id=?)',(ident,org))
    its=rows(c,"SELECT b.*,u.login_name,u.display_name FROM role_bindings b JOIN users u ON u.user_id=b.user_id WHERE b.role_id=? AND (b.organization_id=? OR b.organization_id IS NULL) AND b.status='active' ORDER BY u.display_name,b.created_at",(ident,org)) if role else []
   if not role:return bad(h,'NOT_FOUND','角色不存在',404)
   return h.sendj({'ok':True,'items':its,'total':len(its)}) or True
  if ident and action=='delete-preview' and m=='GET':
   with db.tx(False) as c:
    role=one(c,'SELECT * FROM roles WHERE role_id=? AND (organization_id IS NULL OR organization_id=?)',(ident,org))
    cnt=c.execute("SELECT count(*) FROM role_bindings WHERE role_id=? AND status='active'",(ident,)).fetchone()[0] if role else 0
   if not role:return bad(h,'NOT_FOUND','角色不存在',404)
   return h.sendj({'ok':True,'roleId':ident,'systemRole':bool(role.get('is_system') or role.get('organization_id') is None),'activeBindingCount':cnt,'canDelete':bool(role.get('organization_id')==org and not role.get('is_system') and cnt==0)}) or True
  if m=='POST' and not ident:
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无角色管理权限',403)
   b=h.body();name=str(b.get('name') or '').strip();code=str(b.get('roleCode') or '').strip() or None;scope=str(b.get('scopeLevel') or 'organization').strip();desc=str(b.get('description') or '').strip();perms=sorted(set(str(x) for x in (b.get('permissionKeys') or [])))
   if not name:return bad(h,'NAME_REQUIRED','角色名称不能为空')
   if scope not in ('organization','workspace','department','team','self'):return bad(h,'INVALID_SCOPE','自定义角色不允许平台作用域')
   ctx={'name':name,'organizationId':org,'permissionKeys':perms,'scopeLevel':scope}
   if not consume_confirmation(db,a,'role.create',h.headers.get('X-RBAC-Confirmation',''),ctx):return bad(h,'CONFIRMATION_REQUIRED','高风险确认凭证无效或已过期',428)
   rid='role_'+uuid.uuid4().hex;w=None
   try:
    with db.tx() as c:
     valid={x[0] for x in c.execute('SELECT permission_key FROM permissions')}
     if any(x not in valid for x in perms):return bad(h,'INVALID_PERMISSION','包含不存在的权限')
     w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? AND status='active' ORDER BY created_at LIMIT 1",(org,)).fetchone()
     if not w:return bad(h,'WORKSPACE_REQUIRED','当前企业缺少有效业务空间',409)
     c.execute("INSERT INTO roles(role_id,organization_id,name,scope_level,status,role_code,description,is_system) VALUES(?,?,?,?,?,?,?,0)",(rid,org,name,scope,'active',code or rid,desc))
     c.executemany('INSERT INTO role_permissions(role_id,permission_key) VALUES(?,?)',[(rid,x) for x in perms])
     item=one(c,'SELECT * FROM roles WHERE role_id=?',(rid,));audit_in_tx(c,a,'create','role',rid,{},item,wid=w[0])
   except sqlite3.IntegrityError:return bad(h,'ROLE_CONFLICT','角色名称、代码或权限冲突',409)
   return h.sendj({'ok':True,'roleId':rid,'item':item},201) or True
  if ident and action=='copy' and m=='POST':
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无角色管理权限',403)
   b=h.body();name=str(b.get('name') or '').strip()
   if not name:return bad(h,'NAME_REQUIRED','新角色名称不能为空')
   ctx={'name':name,'organizationId':org,'sourceRoleId':ident}
   if not consume_confirmation(db,a,'role.copy',h.headers.get('X-RBAC-Confirmation',''),ctx):return bad(h,'CONFIRMATION_REQUIRED','高风险确认凭证无效或已过期',428)
   rid='role_'+uuid.uuid4().hex
   try:
    with db.tx() as c:
     src=one(c,'SELECT * FROM roles WHERE role_id=? AND (organization_id IS NULL OR organization_id=?)',(ident,org))
     if not src:return bad(h,'NOT_FOUND','源角色不存在',404)
     scope=src['scope_level'] if src['scope_level']!='platform' else 'organization';w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? AND status='active' ORDER BY created_at LIMIT 1",(org,)).fetchone()
     if not w:return bad(h,'WORKSPACE_REQUIRED','当前企业缺少有效业务空间',409)
     c.execute("INSERT INTO roles(role_id,organization_id,name,scope_level,status,role_code,description,is_system) VALUES(?,?,?,?,?,?,?,0)",(rid,org,name,scope,'active',rid,str(src.get('description') or '')))
     c.execute('INSERT INTO role_permissions(role_id,permission_key) SELECT ?,permission_key FROM role_permissions WHERE role_id=?',(rid,ident));item=one(c,'SELECT * FROM roles WHERE role_id=?',(rid,));audit_in_tx(c,a,'copy','role',rid,src,item,wid=w[0])
   except sqlite3.IntegrityError:return bad(h,'ROLE_CONFLICT','新角色名称冲突',409)
   return h.sendj({'ok':True,'roleId':rid,'item':item},201) or True
  if ident and m=='PATCH' and action is None:
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无角色管理权限',403)
   b=h.body()
   with db.tx(False) as c:old=one(c,'SELECT * FROM roles WHERE role_id=? AND organization_id=? AND is_system=0',(ident,org));oldperms=sorted(x[0] for x in c.execute('SELECT permission_key FROM role_permissions WHERE role_id=?',(ident,))) if old else []
   if not old:return bad(h,'ROLE_IMMUTABLE','角色不存在或系统角色不可编辑',403)
   name=str(b.get('name') if b.get('name') is not None else old['name']).strip();scope=str(b.get('scopeLevel') if b.get('scopeLevel') is not None else old['scope_level']);status=str(b.get('status') if b.get('status') is not None else old['status']);desc=str(b.get('description') if b.get('description') is not None else old.get('description') or '');perms=sorted(set(str(x) for x in (b.get('permissionKeys') if b.get('permissionKeys') is not None else oldperms)))
   if not name or scope not in ('organization','workspace','department','team','self') or status not in ('active','disabled','archived'):return bad(h,'INVALID_ROLE','角色字段不合法')
   ctx={'name':name,'organizationId':org,'permissionKeys':perms,'roleId':ident,'scopeLevel':scope,'status':status}
   if not consume_confirmation(db,a,'role.update',h.headers.get('X-RBAC-Confirmation',''),ctx):return bad(h,'CONFIRMATION_REQUIRED','高风险确认凭证无效或已过期',428)
   try:
    with db.tx() as c:
     valid={x[0] for x in c.execute('SELECT permission_key FROM permissions')}
     if any(x not in valid for x in perms):return bad(h,'INVALID_PERMISSION','包含不存在的权限')
     w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? AND status='active' ORDER BY created_at LIMIT 1",(org,)).fetchone()
     c.execute('UPDATE roles SET name=?,scope_level=?,status=?,description=? WHERE role_id=?',(name,scope,status,desc,ident));c.execute('DELETE FROM role_permissions WHERE role_id=?',(ident,));c.executemany('INSERT INTO role_permissions(role_id,permission_key) VALUES(?,?)',[(ident,x) for x in perms])
     affected=0
     for u in c.execute("SELECT DISTINCT user_id FROM role_bindings WHERE role_id=? AND status='active'",(ident,)).fetchall():affected+=revoke_sessions_in_tx(c,u[0],a['user_id'],'role_permissions_changed')
     item=one(c,'SELECT * FROM roles WHERE role_id=?',(ident,));audit_in_tx(c,a,'update','role',ident,old,item,str(b.get('reason') or ''),w[0] if w else None)
   except sqlite3.IntegrityError:return bad(h,'ROLE_CONFLICT','角色名称、代码或权限冲突',409)
   return h.sendj({'ok':True,'item':item,'revokedSessionCount':affected}) or True
  if ident and m=='DELETE' and action is None:
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无角色管理权限',403)
   ctx={'organizationId':org,'roleId':ident}
   if not consume_confirmation(db,a,'role.delete',h.headers.get('X-RBAC-Confirmation',''),ctx):return bad(h,'CONFIRMATION_REQUIRED','高风险确认凭证无效或已过期',428)
   with db.tx() as c:
    old=one(c,'SELECT * FROM roles WHERE role_id=? AND organization_id=? AND is_system=0',(ident,org))
    if not old:return bad(h,'ROLE_IMMUTABLE','角色不存在或系统角色不可删除',403)
    cnt=c.execute("SELECT count(*) FROM role_bindings WHERE role_id=? AND status='active'",(ident,)).fetchone()[0]
    if cnt:return bad(h,'ROLE_IN_USE','角色仍有有效授权，不能删除',409)
    w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? AND status='active' ORDER BY created_at LIMIT 1",(org,)).fetchone();c.execute('DELETE FROM role_permissions WHERE role_id=?',(ident,));c.execute('DELETE FROM roles WHERE role_id=?',(ident,));audit_in_tx(c,a,'delete','role',ident,old,{},wid=w[0] if w else None)
   return h.sendj({'ok':True}) or True
 # workspaces
 if root=='workspaces':
  if m=='GET':
   with db.tx(False) as c:its=rows(c,"SELECT w.*,(SELECT count(*) FROM sources s WHERE s.workspace_id=w.workspace_id) sources,(SELECT count(*) FROM devices d WHERE d.workspace_id=w.workspace_id) devices,(SELECT count(*) FROM contacts x WHERE x.workspace_id=w.workspace_id) contacts FROM workspaces w WHERE w.organization_id=? ORDER BY w.created_at",(org,))
   return h.sendj({'ok':True,'items':its}) or True
  if m=='POST' and not ident:
   if not manage(db,a,'team.manage',org):return bad(h,'FORBIDDEN','无工作区管理权限',403)
   b=h.body();name=str(b.get('name') or '').strip()
   if not name:return bad(h,'NAME_REQUIRED','业务空间名称不能为空')
   wid='ws_'+uuid.uuid4().hex;n=now_ms()
   try:
    with db.tx() as c:
     c.execute("INSERT INTO workspaces(workspace_id,name,status,created_at,updated_at,organization_id) VALUES(?,?,'active',?,?,?)",(wid,name,n,n,org))
     c.execute("INSERT INTO workspace_configs(workspace_id,revision,items_json,updated_at,updated_by) VALUES(?,0,'[]',?,?)",(wid,n,a['user_id']))
     audit_in_tx(c,a,'create','workspace',wid,{},b,wid=wid)
   except sqlite3.IntegrityError:return bad(h,'WORKSPACE_CONFLICT','业务空间冲突',409)
   return h.sendj({'ok':True,'workspaceId':wid},201) or True
  if ident and m=='PATCH':
   if not manage(db,a,'team.manage',org):return bad(h,'FORBIDDEN','无工作区管理权限',403)
   b=h.body()
   with db.tx() as c:
    old=one(c,'SELECT * FROM workspaces WHERE workspace_id=? AND organization_id=?',(ident,org))
    if not old:return bad(h,'NOT_FOUND','工作区不存在',404)
    c.execute('UPDATE workspaces SET name=?,status=?,updated_at=? WHERE workspace_id=?',(str(b.get('name') or old['name']),clean_status(b.get('status')) or old['status'],now_ms(),ident));new=one(c,'SELECT * FROM workspaces WHERE workspace_id=?',(ident,))
    audit_in_tx(c,a,'update','workspace',ident,old,new,b.get('reason'),ident)
   return h.sendj({'ok':True,'item':new}) or True
 # accounts
 if root=='accounts':
  body=h.body() if m in ('POST','PUT','PATCH','DELETE') else {}
  child_id=seg[3] if len(seg)>3 else None
  payload,status=handle_channel(db,a,org,m,ident,action,child_id,q,body)
  return h.sendj(payload,status) or True
 # V207.1 domain APIs
 if root=='platforms':
  body=h.body() if m in ('POST','PUT','PATCH','DELETE') else {}
  payload,status=handle_platform(db,a,m,ident,q,body)
  return h.sendj(payload,status) or True
 if root=='campaigns':
  body=h.body() if m in ('POST','PUT','PATCH','DELETE') else {}
  payload,status=handle_campaign(db,a,org,m,ident,q,body)
  return h.sendj(payload,status) or True
 if root=='touchpoints':
  b=h.body() if m in ('POST','PATCH','DELETE') else {}
  payload,status=handle_touchpoint(db,a,org,m,seg[1] if len(seg)>1 else None,q,b)
  return h.sendj(payload,status) or True
 if root=='attributions':
  b=h.body() if m in ('POST','PATCH','DELETE') else {}
  ident=seg[1] if len(seg)>1 else None
  payload,status=handle_attribution(db,a,org,m,ident,q,b)
  return h.sendj(payload,status) or True
 if root in ('source-links','source_paths','source-paths'):
  b=h.body() if m in ('POST','PATCH','DELETE') else {}
  payload,status=handle_source_link(db,a,org,m,seg[1] if len(seg)>1 else None,q,b)
  return h.sendj(payload,status) or True
 if root=='migrations' and m=='GET':
  if not (platform(db,a) or can(db,a,'audit.read')):return bad(h,'FORBIDDEN','无迁移记录读取权限',403)
  with db.tx(False) as c:its=rows(c,'SELECT * FROM schema_migrations ORDER BY applied_at DESC')
  return h.sendj({'ok':True,'items':its}) or True
 # sources domain
 if root=='sources':
  body=h.body() if m in ('POST','PUT','PATCH','DELETE') else {}
  payload,status=handle_source(db,a,org,m,ident,q,body)
  return h.sendj(payload,status) or True
 # devices generic list and state
 if root=='devices':
  if m=='GET':
   if not (platform(db,a) or can(db,a,'device.read')):return bad(h,'FORBIDDEN','无设备读取权限',403)
   with db.tx(False) as c:its=rows(c,"SELECT d.*,t.name team_name,u.display_name assigned_user,(SELECT count(*) FROM source_devices sd WHERE sd.device_id=d.device_id) source_count FROM devices d LEFT JOIN teams t ON t.team_id=d.team_id LEFT JOIN users u ON u.user_id=d.assigned_user_id WHERE d.organization_id=? ORDER BY d.last_seen_at DESC",(org,))
   return h.sendj({'ok':True,'items':its}) or True
  if ident and m=='PATCH':
   if not manage(db,a,'device.disable',org):return bad(h,'FORBIDDEN','无资源管理权限',403)
   b=h.body()
   with db.tx() as c:
    old=one(c,'SELECT * FROM devices WHERE device_id=? AND organization_id=?',(ident,org))
    if not old:return bad(h,'NOT_FOUND','资源不存在',404)
    c.execute('UPDATE devices SET admin_device_name=?,admin_computer_name=?,status=? WHERE device_id=?',(str(b.get('deviceName') if b.get('deviceName') is not None else old.get('admin_device_name') or ''),str(b.get('computerName') if b.get('computerName') is not None else old.get('admin_computer_name') or ''),clean_status(b.get('status')) or old['status'],ident));new=one(c,'SELECT * FROM devices WHERE device_id=?',(ident,))
    audit_in_tx(c,a,'update','device',ident,old,new,b.get('reason'),old.get('workspace_id'))
   return h.sendj({'ok':True,'item':new}) or True
  if ident and action=='binding_code' and m=='POST':
   if not (platform(db,a) or manage(db,a,'device.bind',org)):return bad(h,'FORBIDDEN','无设备绑定权限',403)
   with db.tx() as c:
    old=one(c,'SELECT * FROM devices WHERE device_id=? AND organization_id=?',(ident,org))
    if not old:return bad(h,'NOT_FOUND','资源不存在',404)
    code=secrets.token_hex(4).upper();exp=now_ms()+3600*1000
    c.execute('UPDATE devices SET binding_code=?,binding_code_expires_at=? WHERE device_id=?',(code,exp,ident));new=one(c,'SELECT * FROM devices WHERE device_id=?',(ident,))
    audit_in_tx(c,a,'generate_binding_code','device',ident,old,{'binding_code':code,'binding_code_expires_at':exp},'生成设备绑定码',old.get('workspace_id'))
   return h.sendj({'ok':True,'bindingCode':code,'expiresAt':exp}) or True
# contacts (admin table + direct business edit, lifecycle remains old guarded endpoints)
 if root=='contacts':
  # Parse locally because earlier route branches reuse contact_id/action.
  contact_id=seg[1] if len(seg)>1 else None
  contact_action=seg[2] if len(seg)>2 else None
  contact_identity_id=seg[3] if len(seg)>3 else None
  # Contact identities are isolated in their domain service; keep the legacy route contract.
  handled=handle_contact_identity(h,m,seg,q,a,db,org)
  if handled:return handled
  if len(seg)==1 and m=='GET':
   pno,size,off=page(q);search='%'+str(q.get('q') or '')+'%';deleted=q.get('deleted','all')
   cond="c.organization_id=? AND (?='all' OR (?='yes' AND c.deleted_at IS NOT NULL) OR (?='no' AND c.deleted_at IS NULL)) AND (c.display_name LIKE ? OR c.manual_name LIKE ? OR c.observed_phone LIKE ? OR c.manual_phone LIKE ?)";args=(org,deleted,deleted,deleted,search,search,search,search)
   with db.tx(False) as c:total=c.execute('SELECT count(*) FROM contacts c WHERE '+cond,args).fetchone()[0];its=rows(c,'SELECT c.*,s.source_name,t.name team_name FROM contacts c LEFT JOIN sources s ON s.source_id=c.source_id LEFT JOIN teams t ON t.team_id=c.team_id WHERE '+cond+' ORDER BY c.updated_at DESC LIMIT ? OFFSET ?',args+(size,off))
   return h.sendj(pack(its,total,pno,size)) or True
  if contact_id and len(seg)==2 and m=='PATCH':
   if not manage(db,a,'contact.update',org):return bad(h,'FORBIDDEN','无联系人修改权限',403)
   b=h.body()
   with db.tx() as c:
    old=one(c,'SELECT * FROM contacts WHERE contact_id=? AND organization_id=?',(contact_id,org))
    if not old:return bad(h,'NOT_FOUND','联系人不存在',404)
    c.execute('UPDATE contacts SET manual_name=?,manual_phone=?,remark=?,status=?,updated_at=?,version=version+1 WHERE contact_id=?',(str(b.get('manualName') if b.get('manualName') is not None else old['manual_name']),str(b.get('manualPhone') if b.get('manualPhone') is not None else old['manual_phone']),str(b.get('remark') if b.get('remark') is not None else old['remark']),str(b.get('status') if b.get('status') is not None else old['status']),now_ms(),contact_id));new=one(c,'SELECT * FROM contacts WHERE contact_id=?',(contact_id,))
    audit_in_tx(c,a,'update','contact',contact_id,old,new,b.get('reason'),old['workspace_id'])
   return h.sendj({'ok':True,'item':new}) or True
 # graph with explicit relations
 if root=='graph' and m=='GET':
  if not (platform(db,a) or can(db,a,'organization.read')):return bad(h,'FORBIDDEN','无组织读取权限',403)
  with db.tx(False) as c:
   data={
    'organizations':rows(c,'SELECT * FROM organizations WHERE organization_id=?',(org,)),
    'teams':rows(c,'SELECT * FROM teams WHERE organization_id=?',(org,)),
    'users':rows(c,'SELECT user_id,display_name,login_name,status FROM users WHERE organization_id=?',(org,)),
    'workspaces':rows(c,'SELECT * FROM workspaces WHERE organization_id=?',(org,)),
    'accounts':rows(c,'SELECT * FROM channel_accounts WHERE organization_id=?',(org,)),
    'sources':rows(c,'SELECT source_id,source_name,channel,team_id,workspace_id,channel_account_id,status FROM sources WHERE organization_id=?',(org,)),
    'devices':rows(c,'SELECT device_id,team_id,workspace_id,assigned_user_id,system_device_name,user_device_alias,admin_device_name,status FROM devices WHERE organization_id=?',(org,)),
    'teamMemberships':rows(c,"SELECT b.binding_id,b.user_id,b.role_id,b.scope_id team_id,b.status,b.created_at,b.updated_at FROM role_bindings b WHERE b.organization_id=? AND b.scope_type='team'",(org,)),
    'accountGrants':rows(c,'SELECT x.* FROM team_channel_accounts x JOIN teams t ON t.team_id=x.team_id WHERE t.organization_id=?',(org,)),
    'sourceDevices':rows(c,'SELECT sd.* FROM source_devices sd JOIN sources s ON s.source_id=sd.source_id WHERE s.organization_id=?',(org,))}
  return h.sendj({'ok':True,'graph':data}) or True
 # audit
 if root=='audit' and m=='GET':
  if not (platform(db,a) or can(db,a,'audit.read')):return bad(h,'FORBIDDEN','无审计读取权限',403)
  pno,size,off=page(q);et=q.get('entity_type');op=q.get('operation');uid=q.get('user_id');eid=q.get('entity_id');cond='u.organization_id=?';args=[org]
  if et:cond+=' AND l.entity_type=?';args.append(et)
  if op:cond+=' AND l.operation=?';args.append(op)
  if uid:cond+=' AND l.actor_id=?';args.append(uid)
  if eid:cond+=' AND l.entity_id=?';args.append(eid)
  with db.tx(False) as c:total=c.execute(f'SELECT count(*) FROM audit_logs l JOIN users u ON u.user_id=l.actor_id WHERE {cond}',tuple(args)).fetchone()[0];its=rows(c,f'SELECT l.*,u.display_name actor_name FROM audit_logs l JOIN users u ON u.user_id=l.actor_id WHERE {cond} ORDER BY audit_id DESC LIMIT ? OFFSET ?',tuple(args+[size,off]))
  return h.sendj(pack(its,total,pno,size)) or True
 # recycle bin (deleted contacts)
 if root=='recycle' and m=='GET':
  if not (platform(db,a) or can(db,a,'contact.read')):return bad(h,'FORBIDDEN','无联系人读取权限',403)
  pno,size,off=page(q)
  with db.tx(False) as c:total=c.execute('SELECT count(*) FROM contacts WHERE organization_id=? AND deleted_at IS NOT NULL',(org,)).fetchone()[0];its=rows(c,'SELECT c.*,s.source_name FROM contacts c LEFT JOIN sources s ON s.source_id=c.source_id WHERE c.organization_id=? AND c.deleted_at IS NOT NULL ORDER BY c.deleted_at DESC LIMIT ? OFFSET ?',(org,size,off))
  return h.sendj(pack(its,total,pno,size)) or True
 if root=='recycle' and ident and m=='POST':
  if not manage(db,a,'contact.update',org):return bad(h,'FORBIDDEN','无联系人恢复权限',403)
  with db.tx() as c:
   old=one(c,'SELECT * FROM contacts WHERE contact_id=? AND organization_id=? AND deleted_at IS NOT NULL',(ident,org))
   if not old:return bad(h,'NOT_FOUND','联系人不存在或未删除',404)
   c.execute('UPDATE contacts SET deleted_at=NULL,updated_at=?,version=version+1 WHERE contact_id=?',(now_ms(),ident));new=one(c,'SELECT * FROM contacts WHERE contact_id=?',(ident,))
   audit_in_tx(c,a,'restore','contact',ident,old,new,'从回收站恢复',old['workspace_id'])
  return h.sendj({'ok':True,'item':new}) or True
 # sessions management
 if root=='sessions' and m=='GET':
  if not (platform(db,a) or can(db,a,'user.read')):return bad(h,'FORBIDDEN','无会话读取权限',403)
  pno,size,off=page(q)
  with db.tx(False) as c:total=c.execute('SELECT count(*) FROM sessions s JOIN users u ON u.user_id=s.user_id WHERE u.organization_id=?',(org,)).fetchone()[0];its=rows(c,'SELECT s.*,u.display_name user_name,u.login_name FROM sessions s JOIN users u ON u.user_id=s.user_id WHERE u.organization_id=? ORDER BY s.created_at DESC LIMIT ? OFFSET ?',(org,size,off))
  return h.sendj(pack(its,total,pno,size)) or True
 if root=='sessions' and ident and m=='DELETE':
  if not manage(db,a,'user.disable',org):return bad(h,'FORBIDDEN','无会话撤销权限',403)
  with db.tx() as c:
   old=one(c,'SELECT s.*,u.organization_id FROM sessions s JOIN users u ON u.user_id=s.user_id WHERE s.session_id=?',(ident,))
   if not old or old['organization_id']!=org:return bad(h,'NOT_FOUND','会话不存在',404)
   revoke_session_in_tx(c,ident,a['user_id'],'admin_revocation',old['user_id'])
   w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? AND status='active' ORDER BY created_at LIMIT 1",(org,)).fetchone(); audit_in_tx(c,a,'revoke','session',ident,old,{},'管理员撤销会话',w[0] if w else None)
  return h.sendj({'ok':True}) or True
 # tags management
 if root=='tags' and m=='GET':
  if not (platform(db,a) or can(db,a,'contact.read')):return bad(h,'FORBIDDEN','无标签读取权限',403)
  wid=q.get('workspace');kind=q.get('kind')
  if not wid:return bad(h,'WORKSPACE_REQUIRED','工作区参数必需')
  with db.tx(False) as c:
   if not c.execute('SELECT 1 FROM workspaces WHERE workspace_id=? AND organization_id=?',(wid,org)).fetchone():return bad(h,'WORKSPACE_NOT_FOUND','工作区不存在',404)
   cond='workspace_id=?';args=[wid]
   if kind:cond+=' AND tag_kind=?';args.append(kind)
   its=rows(c,f'SELECT * FROM tags WHERE {cond} ORDER BY sort_order,name',tuple(args))
  return h.sendj({'ok':True,'items':its}) or True
 if root=='tags' and m=='POST':
  if not manage(db,a,'contact.update',org):return bad(h,'FORBIDDEN','无标签管理权限',403)
  b=h.body();wid=str(b.get('workspace') or '').strip();name=str(b.get('name') or '').strip();kind=str(b.get('kind') or 'portrait')
  if not wid or not name:return bad(h,'INVALID_INPUT','工作区和名称不能为空')
  if kind not in ('status','portrait'):return bad(h,'INVALID_KIND','标签类型必须为 status 或 portrait')
  tid='tag_'+uuid.uuid4().hex;n=now_ms()
  try:
   with db.tx() as c:
    if not c.execute('SELECT 1 FROM workspaces WHERE workspace_id=? AND organization_id=?',(wid,org)).fetchone():return bad(h,'WORKSPACE_NOT_FOUND','工作区不存在',404)
    c.execute('INSERT INTO tags(tag_id,workspace_id,name,color,category,tag_kind,sort_order,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,1,?,?)',(tid,wid,name,str(b.get('color') or '#64748b'),str(b.get('category') or ''),kind,int(b.get('sortOrder') or 0),n,n));item=one(c,'SELECT * FROM tags WHERE tag_id=?',(tid,))
    audit_in_tx(c,a,'create','tag',tid,{},item,wid)
   return h.sendj({'ok':True,'item':item},201) or True
  except sqlite3.IntegrityError:return bad(h,'TAG_CONFLICT','标签名称已存在',409)
 if root=='tags' and ident and m=='DELETE':
  if not manage(db,a,'contact.update',org):return bad(h,'FORBIDDEN','无标签删除权限',403)
  with db.tx() as c:
   old=one(c,'SELECT t.*,w.organization_id FROM tags t JOIN workspaces w ON w.workspace_id=t.workspace_id WHERE t.tag_id=?',(ident,))
   if not old or old['organization_id']!=org:return bad(h,'NOT_FOUND','标签不存在',404)
   c.execute('DELETE FROM contact_tags WHERE tag_id=?',(ident,));c.execute('DELETE FROM tags WHERE tag_id=?',(ident,))
   audit_in_tx(c,a,'delete','tag',ident,old,{},old['workspace_id'])
  return h.sendj({'ok':True}) or True
 # custom field definitions
 if root=='field-definitions' and m=='GET':
  if not (platform(db,a) or can(db,a,'contact.read')):return bad(h,'FORBIDDEN','无字段定义读取权限',403)
  wid=q.get('workspace')
  if not wid:return bad(h,'WORKSPACE_REQUIRED','工作区参数必需')
  with db.tx(False) as c:
   if not c.execute('SELECT 1 FROM workspaces WHERE workspace_id=? AND organization_id=?',(wid,org)).fetchone():return bad(h,'WORKSPACE_NOT_FOUND','工作区不存在',404)
   its=rows(c,'SELECT * FROM custom_field_definitions WHERE workspace_id=? ORDER BY sort_order,field_key',(wid,))
  return h.sendj({'ok':True,'items':its}) or True
 if root=='field-definitions' and m=='POST':
  if not manage(db,a,'contact.update',org):return bad(h,'FORBIDDEN','无字段定义管理权限',403)
  b=h.body();wid=str(b.get('workspace') or '').strip();key=str(b.get('fieldKey') or '').strip().lower();label=str(b.get('label') or '').strip();ftype=str(b.get('fieldType') or 'text')
  if not wid or not key or not label:return bad(h,'INVALID_INPUT','工作区、键名和标签不能为空')
  if ftype not in ('text','number','date','boolean','select'):return bad(h,'INVALID_TYPE','字段类型无效')
  n=now_ms()
  try:
   with db.tx() as c:
    if not c.execute('SELECT 1 FROM workspaces WHERE workspace_id=? AND organization_id=?',(wid,org)).fetchone():return bad(h,'WORKSPACE_NOT_FOUND','工作区不存在',404)
    c.execute('INSERT INTO custom_field_definitions(workspace_id,field_key,label,field_type,sort_order,enabled,created_at,updated_at) VALUES(?,?,?,?,?,1,?,?)',(wid,key,label,ftype,int(b.get('sortOrder') or 0),n,n));item=one(c,'SELECT * FROM custom_field_definitions WHERE workspace_id=? AND field_key=?',(wid,key))
    audit_in_tx(c,a,'create','field_definition',key,{},item,wid)
   return h.sendj({'ok':True,'item':item},201) or True
  except sqlite3.IntegrityError:return bad(h,'FIELD_CONFLICT','字段键名已存在',409)
 if root=='field-definitions' and ident and m=='DELETE':
  if not manage(db,a,'contact.update',org):return bad(h,'FORBIDDEN','无字段定义删除权限',403)
  wid=q.get('workspace')
  if not wid:return bad(h,'WORKSPACE_REQUIRED','工作区参数必需')
  with db.tx() as c:
   if not c.execute('SELECT 1 FROM workspaces WHERE workspace_id=? AND organization_id=?',(wid,org)).fetchone():return bad(h,'WORKSPACE_NOT_FOUND','工作区不存在',404)
   old=one(c,'SELECT * FROM custom_field_definitions WHERE workspace_id=? AND field_key=?',(wid,ident))
   if not old:return bad(h,'NOT_FOUND','字段定义不存在',404)
   c.execute('DELETE FROM contact_custom_values WHERE field_key=?',(ident,));c.execute('DELETE FROM custom_field_definitions WHERE workspace_id=? AND field_key=?',(wid,ident))
   audit_in_tx(c,a,'delete','field_definition',ident,old,{},wid)
  return h.sendj({'ok':True}) or True
 # diagnostics
 if root=='diagnostics' and m=='GET':
  if not (platform(db,a) or can(db,a,'audit.read')):return bad(h,'FORBIDDEN','无诊断权限',403)
  with db.tx(False) as c:
   tables=[x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")];counts={t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in tables};fk=[dict(x) for x in c.execute('PRAGMA foreign_key_check')]
  path=str(db.path);return h.sendj({'ok':True,'version':PRODUCT_VERSION,'schemaVersion':SCHEMA_VERSION,'quickCheck':db.quick_check(),'databasePath':path,'databaseBytes':os.path.getsize(path) if os.path.exists(path) else 0,'walExists':os.path.exists(path+'-wal'),'shmExists':os.path.exists(path+'-shm'),'foreignKeyIssues':fk,'tableCounts':counts}) or True
 return bad(h,'NOT_FOUND','管理接口不存在',404)

# V207.2.0-dev 更新说明（2026-09-18）：新增平台、营销活动、触点与客户归因管理 API；写入操作执行组织/工作区隔离、RBAC 与审计。

# V207.3.0-dev 更新说明（2026-09-19）：接入部门、业务线、市场和业务空间多维关系 API；创建企业/团队同步主工作区关系；改密兼容 currentPassword，密码错误返回 400。

# V207.5.0-dev 更新说明（2026-09-20）：数据字典仅允许 GET，并统一产品及 Schema 版本来源。
