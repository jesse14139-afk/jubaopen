# -*- coding: utf-8 -*-
"""V208 Collector 服务：插件会话、账号绑定、首次客户解析与幂等消息采集。"""
import hashlib,json,re,secrets,uuid
from V207_shared_db import now_ms,dumps
from V208_privacy import redact_text
from V208_identity import collector_canonical,normalize_identity
from V208_name_sanitize import sanitize_observed_name
from V208_account_claim_service import record_discovery_in_tx,discover_or_auto_claim_in_tx

def _ok(**kw):return ({'ok':True,**kw},200)
def _err(code,message,status=400,**kw):return ({'ok':False,'code':code,'message':message,**kw},status)
def _hash(v):return hashlib.sha256(v.encode()).hexdigest()
def _platform(c,p):
 value=str(p.get('platformId') or p.get('platformCode') or '').strip().lower()
 if not value:return None
 return c.execute("SELECT * FROM platforms WHERE status='active' AND (lower(platform_id)=? OR lower(platform_code)=?)",(value,value)).fetchone()
def _canonical(code,typ,value):
 return collector_canonical(code,typ,value)

def _normalize_code(value):return re.sub(r'[^A-Z0-9]','',str(value or '').upper())
def _account_allowed(c,a,aid,pid):
 return c.execute("""SELECT ca.* FROM channel_accounts ca
  JOIN team_channel_accounts ta ON ta.channel_account_id=ca.channel_account_id AND ta.team_id=?
  WHERE ca.channel_account_id=? AND ca.organization_id=? AND ca.platform_id=?
  AND ca.status='active' AND ca.collection_enabled=1
  AND (EXISTS(SELECT 1 FROM user_channel_account_grants g WHERE g.user_id=? AND g.channel_account_id=ca.channel_account_id)
       OR EXISTS(SELECT 1 FROM platform_administrators pa WHERE pa.user_id=?))""",
  (a['team_id'],aid,a['organization_id'],pid,a['user_id'],a['user_id'])).fetchone()

