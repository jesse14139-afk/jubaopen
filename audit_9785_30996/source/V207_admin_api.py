# -*- coding: utf-8 -*-
"""V208.2.0 企业综合管理 API。Schema 217；所有范围与写入均由服务端校验。"""
import hashlib, json, uuid, os, sqlite3, secrets, re
from V207_shared_db import now_ms,dumps,loads,hash_password,default_workspace_id
from V207_security import can,permissions,authorization_profile,verify_password,password_strong,is_platform_admin,grant_binding_in_tx,revoke_sessions_in_tx,revoke_session_in_tx,issue_confirmation,consume_confirmation,data_scope_clause_in_tx,validate_role_permissions_in_tx,scope_mask_names,page_capabilities_from_profile,has_permission_in_any_scope
from V207_schema_catalog import build_schema_catalog
from V207_version import PRODUCT_VERSION,SCHEMA_VERSION
from V207_scope import resolve_scope, require_platform, require_account_grant
from V207_platform_service import handle as handle_platform
from V207_channel_service import handle as handle_channel
from V207_dict_service import handle_channel_type, handle_source_type
from V207_source_service import handle as handle_source
from V207_campaign_service import handle as handle_campaign
from V207_contact_identity_service import handle as handle_contact_identity
from V207_touchpoint_service import handle as handle_touchpoint
from V207_attribution_service import handle as handle_attribution
from V207_conversion_service import handle as handle_conversion
from V207_source_link_service import handle as handle_source_link
from V207_organization_service import handle as handle_organization_model
from V208_account_admin_service import handle as handle_account_admin
from V208_contact_center_service import handle as handle_contact_center
CHANNELS=('whatsapp','instagram','facebook','messenger','telegram')

def rows(c,sql,args=()): return [dict(x) for x in c.execute(sql,args)]
def one(c,sql,args=()):
 r=c.execute(sql,args).fetchone(); return dict(r) if r else None
def platform(db,a):
 # 平台级权限不得由企业角色隐式提升；仅内置系统管理员具备跨企业能力。
 return is_platform_admin(db,a)
def org_ok(db,a,org):return bool(org) and (platform(db,a) or org==a['organization_id'])
def manage(db,a,perm,org):return org_ok(db,a,org) and (platform(db,a) or can(db,a,perm))
def target(q,a,b=None):return str((b or {}).get('organizationId') or (b or {}).get('organization_id') or q.get('organizationId') or q.get('organization_id') or a['organization_id'])
def page(q):
 try:p=max(1,int(q.get('page',1)));size=min(200,max(1,int(q.get('pageSize',q.get('limit',50)))))
 except:p,size=1,50
 return p,size,(p-1)*size
