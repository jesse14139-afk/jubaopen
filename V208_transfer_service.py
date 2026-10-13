# -*- coding: utf-8 -*-
"""Schema 222 客户转交领域服务。"""
import hashlib
import json
import sqlite3
import uuid
from V207_shared_db import now_ms,dumps
from V209_validation import write_audit

ACTIVE=('pending','matched')
TRANSITIONS={
 'match':({'pending'},'matched','matched'),
 'confirm':({'matched'},'confirmed','confirmed'),
 'reject':({'pending','matched'},'rejected','rejected'),
 'cancel':({'pending','matched'},'cancelled','cancelled'),
 'fail':({'pending','matched'},'failed','failed'),
 'expire':({'pending','matched'},'expired','expired'),
}

def _err(code,message,status=400,**extra):
 out={'ok':False,'code':code,'message':message};out.update(extra);return out,status

def _scope(a):return (a['organization_id'],a['workspace_id'],a['team_id'])
def _text(v):return str(v or '').strip()
def _hash(payload):return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def _row(row):
 if not row:return None
 out=dict(row)
 for key in ('metadata_json','match_evidence_json','details_json'):
  if key in out:
   try:out[key[:-5] if key.endswith('_json') else key]=json.loads(out.pop(key) or '{}')
   except Exception:out[key[:-5] if key.endswith('_json') else key]={}
 return out

