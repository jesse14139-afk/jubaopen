# -*- coding: utf-8 -*-
"""V208 HTTP 边界。匿名接入仅开放一次性邀请码核销，其余接口均要求受限插件会话。"""
from urllib.parse import unquote
import time
from V207_security import actor_from_token,can
from V208_collector_service import (issue_plugin_session,plugin_actor,heartbeat,list_channel_accounts,
 bind_account,detect_account,enroll_plugin,plugin_context,logout_plugin,resolve_conversation,collect_messages)
from V208_interaction_service import chat_context,update_contact,update_fields,update_tags
from V208_conversation_service import list_messages,delete_content
from V208_transfer_service import create_transfer

_ENROLL_ATTEMPTS={}
def _token(h):
 x=h.headers.get('Authorization','');return x[7:].strip() if x.lower().startswith('bearer ') else ''
def _send(h,result):payload,status=result;h.sendj(payload,status);return True
def _forbidden(h):h.sendj({'ok':False,'code':'FORBIDDEN','message':'权限不足'},403);return True
def _client_ip(h):
 # 不信任任意 X-Forwarded-For；反向代理应覆盖为单值 X-Real-IP。
 return str(h.headers.get('X-Real-IP') or getattr(h,'client_address',('unknown',))[0])[:80]
def _enroll_limited(ip,installation):
 now=time.time();keys=('ip:'+ip,'installation:'+installation);limited=False
 for key in keys:
  seq=[x for x in _ENROLL_ATTEMPTS.get(key,[]) if now-x<900]
  window=[x for x in seq if now-x<60]
  limit=10 if key.startswith('ip:') else 5
  if len(window)>=limit or (key.startswith('installation:') and len(seq)>=5):limited=True
  seq.append(now);_ENROLL_ATTEMPTS[key]=seq[-20:]
 return limited
def dispatch(h,m,p,q,db):
 if not (p.startswith('/api/v207/collector/') or p.startswith('/api/v207/interaction/')):return False
 if p=='/api/v207/collector/enroll' and m=='POST':
  b=h.body();installation=str(b.get('installationId') or b.get('installation_id') or '')[:160];ip=_client_ip(h)
  if _enroll_limited(ip,installation):return _send(h,({'ok':False,'code':'ENROLLMENT_RATE_LIMITED','message':'接入尝试过于频繁，请稍后重试'},429))
  return _send(h,enroll_plugin(db,b,ip,h.headers.get('User-Agent','')))
 if p=='/api/v207/collector/session' and m=='POST':
  actor=actor_from_token(db,_token(h))
  if not actor:return _send(h,({'ok':False,'code':'UNAUTHORIZED','message':'请先登录'},401))
  b=h.body();wid=str(b.get('workspaceId') or b.get('workspace_id') or '');team=str(b.get('teamId') or b.get('team_id') or '')
  if not can(db,actor,'collector.session.issue',wid,team):return _forbidden(h)
  return _send(h,issue_plugin_session(db,actor,b))
 a=plugin_actor(db,_token(h),True)
 if not a:return _send(h,({'ok':False,'code':'PLUGIN_UNAUTHORIZED','message':'插件凭证无效、过期或已撤销'},401))
 def allowed(permission):return can(db,a,permission,a['workspace_id'],a['team_id'],resource_user_id=a['user_id'])
 if p=='/api/v207/collector/context' and m=='GET':return _send(h,plugin_context(db,a))
 if p=='/api/v207/collector/logout' and m=='POST':return _send(h,logout_plugin(db,a))
 if p=='/api/v207/collector/heartbeat' and m=='POST':return _send(h,heartbeat(db,a))
 if p=='/api/v207/collector/channel-accounts' and m=='GET':
  args={k:(v[0] if isinstance(v,list) and v else v) for k,v in q.items()};return _send(h,list_channel_accounts(db,a,args))
 if p=='/api/v207/collector/accounts/detect' and m=='POST':return _send(h,detect_account(db,a,h.body()))
 if p=='/api/v207/collector/accounts/resolve' and m=='POST':return _send(h,bind_account(db,a,h.body()))
 if p=='/api/v207/collector/conversations/resolve' and m=='POST':return _send(h,resolve_conversation(db,a,h.body()))
 if p=='/api/v207/collector/messages/batch' and m=='POST':return _send(h,collect_messages(db,a,h.body()))
 parts=[unquote(x) for x in p.strip('/').split('/')]
 if len(parts)>=5 and parts[2]=='interaction' and parts[3]=='contacts':
  cid=parts[4]
  if len(parts)==5 and m=='GET':return _send(h,chat_context(db,a,cid)) if allowed('contact.read.assigned') else _forbidden(h)
  if len(parts)==5 and m=='PATCH':return _send(h,update_contact(db,a,cid,h.body())) if allowed('contact.update.assigned') else _forbidden(h)
  if len(parts)==6 and parts[5] in ('fields','stages') and m in ('PATCH','PUT'):return _send(h,update_fields(db,a,cid,h.body())) if allowed('contact.update.assigned') else _forbidden(h)
  if len(parts)==6 and parts[5]=='tags' and m in ('PATCH','PUT'):return _send(h,update_tags(db,a,cid,h.body())) if allowed('contact.update.assigned') else _forbidden(h)
  if len(parts)==6 and parts[5]=='transfers' and m=='POST':return _send(h,create_transfer(db,a,cid,h.body())) if allowed('transfer.create') else _forbidden(h)
 if len(parts)==6 and parts[2]=='interaction' and parts[3]=='conversations' and parts[5]=='messages' and m=='GET':
  raw=str(q.get('raw') or '0')=='1';perm='message.read.raw' if raw else 'message.read.self'
  return _send(h,list_messages(db,a,parts[4],q.get('limit') or '100',q.get('before') or None,raw)) if allowed(perm) else _forbidden(h)
 if len(parts)==6 and parts[2]=='interaction' and parts[3]=='messages' and parts[5]=='content' and m=='DELETE':
  return _send(h,delete_content(db,a,parts[4],h.body().get('reason'))) if allowed('message.delete.content') else _forbidden(h)
 return _send(h,({'ok':False,'code':'NOT_FOUND'},404))