def pack(items,total,p,size,**extra):return {'ok':True,'items':items,'pagination':{'page':p,'pageSize':size,'total':total,'pages':(total+size-1)//size},**extra}
import datetime
def fmt_ts(ts_ms):
 """将毫秒时间戳转为 YYYY/MM/DD HH:mm 格式。"""
 if not ts_ms:return ''
 try:
  return datetime.datetime.fromtimestamp(ts_ms/1000).strftime('%Y/%m/%d %H:%M')
 except Exception:
  return str(ts_ms)
def bad(h,code,msg,status=400):return h.sendj({'ok':False,'code':code,'message':msg},status) or True
def _audit_workspace(c,a,wid=None):
 if wid:
  row=c.execute("SELECT workspace_id FROM workspaces WHERE workspace_id=? AND organization_id=?",(wid,a['organization_id'])).fetchone()
  if row:return row[0]
 wid=default_workspace_id(c,a['organization_id'])
 if not wid:raise RuntimeError('AUDIT_SCOPE_REQUIRED')
 return wid
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

# 动态数据库预览安全策略。客户端只能提交由 sqlite_schema 发现的精确表名，不能提交 SQL。
_DB_RESTRICTED_TABLES={'user_credentials','sessions','rbac_confirmations','delete_confirmations'}
_DB_BLOCK_PARTS=('password','passwd','salt','secret','private_key','access_token','refresh_token','token_hash','token_digest','credential','authorization','otp','verification_code','recovery_code','api_key')
_DB_MASK_PARTS=('phone','mobile','email','ip_address','client_ip','identity_value','canonical_value','external_id','document_number','id_card','bank_account','address','account_identity')
_DB_CATEGORIES=(
 ('organization','组织与成员',('organization','workspace','department','team','position','business_line','market','membership')),
 ('identity','用户与身份',('user','contact','identity')),
 ('security','权限与安全',('role','permission','session','credential','confirmation','security','grant')),
 ('channel','渠道与来源',('platform','channel','source','device')),
 ('marketing','营销与活动',('campaign','touchpoint','attribution','event','change')),
 ('operations','审计与运维',('audit','migration','meta','config','tag','field')),
)
def _db_qi(name):return '"'+str(name).replace('"','""')+'"'
def _db_category(name):
 low=name.lower()
 for key,label,words in _DB_CATEGORIES:
  if any(word in low for word in words):return key,label
 return 'other','系统与其他'
def _db_tables(c):
 return [r[0] for r in c.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
def _db_columns(c,name):return [r[1] for r in c.execute('PRAGMA table_info('+_db_qi(name)+')')]
def _db_scope(columns,org):
 cs=set(columns)
 if 'organization_id' in cs:return _db_qi('organization_id')+'=?',[org],'organization_id',True
 # 仅使用服务端固定映射，绝不把请求内容拼入 SQL。
 links=(('workspace_id','workspaces','workspace_id'),('team_id','teams','team_id'),('user_id','users','user_id'),('actor_id','users','user_id'),('assigned_user_id','users','user_id'),('contact_id','contacts','contact_id'),('source_id','sources','source_id'),('channel_account_id','channel_accounts','channel_account_id'),('campaign_id','campaigns','campaign_id'))
 for col,parent,pk in links:
  if col in cs:return _db_qi(col)+' IN (SELECT '+_db_qi(pk)+' FROM '+_db_qi(parent)+' WHERE organization_id=?)',[org],col+'→organization_id',True
 if 'role_id' in cs:return _db_qi('role_id')+' IN (SELECT role_id FROM roles WHERE organization_id=?)',[org],'role_id→organization_id',True
 return '1=0',[],'未识别企业范围',False
def _db_field_mode(name):
 low=name.lower()
 if any(part in low for part in _DB_BLOCK_PARTS):return 'omit'
 if any(part in low for part in _DB_MASK_PARTS):return 'mask'
 return 'plain'
def _db_mask(name,value):
 if value is None:return None
 text=str(value)
 if not text:return text
 low=name.lower()
 if 'email' in low and '@' in text:
  left,right=text.split('@',1);return (left[:1] if left else '')+'***@'+right
 if 'ip' in low:
  parts=text.split('.')
  return '.'.join(parts[:2]+['*','*']) if len(parts)==4 else text[:3]+'***'
 if len(text)<=4:return '****'
 return text[:3]+'****'+text[-2:]
def _db_sanitize_json(value):
 if isinstance(value,dict):
  out={}
  for key,item in value.items():
   mode=_db_field_mode(str(key))
   if mode=='omit':continue
   out[key]=_db_mask(str(key),item) if mode=='mask' else _db_sanitize_json(item)
  return out
 if isinstance(value,list):return [_db_sanitize_json(item) for item in value]
 return value
def _db_sanitize_row(row):
 out={};masked=[];omitted=[]
 for key,value in row.items():
  mode=_db_field_mode(key)
  if mode=='omit':omitted.append(key);continue
  if mode=='mask':out[key]=_db_mask(key,value);masked.append(key);continue
  if isinstance(value,str) and (key.lower().endswith('_json') or key.lower() in ('payload','context','metadata')):
   try:out[key]=dumps(_db_sanitize_json(json.loads(value)))
   except Exception:out[key]=value
  else:out[key]=value
 return out,masked,omitted
def _db_policy(name,columns,scoped):
 low=name.lower()
 restricted=(not scoped) or low in _DB_RESTRICTED_TABLES or any(part in low for part in ('credential','session_token','api_key','secret_store'))
 modes={column:_db_field_mode(column) for column in columns}
 sensitive=restricted or any(mode!='plain' for mode in modes.values())
 return ('restricted' if restricted else ('masked' if sensitive else 'full')),modes

# ============================================================
# V208.2.0 Phase 3 — 客户运营工作台 (Workbench) scope 辅助
# ============================================================
def _ops_scope_clause(db,c,actor,allow_admin_bypass=True,org=None,alias=''):
 """Resolve contact.read scope; JOIN callers must identify the contacts alias."""
 org=org or actor.get('organization_id')
 clause,args,info=data_scope_clause_in_tx(c,actor,'contact.read',org,alias=alias,owner_column='owner_user_id',team_column='team_id',workspace_column='workspace_id')
 if not alias:
  clause=clause.replace('.owner_user_id','owner_user_id').replace('.team_id','team_id').replace('.workspace_id','workspace_id')
 level=info['level']
 return clause,args,{'user_id':actor.get('user_id'),'scope':('org' if level=='organization' else level),'level':level,'is_platform':level=='platform','team_ids':[x['scope_id'] for x in info['grants'] if x['scope_type']=='team']}

def _ops_limit(value, default=20, maximum=200):
 try:return max(1,min(int(value),maximum))
 except (TypeError,ValueError):return default

def _ops_day_start(now):
 # 管理中心当前部署时区：Asia/Shanghai (UTC+8)
 offset=8*3600000
 return ((now+offset)//86400000)*86400000-offset

def _ops_filter_clause(q, alias='', include_status=True):
 """Build one canonical workbench filter.

 Customer status is exclusively represented by status_tag_id.  Legacy
 contacts.status / contacts.stage values are deliberately not consulted here.
 """
 pre=(alias+'.') if alias else ''
 contact_ref=(pre+'contact_id') if pre else 'contacts.contact_id'
 clauses=[];params=[]
 workspace=str(q.get('workspace_id') or q.get('workspaceId') or '').strip()
 status_tag_id=str(q.get('status_tag_id') or '').strip()
 source=str(q.get('source') or '').strip()
 team=str(q.get('team') or '').strip()
 portrait=str(q.get('portrait') or '').strip()
 if workspace:clauses.append(pre+'workspace_id=?');params.append(workspace)
 if include_status and status_tag_id:
  clauses.append("EXISTS (SELECT 1 FROM contact_tags octs JOIN tags ots ON ots.tag_id=octs.tag_id WHERE octs.contact_id="+contact_ref+" AND ots.tag_kind='status' AND ots.enabled=1 AND ots.tag_id=?)");params.append(status_tag_id)
 if source:
  clauses.append(pre+'source_id IN (SELECT source_id FROM sources WHERE source_id=? OR source_name=?)');params.extend([source,source])
 if team:
  clauses.append(pre+'team_id IN (SELECT team_id FROM teams WHERE team_id=? OR name=?)');params.extend([team,team])
 if portrait:
  clauses.append("EXISTS (SELECT 1 FROM contact_tags oct JOIN tags ot ON ot.tag_id=oct.tag_id WHERE oct.contact_id="+contact_ref+" AND ot.name=? AND ot.tag_kind='portrait')");params.append(portrait)
 return ((' AND '+' AND '.join(clauses)) if clauses else ''),params

def dispatch(h,m,p,q,a,db):
 # Strip query string from path if not already separated
 if '?' in p and not q:
  from urllib.parse import urlparse, parse_qs
  up = urlparse(p)
  p = up.path
  q = {k: v[-1] for k, v in parse_qs(up.query).items()}
 if not p.startswith('/api/v207/admin/'):return False
 seg=[x for x in p[len('/api/v207/admin/'):].split('/') if x]
 if not seg:return bad(h,'NOT_FOUND','管理接口不存在',404)
 root=seg[0];ident=seg[1] if len(seg)>1 else None;action=seg[2] if len(seg)>2 else None
 org=target(q,a)
 if root=='contact-center':return handle_contact_center(h,m,seg,q,a,db,org)
 if handle_account_admin(h,m,root,ident,action,q,a,db,manage,org):return True
 # [Stage3] 权限矩阵聚合（只读）
 if root=='rbac' and ident=='matrix' and m=='GET':
  org=target(q,a);is_pa=platform(db,a)
  if not (is_pa or can(db,a,'permission.read',organization_id=org)):return bad(h,'FORBIDDEN','无权限矩阵读取权限',403)
  with db.tx(False) as c:
   n=now_ms();roles=rows(c,"SELECT r.*,group_concat(rp.permission_key) permissions,(SELECT count(DISTINCT b.user_id) FROM role_bindings b WHERE b.role_id=r.role_id AND (b.organization_id=? OR b.organization_id IS NULL) AND b.status='active' AND (b.valid_from IS NULL OR b.valid_from<=?) AND (b.expires_at IS NULL OR b.expires_at>?)) member_count FROM roles r LEFT JOIN role_permissions rp ON rp.role_id=r.role_id WHERE r.organization_id=? OR r.organization_id IS NULL GROUP BY r.role_id ORDER BY r.is_system DESC,r.name",(org,n,n,org));perms=rows(c,"SELECT * FROM permissions ORDER BY permission_key");binds=rows(c,"SELECT rp.role_id,rp.permission_key FROM role_permissions rp JOIN roles r ON r.role_id=rp.role_id WHERE r.organization_id=? OR r.organization_id IS NULL",(org,))
  caps={'read':True,'editEnterpriseRoles':bool(is_pa or can(db,a,'permission.manage',organization_id=org) or can(db,a,'role.manage',organization_id=org)),'maintainSystemTemplates':bool(is_pa and can(db,a,'role.template.manage',organization_id=org)),'grantBindings':bool(is_pa or can(db,a,'role.binding.manage',organization_id=org) or can(db,a,'role.manage',organization_id=org)),'export':True}
  return h.sendj({'ok':True,'roles':roles,'permissions':perms,'bindings':binds,'capabilities':caps}) or True
 if root=='users' and ident and action=='permission-sources' and m=='GET':
  org=target(q,a)
  if not (platform(db,a) or can(db,a,'permission.read',organization_id=org)):return bad(h,'FORBIDDEN','无权限读取权限',403)
  with db.tx(False) as c:
   direct=rows(c,"SELECT b.binding_id,b.role_id,r.name role_name,r.role_code,r.scope_level,b.scope_type,COALESCE(b.scope_id,'') scope_id,b.status,r.status role_status,b.valid_from,b.expires_at,b.grant_reason,b.grant_type,b.approved_by FROM role_bindings b JOIN roles r ON r.role_id=b.role_id WHERE b.user_id=? AND (b.organization_id=? OR b.organization_id IS NULL) AND b.status='active' AND r.status='active' AND (b.valid_from IS NULL OR b.valid_from<=?) AND (b.expires_at IS NULL OR b.expires_at>?)",(ident,org,now_ms(),now_ms()))
   inherited=rows(c,"SELECT tm.team_id,t.name team_name,tm.membership_type,tm.is_primary,tm.status FROM team_memberships tm JOIN teams t ON t.team_id=tm.team_id WHERE tm.user_id=? AND t.organization_id=? AND tm.status='active' AND t.status='active'",(ident,org))
   channel=rows(c,"SELECT (g.user_id || ':' || g.channel_account_id) grant_id,g.channel_account_id,COALESCE(ca.display_name,'已删除账号') account_name,'active' status,g.permission_scope,COALESCE(ca.status,'deleted') account_status FROM user_channel_account_grants g LEFT JOIN channel_accounts ca ON ca.channel_account_id=g.channel_account_id WHERE g.user_id=?",(ident,))
  profile=authorization_profile(db,ident)
  sensitive={'role.manage','user.manage','permission.manage','audit.read','contact.delete','contact.merge','conversion.manage','transfer.manage'}
  conflicts=[]
  effective=set(profile['permissions'])
  if 'contact.delete' in effective and 'audit.read' in effective:conflicts.append('同一用户同时拥有客户删除与审计读取权限，请复核职责分离。')
  if 'role.manage' in effective and 'user.manage' in effective:conflicts.append('同一用户同时拥有角色管理与用户管理权限，属于高权组合。')
  return h.sendj({'ok':True,'direct':direct,'inherited':inherited,'channel':channel,'effectivePermissions':sorted(effective),'effectiveScopes':profile['effective_scopes'],'highRiskPermissions':sorted(effective & sensitive),'conflictWarnings':conflicts}) or True

 # session/security
 if root=='profile' and m=='GET':
  auth=authorization_profile(db,a['user_id'])
  with db.tx(False) as c:
   org=one(c,'SELECT * FROM organizations WHERE organization_id=?',(a['organization_id'],));cr=one(c,'SELECT must_change,updated_at FROM user_credentials WHERE user_id=?',(a['user_id'],));pa=one(c,'SELECT is_builtin,onboarding_completed FROM platform_administrators WHERE user_id=?',(a['user_id'],))
   workspaces=rows(c,"SELECT DISTINCT w.* FROM workspaces w LEFT JOIN teams t ON t.workspace_id=w.workspace_id LEFT JOIN team_memberships tm ON tm.team_id=t.team_id AND tm.user_id=? AND tm.status='active' WHERE w.organization_id=? AND w.status='active' AND (? OR tm.user_id IS NOT NULL OR EXISTS(SELECT 1 FROM role_bindings b WHERE b.user_id=? AND b.status='active' AND (b.valid_from IS NULL OR b.valid_from<=?) AND (b.expires_at IS NULL OR b.expires_at>?) AND (b.scope_type='organization' OR (b.scope_type='workspace' AND b.scope_id=w.workspace_id)))) ORDER BY CASE w.workspace_id WHEN 'ws-global' THEN 0 ELSE 1 END,w.created_at",(a['user_id'],a['organization_id'],1 if pa else 0,a['user_id'],now_ms(),now_ms()))
   teams=rows(c,"SELECT DISTINCT t.* FROM teams t LEFT JOIN team_memberships tm ON tm.team_id=t.team_id AND tm.user_id=? AND tm.status='active' WHERE t.organization_id=? AND t.status='active' AND (? OR tm.user_id IS NOT NULL OR EXISTS(SELECT 1 FROM role_bindings b WHERE b.user_id=? AND b.status='active' AND (b.valid_from IS NULL OR b.valid_from<=?) AND (b.expires_at IS NULL OR b.expires_at>?) AND (b.scope_type='organization' OR (b.scope_type='workspace' AND b.scope_id=t.workspace_id) OR (b.scope_type='team' AND b.scope_id=t.team_id)))) ORDER BY t.created_at",(a['user_id'],a['organization_id'],1 if pa else 0,a['user_id'],now_ms(),now_ms()))
   departments=rows(c,"SELECT d.department_id,d.name FROM departments d JOIN positions p ON p.department_id=d.department_id JOIN user_positions up ON up.position_id=p.position_id WHERE up.user_id=? AND up.status='active' AND d.status='active'",(a['user_id'],))
  return h.sendj({'ok':True,'user':{k:a[k] for k in ('user_id','login_name','display_name','organization_id')},'organization':org,'platformAdmin':bool(pa),'permissions':sorted(auth['permissions']),'roles':auth['roles'],'effectiveScopes':auth['effective_scopes'],'pageCapabilities':page_capabilities_from_profile(auth,bool(pa)),'memberships':{'workspaces':workspaces,'teams':teams,'departments':departments},'credential':cr,'platformIdentity':pa,'onboardingRequired':bool(pa and not pa['onboarding_completed']),'workspace':workspaces[0] if workspaces else None,'team':teams[0] if teams else None}) or True

 # ============================================================
 # V208.2.0 Phase 3 — 客户运营工作台 API
 # ============================================================
 # GET /api/v207/admin/workbench/me
 if root=='workbench' and ident=='me' and m=='GET':
  if not (platform(db,a) or has_permission_in_any_scope(db,a,'contact.read',a['organization_id'])):return bad(h,'FORBIDDEN','无权限',403)
  uid=a['user_id']
  with db.tx(False) as c:
   user=one(c,'SELECT user_id,login_name,display_name,status FROM users WHERE user_id=?',(uid,))
   org_info=one(c,'SELECT organization_id,name FROM organizations WHERE organization_id=?',(a['organization_id'],))
   team_rows=c.execute(
    "SELECT t.team_id,t.name FROM teams t JOIN team_memberships tm ON tm.team_id=t.team_id WHERE tm.user_id=? AND tm.status='active' AND t.status='active'",
    (uid,)
   ).fetchall()
   teams=[{'team_id':r[0],'name':r[1]} for r in team_rows]
   is_manager=bool(c.execute(
    "SELECT 1 FROM team_memberships WHERE user_id=? AND membership_type='manager' AND status='active' LIMIT 1",
    (uid,)
   ).fetchone())
   ws_rows=c.execute(
    "SELECT workspace_id,name FROM workspaces WHERE organization_id=? AND status='active' ORDER BY CASE workspace_id WHEN 'ws-global' THEN 0 ELSE 1 END, created_at",
    (a['organization_id'],)
   ).fetchall()
   workspaces=[{'workspace_id':r[0],'name':r[1]} for r in ws_rows]
   default_ws=ws_rows[0] if ws_rows else None
   scope_info=_ops_scope_clause(db,c,a,allow_admin_bypass=True,org=a['organization_id'])
  return h.sendj({
   'ok':True,
   'actor':{'user_id':uid,'login_name':user['login_name'],'display_name':user['display_name']} if user else None,
   'organization':org_info,
   'workspace':{'workspace_id':default_ws[0],'name':default_ws[1]} if default_ws else None,
   'workspaces':workspaces,
   'teams':teams,
   'isManager':is_manager,
   'scope':scope_info[2],
  }) or True

 # GET /api/v207/admin/workbench/kpis
 if root=='workbench' and ident=='kpis' and m=='GET':
  if not (platform(db,a) or has_permission_in_any_scope(db,a,'contact.read',a['organization_id'])):return bad(h,'FORBIDDEN','无权限',403)
  org=a['organization_id'];now=now_ms();day_start=_ops_day_start(now);day_end=day_start+86400000
  prev_day_start=day_start-86400000;week_start=day_start-6*86400000;prev_week_start=week_start-7*86400000
  with db.tx(False) as c:
   wc,wp,scope_info=_ops_scope_clause(db,c,a,True,org);fc,fp=_ops_filter_clause(q)
   base=f"SELECT count(*) FROM contacts WHERE organization_id=? AND deleted_at IS NULL AND {wc}{fc}";args=[org]+wp+fp
   def count_time(field,start,end):return c.execute(f"{base} AND {field}>=? AND {field}<?",args+[start,end]).fetchone()[0]
   today_queue=count_time('next_follow_up_at',day_start,day_end);prev_today_queue=count_time('next_follow_up_at',prev_day_start,day_start)
   marked_sql=" AND EXISTS (SELECT 1 FROM contact_tags mct JOIN tags mt ON mt.tag_id=mct.tag_id WHERE mct.contact_id=contacts.contact_id AND mt.tag_kind='status' AND mt.enabled=1)"
   marked_customers=c.execute(base+marked_sql,args).fetchone()[0]
   queue_trend=[];marked_trend=[];chat_trend=[];new_trend=[]
   for i in range(7):
    ds=day_start-(6-i)*86400000;de=ds+86400000
    queue_trend.append(count_time('next_follow_up_at',ds,de))
    marked_trend.append(c.execute(base+marked_sql+" AND updated_at>=? AND updated_at<?",args+[ds,de]).fetchone()[0])
    chat_trend.append(count_time('last_touch_at',ds,de));new_trend.append(count_time('created_at',ds,de))
   today_chats=chat_trend[-1];prev_today_chats=count_time('last_touch_at',prev_day_start,day_start)
   week_new=sum(new_trend);prev_week_new=count_time('created_at',prev_week_start,week_start)
  return h.sendj({'ok':True,'scope':scope_info,'cards':{
   'todayQueue':{'value':today_queue,'delta':today_queue-prev_today_queue,'vs':'yesterday','trend':queue_trend},
   'statusTagged':{'value':marked_customers,'delta':marked_trend[-1]-(sum(marked_trend[:-1])//6 if len(marked_trend)>1 else 0),'vs':'7d_avg','trend':marked_trend},
   'todayChats':{'value':today_chats,'delta':today_chats-prev_today_chats,'vs':'yesterday','trend':chat_trend},
   'weekNew':{'value':week_new,'delta':week_new-prev_week_new,'vs':'last_week','trend':new_trend}},'staleSeconds':30}) or True

 # GET /api/v207/admin/workbench/queue
 if root=='workbench' and ident=='queue' and m=='GET':
  if not (platform(db,a) or has_permission_in_any_scope(db,a,'contact.read',a['organization_id'])):return bad(h,'FORBIDDEN','无权限',403)
  org=a['organization_id'];bucket=str(q.get('bucket','today'));now=now_ms();day_start=_ops_day_start(now);day_end=day_start+86400000
  buckets={'today':(day_start,day_end),'tomorrow':(day_end,day_end+86400000),'overdue':(0,day_start),'upcoming':(day_end+86400000,day_start+4*86400000)}
  if bucket not in buckets:bucket='today'
  with db.tx(False) as c:
   wc,wp,scope_info=_ops_scope_clause(db,c,a,True,org);fc,fp=_ops_filter_clause(q);base=f"organization_id=? AND deleted_at IS NULL AND {wc}{fc}";args=[org]+wp+fp
   counts={}
   for key,(lo,hi) in buckets.items():counts[key]=c.execute(f"SELECT count(*) FROM contacts WHERE {base} AND next_follow_up_at>=? AND next_follow_up_at<?",args+[lo,hi]).fetchone()[0]
   lo,hi=buckets[bucket];limit=_ops_limit(q.get('limit'),50,200)
   rs=c.execute(f"SELECT contact_id,COALESCE(NULLIF(trim(manual_name),''),display_name) name,next_follow_up_at,status,last_touch_at FROM contacts WHERE {base} AND next_follow_up_at>=? AND next_follow_up_at<? ORDER BY next_follow_up_at LIMIT ?",args+[lo,hi,limit]).fetchall()
   items=[]
   for r in rs:
    name=r[1] or '未知客户';tag_rows=c.execute("SELECT t.name,t.tag_kind FROM tags t JOIN contact_tags ct ON ct.tag_id=t.tag_id WHERE ct.contact_id=? AND t.enabled=1 ORDER BY CASE t.tag_kind WHEN 'status' THEN 0 ELSE 1 END,t.sort_order,t.name LIMIT 4",(r[0],)).fetchall();tags=[x[0] for x in tag_rows];status_tag=next((x[0] for x in tag_rows if x[1]=='status'),'')
    items.append({'id':r[0],'name':name,'avatar':name[:1] or '?','meta':((' · '.join(tags)) if tags else '未设置客户状态'),'when':fmt_ts(r[2]),'daysOverdue':max(0,(now-r[2])//86400000) if bucket=='overdue' else 0,'tags':tags,'stage':status_tag,'statusTag':status_tag,'systemStatus':r[3] or 'active','lastTouchAt':r[4],'queueBucket':bucket})
  return h.sendj({'ok':True,'bucket':bucket,'counts':counts,'items':items,'scope':scope_info,'staleSeconds':30}) or True

 # GET /api/v207/admin/workbench/funnel
 if root=='workbench' and ident=='funnel' and m=='GET':
  if not (platform(db,a) or has_permission_in_any_scope(db,a,'contact.read',a['organization_id'])):return bad(h,'FORBIDDEN','无权限',403)
  org=a['organization_id'];now=now_ms();day_start=_ops_day_start(now)
  selected_status=str(q.get('status_tag_id') or '').strip()
  with db.tx(False) as c:
   wc,wp,scope_info=_ops_scope_clause(db,c,a,True,org)
   # 漏斗卡片使用公共筛选（工作区/团队/来源/画像），状态维度单独计算，
   # 避免把选中的状态先写进 base 后又与每张卡片状态重复相交。
   common_q=dict(q);common_q.pop('status_tag_id',None)
   fc,fp=_ops_filter_clause(common_q,include_status=False)
   base=f"organization_id=? AND deleted_at IS NULL AND {wc}{fc}";args=[org]+wp+fp
   workspace=str(q.get('workspace_id') or q.get('workspaceId') or '').strip()
   tag_sql="SELECT tag_id,name,color,sort_order FROM tags WHERE tag_kind='status' AND enabled=1";tag_args=[]
   if workspace:tag_sql+=" AND (workspace_id=? OR workspace_id IS NULL)";tag_args.append(workspace)
   tag_sql+=' ORDER BY sort_order,name,tag_id';status_tags=c.execute(tag_sql,tag_args).fetchall();funnel=[]
   selected_tag=None
   if selected_status:
    selected_tag=c.execute("SELECT tag_id FROM tags WHERE tag_kind='status' AND enabled=1 AND tag_id=? LIMIT 1",(selected_status,)).fetchone()
    selected_tag=selected_tag[0] if selected_tag else selected_status
   for tag in status_tags:
    is_selected=bool(selected_tag and str(tag[0])==str(selected_tag))
    tagged=" AND EXISTS (SELECT 1 FROM contact_tags fct WHERE fct.contact_id=contacts.contact_id AND fct.tag_id=?)"
    cnt=c.execute(f"SELECT count(*) FROM contacts WHERE {base}{tagged}",args+[tag[0]]).fetchone()[0]
    week_cnt=c.execute(f"SELECT count(*) FROM contacts WHERE {base}{tagged} AND updated_at>=?",args+[tag[0],day_start-6*86400000]).fetchone()[0]
    funnel.append({'key':tag[0],'tagId':tag[0],'label':tag[1],'color':tag[2],'sortOrder':tag[3],'count':cnt,'delta':week_cnt,'selected':is_selected})
   # 趋势及看板其他模块都使用完整筛选（含选中状态）。
   full_fc,full_fp=_ops_filter_clause(q);full_base=f"organization_id=? AND deleted_at IS NULL AND {wc}{full_fc}";full_args=[org]+wp+full_fp
   trend=[]
   for i in range(7):
    ds=day_start-(6-i)*86400000;de=ds+86400000
    trend.append(c.execute(f"SELECT count(*) FROM contacts WHERE {full_base} AND updated_at>=? AND updated_at<?",full_args+[ds,de]).fetchone()[0])
  return h.sendj({'ok':True,'funnel':funnel,'trend7d':trend,'scope':scope_info,'staleSeconds':60,'filterStatusTagId':selected_tag or ''}) or True

 # Workbench insights
 if root=='workbench' and ident=='insights' and action in ('new-customers','upcoming-due','communication-pulse') and m=='GET':
  if not (platform(db,a) or has_permission_in_any_scope(db,a,'contact.read',a['organization_id'])):return bad(h,'FORBIDDEN','无权限',403)
  org=a['organization_id'];now=now_ms();limit=_ops_limit(q.get('limit'),20,100)
  with db.tx(False) as c:
   wc,wp,scope_info=_ops_scope_clause(db,c,a,True,org,alias='c');fc,fp=_ops_filter_clause(q,'c');base=f"c.organization_id=? AND c.deleted_at IS NULL AND {wc}{fc}";args=[org]+wp+fp
   if action=='new-customers':
    rs=c.execute(f"SELECT c.contact_id,COALESCE(NULLIF(trim(c.manual_name),''),c.display_name) name,c.created_at FROM contacts c WHERE {base} AND c.created_at>=? ORDER BY c.created_at DESC LIMIT ?",args+[now-7*86400000,limit]).fetchall();items=[]
    for r in rs:
     tag=c.execute("SELECT t.name FROM tags t JOIN contact_tags ct ON ct.tag_id=t.tag_id WHERE ct.contact_id=? LIMIT 1",(r[0],)).fetchone();diff=max(0,now-(r[2] or now));when='刚刚' if diff<60000 else ((str(diff//60000)+' 分钟前') if diff<3600000 else ((str(diff//3600000)+' 小时前') if diff<86400000 else (str(diff//86400000)+' 天前')));items.append({'id':r[0],'name':r[1] or '未知客户','tag':tag[0] if tag else '','when':when,'createdAt':r[2]})
    return h.sendj({'ok':True,'items':items,'scope':scope_info,'staleSeconds':120}) or True
   if action=='upcoming-due':
    rs=c.execute(f"SELECT c.contact_id,COALESCE(NULLIF(trim(c.manual_name),''),c.display_name) name,c.next_follow_up_at,(SELECT st.name FROM contact_tags sct JOIN tags st ON st.tag_id=sct.tag_id WHERE sct.contact_id=c.contact_id AND st.tag_kind='status' AND st.enabled=1 LIMIT 1) status_tag FROM contacts c WHERE {base} AND c.next_follow_up_at>? AND c.next_follow_up_at<=? ORDER BY c.next_follow_up_at LIMIT ?",args+[now,now+3*86400000,limit]).fetchall()
    items=[{'id':r[0],'name':r[1] or '未知客户','when':fmt_ts(r[2]),'stage':r[3] or '','statusTag':r[3] or ''} for r in rs]
    return h.sendj({'ok':True,'items':items,'scope':scope_info,'staleSeconds':60}) or True
   # 近24小时真实消息脉搏，4小时一个点
   series=[];wa_total=tg_total=0
   for i in range(6):
    lo=now-(6-i)*4*3600000;hi=lo+4*3600000
    rs=c.execute(f"SELECT lower(COALESCE(c.channel,'')) channel,count(*) n FROM conversation_messages m JOIN contacts c ON c.contact_id=m.contact_id WHERE {base} AND m.occurred_at>=? AND m.occurred_at<? AND m.deleted_at IS NULL GROUP BY channel",args+[lo,hi]).fetchall();wa=sum(r[1] for r in rs if 'whatsapp' in r[0] or r[0]=='wa');tg=sum(r[1] for r in rs if 'telegram' in r[0] or r[0]=='tg');wa_total+=wa;tg_total+=tg;series.append({'at':lo,'whatsapp':wa,'telegram':tg})
   return h.sendj({'ok':True,'series':series,'totals':{'whatsapp':wa_total,'telegram':tg_total},'scope':scope_info,'staleSeconds':30}) or True

 # GET /api/v207/admin/workbench/quick-filters (级联：每个维度排除自身、保留其他条件)
 if root=='workbench' and ident=='quick-filters' and m=='GET':
  if not (platform(db,a) or has_permission_in_any_scope(db,a,'contact.read',a['organization_id'])):return bad(h,'FORBIDDEN','无权限',403)
  org=a['organization_id']
  with db.tx(False) as c:
   scope_wc,wp,scope_info=_ops_scope_clause(db,c,a,True,org,alias='c')
   def option_base(exclude=None):
    oq=dict(q);oq.pop(exclude,None)
    fc,fp=_ops_filter_clause(oq,'c')
    return f"c.organization_id=? AND c.deleted_at IS NULL AND {scope_wc}{fc}",[org]+wp+fp
   mb,ma=option_base();matching=c.execute(f"SELECT count(*) FROM contacts c WHERE {mb}",ma).fetchone()[0]
   pb,pa=option_base('portrait');portraits=rows(c,f"SELECT DISTINCT t.name FROM contacts c JOIN contact_tags ct ON ct.contact_id=c.contact_id JOIN tags t ON t.tag_id=ct.tag_id WHERE {pb} AND t.tag_kind='portrait' ORDER BY t.name LIMIT 20",pa)
   sb,sa=option_base('status_tag_id');statuses=rows(c,f"SELECT DISTINCT st.tag_id id,st.name FROM contacts c JOIN contact_tags sct ON sct.contact_id=c.contact_id JOIN tags st ON st.tag_id=sct.tag_id WHERE {sb} AND st.tag_kind='status' AND st.enabled=1 ORDER BY st.sort_order,st.name",sa)
   ob,oa=option_base('source');sources=rows(c,f"SELECT DISTINCT s.source_id id,s.source_name name FROM contacts c JOIN sources s ON s.source_id=c.source_id WHERE {ob} ORDER BY s.source_name LIMIT 20",oa)
   tb,ta=option_base('team');teams=rows(c,f"SELECT DISTINCT t.team_id id,t.name FROM contacts c JOIN teams t ON t.team_id=c.team_id WHERE {tb} ORDER BY t.name LIMIT 20",ta)
  return h.sendj({'ok':True,'portraits':[x['name'] for x in portraits],'statuses':statuses,'sources':sources,'teams':teams,'matchingCount':matching,'scope':scope_info}) or True

 # ============================================================
 # Phase B-2 — 清单写入操作 + 抽屉置顶 (audit-first)
 # 所有写操作只对 actor 自己负责的 contacts 生效，
 # 即 scope 二次过滤；组织超管允许跨团队（受 allow_admin_bypass=True 控制）
 # ============================================================

 # POST /api/v207/admin/workbench/queue/{id}/done
 # PATCH /api/v207/admin/workbench/queue/{id}/done   (兼容两种方法)
 # seg 形态: ['workbench','queue','ct_xxx','done']
 if root=='workbench' and ident=='queue' and m in ('POST','PATCH') and '/'.join(seg[2:]).endswith('/done'):
  cid='/'.join(seg[2:])[:-5]
  if not cid:return bad(h,'INVALID_CONTACT','客户 ID 不能为空')
  if not manage(db,a,'contact.update',a['organization_id']):return bad(h,'FORBIDDEN','无联系人修改权限',403)
  b=h.body()
  reason=str(b.get('reason') or '').strip()
  if not reason:return bad(h,'REASON_REQUIRED','请填写完成原因（审计必填）',400)
  if len(reason)>500:return bad(h,'REASON_TOO_LONG','原因不能超过 500 字符',400)
  now=now_ms()
  with db.tx() as c:
   scope=_ops_scope_clause(db,c,a,allow_admin_bypass=True,org=a['organization_id'])
   wc,wp,_=scope
   contact=c.execute(
    f"SELECT contact_id,workspace_id,manual_name,display_name,stage,status,next_follow_up_at FROM contacts WHERE organization_id=? AND deleted_at IS NULL AND contact_id=? AND {wc}",
    [a['organization_id'], cid]+wp
   ).fetchone()
   if not contact:return bad(h,'NOT_FOUND','联系人不存在或不在你的范围内',404)
   old=dict(contact)
   from V208_follow_up_notification_service import complete_follow_up_in_tx
   completed=complete_follow_up_in_tx(c,cid,now,a.get('user_id'),None,'workbench',{'note':reason,'source':'workbench.queue.done'})
   if not completed:
    c.execute('UPDATE contacts SET next_follow_up_at=NULL,updated_at=?,version=version+1 WHERE contact_id=?',(now,cid))
   audit_in_tx(c,a,'workbench.queue.done','contact',cid,old,{
    'stage':contact['stage'],'contact_id':cid,'reason':reason,
    'nextFollowUpBefore':contact['next_follow_up_at'],'nextFollowUpAfter':None,
   },reason,contact['workspace_id'])
  return h.sendj({'ok':True,'contactId':cid,'bucket':'today','action':'done','appliedAt':now}) or True

 # POST /api/v207/admin/workbench/queue/{id}/snooze
 # PATCH /api/v207/admin/workbench/queue/{id}/snooze
 if root=='workbench' and ident=='queue' and m in ('POST','PATCH') and '/'.join(seg[2:]).endswith('/snooze'):
  cid='/'.join(seg[2:])[:-7]
  if not cid:return bad(h,'INVALID_CONTACT','客户 ID 不能为空')
  if not manage(db,a,'contact.update',a['organization_id']):return bad(h,'FORBIDDEN','无联系人修改权限',403)
  b=h.body()
  until_raw=b.get('until')
  if until_raw is None:return bad(h,'UNTIL_REQUIRED','推迟目标日期必填（ISO date 或 ms 时间戳）',400)
  reason=str(b.get('reason') or '').strip()
  if not reason:return bad(h,'REASON_REQUIRED','请填写推迟原因（审计必填）',400)
  if len(reason)>500:return bad(h,'REASON_TOO_LONG','原因不能超过 500 字符',400)
  until=None
  if isinstance(until_raw,(int,float)):
   until=int(until_raw)
  else:
   s=str(until_raw).strip()
   import datetime as _dt
   for fmt in ('%Y-%m-%d','%Y-%m-%dT%H:%M','%Y-%m-%dT%H:%M:%S','%Y-%m-%d %H:%M'):
    try:
     d=_dt.datetime.strptime(s,fmt);until=int(d.timestamp()*1000);break
    except ValueError:pass
  if not until:return bad(h,'INVALID_UNTIL','until 参数格式无法识别',400)
  now=now_ms()
  if until<=now:return bad(h,'UNTIL_IN_PAST','推迟目标必须在未来',400)
  if until-now>30*86400000:return bad(h,'UNTIL_OUT_OF_RANGE','推迟范围 1-30 天',400)
  target_until=until
  with db.tx() as c:
   scope=_ops_scope_clause(db,c,a,allow_admin_bypass=True,org=a['organization_id'])
   wc,wp,_=scope
   contact=c.execute(
    f"SELECT contact_id,workspace_id,manual_name,display_name,stage,status,next_follow_up_at FROM contacts WHERE organization_id=? AND deleted_at IS NULL AND contact_id=? AND {wc}",
    [a['organization_id'], cid]+wp
   ).fetchone()
   if not contact:return bad(h,'NOT_FOUND','联系人不存在或不在你的范围内',404)
   old=dict(contact)
   c.execute(
    'UPDATE contacts SET next_follow_up_at=?,updated_at=?,version=version+1 WHERE contact_id=?',
    (target_until,now,cid)
   )
   # Keep queue snooze and reminder plans atomic; SELECT * supplies all snapshot fields.
   from V208_follow_up_notification_service import sync_follow_up_plan_in_tx
   updated_contact=dict(c.execute('SELECT * FROM contacts WHERE contact_id=?',(cid,)).fetchone())
   sync_follow_up_plan_in_tx(c,updated_contact,target_until,reason,a.get('user_id'),now)
   audit_in_tx(c,a,'workbench.queue.snooze','contact',cid,old,{
    'until':target_until,'reason':reason,'contact_id':cid,
    'nextFollowUpBefore':contact['next_follow_up_at'],'nextFollowUpAfter':target_until,
   },reason,contact['workspace_id'])
  return h.sendj({'ok':True,'contactId':cid,'action':'snooze','until':target_until,'appliedAt':now}) or True

 # POST /api/v207/admin/workbench/drawer/{contactId}/pin
 if root=='workbench' and ident=='drawer' and m=='POST' and '/'.join(seg[2:]).endswith('/pin'):
  cid='/'.join(seg[2:])[:-4]
  if not cid:return bad(h,'INVALID_CONTACT','客户 ID 不能为空')
  if not manage(db,a,'contact.update',a['organization_id']):return bad(h,'FORBIDDEN','无联系人修改权限',403)
  b=h.body()
  pin_type=str(b.get('type') or 'personal').lower()
  if pin_type not in ('personal','team','unpin'):return bad(h,'INVALID_PIN_TYPE','type 仅支持 personal/team/unpin',400)
  now=now_ms()
  with db.tx() as c:
   scope=_ops_scope_clause(db,c,a,allow_admin_bypass=True,org=a['organization_id'])
   wc,wp,_=scope
   contact=c.execute(
    f"SELECT contact_id,workspace_id FROM contacts WHERE organization_id=? AND deleted_at IS NULL AND contact_id=? AND {wc}",
    [a['organization_id'], cid]+wp
   ).fetchone()
   if not contact:return bad(h,'NOT_FOUND','联系人不存在或不在你的范围内',404)
   if pin_type=='unpin':
    # 取消置顶：删除 actor 自己对该 contact 的 pin 行
    deleted=c.execute(
     "DELETE FROM user_dashboard_pins WHERE user_id=? AND pin_key LIKE ?",
     (a['user_id'],f'contact:{cid}:%')
    ).rowcount
    after={'type':None,'pin_key':None,'deleted':deleted}
    action='workbench.drawer.unpin'
   else:
    pin_key=f'contact:{cid}:{pin_type}'
    # INSERT OR REPLACE 幂等
    c.execute(
     'INSERT OR REPLACE INTO user_dashboard_pins(user_id,pin_key,pinned_at) VALUES(?,?,?)',
     (a['user_id'],pin_key,now)
    )
    after={'type':pin_type,'pin_key':pin_key}
    action=f'workbench.drawer.pin.{pin_type}'
   audit_in_tx(c,a,action,'contact',cid,{},after,'workbench drawer pin',contact['workspace_id'])
  return h.sendj({'ok':True,'contactId':cid,'pin':after,'appliedAt':now}) or True

 # POST /api/v207/admin/workbench/filter/applied
 # 用于记录过滤器切换行为，提供 audit 和分析依据
 if root=='workbench' and ident=='filter' and action=='applied' and m=='POST':
  b=h.body()
  filters=b.get('filters') or {}
  if not isinstance(filters,dict):return bad(h,'INVALID_INPUT','filters 必须是对象',400)
  with db.tx() as c:
   workspace=default_workspace_id(c,a['organization_id'])
   audit_in_tx(c,a,'workbench.filter.applied','workbench_session',a['user_id'],{},{'filters':filters},None,workspace)
  return h.sendj({'ok':True,'recordedAt':now_ms()}) or True

 # POST /api/v207/admin/workbench/scope/changed
 if root=='workbench' and ident=='scope' and action=='changed' and m=='POST':
  b=h.body()
  new_workspace=str(b.get('workspaceId') or '').strip()
  if not new_workspace:return bad(h,'WORKSPACE_REQUIRED','workspaceId 必填',400)
  if not manage(db,a,'contact.read',a['organization_id']):return bad(h,'FORBIDDEN','无权限',403)
  with db.tx() as c:
   ws=c.execute(
    "SELECT workspace_id FROM workspaces WHERE workspace_id=? AND organization_id=? AND status='active'",
    (new_workspace,a['organization_id'])
   ).fetchone()
   if not ws:return bad(h,'WORKSPACE_NOT_FOUND','工作区不存在',404)
   workspace=new_workspace
   audit_in_tx(c,a,'workbench.scope.changed','workbench_session',a['user_id'],{},{'workspace_id':new_workspace,'organization_id':a['organization_id']},None,workspace)
  return h.sendj({'ok':True,'workspaceId':new_workspace,'appliedAt':now_ms()}) or True

 # GET /api/v207/admin/workbench/drawer/pins
 # 抽屉内读取当前用户的 pin 列表（用于『我钉的』chip）
 if root=='workbench' and ident=='drawer' and action=='pins' and m=='GET':
  if not (platform(db,a) or has_permission_in_any_scope(db,a,'contact.read',a['organization_id'])):return bad(h,'FORBIDDEN','无权限',403)
  with db.tx(False) as c:
   pin_rows=c.execute(
    "SELECT pin_key,pinned_at FROM user_dashboard_pins WHERE user_id=? AND pin_key LIKE 'contact:%' ORDER BY pinned_at DESC LIMIT 50",
    (a['user_id'],)
   ).fetchall()
  pins=[]
  for r in pin_rows:
   k=str(r[0])
   # 格式: contact:ct_xxx:personal|team
   parts=k.split(':')
   if len(parts)>=3:
    pins.append({'contactId':parts[1],'type':parts[2],'pinnedAt':r[1]})
  return h.sendj({'ok':True,'pins':pins,'scope':{'user_id':a['user_id']}}) or True

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
   w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? ORDER BY CASE workspace_id WHEN 'ws-global' THEN 0 ELSE 1 END, created_at, workspace_id LIMIT 1",(a['organization_id'],)).fetchone()
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
  if ident and m=='DELETE':
   if not platform(db,a):return bad(h,'FORBIDDEN','仅平台超级管理员可删除企业',403)
   with db.tx() as c:
    old=one(c,'SELECT * FROM organizations WHERE organization_id=?',(ident,))
    if not old:return bad(h,'NOT_FOUND','企业不存在',404)
    refs={'users':c.execute('SELECT count(*) FROM users WHERE organization_id=?',(ident,)).fetchone()[0],'workspaces':c.execute('SELECT count(*) FROM workspaces WHERE organization_id=?',(ident,)).fetchone()[0],'teams':c.execute('SELECT count(*) FROM teams WHERE organization_id=?',(ident,)).fetchone()[0],'channels':c.execute('SELECT count(*) FROM channel_accounts WHERE organization_id=?',(ident,)).fetchone()[0],'contacts':c.execute('SELECT count(*) FROM contacts WHERE organization_id=?',(ident,)).fetchone()[0]}
    refs={k:v for k,v in refs.items() if v}
    if refs:return bad(h,'ORG_IN_USE','企业仍被业务对象引用，无法删除',409,references=refs)
    c.execute('DELETE FROM organizations WHERE organization_id=?',(ident,))
    audit_in_tx(c,a,'delete','organization',ident,old,{})
   return h.sendj({'ok':True}) or True
# common organization scope
 org=target(q,a)
 if not org_ok(db,a,org):return bad(h,'FORBIDDEN','无权访问目标企业',403)
 if root=='rbac' and ident=='changes' and m=='GET':
  if not (platform(db,a) or can(db,a,'audit.read',organization_id=org) or can(db,a,'role.read',organization_id=org)):return bad(h,'FORBIDDEN','无角色授权变更记录读取权限',403)
  pno,psz,off=page(q);kind=str(q.get('kind') or '').strip();where=["l.organization_id=?","l.entity_type IN ('role','role_binding','role_template')"];args=[org]
  if kind:where.append('l.entity_type=?');args.append(kind)
  clause=' AND '.join(where)
  with db.tx(False) as c:
   total=c.execute('SELECT count(*) FROM audit_logs l WHERE '+clause,args).fetchone()[0]
   its=rows(c,"SELECT l.*,COALESCE(u.display_name,u.login_name,l.actor_id) actor_name FROM audit_logs l LEFT JOIN users u ON u.user_id=l.actor_id WHERE "+clause+' ORDER BY l.created_at DESC,l.audit_id DESC LIMIT ? OFFSET ?',tuple(args+[psz,off]))
  return h.sendj(pack(its,total,pno,psz)) or True
 if root=='rbac' and ident=='confirmations' and m=='POST':
  if not (platform(db,a) or can(db,a,'user.manage',organization_id=org)):return bad(h,'FORBIDDEN','无权限管理权限',403)
  b=h.body(); action=str(b.get('actionKey') or '').strip(); context=b.get('context') or {}
  allowed=('role.create','role.update','role.delete','role.copy','binding.grant','binding.revoke')
  if action not in allowed:return bad(h,'INVALID_ACTION','不支持的高风险确认操作')
  if not isinstance(context,dict):return bad(h,'INVALID_CONTEXT','确认上下文必须为对象')
  context={**context,'organizationId':org}
  try:result=issue_confirmation(db,a,action,context,int(b.get('ttlMs') or 300000))
  except ValueError as e:return bad(h,'INVALID_CONFIRMATION',str(e),400)
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
 # safe database overview: platform-admin only, fixed whitelist, no SQL input, no credential/token tables
 if root=='database-overview' and m=='GET':
  if not platform(db,a):return bad(h,'FORBIDDEN','仅平台超级管理员可查看数据库数据总览',403)
  with db.tx() as c:
   items=[]
   for name in _db_tables(c):
    columns=_db_columns(c,name);where,args,scope,scoped=_db_scope(columns,org);mode,modes=_db_policy(name,columns,scoped)
    total=c.execute('SELECT count(*) FROM '+_db_qi(name)+' WHERE '+where,args).fetchone()[0] if scoped else c.execute('SELECT count(*) FROM '+_db_qi(name)).fetchone()[0]
    category,category_label=_db_category(name)
    reason=None
    if mode=='restricted':reason='包含认证凭据、会话密钥，或无法确认企业范围；仅允许查看结构和记录数'
    items.append({'name':name,'rows':total,'columns':len(columns),'scopedBy':scope,'category':category,'categoryLabel':category_label,'securityLevel':'high' if mode=='restricted' else ('sensitive' if mode=='masked' else 'normal'),'previewMode':mode,'sensitive':mode!='full','restrictedReason':reason,'maskedFields':[key for key,value in modes.items() if value=='mask'],'omittedFields':[key for key,value in modes.items() if value=='omit']})
   categories=[]
   for key,label,_ in _DB_CATEGORIES:
    count=sum(1 for item in items if item['category']==key)
    if count:categories.append({'key':key,'label':label,'count':count})
   count=sum(1 for item in items if item['category']=='other')
   if count:categories.append({'key':'other','label':'系统与其他','count':count})
   audit_in_tx(c,a,'database_overview','database','*',{}, {'organization_id':org,'table_count':len(items)})
  return h.sendj({'ok':True,'items':items,'categories':categories,'readOnly':True,'dynamicDiscovery':True,'summary':{'tableCount':len(items),'restrictedCount':sum(1 for item in items if item['previewMode']=='restricted'),'maskedCount':sum(1 for item in items if item['previewMode']=='masked')}}) or True
 if root=='database-tables' and ident and action=='rows' and m=='GET':
  if not platform(db,a):return bad(h,'FORBIDDEN','仅平台超级管理员可预览数据库记录',403)
  try:page_no=max(1,int(q.get('page') or 1));page_size=min(100,max(1,int(q.get('pageSize') or 50)))
  except Exception:return bad(h,'INVALID_PAGINATION','分页参数无效')
  with db.tx() as c:
   discovered=_db_tables(c)
   if ident not in discovered:return bad(h,'TABLE_NOT_FOUND','数据表不存在或不允许访问',404)
   columns=_db_columns(c,ident);where,args,scope,scoped=_db_scope(columns,org);mode,modes=_db_policy(ident,columns,scoped)
   total=c.execute('SELECT count(*) FROM '+_db_qi(ident)+' WHERE '+where,args).fetchone()[0] if scoped else c.execute('SELECT count(*) FROM '+_db_qi(ident)).fetchone()[0]
   category,category_label=_db_category(ident)
   visible_columns=[{'name':column,'mode':modes[column]} for column in columns if modes[column]!='omit']
   omitted=[column for column in columns if modes[column]=='omit']
   if mode=='restricted':
    audit_in_tx(c,a,'database_preview_denied','database_table',ident,{}, {'organization_id':org,'reason':'restricted'})
    result={'ok':True,'table':ident,'items':[],'columns':visible_columns,'omittedFields':omitted,'maskedFields':[column for column in columns if modes[column]=='mask'],'previewMode':'restricted','restricted':True,'restrictedReason':'该表包含认证凭据、会话密钥，或无法确认企业范围；仅允许查看结构和记录数','category':category,'categoryLabel':category_label,'scopedBy':scope,'pagination':{'page':page_no,'pageSize':page_size,'total':total,'pages':(total+page_size-1)//page_size},'readOnly':True}
   else:
    offset=(page_no-1)*page_size
    raw=rows(c,'SELECT * FROM '+_db_qi(ident)+' WHERE '+where+' LIMIT ? OFFSET ?',tuple(args+[page_size,offset]))
    items=[];masked=set();omitted_set=set(omitted)
    for item in raw:
     clean,masked_now,omitted_now=_db_sanitize_row(item);items.append(clean);masked.update(masked_now);omitted_set.update(omitted_now)
    audit_in_tx(c,a,'database_preview','database_table',ident,{}, {'organization_id':org,'page':page_no,'page_size':page_size})
    result={'ok':True,'table':ident,'items':items,'columns':visible_columns,'omittedFields':sorted(omitted_set),'maskedFields':sorted(masked),'previewMode':mode,'restricted':False,'category':category,'categoryLabel':category_label,'scopedBy':scope,'pagination':{'page':page_no,'pageSize':page_size,'total':total,'pages':(total+page_size-1)//page_size},'readOnly':True}
  return h.sendj(result) or True
 # dashboard
 if root=='dashboard' and m=='GET':
  with db.tx(False) as c:
   names={'teams':'teams','users':'users','workspaces':'workspaces','accounts':'channel_accounts','sources':'sources','devices':'devices','contacts':'contacts'}
   counts={k:c.execute(f'SELECT count(*) FROM {t} WHERE organization_id=?',(org,)).fetchone()[0] for k,t in names.items()}
   counts['activeSessions']=c.execute('SELECT count(*) FROM sessions s JOIN users u ON u.user_id=s.user_id WHERE u.organization_id=? AND s.revoked_at IS NULL AND s.expires_at>?',(org,now_ms())).fetchone()[0]
   counts['audit']=c.execute('SELECT count(*) FROM audit_logs l JOIN users u ON u.user_id=l.actor_id WHERE u.organization_id=?',(org,)).fetchone()[0]
   channel=rows(c,'SELECT channel name,count(*) value FROM channel_accounts WHERE organization_id=? GROUP BY channel',(org,));status=rows(c,'SELECT status name,count(*) value FROM devices WHERE organization_id=? GROUP BY status',(org,))
   recent=rows(c,'SELECT l.*,u.display_name actor_name FROM audit_logs l JOIN users u ON u.user_id=l.actor_id WHERE u.organization_id=? ORDER BY audit_id DESC LIMIT 8',(org,))
   trend=rows(c,"SELECT date(l.created_at/1000,'unixepoch','localtime') day,count(*) value FROM audit_logs l JOIN users u ON u.user_id=l.actor_id WHERE u.organization_id=? AND l.created_at>=? GROUP BY day ORDER BY day",(org,now_ms()-7*86400*1000))
   contact_trend=rows(c,"SELECT date(created_at/1000,'unixepoch','localtime') day,count(*) value FROM contacts WHERE organization_id=? AND deleted_at IS NULL AND created_at>=? GROUP BY day ORDER BY day",(org,now_ms()-14*86400*1000))
   source_trend=rows(c,"SELECT date(last_seen_at/1000,'unixepoch','localtime') day,count(DISTINCT source_id) value FROM sources WHERE organization_id=? AND last_seen_at>=? GROUP BY day ORDER BY day",(org,now_ms()-14*86400*1000))
   source_dist=rows(c,"SELECT source_type name,count(*) value FROM sources WHERE organization_id=? AND status='active' GROUP BY source_type",(org,))
   team_dist=rows(c,"SELECT t.name,count(DISTINCT m.user_id) value FROM teams t LEFT JOIN team_memberships m ON m.team_id=t.team_id AND m.status='active' WHERE t.organization_id=? GROUP BY t.team_id ORDER BY value DESC LIMIT 8",(org,))
  return h.sendj({'auditTrend':trend,'ok':True,'counts':counts,'channelDistribution':channel,'deviceStatus':status,'recentAudit':recent,'database':db.quick_check(),'schemaVersion':SCHEMA_VERSION,'version':PRODUCT_VERSION,'contactTrend':contact_trend,'sourceTrend':source_trend,'sourceDistribution':source_dist,'teamDistribution':team_dist}) or True
 # teams
 if root=='teams':
  # 关键修复：子资源路由必须先于集合/单条资源路由匹配，
  # 否则 /teams/{id}/members 会被前导 if m=='GET' 截获并返回全部团队。
  # 1) 子资源：成员候选
  if ident and action=='member-candidates' and m=='GET':
   term=str(q.get('q') or '').strip()
   if not term:return bad(h,'SEARCH_KEYWORD_REQUIRED','成员搜索关键词不能为空',400)
   like='%'+term.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
   with db.tx(False) as c:
       if not c.execute('SELECT 1 FROM teams WHERE team_id=? AND organization_id=?',(ident,org)).fetchone():return bad(h,'TEAM_NOT_FOUND','团队不存在',404)
       its=rows(c,"""SELECT u.user_id,u.login_name,u.display_name,u.status user_status,
        (SELECT p.name FROM user_positions up JOIN positions p ON p.position_id=up.position_id WHERE up.user_id=u.user_id AND up.is_primary=1 AND up.status='active' LIMIT 1) position_name,
        (SELECT d.name FROM user_positions up JOIN positions p ON p.position_id=up.position_id LEFT JOIN departments d ON d.department_id=p.department_id WHERE up.user_id=u.user_id AND up.is_primary=1 AND up.status='active' LIMIT 1) department_name
        FROM users u WHERE u.organization_id=? AND u.status='active'
        AND NOT EXISTS(SELECT 1 FROM team_memberships tm WHERE tm.user_id=u.user_id AND tm.team_id=? AND tm.status='active')
        AND (u.display_name LIKE ? ESCAPE '\' OR u.login_name LIKE ? ESCAPE '\'
         OR EXISTS(SELECT 1 FROM user_positions up JOIN positions p ON p.position_id=up.position_id LEFT JOIN departments d ON d.department_id=p.department_id WHERE up.user_id=u.user_id AND up.status='active' AND (p.name LIKE ? ESCAPE '\' OR d.name LIKE ? ESCAPE '\')))
        ORDER BY u.display_name,u.login_name LIMIT 50""",(org,ident,like,like,like,like))
   return h.sendj({'ok':True,'items':its,'query':term}) or True
  # 2) 子资源：成员列表 / 添加 / 移出
  if ident and action=='members':
   if m=='GET':
       with db.tx(False) as c:
           if not c.execute('SELECT 1 FROM teams WHERE team_id=? AND organization_id=?',(ident,org)).fetchone():return bad(h,'TEAM_NOT_FOUND','团队不存在',404)
           its=rows(c,"""SELECT tm.*,u.login_name,u.display_name,u.status user_status,
            (SELECT p.name FROM user_positions up JOIN positions p ON p.position_id=up.position_id WHERE up.user_id=u.user_id AND up.is_primary=1 AND up.status='active' LIMIT 1) position_name,
            (SELECT d.name FROM user_positions up JOIN positions p ON p.position_id=up.position_id LEFT JOIN departments d ON d.department_id=p.department_id WHERE up.user_id=u.user_id AND up.is_primary=1 AND up.status='active' LIMIT 1) department_name,
            (SELECT group_concat(DISTINCT r.name) FROM role_bindings rb JOIN roles r ON r.role_id=rb.role_id WHERE rb.user_id=u.user_id AND rb.organization_id=t.organization_id AND rb.status='active') role_names
            FROM team_memberships tm JOIN users u ON u.user_id=tm.user_id JOIN teams t ON t.team_id=tm.team_id
            WHERE tm.team_id=? AND t.organization_id=? AND tm.status='active'
            ORDER BY tm.is_primary DESC,u.display_name,u.login_name""",(ident,org))
       return h.sendj({'ok':True,'items':its}) or True
   if m=='POST':
       if not manage(db,a,'team.manage',org):return bad(h,'FORBIDDEN','无成员管理权限',403)
       b=h.body();uid=str(b.get('userId') or '').strip();kind=str(b.get('membershipType') or 'member');primary=1 if str(b.get('isPrimary') or '0').lower() in ('1','true') else 0;reason=str(b.get('reason') or '').strip()
       if not uid:return bad(h,'USER_REQUIRED','必须选择用户')
       if not reason:return bad(h,'REASON_REQUIRED','操作原因必填')
       if kind not in ('member','manager','operator','support'):return bad(h,'INVALID_MEMBERSHIP_TYPE','成员类型无效')
       with db.tx() as c:
           user=one(c,'SELECT user_id,display_name,login_name FROM users WHERE user_id=? AND organization_id=? AND status=\'active\'',(uid,org))
           if not user:return bad(h,'USER_NOT_FOUND','用户不存在、已停用或不属于目标企业',404)
           team=one(c,'SELECT team_id,name FROM teams WHERE team_id=? AND organization_id=?',(ident,org))
           if not team:return bad(h,'TEAM_NOT_FOUND','团队不存在',404)
           old=one(c,'SELECT * FROM team_memberships WHERE user_id=? AND team_id=?',(uid,ident)) or {}
           n=now_ms()
           if primary:c.execute("UPDATE team_memberships SET is_primary=0,updated_at=? WHERE user_id=? AND team_id<>? AND status='active'",(n,uid,ident))
           c.execute("INSERT INTO team_memberships(user_id,team_id,membership_type,is_primary,status,joined_at,left_at,created_at,updated_at) VALUES(?,?,?,?, 'active',?,NULL,?,?) ON CONFLICT(user_id,team_id) DO UPDATE SET membership_type=excluded.membership_type,is_primary=excluded.is_primary,status='active',left_at=NULL,updated_at=excluded.updated_at",(uid,ident,kind,primary,n,n,n))
           newrow=one(c,'SELECT * FROM team_memberships WHERE user_id=? AND team_id=?',(uid,ident))
           audit_in_tx(c,a,'upsert','team_membership',uid,old,newrow,reason)
       return h.sendj({'ok':True,'item':newrow}) or True
   if m=='DELETE':
       if not manage(db,a,'team.manage',org):return bad(h,'FORBIDDEN','无成员管理权限',403)
       b=h.body();uid=str(b.get('userId') or '').strip();reason=str(b.get('reason') or '').strip()
       if not uid:return bad(h,'USER_REQUIRED','必须指定用户')
       if not reason:return bad(h,'REASON_REQUIRED','操作原因必填')
       with db.tx() as c:
           if not c.execute('SELECT 1 FROM teams WHERE team_id=? AND organization_id=?',(ident,org)).fetchone():return bad(h,'TEAM_NOT_FOUND','团队不存在',404)
           old=one(c,"SELECT * FROM team_memberships WHERE user_id=? AND team_id=? AND status='active'",(uid,ident))
           if not old:return bad(h,'MEMBER_NOT_FOUND','该用户不是当前团队的有效成员',404)
           if int(old.get('is_primary') or 0):return bad(h,'PRIMARY_TEAM_TRANSFER_REQUIRED','请先为该用户转移主团队，再执行移出',409)
           n=now_ms();cur=c.execute("UPDATE team_memberships SET status='disabled',is_primary=0,left_at=?,updated_at=? WHERE user_id=? AND team_id=? AND status='active'",(n,n,uid,ident))
           if cur.rowcount!=1:raise RuntimeError('TEAM_MEMBER_UPDATE_RACE')
           audit_in_tx(c,a,'remove','team_membership',uid,old,{},reason)
       return h.sendj({'ok':True}) or True
   return bad(h,'METHOD_NOT_ALLOWED','成员接口支持 GET/POST/DELETE',405)
  # 3) 子资源：业务线关系（GET 列表 / PUT 替换）
  if ident and action=='business-lines' and m in ('GET','PUT','PATCH'):
   if m in ('PUT','PATCH') and not manage(db,a,'team.manage',org):return bad(h,'FORBIDDEN','无团队管理权限',403)
   with db.tx() as c:
       if not c.execute('SELECT 1 FROM teams WHERE team_id=? AND organization_id=?',(ident,org)).fetchone():return bad(h,'TEAM_NOT_FOUND','团队不存在',404)
       if m=='GET':
           its=rows(c,"""SELECT tbl.team_id,tbl.business_line_id,tbl.is_primary,tbl.status,tbl.created_at,tbl.updated_at,bl.name,bl.code
             FROM team_business_lines tbl JOIN business_lines bl ON bl.business_line_id=tbl.business_line_id
             WHERE tbl.team_id=? AND tbl.organization_id=? ORDER BY tbl.is_primary DESC,bl.name""",(ident,org))
           return h.sendj({'ok':True,'items':its}) or True
       b=h.body();items=list(b.get('items') or []);reason=str(b.get('reason') or '').strip()
       if not reason:return bad(h,'REASON_REQUIRED','操作原因必填')
       seen=set();primary_count=0;cleaned=[]
       for it in items:
           bid=str(it.get('businessLineId') or it.get('business_line_id') or '').strip()
           if not bid or bid in seen:continue
           if not c.execute('SELECT 1 FROM business_lines WHERE business_line_id=? AND organization_id=?',(bid,org)).fetchone():
               return bad(h,'BUSINESS_LINE_NOT_FOUND','业务线不存在或不属于当前企业',404)
           seen.add(bid)
           primary=1 if str(it.get('isPrimary') or '0').lower() in ('1','true') else 0
           if primary:primary_count+=1
           status=clean_status(it.get('status')) or 'active'
           cleaned.append((bid,primary,status))
       if primary_count>1:return bad(h,'PRIMARY_BUSINESS_LINE_UNIQUE','业务线只能设置一个主要关系',409)
       old=rows(c,"SELECT * FROM team_business_lines WHERE team_id=? AND organization_id=?",(ident,org))
       n=now_ms()
       c.execute("DELETE FROM team_business_lines WHERE team_id=?",(ident,))
       for bid,primary,status in cleaned:
           c.execute("INSERT INTO team_business_lines(team_id,business_line_id,organization_id,is_primary,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(ident,bid,org,primary,status,n,n))
       new=rows(c,"SELECT * FROM team_business_lines WHERE team_id=? AND organization_id=?",(ident,org))
       audit_in_tx(c,a,'replace','team_business_lines',ident,old,new,reason)
   return h.sendj({'ok':True,'items':new}) or True
  # 4) 子资源：市场关系（GET 列表 / PUT 替换）
  if ident and action=='markets' and m in ('GET','PUT','PATCH'):
   if m in ('PUT','PATCH') and not manage(db,a,'team.manage',org):return bad(h,'FORBIDDEN','无团队管理权限',403)
   with db.tx() as c:
       if not c.execute('SELECT 1 FROM teams WHERE team_id=? AND organization_id=?',(ident,org)).fetchone():return bad(h,'TEAM_NOT_FOUND','团队不存在',404)
       if m=='GET':
           its=rows(c,"""SELECT tmt.team_id,tmt.market_id,tmt.is_primary,tmt.scope_type,tmt.status,tmt.created_at,tmt.updated_at,m.name,m.code
             FROM team_markets tmt JOIN markets m ON m.market_id=tmt.market_id
             WHERE tmt.team_id=? AND tmt.organization_id=? ORDER BY tmt.is_primary DESC,m.name""",(ident,org))
           return h.sendj({'ok':True,'items':its}) or True
       b=h.body();items=list(b.get('items') or []);reason=str(b.get('reason') or '').strip()
       if not reason:return bad(h,'REASON_REQUIRED','操作原因必填')
       seen=set();primary_count=0;cleaned=[]
       for it in items:
           mid=str(it.get('marketId') or it.get('market_id') or '').strip()
           if not mid or mid in seen:continue
           if not c.execute('SELECT 1 FROM markets WHERE market_id=? AND organization_id=?',(mid,org)).fetchone():
               return bad(h,'MARKET_NOT_FOUND','市场不存在或不属于当前企业',404)
           seen.add(mid)
           primary=1 if str(it.get('isPrimary') or '0').lower() in ('1','true') else 0
           if primary:primary_count+=1
           status=clean_status(it.get('status')) or 'active'
           scope=str(it.get('scopeType') or it.get('scope_type') or 'direct').strip().lower()
           if scope not in ('direct','descendants'):return bad(h,'INVALID_SCOPE_TYPE','市场范围必须是 direct 或 descendants',400)
           cleaned.append((mid,primary,scope,status))
       if primary_count>1:return bad(h,'PRIMARY_MARKET_UNIQUE','市场只能设置一个主要关系',409)
       old=rows(c,"SELECT * FROM team_markets WHERE team_id=? AND organization_id=?",(ident,org))
       n=now_ms()
       c.execute("DELETE FROM team_markets WHERE team_id=?",(ident,))
       for mid,primary,scope,status in cleaned:
           c.execute("INSERT INTO team_markets(team_id,market_id,organization_id,is_primary,scope_type,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(ident,mid,org,primary,scope,status,n,n))
       new=rows(c,"SELECT * FROM team_markets WHERE team_id=? AND organization_id=?",(ident,org))
       audit_in_tx(c,a,'replace','team_markets',ident,old,new,reason)
   return h.sendj({'ok':True,'items':new}) or True
  # 5) 子资源：综合配置（业务线+市场+成员概览）
  if ident and action=='config' and m=='GET':
   with db.tx(False) as c:
       if not c.execute('SELECT 1 FROM teams WHERE team_id=? AND organization_id=?',(ident,org)).fetchone():return bad(h,'TEAM_NOT_FOUND','团队不存在',404)
       team=one(c,"SELECT t.*,w.name workspace_name FROM teams t JOIN workspaces w ON w.workspace_id=t.workspace_id WHERE t.team_id=? AND t.organization_id=?",(ident,org))
       bl=rows(c,"""SELECT tbl.business_line_id,tbl.is_primary,tbl.status,bl.name,bl.code FROM team_business_lines tbl JOIN business_lines bl ON bl.business_line_id=tbl.business_line_id WHERE tbl.team_id=? AND tbl.organization_id=? ORDER BY tbl.is_primary DESC,bl.name""",(ident,org))
       mk=rows(c,"""SELECT tmt.market_id,tmt.is_primary,tmt.scope_type,tmt.status,m.name,m.code FROM team_markets tmt JOIN markets m ON m.market_id=tmt.market_id WHERE tmt.team_id=? AND tmt.organization_id=? ORDER BY tmt.is_primary DESC,m.name""",(ident,org))
       member_count=c.execute("""SELECT COUNT(DISTINCT tm.user_id)
         FROM team_memberships tm
         JOIN users u ON u.user_id=tm.user_id AND u.organization_id=t.organization_id
         JOIN teams t ON t.team_id=tm.team_id
         WHERE tm.team_id=? AND tm.status='active'""",(ident,)).fetchone()[0]
   return h.sendj({'ok':True,'team':team,'businessLines':bl,'markets':mk,'memberCount':member_count}) or True
  # 6) 单个团队 PATCH：名称 / 状态 / 所属工作区（同一事务、必填原因）
  if ident and not action and m=='PATCH':
   if not manage(db,a,'team.manage',org):return bad(h,'FORBIDDEN','无团队管理权限',403)
   b=h.body();reason=str(b.get('reason') or '').strip()
   if not reason:return bad(h,'REASON_REQUIRED','操作原因必填')
   with db.tx() as c:
       old=one(c,'SELECT * FROM teams WHERE team_id=? AND organization_id=?',(ident,org))
       if not old:return bad(h,'NOT_FOUND','团队不存在',404)
       new_name=str(b.get('name') or old['name']).strip()
       new_status=clean_status(b.get('status')) or old['status']
       new_workspace=str(b.get('workspaceId') or b.get('workspace_id') or old['workspace_id']).strip()
       if new_workspace!=old['workspace_id']:
           if not c.execute("SELECT 1 FROM workspaces WHERE workspace_id=? AND organization_id=? AND status='active'",(new_workspace,org)).fetchone():
               return bad(h,'WORKSPACE_NOT_FOUND','工作区不存在或已停用',404)
       if not new_name:return bad(h,'NAME_REQUIRED','团队名称不能为空')
       n=now_ms()
       c.execute('UPDATE teams SET name=?,status=?,workspace_id=?,updated_at=? WHERE team_id=?',(new_name,new_status,new_workspace,n,ident))
       if new_workspace!=old['workspace_id']:
           c.execute("DELETE FROM workspace_teams WHERE team_id=? AND workspace_id<>?",(ident,new_workspace))
           c.execute("INSERT INTO workspace_teams(workspace_id,team_id,organization_id,relation_type,is_primary,access_level,status,created_at,updated_at) VALUES(?,?,?,'primary',1,'manage','active',?,?) ON CONFLICT(workspace_id,team_id) DO UPDATE SET status='active',updated_at=excluded.updated_at",(new_workspace,ident,org,n,n))
       new=one(c,'SELECT * FROM teams WHERE team_id=?',(ident,))
       audit_in_tx(c,a,'update','team',ident,old,new,reason,old['workspace_id'])
   return h.sendj({'ok':True,'item':new}) or True
  # 7) 单个团队 GET
  if ident and not action and m=='GET':
   with db.tx(False) as c:
       team=one(c,"""SELECT t.*,w.name workspace_name,
         (SELECT COUNT(DISTINCT tm.user_id) FROM team_memberships tm JOIN users u ON u.user_id=tm.user_id AND u.organization_id=t.organization_id WHERE tm.team_id=t.team_id AND tm.status='active') member_count,
         (SELECT count(*) FROM team_channel_accounts x WHERE x.team_id=t.team_id) account_count,
         (SELECT group_concat(bl.name) FROM team_business_lines tbl JOIN business_lines bl ON bl.business_line_id=tbl.business_line_id WHERE tbl.team_id=t.team_id AND tbl.status='active') business_lines,
         (SELECT group_concat(m.name) FROM team_markets tm JOIN markets m ON m.market_id=tm.market_id WHERE tm.team_id=t.team_id AND tm.status='active') markets
         FROM teams t JOIN workspaces w ON w.workspace_id=t.workspace_id WHERE t.team_id=? AND t.organization_id=?""",(ident,org))
       if not team:return bad(h,'NOT_FOUND','团队不存在',404)
   return h.sendj({'ok':True,'item':team}) or True
  # 8) 单个团队 DELETE
  if ident and not action and m=='DELETE':
   if not manage(db,a,'team.manage',org):return bad(h,'FORBIDDEN','无团队删除权限',403)
   with db.tx() as c:
       old=one(c,'SELECT * FROM teams WHERE team_id=? AND organization_id=?',(ident,org))
       if not old:return bad(h,'NOT_FOUND','团队不存在',404)
       refs={'members':c.execute("SELECT count(*) FROM team_memberships WHERE team_id=? AND status='active'",(ident,)).fetchone()[0],'bindings':c.execute('SELECT count(*) FROM role_bindings WHERE organization_id=? AND scope_type=\'team\' AND scope_id=? AND status=\'active\'',(org,ident)).fetchone()[0],'channelGrants':c.execute('SELECT count(*) FROM team_channel_accounts WHERE team_id=?',(ident,)).fetchone()[0],'positions':c.execute('SELECT count(*) FROM positions WHERE team_id=?',(ident,)).fetchone()[0],'sources':c.execute('SELECT count(*) FROM sources WHERE team_id=? AND status=\'active\'',(ident,)).fetchone()[0]}
       refs={k:v for k,v in refs.items() if v}
       if refs:return bad(h,'TEAM_IN_USE','团队仍被业务对象引用，无法删除',409,references=refs)
       c.execute('DELETE FROM workspace_teams WHERE team_id=?',(ident,))
       c.execute('DELETE FROM team_memberships WHERE team_id=?',(ident,))
       c.execute('DELETE FROM team_business_lines WHERE team_id=?',(ident,))
       c.execute('DELETE FROM team_markets WHERE team_id=?',(ident,))
       c.execute('DELETE FROM teams WHERE team_id=?',(ident,))
       audit_in_tx(c,a,'delete','team',ident,old,{},old['workspace_id'])
   return h.sendj({'ok':True}) or True
  # 9) 团队集合 GET：成员数为企业内去重统计
  if not ident and m=='GET':
   with db.tx(False) as c:
       its=rows(c,"""SELECT t.*,w.name workspace_name,
         (SELECT COUNT(DISTINCT tm.user_id) FROM team_memberships tm JOIN users u ON u.user_id=tm.user_id AND u.organization_id=t.organization_id WHERE tm.team_id=t.team_id AND tm.status='active') member_count,
         (SELECT count(*) FROM team_channel_accounts x WHERE x.team_id=t.team_id) account_count,
         (SELECT group_concat(bl.name) FROM team_business_lines tbl JOIN business_lines bl ON bl.business_line_id=tbl.business_line_id WHERE tbl.team_id=t.team_id AND tbl.status='active') business_lines,
         (SELECT group_concat(m.name) FROM team_markets tm JOIN markets m ON m.market_id=tm.market_id WHERE tm.team_id=t.team_id AND tm.status='active') markets
         FROM teams t JOIN workspaces w ON w.workspace_id=t.workspace_id WHERE t.organization_id=? ORDER BY t.created_at""",(org,))
   return h.sendj({'ok':True,'items':its}) or True
  # 10) 团队集合 POST
  if not ident and m=='POST':
   if not manage(db,a,'team.manage',org):return bad(h,'FORBIDDEN','无团队管理权限',403)
   b=h.body();name=str(b.get('name') or '').strip();wid=str(b.get('workspaceId') or '').strip()
   if not name:return bad(h,'NAME_REQUIRED','团队名称不能为空')
   if not wid:return bad(h,'WORKSPACE_REQUIRED','必须选择所属工作区')
   n=now_ms();tid='team_'+uuid.uuid4().hex
   with db.tx() as c:
       if not c.execute("SELECT 1 FROM workspaces WHERE workspace_id=? AND organization_id=? AND status='active'",(wid,org)).fetchone():return bad(h,'WORKSPACE_NOT_FOUND','工作区不存在或已停用',404)
       c.execute('INSERT INTO teams(team_id,organization_id,workspace_id,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(tid,org,wid,name,'active',n,n))
       c.execute("INSERT INTO workspace_teams(workspace_id,team_id,organization_id,relation_type,is_primary,access_level,status,created_at,updated_at) VALUES(?,?,?,'primary',1,'manage','active',?,?)",(wid,tid,org,n,n))
       audit_in_tx(c,a,'create','team',tid,{},b,wid=wid)
   return h.sendj({'ok':True,'teamId':tid,'workspaceId':wid},201) or True
 # users
 if root=='users':
  if m=='GET':
   with db.tx(False) as c:its=rows(c,"SELECT u.*,(SELECT group_concat(t.name) FROM team_memberships tm JOIN teams t ON t.team_id=tm.team_id WHERE tm.user_id=u.user_id AND tm.status='active') teams,(SELECT group_concat(r.name) FROM role_bindings b JOIN roles r ON r.role_id=b.role_id WHERE b.user_id=u.user_id AND b.organization_id=u.organization_id AND b.status='active') roles,(SELECT p.name FROM user_positions up JOIN positions p ON p.position_id=up.position_id WHERE up.user_id=u.user_id AND up.is_primary=1 AND up.status='active' LIMIT 1) position_name,(SELECT p.position_id FROM user_positions up JOIN positions p ON p.position_id=up.position_id WHERE up.user_id=u.user_id AND up.is_primary=1 AND up.status='active' LIMIT 1) position_id,(SELECT d.name FROM user_positions up JOIN positions p ON p.position_id=up.position_id LEFT JOIN departments d ON d.department_id=p.department_id WHERE up.user_id=u.user_id AND up.is_primary=1 AND up.status='active' LIMIT 1) department_name,(SELECT tm.team_id FROM team_memberships tm WHERE tm.user_id=u.user_id AND tm.is_primary=1 AND tm.status='active' LIMIT 1) primary_team_id,(SELECT tm.membership_type FROM team_memberships tm WHERE tm.user_id=u.user_id AND tm.is_primary=1 AND tm.status='active' LIMIT 1) primary_membership_type FROM users u WHERE u.organization_id=? ORDER BY u.created_at",(org,))
   return h.sendj({'ok':True,'items':its}) or True
  if m=='POST':
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无用户管理权限',403)
   b=h.body();ln=str(b.get('loginName') or '').strip();pwd=str(b.get('password') or '');team=str(b.get('teamId') or '').strip();role=str(b.get('roleId') or 'role_operator');position=str(b.get('positionId') or '').strip();kind=str(b.get('membershipType') or 'member');workspace=str(b.get('workspaceId') or '').strip()
   if not ln or not password_strong(pwd):return bad(h,'INVALID_USER','登录名必填；密码至少 12 位且必须同时包含字母和数字')
   if kind not in ('member','manager','operator','support'):return bad(h,'INVALID_MEMBERSHIP_TYPE','成员类型无效')
   with db.tx() as c:
    rr=c.execute("SELECT scope_level FROM roles WHERE role_id=? AND status='active' AND (organization_id IS NULL OR organization_id=?)",(role,org)).fetchone()
    if not rr or rr[0] not in ('organization','workspace','team'):return bad(h,'INVALID_ROLE','角色不存在、已停用或范围不适用于企业用户',400)
    if team and not c.execute('SELECT 1 FROM teams WHERE team_id=? AND organization_id=?',(team,org)).fetchone():return bad(h,'TEAM_NOT_FOUND','团队不存在',404)
    if rr[0]=='team' and not team:return bad(h,'TEAM_REQUIRED','团队级角色必须选择团队',400)
    if not workspace:workspace=default_workspace_id(c,org) or ''
    if workspace and not c.execute("SELECT 1 FROM workspaces WHERE workspace_id=? AND organization_id=? AND status='active'",(workspace,org)).fetchone():return bad(h,'WORKSPACE_NOT_FOUND','工作区不存在或已停用',404)
    if rr[0]=='workspace' and not workspace:return bad(h,'WORKSPACE_REQUIRED','工作区级角色必须选择工作区',400)
    if position and not c.execute("SELECT 1 FROM positions WHERE position_id=? AND organization_id=? AND status='active'",(position,org)).fetchone():return bad(h,'POSITION_NOT_FOUND','职位不存在或已停用',404)
    scope_type=rr[0];scope_id=org if scope_type=='organization' else (workspace if scope_type=='workspace' else team);uid='usr_'+uuid.uuid4().hex;n=now_ms();ph,salt,it=hash_password(pwd)
    try:
     c.execute('INSERT INTO users(user_id,organization_id,login_name,display_name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(uid,org,ln,str(b.get('displayName') or ln),'active',n,n))
     c.execute('INSERT INTO user_credentials(user_id,password_hash,salt,iterations,must_change,updated_at) VALUES(?,?,?,?,?,?)',(uid,ph,salt,it,1,n))
     if position:c.execute("INSERT INTO user_positions(user_id,position_id,organization_id,is_primary,status,created_at,updated_at) VALUES(?,?,?,1,'active',?,?)",(uid,position,org,n,n))
     if team:c.execute("INSERT INTO team_memberships(user_id,team_id,membership_type,is_primary,status,joined_at,left_at,created_at,updated_at) VALUES(?,?,?,1,'active',?,NULL,?,?)",(uid,team,kind,n,n,n))
     grant_binding_in_tx(c,uid,role,org,scope_type,scope_id,a['user_id'])
    except Exception:
     return bad(h,'USER_CONFLICT','登录名冲突或数据无效',409)
    audit_in_tx(c,a,'create','user',uid,{},dict(b,password='***'))
   return h.sendj({'ok':True,'userId':uid},201) or True
  if ident and not action and m=='PATCH':
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无用户管理权限',403)
   b=h.body();reason=str(b.get('reason') or '').strip()
   if not reason:return bad(h,'REASON_REQUIRED','操作原因不能为空')
   position=str(b.get('positionId') or '').strip();team=str(b.get('teamId') or '').strip();kind=str(b.get('membershipType') or 'member')
   if kind not in ('member','manager','operator','support'):return bad(h,'INVALID_MEMBERSHIP_TYPE','成员类型无效')
   with db.tx() as c:
    old=one(c,'SELECT * FROM users WHERE user_id=? AND organization_id=?',(ident,org))
    if not old:return bad(h,'NOT_FOUND','用户不存在',404)
    if position and not c.execute("SELECT 1 FROM positions WHERE position_id=? AND organization_id=? AND status='active'",(position,org)).fetchone():return bad(h,'POSITION_NOT_FOUND','职位不存在或已停用',404)
    if team and not c.execute("SELECT 1 FROM teams WHERE team_id=? AND organization_id=? AND status='active'",(team,org)).fetchone():return bad(h,'TEAM_NOT_FOUND','团队不存在或已停用',404)
    n=now_ms();new_status=clean_status(b.get('status')) or old['status']
    c.execute('UPDATE users SET display_name=?,status=?,updated_at=? WHERE user_id=?',(str(b.get('displayName') or old['display_name']),new_status,n,ident))
    c.execute("UPDATE user_positions SET is_primary=0,updated_at=? WHERE user_id=? AND organization_id=? AND is_primary=1",(n,ident,org))
    if position:c.execute("INSERT INTO user_positions(user_id,position_id,organization_id,is_primary,status,created_at,updated_at) VALUES(?,?,?,1,'active',?,?) ON CONFLICT(user_id,position_id) DO UPDATE SET is_primary=1,status='active',updated_at=excluded.updated_at",(ident,position,org,n,n))
    c.execute("UPDATE team_memberships SET is_primary=0,updated_at=? WHERE user_id=? AND status='active'",(n,ident))
    if team:c.execute("INSERT INTO team_memberships(user_id,team_id,membership_type,is_primary,status,joined_at,left_at,created_at,updated_at) VALUES(?,?,?,?, 'active',?,NULL,?,?) ON CONFLICT(user_id,team_id) DO UPDATE SET membership_type=excluded.membership_type,is_primary=1,status='active',left_at=NULL,updated_at=excluded.updated_at",(ident,team,kind,1,n,n,n))
    new=one(c,'SELECT * FROM users WHERE user_id=?',(ident,))
    if new['status']!='active':revoke_sessions_in_tx(c,ident,a['user_id'],'user_disabled')
    audit_in_tx(c,a,'update','user',ident,old,dict(new,positionId=position,teamId=team,membershipType=kind),reason)
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
  if ident and not action and m=='DELETE':
   if not manage(db,a,'user.manage',org):return bad(h,'FORBIDDEN','无用户删除权限',403)
   with db.tx() as c:
    old=one(c,'SELECT * FROM users WHERE user_id=? AND organization_id=?',(ident,org))
    if not old:return bad(h,'NOT_FOUND','用户不存在',404)
    refs={'activeBindings':c.execute('SELECT count(*) FROM role_bindings WHERE user_id=? AND organization_id=? AND status=\'active\'',(ident,org)).fetchone()[0],'teamMemberships':c.execute('SELECT count(*) FROM team_memberships WHERE user_id=?',(ident,)).fetchone()[0],'channelGrants':c.execute('SELECT count(*) FROM user_channel_account_grants WHERE user_id=? AND status=\'active\'',(ident,)).fetchone()[0],'ownedContacts':c.execute('SELECT count(*) FROM contacts WHERE assigned_user_id=?',(ident,)).fetchone()[0],'ownedDevices':c.execute('SELECT count(*) FROM devices WHERE assigned_user_id=?',(ident,)).fetchone()[0]}
    refs={k:v for k,v in refs.items() if v}
    if refs:return bad(h,'USER_IN_USE','用户仍被业务对象引用，无法删除',409,references=refs)
    revoke_sessions_in_tx(c,ident,a['user_id'],'user_deleted')
    c.execute("UPDATE role_bindings SET status='archived',updated_at=? WHERE user_id=? AND organization_id=? AND status='active'",(now_ms(),ident,org))
    c.execute('DELETE FROM team_memberships WHERE user_id=?',(ident,))
    c.execute('DELETE FROM user_credentials WHERE user_id=?',(ident,))
    c.execute('DELETE FROM organization_memberships WHERE user_id=?',(ident,))
    c.execute('DELETE FROM users WHERE user_id=?',(ident,))
    audit_in_tx(c,a,'delete','user',ident,old,{})
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
     w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? ORDER BY CASE workspace_id WHEN 'ws-global' THEN 0 ELSE 1 END, created_at, workspace_id LIMIT 1",(org,)).fetchone()
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
    w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? ORDER BY CASE workspace_id WHEN 'ws-global' THEN 0 ELSE 1 END, created_at, workspace_id LIMIT 1",(org,)).fetchone()
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
   if not (platform(db,a) or can(db,a,'role.binding.read',organization_id=org) or can(db,a,'role.read',organization_id=org) or can(db,a,'user.read',organization_id=org)):return bad(h,'FORBIDDEN','无授权读取权限',403)
   status=str(q.get('status') or 'active').strip(); user_id=str(q.get('userId') or q.get('user_id') or '').strip(); role_id=str(q.get('roleId') or q.get('role_id') or '').strip(); scope_type=str(q.get('scopeType') or q.get('scope_type') or '').strip()
   if status not in ('active','disabled','archived','all'):return bad(h,'INVALID_STATUS','授权状态不合法')
   if scope_type and scope_type not in ('organization','workspace','department','team','self'):return bad(h,'INVALID_SCOPE','授权作用域不合法')
   pno,psz,off=page(q);where=['b.organization_id=?',"b.scope_type<>'platform'"];args=[org]
   if status!='all':
    where.append('b.status=?');args.append(status)
    if status=='active':where.append('(b.valid_from IS NULL OR b.valid_from<=?) AND (b.expires_at IS NULL OR b.expires_at>?)');args.extend([now_ms(),now_ms()])
   if user_id:where.append('b.user_id=?');args.append(user_id)
   if role_id:where.append('b.role_id=?');args.append(role_id)
   if scope_type:where.append('b.scope_type=?');args.append(scope_type)
   clause=' AND '.join(where)
   with db.tx(False) as c:
    total=c.execute('SELECT count(*) FROM role_bindings b WHERE '+clause,tuple(args)).fetchone()[0]
    its=rows(c,"""SELECT b.*,u.login_name,u.display_name,r.name role_name,r.role_code,r.is_system,r.scope_level role_scope,
     (SELECT p.name FROM user_positions up JOIN positions p ON p.position_id=up.position_id WHERE up.user_id=u.user_id AND up.is_primary=1 AND up.status='active' LIMIT 1) position_name,
     (SELECT d.name FROM user_positions up JOIN positions p ON p.position_id=up.position_id LEFT JOIN departments d ON d.department_id=p.department_id WHERE up.user_id=u.user_id AND up.is_primary=1 AND up.status='active' LIMIT 1) department_name,
     COALESCE((SELECT name FROM workspaces WHERE b.scope_type='workspace' AND workspace_id=b.scope_id),(SELECT name FROM departments WHERE b.scope_type='department' AND department_id=b.scope_id),(SELECT name FROM teams WHERE b.scope_type='team' AND team_id=b.scope_id),CASE WHEN b.scope_type='organization' THEN '当前企业' WHEN b.scope_type='self' THEN u.display_name END,b.scope_id) scope_name,
     COALESCE((SELECT display_name FROM users WHERE user_id=b.approved_by),b.approved_by,'—') approved_by_name
     FROM role_bindings b JOIN users u ON u.user_id=b.user_id JOIN roles r ON r.role_id=b.role_id WHERE """+clause+' ORDER BY b.updated_at DESC,b.binding_id LIMIT ? OFFSET ?',tuple(args+[psz,off]))
    now=now_ms()
    for item in its:item['effective_status']='revoked' if item['status']!='active' else ('pending' if item.get('valid_from') and item['valid_from']>now else ('expired' if item.get('expires_at') and item['expires_at']<=now else ('expiring' if item.get('expires_at') and item['expires_at']<=now+7*86400000 else 'active')))
   return h.sendj(pack(its,total,pno,psz)) or True
  if m=='POST' and not ident:
   if not (platform(db,a) or can(db,a,'role.binding.manage',organization_id=org) or can(db,a,'role.manage',organization_id=org)):return bad(h,'FORBIDDEN','无授权管理权限',403)
   b=h.body();user_id=str(b.get('userId') or '').strip();role_id=str(b.get('roleId') or '').strip();scope_type=str(b.get('scopeType') or '').strip();scope_id=str(b.get('scopeId') or '').strip();valid_from=b.get('validFrom');expires_at=b.get('expiresAt');grant_reason=str(b.get('reason') or '').strip();grant_type=str(b.get('grantType') or 'standard').strip()
   if not all((user_id,role_id,scope_type,scope_id)):return bad(h,'INVALID_INPUT','用户、角色、作用域类型和作用域 ID 均不能为空')
   if not grant_reason:return bad(h,'GRANT_REASON_REQUIRED','授权原因不能为空')
   if scope_type not in ('organization','workspace','department','team','self'):return bad(h,'INVALID_SCOPE','通用授权接口不允许平台作用域')
   ctx={'expiresAt':expires_at,'grantType':grant_type,'organizationId':org,'roleId':role_id,'scopeId':scope_id,'scopeType':scope_type,'userId':user_id,'validFrom':valid_from}
   if not consume_confirmation(db,a,'binding.grant',h.headers.get('X-RBAC-Confirmation',''),ctx):return bad(h,'CONFIRMATION_REQUIRED','高风险确认凭证无效或已过期',428)
   try:
    with db.tx() as c:
     w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? AND status='active' ORDER BY CASE workspace_id WHEN 'ws-global' THEN 0 ELSE 1 END, created_at, workspace_id LIMIT 1",(org,)).fetchone()
     if not w:return bad(h,'WORKSPACE_REQUIRED','当前企业缺少有效业务空间',409)
     active_sessions=c.execute("SELECT count(*) FROM sessions WHERE user_id=? AND revoked_at IS NULL AND expires_at>?",(user_id,now_ms())).fetchone()[0]
     bid=grant_binding_in_tx(c,user_id,role_id,org,scope_type,scope_id,a['user_id'],valid_from,expires_at,grant_reason,grant_type,a['user_id'])
     item=one(c,'SELECT * FROM role_bindings WHERE binding_id=?',(bid,));audit_in_tx(c,a,'grant','role_binding',bid,{},item,str(b.get('reason') or ''),w[0])
   except sqlite3.IntegrityError as e:return bad(h,'BINDING_CONFLICT','授权与租户或作用域约束冲突',409)
   return h.sendj({'ok':True,'bindingId':bid,'item':item,'revokedSessionCount':active_sessions},201) or True
  if ident and m=='DELETE' and action is None:
   if not (platform(db,a) or can(db,a,'role.binding.manage',organization_id=org) or can(db,a,'role.manage',organization_id=org)):return bad(h,'FORBIDDEN','无授权管理权限',403)
   with db.tx(False) as c:old=one(c,"SELECT * FROM role_bindings WHERE binding_id=? AND organization_id=? AND scope_type<>'platform' AND status='active'",(ident,org))
   if not old:return bad(h,'NOT_FOUND','有效授权不存在',404)
   ctx={'bindingId':ident,'organizationId':org,'roleId':old['role_id'],'scopeId':old['scope_id'],'scopeType':old['scope_type'],'userId':old['user_id']}
   if not consume_confirmation(db,a,'binding.revoke',h.headers.get('X-RBAC-Confirmation',''),ctx):return bad(h,'CONFIRMATION_REQUIRED','高风险确认凭证无效或已过期',428)
   b=h.body();reason=str(b.get('reason') or '')
   with db.tx() as c:
    current=one(c,"SELECT * FROM role_bindings WHERE binding_id=? AND organization_id=? AND scope_type<>'platform' AND status='active'",(ident,org))
    if not current:return bad(h,'BINDING_CHANGED','授权已变更或撤销，请刷新后重试',409)
    w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? AND status='active' ORDER BY CASE workspace_id WHEN 'ws-global' THEN 0 ELSE 1 END, created_at, workspace_id LIMIT 1",(org,)).fetchone()
    if not w:return bad(h,'WORKSPACE_REQUIRED','当前企业缺少有效业务空间',409)
    revoked=revoke_sessions_in_tx(c,current['user_id'],a['user_id'],'authorization_changed')
    c.execute("UPDATE role_bindings SET status='archived',updated_at=? WHERE binding_id=? AND status='active'",(now_ms(),ident));after=one(c,'SELECT * FROM role_bindings WHERE binding_id=?',(ident,));audit_in_tx(c,a,'revoke','role_binding',ident,current,after,reason,w[0])
   return h.sendj({'ok':True,'bindingId':ident,'revokedSessionCount':revoked}) or True
  return bad(h,'METHOD_NOT_ALLOWED','授权接口方法不受支持',405)
 # roles and permission matrix
 if root=='permissions' and m=='GET':
  if not (platform(db,a) or can(db,a,'permission.read',organization_id=org) or can(db,a,'role.read',organization_id=org)):return bad(h,'FORBIDDEN','无权限元数据读取权限',403)
  with db.tx(False) as c:its=rows(c,'SELECT * FROM permissions ORDER BY permission_key')
  resource_zh={'account':'渠道账号','attribution':'归因','audit':'审计','campaign':'营销活动','contact':'联系人','device':'设备','organization':'企业组织','permission':'权限','platform':'平台','role':'角色','source':'来源','team':'团队','touchpoint':'客户触点','user':'用户','workspace':'工作区'}
  action_zh={'read':'查看','manage':'管理','create':'新建','update':'修改','delete':'删除','restore':'恢复','recalculate':'重新计算','disable':'停用','rename':'重命名','bind':'绑定','identity':'身份管理','export':'导出','approve':'审批','path':'路径','structure':'组织架构','self':'本人','admin':'管理员'}
  for x in its:
   parts=[p for p in str(x.get('permission_key') or '').split('.') if p];resource=parts[0] if parts else '';action=parts[-1] if parts else ''
   # 始终根据 permission_key 生成权威中文释义，避免数据库中遗留的英文 key 被原样返回
   x['display_name']=' · '.join(resource_zh.get(p,action_zh.get(p,p)) for p in parts)
   x['resource']=resource_zh.get(resource,resource or '其他')
   if not x.get('description') or x.get('description')==x.get('permission_key'):x['description']='用于'+x['display_name']+'；实际数据可见性由角色绑定范围决定。'
   x['recommendation']=('仅建议授予受控管理员并定期复核。' if action in ('delete','manage','approve') else ('建议按职责授予并限制数据范围。' if action in ('create','update','bind','export','restore','recalculate','disable','rename','identity') else '可按岗位需要授予只读访问。'))
   risk=str(x.get('risk_level') or '').lower();x['risk_level']=risk if risk in ('low','medium','high','critical') else ('high' if action in ('delete','manage','approve') else ('medium' if action in ('create','update','bind','export','restore','recalculate','disable','rename','identity') else 'low'))
   x['recommendation']=x.get('recommendation') or ('仅建议授予受控管理员并定期复核。' if x['risk_level'] in ('high','critical') else '遵循岗位职责和最小范围授予。')
   x['scope_names']=scope_mask_names(x.get('scope_mask'))
  return h.sendj({'ok':True,'items':its}) or True
 if root=='roles':
  if not (platform(db,a) or can(db,a,'role.read',organization_id=org)):return bad(h,'FORBIDDEN','无角色读取权限',403)
  if m=='GET' and not ident:
   with db.tx(False) as c:
    n=now_ms();soon=n+7*86400000;its=rows(c,"""SELECT r.*,group_concat(rp.permission_key) permissions,
     (SELECT count(DISTINCT b.user_id) FROM role_bindings b WHERE b.role_id=r.role_id AND (b.organization_id=? OR b.organization_id IS NULL) AND b.status='active' AND (b.valid_from IS NULL OR b.valid_from<=?) AND (b.expires_at IS NULL OR b.expires_at>?)) member_count,
     (SELECT count(*) FROM role_bindings b WHERE b.role_id=r.role_id AND b.status='active' AND b.valid_from>?) pending_count,
     (SELECT count(*) FROM role_bindings b WHERE b.role_id=r.role_id AND b.status='active' AND b.expires_at>? AND b.expires_at<=?) expiring_count,
     (SELECT count(*) FROM role_permissions x JOIN permissions p ON p.permission_key=x.permission_key WHERE x.role_id=r.role_id AND p.risk_level IN ('high','critical')) high_risk_count
     FROM roles r LEFT JOIN role_permissions rp ON rp.role_id=r.role_id WHERE r.organization_id IS NULL OR r.organization_id=? GROUP BY r.role_id ORDER BY r.is_system DESC,r.scope_level,r.name""",(org,n,n,n,n,soon,org))
    for item in its:item['role_type']='platform_protected' if item['role_id']=='role_superadmin' else ('standard_template' if item.get('is_system') or item.get('organization_id') is None else 'enterprise_custom')
   return h.sendj({'ok':True,'items':its}) or True
  if ident and m=='GET' and action is None:
   with db.tx(False) as c:
    item=one(c,'SELECT * FROM roles WHERE role_id=? AND (organization_id IS NULL OR organization_id=?)',(ident,org))
    if item:
      item['permissionKeys']=[x[0] for x in c.execute('SELECT permission_key FROM role_permissions WHERE role_id=? ORDER BY permission_key',(ident,))]
      item['members']=rows(c,"SELECT b.*,u.login_name,u.display_name FROM role_bindings b JOIN users u ON u.user_id=b.user_id WHERE b.role_id=? AND (b.organization_id=? OR b.organization_id IS NULL) AND b.status='active' AND (b.valid_from IS NULL OR b.valid_from<=?) AND (b.expires_at IS NULL OR b.expires_at>?) ORDER BY u.display_name",(ident,org,now_ms(),now_ms()))
   if not item:return bad(h,'NOT_FOUND','角色不存在',404)
   return h.sendj({'ok':True,'item':item}) or True
  if ident and action=='members' and m=='GET':
   with db.tx(False) as c:
    role=one(c,'SELECT role_id FROM roles WHERE role_id=? AND (organization_id IS NULL OR organization_id=?)',(ident,org))
    its=rows(c,"SELECT b.*,u.login_name,u.display_name FROM role_bindings b JOIN users u ON u.user_id=b.user_id WHERE b.role_id=? AND (b.organization_id=? OR b.organization_id IS NULL) AND b.status='active' AND (b.valid_from IS NULL OR b.valid_from<=?) AND (b.expires_at IS NULL OR b.expires_at>?) ORDER BY u.display_name,b.created_at",(ident,org,now_ms(),now_ms())) if role else []
   if not role:return bad(h,'NOT_FOUND','角色不存在',404)
   return h.sendj({'ok':True,'items':its,'total':len(its)}) or True
  if ident and action=='delete-preview' and m=='GET':
   with db.tx(False) as c:
    role=one(c,'SELECT * FROM roles WHERE role_id=? AND (organization_id IS NULL OR organization_id=?)',(ident,org))
    cnt=c.execute("SELECT count(*) FROM role_bindings WHERE role_id=? AND status='active'",(ident,)).fetchone()[0] if role else 0
   if not role:return bad(h,'NOT_FOUND','角色不存在',404)
   return h.sendj({'ok':True,'roleId':ident,'systemRole':bool(role.get('is_system') or role.get('organization_id') is None),'activeBindingCount':cnt,'canDelete':bool(role.get('organization_id')==org and not role.get('is_system') and cnt==0)}) or True
  if m=='POST' and not ident:
   if not (platform(db,a) or can(db,a,'role.manage',organization_id=org)):return bad(h,'FORBIDDEN','无角色管理权限',403)
   b=h.body();name=str(b.get('name') or '').strip();code=str(b.get('roleCode') or '').strip() or None;scope=str(b.get('scopeLevel') or 'organization').strip();desc=str(b.get('description') or '').strip();perms=sorted(set(str(x) for x in (b.get('permissionKeys') or [])))
   if not name:return bad(h,'NAME_REQUIRED','角色名称不能为空')
   if scope not in ('organization','workspace','department','team','self'):return bad(h,'INVALID_SCOPE','自定义角色不允许平台作用域')
   ctx={'name':name,'organizationId':org,'permissionKeys':perms,'scopeLevel':scope}
   if not consume_confirmation(db,a,'role.create',h.headers.get('X-RBAC-Confirmation',''),ctx):return bad(h,'CONFIRMATION_REQUIRED','高风险确认凭证无效或已过期',428)
   rid='role_'+uuid.uuid4().hex;w=None
   try:
    with db.tx() as c:
     perms=validate_role_permissions_in_tx(c,scope,perms)
     w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? AND status='active' ORDER BY CASE workspace_id WHEN 'ws-global' THEN 0 ELSE 1 END, created_at, workspace_id LIMIT 1",(org,)).fetchone()
     if not w:return bad(h,'WORKSPACE_REQUIRED','当前企业缺少有效业务空间',409)
     c.execute("INSERT INTO roles(role_id,organization_id,name,scope_level,status,role_code,description,is_system) VALUES(?,?,?,?,?,?,?,0)",(rid,org,name,scope,'active',code or rid,desc))
     c.executemany('INSERT INTO role_permissions(role_id,permission_key) VALUES(?,?)',[(rid,x) for x in perms])
     item=one(c,'SELECT * FROM roles WHERE role_id=?',(rid,));audit_in_tx(c,a,'create','role',rid,{},item,wid=w[0])
   except ValueError as e:return bad(h,str(e),'权限不存在或不允许授予到该角色范围',400)
   except sqlite3.IntegrityError:return bad(h,'ROLE_CONFLICT','角色名称、代码或权限冲突',409)
   return h.sendj({'ok':True,'roleId':rid,'item':item},201) or True
  if ident and action=='copy' and m=='POST':
   if not (platform(db,a) or can(db,a,'role.manage',organization_id=org)):return bad(h,'FORBIDDEN','无角色管理权限',403)
   b=h.body();name=str(b.get('name') or '').strip()
   if not name:return bad(h,'NAME_REQUIRED','新角色名称不能为空')
   ctx={'name':name,'organizationId':org,'sourceRoleId':ident}
   if not consume_confirmation(db,a,'role.copy',h.headers.get('X-RBAC-Confirmation',''),ctx):return bad(h,'CONFIRMATION_REQUIRED','高风险确认凭证无效或已过期',428)
   rid='role_'+uuid.uuid4().hex
   try:
    with db.tx() as c:
     src=one(c,'SELECT * FROM roles WHERE role_id=? AND (organization_id IS NULL OR organization_id=?)',(ident,org))
     if not src:return bad(h,'NOT_FOUND','源角色不存在',404)
     scope=src['scope_level'] if src['scope_level']!='platform' else 'organization';w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? AND status='active' ORDER BY CASE workspace_id WHEN 'ws-global' THEN 0 ELSE 1 END, created_at, workspace_id LIMIT 1",(org,)).fetchone()
     if not w:return bad(h,'WORKSPACE_REQUIRED','当前企业缺少有效业务空间',409)
     c.execute("INSERT INTO roles(role_id,organization_id,name,scope_level,status,role_code,description,is_system) VALUES(?,?,?,?,?,?,?,0)",(rid,org,name,scope,'active',rid,str(src.get('description') or '')))
     c.execute('INSERT INTO role_permissions(role_id,permission_key) SELECT ?,permission_key FROM role_permissions WHERE role_id=?',(rid,ident));item=one(c,'SELECT * FROM roles WHERE role_id=?',(rid,));audit_in_tx(c,a,'copy','role',rid,src,item,wid=w[0])
   except sqlite3.IntegrityError:return bad(h,'ROLE_CONFLICT','新角色名称冲突',409)
   return h.sendj({'ok':True,'roleId':rid,'item':item},201) or True
  if ident and m=='PATCH' and action is None:
   if not (platform(db,a) or can(db,a,'role.manage',organization_id=org)):return bad(h,'FORBIDDEN','无角色管理权限',403)
   b=h.body()
   with db.tx(False) as c:old=one(c,'SELECT * FROM roles WHERE role_id=? AND organization_id=? AND is_system=0',(ident,org));oldperms=sorted(x[0] for x in c.execute('SELECT permission_key FROM role_permissions WHERE role_id=?',(ident,))) if old else []
   if not old:return bad(h,'ROLE_IMMUTABLE','角色不存在或系统角色不可编辑',403)
   name=str(b.get('name') if b.get('name') is not None else old['name']).strip();scope=str(b.get('scopeLevel') if b.get('scopeLevel') is not None else old['scope_level']);status=str(b.get('status') if b.get('status') is not None else old['status']);desc=str(b.get('description') if b.get('description') is not None else old.get('description') or '');perms=sorted(set(str(x) for x in (b.get('permissionKeys') if b.get('permissionKeys') is not None else oldperms)))
   if not name or scope not in ('organization','workspace','department','team','self') or status not in ('active','disabled','archived'):return bad(h,'INVALID_ROLE','角色字段不合法')
   ctx={'name':name,'organizationId':org,'permissionKeys':perms,'roleId':ident,'scopeLevel':scope,'status':status}
   if not consume_confirmation(db,a,'role.update',h.headers.get('X-RBAC-Confirmation',''),ctx):return bad(h,'CONFIRMATION_REQUIRED','高风险确认凭证无效或已过期',428)
   try:
    with db.tx() as c:
     perms=validate_role_permissions_in_tx(c,scope,perms)
     w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? AND status='active' ORDER BY CASE workspace_id WHEN 'ws-global' THEN 0 ELSE 1 END, created_at, workspace_id LIMIT 1",(org,)).fetchone()
     c.execute('UPDATE roles SET name=?,scope_level=?,status=?,description=? WHERE role_id=?',(name,scope,status,desc,ident));c.execute('DELETE FROM role_permissions WHERE role_id=?',(ident,));c.executemany('INSERT INTO role_permissions(role_id,permission_key) VALUES(?,?)',[(ident,x) for x in perms])
     affected=0
     for u in c.execute("SELECT DISTINCT user_id FROM role_bindings WHERE role_id=? AND status='active'",(ident,)).fetchall():affected+=revoke_sessions_in_tx(c,u[0],a['user_id'],'role_permissions_changed')
     item=one(c,'SELECT * FROM roles WHERE role_id=?',(ident,));audit_in_tx(c,a,'update','role',ident,old,item,str(b.get('reason') or ''),w[0] if w else None)
   except ValueError as e:return bad(h,str(e),'权限不存在或不允许授予到该角色范围',400)
   except sqlite3.IntegrityError:return bad(h,'ROLE_CONFLICT','角色名称、代码或权限冲突',409)
   return h.sendj({'ok':True,'item':item,'revokedSessionCount':affected}) or True
  if ident and m=='DELETE' and action is None:
   if not (platform(db,a) or can(db,a,'role.manage',organization_id=org)):return bad(h,'FORBIDDEN','无角色管理权限',403)
   ctx={'organizationId':org,'roleId':ident}
   if not consume_confirmation(db,a,'role.delete',h.headers.get('X-RBAC-Confirmation',''),ctx):return bad(h,'CONFIRMATION_REQUIRED','高风险确认凭证无效或已过期',428)
   with db.tx() as c:
    old=one(c,'SELECT * FROM roles WHERE role_id=? AND organization_id=? AND is_system=0',(ident,org))
    if not old:return bad(h,'ROLE_IMMUTABLE','角色不存在或系统角色不可删除',403)
    cnt=c.execute("SELECT count(*) FROM role_bindings WHERE role_id=? AND status='active'",(ident,)).fetchone()[0]
    if cnt:return bad(h,'ROLE_IN_USE','角色仍有有效授权，不能删除',409)
    w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? AND status='active' ORDER BY CASE workspace_id WHEN 'ws-global' THEN 0 ELSE 1 END, created_at, workspace_id LIMIT 1",(org,)).fetchone();c.execute('DELETE FROM role_permissions WHERE role_id=?',(ident,));c.execute('DELETE FROM roles WHERE role_id=?',(ident,));audit_in_tx(c,a,'delete','role',ident,old,{},wid=w[0] if w else None)
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
  if ident and m=='DELETE':
   if not manage(db,a,'team.manage',org):return bad(h,'FORBIDDEN','无工作区删除权限',403)
   with db.tx() as c:
    old=one(c,'SELECT * FROM workspaces WHERE workspace_id=? AND organization_id=?',(ident,org))
    if not old:return bad(h,'NOT_FOUND','工作区不存在',404)
    refs={'sources':c.execute('SELECT count(*) FROM sources WHERE workspace_id=? AND status=\'active\'',(ident,)).fetchone()[0],'devices':c.execute('SELECT count(*) FROM devices WHERE workspace_id=? AND status=\'active\'',(ident,)).fetchone()[0],'contacts':c.execute('SELECT count(*) FROM contacts WHERE workspace_id=?',(ident,)).fetchone()[0],'campaigns':c.execute('SELECT count(*) FROM campaigns WHERE workspace_id=? AND status IN (\'draft\',\'active\',\'paused\')',(ident,)).fetchone()[0],'tags':c.execute('SELECT count(*) FROM tags WHERE workspace_id=?',(ident,)).fetchone()[0],'fields':c.execute('SELECT count(*) FROM custom_field_definitions WHERE workspace_id=?',(ident,)).fetchone()[0]}
    refs={k:v for k,v in refs.items() if v}
    if refs:return bad(h,'WORKSPACE_IN_USE','工作区仍被业务对象引用，无法删除',409,references=refs)
    c.execute('DELETE FROM workspace_configs WHERE workspace_id=?',(ident,))
    c.execute('DELETE FROM workspace_teams WHERE workspace_id=?',(ident,))
    c.execute('DELETE FROM workspace_business_lines WHERE workspace_id=?',(ident,))
    c.execute('DELETE FROM workspace_markets WHERE workspace_id=?',(ident,))
    c.execute('DELETE FROM workspaces WHERE workspace_id=?',(ident,))
    audit_in_tx(c,a,'delete','workspace',ident,old,{},ident)
   return h.sendj({'ok':True}) or True
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

 # P2 字典摘要 API
 if root=='dictionaries' and m=='GET':
  if not org_ok(db,a,org):return bad(h,'FORBIDDEN','无权限',403)
  with db.tx(False) as c:
   # 如果请求特定子资源
   if ident in ('platform-channels','runtime'):
    # P1：统一运行时字典入口，前端不再维护来源和渠道业务枚举。
    platform_channels={}
    platforms=rows(c,"SELECT platform_id,platform_code,platform_name FROM platforms WHERE status='active' ORDER BY platform_code")
    for p in platforms:
     channels=rows(c,"SELECT channel_type_id,channel_type_code,name,direction FROM channel_types WHERE platform_id=? AND is_active=1 ORDER BY sort_order,name",(p['platform_id'],))
     platform_channels[p['platform_id']]={'platform_code':p['platform_code'],'platform_name':p['platform_name'],'channel_types':channels}
    if ident=='platform-channels':return h.sendj({'ok':True,'data':platform_channels}) or True
    data={'platforms':platform_channels,
     'source_types':rows(c,"SELECT source_type_id,source_type_code,name,description FROM source_type_definitions WHERE is_active=1 ORDER BY sort_order,name"),
     'directions':[{'value':'inbound','label':'入站'},{'value':'outbound','label':'出站'},{'value':'bidirectional','label':'双向'},{'value':'unknown','label':'未知'}],
     'channel_directions':[{'value':'inbound','label':'入站'},{'value':'outbound','label':'出站'},{'value':'both','label':'双向'}],
     'account_purposes':[{'value':'chat','label':'日常聊天','requiresChannel':False},{'value':'internal','label':'内部协作','requiresChannel':False},{'value':'login','label':'普通平台登录','requiresChannel':False},{'value':'service','label':'客户服务','requiresChannel':True},{'value':'marketing','label':'营销触达','requiresChannel':True},{'value':'advertising','label':'广告投放','requiresChannel':True},{'value':'attribution','label':'来源归因','requiresChannel':True}],
     'identity_types':[{'value':'login','label':'登录名账号'},{'value':'phone','label':'手机号码'},{'value':'email','label':'邮箱'},{'value':'username','label':'用户名'}]}
    return h.sendj({'ok':True,'data':data}) or True

   # 默认返回所有字典摘要
   platforms_count=c.execute("SELECT count(*) FROM platforms").fetchone()[0]
   platforms_active=c.execute("SELECT count(*) FROM platforms WHERE status='active'").fetchone()[0]
   channels_count=c.execute("SELECT count(*) FROM channel_types").fetchone()[0]
   channels_active=c.execute("SELECT count(*) FROM channel_types WHERE is_active=1").fetchone()[0]
   sources_count=c.execute("SELECT count(*) FROM source_type_definitions").fetchone()[0]
   sources_active=c.execute("SELECT count(*) FROM source_type_definitions WHERE is_active=1").fetchone()[0]
   
   return h.sendj({'ok':True,'dictionaries':{
    'platforms':{'count':platforms_count,'active':platforms_active},
    'channel_types':{'count':channels_count,'active':channels_active},
    'source_types':{'count':sources_count,'active':sources_active}
   }}) or True

 # P1 字典 API：渠道类型与来源类型
 if root=='channel-types':
  body=h.body() if m in ('POST','PUT','PATCH','DELETE') else {}
  payload,status=handle_channel_type(db,a,org,m,ident,q,body)
  return h.sendj(payload,status) or True
 if root=='source-types':
  body=h.body() if m in ('POST','PUT','PATCH','DELETE') else {}
  payload,status=handle_source_type(db,a,org,m,ident,q,body)
  return h.sendj(payload,status) or True
 if root=='campaigns':
  body=h.body() if m in ('POST','PUT','PATCH','DELETE') else {}
  payload,status=handle_campaign(db,a,org,m,ident,q,body)
  return h.sendj(payload,status) or True
 # campaign aggregation (stats, funnel)
 if root=='campaign-stats' and m=='GET':
  if not (platform(db,a) or can(db,a,'campaign.read')):return bad(h,'FORBIDDEN','无权限',403)
  with db.tx(False) as c:
   status_dist=rows(c,'SELECT status name,count(*) value FROM campaigns WHERE organization_id=? GROUP BY status',(org,))
   type_dist=rows(c,'SELECT campaign_type name,count(*) value FROM campaigns WHERE organization_id=? GROUP BY campaign_type',(org,))
   recent=rows(c,'SELECT campaign_id,campaign_name,status,campaign_type,start_at,end_at FROM campaigns WHERE organization_id=? ORDER BY created_at DESC LIMIT 5',(org,))
   total=c.execute('SELECT count(*) FROM campaigns WHERE organization_id=?',(org,)).fetchone()[0]
   active=c.execute("SELECT count(*) FROM campaigns WHERE organization_id=? AND status='active'",(org,)).fetchone()[0]
  return h.sendj({'ok':True,'total':total,'active':active,'statusDistribution':status_dist,'typeDistribution':type_dist,'recentCampaigns':recent}) or True
 # touchpoints delegation
 if root=='touchpoints':
  b=h.body() if m in ('POST','PATCH','DELETE') else {}
  payload,status=handle_touchpoint(db,a,org,m,seg[1] if len(seg)>1 else None,q,b)
  return h.sendj(payload,status) or True
 if root=='conversions':
  b=h.body() if m in ('POST','PATCH','DELETE') else {}
  payload,status=handle_conversion(db,a,org,m,seg[1] if len(seg)>1 else None,q,b)
  return h.sendj(payload,status) or True
 if root=='attributions':
  b=h.body() if m in ('POST','PATCH','DELETE') else {}
  ident=seg[1] if len(seg)>1 else None
  payload,status=handle_attribution(db,a,org,m,ident,q,b)
  return h.sendj(payload,status) or True
 # attribution aggregation: source contribution + funnel summary
 if root=='attribution-summary' and m=='GET':
  if not (platform(db,a) or can(db,a,'attribution.read')):return bad(h,'FORBIDDEN','无权限',403)
  with db.tx(False) as c:
   src_attr=rows(c,'SELECT s.source_name,s.channel,a.attribution_type,count(*) touchpoint_count FROM contact_attributions a JOIN sources s ON s.source_id=a.source_id WHERE a.organization_id=? GROUP BY s.source_id,a.attribution_type ORDER BY touchpoint_count DESC LIMIT 20',(org,))
   type_dist=rows(c,'SELECT attribution_type name,count(*) value FROM contact_attributions WHERE organization_id=? GROUP BY attribution_type',(org,))
   funnel=rows(c,"SELECT s.source_name,COALESCE(c.campaign_name,'未关联活动') campaign_name,a.is_primary,count(*) cnt FROM contact_attributions a JOIN sources s ON s.source_id=a.source_id LEFT JOIN campaigns c ON c.campaign_id=s.campaign_id WHERE a.organization_id=? GROUP BY s.source_id,COALESCE(c.campaign_name,'未关联活动'),a.is_primary ORDER BY cnt DESC LIMIT 10",(org,))
   total_attr=c.execute('SELECT count(*) FROM contact_attributions WHERE organization_id=?',(org,)).fetchone()[0]
   total_tp=c.execute('SELECT count(*) FROM source_touchpoints WHERE organization_id=?',(org,)).fetchone()[0]
  return h.sendj({'ok':True,'totalAttributions':total_attr,'totalTouchpoints':total_tp,'sourceContribution':src_attr,'typeDistribution':type_dist,'topSources':funnel}) or True
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
 # device enrollment invitations: pending invitations are separate from formal devices
 if root=='device-enrollments':
  if not (platform(db,a) or manage(db,a,'device.bind',org)):return bad(h,'FORBIDDEN','无设备绑定权限',403)
  if m=='GET':
   with db.tx() as c:
    now=now_ms();c.execute("UPDATE device_enrollments SET status='expired' WHERE organization_id=? AND status='pending' AND expires_at<=?",(org,now))
    its=rows(c,"SELECT e.enrollment_id,e.organization_id,e.workspace_id,e.team_id,e.assigned_user_id,e.admin_device_name,e.admin_computer_name,e.status,e.expires_at,e.consumed_at,e.consumed_device_id,e.created_by,e.created_at,e.revoked_at,e.revoked_by,e.reason,w.name workspace_name,t.name team_name,u.display_name assigned_user FROM device_enrollments e JOIN workspaces w ON w.workspace_id=e.workspace_id JOIN teams t ON t.team_id=e.team_id LEFT JOIN users u ON u.user_id=e.assigned_user_id WHERE e.organization_id=? ORDER BY e.created_at DESC",(org,))
   return h.sendj({'ok':True,'items':its}) or True
  if not ident and m=='POST':
   b=h.body();wid=str(b.get('workspaceId') or '').strip();tid=str(b.get('teamId') or '').strip();uid=str(b.get('assignedUserId') or '').strip();reason=str(b.get('reason') or '').strip()
   if not wid or not tid or not uid or not reason:return bad(h,'INVALID_INPUT','工作区、团队、指定用户和操作原因必填')
   try:hours=max(1,min(72,int(b.get('validHours') or 24)))
   except Exception:return bad(h,'INVALID_INPUT','有效时长必须为整数')
   with db.tx() as c:
    team=one(c,"SELECT t.*,wt.workspace_id authorized_workspace FROM teams t LEFT JOIN workspace_teams wt ON wt.team_id=t.team_id AND wt.workspace_id=? AND wt.status='active' WHERE t.team_id=? AND t.organization_id=? AND t.status='active'",(wid,tid,org))
    if not team or not (team.get('workspace_id')==wid or team.get('authorized_workspace')==wid):return bad(h,'TEAM_WORKSPACE_MISMATCH','团队不属于所选工作区',409)
    if not one(c,"SELECT 1 ok FROM users u JOIN team_memberships tm ON tm.user_id=u.user_id AND tm.team_id=? AND tm.status='active' WHERE u.user_id=? AND u.organization_id=? AND u.status='active'",(tid,uid,org)):return bad(h,'USER_TEAM_MISMATCH','用户不是目标团队的有效成员',409)
    raw=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(20));code='-'.join(raw[i:i+4] for i in range(0,20,4));eid='denr_'+secrets.token_hex(12);now=now_ms();exp=now+hours*3600*1000;digest=hashlib.sha256(raw.encode()).hexdigest()
    c.execute("INSERT INTO device_enrollments(enrollment_id,organization_id,workspace_id,team_id,assigned_user_id,admin_device_name,admin_computer_name,binding_code_hash,status,expires_at,created_by,created_at,reason) VALUES(?,?,?,?,?,?,?,?,'pending',?,?,?,?)",(eid,org,wid,tid,uid,str(b.get('deviceName') or '')[:120],str(b.get('computerName') or '')[:120],digest,exp,a['user_id'],now,reason))
    item=one(c,'SELECT * FROM device_enrollments WHERE enrollment_id=?',(eid,));audit_in_tx(c,a,'create','device_enrollment',eid,None,{k:v for k,v in item.items() if k!='binding_code_hash'},reason,wid)
   return h.sendj({'ok':True,'item':{k:v for k,v in item.items() if k!='binding_code_hash'},'invitationCode':code,'bindingCode':code},201) or True
  if ident and action=='revoke' and m=='POST':
   b=h.body();reason=str(b.get('reason') or '').strip()
   if not reason:return bad(h,'REASON_REQUIRED','操作原因必填')
   with db.tx() as c:
    old=one(c,'SELECT * FROM device_enrollments WHERE enrollment_id=? AND organization_id=?',(ident,org))
    if not old:return bad(h,'NOT_FOUND','设备接入邀请不存在',404)
    if old['status']!='pending':return bad(h,'STATE_CONFLICT','只有待核销邀请可以撤销',409)
    now=now_ms();c.execute("UPDATE device_enrollments SET status='revoked',revoked_at=?,revoked_by=? WHERE enrollment_id=? AND status='pending'",(now,a['user_id'],ident));new=one(c,'SELECT * FROM device_enrollments WHERE enrollment_id=?',(ident,));audit_in_tx(c,a,'revoke','device_enrollment',ident,{k:v for k,v in old.items() if k!='binding_code_hash'},{k:v for k,v in new.items() if k!='binding_code_hash'},reason,old['workspace_id'])
   return h.sendj({'ok':True,'item':{k:v for k,v in new.items() if k!='binding_code_hash'}}) or True
  return bad(h,'METHOD_NOT_ALLOWED','不支持的设备接入邀请操作',405)
 # devices generic list and state
 if root=='devices':
  if not ident and m=='GET':
   if not (platform(db,a) or can(db,a,'device.read')):return bad(h,'FORBIDDEN','无设备读取权限',403)
   with db.tx(False) as c:
    its=rows(c,"""SELECT d.*,t.name team_name,u.display_name assigned_user,
     (SELECT count(*) FROM source_devices sd WHERE sd.device_id=d.device_id) source_count,
     (SELECT count(*) FROM plugin_sessions ps WHERE ps.device_id=d.device_id AND ps.status='active' AND ps.expires_at>CAST(strftime('%s','now') AS INTEGER)*1000) active_plugin_sessions,
     (SELECT ps.client_version FROM plugin_sessions ps WHERE ps.device_id=d.device_id ORDER BY ps.last_seen_at DESC LIMIT 1) client_version,
     (SELECT MAX(ps.last_seen_at) FROM plugin_sessions ps WHERE ps.device_id=d.device_id AND ps.status='active' AND ps.expires_at>CAST(strftime('%s','now') AS INTEGER)*1000) last_session_seen
     FROM devices d LEFT JOIN teams t ON t.team_id=d.team_id LEFT JOIN users u ON u.user_id=d.assigned_user_id
     WHERE d.organization_id=? ORDER BY d.last_seen_at DESC""",(org,))
    bindings=rows(c,"""SELECT b.device_id,b.binding_id,b.channel_account_id,b.platform_id,b.external_account_key,b.status,b.bound_at,b.last_verified_at,
     ca.display_name account_name,p.platform_code,p.platform_name
     FROM device_channel_account_bindings b
     LEFT JOIN channel_accounts ca ON ca.channel_account_id=b.channel_account_id
     LEFT JOIN platforms p ON p.platform_id=b.platform_id
     WHERE b.organization_id=? AND b.status='active' ORDER BY b.last_verified_at DESC""",(org,))
    discoveries=rows(c,"""SELECT ad.device_id,ad.discovery_id,ad.channel_account_id,ad.platform_id,ad.identity_type,ad.canonical_value,ad.status,ad.reason_code,ad.last_seen_at,
     ca.display_name account_name,p.platform_code,p.platform_name
     FROM account_identity_discoveries ad
     LEFT JOIN channel_accounts ca ON ca.channel_account_id=ad.channel_account_id
     LEFT JOIN platforms p ON p.platform_id=ad.platform_id
     WHERE ad.organization_id=? AND ad.device_id IS NOT NULL AND ad.status IN ('pending','conflict','approved','auto_claimed')
     ORDER BY ad.last_seen_at DESC""",(org,))
   bind_by={};disc_by={}
   for z in bindings:bind_by.setdefault(z.get('device_id'),[]).append(z)
   for z in discoveries:disc_by.setdefault(z.get('device_id'),[]).append(z)
   now=now_ms();online_threshold_ms=120000;offline_threshold_ms=600000
   for x in its:
    last=int(x.get('last_session_seen') or 0) or None;age=max(0,now-int(last)) if last else None
    # Online status is session-liveness only; the device-level timestamp is a legacy snapshot.
    x['last_heartbeat_at']=last
    x['legacy_device_last_seen_at']=x.get('last_seen_at')
    x['heartbeat_age_ms']=age;x['online_threshold_ms']=online_threshold_ms;x['offline_threshold_ms']=offline_threshold_ms
    if x.get('status')!='active':x['online_status']='disabled'
    elif last is None:x['online_status']='unknown'
    elif age<=online_threshold_ms:x['online_status']='online'
    elif age<=offline_threshold_ms:x['online_status']='unstable'
    else:x['online_status']='offline'
    active=bind_by.get(x.get('device_id'),[]);found=disc_by.get(x.get('device_id'),[])
    active_keys={(z.get('channel_account_id'),z.get('platform_id')) for z in active}
    pending=[z for z in found if z.get('status') in ('pending','conflict')]
    awaiting=[z for z in found if z.get('status') in ('approved','auto_claimed') and z.get('channel_account_id') and (z.get('channel_account_id'),z.get('platform_id')) not in active_keys]
    x['running_accounts']=active;x['pending_identities']=pending;x['awaiting_recheck_identities']=awaiting
    x['pending_identity_count']=len(pending);x['awaiting_recheck_count']=len(awaiting)
    x['effective_account_count']=len({z.get('channel_account_id') for z in active+awaiting if z.get('channel_account_id')})
    labels=[]
    labels += [(z.get('account_name') or z.get('channel_account_id') or '未知账号')+' ['+(z.get('platform_code') or z.get('platform_id') or '未知平台')+' · 运行中]' for z in active]
    labels += [(z.get('canonical_value') or '未知身份')+' ['+(z.get('platform_code') or z.get('platform_id') or '未知平台')+' · '+('身份冲突' if z.get('status')=='conflict' else '待审批')+']' for z in pending]
    labels += [(z.get('canonical_value') or z.get('account_name') or '未知身份')+' ['+(z.get('platform_code') or z.get('platform_id') or '未知平台')+' · 已批准待复检]' for z in awaiting]
    x['running_accounts_display']='；'.join(labels) if labels else None
   return h.sendj({'ok':True,'items':its}) or True
  if ident and action=='sessions' and len(seg)==3 and m=='GET':
   if not (platform(db,a) or can(db,a,'device.read')):return bad(h,'FORBIDDEN','无设备会话读取权限',403)
   with db.tx(False) as c:
    if not one(c,'SELECT 1 ok FROM devices WHERE device_id=? AND organization_id=?',(ident,org)):return bad(h,'NOT_FOUND','设备不存在',404)
    its=rows(c,"SELECT ps.plugin_session_id,ps.workspace_id,ps.team_id,ps.user_id,u.display_name user_name,ps.status,ps.issued_at,ps.expires_at,ps.last_seen_at,ps.revoked_at,ps.revoked_by,ps.revoked_reason,ps.client_version,ps.metadata_json FROM plugin_sessions ps LEFT JOIN users u ON u.user_id=ps.user_id WHERE ps.device_id=? AND ps.organization_id=? ORDER BY ps.issued_at DESC",(ident,org))
   return h.sendj({'ok':True,'items':its}) or True
  if ident and action=='sessions' and len(seg)==5 and seg[4]=='revoke' and m=='POST':
   if not (platform(db,a) or manage(db,a,'device.disable',org)):return bad(h,'FORBIDDEN','无设备会话撤销权限',403)
   b=h.body();session_id=seg[3];reason=str(b.get('reason') or '').strip()
   if not reason:return bad(h,'REASON_REQUIRED','操作原因必填')
   with db.tx() as c:
    dev=one(c,'SELECT * FROM devices WHERE device_id=? AND organization_id=?',(ident,org))
    if not dev:return bad(h,'NOT_FOUND','设备不存在',404)
    old_session=one(c,'SELECT * FROM plugin_sessions WHERE plugin_session_id=? AND device_id=? AND organization_id=?',(session_id,ident,org))
    if not old_session:return bad(h,'NOT_FOUND','插件会话不存在',404)
    if old_session['status']=='active':c.execute("UPDATE plugin_sessions SET status='revoked',revoked_at=?,revoked_by=?,revoked_reason=? WHERE plugin_session_id=? AND status='active'",(now_ms(),a['user_id'],reason[:200],session_id))
    new_session=one(c,'SELECT * FROM plugin_sessions WHERE plugin_session_id=?',(session_id,));audit_in_tx(c,a,'revoke','plugin_session',session_id,old_session,new_session,reason,dev.get('workspace_id'))
   return h.sendj({'ok':True,'item':new_session}) or True
  if ident and action=='history' and m=='GET':
   if not (platform(db,a) or can(db,a,'device.read')):return bad(h,'FORBIDDEN','无设备读取权限',403)
   with db.tx(False) as c:
    if not one(c,'SELECT 1 ok FROM devices WHERE device_id=? AND organization_id=?',(ident,org)):return bad(h,'NOT_FOUND','设备不存在',404)
    its=rows(c,"SELECT da.*,u.display_name assigned_user,t.name team_name FROM device_assignments da LEFT JOIN users u ON u.user_id=da.assigned_user_id LEFT JOIN teams t ON t.team_id=da.team_id WHERE da.device_id=? ORDER BY da.assigned_at DESC",(ident,))
   return h.sendj({'ok':True,'items':its}) or True
  if ident and action=='rebind' and m=='GET':
   if not (platform(db,a) or can(db,a,'device.read')):return bad(h,'FORBIDDEN','无设备读取权限',403)
   with db.tx() as c:
    now=now_ms();c.execute("UPDATE device_rebind_requests SET status='expired' WHERE device_id=? AND organization_id=? AND status='pending' AND expires_at<?",(ident,org,now))
    its=rows(c,"SELECT r.rebind_id,r.device_id,r.from_user_id,r.to_user_id,r.from_team_id,r.to_team_id,r.to_workspace_id,r.status,r.expires_at,r.created_by,r.created_at,r.consumed_at,r.revoked_at,r.revoked_by,r.reason,u.display_name target_user,t.name target_team FROM device_rebind_requests r LEFT JOIN users u ON u.user_id=r.to_user_id LEFT JOIN teams t ON t.team_id=r.to_team_id WHERE r.device_id=? AND r.organization_id=? ORDER BY r.created_at DESC",(ident,org))
   return h.sendj({'ok':True,'items':its}) or True
  if ident and action=='rebind' and len(seg)==3 and m=='POST':
   if not (platform(db,a) or manage(db,a,'device.bind',org)):return bad(h,'FORBIDDEN','无设备换绑权限',403)
   b=h.body();tid=str(b.get('teamId') or '').strip();uid=str(b.get('assignedUserId') or '').strip();reason=str(b.get('reason') or '').strip()
   if not tid or not uid or not reason:return bad(h,'INVALID_INPUT','目标团队、目标用户和操作原因必填')
   try:minutes=max(5,min(1440,int(b.get('validMinutes') or 30)))
   except Exception:return bad(h,'INVALID_INPUT','有效分钟数必须为整数')
   with db.tx() as c:
    old=one(c,'SELECT * FROM devices WHERE device_id=? AND organization_id=?',(ident,org))
    if not old:return bad(h,'NOT_FOUND','设备不存在',404)
    if old.get('status')!='active':return bad(h,'DEVICE_DISABLED','只有启用设备可以换绑',409)
    team=one(c,"SELECT * FROM teams WHERE team_id=? AND organization_id=? AND status='active'",(tid,org))
    if not team:return bad(h,'TEAM_NOT_FOUND','目标团队不存在或未启用',404)
    wid=team['workspace_id']
    if not one(c,"SELECT 1 ok FROM users u JOIN team_memberships tm ON tm.user_id=u.user_id AND tm.team_id=? AND tm.status='active' WHERE u.user_id=? AND u.organization_id=? AND u.status='active'",(tid,uid,org)):return bad(h,'USER_TEAM_MISMATCH','用户不是目标团队的有效成员',409)
    now=now_ms();c.execute("UPDATE device_rebind_requests SET status='expired' WHERE device_id=? AND organization_id=? AND status='pending' AND expires_at<?",(ident,org,now))
    if one(c,"SELECT 1 ok FROM device_rebind_requests WHERE device_id=? AND organization_id=? AND status='pending'",(ident,org)):return bad(h,'REBIND_PENDING','该设备已有待核销换绑请求，请先撤销',409)
    raw=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(20));code='-'.join(raw[i:i+4] for i in range(0,20,4));rid='rbd_'+secrets.token_hex(12);exp=now+minutes*60000
    c.execute("INSERT INTO device_rebind_requests(rebind_id,organization_id,device_id,from_user_id,to_user_id,from_team_id,to_team_id,to_workspace_id,code_hash,status,expires_at,created_by,created_at,reason) VALUES(?,?,?,?,?,?,?,?,?,'pending',?,?,?,?)",(rid,org,ident,old.get('assigned_user_id'),uid,old.get('team_id'),tid,wid,hashlib.sha256(raw.encode()).hexdigest(),exp,a['user_id'],now,reason))
    revoked=c.execute("UPDATE plugin_sessions SET status='revoked',revoked_at=?,revoked_by=?,revoked_reason='device_rebind_pending' WHERE device_id=? AND organization_id=? AND status='active'",(now,a['user_id'],ident,org)).rowcount
    disabled=c.execute("UPDATE device_channel_account_bindings SET status='disabled' WHERE device_id=? AND organization_id=? AND status='active'",(ident,org)).rowcount
    item=one(c,'SELECT * FROM device_rebind_requests WHERE rebind_id=?',(rid,));audit_in_tx(c,a,'create','device_rebind_request',rid,None,{k:v for k,v in item.items() if k!='code_hash'},reason,old.get('workspace_id'))
   return h.sendj({'ok':True,'item':{k:v for k,v in item.items() if k!='code_hash'},'rebindCode':code,'revokedSessionCount':revoked,'disabledBindingCount':disabled},201) or True
  if ident and action=='rebind' and len(seg)==5 and seg[4]=='revoke' and m=='POST':
   if not (platform(db,a) or manage(db,a,'device.bind',org)):return bad(h,'FORBIDDEN','无设备换绑权限',403)
   rid=seg[3];b=h.body();reason=str(b.get('reason') or '').strip()
   if not reason:return bad(h,'REASON_REQUIRED','撤销原因必填')
   with db.tx() as c:
    old=one(c,"SELECT * FROM device_rebind_requests WHERE rebind_id=? AND device_id=? AND organization_id=?",(rid,ident,org))
    if not old:return bad(h,'NOT_FOUND','换绑请求不存在',404)
    if old['status']!='pending':return bad(h,'STATE_CONFLICT','只有待核销换绑请求可以撤销',409)
    now=now_ms();changed=c.execute("UPDATE device_rebind_requests SET status='revoked',revoked_at=?,revoked_by=? WHERE rebind_id=? AND status='pending'",(now,a['user_id'],rid)).rowcount
    if changed!=1:return bad(h,'STATE_CONFLICT','换绑请求状态已变化',409)
    new=one(c,'SELECT * FROM device_rebind_requests WHERE rebind_id=?',(rid,));audit_in_tx(c,a,'revoke','device_rebind_request',rid,{k:v for k,v in old.items() if k!='code_hash'},{k:v for k,v in new.items() if k!='code_hash'},reason,old.get('to_workspace_id'))
   return h.sendj({'ok':True,'item':{k:v for k,v in new.items() if k!='code_hash'}}) or True
  if ident and action=='assign' and m=='POST':
   if not (platform(db,a) or manage(db,a,'device.bind',org)):return bad(h,'FORBIDDEN','无设备分配权限',403)
   b=h.body();tid=str(b.get('teamId') or '').strip();uid=str(b.get('assignedUserId') or '').strip();reason=str(b.get('reason') or '').strip()
   if not tid or not uid or not reason:return bad(h,'INVALID_INPUT','团队、用户和操作原因必填')
   with db.tx() as c:
    old=one(c,'SELECT * FROM devices WHERE device_id=? AND organization_id=?',(ident,org))
    if not old:return bad(h,'NOT_FOUND','设备不存在',404)
    if not one(c,"SELECT 1 ok FROM users u JOIN team_memberships tm ON tm.user_id=u.user_id AND tm.team_id=? AND tm.status='active' JOIN teams t ON t.team_id=tm.team_id WHERE u.user_id=? AND u.organization_id=? AND u.status='active' AND t.organization_id=? AND t.status='active'",(tid,uid,org,org)):return bad(h,'USER_TEAM_MISMATCH','用户不是目标团队的有效成员',409)
    team=one(c,"SELECT * FROM teams WHERE team_id=? AND organization_id=? AND status='active'",(tid,org))
    if not team:return bad(h,'TEAM_NOT_FOUND','目标团队不存在、未启用或不属于当前企业',404)
    now=now_ms();c.execute('UPDATE device_assignments SET released_at=? WHERE device_id=? AND released_at IS NULL',(now,ident));c.execute('INSERT INTO device_assignments(assignment_id,device_id,assigned_user_id,team_id,assigned_at,released_at) VALUES(?,?,?,?,?,NULL)',('asn_'+secrets.token_hex(12),ident,uid,tid,now));c.execute('UPDATE devices SET workspace_id=?,team_id=?,assigned_user_id=? WHERE device_id=?',(team['workspace_id'],tid,uid,ident))
    revoked=c.execute("UPDATE plugin_sessions SET status='revoked',revoked_at=?,revoked_by=?,revoked_reason='device_reassigned' WHERE device_id=? AND organization_id=? AND status='active'",(now,a['user_id'],ident,org)).rowcount
    disabled_bindings=c.execute("UPDATE device_channel_account_bindings SET status='disabled' WHERE device_id=? AND organization_id=? AND status='active'",(ident,org)).rowcount
    new=one(c,'SELECT * FROM devices WHERE device_id=?',(ident,));audit_in_tx(c,a,'assign','device',ident,old,new,reason,team['workspace_id'])
    return h.sendj({'ok':True,'item':new,'revokedSessionCount':revoked,'disabledBindingCount':disabled_bindings}) or True
  if ident and not action and m=='GET':
   if not (platform(db,a) or can(db,a,'device.read')):return bad(h,'FORBIDDEN','无设备读取权限',403)
   with db.tx(False) as c:item=one(c,"SELECT d.*,t.name team_name,u.display_name assigned_user FROM devices d LEFT JOIN teams t ON t.team_id=d.team_id LEFT JOIN users u ON u.user_id=d.assigned_user_id WHERE d.device_id=? AND d.organization_id=?",(ident,org))
   if not item:return bad(h,'NOT_FOUND','设备不存在',404)
   item['display_name']=item.get('admin_device_name') or item.get('user_device_alias') or item.get('system_device_name') or ident
   return h.sendj({'ok':True,'item':item}) or True
  if ident and not action and m=='PATCH':
   if not manage(db,a,'device.disable',org):return bad(h,'FORBIDDEN','无资源管理权限',403)
   b=h.body();reason=str(b.get('reason') or '').strip()
   if not reason:return bad(h,'REASON_REQUIRED','操作原因必填')
   with db.tx() as c:
    old=one(c,'SELECT * FROM devices WHERE device_id=? AND organization_id=?',(ident,org))
    if not old:return bad(h,'NOT_FOUND','资源不存在',404)
    new_status=clean_status(b.get('status')) or old['status'];now=now_ms()
    c.execute('UPDATE devices SET admin_device_name=?,admin_computer_name=?,status=? WHERE device_id=?',(str(b.get('deviceName') if b.get('deviceName') is not None else old.get('admin_device_name') or ''),str(b.get('computerName') if b.get('computerName') is not None else old.get('admin_computer_name') or ''),new_status,ident))
    revoked=disabled_bindings=0
    if old.get('status')=='active' and new_status!='active':
     revoked=c.execute("UPDATE plugin_sessions SET status='revoked',revoked_at=?,revoked_by=?,revoked_reason='device_disabled' WHERE device_id=? AND organization_id=? AND status='active'",(now,a['user_id'],ident,org)).rowcount
     disabled_bindings=c.execute("UPDATE device_channel_account_bindings SET status='disabled' WHERE device_id=? AND organization_id=? AND status='active'",(ident,org)).rowcount
    new=one(c,'SELECT * FROM devices WHERE device_id=?',(ident,));audit_in_tx(c,a,'update','device',ident,old,new,reason,old.get('workspace_id'))
    return h.sendj({'ok':True,'item':new,'revokedSessionCount':revoked,'disabledBindingCount':disabled_bindings}) or True
  if ident and not action and m=='DELETE':
   if not (platform(db,a) or manage(db,a,'device.disable',org)):return bad(h,'FORBIDDEN','无设备删除权限',403)
   with db.tx() as c:
    old=one(c,'SELECT * FROM devices WHERE device_id=? AND organization_id=?',(ident,org))
    if not old:return bad(h,'NOT_FOUND','资源不存在',404)
    refs={'pluginSessions':c.execute('SELECT count(*) FROM plugin_sessions WHERE device_id=?',(ident,)).fetchone()[0],'accountBindings':c.execute('SELECT count(*) FROM device_channel_account_bindings WHERE device_id=?',(ident,)).fetchone()[0],'assignments':c.execute('SELECT count(*) FROM device_assignments WHERE device_id=?',(ident,)).fetchone()[0],'sources':c.execute('SELECT count(*) FROM source_devices WHERE device_id=?',(ident,)).fetchone()[0],'enrollments':c.execute('SELECT count(*) FROM device_enrollments WHERE consumed_device_id=?',(ident,)).fetchone()[0],'contacts':c.execute('SELECT count(*) FROM contacts WHERE last_observed_device_id=?',(ident,)).fetchone()[0],'auditLogs':c.execute("SELECT count(*) FROM audit_logs WHERE device_id=? OR (entity_type='device' AND entity_id=?)",(ident,ident)).fetchone()[0]}
    refs={k:v for k,v in refs.items() if v}
    if refs:return h.sendj({'ok':False,'code':'DEVICE_IN_USE','message':'设备存在业务或接入历史，只能停用，不能物理删除','references':refs},409) or True
    c.execute('DELETE FROM devices WHERE device_id=?',(ident,))
    audit_in_tx(c,a,'delete','device',ident,old,{},old.get('workspace_id'))
   return h.sendj({'ok':True}) or True
# contacts (admin table + direct business edit, lifecycle remains old guarded endpoints)
 if root=='contact-identities' and m=='GET':
  if not (platform(db,a) or can(db,a,'contact.read')):return bad(h,'FORBIDDEN','无联系人读取权限',403)
  pno,size,off=page(q)
  with db.tx(False) as c:
   scope,scope_args,_=data_scope_clause_in_tx(c,a,'contact.read',org,alias='c')
   where='i.organization_id=? AND c.organization_id=? AND c.deleted_at IS NULL AND ('+scope+')'
   args=[org,org]+scope_args
   total=c.execute('SELECT count(*) FROM contact_identities i JOIN contacts c ON c.contact_id=i.contact_id WHERE '+where,args).fetchone()[0]
   its=rows(c,'SELECT i.*,p.platform_name,p.platform_code,c.manual_name,c.display_name FROM contact_identities i LEFT JOIN platforms p ON p.platform_id=i.platform_id JOIN contacts c ON c.contact_id=i.contact_id WHERE '+where+' ORDER BY i.last_seen_at DESC,i.contact_identity_id LIMIT ? OFFSET ?',args+[size,off])
  return h.sendj(pack(its,total,pno,size)) or True
 if root=='contacts':
  # Parse locally because earlier route branches reuse contact_id/action.
  contact_id=seg[1] if len(seg)>1 else None
  contact_action=seg[2] if len(seg)>2 else None
  contact_identity_id=seg[3] if len(seg)>3 else None
  # Contact identities are isolated in their domain service; keep the legacy route contract.
  handled=handle_contact_identity(h,m,seg,q,a,db,org)
  if handled:return handled
  if len(seg)==1 and m=='POST':
   if not manage(db,a,'contact.update',org):return bad(h,'FORBIDDEN','无联系人创建权限',403)
   b=h.body();name=str(b.get('manualName') or b.get('displayName') or '').strip();phone=str(b.get('manualPhone') or '').strip();wid=str(b.get('workspaceId') or '').strip();sid=str(b.get('sourceId') or '').strip()
   if not name or not wid or not sid:return bad(h,'INVALID_CONTACT','姓名、工作区和来源均为必填')
   n=now_ms();cid='ct_'+uuid.uuid4().hex;external='manual_'+uuid.uuid4().hex;typ=str(b.get('identityType') or 'external_id');value=str(b.get('identityValue') or phone or external).strip();canonical=value.lower();iid='cid_'+uuid.uuid4().hex
   with db.tx() as c:
    src=one(c,"SELECT source_id,workspace_id,team_id,channel FROM sources WHERE source_id=? AND organization_id=? AND status='active'",(sid,org))
    if not src or src['workspace_id']!=wid:return bad(h,'SOURCE_SCOPE_MISMATCH','来源不存在或不属于所选工作区',400)
    c.execute('INSERT INTO contacts(contact_id,workspace_id,source_id,channel,external_contact_id,display_name,manual_name,manual_phone,status,created_at,updated_at,last_seen_at,organization_id,team_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(cid,wid,sid,src['channel'] or 'manual',external,name,name,phone,'active',n,n,n,org,src['team_id']))
    c.execute('INSERT INTO contact_identities(contact_identity_id,organization_id,workspace_id,contact_id,platform_id,identity_type,identity_value,canonical_value,verification_status,is_primary,first_seen_at,last_seen_at,metadata_json) VALUES(?,?,?,?,NULL,?,?,?,?,1,?,?,?)',(iid,org,wid,cid,typ,value,canonical,'unverified',n,n,dumps({'source':'admin_manual'})))
    audit_in_tx(c,a,'create','contact',cid,{},b,wid=wid)
   return h.sendj({'ok':True,'contactId':cid,'identityId':iid},201) or True
  if len(seg)==1 and m=='GET':
   pno,size,off=page(q);search='%'+str(q.get('q') or '')+'%';deleted=str(q.get('deleted','all')).lower();deleted={'only':'yes','deleted':'yes','1':'yes','true':'yes','none':'no','active':'no','0':'no','false':'no'}.get(deleted,deleted)
   base_cond="c.organization_id=? AND (?='all' OR (?='yes' AND c.deleted_at IS NOT NULL) OR (?='no' AND c.deleted_at IS NULL)) AND (c.display_name LIKE ? OR c.manual_name LIKE ? OR c.observed_phone LIKE ? OR c.manual_phone LIKE ?)";base_args=[org,deleted,deleted,deleted,search,search,search,search]
   with db.tx(False) as c:
    scope,scope_args,_=data_scope_clause_in_tx(c,a,'contact.read',org,alias='c');cond=base_cond+' AND ('+scope+')';args=base_args+scope_args
    total=c.execute('SELECT count(*) FROM contacts c WHERE '+cond,args).fetchone()[0];its=rows(c,'SELECT c.*,s.source_name,t.name team_name FROM contacts c LEFT JOIN sources s ON s.source_id=c.source_id LEFT JOIN teams t ON t.team_id=c.team_id WHERE '+cond+' ORDER BY c.updated_at DESC LIMIT ? OFFSET ?',args+[size,off])
   return h.sendj(pack(its,total,pno,size)) or True
  if contact_id and len(seg)==2 and m=='DELETE':
   if not manage(db,a,'contact.update',org):return bad(h,'FORBIDDEN','无联系人软删除权限',403)
   b=h.body();reason=str(b.get('reason') or '').strip()
   if not reason:return bad(h,'REASON_REQUIRED','软删除原因必填')
   with db.tx() as c:
    scope,scope_args,_=data_scope_clause_in_tx(c,a,'contact.read',org,alias='c');old=one(c,'SELECT c.* FROM contacts c WHERE c.contact_id=? AND c.organization_id=? AND ('+scope+')',[contact_id,org]+scope_args)
    if not old:return bad(h,'NOT_FOUND','联系人不存在',404)
    if old.get('deleted_at') is not None:return h.sendj({'ok':True,'item':old,'alreadyDeleted':True}) or True
    n=now_ms();c.execute('UPDATE contacts SET deleted_at=?,deleted_by=?,delete_reason=?,updated_at=?,version=version+1 WHERE contact_id=? AND organization_id=? AND deleted_at IS NULL',(n,a['user_id'],reason,n,contact_id,org));new=one(c,'SELECT * FROM contacts WHERE contact_id=? AND organization_id=?',(contact_id,org))
    audit_in_tx(c,a,'soft_delete','contact',contact_id,old,new,reason,old['workspace_id'])
   return h.sendj({'ok':True,'item':new,'alreadyDeleted':False}) or True
  if contact_id and len(seg)==2 and m=='PATCH':
   if not manage(db,a,'contact.update',org):return bad(h,'FORBIDDEN','无联系人修改权限',403)
   b=h.body()
   with db.tx() as c:
    scope,scope_args,_=data_scope_clause_in_tx(c,a,'contact.read',org,alias='c');old=one(c,'SELECT c.* FROM contacts c WHERE c.contact_id=? AND c.organization_id=? AND ('+scope+')',[contact_id,org]+scope_args)
    if not old:return bad(h,'NOT_FOUND','联系人不存在',404)
    c.execute('UPDATE contacts SET manual_name=?,manual_phone=?,remark=?,status=?,updated_at=?,version=version+1 WHERE contact_id=?',(str(b.get('manualName') if b.get('manualName') is not None else old['manual_name']),str(b.get('manualPhone') if b.get('manualPhone') is not None else old['manual_phone']),str(b.get('remark') if b.get('remark') is not None else old['remark']),str(b.get('status') if b.get('status') is not None else old['status']),now_ms(),contact_id));new=one(c,'SELECT * FROM contacts WHERE contact_id=?',(contact_id,))
    audit_in_tx(c,a,'update','contact',contact_id,old,new,b.get('reason'),old['workspace_id'])
   return h.sendj({'ok':True,'item':new}) or True

 # GET /api/v207/admin/contacts/{contactId}  — OpsDrawer 详情
 if root=='contacts' and contact_id and len(seg)==2 and m=='GET':
  if not (platform(db,a) or has_permission_in_any_scope(db,a,'contact.read',org)):return bad(h,'FORBIDDEN','无联系人读取权限',403)
  with db.tx(False) as c:
   # 允许本人/团队等有效读取授权进入；目标客户继续由行级 scope 限制，避免越权。
   wc,wp,_=_ops_scope_clause(db,c,a,True,org,alias='c');fc,fp=_ops_filter_clause(q,'c')
   r=one(c,f"SELECT c.*,s.source_name,t.name team_name FROM contacts c LEFT JOIN sources s ON s.source_id=c.source_id LEFT JOIN teams t ON t.team_id=c.team_id WHERE c.contact_id=? AND c.organization_id=? AND c.deleted_at IS NULL AND {wc}{fc}",[contact_id,org]+wp+fp)
   if not r:return bad(h,'NOT_FOUND','联系人不存在',404)
   logs=rows(c,'SELECT l.*,u.display_name actor_name FROM audit_logs l LEFT JOIN users u ON u.user_id=l.actor_id WHERE l.entity_id=? AND l.entity_type=? ORDER BY l.created_at DESC LIMIT 20',(contact_id,'contact'))
   touchpoints=rows(c,'SELECT touchpoint_id,touchpoint_type,direction,initiated_by,occurred_at,metadata_json FROM source_touchpoints WHERE contact_id=? ORDER BY occurred_at DESC LIMIT 10',(contact_id,))
   raw_requested=str(q.get('raw') or '').strip().lower() in ('1','true','yes')
   allow_raw=False
   if raw_requested:
    allow_raw=can(db,a,'message.read.raw',workspace_id=r.get('workspace_id'),team_id=r.get('team_id'),organization_id=org)
    if not allow_raw:return bad(h,'FORBIDDEN','无消息原文读取权限',403)
   text_column='text_content' if allow_raw else 'redacted_text'
   messages=rows(c,f"SELECT m.message_id,m.conversation_id,m.direction,m.sender_type,m.content_type,CASE WHEN m.content_deleted_at IS NOT NULL THEN NULL ELSE m.{text_column} END AS text,m.occurred_at,m.collected_at,m.status,m.content_deleted_at,m.metadata_json,ca.display_name channel_account_name,p.platform_name platform_name FROM conversation_messages m LEFT JOIN conversations v ON v.conversation_id=m.conversation_id LEFT JOIN channel_accounts ca ON ca.channel_account_id=v.channel_account_id LEFT JOIN platforms p ON p.platform_id=v.platform_id WHERE m.contact_id=? AND m.deleted_at IS NULL ORDER BY m.occurred_at IS NULL,m.occurred_at DESC,m.collected_at DESC,m.message_id DESC LIMIT 10",(contact_id,))
  for m in messages:
   try:
    meta=json.loads(m.pop('metadata_json',None) or '{}');tr=meta.get('translation') if isinstance(meta,dict) else None
    safe_meta={k:meta[k] for k in ('timestampResolved','timestampSource','timestampConfidence','timestampPrecision') if isinstance(meta,dict) and k in meta}
    if m.get('content_deleted_at') is None and isinstance(tr,dict) and isinstance(tr.get('text'),str) and bool(tr.get('visible',True)):
     from V208_privacy import redact_text
     translated=tr['text'] if allow_raw else redact_text(tr['text'])[0]
     safe_tr={'text':translated[:65536],'source':str(tr.get('source') or 'page')[:80],'visible':True}
     safe_meta['translation']=safe_tr;m['translation']=safe_tr
    m['metadata']=safe_meta
   except Exception:m['metadata']={}
   if allow_raw:audit_in_tx(c,a,'read_raw','contact_messages',contact_id,{}, {'contactId':contact_id,'workspaceId':r.get('workspace_id'),'teamId':r.get('team_id'),'scope':'latest_10'},'explicit raw message access',r.get('workspace_id'))
  return h.sendj({'ok':True,'contact':r,'auditLogs':logs,'touchpoints':touchpoints,'messages':messages,'messageContent':'raw' if allow_raw else 'redacted'}) or True

 # graph with explicit relations
 if root=='graph' and m=='GET':
  if not (platform(db,a) or can(db,a,'organization.read')):return bad(h,'FORBIDDEN','无组织读取权限',403)
  with db.tx(False) as c:
   data={
    'organizations':rows(c,'SELECT * FROM organizations WHERE organization_id=?',(org,)),
    'departments':rows(c,'SELECT * FROM departments WHERE organization_id=?',(org,)),
    'businessLines':rows(c,'SELECT * FROM business_lines WHERE organization_id=?',(org,)),
    'markets':rows(c,'SELECT * FROM markets WHERE organization_id=?',(org,)),
    'teams':rows(c,'SELECT * FROM teams WHERE organization_id=?',(org,)),
    'users':rows(c,'SELECT user_id,display_name,login_name,status FROM users WHERE organization_id=?',(org,)),
    'workspaces':rows(c,'SELECT * FROM workspaces WHERE organization_id=?',(org,)),
    'accounts':rows(c,'SELECT * FROM channel_accounts WHERE organization_id=?',(org,)),
    'sources':rows(c,'SELECT source_id,source_name,channel,team_id,workspace_id,channel_account_id,status FROM sources WHERE organization_id=?',(org,)),
    'devices':rows(c,'SELECT device_id,team_id,workspace_id,assigned_user_id,system_device_name,user_device_alias,admin_device_name,status FROM devices WHERE organization_id=?',(org,)),
    'teamMemberships':rows(c,"SELECT tm.user_id,tm.team_id,tm.membership_type,tm.is_primary,tm.status FROM team_memberships tm JOIN teams t ON t.team_id=tm.team_id WHERE t.organization_id=? AND tm.status='active'",(org,)),
    'userPositions':rows(c,"SELECT up.user_id,up.position_id,p.name position_name,p.department_id FROM user_positions up JOIN positions p ON p.position_id=up.position_id WHERE up.organization_id=? AND up.status='active'",(org,)),
    'teamBusinessLines':rows(c,"SELECT tbl.team_id,tbl.business_line_id,tbl.is_primary,bl.name FROM team_business_lines tbl JOIN business_lines bl ON bl.business_line_id=tbl.business_line_id WHERE tbl.organization_id=? AND tbl.status='active'",(org,)),
    'teamMarkets':rows(c,"SELECT tm.team_id,tm.market_id,tm.is_primary,tm.scope_type,m.name FROM team_markets tm JOIN markets m ON m.market_id=tm.market_id WHERE tm.organization_id=? AND tm.status='active'",(org,)),
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
  if q.get('days'):cond+=' AND l.created_at>=?';args.append(now_ms()-int(q['days'])*86400*1000)
  with db.tx(False) as c:
   total=c.execute(f'SELECT count(*) FROM audit_logs l JOIN users u ON u.user_id=l.actor_id WHERE {cond}',tuple(args)).fetchone()[0]
   its=rows(c,f'SELECT l.*,u.display_name actor_name FROM audit_logs l JOIN users u ON u.user_id=l.actor_id WHERE {cond} ORDER BY audit_id DESC LIMIT ? OFFSET ?',tuple(args+[size,off]))
   since_ms=now_ms()-30*86400*1000
   heat=rows(c,f"SELECT cast(strftime('%w',l.created_at/1000,'unixepoch','localtime') as int) weekday,cast(strftime('%H',l.created_at/1000,'unixepoch','localtime') as int) hour,count(*) cnt FROM audit_logs l JOIN users u ON u.user_id=l.actor_id WHERE l.created_at>=? AND u.organization_id=? GROUP BY weekday,hour",(since_ms,org))
   op_dist=rows(c,f"SELECT operation name,count(*) value FROM audit_logs l JOIN users u ON u.user_id=l.actor_id WHERE l.created_at>=? AND u.organization_id=? GROUP BY operation ORDER BY value DESC",(since_ms,org))
   type_dist=rows(c,f"SELECT entity_type name,count(*) value FROM audit_logs l JOIN users u ON u.user_id=l.actor_id WHERE l.created_at>=? AND u.organization_id=? GROUP BY entity_type ORDER BY value DESC",(since_ms,org))
   top_actors=rows(c,f"SELECT u.display_name name,count(*) value FROM audit_logs l JOIN users u ON u.user_id=l.actor_id WHERE l.created_at>=? AND u.organization_id=? GROUP BY l.actor_id ORDER BY value DESC LIMIT 10",(since_ms,org))
   daily=rows(c,f"SELECT date(l.created_at/1000,'unixepoch','localtime') day,count(*) value FROM audit_logs l JOIN users u ON u.user_id=l.actor_id WHERE l.created_at>=? AND u.organization_id=? GROUP BY day ORDER BY day",(since_ms,org))
   pack_dict=pack(its,total,pno,size)
   pack_dict.update({'heatMap':heat,'operationDistribution':op_dist,'entityTypeDistribution':type_dist,'topActors':top_actors,'dailyTrend':daily})
  return h.sendj(pack_dict) or True
 # recycle bin (deleted contacts)
 if root=='recycle' and m=='GET':
  if not (platform(db,a) or has_permission_in_any_scope(db,a,'contact.read',org)):return bad(h,'FORBIDDEN','无联系人读取权限',403)
  pno,size,off=page(q)
  with db.tx(False) as c:
   scope,scope_args,_=data_scope_clause_in_tx(c,a,'contact.read',org,alias='c');cond='c.organization_id=? AND c.deleted_at IS NOT NULL AND ('+scope+')';args=[org]+scope_args
   total=c.execute('SELECT count(*) FROM contacts c WHERE '+cond,args).fetchone()[0];its=rows(c,'SELECT c.*,s.source_name,t.name team_name FROM contacts c LEFT JOIN sources s ON s.source_id=c.source_id LEFT JOIN teams t ON t.team_id=c.team_id WHERE '+cond+' ORDER BY c.deleted_at DESC LIMIT ? OFFSET ?',args+[size,off])
  return h.sendj(pack(its,total,pno,size)) or True
 if root=='recycle' and ident and m=='POST':
  if not manage(db,a,'contact.update',org):return bad(h,'FORBIDDEN','无联系人恢复权限',403)
  with db.tx() as c:
   old=one(c,'SELECT * FROM contacts WHERE contact_id=? AND organization_id=? AND deleted_at IS NOT NULL',(ident,org))
   if not old:return bad(h,'NOT_FOUND','联系人不存在或未删除',404)
   c.execute('UPDATE contacts SET deleted_at=NULL,updated_at=?,version=version+1 WHERE contact_id=?',(now_ms(),ident));new=one(c,'SELECT * FROM contacts WHERE contact_id=?',(ident,))
   audit_in_tx(c,a,'restore','contact',ident,old,new,'从回收站恢复',old['workspace_id'])
  return h.sendj({'ok':True,'item':new}) or True
 if root=='recycle' and ident and m=='DELETE':
  if not (platform(db,a) or manage(db,a,'contact.delete',org)):return bad(h,'FORBIDDEN','无联系人永久删除权限',403)
  b=h.body();
  if str(b.get('confirm') or '')!='PURGE':return bad(h,'PURGE_CONFIRMATION_REQUIRED','永久删除需要明确确认',428)
  try:
   with db.tx() as c:
    scope,scope_args,_=data_scope_clause_in_tx(c,a,'contact.read',org,alias='c');old=one(c,'SELECT c.* FROM contacts c WHERE c.contact_id=? AND c.organization_id=? AND c.deleted_at IS NOT NULL AND ('+scope+')',[ident,org]+scope_args)
    if not old:return bad(h,'NOT_FOUND','联系人不存在、未在回收站或不在授权范围',404)
    # 只清理数据库声明为直接引用 contacts 的行；事务保证任何遗漏引用都会整体回滚。
    tables=[r[0] for r in c.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
    deleted={}
    for table in tables:
     if table in ('contacts','audit_logs'):continue
     refs=[]
     try:
      for fk in c.execute('PRAGMA foreign_key_list("'+table.replace('"','""')+'")').fetchall():
       if str(fk[2])=='contacts' and str(fk[4])=='contact_id':refs.append(str(fk[3]))
     except sqlite3.DatabaseError:continue
     # 兼容历史表未声明 FK 但使用标准 contact_id 字段的情况。
     cols=[str(x[1]) for x in c.execute('PRAGMA table_info("'+table.replace('"','""')+'")').fetchall()]
     if 'contact_id' in cols and 'contact_id' not in refs:refs.append('contact_id')
     if not refs:continue
     where=' OR '.join('"'+col.replace('"','""')+'"=?' for col in refs);cur=c.execute('DELETE FROM "'+table.replace('"','""')+'" WHERE '+where,[ident]*len(refs))
     if cur.rowcount:deleted[table]=cur.rowcount
    cur=c.execute('DELETE FROM contacts WHERE contact_id=? AND organization_id=? AND deleted_at IS NOT NULL',(ident,org))
    if cur.rowcount!=1:raise RuntimeError('CONTACT_PURGE_RACE')
    audit_in_tx(c,a,'purge','contact_tombstone',ident,{'contactId':ident,'workspaceId':old['workspace_id'],'deletedAt':old.get('deleted_at')},{'purged':True,'relatedRows':deleted},'回收站永久删除',old['workspace_id'])
   return h.sendj({'ok':True,'contactId':ident,'purgedRelatedRows':deleted}) or True
  except sqlite3.IntegrityError:return bad(h,'CONTACT_PURGE_BLOCKED','联系人仍被受保护业务记录引用，永久删除已整体回滚',409)
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
   w=c.execute("SELECT workspace_id FROM workspaces WHERE organization_id=? AND status='active' ORDER BY CASE workspace_id WHEN 'ws-global' THEN 0 ELSE 1 END, created_at, workspace_id LIMIT 1",(org,)).fetchone(); audit_in_tx(c,a,'revoke','session',ident,old,{},'管理员撤销会话',w[0] if w else None)
  return h.sendj({'ok':True}) or True
 # tags management
 if root=='tags' and m=='GET':
  if not (platform(db,a) or can(db,a,'contact.read')):return bad(h,'FORBIDDEN','无标签读取权限',403)
  wid=q.get('workspace');kind=q.get('kind')
  if not wid:return bad(h,'WORKSPACE_REQUIRED','工作区参数必需')
  with db.tx(False) as c:
   if not c.execute('SELECT 1 FROM workspaces WHERE workspace_id=? AND organization_id=?',(wid,org)).fetchone():return bad(h,'WORKSPACE_NOT_FOUND','工作区不存在',404)
   sql='SELECT * FROM tags WHERE workspace_id=?';args=[wid]
   if kind:sql+=' AND tag_kind=?';args.append(kind)
   its=rows(c,sql+' ORDER BY sort_order,name',tuple(args))
  return h.sendj({'ok':True,'items':its}) or True
 if root=='tags' and m=='POST':
  if not manage(db,a,'contact.update',org):return bad(h,'FORBIDDEN','无标签管理权限',403)
  x=h.body();wid=str(x.get('workspace') or '').strip();name=str(x.get('name') or '').strip();kind=str(x.get('kind') or 'portrait');color=str(x.get('color') or '#64748b').strip().upper()
  if not wid or not name:return bad(h,'INVALID_INPUT','工作区和名称不能为空')
  if kind not in ('status','portrait'):return bad(h,'INVALID_KIND','标签类型无效')
  if not re.fullmatch(r'#[0-9A-F]{6}',color):return bad(h,'INVALID_COLOR','标签颜色必须是 #RRGGBB 格式')
  tid='tag_'+uuid.uuid4().hex;n=now_ms()
  try:
   with db.tx() as c:
    if not c.execute('SELECT 1 FROM workspaces WHERE workspace_id=? AND organization_id=?',(wid,org)).fetchone():return bad(h,'WORKSPACE_NOT_FOUND','工作区不存在',404)
    c.execute('INSERT INTO tags(tag_id,workspace_id,name,color,category,tag_kind,sort_order,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(tid,wid,name,color,str(x.get('category') or '')[:80],kind,int(x.get('sortOrder') or 0),1 if x.get('enabled',True) not in (False,0,'0') else 0,n,n));item=one(c,'SELECT * FROM tags WHERE tag_id=?',(tid,));audit_in_tx(c,a,'create','tag',tid,{},item,wid)
   return h.sendj({'ok':True,'item':item},201) or True
  except (sqlite3.IntegrityError,ValueError):return bad(h,'TAG_CONFLICT','标签名称已存在或排序无效',409)
 if root=='tags' and ident and m=='PATCH':
  if not manage(db,a,'contact.update',org):return bad(h,'FORBIDDEN','无标签管理权限',403)
  x=h.body();n=now_ms()
  try:
   with db.tx() as c:
    old=one(c,'SELECT t.*,w.organization_id FROM tags t JOIN workspaces w ON w.workspace_id=t.workspace_id WHERE t.tag_id=?',(ident,))
    if not old or old['organization_id']!=org:return bad(h,'NOT_FOUND','标签不存在',404)
    name=str(x.get('name',old['name'])).strip();kind=str(x.get('kind',old['tag_kind']));color=str(x.get('color',old['color'])).strip().upper()
    if not name or kind not in ('status','portrait'):return bad(h,'INVALID_INPUT','标签名称或类型无效')
    if kind!=old['tag_kind']:return bad(h,'TAG_KIND_IMMUTABLE','标签类型创建后不可修改',409)
    if not re.fullmatch(r'#[0-9A-F]{6}',color):return bad(h,'INVALID_COLOR','标签颜色必须是 #RRGGBB 格式')
    c.execute('UPDATE tags SET name=?,color=?,category=?,tag_kind=?,sort_order=?,enabled=?,updated_at=? WHERE tag_id=?',(name,color,str(x.get('category',old['category']))[:80],kind,int(x.get('sortOrder',old['sort_order'])),1 if x.get('enabled',old['enabled']) not in (False,0,'0') else 0,n,ident));item=one(c,'SELECT * FROM tags WHERE tag_id=?',(ident,));audit_in_tx(c,a,'update','tag',ident,old,item,old['workspace_id'])
   return h.sendj({'ok':True,'item':item}) or True
  except (sqlite3.IntegrityError,ValueError):return bad(h,'TAG_CONFLICT','标签名称已存在或排序无效',409)
 if root=='tags' and ident and m=='DELETE':
  if not manage(db,a,'contact.update',org):return bad(h,'FORBIDDEN','无标签删除权限',403)
  with db.tx() as c:
   old=one(c,'SELECT t.*,w.organization_id FROM tags t JOIN workspaces w ON w.workspace_id=t.workspace_id WHERE t.tag_id=?',(ident,))
   if not old or old['organization_id']!=org:return bad(h,'NOT_FOUND','标签不存在',404)
   if c.execute('SELECT COUNT(*) FROM contact_tags WHERE tag_id=?',(ident,)).fetchone()[0]:return bad(h,'TAG_IN_USE','标签仍被联系人使用',409)
   c.execute('DELETE FROM tags WHERE tag_id=?',(ident,));audit_in_tx(c,a,'delete','tag',ident,old,{},old['workspace_id'])
  return h.sendj({'ok':True}) or True
 if root=='field-definitions' and m=='GET':
  if not (platform(db,a) or can(db,a,'contact.read')):return bad(h,'FORBIDDEN','无字段定义读取权限',403)
  wid=q.get('workspace')
  if not wid:return bad(h,'WORKSPACE_REQUIRED','工作区参数必需')
  with db.tx(False) as c:
   if not c.execute('SELECT 1 FROM workspaces WHERE workspace_id=? AND organization_id=?',(wid,org)).fetchone():return bad(h,'WORKSPACE_NOT_FOUND','工作区不存在',404)
   its=rows(c,'SELECT * FROM custom_field_definitions WHERE workspace_id=? ORDER BY sort_order,field_key',(wid,))
  return h.sendj({'ok':True,'items':its}) or True
 if root=='field-definitions' and (m=='POST' or (ident and m=='PATCH')):
  if not manage(db,a,'contact.update',org):return bad(h,'FORBIDDEN','无字段定义管理权限',403)
  x=h.body();wid=str(x.get('workspace') or q.get('workspace') or '').strip();key=str(ident or x.get('fieldKey') or '').strip().lower();label=str(x.get('label') or '').strip();ftype=str(x.get('fieldType') or 'text')
  if ftype=='select':ftype='single_select'
  if not wid or not key or not label:return bad(h,'INVALID_INPUT','工作区、键名和标签不能为空')
  if not __import__('re').fullmatch(r'[A-Za-z0-9_.:-]{1,80}',key):return bad(h,'INVALID_KEY','字段键名无效')
  if ftype not in ('text','number','date','boolean','json','single_select','multi_select'):return bad(h,'INVALID_TYPE','字段类型无效')
  opts=x.get('options',x.get('optionsJson',[]))
  if isinstance(opts,str):
   try:opts=json.loads(opts) if opts.strip().startswith('[') else [v.strip() for v in opts.split(',') if v.strip()]
   except Exception:return bad(h,'INVALID_OPTIONS','候选项格式无效')
  if not isinstance(opts,list) or any(not isinstance(v,str) or not v.strip() for v in opts) or len(opts)!=len(set(opts)):return bad(h,'INVALID_OPTIONS','候选项必须是不重复的非空字符串数组')
  opts=[v.strip()[:120] for v in opts]
  if ftype in ('single_select','multi_select') and not opts:return bad(h,'OPTIONS_REQUIRED','选择字段必须配置候选项')
  if ftype not in ('single_select','multi_select'):opts=[]
  n=now_ms()
  try:
   with db.tx() as c:
    if not c.execute('SELECT 1 FROM workspaces WHERE workspace_id=? AND organization_id=?',(wid,org)).fetchone():return bad(h,'WORKSPACE_NOT_FOUND','工作区不存在',404)
    old=one(c,'SELECT * FROM custom_field_definitions WHERE workspace_id=? AND field_key=?',(wid,key))
    if m=='POST' and old:return bad(h,'FIELD_CONFLICT','字段键名已存在',409)
    if m=='PATCH' and not old:return bad(h,'NOT_FOUND','字段定义不存在',404)
    enabled=1 if x.get('enabled',old['enabled'] if old else True) not in (False,0,'0') else 0;quick=1 if x.get('isQuickEdit',old['is_quick_edit'] if old else False) not in (False,0,'0','') else 0
    role=str(x.get('fieldRole',old['field_role'] if old else 'custom'))[:80];zone=str(x.get('displayZone',old['display_zone'] if old else 'interaction_panel'))[:80];placeholder=str(x.get('placeholder',old['placeholder'] if old else ''))[:240];order=int(x.get('sortOrder',old['sort_order'] if old else 0))
    vals=(label,ftype,order,enabled,n,role,zone,quick,json.dumps(opts,ensure_ascii=False),placeholder)
    if m=='POST':c.execute('INSERT INTO custom_field_definitions(workspace_id,field_key,label,field_type,sort_order,enabled,created_at,updated_at,field_role,display_zone,is_quick_edit,options_json,placeholder) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(wid,key,label,ftype,order,enabled,n,n,role,zone,quick,json.dumps(opts,ensure_ascii=False),placeholder))
    else:c.execute('UPDATE custom_field_definitions SET label=?,field_type=?,sort_order=?,enabled=?,updated_at=?,field_role=?,display_zone=?,is_quick_edit=?,options_json=?,placeholder=? WHERE workspace_id=? AND field_key=?',vals+(wid,key))
    # 定义更新后立即协调已有值，插件与客户档案下一次读取即采用新定义。
    if m=='PATCH':
     value_rows=c.execute('SELECT v.contact_id,v.value_json FROM contact_custom_values v JOIN contacts ct ON ct.contact_id=v.contact_id WHERE ct.workspace_id=? AND v.field_key=?',(wid,key)).fetchall()
     allowed=set(opts)
     for vr in value_rows:
      try:value=json.loads(vr[1])
      except Exception:value=None
      if ftype=='multi_select':
       seq=value if isinstance(value,list) else ([] if value in (None,'') else [value]);clean=[]
       for v in seq:
        if isinstance(v,str) and v in allowed and v not in clean:clean.append(v)
       value=clean
      elif ftype=='single_select':value=value if isinstance(value,str) and value in allowed else None
      elif ftype in ('text','date'):value=value if isinstance(value,str) else ''
      elif ftype=='number':value=value if isinstance(value,(int,float)) and not isinstance(value,bool) else None
      elif ftype=='boolean':value=value if isinstance(value,bool) else None
      if value is None:c.execute('DELETE FROM contact_custom_values WHERE contact_id=? AND field_key=?',(vr[0],key))
      else:c.execute('UPDATE contact_custom_values SET value_json=?,updated_at=?,updated_by=? WHERE contact_id=? AND field_key=?',(json.dumps(value,ensure_ascii=False,separators=(',',':')),n,a['user_id'],vr[0],key))
    item=one(c,'SELECT * FROM custom_field_definitions WHERE workspace_id=? AND field_key=?',(wid,key));audit_in_tx(c,a,'create' if m=='POST' else 'update','field_definition',key,old or {},item,wid)
   return h.sendj({'ok':True,'item':item},201 if m=='POST' else 200) or True
  except (sqlite3.IntegrityError,ValueError):return bad(h,'FIELD_CONFLICT','字段配置冲突或排序无效',409)
 if root=='field-definitions' and ident and m=='DELETE':
  if not manage(db,a,'contact.update',org):return bad(h,'FORBIDDEN','无字段定义删除权限',403)
  wid=q.get('workspace')
  if not wid:return bad(h,'WORKSPACE_REQUIRED','工作区参数必需')
  with db.tx() as c:
   if not c.execute('SELECT 1 FROM workspaces WHERE workspace_id=? AND organization_id=?',(wid,org)).fetchone():return bad(h,'WORKSPACE_NOT_FOUND','工作区不存在',404)
   old=one(c,'SELECT * FROM custom_field_definitions WHERE workspace_id=? AND field_key=?',(wid,ident))
   if not old:return bad(h,'NOT_FOUND','字段定义不存在',404)
   c.execute('DELETE FROM contact_custom_values WHERE field_key=? AND contact_id IN (SELECT contact_id FROM contacts WHERE workspace_id=?)',(ident,wid));c.execute('DELETE FROM custom_field_definitions WHERE workspace_id=? AND field_key=?',(wid,ident));audit_in_tx(c,a,'delete','field_definition',ident,old,{},wid)
  return h.sendj({'ok':True}) or True
 if root=='diagnostics' and m=='GET':
  if not (platform(db,a) or can(db,a,'audit.read')):return bad(h,'FORBIDDEN','无诊断权限',403)
  with db.tx(False) as c:
   tables=[x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
   counts={t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in tables}
   fk=[dict(x) for x in c.execute('PRAGMA foreign_key_check')]
   idx_map={}
   for t in tables:
    idx_map[t]=c.execute("SELECT count(*) FROM sqlite_master WHERE type='index' AND tbl_name=? AND name NOT LIKE 'sqlite_%'",(t,)).fetchone()[0]
   page_count=c.execute('PRAGMA page_count').fetchone()[0]
   page_size=c.execute('PRAGMA page_size').fetchone()[0]
   freelist=c.execute('PRAGMA freelist_count').fetchone()[0]
   integrity=c.execute('PRAGMA integrity_check').fetchone()
   table_meta=[]
   for t in tables:
    rows_count=counts[t]
    try:
     r=c.execute(f'SELECT SUM(pgsize) FROM dbstat WHERE name=?',(t,)).fetchone()
     size_bytes=(r[0] if r and r[0] else 0)
    except Exception:
     size_bytes=0
    table_meta.append({'name':t,'rows':rows_count,'indexes':idx_map[t],'size':size_bytes})
   table_meta.sort(key=lambda x:-x['rows'])
   t0=now_ms();c.execute('SELECT 1');read_ms=(now_ms()-t0)*1000
  path=str(db.path)
  return h.sendj({'ok':True,'version':PRODUCT_VERSION,'schemaVersion':SCHEMA_VERSION,'quickCheck':db.quick_check(),'databasePath':path,'databaseBytes':os.path.getsize(path) if os.path.exists(path) else 0,'walExists':os.path.exists(path+'-wal'),'shmExists':os.path.exists(path+'-shm'),'foreignKeyIssues':fk,'tableCounts':counts,'tableMeta':table_meta,'pageCount':page_count,'pageSize':page_size,'freelistCount':freelist,'integrityCheck':integrity[0] if integrity else '','readLatencyMs':round(read_ms,3),'databaseUsageBytes':(page_count-freelist)*page_size,'databaseFreeBytes':freelist*page_size}) or True
 return bad(h,'NOT_FOUND','管理接口不存在',404)

# V208.0.0 更新说明（2026-09-18）：新增平台、营销活动、触点与客户归因管理 API；写入操作执行组织/工作区隔离、RBAC 与审计。

# V207.3.0-dev 更新说明（2026-09-19）：接入部门、业务线、市场和业务空间多维关系 API；创建企业/团队同步主工作区关系；改密兼容 currentPassword，密码错误返回 400。

# V207.5.0-dev 更新说明（2026-09-20）：数据字典仅允许 GET，并统一产品及 Schema 版本来源。
