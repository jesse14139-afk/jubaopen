# -*- coding: utf-8 -*-
"""V207 企业综合管理 API。保持 Schema 207；所有范围与写入均由服务端校验。"""
import json, uuid, os, sqlite3
from V207_shared_db import now_ms,dumps,loads,hash_password
from V207_security import can,permissions,verify_password,password_strong
from V207_schema_catalog import build_schema_catalog
from V207_scope import resolve_scope, require_platform, require_account_grant
from V207_platform_service import handle as handle_platform
from V207_channel_service import handle as handle_channel
from V207_source_service import handle as handle_source
from V207_campaign_service import handle as handle_campaign
from V207_contact_identity_service import handle as handle_contact_identity
from V207_touchpoint_service import handle as handle_touchpoint
from V207_attribution_service import handle as handle_attribution
from V207_source_link_service import handle as handle_source_link
CHANNELS=('whatsapp','instagram','facebook','messenger','telegram')

def rows(c,sql,args=()): return [dict(x) for x in c.execute(sql,args)]
def one(c,sql,args=()):
 r=c.execute(sql,args).fetchone(); return dict(r) if r else None
def platform(db,a):
 # 平台级权限不得由企业角色隐式提升；仅内置系统管理员具备跨企业能力。
 return bool(a and a.get('user_id')=='usr_admin')
def org_ok(db,a,org):return bool(org) and (platform(db,a) or org==a['organization_id'])
def manage(db,a,perm,org):return org_ok(db,a,org) and (platform(db,a) or can(db,a,perm))
def target(q,a,b=None):return str((b or {}).get('organizationId') or (b or {}).get('organization_id') or q.get('organization_id') or a['organization_id'])
def page(q):
 try:p=max(1,int(q.get('page',1)));size=min(200,max(1,int(q.get('pageSize',q.get('limit',50)))))
 except:p,size=1,50
 return p,size,(p-1)*size