def enroll_plugin(db,p,client_ip='',user_agent='',ttl_ms=30*24*3600*1000):
 """匿名核销一次性邀请码；在单事务内登记插件实例并签发受限会话。"""
 code=_normalize_code(p.get('invitationCode') or p.get('bindingCode') or p.get('binding_code'));iid=str(p.get('installationId') or p.get('installation_id') or '').strip()
 if len(code)<16 or len(iid)<16 or len(iid)>160:return _err('ENROLLMENT_INVALID','接入码或安装实例无效',400)
 digest=_hash(code);n=now_ms()
 with db.tx() as c:
  e=c.execute('SELECT * FROM device_enrollments WHERE binding_code_hash=?',(digest,)).fetchone()
  # 对外统一失败，避免泄漏邀请码的存在、状态和归属。
  if not e or e['status']!='pending':return _err('ENROLLMENT_INVALID','接入码无效、已使用或已撤销',409)
  if e['expires_at']<=n:
   c.execute("UPDATE device_enrollments SET status='expired' WHERE enrollment_id=? AND status='pending'",(e['enrollment_id'],))
   return _err('ENROLLMENT_INVALID','接入码无效、已使用或已撤销',409)
  uid=e['assigned_user_id']
  if not uid:return _err('ENROLLMENT_INVALID','接入邀请未指定用户',409)
  u=c.execute("""SELECT u.user_id,u.display_name,u.organization_id FROM users u
   JOIN team_memberships tm ON tm.user_id=u.user_id AND tm.team_id=? AND tm.status='active'
   WHERE u.user_id=? AND u.organization_id=? AND u.status='active'""",(e['team_id'],uid,e['organization_id'])).fetchone()
  t=c.execute("SELECT * FROM teams WHERE team_id=? AND organization_id=? AND status='active'",(e['team_id'],e['organization_id'])).fetchone()
  w=c.execute("SELECT * FROM workspaces WHERE workspace_id=? AND organization_id=? AND status='active'",(e['workspace_id'],e['organization_id'])).fetchone()
  relation=c.execute("SELECT 1 FROM workspace_teams WHERE workspace_id=? AND team_id=? AND organization_id=? AND status='active'",(e['workspace_id'],e['team_id'],e['organization_id'])).fetchone()
  if not u or not t or not w or (t['workspace_id']!=e['workspace_id'] and not relation):return _err('ENROLLMENT_SCOPE_INVALID','邀请归属已失效，请管理员重新创建',409)
  if c.execute('SELECT 1 FROM devices WHERE installation_id=?',(iid,)).fetchone():return _err('INSTALLATION_CONFLICT','该插件安装实例已登记；请先退出或联系管理员处理',409)
  did='dev_'+uuid.uuid4().hex;sid='pls_'+uuid.uuid4().hex;token='jbp_'+secrets.token_urlsafe(40);exp=n+min(max(int(ttl_ms),3600000),90*24*3600*1000)
  alias=str(p.get('deviceAlias') or '')[:120];computer=str(p.get('computerAlias') or '')[:120];client=str(p.get('clientVersion') or '')[:40]
  system_name=str(p.get('browser') or user_agent or 'Browser')[:120]
  metadata=dumps({'browser':str(p.get('browser') or '')[:80],'userAgent':str(user_agent)[:300],'clientIp':str(client_ip)[:80],'enrollmentId':e['enrollment_id']})
  c.execute("""INSERT INTO devices(device_id,workspace_id,installation_id,device_name,computer_name,status,first_seen_at,last_seen_at,metadata_json,organization_id,team_id,assigned_user_id,system_device_name,system_computer_name,user_device_alias,user_computer_alias,admin_device_name,admin_computer_name)
   VALUES(?,?,?,?,?,'active',?,?,?,?,?,?,?,?,?,?,?,?)""",(did,e['workspace_id'],iid,alias or system_name,computer,n,n,metadata,e['organization_id'],e['team_id'],uid,system_name,computer,alias,computer,e['admin_device_name'] or '',e['admin_computer_name'] or ''))
  c.execute('INSERT INTO device_assignments(assignment_id,device_id,assigned_user_id,team_id,assigned_at,released_at) VALUES(?,?,?,?,?,NULL)',('asn_'+secrets.token_hex(12),did,uid,e['team_id'],n))
  changed=c.execute("UPDATE device_enrollments SET status='consumed',consumed_at=?,consumed_device_id=? WHERE enrollment_id=? AND status='pending' AND expires_at>?",(n,did,e['enrollment_id'],n)).rowcount
  if changed!=1:raise RuntimeError('ENROLLMENT_RACE')
  c.execute("INSERT INTO plugin_sessions(plugin_session_id,organization_id,workspace_id,team_id,user_id,device_id,token_hash,status,issued_at,expires_at,last_seen_at,client_version,metadata_json) VALUES(?,?,?,?,?,?,?,'active',?,?,?,?,?)",(sid,e['organization_id'],e['workspace_id'],e['team_id'],uid,did,_hash(token),n,exp,n,client,dumps({'enrollmentId':e['enrollment_id']})))
  c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at,organization_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(e['workspace_id'],uid,did,'enroll','plugin_session',sid,'{}',dumps({'deviceId':did,'installationId':iid,'teamId':e['team_id']}),'一次性接入邀请核销',n,e['organization_id']))
  return _ok(pluginToken=token,pluginSessionId=sid,deviceId=did,expiresAt=exp,user={'userId':uid,'displayName':u['display_name']},workspace={'workspaceId':w['workspace_id'],'name':w['name']},team={'teamId':t['team_id'],'name':t['name']})

def plugin_context(db,a):
 with db.tx(False) as c:
  u=c.execute('SELECT user_id,display_name,login_name FROM users WHERE user_id=?',(a['user_id'],)).fetchone();d=c.execute('SELECT device_id,installation_id,user_device_alias,system_device_name,last_seen_at,status FROM devices WHERE device_id=?',(a['device_id'],)).fetchone();w=c.execute('SELECT workspace_id,name FROM workspaces WHERE workspace_id=?',(a['workspace_id'],)).fetchone();t=c.execute('SELECT team_id,name FROM teams WHERE team_id=?',(a['team_id'],)).fetchone()
  return _ok(user=dict(u),device=dict(d),workspace=dict(w),team=dict(t),pluginSessionId=a['plugin_session_id'],expiresAt=a['expires_at'])

