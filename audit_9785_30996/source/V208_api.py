# -*- coding: utf-8 -*-
"""V208 HTTP 边界。匿名接入仅开放一次性邀请码核销，其余接口均要求受限插件会话。"""
from urllib.parse import unquote
import time
import logging
from V207_security import actor_from_token,can,permissions
from V208_collector_service import (issue_plugin_session,plugin_actor,heartbeat,list_channel_accounts,
 bind_account,detect_account,enroll_plugin,rebind_plugin,plugin_context,update_plugin_device,logout_plugin,resolve_conversation,resolve_follow_ups,collect_messages,collection_state)
from V208_interaction_service import chat_context,contact_version,update_contact,update_fields,update_tags,update_next_follow_up,register_contact
from V208_conversation_service import list_conversations,get_conversation,list_messages,transition_conversation,delete_content
from V208_transfer_service import create_transfer,list_transfer_candidates,transition_transfer
from V221_identity_service import find_candidates,link_identity,search_contacts
from V208_follow_up_notification_service import poll_notifications,receipt_action,list_notifications,notification_summary

_ENROLL_ATTEMPTS={}
def _token(h):
 x=h.headers.get('Authorization','');return x[7:].strip() if x.lower().startswith('bearer ') else ''
def _send(h,result):payload,status=result;h.sendj(payload,status);return True
def _forbidden(h,actor=None,path='',method='',required=None,effective=None,code='FORBIDDEN',message='权限不足'):
 required=list(required or [])
 eff=sorted(list(effective or []))[:300]
 detail={'path':path,'method':method,'required':required,'userId':(actor or {}).get('user_id'),'organizationId':(actor or {}).get('organization_id'),'workspaceId':(actor or {}).get('workspace_id'),'teamId':(actor or {}).get('team_id'),'deviceId':(actor or {}).get('device_id'),'effectivePermissions':eff}
 logging.warning('API permission denied: %s',detail)
 h.sendj({'ok':False,'code':code,'message':message,'requiredPermissions':required,'path':path,'method':method},403);return True