def _event(c,row,event_type,actor,from_status,to_status,reason='',details=None,conversation_id=None,channel_account_id=None):
 c.execute("""INSERT INTO contact_transfer_events(event_id,transfer_id,organization_id,workspace_id,team_id,contact_id,event_type,from_status,to_status,actor_id,conversation_id,channel_account_id,reason,details_json,created_at)
 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",('tre_'+uuid.uuid4().hex,row['transfer_id'],row['organization_id'],row['workspace_id'],row['team_id'],row['contact_id'],event_type,from_status,to_status,actor,conversation_id,channel_account_id,reason,dumps(details or {}),now_ms()))

def _find(c,a,transfer_id):
 sql="SELECT * FROM contact_transfers WHERE transfer_id=? AND organization_id=? AND workspace_id=? AND team_id=?";params=[transfer_id]+list(_scope(a))
 if a.get('_transfer_access')=='self':sql+=' AND requested_by=?';params.append(a['user_id'])
 return c.execute(sql,tuple(params)).fetchone()

def create_transfer(db,a,cid,p):
 if not isinstance(p,dict):return _err('INVALID_BODY','请求正文必须是对象')
 to=_text(p.get('toChannelAccountId'));source=_text(p.get('fromChannelAccountId')) or None
 conversation=_text(p.get('fromConversationId')) or None;to_conversation=_text(p.get('toConversationId')) or None
 method=_text(p.get('transferMethod') or 'other');transfer_type=_text(p.get('transferType') or 'channel_transfer')
 reason=_text(p.get('reason'));key=_text(p.get('idempotencyKey'))
 allowed_methods=('phone_shared','username_shared','invite_link','qr_code','manual_link','system_match','other')
 if not to or not key or method not in allowed_methods or transfer_type not in ('channel_transfer','owner_reassignment','team_handoff'):
  return _err('INVALID_TRANSFER','目标账号、幂等键或转交参数无效')
 if len(key)>200:return _err('IDEMPOTENCY_KEY_TOO_LONG','幂等键不能超过 200 个字符')
 if len(reason)>1000:return _err('TRANSFER_REASON_TOO_LONG','转交原因不能超过 1000 个字符')
 if source and source==to:return _err('TRANSFER_TARGET_SAME','目标账号不能与来源账号相同',409)
 expires=p.get('expiresAt')
 if expires is not None:
  try:expires=int(expires)
  except Exception:return _err('INVALID_EXPIRES_AT','过期时间无效')
  if expires<=now_ms():return _err('INVALID_EXPIRES_AT','过期时间必须晚于当前时间')
 canonical={'contactId':cid,'toChannelAccountId':to,'fromChannelAccountId':source,'fromConversationId':conversation,'toConversationId':to_conversation,'transferMethod':method,'transferType':transfer_type,'reason':reason,'expiresAt':expires,'metadata':p.get('metadata') or {}}
 request_hash=_hash(canonical)
 with db.tx() as c:
  old=c.execute("SELECT transfer_id,status,request_hash FROM contact_transfers WHERE organization_id=? AND idempotency_key=?",(a['organization_id'],key)).fetchone()
  if old:
   if old['request_hash']!=request_hash:return _err('IDEMPOTENCY_CONFLICT','同一幂等键对应不同请求',409,transferId=old['transfer_id'])
   return ({'ok':True,'transferId':old['transfer_id'],'status':old['status'],'idempotentReplay':True},200)
  contact=c.execute("SELECT 1 FROM contacts WHERE contact_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND deleted_at IS NULL",(cid,)+_scope(a)).fetchone()
  if not contact:return _err('CONTACT_SCOPE_INVALID','客户不存在、已删除或不属于当前作用域',404)
  account=c.execute("""SELECT x.platform_id FROM channel_accounts x JOIN team_channel_accounts t ON t.channel_account_id=x.channel_account_id AND t.team_id=?
   WHERE x.channel_account_id=? AND x.organization_id=? AND x.status='active' AND x.collection_enabled=1
   AND (EXISTS(SELECT 1 FROM user_channel_account_grants g WHERE g.channel_account_id=x.channel_account_id AND g.user_id=?) OR EXISTS(SELECT 1 FROM platform_administrators pa WHERE pa.user_id=?))""",(a['team_id'],to,a['organization_id'],a['user_id'],a['user_id'])).fetchone()
  if not account:return _err('TRANSFER_TARGET_UNAUTHORIZED','目标账号不存在或当前用户无权使用',403)
  from_platform=None
  if conversation:
   conv=c.execute("SELECT channel_account_id,platform_id FROM conversations WHERE conversation_id=? AND contact_id=? AND organization_id=? AND workspace_id=? AND team_id=?",(conversation,cid)+_scope(a)).fetchone()
   if not conv:return _err('TRANSFER_SOURCE_INVALID','来源会话不属于当前客户',403)
   if source and conv['channel_account_id']!=source:return _err('TRANSFER_SOURCE_INVALID','来源账号与来源会话不一致',409)
   source=conv['channel_account_id'];from_platform=conv['platform_id']
  elif source:
   conv=c.execute("SELECT platform_id FROM conversations WHERE contact_id=? AND channel_account_id=? AND organization_id=? AND workspace_id=? AND team_id=? LIMIT 1",(cid,source)+_scope(a)).fetchone()
   if not conv:return _err('TRANSFER_SOURCE_INVALID','来源账号不属于当前客户会话',403)
   from_platform=conv['platform_id']
  if source==to:return _err('TRANSFER_TARGET_SAME','目标账号不能与来源账号相同',409)
  if to_conversation:
   target=c.execute("SELECT 1 FROM conversations WHERE conversation_id=? AND contact_id=? AND channel_account_id=? AND organization_id=? AND workspace_id=? AND team_id=?",(to_conversation,cid,to)+_scope(a)).fetchone()
   if not target:return _err('TRANSFER_TARGET_CONVERSATION_INVALID','目标会话不属于客户或目标账号',409)
  duplicate=c.execute("SELECT transfer_id FROM contact_transfers WHERE organization_id=? AND workspace_id=? AND contact_id=? AND to_channel_account_id=? AND status IN ('pending','matched') LIMIT 1",(a['organization_id'],a['workspace_id'],cid,to)).fetchone()
  if duplicate:return _err('TRANSFER_PENDING_EXISTS','该客户到此目标账号已有处理中转交',409,transferId=duplicate['transfer_id'])
  n=now_ms();tid='trf_'+uuid.uuid4().hex
  try:
   c.execute("""INSERT INTO contact_transfers(transfer_id,organization_id,workspace_id,team_id,contact_id,transfer_type,from_channel_account_id,from_conversation_id,from_platform_id,to_channel_account_id,to_conversation_id,to_platform_id,transfer_method,status,requested_by,requested_at,expires_at,reason,idempotency_key,request_hash,metadata_json,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'pending',?,?,?,?,?,?,?,?,?)""",(tid,a['organization_id'],a['workspace_id'],a['team_id'],cid,transfer_type,source,conversation,from_platform,to,to_conversation,account['platform_id'],method,a['user_id'],n,expires,reason,key,request_hash,dumps(p.get('metadata') or {}),n,n))
  except sqlite3.IntegrityError as exc:
   if 'uq_transfers_pending_target' in str(exc) or 'UNIQUE constraint failed' in str(exc):return _err('TRANSFER_PENDING_EXISTS','该客户到此目标账号已有处理中转交',409)
   raise
  row=_find(c,a,tid);_event(c,row,'created',a['user_id'],None,'pending',reason,{'transferMethod':method,'transferType':transfer_type},conversation,source)
  write_audit(c,a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'],'transfer.create','contact_transfer',tid,{}, {'status':'pending','contactId':cid,'toChannelAccountId':to,'version':1},reason or None,device_id=a.get('device_id'))
  return ({'ok':True,'transferId':tid,'status':'pending','version':1,'idempotentReplay':False},201)

def transition_transfer(db,a,transfer_id,action,p):
 if action not in TRANSITIONS:return _err('TRANSFER_ACTION_INVALID','不支持的转交操作',404)
 if not isinstance(p,dict):return _err('INVALID_BODY','请求正文必须是对象')
 try:base=int(p.get('baseVersion'))
 except Exception:return _err('BASE_VERSION_REQUIRED','必须提供有效的 baseVersion')
 if base<1:return _err('BASE_VERSION_INVALID','baseVersion 必须是大于零的整数')
 allowed,target,event=TRANSITIONS[action];reason=_text(p.get('reason'))
 if action in ('reject','fail') and not reason:return _err('TRANSFER_REASON_REQUIRED','此操作必须填写原因')
 if len(reason)>1000:return _err('TRANSFER_REASON_TOO_LONG','原因不能超过 1000 个字符')
 with db.tx() as c:
  row=_find(c,a,transfer_id)
  if not row:return _err('TRANSFER_NOT_FOUND','转交记录不存在',404)
  if action=='cancel' and row['requested_by']!=a['user_id'] and not a.get('_transfer_manage'):
   return _err('TRANSFER_CANCEL_FORBIDDEN','只能取消本人发起的转交',403)
  if row['status']==target:
   requested_conversation=_text(p.get('toConversationId'));requested_identity=_text(p.get('matchedIdentityId'))
   if requested_conversation and requested_conversation!=_text(row['to_conversation_id']):return _err('IDEMPOTENCY_CONFLICT','重复操作的目标会话与已保存结果不一致',409,currentVersion=row['version'],currentStatus=row['status'])
   if requested_identity and requested_identity!=_text(row['matched_identity_id']):return _err('IDEMPOTENCY_CONFLICT','重复操作的匹配身份与已保存结果不一致',409,currentVersion=row['version'],currentStatus=row['status'])
   if action=='reject' and reason!=_text(row['rejection_reason']):return _err('IDEMPOTENCY_CONFLICT','重复拒绝的原因与已保存结果不一致',409,currentVersion=row['version'],currentStatus=row['status'])
   if action=='fail' and (reason!=_text(row['failure_reason']) or (_text(p.get('failureCode')) or 'TRANSFER_FAILED')!=(_text(row['failure_code']) or 'TRANSFER_FAILED')):return _err('IDEMPOTENCY_CONFLICT','重复失败操作的原因或失败码与已保存结果不一致',409,currentVersion=row['version'],currentStatus=row['status'])
   return ({'ok':True,'transferId':transfer_id,'status':target,'version':row['version'],'toConversationId':row['to_conversation_id'],'idempotentReplay':True},200)
  if row['version']!=base:return _err('TRANSFER_VERSION_CONFLICT','转交记录已更新，请刷新后重试',409,currentVersion=row['version'],currentStatus=row['status'])
  if action in ('match','confirm') and row['expires_at'] is not None and int(row['expires_at'])<=now_ms():return _err('TRANSFER_EXPIRED','转交已过期，不能继续匹配或确认',409,currentVersion=row['version'],currentStatus=row['status'])
  if row['status'] not in allowed:return _err('TRANSFER_TRANSITION_INVALID','当前状态不允许执行此操作',409,currentStatus=row['status'])
  n=now_ms();to_conversation=_text(p.get('toConversationId')) or row['to_conversation_id'];target_conv=None;identity=None
  if action in ('match','confirm'):
   if not to_conversation:return _err('TRANSFER_TARGET_CONVERSATION_REQUIRED','匹配或确认前必须指定目标会话',409)
   target_conv=c.execute("SELECT conversation_id,contact_id,contact_identity_id,channel_account_id,platform_id,version FROM conversations WHERE conversation_id=? AND channel_account_id=? AND organization_id=? AND workspace_id=? AND team_id=?",(to_conversation,row['to_channel_account_id'])+_scope(a)).fetchone()
   if not target_conv:return _err('TRANSFER_TARGET_CONVERSATION_INVALID','目标会话不存在、越权或不属于目标账号',409)
  identity_id=_text(p.get('matchedIdentityId')) or row['matched_identity_id']
  if identity_id:
   identity=c.execute("SELECT contact_identity_id,contact_id,platform_id,identity_type,canonical_value,verification_status FROM contact_identities WHERE contact_identity_id=? AND organization_id=?",(identity_id,a['organization_id'])).fetchone()
   if not identity or identity['contact_id']!=row['contact_id'] or identity['platform_id']!=row['to_platform_id'] or identity['verification_status'] not in ('observed','verified'):
    return _err('TRANSFER_MATCH_IDENTITY_INVALID','匹配身份不属于原客户、目标平台或尚未验证',409)
   if target_conv and target_conv['contact_identity_id']:
    target_identity=c.execute("SELECT platform_id,identity_type,canonical_value FROM contact_identities WHERE contact_identity_id=? AND organization_id=?",(target_conv['contact_identity_id'],a['organization_id'])).fetchone()
    if not target_identity or target_identity['platform_id']!=identity['platform_id'] or target_identity['identity_type']!=identity['identity_type'] or target_identity['canonical_value']!=identity['canonical_value']:
     return _err('TRANSFER_TARGET_IDENTITY_MISMATCH','匹配身份与目标会话实际采集身份不一致',409)
  confidence=p.get('matchConfidence',row['match_confidence'])
  if confidence is not None:
   try:confidence=int(confidence)
   except Exception:return _err('MATCH_CONFIDENCE_INVALID','匹配置信度无效')
   if not 0<=confidence<=100:return _err('MATCH_CONFIDENCE_INVALID','匹配置信度必须在 0 到 100 之间')
  if action=='confirm' and target_conv['contact_id']!=row['contact_id'] and not identity:
   return _err('TRANSFER_MATCH_EVIDENCE_REQUIRED','目标会话属于其他客户，确认前必须提供原客户在目标平台的有效身份',409)
  sets=['status=?','version=version+1','updated_at=?'];values=[target,n]
  fields={'confirm':('accepted_by','accepted_at'),'reject':('rejected_by','rejected_at'),'cancel':('cancelled_by','cancelled_at')}
  if action in fields:
   who,when=fields[action];sets += [who+'=?',when+'=?'];values += [a['user_id'],n]
  if action=='reject':sets.append('rejection_reason=?');values.append(reason)
  if action=='fail':sets += ['failed_at=?','failure_code=?','failure_reason=?'];values += [n,_text(p.get('failureCode')) or 'TRANSFER_FAILED',reason]
  if action=='expire':sets.append('expired_at=?');values.append(n)
  if action=='match':
   evidence=p.get('matchEvidence') or {}
   if not isinstance(evidence,dict):return _err('MATCH_EVIDENCE_INVALID','匹配证据必须是对象')
   sets += ['matched_identity_id=?','match_confidence=?','match_evidence_json=?'];values += [identity_id or None,confidence,dumps(evidence)]
  if action in ('match','confirm'):
   sets.append('to_conversation_id=?');values.append(to_conversation)
  # Conversation first, then messages: the message scope trigger validates against the new conversation owner.
  rebound=False;previous_contact=None;identity_bound=False
  if action=='confirm' and target_conv['contact_id']!=row['contact_id']:
   previous_contact=target_conv['contact_id']
   changed_conv=c.execute("UPDATE conversations SET contact_id=?,contact_identity_id=?,updated_at=?,version=version+1 WHERE conversation_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND version=?",(row['contact_id'],identity_id,n,to_conversation)+_scope(a)+(target_conv['version'],)).rowcount
   if changed_conv!=1:return _err('CONVERSATION_VERSION_CONFLICT','目标会话已更新，请刷新后重试',409)
   c.execute("UPDATE conversation_messages SET contact_id=? WHERE conversation_id=? AND organization_id=? AND workspace_id=? AND team_id=?",(row['contact_id'],to_conversation)+_scope(a));rebound=True;identity_bound=bool(identity_id)
  elif action=='confirm' and identity_id and not target_conv['contact_identity_id']:
   changed_conv=c.execute("UPDATE conversations SET contact_identity_id=?,updated_at=?,version=version+1 WHERE conversation_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND version=? AND contact_identity_id IS NULL",(identity_id,n,to_conversation)+_scope(a)+(target_conv['version'],)).rowcount
   if changed_conv!=1:return _err('CONVERSATION_VERSION_CONFLICT','目标会话已更新，请刷新后重试',409)
   identity_bound=True
  values += [transfer_id,base]
  changed=c.execute('UPDATE contact_transfers SET '+','.join(sets)+' WHERE transfer_id=? AND version=?',tuple(values)).rowcount
  if changed!=1:return _err('TRANSFER_VERSION_CONFLICT','转交记录已更新，请刷新后重试',409)
  fresh=_find(c,a,transfer_id);details={'baseVersion':base,'contactBound':bool(action=='confirm'),'conversationRebound':rebound,'identityBound':identity_bound,'previousContactId':previous_contact}
  _event(c,fresh,event,a['user_id'],row['status'],target,reason,details,fresh['to_conversation_id'],fresh['to_channel_account_id'])
  if to_conversation and to_conversation!=row['to_conversation_id']:_event(c,fresh,'target_conversation_linked',a['user_id'],target,target,'',details,to_conversation,fresh['to_channel_account_id'])
  write_audit(c,a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'],'transfer.'+action,'contact_transfer',transfer_id,{'status':row['status'],'version':row['version'],'toConversationId':row['to_conversation_id']},{'status':target,'version':fresh['version'],'toConversationId':fresh['to_conversation_id'],'conversationRebound':rebound,'identityBound':identity_bound},reason or None,device_id=a.get('device_id'))
  return ({'ok':True,'transferId':transfer_id,'status':target,'version':fresh['version'],'toConversationId':fresh['to_conversation_id'],'conversationRebound':rebound,'identityBound':identity_bound,'idempotentReplay':False},200)

# Schema 222 management-center transfer query extensions.
def transfer_meta(db,a):
 with db.tx(False) as c:
  accounts=c.execute("SELECT ca.channel_account_id,ca.display_name,ca.platform_id,p.platform_name,ca.status FROM channel_accounts ca JOIN team_channel_accounts ta ON ta.channel_account_id=ca.channel_account_id LEFT JOIN platforms p ON p.platform_id=ca.platform_id WHERE ca.organization_id=? AND ta.team_id=? AND ca.status='active' AND (EXISTS(SELECT 1 FROM user_channel_account_grants g WHERE g.channel_account_id=ca.channel_account_id AND g.user_id=?) OR EXISTS(SELECT 1 FROM platform_administrators pa WHERE pa.user_id=?)) ORDER BY p.platform_name,ca.display_name",(a['organization_id'],a['team_id'],a['user_id'],a['user_id'])).fetchall()
 return {'ok':True,'accounts':[dict(x) for x in accounts],'methods':['phone_shared','username_shared','invite_link','qr_code','manual_link','system_match','other'],'statuses':['pending','matched','confirmed','rejected','failed','cancelled','expired'],'defaultExpiresInMs':604800000},200

def list_transfers(db,a,q):
 where=['t.organization_id=?','t.workspace_id=?','t.team_id=?'];params=list(_scope(a))
 if a.get('_transfer_access')=='self':where.append('t.requested_by=?');params.append(a['user_id'])
 mappings=(('contactId','t.contact_id'),('status','t.status'),('fromPlatformId','t.from_platform_id'),('toPlatformId','t.to_platform_id'),('fromChannelAccountId','t.from_channel_account_id'),('toChannelAccountId','t.to_channel_account_id'),('requestedBy','t.requested_by'))
 for key,col in mappings:
  value=q.get(key);value=value[-1] if isinstance(value,list) and value else value
  if value:where.append(col+'=?');params.append(value)
 handled=q.get('handledBy');handled=handled[-1] if isinstance(handled,list) and handled else handled
 if handled:where.append('COALESCE(t.accepted_by,t.rejected_by,t.cancelled_by)=?');params.append(handled)
 for key,op in (('createdFrom','>='),('createdTo','<=')):
  value=q.get(key);value=value[-1] if isinstance(value,list) and value else value
  if value:
   try:value=int(value)
   except Exception:return _err('INVALID_TIME_RANGE','时间筛选必须是毫秒时间戳')
   where.append('t.requested_at'+op+'?');params.append(value)
 cursor=q.get('cursor');cursor=cursor[-1] if isinstance(cursor,list) and cursor else cursor
 if cursor:
  try:
   import base64
   point=json.loads(base64.urlsafe_b64decode(str(cursor)+'='*(-len(str(cursor))%4)).decode())
   where.append('(t.requested_at<? OR (t.requested_at=? AND t.transfer_id<?))');params.extend((int(point['t']),int(point['t']),str(point['id'])))
  except Exception:return _err('INVALID_CURSOR','游标无效')
 try:limit=max(1,min(int(q.get('limit',50)),200))
 except Exception:limit=50
 sql="SELECT t.*,ct.display_name contact_name,fp.platform_name from_platform_name,tp.platform_name to_platform_name,fa.display_name from_account_name,ta.display_name to_account_name,ru.display_name requested_by_name FROM contact_transfers t LEFT JOIN contacts ct ON ct.contact_id=t.contact_id LEFT JOIN platforms fp ON fp.platform_id=t.from_platform_id LEFT JOIN platforms tp ON tp.platform_id=t.to_platform_id LEFT JOIN channel_accounts fa ON fa.channel_account_id=t.from_channel_account_id LEFT JOIN channel_accounts ta ON ta.channel_account_id=t.to_channel_account_id LEFT JOIN users ru ON ru.user_id=t.requested_by WHERE "+' AND '.join(where)+' ORDER BY t.requested_at DESC,t.transfer_id DESC LIMIT ?'
 with db.tx(False) as c:rows=c.execute(sql,tuple(params+[limit+1])).fetchall()
 more=len(rows)>limit;rows=rows[:limit];next_cursor=None
 if more and rows:
  import base64
  next_cursor=base64.urlsafe_b64encode(dumps({'t':rows[-1]['requested_at'],'id':rows[-1]['transfer_id']}).encode()).decode().rstrip('=')
 return {'ok':True,'items':[_row(x) for x in rows],'nextCursor':next_cursor,'hasMore':more},200

def get_transfer(db,a,transfer_id):
 with db.tx(False) as c:
  row=_find(c,a,transfer_id)
  if not row:return _err('TRANSFER_NOT_FOUND','转交记录不存在',404)
  events=[_row(x) for x in c.execute('SELECT * FROM contact_transfer_events WHERE transfer_id=? ORDER BY created_at,event_id',(transfer_id,))]
  contact=c.execute('SELECT contact_id,display_name,phone,email,stage,status FROM contacts WHERE contact_id=? AND organization_id=? AND workspace_id=? AND team_id=?',(row['contact_id'],)+_scope(a)).fetchone()
  source=c.execute('SELECT conversation_id,platform_id,channel_account_id,status,last_message_at FROM conversations WHERE conversation_id=? AND organization_id=? AND workspace_id=? AND team_id=?',(row['from_conversation_id'],)+_scope(a)).fetchone() if row['from_conversation_id'] else None
  target=c.execute('SELECT conversation_id,platform_id,channel_account_id,status,last_message_at FROM conversations WHERE conversation_id=? AND organization_id=? AND workspace_id=? AND team_id=?',(row['to_conversation_id'],)+_scope(a)).fetchone() if row['to_conversation_id'] else None
 return {'ok':True,'transfer':_row(row),'contact':dict(contact) if contact else None,'sourceConversation':dict(source) if source else None,'targetConversation':dict(target) if target else None,'events':events},200


def list_transfer_candidates(db,a,q):
 """插件当前目标账号下的有效待处理转交；不返回原始匹配证据。"""
 q=q if isinstance(q,dict) else {}
 def one(name):
  value=q.get(name);return str(value[-1] if isinstance(value,list) and value else value or '').strip()
 account_id=one('channelAccountId');conversation_id=one('conversationId')
 if not account_id:return _err('CHANNEL_ACCOUNT_REQUIRED','必须提供当前渠道账号')
 with db.tx(False) as c:
  authorized=c.execute("""SELECT ca.platform_id FROM channel_accounts ca JOIN team_channel_accounts ta ON ta.channel_account_id=ca.channel_account_id AND ta.team_id=? WHERE ca.channel_account_id=? AND ca.organization_id=? AND ca.status='active' AND ca.collection_enabled=1 AND (EXISTS(SELECT 1 FROM user_channel_account_grants g WHERE g.user_id=? AND g.channel_account_id=ca.channel_account_id) OR EXISTS(SELECT 1 FROM platform_administrators pa WHERE pa.user_id=?))""",(a['team_id'],account_id,a['organization_id'],a['user_id'],a['user_id'])).fetchone()
  if not authorized:return _err('TRANSFER_TARGET_UNAUTHORIZED','当前插件无权读取该目标账号的转交',403)
  current=None
  if conversation_id:
   current=c.execute('SELECT conversation_id,contact_id,contact_identity_id FROM conversations WHERE conversation_id=? AND channel_account_id=? AND organization_id=? AND workspace_id=? AND team_id=?',(conversation_id,account_id)+_scope(a)).fetchone()
   if not current:return _err('CONVERSATION_SCOPE_INVALID','当前会话不存在或不属于目标账号',404)
  rows=c.execute("""SELECT t.transfer_id,t.contact_id,t.status,t.transfer_method,t.requested_at,t.expires_at,t.version,t.from_platform_id,t.from_channel_account_id,t.reason,c.display_name contact_name,u.display_name requested_by_name FROM contact_transfers t JOIN contacts c ON c.contact_id=t.contact_id LEFT JOIN users u ON u.user_id=t.requested_by WHERE t.organization_id=? AND t.workspace_id=? AND t.team_id=? AND t.to_channel_account_id=? AND t.status IN ('pending','matched') AND (t.expires_at IS NULL OR t.expires_at>?) ORDER BY t.requested_at DESC,t.transfer_id DESC LIMIT 20""",_scope(a)+(account_id,now_ms())).fetchall()
  items=[]
  for row in rows:
   item=dict(row);item['currentConversationId']=conversation_id or None
   item['alreadyMatched']=bool(current and row['contact_id']==current['contact_id'])
   item['suggestedAction']='confirm' if row['status']=='matched' else 'match'
   items.append(item)
 return {'ok':True,'items':items,'count':len(items)},200