def logout_plugin(db,a):
 n=now_ms()
 with db.tx() as c:c.execute("UPDATE plugin_sessions SET status='revoked',revoked_at=?,revoked_by=?,revoked_reason='self_logout' WHERE plugin_session_id=? AND status='active'",(n,a['user_id'],a['plugin_session_id']))
 return _ok()

def _record_identity_discovery(c,a,platform,typ,canonical,reason):
 n=now_ms();detail=dumps({'platformCode':platform['platform_code'],'identityType':typ,'identityValue':canonical,'reason':reason,'teamId':a['team_id'],'deviceId':a['device_id']})
 # 同一插件会话/身份十分钟内只记一次，避免未授权轮询污染审计记录。
 recent=c.execute("SELECT 1 FROM security_events WHERE user_id=? AND organization_id=? AND event_type='collector_identity_discovered' AND detail_json=? AND created_at>? LIMIT 1",(a['user_id'],a['organization_id'],detail,n-600000)).fetchone()
 if not recent:c.execute("INSERT INTO security_events(user_id,organization_id,event_type,ip,user_agent,detail_json,created_at) VALUES(?,?,'collector_identity_discovered','','browser_extension',?,?)",(a['user_id'],a['organization_id'],detail,n))

def detect_account(db,a,p):
 with db.tx() as c:
  platform=_platform(c,p)
  if not platform:return _err('PLATFORM_NOT_FOUND','平台不存在或未启用',404)
  code=platform['platform_code'];typ,raw,canonical=normalize_identity(code,p.get('identityType'),p.get('identityValue'))
  if not canonical:return _err('STABLE_ACCOUNT_IDENTITY_REQUIRED','无法识别当前平台登录账号的稳定身份，已停止采集',409,platformCode=code,identityType=typ)
  n=now_ms();base="""SELECT DISTINCT ca.* FROM channel_account_identities i
   JOIN channel_accounts ca ON ca.channel_account_id=i.channel_account_id
   WHERE i.platform_id=? AND i.identity_type=? AND i.canonical_value=? AND i.status='active'
   AND (i.valid_from IS NULL OR i.valid_from<=?) AND (i.valid_to IS NULL OR i.valid_to>=?)
   AND ca.organization_id=? AND ca.platform_id=? AND ca.status='active' AND ca.collection_enabled=1"""
  candidates=c.execute(base,(platform['platform_id'],typ,canonical,n,n,a['organization_id'],platform['platform_id'])).fetchall()
  detail={'platformCode':code,'identityType':typ,'identityValue':canonical,'adminAction':'请管理员审批当前平台身份，或为当前用户预分配唯一自动绑定槽位'}
  if len(candidates)>1:
   record_discovery_in_tx(c,a,platform,typ,raw,canonical,'conflict','identity_conflict')
   _record_identity_discovery(c,a,platform,typ,canonical,'identity_conflict')
   return _err('ACCOUNT_IDENTITY_CONFLICT','平台账号身份存在重复登记，请联系管理员处理',409,matches=len(candidates),**detail)
  account=candidates[0] if candidates else None
  authorized=False
  if account:
   team=c.execute('SELECT 1 FROM team_channel_accounts WHERE team_id=? AND channel_account_id=?',(a['team_id'],account['channel_account_id'])).fetchone()
   user=c.execute("SELECT 1 FROM user_channel_account_grants WHERE user_id=? AND channel_account_id=?",(a['user_id'],account['channel_account_id'])).fetchone()
   admin=c.execute('SELECT 1 FROM platform_administrators WHERE user_id=?',(a['user_id'],)).fetchone()
   authorized=bool(team and (user or admin))
  if not authorized:
   result=discover_or_auto_claim_in_tx(c,a,platform,typ,raw,canonical,account['channel_account_id'] if account else None)
   if result['outcome']=='conflict':
    _record_identity_discovery(c,a,platform,typ,canonical,result['reason'])
    return _err('ACCOUNT_IDENTITY_CONFLICT','平台账号身份或预分配槽位存在冲突，请联系管理员处理',409,**detail)
   if result['outcome']!='claimed':
    _record_identity_discovery(c,a,platform,typ,canonical,result['reason'])
    return _err('ACCOUNT_APPROVAL_PENDING','已检测到当前平台账号，正在等待管理员审批',403,discoveryId=result['discovery']['discovery_id'],reasonCode=result['reason'],**detail)
   account=result['account']
  bid='dcb_'+uuid.uuid4().hex
  c.execute("""INSERT INTO device_channel_account_bindings(binding_id,organization_id,workspace_id,team_id,device_id,user_id,channel_account_id,platform_id,external_account_key,status,bound_at,bound_by,last_verified_at,metadata_json)
   VALUES(?,?,?,?,?,?,?,?,?,'active',?,?,?,'{}') ON CONFLICT(device_id,platform_id,external_account_key) DO UPDATE SET
   organization_id=excluded.organization_id,workspace_id=excluded.workspace_id,team_id=excluded.team_id,user_id=excluded.user_id,channel_account_id=excluded.channel_account_id,status='active',last_verified_at=excluded.last_verified_at""",(bid,a['organization_id'],a['workspace_id'],a['team_id'],a['device_id'],a['user_id'],account['channel_account_id'],platform['platform_id'],canonical,n,a['user_id'],n))
  return _ok(matchStatus='matched',platformCode=code,identityType=typ,identityValue=canonical,channelAccount={'channelAccountId':account['channel_account_id'],'displayName':account['display_name'],'businessPurpose':account['business_purpose']})

