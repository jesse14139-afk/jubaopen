import sqlite3
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聚宝盆 210.2.75 / Schema 222 中心服务（Python 标准库，零第三方依赖）。"""
import argparse,json,os,sys,uuid
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs,unquote
ROOT=os.path.dirname(os.path.abspath(__file__));sys.path.insert(0,ROOT)
from V207_shared_db import Database,now_ms,dumps,hash_password,default_workspace_id
from V207_version import PRODUCT_VERSION,SCHEMA_VERSION
from V207_security import login,actor_from_token,can,canonical,password_strong,grant_binding_in_tx,revoke_token_session_in_tx
from V207_admin_api import dispatch as admin_dispatch
from V208_api import dispatch as v208_dispatch
from V208_account_policy import normalize_account_policy
from V208_follow_up_notification_service import start_scanner
from V207_core import session_context,resolve_account,register_device,rename_device,graph,ok,err
from V206_core_compat import (list_contacts,get_contact,changes,apply_event,delete_preview,get_workspace,update_workspace,list_sources,list_tags,save_tag,delete_tag,list_field_definitions,save_field_definition,delete_field_definition,admin_contact_lifecycle,admin_logs,admin_schema)
VERSION=PRODUCT_VERSION;DB=None;WEB_ROOT=os.path.join(ROOT,'web');ADMIN=open(os.path.join(WEB_ROOT,'admin.html'),'rb').read();ECHARTS=open(os.path.join(WEB_ROOT,'echarts.min.js'),'rb').read()
READ_PERM={'/api/v207/contacts':'contact.read','/api/v207/changes':'contact.read','/api/v207/admin/graph':'organization.read'}
class H(BaseHTTPRequestHandler):
 server_version='Jubaopen/'+PRODUCT_VERSION
 def log_message(self,fmt,*args):
  # 正常 HTTP 访问日志写 stdout，避免 Windows PowerShell 误报 NativeCommandError。
  sys.stdout.write('%s %s\n'%(self.address_string(),fmt%args));sys.stdout.flush()
 def log_error(self,fmt,*args):
  sys.stderr.write('%s ERROR %s\n'%(self.address_string(),fmt%args));sys.stderr.flush()
 def sendj(self,d,s=200):
  b=json.dumps(d,ensure_ascii=False,separators=(',',':')).encode()
  try:self.send_response(s);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.security_headers();self.end_headers();self.wfile.write(b)
  except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):return
 def security_headers(self):
  self.send_header('Access-Control-Allow-Origin','null');self.send_header('Access-Control-Allow-Headers','Authorization,Content-Type');self.send_header('Access-Control-Allow-Methods','GET,POST,PUT,PATCH,DELETE,OPTIONS');self.send_header('Cache-Control','no-store');self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' https: data:; connect-src 'self'; frame-ancestors 'none'");self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=()')
 def body(self):
  n=int(self.headers.get('Content-Length','0') or 0)
  if n>1048576:raise ValueError('REQUEST_TOO_LARGE')
  try:d=json.loads(self.rfile.read(n) or b'{}')
  except Exception:raise ValueError('INVALID_JSON')
  if not isinstance(d,dict):raise ValueError('JSON_OBJECT_REQUIRED')
  return d
 def actor(self):
  x=self.headers.get('Authorization','');return actor_from_token(DB,x[7:].strip()) if x.lower().startswith('bearer ') else None
 def scope(self,a,wid,team=None,perm=None):
  if not a:return False
  if not team and wid:
   with DB.tx(False) as c:
    r=c.execute("SELECT team_id FROM teams WHERE workspace_id=? AND organization_id=? AND status='active'",(wid,a['organization_id'])).fetchone()
    team=r['team_id'] if r else None
  return can(DB,a,perm,wid,team) if perm else can(DB,a,'organization.read',wid,team)
 def audit(self,a,op,typ,eid,before,after,reason=None):
  candidates=[]
  for value in (after,before):
   if isinstance(value,dict):candidates.append(value.get('workspace_id') or value.get('workspaceId'))
  wid=next((x for x in candidates if x),None)
  with DB.tx() as c:
   if not wid:
    wid=default_workspace_id(c,a['organization_id'])
    if not wid:raise RuntimeError('AUDIT_WORKSPACE_REQUIRED')
   scope=c.execute('SELECT organization_id FROM workspaces WHERE workspace_id=?',(wid,)).fetchone()
   if not scope or scope['organization_id']!=a['organization_id']:raise RuntimeError('AUDIT_SCOPE_MISMATCH')
   c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at,organization_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(wid,a['user_id'],None,op,typ,eid,dumps(before or {}),dumps(after or {}),reason,now_ms(),a['organization_id']))
 def do_OPTIONS(self):self.send_response(204);self.security_headers();self.end_headers()
 def safe_route(self,m):
  try:self.route(m)
  except ValueError as e:
   code=str(e);self.sendj({'ok':False,'code':code,'message':'请求体超过 1MiB' if code=='REQUEST_TOO_LARGE' else 'JSON 请求体无效'},413 if code=='REQUEST_TOO_LARGE' else 400)
  except sqlite3.OperationalError as e:
   if 'locked' in str(e).lower() or 'busy' in str(e).lower():
    self.log_message('database busy: %s',e);return self.sendj({'ok':False,'code':'DATABASE_BUSY','message':'系统繁忙，请稍后重试','retryAfterMs':800},503)
   self.log_message('database error: %s',e);self.sendj({'ok':False,'code':'INTERNAL_ERROR','message':'服务器内部错误'},500)
  except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):return
  except Exception as e:
   self.log_message('internal error: %s',e);self.sendj({'ok':False,'code':'INTERNAL_ERROR','message':'服务器内部错误'},500)
 def do_GET(self):self.safe_route('GET')
 def do_POST(self):self.safe_route('POST')
 def do_PUT(self):self.safe_route('PUT')
 def do_PATCH(self):self.safe_route('PATCH')
 def do_DELETE(self):self.safe_route('DELETE')
 def route(self,m):
  u=urlparse(self.path);p=u.path;q={k:v[-1] for k,v in parse_qs(u.query).items()};wid=str(q.get('workspace_id') or '').strip()
  if p in ('/health','/api/health'):return self.sendj({'ok':True,'version':VERSION,'schemaVersion':SCHEMA_VERSION,'database':DB.quick_check()})
  if p in ('/favicon.ico','/.well-known/appspecific/com.chrome.devtools.json') and m=='GET':
   self.send_response(204);self.send_header('Cache-Control','public, max-age=86400');self.security_headers();self.end_headers();return
  if p in ('/echarts.min.js','/admin/echarts.min.js') and m=='GET':
   self.send_response(200);self.send_header('Content-Type','application/javascript; charset=utf-8');self.send_header('Content-Length',str(len(ECHARTS)));self.send_header('X-Content-Type-Options','nosniff');self.security_headers();self.end_headers();return self.wfile.write(ECHARTS)
  if p in ('/admin','/admin/','/workspace','/workspace/'):
   self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(ADMIN)));self.security_headers();self.end_headers();return self.wfile.write(ADMIN)
  if p=='/api/v207/auth/login' and m=='POST':
   b=self.body();r,s=login(DB,str(b.get('organizationId') or ''),str(b.get('loginName') or ''),str(b.get('password') or ''),self.client_address[0],self.headers.get('User-Agent',''));return self.sendj(r,s)
  if p=='/api/v207/center/user' and m=='POST':
   return self.sendj({'ok':False,'code':'DEPRECATED','message':'用户创建请使用 POST /api/v207/admin/users（支持职位、团队、角色独立管理）'},410)
  if p.startswith('/api/v205/') or p.startswith('/api/v206/'):
   return self.sendj({'ok':False,'code':'CLIENT_READ_ONLY','message':'V207 迁移期已冻结旧客户端写入；请升级 V207 客户端'},426)
  if not p.startswith('/api/v207/'):return self.sendj({'ok':False,'code':'NOT_FOUND'},404)
  if v208_dispatch(self,m,p,q,DB):return
  a=self.actor()
  if not a:return self.sendj({'ok':False,'code':'UNAUTHORIZED','message':'请登录或重新登录'},401)
  if p.startswith('/api/v207/admin/') and p!='/api/v207/admin/channel-accounts' and admin_dispatch(self,m,p,q,a,DB):return
  if p=='/api/v207/session/context' and m=='GET':r,s=session_context(DB,a);return self.sendj(r,s)
  if p=='/api/v207/auth/logout' and m=='POST':
   token=self.headers.get('Authorization','')[7:].strip()
   with DB.tx() as c:revoke_token_session_in_tx(c,token,a['user_id'],a['user_id'],'logout')
   return self.sendj({'ok':True})
  if p=='/api/v207/accounts/resolve' and m=='POST':r,s=resolve_account(DB,a,self.body());return self.sendj(r,s)
  if p=='/api/v207/devices/register' and m=='POST':
   return self.sendj({'ok':False,'code':'LEGACY_DEVICE_REGISTER_GONE','message':'旧设备注册接口已停用，请使用设备接入邀请码流程'},410)
  if p=='/api/v207/devices/alias' and m=='PATCH':
   b=self.body()
   with DB.tx(False) as c:d=c.execute('SELECT workspace_id,team_id FROM devices WHERE device_id=? AND organization_id=?',(str(b.get('device_id') or ''),a['organization_id'])).fetchone()
   if not d or not can(DB,a,'device.rename.self',d['workspace_id'],d['team_id']):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   r,s=rename_device(DB,a,b,False);return self.sendj(r,s)
  if p=='/api/v207/admin/devices/name' and m=='PATCH':
   if not can(DB,a,'device.rename.admin'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   r,s=rename_device(DB,a,self.body(),True);return self.sendj(r,s)
  if p=='/api/v207/admin/graph' and m=='GET':
   if not can(DB,a,'organization.read'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   r,s=graph(DB,a);return self.sendj(r,s)
  if p=='/api/v207/admin/channel-accounts' and m=='POST':return self.channel_account(a)
  if p=='/api/v207/admin/teams' and m=='POST':return self.create_team(a)
  if p=='/api/v207/admin/users' and m=='POST':return self.create_user(a)
  if p=='/api/v207/workspace' and m=='GET':
   if not self.scope(a,wid,perm='team.read'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   r,s=get_workspace(DB,wid);return self.sendj(r,s)
  if p=='/api/v207/workspace' and m=='PATCH':
   if not self.scope(a,wid,perm='team.manage'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   r,s=update_workspace(DB,wid,self.body());return self.sendj(r,s)
  if p=='/api/v207/sources' and m=='GET':
   if not self.scope(a,wid,perm='source.read'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   r,s=list_sources(DB,wid);return self.sendj(r,s)
  if p=='/api/v207/tags' and m=='GET':
   if not self.scope(a,wid,perm='contact.read'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   r,s=list_tags(DB,wid);return self.sendj(r,s)
  if p=='/api/v207/tags' and m=='POST':
   if not self.scope(a,wid,perm='contact.update'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   r,s=save_tag(DB,wid,self.body());return self.sendj(r,s)
  if p.startswith('/api/v207/tags/') and m=='DELETE':
   if not self.scope(a,wid,perm='contact.update'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   r,s=delete_tag(DB,wid,unquote(p.rsplit('/',1)[-1]));return self.sendj(r,s)
  if p=='/api/v207/field-definitions' and m=='GET':
   if not self.scope(a,wid,perm='contact.read'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   r,s=list_field_definitions(DB,wid);return self.sendj(r,s)
  if p=='/api/v207/field-definitions' and m=='POST':
   if not self.scope(a,wid,perm='contact.update'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   r,s=save_field_definition(DB,wid,self.body());return self.sendj(r,s)
  if p.startswith('/api/v207/field-definitions/') and m=='DELETE':
   if not self.scope(a,wid,perm='contact.update'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   r,s=delete_field_definition(DB,wid,unquote(p.rsplit('/',1)[-1]));return self.sendj(r,s)
  if p=='/api/v207/contacts/delete-preview' and m=='POST':
   b=self.body();wid=str(b.get('workspace_id') or wid)
   if not self.scope(a,wid,perm='contact.delete'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   r,s=delete_preview(DB,wid,str(b.get('device_id') or ''),str(b.get('contact_id') or ''),b.get('version'));return self.sendj(r,s)
  if p.startswith('/api/v207/contacts/') and p.endswith('/restore') and m=='POST':
   cid=unquote(p.split('/')[-2]);b=self.body();b['actor_id']=a['user_id']
   if not self.scope(a,wid,perm='contact.restore'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   r,s=admin_contact_lifecycle(DB,wid,cid,'restore',b);return self.sendj(r,s)
  if p=='/api/v207/admin/diagnostics/schema' and m=='GET':
   if not can(DB,a,'audit.read'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   r,s=admin_schema(DB);return self.sendj(r,s)
  if p=='/api/v207/admin/diagnostics/logs' and m=='GET':
   if not self.scope(a,wid,perm='audit.read'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   r,s=admin_logs(DB,wid,q.get('kind','audit'),q.get('limit',200));return self.sendj(r,s)
  if p=='/api/v207/contacts' and m=='GET':
   if not self.scope(a,wid,perm='contact.read'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   q['workspace_id']=wid;q['limit']=min(int(q.get('limit',200)),1000);r,s=list_contacts(DB,q);return self.sendj(r,s)
  if p.startswith('/api/v207/contacts/') and m=='GET':
   if not self.scope(a,wid,perm='contact.read'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   r,s=get_contact(DB,wid,unquote(p.rsplit('/',1)[-1]));return self.sendj(r,s)
  if p=='/api/v207/changes' and m=='GET':
   if not self.scope(a,wid,perm='contact.read'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
   r,s=changes(DB,wid,int(q.get('after',0)),min(int(q.get('limit',500)),2000));return self.sendj(r,s)
  if p=='/api/v207/events' and m=='POST':return self.event(a,self.body())
  if p=='/api/v207/events/batch' and m=='POST':
   es=self.body().get('events');
   if not isinstance(es,list) or len(es)>500:return self.sendj({'ok':False,'code':'INVALID_BATCH'},400)
   out=[]
   for e in es:
    r,s=self.apply_event_checked(a,e if isinstance(e,dict) else {});r['httpStatus']=s;out.append(r)
   return self.sendj({'ok':True,'results':out,'applied':sum(bool(x.get('ok')) for x in out),'total':len(out)})
  return self.sendj({'ok':False,'code':'NOT_FOUND'},404)
 def event(self,a,b):r,s=self.apply_event_checked(a,b);return self.sendj(r,s)
 def apply_event_checked(self,a,b):
  b=dict(b);b.pop('actor_id',None);b.pop('actorId',None);wid=str(b.get('workspaceId') or b.get('workspace_id') or '').strip();sid=str(b.get('sourceId') or b.get('source_id') or '').strip();op=str(b.get('operation') or '').lower();perm='contact.delete' if op in ('delete','contact.delete') else ('contact.restore' if op in ('restore','contact.restore') else 'contact.update')
  with DB.tx(False) as c:
   s=c.execute('SELECT workspace_id,organization_id,team_id,channel_account_id FROM sources WHERE source_id=?',(sid,)).fetchone()
   if not s or s['workspace_id']!=wid or s['organization_id']!=a['organization_id']:return err('SOURCE_SCOPE_INVALID','来源不属于当前企业或工作区',403)
  if not can(DB,a,perm,wid,s['team_id'],organization_id=a['organization_id']):return err('FORBIDDEN','无此联系人操作权限',403)
  b['workspaceId']=wid;b['workspace_id']=wid;b['sourceId']=sid;b['source_id']=sid;b['actor_id']=a['user_id'];b['user_id']=a['user_id'];r,status=apply_event(DB,b)
  if r.get('ok'):
   with DB.tx() as c:c.execute('UPDATE events SET user_id=? WHERE event_id=?',(a['user_id'],str(b.get('eventId') or b.get('event_id') or '')))
  return r,status
 def channel_account(self,a):
  if not can(DB,a,'account.bind'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
  b=self.body();requested_pid=str(b.get('platformId') or '');ch=str(b.get('channel') or '').lower();identity=canonical(b.get('identity'));team=str(b.get('teamId') or '')
  if not (ch or requested_pid) or not identity or not team:return self.sendj({'ok':False,'code':'INVALID_ACCOUNT'},400)
  try:policy=normalize_account_policy(b)
  except ValueError as e:return self.sendj({'ok':False,'code':str(e)},400)
  with DB.tx() as c:
   t=c.execute('SELECT * FROM teams WHERE team_id=? AND organization_id=?',(team,a['organization_id'])).fetchone()
   if not t:return self.sendj({'ok':False,'code':'TEAM_NOT_FOUND'},404)
   platform_row=c.execute("SELECT * FROM platforms WHERE status='active' AND (platform_id=? OR (?='' AND platform_code=?))",(requested_pid,requested_pid,ch)).fetchone()
   if not platform_row:return self.sendj({'ok':False,'code':'PLATFORM_NOT_FOUND'},404)
   pid=platform_row['platform_id'];ch=platform_row['platform_code'];n=now_ms();aid='acc_'+uuid.uuid4().hex;iid='idn_'+uuid.uuid4().hex;sid='src_'+uuid.uuid4().hex
   c.execute('INSERT INTO channel_accounts(channel_account_id,organization_id,channel,display_name,status,created_at,updated_at,platform_id,account_type,metadata_json,business_purpose,collection_enabled,business_scene,contact_entry_policy) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(aid,a['organization_id'],ch,str(b.get('displayName') or identity),'active',n,n,pid,policy['account_type'],'{}',policy['business_purpose'],policy['collection_enabled'],policy['business_scene'],policy['contact_entry_policy']));c.execute('INSERT INTO channel_account_identities(identity_id,channel_account_id,identity_type,identity_value,canonical_value,created_at,platform_id,is_primary,status,valid_from,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(iid,aid,str(b.get('identityType') or 'login'),str(b.get('identity')),identity,n,pid,1,'active',n,'{}'));c.execute('INSERT INTO team_channel_accounts(team_id,channel_account_id,granted_by,granted_at) VALUES(?,?,?,?)',(team,aid,a['user_id'],n));c.execute("INSERT INTO sources(source_id,workspace_id,channel,account_identity,source_name,status,first_seen_at,last_seen_at,metadata_json,organization_id,team_id,channel_account_id) VALUES(?,?,?,?,?,'active',?,?,'{}',?,?,?)",(sid,t['workspace_id'],ch,str(b.get('identity')),str(b.get('sourceName') or b.get('displayName') or identity),n,n,a['organization_id'],team,aid))
  self.audit(a,'create','channel_account',aid,{},dict(b,workspace_id=t['workspace_id']));return self.sendj({'ok':True,'channelAccountId':aid,'sourceId':sid},201)
 def create_team(self,a):
  # [P0 收口] 旧团队创建入口已废弃。Schema 217 要求所有团队创建统一走新管理 API：
  #   POST /api/v207/admin/teams
  # 旧实现会忽略前端选择的工作区并自动创建新工作区，制造孤立工作区与团队漂移。
  # 此路由仅返回弃用错误，避免后续请求继续产生错误数据。
  self.sendj({'ok':False,'code':'DEPRECATED','message':'团队创建请使用 POST /api/v207/admin/teams（必须显式选择所属工作区）'},410)
 def create_user(self,a):
  # [P0 收口] 旧用户创建入口已废弃。Schema 211 要求所有用户创建统一走新管理 API：
  #   POST /api/v207/admin/users
  # 新接口支持：职位（可选）、团队（可选）、角色权限（可选）、多团队成员关系。
  # 此路由仅返回弃用错误，不再产生旧结构数据。
  self.sendj({'ok':False,'code':'DEPRECATED','message':'用户创建请使用 POST /api/v207/admin/users（支持职位、团队、角色独立管理）'},410)
def main():
 global DB
 ap=argparse.ArgumentParser();ap.add_argument('--db',default=r'I:\jubaopen_data\jubaopen-v208-schema222.db');ap.add_argument('--host',default='127.0.0.1');ap.add_argument('--port',type=int,default=8765)
 for arg in ('organization-id','organization-name','workspace-id','workspace-name','team-id','team-name','admin-user-id','admin-login','admin-display-name','admin-password'):ap.add_argument('--'+arg)
 a=ap.parse_args();DB=Database(a.db)
 bootstrap={k:getattr(a,k) for k in ('organization_id','organization_name','workspace_id','workspace_name','team_id','team_name','admin_user_id','admin_login','admin_display_name','admin_password')}
 if any(bootstrap.values()):bootstrap['builtin_default']='0'
 else:bootstrap=None
 DB.initialize(bootstrap);start_scanner(DB,15)
 print('V%s / Schema %s 服务：http://%s:%s/admin'%(PRODUCT_VERSION,SCHEMA_VERSION,a.host,a.port));ThreadingHTTPServer((a.host,a.port),H).serve_forever()
if __name__=='__main__':main()

# V207.8.0 更新说明（2026-09-20）：统一版本源并接入严格只读数据字典接口。
