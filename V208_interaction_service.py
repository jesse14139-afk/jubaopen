# -*- coding: utf-8 -*-
"""V208 聊天侧互动：上下文、快捷字段、阶段与标签。"""
import json,uuid,hashlib,sqlite3,logging
from contextlib import nullcontext
from V207_shared_db import now_ms,dumps
from V208_identity import normalize_identity
from V208_name_sanitize import sanitize_observed_name
from V208_avatar import sanitize_avatar
from V208_follow_up_notification_service import sync_follow_up_plan_in_tx
from V208_collector_service import _platform,_account_allowed,_ensure_source,_create_conversation,_resolved_source_type,SOCIAL_ACQUISITION_CODES,_trusted_contact_identities,_identity_matches,_ensure_contact_identities

def ok(**x):return ({'ok':True,**x},200)
def err(c,m,s=400,**x):return ({'ok':False,'code':c,'message':m,**x},s)
def _contact(c,a,cid):return c.execute("SELECT * FROM contacts ct WHERE ct.contact_id=? AND ct.organization_id=? AND ct.workspace_id=? AND ct.deleted_at IS NULL AND (ct.team_id=? OR EXISTS(SELECT 1 FROM contact_team_access x WHERE x.contact_id=ct.contact_id AND x.team_id=? AND x.revoked_at IS NULL))",(cid,a['organization_id'],a['workspace_id'],a['team_id'],a['team_id'])).fetchone()
def _audit(c,a,op,cid,before,after,reason):c.execute("INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at,organization_id,team_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(a['workspace_id'],a['user_id'],a.get('device_id'),op,'contact',cid,dumps(before),dumps(after),reason,now_ms(),a['organization_id'],a['team_id']))
def chat_context(db,a,cid):
 with db.tx(False) as c:
  row=_contact(c,a,cid)
  if not row:return err('CONTACT_SCOPE_INVALID','客户不存在或不属于当前作用域',404)
  fields=[dict(x) for x in c.execute("SELECT * FROM custom_field_definitions WHERE workspace_id=? AND enabled=1 AND (is_quick_edit=1 OR field_role LIKE 'stage_%') ORDER BY sort_order,field_key",(a['workspace_id'],))]
  vals={x['field_key']:json.loads(x['value_json']) for x in c.execute('SELECT field_key,value_json FROM contact_custom_values WHERE contact_id=?',(cid,))}
  tags=[dict(x) for x in c.execute("SELECT t.*,(ct.contact_id IS NOT NULL) selected FROM tags t LEFT JOIN contact_tags ct ON ct.tag_id=t.tag_id AND ct.contact_id=? WHERE t.workspace_id=? AND t.enabled=1 ORDER BY t.tag_kind,t.sort_order,t.name",(cid,a['workspace_id']))]
  conv=[dict(x) for x in c.execute("SELECT conversation_id,channel_account_id,platform_id,status,last_message_at FROM conversations WHERE contact_id=? AND team_id=? ORDER BY last_message_at DESC",(cid,a['team_id']))]
  contact={k:row[k] for k in ('contact_id','display_name','manual_name','observed_phone','manual_phone','avatar_url','remark','status','version','next_follow_up_at')}
  try: contact['next_follow_up_reason']=str((json.loads(row['business_json'] or '{}') or {}).get('nextFollowUpReason') or '')[:500]
  except Exception: contact['next_follow_up_reason']=''
  return ok(contact=contact,fields=fields,values=vals,tags=tags,conversations=conv)

def contact_version(db,a,cid):
 """轻量读取联系人版本，供已授权插件检测管理端变更。"""
 with db.tx(False) as c:
  row=_contact(c,a,cid)
  if not row:return err('CONTACT_SCOPE_INVALID','客户不存在或不属于当前作用域',404)
  return ok(contactId=cid,version=int(row['version'] or 0),updatedAt=row['updated_at'])

def update_contact(db,a,cid,p):
 try:base=int(p.get('baseVersion',p.get('base_version')))
 except Exception:return err('BASE_VERSION_REQUIRED','baseVersion 必填')
 allowed={'manualName':'manual_name','manualPhone':'manual_phone','remark':'remark'};changes={}
 for key,col in allowed.items():
  if key in p:changes[col]=str(p.get(key) or '').strip()
 if not changes:return err('CONTACT_FIELDS_REQUIRED','至少提交一个可更新字段')
 if len(changes.get('manual_name',''))>200 or len(changes.get('manual_phone',''))>80 or len(changes.get('remark',''))>4000:return err('CONTACT_FIELD_TOO_LONG','客户资料超过长度限制')
 with db.tx() as c:
  row=_contact(c,a,cid)
  if not row:return err('CONTACT_SCOPE_INVALID','客户不存在或不属于当前作用域',404)
  if base!=row['version']:return err('VERSION_CONFLICT','客户版本冲突',409,currentVersion=row['version'])
  before={x:row[x] for x in changes};n=now_ms();ver=base+1
  sets=','.join(x+'=?' for x in changes)+',version=?,updated_at=?'
  c.execute('UPDATE contacts SET '+sets+' WHERE contact_id=?',tuple(changes.values())+(ver,n,cid))
  _audit(c,a,'interaction-contact',cid,before,changes,'聊天面板客户资料更新')
  return ok(version=ver,contactId=cid,updated=changes)

def update_next_follow_up(db,a,cid,p):
 try:base=int(p.get('baseVersion',p.get('base_version')))
 except Exception:return err('BASE_VERSION_REQUIRED','baseVersion 必填')
 value=p.get('nextFollowUpAt',p.get('next_follow_up_at'))
 if value is not None:
  if isinstance(value,bool) or not isinstance(value,(int,float)) or int(value)!=value:return err('INVALID_NEXT_FOLLOW_UP','下次跟进时间必须是毫秒时间戳或 null')
  value=int(value)
  if value<946684800000 or value>4102444800000:return err('NEXT_FOLLOW_UP_OUT_OF_RANGE','下次跟进时间超出允许范围（2000—2100）')
 reason=p.get('nextFollowUpReason',p.get('next_follow_up_reason'))
 if reason is not None and not isinstance(reason,str):return err('INVALID_NEXT_FOLLOW_UP_REASON','跟进事由必须是文本')
 reason=(reason or '').strip() if reason is not None else None
 if reason is not None and len(reason)>500:return err('INVALID_NEXT_FOLLOW_UP_REASON','跟进事由最多 500 字')
 with db.tx() as c:
  row=_contact(c,a,cid)
  if not row:return err('CONTACT_SCOPE_INVALID','客户不存在或不属于当前作用域',404)
  if base!=row['version']:return err('VERSION_CONFLICT','客户版本冲突',409,currentVersion=row['version'])
  before=row['next_follow_up_at'];business={}
  try:
   business=json.loads(row['business_json'] or '{}') if row['business_json'] else {}
   if not isinstance(business,dict):business={}
  except Exception:business={}
  before_reason=str(business.get('nextFollowUpReason') or '')
  if reason is not None:
   if reason:business['nextFollowUpReason']=reason
   else:business.pop('nextFollowUpReason',None)
  final_reason=str(business.get('nextFollowUpReason') or '')[:500]
  n=now_ms();ver=base+1
  c.execute('UPDATE contacts SET next_follow_up_at=?,business_json=?,version=?,updated_at=? WHERE contact_id=?',(value,json.dumps(business,ensure_ascii=False,separators=(',',':')),ver,n,cid))
  updated=dict(c.execute('SELECT * FROM contacts WHERE contact_id=?',(cid,)).fetchone());sync_follow_up_plan_in_tx(c,updated,value,final_reason,a['user_id'],n)
  _audit(c,a,'interaction-next-follow-up',cid,{'nextFollowUpAt':before,'nextFollowUpReason':before_reason},{'nextFollowUpAt':value,'nextFollowUpReason':final_reason},'聊天面板下次跟进时间与事由更新')
  return ok(version=ver,contactId=cid,nextFollowUpAt=value,nextFollowUpReason=final_reason)

def update_fields(db,a,cid,p):
 values=p.get('fields')
 if not isinstance(values,dict) or not values:return err('INVALID_FIELDS','fields 必须是非空对象')
 try:base=int(p.get('baseVersion',p.get('base_version')))
 except Exception:return err('BASE_VERSION_REQUIRED','baseVersion 必填')
 with db.tx() as c:
  row=_contact(c,a,cid)
  if not row:return err('CONTACT_SCOPE_INVALID','客户不存在或不属于当前作用域',404)
  if base!=row['version']:return err('VERSION_CONFLICT','客户版本冲突',409,currentVersion=row['version'])
  before={};n=now_ms()
  for key,value in values.items():
   fd=c.execute("SELECT * FROM custom_field_definitions WHERE workspace_id=? AND field_key=? AND enabled=1",(a['workspace_id'],str(key))).fetchone()
   if not fd:return err('FIELD_NOT_DEFINED','字段未定义或已停用',400,fieldKey=key)
   typ=fd['field_type'];options=json.loads(fd['options_json'] or '[]');valid=True
   if typ in ('text','date'):valid=isinstance(value,str)
   elif typ=='number':valid=isinstance(value,(int,float)) and not isinstance(value,bool)
   elif typ=='boolean':valid=isinstance(value,bool)
   elif typ=='single_select':valid=value is None or (isinstance(value,str) and value in options)
   elif typ=='multi_select':valid=isinstance(value,list) and len(value)==len(set(map(str,value))) and all(isinstance(x,str) and x in options for x in value)
   if not valid:return err('FIELD_TYPE_MISMATCH','字段值与定义不匹配',400,fieldKey=key,expectedType=typ)
   old=c.execute('SELECT value_json FROM contact_custom_values WHERE contact_id=? AND field_key=?',(cid,key)).fetchone();before[key]=json.loads(old[0]) if old else None
   c.execute("INSERT INTO contact_custom_values(contact_id,field_key,value_json,updated_at,updated_by) VALUES(?,?,?,?,?) ON CONFLICT(contact_id,field_key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by",(cid,key,dumps(value),n,a['user_id']))
  ver=base+1;c.execute('UPDATE contacts SET version=?,updated_at=? WHERE contact_id=?',(ver,n,cid));_audit(c,a,'interaction-fields',cid,before,values,'聊天面板快捷字段更新')
  return ok(version=ver,fields=values)
def update_tags(db,a,cid,p):
 ids=p.get('tagIds',p.get('tag_ids'))
 if not isinstance(ids,list):return err('INVALID_TAGS','tagIds 必须是数组')
 try:base=int(p.get('baseVersion',p.get('base_version')))
 except Exception:return err('BASE_VERSION_REQUIRED','baseVersion 必填')
 clean=[]
 with db.tx() as c:
  row=_contact(c,a,cid)
  if not row:return err('CONTACT_SCOPE_INVALID','客户不存在或不属于当前作用域',404)
  if base!=row['version']:return err('VERSION_CONFLICT','客户版本冲突',409,currentVersion=row['version'])
  status_count=0
  for tid0 in ids:
   tid=str(tid0)
   if tid in clean:continue
   tag=c.execute('SELECT tag_kind FROM tags WHERE workspace_id=? AND tag_id=? AND enabled=1',(a['workspace_id'],tid)).fetchone()
   if not tag:return err('TAG_NOT_FOUND','标签不存在或已停用',404,tagId=tid)
   status_count+=tag['tag_kind']=='status';clean.append(tid)
  if status_count>1:return err('MULTIPLE_STATUS_TAGS','状态标签最多选择一个',409)
  old=[x[0] for x in c.execute('SELECT tag_id FROM contact_tags WHERE contact_id=?',(cid,))];n=now_ms()
  c.execute('DELETE FROM contact_tags WHERE contact_id=?',(cid,))
  for tid in clean:c.execute('INSERT INTO contact_tags(contact_id,tag_id,created_at) VALUES(?,?,?)',(cid,tid,n))
  ver=base+1;c.execute('UPDATE contacts SET version=?,updated_at=? WHERE contact_id=?',(ver,n,cid));_audit(c,a,'interaction-tags',cid,{'tagIds':old},{'tagIds':clean},'聊天面板标签更新')
  return ok(version=ver,tagIds=clean)


class _RegisterAbort(Exception):
 def __init__(self,result):super().__init__(result[0].get('code','REGISTER_FAILED'));self.result=result

def _abort(code,message,status=400,**extra):raise _RegisterAbort(err(code,message,status,**extra))
def _canonical_request(payload):
 clean={k:v for k,v in payload.items() if k not in ('idempotencyKey','idempotency_key')}
 return hashlib.sha256(json.dumps(clean,ensure_ascii=False,separators=(',',':'),sort_keys=True).encode('utf-8')).hexdigest()
def _valid_field_value(fd,value):
 typ=fd['field_type']
 try:options=json.loads(fd['options_json'] or '[]')
 except Exception:options=[]
 if typ in ('text','date'):valid=isinstance(value,str)
 elif typ=='number':valid=isinstance(value,(int,float)) and not isinstance(value,bool)
 elif typ=='boolean':valid=isinstance(value,bool)
 elif typ=='single_select':valid=value is None or (isinstance(value,str) and value in options)
 elif typ=='multi_select':valid=isinstance(value,list) and len(value)==len(set(map(str,value))) and all(isinstance(x,str) and x in options for x in value)
 else:valid=False
 return valid,typ

def _registration_context(c,a,cid,conversation,created,replayed=False):
 row=_contact(c,a,cid)
 fields=[dict(x) for x in c.execute("SELECT * FROM custom_field_definitions WHERE workspace_id=? AND enabled=1 AND (is_quick_edit=1 OR field_role LIKE 'stage_%') ORDER BY sort_order,field_key",(a['workspace_id'],))]
 values={x['field_key']:json.loads(x['value_json']) for x in c.execute('SELECT field_key,value_json FROM contact_custom_values WHERE contact_id=?',(cid,))}
 tags=[dict(x) for x in c.execute("SELECT t.*,(ct.contact_id IS NOT NULL) selected FROM tags t LEFT JOIN contact_tags ct ON ct.tag_id=t.tag_id AND ct.contact_id=? WHERE t.workspace_id=? AND t.enabled=1 ORDER BY t.tag_kind,t.sort_order,t.name",(cid,a['workspace_id']))]
 contact={k:row[k] for k in ('contact_id','display_name','manual_name','observed_phone','manual_phone','avatar_url','remark','status','version','owner_user_id','last_touch_at','last_seen_at')}
 return {'ok':True,'entryState':'registered','contactCreated':bool(created),'contactId':cid,'contact':contact,'conversation':dict(conversation),'fields':fields,'values':values,'tags':tags,'replayed':bool(replayed)}

def register_contact(db,a,p,_connection=None,_operation=None):
 """Atomically register/reuse a contact from an unregistered plugin conversation."""
 if not isinstance(p,dict):return err('INVALID_REQUEST','请求正文必须是对象')
 key=str(p.get('idempotencyKey') or p.get('idempotency_key') or '').strip()
 if not key or len(key)>200:return err('IDEMPOTENCY_KEY_REQUIRED','idempotencyKey 必填且不得超过 200 字符')
 aid=str(p.get('channelAccountId') or '').strip();ext=str(p.get('externalConversationId') or '').strip()
 if not aid or not ext:return err('CONVERSATION_REQUIRED','channelAccountId、externalConversationId 必填')
 if len(ext)>500:return err('EXTERNAL_CONVERSATION_ID_TOO_LONG','externalConversationId 超过长度限制')
 account_identity=p.get('accountIdentity') or {};identity=p.get('contactIdentity') or {};identity_aliases=p.get('contactIdentityAliases') or [];profile=p.get('profile') or {}
 fields=p.get('fields') or {};stages=p.get('stages') or {};tag_ids=p.get('tagIds',p.get('tag_ids',[]))
 if not isinstance(account_identity,dict) or not isinstance(identity,dict):return err('INVALID_IDENTITY','accountIdentity、contactIdentity 必须是对象')
 if not isinstance(profile,dict) or not isinstance(fields,dict) or not isinstance(stages,dict) or not isinstance(tag_ids,list):return err('INVALID_REGISTRATION_DATA','profile、fields、stages 或 tagIds 类型无效')
 overlap=set(fields)&set(stages)
 if overlap:return err('DUPLICATE_FIELD_INPUT','fields 与 stages 不得重复提交同一字段',fieldKeys=sorted(overlap))
 merged={**fields,**stages};request_hash=_canonical_request(p);operation=_operation or 'interaction.contact.register';n=now_ms()
 try:
  with (nullcontext(_connection) if _connection is not None else db.tx()) as c:
   idem=c.execute("SELECT * FROM interaction_idempotency WHERE organization_id=? AND workspace_id=? AND team_id=? AND user_id=? AND operation=? AND idempotency_key=?",(a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'],operation,key)).fetchone()
   if idem:
    if idem['request_hash']!=request_hash:_abort('IDEMPOTENCY_CONFLICT','idempotencyKey 已被不同请求使用',409)
    try:payload=json.loads(idem['response_json'])
    except Exception:_abort('IDEMPOTENCY_RESULT_INVALID','幂等结果损坏',500)
    payload['replayed']=True;return (payload,200)
   platform=_platform(c,p)
   if not platform:_abort('PLATFORM_NOT_FOUND','平台不存在或未启用',404)
   pid=platform['platform_id'];code=platform['platform_code']
   account_typ,account_raw,account_key=normalize_identity(code,account_identity.get('identityType'),account_identity.get('identityValue'))
   if not account_key:_abort('STABLE_ACCOUNT_IDENTITY_REQUIRED','当前平台登录账号稳定身份缺失',409)
   binding=c.execute("SELECT * FROM device_channel_account_bindings WHERE device_id=? AND user_id=? AND channel_account_id=? AND platform_id=? AND external_account_key=? AND status='active'",(a['device_id'],a['user_id'],aid,pid,account_key)).fetchone()
   if not binding:_abort('ACCOUNT_BINDING_REQUIRED','当前插件实例尚未验证该平台账号',403)
   account=_account_allowed(c,a,aid,pid)
   if not account:_abort('ACCOUNT_NOT_AUTHORIZED','渠道账号授权已失效',403)
   account_ident=c.execute("SELECT 1 FROM channel_account_identities WHERE channel_account_id=? AND platform_id=? AND identity_type=? AND canonical_value=? AND status='active' AND (valid_from IS NULL OR valid_from<=?) AND (valid_to IS NULL OR valid_to>=?)",(aid,pid,account_typ,account_key,n,n)).fetchone()
   if not account_ident:_abort('ACCOUNT_IDENTITY_CHANGED','平台账号身份验证已失效，请重新检测',403)
   if account['contact_entry_policy']=='disabled' or not account['collection_enabled']:_abort('COLLECTION_DISABLED','内部账号或禁用策略禁止建档',409)
   social=account['business_scene']=='social_acquisition'
   source_type=None;selection_method=None
   source_selection=p.get('sourceSelection') or {}
   if not isinstance(source_selection,dict):_abort('SOURCE_SELECTION_INVALID','来源选择格式无效')
   selected_source_id=str(source_selection.get('sourceTypeId') or '').strip()
   if social:
    if account['contact_entry_policy']!='manual_on_record' or ('business_purpose' in account.keys() and account['business_purpose']!='acquisition'):
     _abort('SOCIAL_ACCOUNT_POLICY_INVALID','社交获客账号策略无效',409)
    market_id=account['default_market_id'] if 'default_market_id' in account.keys() else None
    market=c.execute("SELECT 1 FROM markets WHERE market_id=? AND organization_id=? AND status='active'",(market_id,a['organization_id'])).fetchone() if market_id else None
    if not market:_abort('SOCIAL_MARKET_REQUIRED','社交获客账号缺少有效默认市场',409)
    if selected_source_id:
     source_type=_resolved_source_type(c,account,selected_source_id);selection_method='manual_selection'
     if not source_type or source_type['source_type_code'] not in SOCIAL_ACQUISITION_CODES:_abort('SOCIAL_SOURCE_TYPE_INVALID','来源类型不属于社交获客选项',400)
    else:
     source_type=_resolved_source_type(c,account)
     selection_method='fallback_pending' if source_type and source_type['source_type_code']=='social_pending' else 'account_suggestion'
    if not source_type:_abort('SOCIAL_SOURCE_TYPE_MISSING','社交来源类型尚未初始化',409)
   elif selected_source_id:_abort('SOURCE_SELECTION_UNSUPPORTED','非社交获客账号不能选择社交获客来源类型',400)
   identity_items=_trusted_contact_identities(code,identity,identity_aliases)
   if not identity_items:_abort('STABLE_CONTACT_IDENTITY_REQUIRED','联系人稳定平台身份缺失',409)
   typ,raw,canonical=identity_items[0]['identityType'],identity_items[0]['identityValue'],identity_items[0]['canonicalValue']
   identity_rows=_identity_matches(c,a,pid,identity_items);identity_contact_ids={r['contact_id'] for r in identity_rows}
   if len(identity_contact_ids)>1:_abort('WHATSAPP_IDENTITY_SPLIT_CONFLICT','提交的可信身份分别属于多个联系人，事务已回滚',409,contactIds=sorted(identity_contact_ids))
   manual_name=str(profile.get('manualName') or '').strip();manual_phone=str(profile.get('manualPhone') or '').strip();remark=str(profile.get('remark') or '').strip()
   if len(manual_name)>200 or len(manual_phone)>80 or len(remark)>4000:_abort('CONTACT_FIELD_TOO_LONG','客户资料超过长度限制')
   observed_name=sanitize_observed_name(identity.get('displayName'));observed_phone=str(identity.get('phone') or '')[:80];avatar=sanitize_avatar(identity.get('avatarUrl'))
   clean_tags=[];status_count=0
   for raw_tid in tag_ids:
    tid=str(raw_tid)
    if tid in clean_tags:continue
    tag=c.execute('SELECT tag_kind FROM tags WHERE workspace_id=? AND tag_id=? AND enabled=1',(a['workspace_id'],tid)).fetchone()
    if not tag:_abort('TAG_NOT_FOUND','标签不存在或已停用',404,tagId=tid)
    status_count+=tag['tag_kind']=='status';clean_tags.append(tid)
   if status_count>1:_abort('MULTIPLE_STATUS_TAGS','状态标签最多选择一个',409)
   validated={}
   for raw_key,value in merged.items():
    field_key=str(raw_key);fd=c.execute("SELECT * FROM custom_field_definitions WHERE workspace_id=? AND field_key=? AND enabled=1",(a['workspace_id'],field_key)).fetchone()
    if not fd:_abort('FIELD_NOT_DEFINED','字段未定义或已停用',400,fieldKey=field_key)
    if raw_key in stages and not str(fd['field_role']).startswith('stage_'):_abort('FIELD_NOT_STAGE','stages 只能提交阶段字段',400,fieldKey=field_key)
    valid,typ_expected=_valid_field_value(fd,value)
    if not valid:_abort('FIELD_TYPE_MISMATCH','字段值与定义不匹配',400,fieldKey=field_key,expectedType=typ_expected)
    validated[field_key]=value
   old_conv=c.execute('SELECT * FROM conversations WHERE organization_id=? AND channel_account_id=? AND external_conversation_id=?',(a['organization_id'],aid,ext)).fetchone()
   identity_row=identity_rows[0] if identity_rows else None
   contact=None;iid=None;created=False
   if identity_row:
    iid=identity_row['contact_identity_id'];contact=_contact(c,a,identity_row['contact_id'])
    if not contact:_abort('IDENTITY_SCOPE_CONFLICT','平台身份属于其他工作区、团队或已删除客户',409)
   if old_conv:
    if contact and old_conv['contact_id']!=contact['contact_id']:_abort('CONVERSATION_CONTACT_CONFLICT','会话已经绑定其他客户',409)
    if not contact:
     contact=_contact(c,a,old_conv['contact_id']);iid=old_conv['contact_identity_id']
     if not contact:_abort('CONVERSATION_SCOPE_CONFLICT','会话不属于当前作用域',409)
   if not contact and account['contact_entry_policy']=='existing_contact_first':_abort('TRANSFER_MATCH_REQUIRED','转化成交场景必须先匹配已有联系人或待确认转移',409)
   current_source_id=_ensure_source(c,a,account,platform,n,source_type,selection_method) if social else None
   source_id=None
   if not contact:
    source_id=current_source_id or _ensure_source(c,a,account,platform,n);cid='ct_'+uuid.uuid4().hex;iid='ci_'+uuid.uuid4().hex;created=True
    display=observed_name or manual_name
    c.execute("""INSERT INTO contacts(contact_id,workspace_id,source_id,channel,external_contact_id,display_name,observed_phone,avatar_url,observed_json,observation_hash,manual_name,manual_phone,remark,status,business_json,last_observed_device_id,last_observed_at,version,created_at,updated_at,last_seen_at,organization_id,team_id,owner_user_id,last_touch_at)
     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'active','{}',?,?,1,?,?,?,?,?,?,?)""",(cid,a['workspace_id'],source_id,code,canonical,display,observed_phone,avatar,dumps(identity),hashlib.sha256(dumps(identity).encode()).hexdigest(),manual_name,manual_phone,remark,a['device_id'],n,n,n,n,a['organization_id'],a['team_id'],a['user_id'],n))
    rows=_ensure_contact_identities(c,a,pid,cid,identity_items,n);primary=next((r for r in rows if r['identity_type']==typ and r['canonical_value']==canonical),rows[0]);iid=primary['contact_identity_id']
    contact=_contact(c,a,cid)
   else:
    cid=contact['contact_id'];source_id=contact['source_id']
    rows=_ensure_contact_identities(c,a,pid,cid,identity_items,n)
    primary=next((r for r in rows if r['identity_type']==typ and r['canonical_value']==canonical),rows[0]);iid=primary['contact_identity_id']
    c.execute("UPDATE contacts SET manual_name=CASE WHEN ?<>'' THEN ? ELSE manual_name END,manual_phone=CASE WHEN ?<>'' THEN ? ELSE manual_phone END,remark=CASE WHEN ?<>'' THEN ? ELSE remark END,display_name=CASE WHEN ?<>'' THEN ? ELSE display_name END,observed_phone=CASE WHEN ?<>'' THEN ? ELSE observed_phone END,avatar_url=CASE WHEN ?<>'' THEN ? ELSE avatar_url END,last_observed_device_id=?,last_observed_at=?,last_seen_at=?,last_touch_at=?,updated_at=?,version=version+1 WHERE contact_id=?",(manual_name,manual_name,manual_phone,manual_phone,remark,remark,observed_name,observed_name,observed_phone,observed_phone,avatar,avatar,a['device_id'],n,n,n,n,cid))
   rows=_ensure_contact_identities(c,a,pid,cid,identity_items,n)
   primary=next((r for r in rows if r['identity_type']==typ and r['canonical_value']==canonical),rows[0]);iid=primary['contact_identity_id']
   conv,conv_created=_create_conversation(c,a,account,platform,cid,iid,ext,n)
   if conv['contact_id']!=cid:_abort('CONVERSATION_CONTACT_CONFLICT','会话已经绑定其他客户',409)
   for tid in clean_tags:c.execute('INSERT OR IGNORE INTO contact_tags(contact_id,tag_id,created_at) VALUES(?,?,?)',(cid,tid,n))
   for field_key,value in validated.items():c.execute("INSERT INTO contact_custom_values(contact_id,field_key,value_json,updated_at,updated_by) VALUES(?,?,?,?,?) ON CONFLICT(contact_id,field_key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by",(cid,field_key,dumps(value),n,a['user_id']))
   if created:
    touch='tp_'+uuid.uuid4().hex;attrib='atr_'+uuid.uuid4().hex
    event_key='contact-registration:'+hashlib.sha256('|'.join((a['organization_id'],a['workspace_id'],aid,ext,cid)).encode()).hexdigest()
    c.execute("INSERT INTO source_touchpoints(touchpoint_id,organization_id,workspace_id,source_id,contact_id,platform_id,channel_account_id,touchpoint_type,direction,initiated_by,session_id,occurred_at,metadata_json,created_at,channel_type_id,event_key) VALUES(?,?,?,?,?,?,?,'contact_registration','inbound','customer',?,?,?,?,?,?)",(touch,a['organization_id'],a['workspace_id'],source_id,cid,pid,aid,ext,n,dumps({'createdBy':'interaction.register'}),n,account['channel_type_id'],event_key))
    c.execute("INSERT INTO contact_attributions(attribution_id,organization_id,workspace_id,contact_id,source_id,touchpoint_id,attribution_type,attribution_weight,confidence,is_primary,attributed_at,metadata_json) VALUES(?,?,?,?,?,?,'first_touch',1.0,'observed',1,?,?)",(attrib,a['organization_id'],a['workspace_id'],cid,source_id,touch,n,dumps({'createdBy':'interaction.register'})))
   if social:
    confidence=0.2 if source_type['source_type_code']=='social_pending' else (0.8 if selection_method=='account_suggestion' else 1.0)
    log_status='pending' if source_type['source_type_code']=='social_pending' else 'resolved'
    digest=hashlib.sha256(json.dumps({'account':aid,'conversation':ext,'sourceType':source_type['source_type_id']},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
    c.execute("""INSERT INTO source_resolution_logs(resolution_log_id,organization_id,workspace_id,channel_account_id,market_id,source_type_id,source_id,input_digest,resolver_version,resolution_method,confidence,status,input_summary_json,created_at)
     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",('srl_'+uuid.uuid4().hex,a['organization_id'],a['workspace_id'],aid,account['default_market_id'],source_type['source_type_id'],current_source_id,digest,'v219.2',selection_method,confidence,log_status,dumps({'contactId':cid,'conversationId':conv['conversation_id'],'sourceTypeCode':source_type['source_type_code'],'selectionOrigin':selection_method,'firstSourcePreserved':not created}),n))
   c.execute('UPDATE device_channel_account_bindings SET last_verified_at=? WHERE binding_id=?',(n,binding['binding_id']))
   _audit(c,a,'interaction-contact-register',cid,{}, {'created':created,'channelAccountId':aid,'conversationId':conv['conversation_id'],'fields':validated,'tagIds':clean_tags},'插件未建档会话原子建档')
   payload=_registration_context(c,a,cid,conv,created,False)
   c.execute("INSERT INTO interaction_idempotency(idempotency_id,organization_id,workspace_id,team_id,user_id,operation,idempotency_key,request_hash,entity_type,entity_id,response_json,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",('idem_'+uuid.uuid4().hex,a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'],operation,key,request_hash,'contact',cid,dumps(payload),n,n+30*24*3600*1000))
   return (payload,201 if created else 200)
 except _RegisterAbort as ex:return ex.result
 except ValueError as ex:
  if str(ex)=='WHATSAPP_IDENTITY_SPLIT_CONFLICT':return err('WHATSAPP_IDENTITY_SPLIT_CONFLICT','可信 WhatsApp 身份存在分叉，事务已回滚',409)
  raise
 except sqlite3.IntegrityError as ex:
  text=str(ex)
  if 'interaction_idempotency' in text:return err('IDEMPOTENCY_CONFLICT','并发请求发生幂等冲突，请重试',409)
  if 'contact_identities' in text:return err('IDENTITY_CONFLICT','联系人稳定身份发生并发冲突，请重试',409)
  if 'conversations' in text:return err('CONVERSATION_CONFLICT','外部会话发生并发冲突，请重试',409)
  return err('REGISTER_CONSTRAINT_FAILED','建档违反数据库约束',409,detail=text)
 except sqlite3.OperationalError as ex:
  logging.exception('interaction contact register schema/database operation failed')
  return err('REGISTER_SCHEMA_ERROR','建档所需数据库结构不完整或暂时不可用，请执行数据库修复后重试',503)
 except sqlite3.DatabaseError as ex:
  logging.exception('interaction contact register database failed')
  return err('REGISTER_DATABASE_ERROR','客户建档数据库操作失败，请稍后重试',500)
 except Exception as ex:
  logging.exception('interaction contact register unexpected failure')
  return err('REGISTER_INTERNAL_ERROR','客户建档失败，请查看服务端日志',500)