def issue_plugin_session(db,actor,p,ttl_ms=30*24*3600*1000):
 did=str(p.get('deviceId') or p.get('device_id') or '');wid=str(p.get('workspaceId') or p.get('workspace_id') or '');team=str(p.get('teamId') or p.get('team_id') or '')
 with db.tx() as c:
  d=c.execute("SELECT * FROM devices WHERE device_id=? AND workspace_id=? AND team_id=? AND organization_id=? AND status='active'",(did,wid,team,actor['organization_id'])).fetchone()
  if not d:return _err('DEVICE_SCOPE_INVALID','设备不存在、已停用或不属于指定作用域',403)
  if d['assigned_user_id'] and d['assigned_user_id']!=actor['user_id']:return _err('DEVICE_USER_MISMATCH','设备已分配给其他用户',403)
  if not c.execute("SELECT 1 FROM team_memberships WHERE user_id=? AND team_id=? AND status='active'",(actor['user_id'],team)).fetchone() and not c.execute("SELECT 1 FROM platform_administrators WHERE user_id=?",(actor['user_id'],)).fetchone():return _err('TEAM_MEMBERSHIP_REQUIRED','用户不属于该团队',403)
  token='jbp_'+secrets.token_urlsafe(40);sid='pls_'+uuid.uuid4().hex;n=now_ms();exp=n+min(max(int(ttl_ms),3600000),90*24*3600*1000)
  c.execute("INSERT INTO plugin_sessions(plugin_session_id,organization_id,workspace_id,team_id,user_id,device_id,token_hash,status,issued_at,expires_at,last_seen_at,client_version,metadata_json) VALUES(?,?,?,?,?,?,?,'active',?,?,?,?,?)",(sid,actor['organization_id'],wid,team,actor['user_id'],did,_hash(token),n,exp,n,str(p.get('clientVersion') or '')[:40],'{}'))
  return _ok(token=token,pluginSessionId=sid,deviceId=did,expiresAt=exp)

def plugin_actor(db,token,touch=False):
 if not token:return None
 n=now_ms()
 with db.tx(touch) as c:
  row=c.execute("""SELECT p.*,u.status user_status,d.status device_status,d.assigned_user_id,d.team_id device_team_id,d.organization_id device_org_id,
   EXISTS(SELECT 1 FROM team_memberships tm WHERE tm.user_id=p.user_id AND tm.team_id=p.team_id AND tm.status='active') team_member,
   EXISTS(SELECT 1 FROM platform_administrators pa WHERE pa.user_id=p.user_id) platform_admin
   FROM plugin_sessions p JOIN users u ON u.user_id=p.user_id JOIN devices d ON d.device_id=p.device_id WHERE p.token_hash=?""",(_hash(token),)).fetchone()
  if not row or row['status']!='active' or row['expires_at']<n or row['user_status']!='active' or row['device_status']!='active':return None
  if row['assigned_user_id']!=row['user_id'] or row['device_team_id']!=row['team_id'] or row['device_org_id']!=row['organization_id'] or not (row['team_member'] or row['platform_admin']):return None
  if touch:c.execute('UPDATE plugin_sessions SET last_seen_at=? WHERE plugin_session_id=?',(n,row['plugin_session_id']))
  return dict(row)