def _query_flag(value):
 if isinstance(value,list):value=value[-1] if value else ''
 return str(value or '').strip().lower() in ('1','true','yes')
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
 if p=='/api/v207/collector/rebind' and m=='POST':
  b=h.body();installation=str(b.get('installationId') or b.get('installation_id') or '')[:160];ip=_client_ip(h)
  if _enroll_limited(ip,installation):return _send(h,({'ok':False,'code':'REBIND_RATE_LIMITED','message':'换绑尝试过于频繁，请稍后重试'},429))
  return _send(h,rebind_plugin(db,b,ip,h.headers.get('User-Agent','')))
 if p=='/api/v207/collector/session' and m=='POST':
  actor=actor_from_token(db,_token(h))
  if not actor:return _send(h,({'ok':False,'code':'UNAUTHORIZED','message':'请先登录'},401))
  b=h.body();wid=str(b.get('workspaceId') or b.get('workspace_id') or '');team=str(b.get('teamId') or b.get('team_id') or '')
  if not can(db,actor,'collector.session.issue',wid,team):return _forbidden(h)
  return _send(h,issue_plugin_session(db,actor,b))
 a=plugin_actor(db,_token(h),True)
 if not a:return _send(h,({'ok':False,'code':'PLUGIN_UNAUTHORIZED','message':'插件凭证无效、过期或已撤销'},401))
 # Resolve scoped RBAC once per request; alternative permissions must not repeat DB queries.
 effective_permissions=None
 def _effective_permissions():
  nonlocal effective_permissions
  if effective_permissions is None:
   effective_permissions=frozenset(permissions(db,a['user_id'],workspace_id=a['workspace_id'],team_id=a['team_id'],resource_user_id=a['user_id'],organization_id=a['organization_id']))
  return effective_permissions
 def allowed(permission):
  return permission in _effective_permissions()
 def denied(required,code='FORBIDDEN',message='权限不足'):
  req=list(required) if isinstance(required,(list,tuple,set)) else [required]
  return _forbidden(h,actor=a,path=p,method=m,required=req,effective=_effective_permissions(),code=code,message=message)
 def allow_any(required):
  req=list(required) if isinstance(required,(list,tuple,set)) else [required]
  return any(allowed(x) for x in req)
 a=dict(a);a['_conversation_access']='self'
 if p=='/api/v207/collector/context' and m=='GET':return _send(h,plugin_context(db,a))
 if p=='/api/v207/collector/device' and m in ('PATCH','PUT'):return _send(h,update_plugin_device(db,a,h.body()))
 if p=='/api/v207/collector/logout' and m=='POST':return _send(h,logout_plugin(db,a))
 if p=='/api/v207/collector/heartbeat' and m=='POST':return _send(h,heartbeat(db,a))
 if p=='/api/v207/collector/channel-accounts' and m=='GET':
  args={k:(v[0] if isinstance(v,list) and v else v) for k,v in q.items()};return _send(h,list_channel_accounts(db,a,args))
 if p=='/api/v207/collector/accounts/detect' and m=='POST':return _send(h,detect_account(db,a,h.body()))
 if p=='/api/v207/collector/accounts/resolve' and m=='POST':return _send(h,bind_account(db,a,h.body()))
 if p=='/api/v207/collector/conversations/resolve' and m=='POST':return _send(h,resolve_conversation(db,a,h.body()))
 if p=='/api/v207/collector/follow-ups/resolve' and m=='POST':return _send(h,resolve_follow_ups(db,a,h.body()))
 if p=='/api/v207/collector/follow-up-notifications/poll' and m=='POST':return _send(h,poll_notifications(db,a,h.body()))
 if p=='/api/v207/collector/follow-up-notifications' and m=='GET':return _send(h,list_notifications(db,a,q))
 if p=='/api/v207/collector/follow-up-notifications/summary' and m=='GET':return _send(h,notification_summary(db,a))
 if p=='/api/v207/collector/messages/batch' and m=='POST':return _send(h,collect_messages(db,a,h.body()))
 if p=='/api/v207/collector/transfers/candidates' and m=='GET':return _send(h,list_transfer_candidates(db,a,q)) if allowed('transfer.read.self') or allowed('transfer.match') else _forbidden(h)
 if p=='/api/v207/interaction/contacts/register' and m=='POST':
  required=['collector.write','contact.create']
  # 210.2.55: creation is a write operation; both permissions are mandatory.
  return _send(h,register_contact(db,a,h.body())) if all(allowed(x) for x in required) else denied(required,'CONTACT_REGISTER_PERMISSION_DENIED','当前业务员账号缺少“采集写入”或“新建客户”权限，请重启后端以应用 210.2.55 权限基线。')
 if p=='/api/v207/interaction/contacts/candidates' and m=='POST':
  required=['contact.read.assigned','contact.read']
  return _send(h,find_candidates(db,a,h.body())) if allow_any(required) else denied(required,'CONTACT_CANDIDATE_PERMISSION_DENIED','当前账号没有查询候选客户的权限')
 if p=='/api/v207/interaction/contacts/search' and m=='POST':
  required=['contact.read.assigned','contact.read']
  return _send(h,search_contacts(db,a,h.body())) if allow_any(required) else denied(required,'CONTACT_SEARCH_PERMISSION_DENIED','当前账号没有搜索客户的权限')
 parts=[unquote(x) for x in p.strip('/').split('/')]
 if len(parts)==6 and parts[2]=='collector' and parts[3]=='follow-up-notifications' and parts[5] in ('read','snooze','dismiss','complete') and m=='POST':return _send(h,receipt_action(db,a,parts[4],parts[5],h.body()))
 if len(parts)==6 and parts[2]=='collector' and parts[3]=='conversations' and parts[5]=='collection-state' and m=='GET':
  return _send(h,collection_state(db,a,parts[4]))

 if len(parts)==6 and parts[2]=='collector' and parts[3]=='transfers' and parts[5] in ('match','confirm') and m=='POST':
  action=parts[5];permission='transfer.match' if action=='match' else 'transfer.confirm'
  return _send(h,transition_transfer(db,a,parts[4],action,h.body())) if allowed(permission) else _forbidden(h)
 if len(parts)>=5 and parts[2]=='interaction' and parts[3]=='contacts':
  cid=parts[4]
  if len(parts)==6 and parts[5]=='link-current' and m=='POST':return _send(h,link_identity(db,a,cid,h.body(),True)) if allowed('collector.write') else _forbidden(h)
  if len(parts)==6 and parts[5]=='version' and m=='GET':
   required=['contact.read.assigned','contact.read','collector.write']
   if not any(allowed(x) for x in required):return _forbidden(h,a,p,m,required,effective_permissions,'CONTACT_READ_PERMISSION_DENIED','当前账号没有读取客户资料的权限')
   return _send(h,contact_version(db,a,cid))
  if len(parts)==5 and m=='GET':
   required=['contact.read.assigned','contact.read','collector.write']
   if not any(allowed(x) for x in required):return _forbidden(h,a,p,m,required,effective_permissions,'CONTACT_READ_PERMISSION_DENIED','当前账号没有读取客户资料的权限')
   return _send(h,chat_context(db,a,cid))
  if len(parts)==5 and m=='PATCH':return _send(h,update_contact(db,a,cid,h.body())) if allowed('contact.update.assigned') else _forbidden(h)
  if len(parts)==6 and parts[5]=='next-follow-up' and m in ('PATCH','PUT'):return _send(h,update_next_follow_up(db,a,cid,h.body())) if allowed('contact.update.assigned') else _forbidden(h)
  if len(parts)==6 and parts[5] in ('fields','stages') and m in ('PATCH','PUT'):return _send(h,update_fields(db,a,cid,h.body())) if allowed('contact.update.assigned') else _forbidden(h)
  if len(parts)==6 and parts[5]=='tags' and m in ('PATCH','PUT'):return _send(h,update_tags(db,a,cid,h.body())) if allowed('contact.update.assigned') else _forbidden(h)
  if len(parts)==6 and parts[5]=='transfers' and m=='POST':return _send(h,create_transfer(db,a,cid,h.body())) if allowed('transfer.create') else _forbidden(h)
 if len(parts)==4 and parts[2]=='interaction' and parts[3]=='conversations' and m=='GET':
  return _send(h,list_conversations(db,a,q)) if allowed('conversation.read.self') else _forbidden(h)
 if len(parts)>=5 and parts[2]=='interaction' and parts[3]=='conversations':
  cid=parts[4]
  if len(parts)==5 and m=='GET':return _send(h,get_conversation(db,a,cid)) if allowed('conversation.read.self') else _forbidden(h)
  if len(parts)==6 and parts[5]=='messages' and m=='GET':
   raw=_query_flag(q.get('raw'))
   permitted=allowed('message.read.self') and (not raw or allowed('message.read.raw'))
   return _send(h,list_messages(db,a,cid,q.get('limit') or '100',q.get('before') or None,raw,q.get('cursor') or None)) if permitted else _forbidden(h)
  if len(parts)==6 and parts[5] in ('close','reopen','archive') and m=='POST':
   action=parts[5];perm='conversation.archive' if action=='archive' else 'conversation.close'
   return _send(h,transition_conversation(db,a,cid,action,h.body())) if allowed(perm) else _forbidden(h)
 if len(parts)==6 and parts[2]=='interaction' and parts[3]=='messages' and parts[5]=='content' and m=='DELETE':
  return _send(h,delete_content(db,a,parts[4],h.body().get('reason'))) if allowed('message.delete.content') else _forbidden(h)
 return _send(h,({'ok':False,'code':'NOT_FOUND'},404))