def pack(items,total,p,size,**extra):return {'ok':True,'items':items,'pagination':{'page':p,'pageSize':size,'total':total,'pages':(total+size-1)//size},**extra}
def bad(h,code,msg,status=400):return h.sendj({'ok':False,'code':code,'message':msg},status) or True
def audit(db,a,op,typ,eid,before,after,reason=None,wid='default'):
 with db.tx() as c:c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(wid or 'default',a['user_id'],None,op,typ,eid,dumps(before or {}),dumps(after or {}),reason,now_ms()))
def audit_in_tx(c,a,op,typ,eid,before,after,reason=None,wid='default'):
 c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(wid or 'default',a['user_id'],None,op,typ,eid,dumps(before or {}),dumps(after or {}),reason,now_ms()))
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
   org=one(c,'SELECT * FROM organizations WHERE organization_id=?',(a['organization_id'],)); cr=one(c,'SELECT must_change,updated_at FROM user_credentials WHERE user_id=?',(a['user_id'],))
  return h.sendj({'ok':True,'user':{k:a[k] for k in ('user_id','login_name','display_name','organization_id')},'organization':org,'platformAdmin':platform(db,a),'permissions':sorted(permissions(db,a['user_id'])),'credential':cr}) or True
 if root=='change-password' and m=='POST':
  b=h.body();old=str(b.get('oldPassword') or '');new=str(b.get('newPassword') or '')
  if not password_strong(new):return bad(h,'WEAK_PASSWORD','新密码至少 12 位，且必须同时包含字母和数字')
  with db.tx() as c:
   cr=c.execute('SELECT * FROM user_credentials WHERE user_id=?',(a['user_id'],)).fetchone()
   if not cr or not verify_password(old,cr):return bad(h,'INVALID_PASSWORD','当前密码错误',401)
   ph,salt,it=hash_password(new);c.execute('UPDATE user_credentials SET password_hash=?,salt=?,iterations=?,must_change=0,updated_at=? WHERE user_id=?',(ph,salt,it,now_ms(),a['user_id']))
   c.execute('UPDATE sessions SET revoked_at=? WHERE user_id=? AND session_id<>?',(now_ms(),a['user_id'],a['session_id']))
  audit(db,a,'change_password','user',a['user_id'],{},{});return h.sendj({'ok':True}) or True
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
     c.execute('INSERT INTO organizations(organization_id,name,status,created_at,updated_at) VALUES(?,?,?,?,?)',(oid,name,'active',n,n));c.execute('INSERT INTO workspaces(workspace_id,name,status,created_at,updated_at,organization_id) VALUES(?,?,\'active\',?,?,?)',(wid,name+'工作区',n,n,oid));c.execute('INSERT INTO workspace_configs(workspace_id,revision,items_json,updated_at,updated_by) VALUES(?,0,\'[]\',?,?)',(wid,n,a['user_id']));c.execute('INSERT INTO teams(team_id,organization_id,workspace_id,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(tid,oid,wid,'默认团队','active',n,n))
   except Exception as e:return bad(h,'ORGANIZATION_CONFLICT','企业 ID 已存在或数据冲突',409)
   audit(db,a,'create','organization',oid,{},b,wid=wid);return h.sendj({'ok':True,'organizationId':oid,'workspaceId':wid,'teamId':tid},201) or True
  if ident and m=='PATCH':
   if not platform(db,a):return bad(h,'FORBIDDEN','仅平台超级管理员可修改企业',403)
   b=h.body();st=clean_status(b.get('status'))
   with db.tx() as c:
    old=one(c,'SELECT * FROM organizations WHERE organization_id=?',(ident,))
    if not old:return bad(h,'NOT_FOUND','企业不存在',404)
    c.execute('UPDATE organizations SET name=?,status=?,updated_at=? WHERE organization_id=?',(str(b.get('name') or old['name']).strip(),st or old['status'],now_ms(),ident));new=one(c,'SELECT * FROM organizations WHERE organization_id=?',(ident,))
   audit(db,a,'update','organization',ident,old,new, b.get('reason'));return h.sendj({'ok':True,'item':new}) or True
 # common organization scope
 org=target(q,a)
 if not org_ok(db,a,org):return bad(h,'FORBIDDEN','无权访问目标企业',403)
 # database schema catalog: metadata only, never returns row contents or accepts SQL
 if root=='database-schema':
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
  return h.sendj({'ok':True,'counts':counts,'channelDistribution':channel,'deviceStatus':status,'recentAudit':recent,'database':db.quick_check(),'schemaVersion':207,'version':'207.2.0-dev'}) or True
 # teams
 if root=='teams':
  if m=='GET':
   with db.tx(False) as c:its=rows(c,"SELECT t.*,w.name workspace_name,(SELECT count(*) FROM team_memberships tm WHERE tm.team_id=t.team_id AND tm.status='active') member_count,(SELECT count(*) FROM team_channel_accounts x WHERE x.team_id=t.team_id) account_count FROM teams t JOIN workspaces w ON w.workspace_id=t.workspace_id WHERE t.organization_id=? ORDER BY t.created_at",(org,))
   return h.sendj({'ok':True,'items':its}) or True
  if m=='POST':
   if not manage(db,a,'team.manage',org):return bad(h,'FORBIDDEN','无团队管理权限',403)
   b=h.body();name=str(b.get('name') or '').strip()
   if not name:return bad(h,'NAME_REQUIRED','团队名称不能为空')
   n=now_ms();tid='team_'+uuid.uuid4().hex;wid='ws_'+uuid.uuid4().hex
   with db.tx() as c:c.execute('INSERT INTO workspaces(workspace_id,name,status,created_at,updated_at,organization_id) VALUES(?,?,\'active\',?,?,?)',(wid,str(b.get('workspaceName') or name),n,n,org));c.execute('INSERT INTO workspace_configs(workspace_id,revision,items_json,updated_at,updated_by) VALUES(?,0,\'[]\',?,?)',(wid,n,a['user_id']));c.execute('INSERT INTO teams(team_id,organization_id,workspace_id,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(tid,org,wid,name,'active',n,n))
   audit(db,a,'create','team',tid,{},b,wid=wid);return h.sendj({'ok':True,'teamId':tid,'workspaceId':wid},201) or True
  if ident and not action and m=='PATCH':
   if not manage(db,a,'team.manage',org):return bad(h,'FORBIDDEN','无团队管理权限',403)
   b=h.body();
   with db.tx() as c:
    old=one(c,'SELECT * FROM teams WHERE team_id=? AND organization_id=?',(ident,org))
    if not old:return bad(h,'NOT_FOUND','团队不存在',404)
    c.execute('UPDATE teams SET name=?,status=?,updated_at=? WHERE team_id=?',(str(b.get('name') or old['name']),clean_status(b.get('status')) or old['status'],now_ms(),ident));new=one(c,'SELECT * FROM teams WHERE team_id=?',(ident,))
   audit(db,a,'update','team',ident,old,new,b.get('reason'),old['workspace_id']);return h.sendj({'ok':True,'item':new}) or True
  if ident and action=='members':
   if m=='GET':
    with db.tx(False) as c:its=rows(c,'SELECT tm.*,u.login_name,u.display_name,u.status user_status,r.name role_name FROM team_memberships tm JOIN users u ON u.user_id=tm.user_id JOIN roles r ON r.role_id=tm.role_id WHERE tm.team_id=? AND u.organization_id=?',(ident,org))
    return h.sendj({'ok':True,'items':its}) or True
   if m=='POST':
    if not manage(db,a,'team.manage',org):return bad(h,'FORBIDDEN','无成员管理权限',403)
    b=h.body();uid=str(b.get('userId') or '');role=str(b.get('roleId') or 'role_operator')
    with db.tx() as c:
     if not c.execute('SELECT 1 FROM users WHERE user_id=? AND organization_id=?',(uid,org)).fetchone():return bad(h,'USER_NOT_FOUND','用户不属于目标企业',404)
     c.execute("INSERT INTO team_memberships(user_id,team_id,role_id,status) VALUES(?,?,?,'active') ON CONFLICT(user_id,team_id,role_id) DO UPDATE SET status='active'",(uid,ident,role))
    audit(db,a,'grant','team_membership',uid,{},b);return h.sendj({'ok':True}) or True
 # users
 if root=='users':
  if m=='GET':
   with db.tx(False) as c:its=rows(c,"SELECT u.*,group_concat(DISTINCT t.name) teams,group_concat(DISTINCT r.name) roles FROM users u LEFT JOIN team_memberships tm ON tm.user_id=u.user_id LEFT JOIN teams t ON t.team_id=tm.team_id LEFT JOIN roles r ON r.role_id=tm.role_id WHERE u.organization_id=? GROUP BY u.user_id ORDER BY u.created_at",(org,))
   return h.sendj({'ok':True,'items':its}) or True
  if m=='POST':
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无用户管理权限',403)
   b=h.body();ln=str(b.get('loginName') or '').strip();pwd=str(b.get('password') or '');team=str(b.get('teamId') or '');role=str(b.get('roleId') or 'role_operator')
   if not ln or not password_strong(pwd):return bad(h,'INVALID_USER','登录名必填；密码至少 12 位且必须同时包含字母和数字')
   with db.tx() as c:
    tr=c.execute('SELECT 1 FROM teams WHERE team_id=? AND organization_id=?',(team,org)).fetchone()
    if not tr:return bad(h,'TEAM_NOT_FOUND','团队不存在',404)
    uid='usr_'+uuid.uuid4().hex;n=now_ms();ph,salt,it=hash_password(pwd)
    try:
     c.execute('INSERT INTO users(user_id,organization_id,login_name,display_name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(uid,org,ln,str(b.get('displayName') or ln),'active',n,n))
     c.execute('INSERT INTO user_credentials(user_id,password_hash,salt,iterations,must_change,updated_at) VALUES(?,?,?,?,?,?)',(uid,ph,salt,it,1,n))
     c.execute("INSERT INTO team_memberships(user_id,team_id,role_id,status) VALUES(?,?,?,'active')",(uid,team,role))
     if role in ('role_orgadmin','role_superadmin','role_auditor'):
      c.execute("INSERT INTO organization_memberships(user_id,organization_id,role_id,status) VALUES(?,?,?,'active')",(uid,org,role))
    except Exception:
     return bad(h,'USER_CONFLICT','登录名冲突或数据无效',409)
   audit(db,a,'create','user',uid,{},dict(b,password='***'));return h.sendj({'ok':True,'userId':uid},201) or True
  if ident and not action and m=='PATCH':
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无用户管理权限',403)
   b=h.body()
   with db.tx() as c:
    old=one(c,'SELECT * FROM users WHERE user_id=? AND organization_id=?',(ident,org))
    if not old:return bad(h,'NOT_FOUND','用户不存在',404)
    c.execute('UPDATE users SET display_name=?,status=?,updated_at=? WHERE user_id=?',(str(b.get('displayName') or old['display_name']),clean_status(b.get('status')) or old['status'],now_ms(),ident));new=one(c,'SELECT * FROM users WHERE user_id=?',(ident,))
    if new['status']!='active':c.execute('UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL',(now_ms(),ident))
   audit(db,a,'update','user',ident,old,new,b.get('reason'));return h.sendj({'ok':True,'item':new}) or True
  if ident and action=='reset-password' and m=='POST':
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无密码重置权限',403)
   b=h.body();pwd=str(b.get('password') or '')
   if not password_strong(pwd):return bad(h,'WEAK_PASSWORD','密码至少 12 位，且必须同时包含字母和数字')
   ph,salt,it=hash_password(pwd)
   with db.tx() as c:
    if not c.execute('SELECT 1 FROM users WHERE user_id=? AND organization_id=?',(ident,org)).fetchone():return bad(h,'NOT_FOUND','用户不存在',404)
    c.execute('UPDATE user_credentials SET password_hash=?,salt=?,iterations=?,must_change=1,updated_at=? WHERE user_id=?',(ph,salt,it,now_ms(),ident));c.execute('UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL',(now_ms(),ident))
   audit(db,a,'reset_password','user',ident,{},{});return h.sendj({'ok':True}) or True
  if ident and action=='revoke-sessions' and m=='POST':
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无会话管理权限',403)
   with db.tx() as c:c.execute('UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL',(now_ms(),ident))
   audit(db,a,'revoke_sessions','user',ident,{},{});return h.sendj({'ok':True}) or True
 # roles
 if root in ('roles','permissions') and m=='GET':
  with db.tx(False) as c:
   if root=='permissions':its=rows(c,'SELECT * FROM permissions ORDER BY permission_key')
   else:its=rows(c,"SELECT r.*,group_concat(rp.permission_key) permissions,(SELECT count(*) FROM team_memberships tm WHERE tm.role_id=r.role_id)+(SELECT count(*) FROM organization_memberships om WHERE om.role_id=r.role_id) member_count FROM roles r LEFT JOIN role_permissions rp ON rp.role_id=r.role_id WHERE r.organization_id IS NULL OR r.organization_id=? GROUP BY r.role_id ORDER BY r.scope_level,r.name",(org,))
  return h.sendj({'ok':True,'items':its}) or True
 # workspaces
 if root=='workspaces':
  if m=='GET':
   with db.tx(False) as c:its=rows(c,"SELECT w.*,(SELECT count(*) FROM sources s WHERE s.workspace_id=w.workspace_id) sources,(SELECT count(*) FROM devices d WHERE d.workspace_id=w.workspace_id) devices,(SELECT count(*) FROM contacts x WHERE x.workspace_id=w.workspace_id) contacts FROM workspaces w WHERE w.organization_id=? ORDER BY w.created_at",(org,))
   return h.sendj({'ok':True,'items':its}) or True
  if ident and m=='PATCH':
   if not manage(db,a,'team.manage',org):return bad(h,'FORBIDDEN','无工作区管理权限',403)
   b=h.body()
   with db.tx() as c:
    old=one(c,'SELECT * FROM workspaces WHERE workspace_id=? AND organization_id=?',(ident,org))
    if not old:return bad(h,'NOT_FOUND','工作区不存在',404)
    c.execute('UPDATE workspaces SET name=?,status=?,updated_at=? WHERE workspace_id=?',(str(b.get('name') or old['name']),clean_status(b.get('status')) or old['status'],now_ms(),ident));new=one(c,'SELECT * FROM workspaces WHERE workspace_id=?',(ident,))
   audit(db,a,'update','workspace',ident,old,new,b.get('reason'),ident);return h.sendj({'ok':True,'item':new}) or True
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
   audit(db,a,'update','device',ident,old,new,b.get('reason'),old.get('workspace_id'));return h.sendj({'ok':True,'item':new}) or True
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
   audit(db,a,'update','contact',contact_id,old,new,b.get('reason'),old['workspace_id']);return h.sendj({'ok':True,'item':new}) or True
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
    'teamMemberships':rows(c,'SELECT tm.* FROM team_memberships tm JOIN teams t ON t.team_id=tm.team_id WHERE t.organization_id=?',(org,)),
    'accountGrants':rows(c,'SELECT x.* FROM team_channel_accounts x JOIN teams t ON t.team_id=x.team_id WHERE t.organization_id=?',(org,)),
    'sourceDevices':rows(c,'SELECT sd.* FROM source_devices sd JOIN sources s ON s.source_id=sd.source_id WHERE s.organization_id=?',(org,))}
  return h.sendj({'ok':True,'graph':data}) or True
 # audit
 if root=='audit' and m=='GET':
  if not (platform(db,a) or can(db,a,'audit.read')):return bad(h,'FORBIDDEN','无审计读取权限',403)
  pno,size,off=page(q)
  with db.tx(False) as c:total=c.execute('SELECT count(*) FROM audit_logs l JOIN users u ON u.user_id=l.actor_id WHERE u.organization_id=?',(org,)).fetchone()[0];its=rows(c,'SELECT l.*,u.display_name actor_name FROM audit_logs l JOIN users u ON u.user_id=l.actor_id WHERE u.organization_id=? ORDER BY audit_id DESC LIMIT ? OFFSET ?',(org,size,off))
  return h.sendj(pack(its,total,pno,size)) or True
 # diagnostics
 if root=='diagnostics' and m=='GET':
  if not (platform(db,a) or can(db,a,'audit.read')):return bad(h,'FORBIDDEN','无诊断权限',403)
  with db.tx(False) as c:
   tables=[x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")];counts={t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in tables};fk=[dict(x) for x in c.execute('PRAGMA foreign_key_check')]
  path=str(db.path);return h.sendj({'ok':True,'version':'207.2.0-dev','schemaVersion':207,'quickCheck':db.quick_check(),'databasePath':path,'databaseBytes':os.path.getsize(path) if os.path.exists(path) else 0,'walExists':os.path.exists(path+'-wal'),'shmExists':os.path.exists(path+'-shm'),'foreignKeyIssues':fk,'tableCounts':counts}) or True
 return bad(h,'NOT_FOUND','管理接口不存在',404)

# V207.2.0-dev 更新说明（2026-09-18）：新增平台、营销活动、触点与客户归因管理 API；写入操作执行组织/工作区隔离、RBAC 与审计。