def heartbeat(db,a):
 with db.tx() as c:c.execute('UPDATE plugin_sessions SET last_seen_at=? WHERE plugin_session_id=?',(now_ms(),a['plugin_session_id']))
 return _ok(serverTime=now_ms())

def list_channel_accounts(db,a,p=None):
 p=p or {}
 with db.tx(False) as c:
  platform=_platform(c,p) if (p.get('platformId') or p.get('platformCode')) else None
  if (p.get('platformId') or p.get('platformCode')) and not platform:return _err('PLATFORM_NOT_FOUND','平台不存在或未启用',404)
  params=[a['organization_id'],a['team_id'],a['user_id'],a['user_id']]
  extra=''
  if platform:extra=' AND x.platform_id=?';params.append(platform['platform_id'])
  rows=c.execute("""SELECT DISTINCT x.channel_account_id,x.display_name,x.channel,x.platform_id,p.platform_code,x.business_purpose,x.collection_enabled
   FROM channel_accounts x JOIN team_channel_accounts t ON t.channel_account_id=x.channel_account_id
   JOIN platforms p ON p.platform_id=x.platform_id
   WHERE x.organization_id=? AND t.team_id=? AND x.status='active' AND x.collection_enabled=1
   AND (EXISTS(SELECT 1 FROM user_channel_account_grants g WHERE g.channel_account_id=x.channel_account_id AND g.user_id=?)
        OR EXISTS(SELECT 1 FROM platform_administrators pa WHERE pa.user_id=?))"""+extra+' ORDER BY x.display_name',tuple(params)).fetchall()
  return _ok(items=[dict(x) for x in rows])

def bind_account(db,a,p):
 # 兼容旧路由，但不再接受客户端指定 channelAccountId。
 if p.get('channelAccountId'):return _err('CLIENT_ACCOUNT_SELECTION_FORBIDDEN','渠道账号必须由服务器按稳定身份自动匹配',400)
 return detect_account(db,a,p)

def _ensure_source(c,a,account,platform,n):
 identity='extension:'+account['channel_account_id']
 row=c.execute('SELECT * FROM sources WHERE workspace_id=? AND channel=? AND account_identity=?',(a['workspace_id'],platform['platform_code'],identity)).fetchone()
 if row:
  c.execute('UPDATE sources SET last_seen_at=?,last_device_id=?,updated_at=? WHERE source_id=?',(n,a['device_id'],n,row['source_id']));return row['source_id']
 sid='src_'+uuid.uuid4().hex
 c.execute("""INSERT INTO sources(source_id,workspace_id,channel,account_identity,source_name,status,first_seen_at,last_seen_at,last_device_id,metadata_json,organization_id,team_id,channel_account_id,platform_id,source_type,source_subtype,direction,initiated_by,external_key,updated_at)
 VALUES(?,?,?,?,?,'active',?,?,?,?,?,?,?,?,?,'browser_extension','inbound','unknown',?,?)""",(sid,a['workspace_id'],platform['platform_code'],identity,account['display_name'],n,n,a['device_id'],dumps({'createdBy':'collector'}),a['organization_id'],a['team_id'],account['channel_account_id'],platform['platform_id'],'channel_account',identity,n))
 return sid

