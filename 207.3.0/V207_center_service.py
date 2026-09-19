#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聚宝盆 V207.2.0-dev 中心服务（Python 标准库，零第三方依赖）。"""
import argparse,json,os,sys,uuid
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs,unquote
ROOT=os.path.dirname(os.path.abspath(__file__));sys.path.insert(0,ROOT)
from V207_shared_db import Database,now_ms,dumps,hash_password
from V207_security import login,actor_from_token,can,canonical,password_strong
from V207_admin_api import dispatch as admin_dispatch
from V207_core import session_context,resolve_account,register_device,rename_device,graph,ok,err
from V206_core_compat import (list_contacts,get_contact,changes,apply_event,delete_preview,get_workspace,update_workspace,list_sources,list_tags,save_tag,delete_tag,list_field_definitions,save_field_definition,delete_field_definition,admin_contact_lifecycle,admin_logs,admin_schema)
VERSION='207.2.0-dev';DB=None;ADMIN=open(os.path.join(ROOT,'admin_v207.html'),'rb').read()
READ_PERM={'/api/v207/contacts':'contact.read','/api/v207/changes':'contact.read','/api/v207/admin/graph':'organization.read'}
class H(BaseHTTPRequestHandler):
 server_version='Jubaopen/207.2.0-dev'
 def log_message(self,fmt,*args):sys.stderr.write('%s %s\n'%(self.address_string(),fmt%args))
 def sendj(self,d,s=200):
  b=json.dumps(d,ensure_ascii=False,separators=(',',':')).encode();self.send_response(s);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.security_headers();self.end_headers();self.wfile.write(b)
 def security_headers(self):
  self.send_header('Access-Control-Allow-Origin','null');self.send_header('Access-Control-Allow-Headers','Authorization,Content-Type');self.send_header('Access-Control-Allow-Methods','GET,POST,PATCH,DELETE,OPTIONS');self.send_header('Cache-Control','no-store');self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'");self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=()')
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
  with DB.tx() as c:c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(after.get('workspace_id','default') if isinstance(after,dict) else 'default',a['user_id'],None,op,typ,eid,dumps(before or {}),dumps(after or {}),reason,now_ms()))
 def do_OPTIONS(self):self.send_response(204);self.security_headers();self.end_headers()
 def safe_route(self,m):
  try:self.route(m)
  except ValueError as e:
   code=str(e);self.sendj({'ok':False,'code':code,'message':'请求体超过 1MiB' if code=='REQUEST_TOO_LARGE' else 'JSON 请求体无效'},413 if code=='REQUEST_TOO_LARGE' else 400)
  except Exception as e:
   self.log_message('internal error: %s',e);self.sendj({'ok':False,'code':'INTERNAL_ERROR','message':'服务器内部错误'},500)
 def do_GET(self):self.safe_route('GET')
 def do_POST(self):self.safe_route('POST')
 def do_PATCH(self):self.safe_route('PATCH')
 def do_DELETE(self):self.safe_route('DELETE')
 def route(self,m):
  u=urlparse(self.path);p=u.path;q={k:v[-1] for k,v in parse_qs(u.query).items()};wid=q.get('workspace_id','default')
  if p in ('/health','/api/health'):return self.sendj({'ok':True,'version':VERSION,'schemaVersion':207,'database':DB.quick_check()})
  if p in ('/admin','/admin/'):
   self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(ADMIN)));self.security_headers();self.end_headers();return self.wfile.write(ADMIN)
  if p=='/api/v207/auth/login' and m=='POST':
   b=self.body();r,s=login(DB,str(b.get('organizationId') or ''),str(b.get('loginName') or ''),str(b.get('password') or ''),self.client_address[0],self.headers.get('User-Agent',''));return self.sendj(r,s)
  if p.startswith('/api/v205/') or p.startswith('/api/v206/'):
   return self.sendj({'ok':False,'code':'CLIENT_READ_ONLY','message':'V207 迁移期已冻结旧客户端写入；请升级 V207 客户端'},426)
  if not p.startswith('/api/v207/'):return self.sendj({'ok':False,'code':'NOT_FOUND'},404)
  a=self.actor()
  if not a:return self.sendj({'ok':False,'code':'UNAUTHORIZED','message':'请登录或重新登录'},401)
  if a.get('must_change') and p not in ('/api/v207/admin/profile','/api/v207/admin/change-password','/api/v207/auth/logout'):return self.sendj({'ok':False,'code':'PASSWORD_CHANGE_REQUIRED','message':'首次登录必须先修改密码'},403)
  if p.startswith('/api/v207/admin/') and p!='/api/v207/admin/channel-accounts' and admin_dispatch(self,m,p,q,a,DB):return
  if p=='/api/v207/session/context' and m=='GET':r,s=session_context(DB,a);return self.sendj(r,s)
  if p=='/api/v207/auth/logout' and m=='POST':
   token=self.headers.get('Authorization','')[7:].strip();import hashlib
   with DB.tx() as c:c.execute('UPDATE sessions SET revoked_at=? WHERE access_token_hash=?',(now_ms(),hashlib.sha256(token.encode()).hexdigest()))
   return self.sendj({'ok':True})
  if p=='/api/v207/accounts/resolve' and m=='POST':r,s=resolve_account(DB,a,self.body());return self.sendj(r,s)
  if p=='/api/v207/devices/register' and m=='POST':
   b=self.body();team=str(b.get('team_id') or '')
   if not can(DB,a,'device.rename.self',None,team):return self.sendj({'ok':False,'code':'FORBIDDEN','message':'无设备注册权限'},403)
   b.pop('actor_id',None);r,s=register_device(DB,a,b);return self.sendj(r,s)
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
  b=dict(b);b.pop('actor_id',None);b.pop('actorId',None);wid=str(b.get('workspaceId') or b.get('workspace_id') or 'default');sid=str(b.get('sourceId') or b.get('source_id') or '');op=str(b.get('operation') or '').lower();perm='contact.delete' if op in ('delete','contact.delete') else ('contact.restore' if op in ('restore','contact.restore') else 'contact.update')
  with DB.tx(False) as c:
   s=c.execute('SELECT workspace_id,organization_id,team_id,channel_account_id FROM sources WHERE source_id=?',(sid,)).fetchone()
   if not s or s['workspace_id']!=wid or s['organization_id']!=a['organization_id']:return err('SOURCE_SCOPE_INVALID','来源不属于当前企业或工作区',403)
   authorized=c.execute("SELECT 1 FROM team_memberships WHERE user_id=? AND team_id=? AND status='active'",(a['user_id'],s['team_id'])).fetchone();superadmin=c.execute("SELECT 1 FROM organization_memberships WHERE user_id=? AND organization_id=? AND role_id='role_superadmin' AND status='active'",(a['user_id'],a['organization_id'])).fetchone()
  if not (authorized or superadmin) or not can(DB,a,perm,wid,s['team_id']):return err('FORBIDDEN','无此联系人操作权限',403)
  b['workspaceId']=wid;b['workspace_id']=wid;b['sourceId']=sid;b['source_id']=sid;b['actor_id']=a['user_id'];b['user_id']=a['user_id'];r,status=apply_event(DB,b)
  if r.get('ok'):
   with DB.tx() as c:c.execute('UPDATE events SET user_id=? WHERE event_id=?',(a['user_id'],str(b.get('eventId') or b.get('event_id') or '')))
  return r,status
 def channel_account(self,a):
  if not can(DB,a,'account.bind'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
  b=self.body();requested_pid=str(b.get('platformId') or '');ch=str(b.get('channel') or '').lower();identity=canonical(b.get('identity'));team=str(b.get('teamId') or '')
  if not (ch or requested_pid) or not identity or not team:return self.sendj({'ok':False,'code':'INVALID_ACCOUNT'},400)
  with DB.tx() as c:
   t=c.execute('SELECT * FROM teams WHERE team_id=? AND organization_id=?',(team,a['organization_id'])).fetchone()
   if not t:return self.sendj({'ok':False,'code':'TEAM_NOT_FOUND'},404)
   platform_row=c.execute("SELECT * FROM platforms WHERE status='active' AND (platform_id=? OR (?='' AND platform_code=?))",(requested_pid,requested_pid,ch)).fetchone()
   if not platform_row:return self.sendj({'ok':False,'code':'PLATFORM_NOT_FOUND'},404)
   pid=platform_row['platform_id'];ch=platform_row['platform_code'];n=now_ms();aid='acc_'+uuid.uuid4().hex;iid='idn_'+uuid.uuid4().hex;sid='src_'+uuid.uuid4().hex
   c.execute('INSERT INTO channel_accounts(channel_account_id,organization_id,channel,display_name,status,created_at,updated_at,platform_id,account_type,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?)',(aid,a['organization_id'],ch,str(b.get('displayName') or identity),'active',n,n,pid,str(b.get('accountType') or 'business_account'),'{}'));c.execute('INSERT INTO channel_account_identities(identity_id,channel_account_id,identity_type,identity_value,canonical_value,created_at,platform_id,is_primary,status,valid_from,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(iid,aid,str(b.get('identityType') or 'login'),str(b.get('identity')),identity,n,pid,1,'active',n,'{}'));c.execute('INSERT INTO team_channel_accounts(team_id,channel_account_id,granted_by,granted_at) VALUES(?,?,?,?)',(team,aid,a['user_id'],n));c.execute("INSERT INTO sources(source_id,workspace_id,channel,account_identity,source_name,status,first_seen_at,last_seen_at,metadata_json,organization_id,team_id,channel_account_id) VALUES(?,?,?,?,?,'active',?,?,'{}',?,?,?)",(sid,t['workspace_id'],ch,str(b.get('identity')),str(b.get('sourceName') or b.get('displayName') or identity),n,n,a['organization_id'],team,aid))
  self.audit(a,'create','channel_account',aid,{},dict(b,workspace_id=t['workspace_id']));return self.sendj({'ok':True,'channelAccountId':aid,'sourceId':sid},201)
 def create_team(self,a):
  if not can(DB,a,'team.manage'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
  b=self.body();tid='team_'+uuid.uuid4().hex;wid='ws_'+uuid.uuid4().hex;n=now_ms();name=str(b.get('name') or '').strip()
  if not name:return self.sendj({'ok':False,'code':'NAME_REQUIRED'},400)
  with DB.tx() as c:c.execute('INSERT INTO workspaces(workspace_id,name,status,created_at,updated_at,organization_id) VALUES(?,?,\'active\',?,?,?)',(wid,name,n,n,a['organization_id']));c.execute('INSERT INTO workspace_configs(workspace_id,revision,items_json,updated_at,updated_by) VALUES(?,0,\'[]\',?,?)',(wid,n,a['user_id']));c.execute('INSERT INTO teams(team_id,organization_id,workspace_id,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(tid,a['organization_id'],wid,name,'active',n,n))
  return self.sendj({'ok':True,'teamId':tid,'workspaceId':wid},201)
 def create_user(self,a):
  if not can(DB,a,'user.manage'):return self.sendj({'ok':False,'code':'FORBIDDEN'},403)
  b=self.body();uid='usr_'+uuid.uuid4().hex;n=now_ms();pwd=str(b.get('password') or '');loginname=str(b.get('loginName') or '').strip();team=str(b.get('teamId') or '');role=str(b.get('roleId') or 'role_operator')
  if not password_strong(pwd) or not loginname:return self.sendj({'ok':False,'code':'WEAK_OR_INVALID_CREDENTIAL'},400)
  h,salt,it=hash_password(pwd)
  try:
   with DB.tx() as c:c.execute('INSERT INTO users(user_id,organization_id,login_name,display_name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(uid,a['organization_id'],loginname,str(b.get('displayName') or loginname),'active',n,n));c.execute('INSERT INTO user_credentials(user_id,password_hash,salt,iterations,must_change,updated_at) VALUES(?,?,?,?,?,?)',(uid,h,salt,it,1,n));c.execute('INSERT INTO team_memberships(user_id,team_id,role_id,status) VALUES(?,?,?,\'active\')',(uid,team,role))
  except Exception:return self.sendj({'ok':False,'code':'USER_CREATE_FAILED'},409)
  return self.sendj({'ok':True,'userId':uid},201)
def main():
 global DB
 ap=argparse.ArgumentParser();ap.add_argument('--db',default='jubaopen-v207.db');ap.add_argument('--host',default='127.0.0.1');ap.add_argument('--port',type=int,default=8765);ap.add_argument('--admin-password');a=ap.parse_args();DB=Database(a.db);DB.initialize(a.admin_password)
 with DB.tx(False) as c:pwd=c.execute("SELECT value FROM meta WHERE key='initial_admin_password'").fetchone()
 if pwd:print('首次管理员：admin / '+pwd[0]+'（登录后请立即修改）')
 print('V207 服务：http://%s:%s/admin'%(a.host,a.port));ThreadingHTTPServer((a.host,a.port),H).serve_forever()
if __name__=='__main__':main()