def resolve_conversation(db,a,p):
 aid=str(p.get('channelAccountId') or '');ext=str(p.get('externalConversationId') or '').strip();cid=str(p.get('contactId') or '').strip();identity=p.get('contactIdentity') or {};account_identity=p.get('accountIdentity') or {}
 if not aid or not ext:return _err('CONVERSATION_REQUIRED','channelAccountId、externalConversationId 必填')
 n=now_ms()
 with db.tx() as c:
  platform=_platform(c,p)
  if not platform:return _err('PLATFORM_NOT_FOUND','平台不存在或未启用',404)
  pid=platform['platform_id'];code=platform['platform_code'];account_typ,account_raw,account_key=normalize_identity(code,account_identity.get('identityType'),account_identity.get('identityValue'))
  if not account_key:return _err('STABLE_ACCOUNT_IDENTITY_REQUIRED','当前平台登录账号稳定身份缺失',409)
  binding=c.execute("SELECT * FROM device_channel_account_bindings WHERE device_id=? AND user_id=? AND channel_account_id=? AND platform_id=? AND external_account_key=? AND status='active'",(a['device_id'],a['user_id'],aid,pid,account_key)).fetchone()
  if not binding:return _err('ACCOUNT_BINDING_REQUIRED','当前插件实例尚未验证该平台账号',403)
  account=_account_allowed(c,a,aid,pid)
  if not account:return _err('ACCOUNT_NOT_AUTHORIZED','渠道账号授权已失效',403)
  ident=c.execute("SELECT 1 FROM channel_account_identities WHERE channel_account_id=? AND platform_id=? AND identity_type=? AND canonical_value=? AND status='active' AND (valid_from IS NULL OR valid_from<=?) AND (valid_to IS NULL OR valid_to>?)",(aid,pid,account_typ,account_key,n,n)).fetchone()
  if not ident:return _err('ACCOUNT_IDENTITY_CHANGED','平台账号身份验证已失效，请重新检测',403)
  c.execute('UPDATE device_channel_account_bindings SET last_verified_at=? WHERE binding_id=?',(n,binding['binding_id']))
  old=c.execute('SELECT * FROM conversations WHERE organization_id=? AND channel_account_id=? AND external_conversation_id=?',(a['organization_id'],aid,ext)).fetchone()
  if old:
   if cid and old['contact_id']!=cid:return _err('CONVERSATION_CONTACT_CONFLICT','会话已经绑定其他客户',409)
   # Existing conversations still refresh observed profile data, but only when the
   # submitted stable identity matches the identity already bound to this chat.
   typ,raw,canonical=normalize_identity(code,identity.get('identityType'),identity.get('identityValue'))
   bound=c.execute('SELECT * FROM contact_identities WHERE contact_identity_id=? AND contact_id=? AND platform_id=?',(old['contact_identity_id'],old['contact_id'],pid)).fetchone() if old['contact_identity_id'] else None
   if bound and canonical and typ==bound['identity_type'] and canonical==bound['canonical_value']:
    observed_name=sanitize_observed_name(identity.get('displayName'));observed_phone=str(identity.get('phone') or '')[:80];avatar=str(identity.get('avatarUrl') or '')[:2048]
    c.execute('UPDATE contact_identities SET last_seen_at=? WHERE contact_identity_id=?',(n,bound['contact_identity_id']))
    c.execute("UPDATE contacts SET display_name=CASE WHEN ?<>'' THEN ? ELSE display_name END,observed_phone=CASE WHEN ?<>'' THEN ? ELSE observed_phone END,avatar_url=CASE WHEN ?<>'' THEN ? ELSE avatar_url END,last_observed_device_id=?,last_observed_at=?,last_seen_at=?,updated_at=? WHERE contact_id=?",(observed_name,observed_name,observed_phone,observed_phone,avatar,avatar,a['device_id'],n,n,n,old['contact_id']))
   c.execute('UPDATE conversations SET last_collected_at=?,updated_at=? WHERE conversation_id=?',(n,n,old['conversation_id']))
   refreshed=dict(c.execute('SELECT * FROM conversations WHERE conversation_id=?',(old['conversation_id'],)).fetchone())
   return _ok(contactId=old['contact_id'],contactIdentityId=old['contact_identity_id'],conversation=refreshed,created=False,contactCreated=False)
  iid=None;contact_created=False
  if cid:
   ct=c.execute("SELECT * FROM contacts WHERE contact_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND deleted_at IS NULL",(cid,a['organization_id'],a['workspace_id'],a['team_id'])).fetchone()
   if not ct:return _err('CONTACT_SCOPE_INVALID','联系人不存在或不属于当前作用域',404)
  else:
   typ,raw,canonical=normalize_identity(code,identity.get('identityType'),identity.get('identityValue'))
   if not canonical:return _err('STABLE_IDENTITY_REQUIRED','首次会话必须提供有效的 WA/TG 稳定身份',400)
   ir=c.execute('SELECT * FROM contact_identities WHERE organization_id=? AND platform_id=? AND identity_type=? AND canonical_value=?',(a['organization_id'],pid,typ,canonical)).fetchone()
   if ir:
    cid=ir['contact_id'];iid=ir['contact_identity_id'];ct=c.execute("SELECT * FROM contacts WHERE contact_id=? AND workspace_id=? AND team_id=? AND deleted_at IS NULL",(cid,a['workspace_id'],a['team_id'])).fetchone()
    if not ct:return _err('IDENTITY_SCOPE_CONFLICT','平台身份属于其他工作区、团队或已删除客户',409)
    c.execute('UPDATE contact_identities SET last_seen_at=? WHERE contact_identity_id=?',(n,iid))
    observed_name=sanitize_observed_name(identity.get('displayName'));observed_phone=str(identity.get('phone') or '')[:80];avatar=str(identity.get('avatarUrl') or '')[:2048]
    c.execute("UPDATE contacts SET display_name=CASE WHEN ?<>'' THEN ? ELSE display_name END,observed_phone=CASE WHEN ?<>'' THEN ? ELSE observed_phone END,avatar_url=CASE WHEN ?<>'' THEN ? ELSE avatar_url END,last_observed_device_id=?,last_observed_at=?,last_seen_at=?,updated_at=? WHERE contact_id=?",(observed_name,observed_name,observed_phone,observed_phone,avatar,avatar,a['device_id'],n,n,n,cid))
    ct=c.execute('SELECT * FROM contacts WHERE contact_id=?',(cid,)).fetchone()
   else:
    source_id=_ensure_source(c,a,account,platform,n);cid='ct_'+uuid.uuid4().hex;iid='cid_'+uuid.uuid4().hex
    name=sanitize_observed_name(identity.get('displayName'));phone=str(identity.get('phone') or '')[:80];avatar=str(identity.get('avatarUrl') or '')[:2048]
    c.execute("""INSERT INTO contacts(contact_id,workspace_id,source_id,channel,external_contact_id,display_name,observed_phone,avatar_url,observed_json,observation_hash,manual_name,manual_phone,remark,status,business_json,last_observed_device_id,last_observed_at,version,created_at,updated_at,last_seen_at,organization_id,team_id)
     VALUES(?,?,?,?,?,?,?,?,?,'','','','', 'active','{}',?,?,1,?,?,?,?,?)""",(cid,a['workspace_id'],source_id,code,canonical,name,phone,avatar,dumps({'platform':code,'identityType':typ}),a['device_id'],n,n,n,n,a['organization_id'],a['team_id']))
    c.execute("INSERT INTO contact_identities(contact_identity_id,organization_id,workspace_id,contact_id,platform_id,identity_type,identity_value,canonical_value,verification_status,is_primary,first_seen_at,last_seen_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,'observed',1,?,?,?)",(iid,a['organization_id'],a['workspace_id'],cid,pid,typ,raw,canonical,n,n,dumps({'collector':'browser_extension'})))
    ct=c.execute('SELECT * FROM contacts WHERE contact_id=?',(cid,)).fetchone();contact_created=True
  if not iid:
   ir=c.execute('SELECT contact_identity_id FROM contact_identities WHERE contact_id=? AND platform_id=? ORDER BY is_primary DESC,first_seen_at LIMIT 1',(cid,pid)).fetchone();iid=ir['contact_identity_id'] if ir else None
  vid='cnv_'+uuid.uuid4().hex
  c.execute("INSERT INTO conversations(conversation_id,organization_id,workspace_id,team_id,channel_account_id,platform_id,contact_id,contact_identity_id,external_conversation_id,conversation_type,status,assigned_user_id,source_id,last_collected_at,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'direct','active',?,?,?,'{}',?,?)",(vid,a['organization_id'],a['workspace_id'],a['team_id'],aid,pid,cid,iid,ext,a['user_id'],ct['source_id'],n,n,n))
  conv=dict(c.execute('SELECT * FROM conversations WHERE conversation_id=?',(vid,)).fetchone())
  return _ok(contactId=cid,contactIdentityId=iid,conversation=conv,created=True,contactCreated=contact_created)

def collect_messages(db,a,p):
 items=p.get('messages')
 if not isinstance(items,list) or not items or len(items)>100:return _err('INVALID_BATCH','messages 必须是 1 至 100 条的数组')
 if len(json.dumps(p,ensure_ascii=False).encode())>524288:return _err('REQUEST_TOO_LARGE','消息批次超过 512KB',413)
 out=[]
 for item in items:
  try:out.append(_collect_one(db,a,item if isinstance(item,dict) else {}))
  except Exception:out.append({'ok':False,'code':'MESSAGE_INTERNAL_ERROR'})
 duplicated=sum(bool(x.get('duplicate')) for x in out);accepted=sum(bool(x.get('ok')) and not x.get('duplicate') for x in out)
 return _ok(results=out,accepted=accepted,duplicated=duplicated,rejected=len(out)-accepted-duplicated,total=len(out))

def _collect_one(db,a,p):
 vid=str(p.get('conversationId') or '');eid=str(p.get('externalMessageId') or '').strip() or None;ceid=str(p.get('clientEventId') or '').strip() or None
 if not eid and not ceid:return {'ok':False,'code':'MESSAGE_ID_REQUIRED'}
 text=p.get('text');text=None if text is None else str(text)
 if text is not None and len(text.encode())>65536:return {'ok':False,'code':'MESSAGE_TEXT_TOO_LARGE'}
 direction=str(p.get('direction') or 'inbound');typ=str(p.get('contentType') or 'text');occurred=int(p.get('occurredAt') or now_ms())
 if direction not in ('inbound','outbound','system') or typ not in ('text','image','audio','video','file','sticker','location','contact','call','system','unknown'):return {'ok':False,'code':'MESSAGE_ENUM_INVALID'}
 redacted,flags=redact_text(text);digest=hashlib.sha256(((text or '')+'|'+direction+'|'+typ+'|'+str(occurred)).encode()).hexdigest();n=now_ms()
 with db.tx() as c:
  v=c.execute("SELECT * FROM conversations WHERE conversation_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND assigned_user_id=?",(vid,a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'])).fetchone()
  if not v:return {'ok':False,'code':'CONVERSATION_SCOPE_INVALID'}
  if not _account_allowed(c,a,v['channel_account_id'],v['platform_id']):return {'ok':False,'code':'ACCOUNT_NOT_AUTHORIZED'}
  if not c.execute("SELECT 1 FROM device_channel_account_bindings WHERE device_id=? AND user_id=? AND channel_account_id=? AND platform_id=? AND status='active'",(a['device_id'],a['user_id'],v['channel_account_id'],v['platform_id'])).fetchone():return {'ok':False,'code':'ACCOUNT_BINDING_REQUIRED'}
  old=None
  if eid:old=c.execute('SELECT message_id,content_hash FROM conversation_messages WHERE organization_id=? AND channel_account_id=? AND external_message_id=?',(a['organization_id'],v['channel_account_id'],eid)).fetchone()
  if not old and ceid:old=c.execute('SELECT message_id,content_hash FROM conversation_messages WHERE organization_id=? AND channel_account_id=? AND client_event_id=?',(a['organization_id'],v['channel_account_id'],ceid)).fetchone()
  if old:return {'ok':old['content_hash']==digest,'duplicate':old['content_hash']==digest,'code':None if old['content_hash']==digest else 'IDEMPOTENCY_CONFLICT','messageId':old['message_id']}
  mid='msg_'+uuid.uuid4().hex
  c.execute("INSERT INTO conversation_messages(message_id,organization_id,workspace_id,team_id,conversation_id,channel_account_id,contact_id,external_message_id,client_event_id,direction,sender_type,sender_external_id,content_type,text_content,redacted_text,content_hash,pii_flags_json,occurred_at,collected_at,status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active',?)",(mid,a['organization_id'],a['workspace_id'],a['team_id'],vid,v['channel_account_id'],v['contact_id'],eid,ceid,direction,str(p.get('senderType') or 'unknown'),str(p.get('senderExternalId') or '') or None,typ,text,redacted,digest,dumps(flags),occurred,n,dumps(p.get('metadata') or {})))
  c.execute('UPDATE conversations SET first_message_at=COALESCE(first_message_at,?),last_message_at=MAX(COALESCE(last_message_at,0),?),last_collected_at=?,updated_at=? WHERE conversation_id=?',(occurred,occurred,n,n,vid))
  return {'ok':True,'duplicate':False,'messageId':mid}
