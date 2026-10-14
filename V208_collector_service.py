# -*- coding: utf-8 -*-
"""V208 Collector 服务：插件会话、账号绑定、首次客户解析与幂等消息采集。"""
import hashlib,json,logging,re,secrets,uuid
from V207_shared_db import now_ms,dumps
from V208_privacy import redact_text
from V208_message_normalization import split_translation_suffix,message_digest
from V208_identity import collector_canonical,normalize_identity
from V208_name_sanitize import sanitize_observed_name
from V208_avatar import sanitize_avatar
from V208_account_claim_service import record_discovery_in_tx,discover_or_auto_claim_in_tx
from V208_follow_up_notification_service import complete_follow_up_in_tx
LOG=logging.getLogger(__name__)

def _complete_follow_up_isolated(c,*args,**kw):
 """210.2.44：跟进自动完成是消息入库的附属副作用，必须与消息写入隔离。
 若跟进表约束/触发器/旧数据导致异常，只回滚本 SAVEPOINT 内的跟进改动，
 消息与会话缓存照常提交；跟进仍可由手动完成或下一条出站消息再次触发。"""
 sp='juba_fu_'+uuid.uuid4().hex[:12]
 c.execute('SAVEPOINT '+sp)
 try:
  result=complete_follow_up_in_tx(c,*args,**kw)
 except Exception as ex:
  try:c.execute('ROLLBACK TO SAVEPOINT '+sp)
  finally:c.execute('RELEASE SAVEPOINT '+sp)
  LOG.warning('collector follow-up completion isolated and skipped: %s',str(ex)[:300])
  return 0
 c.execute('RELEASE SAVEPOINT '+sp)
 return result

def _ok(**kw):return ({'ok':True,**kw},200)
def _err(code,message,status=400,**kw):return ({'ok':False,'code':code,'message':message,**kw},status)
def _hash(v):return hashlib.sha256(v.encode()).hexdigest()
def _platform(c,p):
 """
 查找采集平台。

 JUBAOPEN_THREADS_PLATFORM_AUTO_ENABLE_210_3_4

 Threads 是 210.3.x 新增的内置采集平台。旧数据库可能没有
 platforms 记录，或者记录仍为 disabled。第一次收到 Threads
 采集请求时，在当前事务中幂等创建或启用它。

 其他平台继续保持原来的 fail-closed 行为。
 """
 value=str(
  p.get('platformId')
  or p.get('platformCode')
  or ''
 ).strip().lower()

 if not value:
  return None

 row=c.execute(
  """SELECT * FROM platforms
     WHERE status='active'
     AND (
      lower(platform_id)=?
      OR lower(platform_code)=?
     )""",
  (value,value)
 ).fetchone()

 if row:
  return row

 if value not in ('threads','plt_threads'):
  return None

 timestamp=now_ms()

 existing=c.execute(
  """SELECT * FROM platforms
     WHERE lower(platform_id)='plt_threads'
        OR lower(platform_code)='threads'
     ORDER BY
      CASE
       WHEN lower(platform_code)='threads' THEN 0
       ELSE 1
      END
     LIMIT 1"""
 ).fetchone()

 if existing:
  c.execute(
   """UPDATE platforms
      SET status='active',
          platform_name=CASE
           WHEN trim(coalesce(platform_name,''))=''
           THEN 'Threads'
           ELSE platform_name
          END,
          platform_abbr=CASE
           WHEN trim(coalesce(platform_abbr,''))=''
           THEN 'THREADS'
           ELSE platform_abbr
          END,
          platform_kind=CASE
           WHEN trim(coalesce(platform_kind,''))=''
           THEN 'social'
           ELSE platform_kind
          END,
          updated_at=?
      WHERE platform_id=?""",
   (timestamp,existing['platform_id'])
  )
 else:
  c.execute(
   """INSERT OR IGNORE INTO platforms(
       platform_id,
       platform_code,
       platform_name,
       platform_abbr,
       platform_kind,
       status,
       capabilities_json,
       metadata_json,
       created_at,
       updated_at
      )
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
   (
    'plt_threads',
    'threads',
    'Threads',
    'THREADS',
    'social',
    'active',
    dumps({
     'collector':True,
     'messages':True,
     'manualOwnerIdentity':True,
     'identityTypes':[
      'threads_user_id',
      'threads_username'
     ]
    }),
    dumps({
     'system':True,
     'introducedIn':'210.3.4',
     'provisioning':
      'collector-runtime-idempotent'
    }),
    timestamp,
    timestamp
   )
  )

 return c.execute(
  """SELECT * FROM platforms
     WHERE status='active'
     AND (
      lower(platform_id)='plt_threads'
      OR lower(platform_code)='threads'
     )
     ORDER BY
      CASE
       WHEN lower(platform_code)='threads' THEN 0
       ELSE 1
      END
     LIMIT 1"""
 ).fetchone()


def _canonical(code,typ,value):
 return collector_canonical(code,typ,value)

def _normalize_code(value):return re.sub(r'[^A-Z0-9]','',str(value or '').upper())
def _account_allowed(c,a,aid,pid):
 return c.execute("""SELECT ca.* FROM channel_accounts ca
  JOIN team_channel_accounts ta ON ta.channel_account_id=ca.channel_account_id AND ta.team_id=?
  WHERE ca.channel_account_id=? AND ca.organization_id=? AND ca.platform_id=?
  AND ca.status='active'
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

def rebind_plugin(db,p,client_ip='',user_agent='',ttl_ms=30*24*3600*1000):
 """核销管理员签发的一次性换绑码；必须由原安装实例发起并保留原设备档案。"""
 code=_normalize_code(p.get('rebindCode') or p.get('bindingCode') or p.get('rebind_code'));iid=str(p.get('installationId') or p.get('installation_id') or '').strip()
 if len(code)<16 or len(iid)<16 or len(iid)>160:return _err('REBIND_INVALID','换绑码或安装实例无效',400)
 digest=_hash(code);n=now_ms()
 with db.tx() as c:
  r=c.execute('SELECT * FROM device_rebind_requests WHERE code_hash=?',(digest,)).fetchone()
  if not r or r['status']!='pending':return _err('REBIND_INVALID','换绑码无效、已使用或已撤销',409)
  if r['expires_at']<n:
   c.execute("UPDATE device_rebind_requests SET status='expired' WHERE rebind_id=? AND status='pending'",(r['rebind_id'],))
   return _err('REBIND_INVALID','换绑码无效、已使用或已撤销',409)
  d=c.execute('SELECT * FROM devices WHERE device_id=? AND organization_id=?',(r['device_id'],r['organization_id'])).fetchone()
  if not d or d['status']!='active' or d['installation_id']!=iid:return _err('REBIND_INSTANCE_MISMATCH','换绑码不属于当前插件安装实例',409)
  u=c.execute("SELECT u.user_id,u.display_name FROM users u JOIN team_memberships tm ON tm.user_id=u.user_id AND tm.team_id=? AND tm.status='active' WHERE u.user_id=? AND u.organization_id=? AND u.status='active'",(r['to_team_id'],r['to_user_id'],r['organization_id'])).fetchone()
  t=c.execute("SELECT * FROM teams WHERE team_id=? AND organization_id=? AND status='active'",(r['to_team_id'],r['organization_id'])).fetchone()
  w=c.execute("SELECT * FROM workspaces WHERE workspace_id=? AND organization_id=? AND status='active'",(r['to_workspace_id'],r['organization_id'])).fetchone()
  if not u or not t or not w or t['workspace_id']!=w['workspace_id']:return _err('REBIND_SCOPE_INVALID','目标用户、团队或工作区已失效',409)
  changed=c.execute("UPDATE device_rebind_requests SET status='consumed',consumed_at=? WHERE rebind_id=? AND status='pending' AND expires_at>=?",(n,r['rebind_id'],n)).rowcount
  if changed!=1:return _err('REBIND_INVALID','换绑码已被使用',409)
  c.execute('UPDATE device_assignments SET released_at=? WHERE device_id=? AND released_at IS NULL',(n,d['device_id']))
  c.execute('INSERT INTO device_assignments(assignment_id,device_id,assigned_user_id,team_id,assigned_at,released_at) VALUES(?,?,?,?,?,NULL)',('asn_'+secrets.token_hex(12),d['device_id'],r['to_user_id'],r['to_team_id'],n))
  c.execute('UPDATE devices SET workspace_id=?,team_id=?,assigned_user_id=?,last_seen_at=? WHERE device_id=?',(r['to_workspace_id'],r['to_team_id'],r['to_user_id'],n,d['device_id']))
  c.execute("UPDATE plugin_sessions SET status='revoked',revoked_at=?,revoked_by=?,revoked_reason='device_rebound' WHERE device_id=? AND status='active'",(n,r['created_by'],d['device_id']))
  token='jbp_'+secrets.token_urlsafe(40);sid='pls_'+uuid.uuid4().hex;exp=n+min(max(int(ttl_ms),3600000),90*24*3600*1000);client=str(p.get('clientVersion') or '')[:40]
  c.execute("INSERT INTO plugin_sessions(plugin_session_id,organization_id,workspace_id,team_id,user_id,device_id,token_hash,status,issued_at,expires_at,last_seen_at,client_version,metadata_json) VALUES(?,?,?,?,?,?,?,'active',?,?,?,?,?)",(sid,r['organization_id'],r['to_workspace_id'],r['to_team_id'],r['to_user_id'],d['device_id'],_hash(token),n,exp,n,client,dumps({'rebindId':r['rebind_id'],'clientIp':str(client_ip)[:80],'userAgent':str(user_agent)[:300]})))
  c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at,organization_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(r['to_workspace_id'],r['created_by'],d['device_id'],'consume','device_rebind_request',r['rebind_id'],dumps({'userId':d['assigned_user_id'],'teamId':d['team_id'],'workspaceId':d['workspace_id']}),dumps({'userId':r['to_user_id'],'teamId':r['to_team_id'],'workspaceId':r['to_workspace_id'],'pluginSessionId':sid}),r['reason'],n,r['organization_id']))
  return _ok(pluginToken=token,pluginSessionId=sid,deviceId=d['device_id'],expiresAt=exp,user={'userId':u['user_id'],'displayName':u['display_name']},workspace={'workspaceId':w['workspace_id'],'name':w['name']},team={'teamId':t['team_id'],'name':t['name']})

def plugin_context(db,a):
 with db.tx(False) as c:
  u=c.execute('SELECT user_id,display_name,login_name FROM users WHERE user_id=?',(a['user_id'],)).fetchone();d=c.execute('SELECT device_id,installation_id,user_device_alias,user_computer_alias,system_device_name,system_computer_name,admin_device_name,admin_computer_name,last_seen_at,status FROM devices WHERE device_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND assigned_user_id=?',(a['device_id'],a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'])).fetchone();w=c.execute('SELECT workspace_id,name FROM workspaces WHERE workspace_id=?',(a['workspace_id'],)).fetchone();t=c.execute('SELECT team_id,name FROM teams WHERE team_id=?',(a['team_id'],)).fetchone()
  if not d:return _err('DEVICE_SCOPE_INVALID','当前插件设备不存在或已不属于当前用户',403)
  return _ok(user=dict(u),device=dict(d),workspace=dict(w),team=dict(t),pluginSessionId=a['plugin_session_id'],expiresAt=a['expires_at'])

def update_plugin_device(db,a,p):
 alias=str(p.get('deviceName') if p.get('deviceName') is not None else p.get('userDeviceAlias') if p.get('userDeviceAlias') is not None else '').strip()
 if len(alias)>120:return _err('DEVICE_NAME_TOO_LONG','我的设备名称不能超过 120 个字符',400)
 if any(ord(ch)<32 for ch in alias):return _err('DEVICE_NAME_INVALID','我的设备名称不能包含控制字符',400)
 n=now_ms()
 with db.tx() as c:
  old=c.execute("SELECT * FROM devices WHERE device_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND assigned_user_id=? AND status='active'",(a['device_id'],a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'])).fetchone()
  if not old:return _err('DEVICE_SCOPE_INVALID','只能修改当前插件会话绑定的有效设备',403)
  c.execute('UPDATE devices SET user_device_alias=?,last_seen_at=? WHERE device_id=?',(alias,n,a['device_id']))
  new=c.execute('SELECT * FROM devices WHERE device_id=?',(a['device_id'],)).fetchone()
  c.execute('INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at,organization_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(a['workspace_id'],a['user_id'],a['device_id'],'update_self_alias','device',a['device_id'],dumps({'userDeviceAlias':old['user_device_alias']}),dumps({'userDeviceAlias':new['user_device_alias']}),'插件用户修改我的设备名称',n,a['organization_id']))
  return _ok(device={'deviceId':new['device_id'],'userDeviceAlias':new['user_device_alias'],'adminDeviceName':new['admin_device_name'],'systemDeviceName':new['system_device_name']})

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
   AND ca.organization_id=? AND ca.platform_id=? AND ca.status='active'"""
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
  return _ok(matchStatus='matched',platformCode=code,identityType=typ,identityValue=canonical,channelAccount={'channelAccountId':account['channel_account_id'],'displayName':account['display_name'],'businessPurpose':account['business_purpose'],'businessScene':account['business_scene'],'contactEntryPolicy':account['contact_entry_policy'],'collectionEnabled':bool(account['collection_enabled'])})

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
  if touch:
   c.execute('UPDATE plugin_sessions SET last_seen_at=? WHERE plugin_session_id=?',(n,row['plugin_session_id']))
   c.execute('UPDATE devices SET last_seen_at=? WHERE device_id=?',(n,row['device_id']))
  return dict(row)

def heartbeat(db,a):
 n=now_ms()
 with db.tx() as c:
  c.execute('UPDATE plugin_sessions SET last_seen_at=? WHERE plugin_session_id=?',(n,a['plugin_session_id']))
  c.execute('UPDATE devices SET last_seen_at=? WHERE device_id=?',(n,a['device_id']))
 return _ok(serverTime=n)

def list_channel_accounts(db,a,p=None):
 p=p or {}
 with db.tx(False) as c:
  platform=_platform(c,p) if (p.get('platformId') or p.get('platformCode')) else None
  if (p.get('platformId') or p.get('platformCode')) and not platform:return _err('PLATFORM_NOT_FOUND','平台不存在或未启用',404)
  params=[a['organization_id'],a['team_id'],a['user_id'],a['user_id']]
  extra=''
  if platform:extra=' AND x.platform_id=?';params.append(platform['platform_id'])
  rows=c.execute("""SELECT DISTINCT x.channel_account_id,x.display_name,x.channel,x.platform_id,p.platform_code,x.business_purpose,x.business_scene,x.contact_entry_policy,x.collection_enabled
   FROM channel_accounts x JOIN team_channel_accounts t ON t.channel_account_id=x.channel_account_id
   JOIN platforms p ON p.platform_id=x.platform_id
   WHERE x.organization_id=? AND t.team_id=? AND x.status='active'
   AND (EXISTS(SELECT 1 FROM user_channel_account_grants g WHERE g.channel_account_id=x.channel_account_id AND g.user_id=?)
        OR EXISTS(SELECT 1 FROM platform_administrators pa WHERE pa.user_id=?))"""+extra+' ORDER BY x.display_name',tuple(params)).fetchall()
  return _ok(items=[dict(x) for x in rows])

def bind_account(db,a,p):
 # 兼容旧路由，但不再接受客户端指定 channelAccountId。
 if p.get('channelAccountId'):return _err('CLIENT_ACCOUNT_SELECTION_FORBIDDEN','渠道账号必须由服务器按稳定身份自动匹配',400)
 return detect_account(db,a,p)

SOCIAL_ACQUISITION_CODES=(
 'social_outbound','social_inbound','social_community','social_referral',
 'social_content','social_other','social_pending'
)

def _social_source_types(c):
 marks=','.join('?' for _ in SOCIAL_ACQUISITION_CODES)
 return c.execute(
  "SELECT source_type_id,source_type_code,name FROM source_type_definitions "
  "WHERE is_active=1 AND source_type_code IN ("+marks+") ORDER BY sort_order,source_type_code",
  SOCIAL_ACQUISITION_CODES).fetchall()

def _resolved_source_type(c,account,selected_id=None):
 social=account['business_scene']=='social_acquisition'
 if selected_id:
  row=c.execute("SELECT source_type_id,source_type_code,name FROM source_type_definitions WHERE source_type_id=? AND is_active=1",(selected_id,)).fetchone()
  if row and (not social or row['source_type_code'] in SOCIAL_ACQUISITION_CODES):return row
  return None
 preferred=account['suggested_source_type_id'] if 'suggested_source_type_id' in account.keys() else None
 if preferred:
  row=c.execute("SELECT source_type_id,source_type_code,name FROM source_type_definitions WHERE source_type_id=? AND is_active=1",(preferred,)).fetchone()
  if row and (not social or row['source_type_code'] in SOCIAL_ACQUISITION_CODES):return row
 code='social_pending' if social else 'social_direct_message'
 return c.execute("SELECT source_type_id,source_type_code,name FROM source_type_definitions WHERE source_type_code=? AND is_active=1",(code,)).fetchone()

def _source_initiation(code):
 if code=='social_outbound':return 'outbound','business'
 if code in ('social_inbound','social_referral','social_content'):return 'inbound','customer'
 if code=='social_community':return 'inbound','mixed'
 return 'inbound','unknown'

def _ensure_source(c,a,account,platform,n,source_type=None,resolution_method=None):
 aid=account['channel_account_id'];pid=platform['platform_id'];social=account['business_scene']=='social_acquisition'
 source_type=source_type or _resolved_source_type(c,account)
 if not source_type:raise RuntimeError('ACTIVE_SOURCE_TYPE_REQUIRED')
 if social and source_type['source_type_code'] not in SOCIAL_ACQUISITION_CODES:raise RuntimeError('SOCIAL_SOURCE_TYPE_INVALID')
 market_id=account['default_market_id'] if 'default_market_id' in account.keys() else None
 market=c.execute("SELECT market_id,name FROM markets WHERE market_id=? AND organization_id=? AND status='active'",(market_id,a['organization_id'])).fetchone() if market_id else None
 if social and not market:raise RuntimeError('SOCIAL_MARKET_REQUIRED')
 if not market:market_id=None
 direction,initiated=_source_initiation(source_type['source_type_code']) if social else ('inbound','contact')
 identity_data={
  'organizationId':a['organization_id'],'workspaceId':a['workspace_id'],
  'marketId':market_id,'platformId':pid,'channelAccountId':aid,
  'businessScene':account['business_scene'],'sourceTypeId':source_type['source_type_id'],
  'campaignId':None,'initiatedBy':initiated
 }
 canonical=json.dumps(identity_data,ensure_ascii=False,sort_keys=True,separators=(',',':'))
 fingerprint=_hash(canonical)
 # The legacy UNIQUE(workspace_id,channel,account_identity) remains in fresh schema.
 # Include the fingerprint so one account may legitimately have multiple business sources.
 identity='extension:'+aid+(':'+fingerprint if social else '')
 row=c.execute("""SELECT * FROM sources WHERE organization_id=? AND workspace_id=? AND team_id=?
  AND channel_account_id=? AND platform_id=? AND source_fingerprint=? AND status='active'""",
  (a['organization_id'],a['workspace_id'],a['team_id'],aid,pid,fingerprint)).fetchone()
 if row:
  c.execute("UPDATE sources SET last_seen_at=?,last_device_id=?,updated_at=? WHERE source_id=?",(n,a['device_id'],n,row['source_id']))
  return row['source_id']
 display=(' / '.join((market['name'],platform['platform_code'],'社交获客',source_type['name'],account['display_name'])) if social else account['display_name'])
 method=resolution_method or ('account_default' if not social else 'fallback_pending')
 confidence=0.2 if source_type['source_type_code']=='social_pending' else (0.8 if method=='account_suggestion' else 1.0)
 sid='src_'+uuid.uuid4().hex
 c.execute("""INSERT INTO sources(source_id,workspace_id,channel,account_identity,source_name,status,first_seen_at,last_seen_at,last_device_id,
  metadata_json,organization_id,team_id,channel_account_id,platform_id,source_type,source_subtype,direction,initiated_by,external_key,updated_at,
  source_type_id,channel_type_id,market_id,source_fingerprint,resolver_version,resolution_method,resolution_confidence)
  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
  (sid,a['workspace_id'],platform['platform_code'],identity,display,'active',n,n,a['device_id'],
   dumps({'createdBy':'collector','resolverVersion':'v219.2','businessScene':account['business_scene'],'campaignId':None,'needsConfirmation':source_type['source_type_code']=='social_pending'}),
   a['organization_id'],a['team_id'],aid,pid,source_type['source_type_code'],'browser_extension',direction,initiated,identity,n,
   source_type['source_type_id'],account['channel_type_id'],market_id,fingerprint,'v219.2',method,confidence))
 return sid

def _entry_configuration(c,a,account):
 fields=[dict(x) for x in c.execute("SELECT * FROM custom_field_definitions WHERE workspace_id=? AND enabled=1 AND display_zone='interaction_panel' ORDER BY sort_order,field_key",(a['workspace_id'],)).fetchall()]
 stages=[x for x in fields if str(x.get('field_role') or '').startswith('stage_')]
 quick=[x for x in fields if not str(x.get('field_role') or '').startswith('stage_') and bool(x.get('is_quick_edit'))]
 tags=[dict(x) for x in c.execute("SELECT tag_id,name,color,tag_kind,sort_order FROM tags WHERE workspace_id=? AND enabled=1 ORDER BY tag_kind,sort_order,name",(a['workspace_id'],)).fetchall()]
 social=account['business_scene']=='social_acquisition'
 source_types=[dict(x) for x in _social_source_types(c)] if social else []
 source=_resolved_source_type(c,account)
 return {'fields':quick,'tags':tags,'stages':stages,'sourceTypes':source_types,
  'suggestedSourceType':source['source_type_code'] if source else None,
  'suggestedSourceTypeId':source['source_type_id'] if source else None,
  'defaultMarketId':account['default_market_id'] if 'default_market_id' in account.keys() else None}

def _entry(account,state,**extra):
 return _ok(entryState=state,contactCreated=False,contactId=extra.pop('contactId',None),contactIdentityId=extra.pop('contactIdentityId',None),conversation=extra.pop('conversation',None),businessScene=account['business_scene'],contactEntryPolicy=account['contact_entry_policy'],**extra)

WA_ALIAS_EVIDENCE={'wa-chat-contact-model','same-wa-chat-contact-model'}

def _trusted_contact_identities(code,identity,aliases=None):
 """Normalize the primary identity and only model-proven WhatsApp aliases."""
 raw_items=[(identity,True)]
 if code=='whatsapp':
  source=aliases if isinstance(aliases,list) else identity.get('aliases') if isinstance(identity,dict) else []
  for item in (source if isinstance(source,list) else [])[:8]:raw_items.append((item,False))
 out=[];seen=set()
 for item,primary in raw_items:
  if not isinstance(item,dict):continue
  evidence=str(item.get('evidence') or item.get('source') or '')
  if not primary and (code!='whatsapp' or evidence not in WA_ALIAS_EVIDENCE):continue
  typ,raw,canonical=normalize_identity(code,item.get('identityType'),item.get('identityValue'))
  if not canonical or (code=='whatsapp' and typ not in ('whatsapp_lid','whatsapp_jid')):continue
  key=(typ,canonical)
  if key in seen:continue
  seen.add(key);out.append({'identityType':typ,'identityValue':raw,'canonicalValue':canonical,'primary':primary,'evidence':evidence or 'primary-observation'})
 return out

def _identity_matches(c,a,pid,items):
 if not items:return []
 clauses=[];params=[]
 for x in items:clauses.append('(identity_type=? AND canonical_value=?)');params.extend((x['identityType'],x['canonicalValue']))
 return c.execute("SELECT * FROM contact_identities WHERE organization_id=? AND workspace_id=? AND platform_id=? AND ("+' OR '.join(clauses)+')',(a['organization_id'],a['workspace_id'],pid,*params)).fetchall()

def _ensure_contact_identities(c,a,pid,cid,items,n):
 rows=[]
 for x in items:
  old=c.execute("SELECT * FROM contact_identities WHERE organization_id=? AND workspace_id=? AND platform_id=? AND identity_type=? AND canonical_value=?",(a['organization_id'],a['workspace_id'],pid,x['identityType'],x['canonicalValue'])).fetchone()
  if old and old['contact_id']!=cid:raise ValueError('WHATSAPP_IDENTITY_SPLIT_CONFLICT')
  if old:
   c.execute('UPDATE contact_identities SET last_seen_at=? WHERE contact_identity_id=?',(n,old['contact_identity_id']));rows.append(old);continue
  iid='ci_'+uuid.uuid4().hex;primary=0 if c.execute('SELECT 1 FROM contact_identities WHERE contact_id=? AND is_primary=1',(cid,)).fetchone() else 1
  c.execute("INSERT INTO contact_identities(contact_identity_id,organization_id,workspace_id,contact_id,platform_id,identity_type,identity_value,canonical_value,verification_status,is_primary,first_seen_at,last_seen_at,metadata_json) VALUES(?,?,?,?,?,?,?,?, 'observed',?,?,?,?)",(iid,a['organization_id'],a['workspace_id'],cid,pid,x['identityType'],x['identityValue'],x['canonicalValue'],primary,n,n,dumps({'createdBy':'collector.identity-set','evidence':x['evidence']})))
  rows.append(c.execute('SELECT * FROM contact_identities WHERE contact_identity_id=?',(iid,)).fetchone())
 lids=[x for x in items if x['identityType']=='whatsapp_lid'];jids=[x for x in items if x['identityType']=='whatsapp_jid']
 if lids and jids:
  lid,jid=lids[0],jids[0];evidence='wa-chat-contact-model'
  old=c.execute("SELECT * FROM whatsapp_identity_links WHERE organization_id=? AND workspace_id=? AND platform_id=? AND (lid_canonical=? OR jid_canonical=?)",(a['organization_id'],a['workspace_id'],pid,lid['canonicalValue'],jid['canonicalValue'])).fetchall()
  if any(r['contact_id']!=cid or r['lid_canonical']!=lid['canonicalValue'] or r['jid_canonical']!=jid['canonicalValue'] for r in old):raise ValueError('WHATSAPP_IDENTITY_SPLIT_CONFLICT')
  if old:c.execute('UPDATE whatsapp_identity_links SET last_seen_at=? WHERE link_id=?',(n,old[0]['link_id']))
  else:c.execute("INSERT INTO whatsapp_identity_links(link_id,organization_id,workspace_id,platform_id,contact_id,lid_canonical,jid_canonical,evidence_source,verification_status,first_seen_at,last_seen_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,'observed',?,?,'{}')",('wil_'+uuid.uuid4().hex,a['organization_id'],a['workspace_id'],pid,cid,lid['canonicalValue'],jid['canonicalValue'],evidence,n,n))
 return rows

def _record_conversation_alias(c,a,platform,conversation,cid,ext,n,evidence='observed-conversation-id'):
 typ='whatsapp_lid' if str(ext).endswith('@lid') else 'whatsapp_jid' if str(ext).endswith('@c.us') else 'external_conversation_id'
 old=c.execute('SELECT conversation_id,contact_id FROM conversation_external_aliases WHERE organization_id=? AND channel_account_id=? AND alias_value=?',(a['organization_id'],conversation['channel_account_id'],ext)).fetchone()
 if old and (old['conversation_id']!=conversation['conversation_id'] or old['contact_id']!=cid):raise ValueError('CONVERSATION_ALIAS_CONFLICT')
 c.execute("INSERT INTO conversation_external_aliases(alias_id,organization_id,workspace_id,channel_account_id,platform_id,conversation_id,contact_id,alias_type,alias_value,evidence_source,first_seen_at,last_seen_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?, '{}') ON CONFLICT(organization_id,channel_account_id,alias_value) DO UPDATE SET last_seen_at=excluded.last_seen_at",('cxa_'+uuid.uuid4().hex,a['organization_id'],a['workspace_id'],conversation['channel_account_id'],platform['platform_id'],conversation['conversation_id'],cid,typ,ext,evidence,n,n))

def _create_conversation(c,a,account,platform,cid,iid,ext,n):
 old=c.execute('SELECT * FROM conversations WHERE organization_id=? AND channel_account_id=? AND external_conversation_id=?',(a['organization_id'],account['channel_account_id'],ext)).fetchone()
 if old:
  if old['contact_id']!=cid:raise ValueError('CONVERSATION_CONTACT_CONFLICT')
  _record_conversation_alias(c,a,platform,old,cid,ext,n);return old,False
 old=c.execute("SELECT * FROM conversations WHERE organization_id=? AND channel_account_id=? AND contact_id=? AND conversation_type='direct'",(a['organization_id'],account['channel_account_id'],cid)).fetchone()
 if old:
  _record_conversation_alias(c,a,platform,old,cid,ext,n,'contact-identity-alias');return old,False
 ct=c.execute('SELECT source_id FROM contacts WHERE contact_id=?',(cid,)).fetchone();vid='cnv_'+uuid.uuid4().hex
 c.execute("INSERT INTO conversations(conversation_id,organization_id,workspace_id,team_id,channel_account_id,platform_id,contact_id,contact_identity_id,external_conversation_id,conversation_type,status,assigned_user_id,source_id,last_collected_at,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'direct','active',?,?,?,'{}',?,?)",(vid,a['organization_id'],a['workspace_id'],a['team_id'],account['channel_account_id'],platform['platform_id'],cid,iid,ext,a['user_id'],ct['source_id'],n,n,n))
 row=c.execute('SELECT * FROM conversations WHERE conversation_id=?',(vid,)).fetchone();_record_conversation_alias(c,a,platform,row,cid,ext,n);return row,True

def _transfer_candidates_in_tx(c,a,channel_account_id,conversation=None,limit=20):
 """返回当前事务内、当前作用域内的非敏感转交摘要。"""
 rows=c.execute("""SELECT t.transfer_id,t.contact_id,t.status,t.version,t.transfer_method,t.requested_by,t.requested_at,t.expires_at,t.matched_identity_id,ct.display_name AS contact_name
  FROM contact_transfers t JOIN contacts ct ON ct.contact_id=t.contact_id
  WHERE t.organization_id=? AND t.workspace_id=? AND t.team_id=? AND t.to_channel_account_id=?
   AND t.status IN ('pending','matched') AND (t.expires_at IS NULL OR t.expires_at>?)
  ORDER BY CASE t.status WHEN 'matched' THEN 0 ELSE 1 END,t.requested_at DESC,t.transfer_id DESC LIMIT ?""",
  (a['organization_id'],a['workspace_id'],a['team_id'],channel_account_id,now_ms(),max(1,min(int(limit),20)))).fetchall()
 current_contact=conversation['contact_id'] if conversation else None
 return [{'transferId':r['transfer_id'],'contactId':r['contact_id'],'contactName':r['contact_name'],'status':r['status'],'version':r['version'],'transferMethod':r['transfer_method'],'requestedBy':r['requested_by'],'requestedAt':r['requested_at'],'expiresAt':r['expires_at'],'matchedIdentityId':r['matched_identity_id'],'alreadyMatched':bool(current_contact and current_contact==r['contact_id']),'suggestedAction':'confirm' if r['status']=='matched' else 'match'} for r in rows]

def resolve_follow_ups(db,a,p):
 # JUBAOPEN_THREADS_FOLLOWUP_PLATFORM_PREFLIGHT_210_3_5
 # Threads 210.3.4 的 _platform() 已具备幂等创建能力；
 # 在旧 resolver 读取平台前，先用写事务完成平台预检。
 with db.tx(True) as _juba_platform_tx:
  _platform(_juba_platform_tx,p)
 """Resolve visible conversations without assuming that WA @c.us and @lid are the same key."""
 if not isinstance(p,dict):return _err('INVALID_REQUEST','请求正文必须是对象')
 code=str(p.get('platformCode') or '').strip().lower()
 aid=str(p.get('channelAccountId') or '').strip()
 raw=p.get('externalConversationIds')
 if code not in ('whatsapp','telegram','instagram','messenger','facebook'):
  return _err('PLATFORM_REQUIRED','platformCode 无效')
 if not aid:return _err('CHANNEL_ACCOUNT_REQUIRED','channelAccountId 必填')
 if not isinstance(raw,list):return _err('CONVERSATION_IDS_REQUIRED','externalConversationIds 必须是数组')
 ids=[]
 for value in raw:
  value=str(value or '').strip()
  if not value or len(value)>500:continue
  if value not in ids:ids.append(value)
 if not ids:return _ok(items=[])
 if len(ids)>100:return _err('TOO_MANY_CONVERSATIONS','单次最多解析 100 个会话')
 with db.tx(False) as c:
  platform=_platform(c,{'platformCode':code})
  if not platform:return _err('PLATFORM_NOT_FOUND','平台未启用',404)
  account=_account_allowed(c,a,aid,platform['platform_id'])
  if not account:return _err('ACCOUNT_NOT_AUTHORIZED','渠道账号未授权',403)
  prefix={'instagram':'ig','whatsapp':'wa','telegram':'tg','facebook':'facebook','messenger':'messenger'}[code]+':'
  request_aliases={}
  alias_owner={}
  for requested in ids:
   token=requested.split(':',1)[1] if requested.startswith(prefix) else requested
   values=[]
   for candidate in (requested,token,prefix+token):
    if candidate and candidate not in values:values.append(candidate)
   request_aliases[requested]=values
   for candidate in values:alias_owner.setdefault(candidate,[]).append(requested)
  all_aliases=list(alias_owner)
  marks=','.join('?' for _ in all_aliases)
  base_params=(a['organization_id'],a['workspace_id'],a['team_id'],aid,platform['platform_id'])
  exact_rows=c.execute(f"""SELECT v.external_conversation_id,v.conversation_id,v.contact_id,
    ct.next_follow_up_at,ct.business_json,ct.version,v.updated_at
   FROM conversations v JOIN contacts ct ON ct.contact_id=v.contact_id
   WHERE v.organization_id=? AND v.workspace_id=? AND v.team_id=?
    AND v.channel_account_id=? AND v.platform_id=?
    AND ct.deleted_at IS NULL AND NOT EXISTS(SELECT 1 FROM follow_up_notifications fn WHERE fn.contact_id=ct.contact_id AND fn.follow_up_at=ct.next_follow_up_at AND fn.status='completed') AND v.external_conversation_id IN ({marks})
   ORDER BY v.updated_at DESC,v.conversation_id""",(*base_params,*all_aliases)).fetchall()
  matches={}
  methods={}
  if code=='whatsapp':
   alias_rows=c.execute(f'''SELECT x.alias_value,v.external_conversation_id,v.conversation_id,v.contact_id,ct.next_follow_up_at,ct.business_json,ct.version,v.updated_at
    FROM conversation_external_aliases x JOIN conversations v ON v.conversation_id=x.conversation_id JOIN contacts ct ON ct.contact_id=v.contact_id
    WHERE x.organization_id=? AND x.workspace_id=? AND x.channel_account_id=? AND x.platform_id=? AND x.alias_value IN ({marks})
     AND v.team_id=? AND ct.deleted_at IS NULL AND NOT EXISTS(SELECT 1 FROM follow_up_notifications fn WHERE fn.contact_id=ct.contact_id AND fn.follow_up_at=ct.next_follow_up_at AND fn.status='completed') ORDER BY v.updated_at DESC''',(a['organization_id'],a['workspace_id'],aid,platform['platform_id'],*all_aliases,a['team_id'])).fetchall()
   for row in alias_rows:
    for requested in alias_owner.get(row['alias_value'],()):
     if requested not in matches:matches[requested]=row;methods[requested]='conversation_external_alias'
  for row in exact_rows:
   for requested in alias_owner.get(row['external_conversation_id'],()):
    if requested not in matches:
     matches[requested]=row;methods[requested]='external_conversation_id'
  # WhatsApp Web may expose a phone JID while an existing conversation is keyed by LID
  # (or vice versa). Resolve that mismatch only through an identity already bound to the
  # same contact; never infer equivalence from the unrelated numeric local parts.
  if code=='whatsapp':
   identity_requests={}
   for requested in ids:
    if requested in matches:continue
    value=requested.removeprefix('wa:').removeprefix('whatsapp:')
    typ='whatsapp_lid' if value.lower().endswith('@lid') else 'whatsapp_jid'
    normalized_type,_,canonical=normalize_identity('whatsapp',typ,value)
    if canonical:identity_requests.setdefault((normalized_type,canonical),[]).append(requested)
   if identity_requests:
    canonicals=list(dict.fromkeys(x[1] for x in identity_requests))
    imarks=','.join('?' for _ in canonicals)
    identities=c.execute(f"""SELECT contact_id,identity_type,canonical_value
     FROM contact_identities WHERE organization_id=? AND workspace_id=? AND platform_id=?
      AND verification_status IN ('unverified','observed','verified') AND canonical_value IN ({imarks})""",
     (a['organization_id'],a['workspace_id'],platform['platform_id'],*canonicals)).fetchall()
    contact_requests={}
    for identity in identities:
     for requested in identity_requests.get((identity['identity_type'],identity['canonical_value']),()):
      contact_requests.setdefault(identity['contact_id'],[]).append(requested)
    if contact_requests:
     contact_ids=list(contact_requests)
     cmarks=','.join('?' for _ in contact_ids)
     alias_rows=c.execute(f"""SELECT v.external_conversation_id,v.conversation_id,v.contact_id,
       ct.next_follow_up_at,ct.business_json,ct.version,v.updated_at
      FROM conversations v JOIN contacts ct ON ct.contact_id=v.contact_id
      WHERE v.organization_id=? AND v.workspace_id=? AND v.team_id=?
       AND v.channel_account_id=? AND v.platform_id=?
       AND ct.deleted_at IS NULL AND NOT EXISTS(SELECT 1 FROM follow_up_notifications fn WHERE fn.contact_id=ct.contact_id AND fn.follow_up_at=ct.next_follow_up_at AND fn.status='completed') AND v.contact_id IN ({cmarks})
      ORDER BY v.updated_at DESC,v.conversation_id""",(*base_params,*contact_ids)).fetchall()
     for row in alias_rows:
      for requested in contact_requests.get(row['contact_id'],()):
       if requested not in matches:
        matches[requested]=row;methods[requested]='contact_identity_alias'
     # A trusted visible-row identity may belong to a contact that has not yet created a
     # conversation under this channel account.  Resolve the follow-up directly, but only
     # inside the actor's organization/workspace and team (or explicit team-share) scope.
     unresolved_contacts={cid:reqs for cid,reqs in contact_requests.items() if any(x not in matches for x in reqs)}
     if unresolved_contacts:
      direct_ids=list(unresolved_contacts)
      dmarks=','.join('?' for _ in direct_ids)
      direct_rows=c.execute(f"""SELECT ct.contact_id,ct.next_follow_up_at,ct.business_json,ct.version,ct.updated_at
       FROM contacts ct WHERE ct.organization_id=? AND ct.workspace_id=? AND ct.deleted_at IS NULL AND NOT EXISTS(SELECT 1 FROM follow_up_notifications fn WHERE fn.contact_id=ct.contact_id AND fn.follow_up_at=ct.next_follow_up_at AND fn.status='completed')
        AND ct.contact_id IN ({dmarks})
        AND (ct.team_id=? OR EXISTS(SELECT 1 FROM contact_team_access x
         WHERE x.organization_id=ct.organization_id AND x.workspace_id=ct.workspace_id
          AND x.contact_id=ct.contact_id AND x.team_id=? AND x.revoked_at IS NULL))""",
       (a['organization_id'],a['workspace_id'],*direct_ids,a['team_id'],a['team_id'])).fetchall()
      for contact in direct_rows:
       for requested in unresolved_contacts.get(contact['contact_id'],()):
        if requested in matches:continue
        row=dict(contact);row.update({'external_conversation_id':requested,'conversation_id':None})
        matches[requested]=row;methods[requested]='contact_identity'
  out=[]
  for requested in ids:
   row=matches.get(requested)
   if not row or row['next_follow_up_at'] is None:continue
   try:reason=str((json.loads(row['business_json'] or '{}') or {}).get('nextFollowUpReason') or '')[:500]
   except Exception:reason=''
   canonical=row['external_conversation_id']
   out.append({'externalConversationId':requested,'requestedExternalConversationId':requested,
    'canonicalExternalConversationId':canonical,'aliases':list(dict.fromkeys([requested,canonical])),
    'matchedBy':methods.get(requested,'external_conversation_id'),'conversationId':row['conversation_id'],
    'contactId':row['contact_id'],'nextFollowUpAt':int(row['next_follow_up_at']),
    'nextFollowUpReason':reason,'contactVersion':int(row['version'] or 0)})
  return _ok(items=out)

def _meta_thread_token(code,external_conversation_id):
 code=str(code or '').strip().lower();ext=str(external_conversation_id or '').strip()
 if code not in ('facebook','messenger'):return ''
 prefix=code+':'
 if not ext.startswith(prefix):return ''
 token=ext[len(prefix):].strip()
 return token if token.isdigit() and 5<=len(token)<=30 else ''

def _repair_legacy_meta_thread_identity(c,a,code,pid,old,bound_identity,typ,canonical,n):
 # Narrow repair: the bound observed identity must exactly equal the normalized Meta thread token.
 thread_token=_meta_thread_token(code,old['external_conversation_id'])
 if not thread_token or typ!='facebook_user_id' or not canonical or canonical==thread_token:return None
 if not bound_identity or bound_identity['identity_type']!='facebook_user_id':return None
 if bound_identity['canonical_value']!=thread_token:return None
 if bound_identity['verification_status'] not in ('observed','unverified'):return None
 if bound_identity['contact_id']!=old['contact_id'] or bound_identity['platform_id']!=pid:return None
 if old['organization_id']!=a['organization_id'] or old['workspace_id']!=a['workspace_id'] or old['team_id']!=a['team_id']:return None
 targets=c.execute("""SELECT contact_identity_id,contact_id,platform_id,identity_type,canonical_value,verification_status
  FROM contact_identities WHERE organization_id=? AND contact_id=? AND platform_id=? AND identity_type=? AND canonical_value=?
  AND verification_status IN ('unverified','observed','verified') LIMIT 2""",
  (a['organization_id'],old['contact_id'],pid,typ,canonical)).fetchall()
 if len(targets)!=1:return None
 target=targets[0]
 changed=c.execute("""UPDATE conversations SET contact_identity_id=?,updated_at=?
  WHERE conversation_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND contact_id=? AND platform_id=? AND contact_identity_id=?""",
  (target['contact_identity_id'],n,old['conversation_id'],a['organization_id'],a['workspace_id'],a['team_id'],old['contact_id'],pid,bound_identity['contact_identity_id']))
 if changed.rowcount!=1:return None
 c.execute("""INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at)
  VALUES(?,?,?,?,?,?,?,?,?,?)""",(a['workspace_id'],a['user_id'],a.get('device_id'),'repair_meta_e2ee_identity','conversation',old['conversation_id'],
  dumps({'contactIdentityId':bound_identity['contact_identity_id'],'canonicalValue':bound_identity['canonical_value'],'externalConversationId':old['external_conversation_id']}),
  dumps({'contactIdentityId':target['contact_identity_id'],'canonicalValue':target['canonical_value'],'externalConversationId':old['external_conversation_id']}),
  '修复旧版将 Meta E2EE 线程号误存为联系人身份',n))
 return target

def _identity_public(row):
 if not row:return None
 return {'contactIdentityId':row['contact_identity_id'],'identityType':row['identity_type'],'canonicalValue':row['canonical_value'],'verificationStatus':row['verification_status']}

def _repair_instagram_identity_upgrade(c,a,pid,old,bound_identity,typ,raw,canonical,identity,n):
 """Upgrade username to numeric IG identity using exact same-header alias evidence."""
 if typ!='instagram_user_id' or not canonical or not bound_identity:return None,None
 if bound_identity['identity_type']!='instagram_username':return None,None
 if bound_identity['verification_status'] not in ('unverified','observed','verified'):return None,None
 if bound_identity['contact_id']!=old['contact_id'] or bound_identity['platform_id']!=pid:return None,None
 if old['organization_id']!=a['organization_id'] or old['workspace_id']!=a['workspace_id'] or old['team_id']!=a['team_id']:return None,None
 aliases=identity.get('aliases') if isinstance(identity,dict) else None
 aliases=aliases if isinstance(aliases,list) else []
 matched=False
 for alias in aliases[:8]:
  if not isinstance(alias,dict) or alias.get('evidence')!='same-central-header-react-object':continue
  at,ar,ac=normalize_identity('instagram',alias.get('identityType'),alias.get('identityValue'))
  if at=='instagram_username' and ac and ac==bound_identity['canonical_value']:
   matched=True;break
 if not matched:return None,'EXACT_USERNAME_ALIAS_MISSING'
 rows=c.execute("""SELECT contact_identity_id,contact_id,platform_id,identity_type,canonical_value,verification_status
  FROM contact_identities WHERE organization_id=? AND workspace_id=? AND platform_id=? AND identity_type=? AND canonical_value=? LIMIT 2""",
  (a['organization_id'],a['workspace_id'],pid,typ,canonical)).fetchall()
 if len(rows)>1:return None,'NUMERIC_ID_NOT_UNIQUE'
 if rows and rows[0]['contact_id']!=old['contact_id']:return None,'NUMERIC_ID_BOUND_TO_OTHER_CONTACT'
 if rows:target=rows[0]
 else:
  iid='ci_'+uuid.uuid4().hex
  c.execute("""INSERT INTO contact_identities(contact_identity_id,organization_id,workspace_id,contact_id,platform_id,identity_type,identity_value,canonical_value,verification_status,is_primary,first_seen_at,last_seen_at,metadata_json)
   VALUES(?,?,?,?,?,?,?,?,'observed',0,?,?,?)""",
   (iid,a['organization_id'],a['workspace_id'],old['contact_id'],pid,typ,raw,canonical,n,n,dumps({'createdBy':'collector.instagram_identity_upgrade','evidence':'same-central-header-react-object'})))
  target=c.execute("""SELECT contact_identity_id,contact_id,platform_id,identity_type,canonical_value,verification_status
   FROM contact_identities WHERE contact_identity_id=?""",(iid,)).fetchone()
 changed=c.execute("""UPDATE conversations SET contact_identity_id=?,updated_at=?
  WHERE conversation_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND contact_id=? AND platform_id=? AND contact_identity_id=?""",
  (target['contact_identity_id'],n,old['conversation_id'],a['organization_id'],a['workspace_id'],a['team_id'],old['contact_id'],pid,bound_identity['contact_identity_id']))
 if changed.rowcount!=1:return None,'CONVERSATION_CHANGED_DURING_REPAIR'
 c.execute("""INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at)
  VALUES(?,?,?,?,?,?,?,?,?,?)""",
  (a['workspace_id'],a['user_id'],a.get('device_id'),'repair_instagram_identity_upgrade','conversation',old['conversation_id'],dumps(_identity_public(bound_identity)),dumps(_identity_public(target)),'Instagram 中央会话 Header 将同一用户名解析为稳定数字用户 ID',n))
 return target,None

def _instagram_same_contact_alias(c,a,pid,old,typ,canonical):
 if typ!='instagram_username' or not canonical:return None
 rows=c.execute("""SELECT contact_identity_id,contact_id,platform_id,identity_type,canonical_value,verification_status
  FROM contact_identities WHERE organization_id=? AND workspace_id=? AND platform_id=? AND identity_type=? AND canonical_value=?
  AND verification_status IN ('unverified','observed','verified') LIMIT 2""",
  (a['organization_id'],a['workspace_id'],pid,typ,canonical)).fetchall()
 return rows[0] if len(rows)==1 and rows[0]['contact_id']==old['contact_id'] else None

def resolve_conversation(db,a,p):
 aid=str(p.get('channelAccountId') or '');ext=str(p.get('externalConversationId') or '').strip();cid=str(p.get('contactId') or '').strip();identity=p.get('contactIdentity') or {};account_identity=p.get('accountIdentity') or {}
 if not aid or not ext:return _err('CONVERSATION_REQUIRED','channelAccountId、externalConversationId 必填')
 n=now_ms()
 with db.tx() as c:
  platform=_platform(c,p)
  if not platform:return _err('PLATFORM_NOT_FOUND','平台不存在或未启用',404)
  pid=platform['platform_id'];code=platform['platform_code'];account_typ,account_raw,account_key=normalize_identity(code,account_identity.get('identityType'),account_identity.get('identityValue'))
  identity_items=_trusted_contact_identities(code,identity,p.get('contactIdentityAliases'))
  identity_matches=_identity_matches(c,a,pid,identity_items)
  matched_contact_ids={r['contact_id'] for r in identity_matches}
  if len(matched_contact_ids)>1:return _err('WHATSAPP_IDENTITY_SPLIT_CONFLICT','提交的可信身份分别属于多个联系人，事务已回滚',409,contactIds=sorted(matched_contact_ids))
  if not account_key:return _err('STABLE_ACCOUNT_IDENTITY_REQUIRED','当前平台登录账号稳定身份缺失',409)
  binding=c.execute("SELECT * FROM device_channel_account_bindings WHERE device_id=? AND user_id=? AND channel_account_id=? AND platform_id=? AND external_account_key=? AND status='active'",(a['device_id'],a['user_id'],aid,pid,account_key)).fetchone()
  if not binding:return _err('ACCOUNT_BINDING_REQUIRED','当前插件实例尚未验证该平台账号',403)
  account=_account_allowed(c,a,aid,pid)
  if not account:return _err('ACCOUNT_NOT_AUTHORIZED','渠道账号授权已失效',403)
  ident=c.execute("SELECT 1 FROM channel_account_identities WHERE channel_account_id=? AND platform_id=? AND identity_type=? AND canonical_value=? AND status='active' AND (valid_from IS NULL OR valid_from<=?) AND (valid_to IS NULL OR valid_to>=?)",(aid,pid,account_typ,account_key,n,n)).fetchone()
  if not ident:return _err('ACCOUNT_IDENTITY_CHANGED','平台账号身份验证已失效，请重新检测',403)
  c.execute('UPDATE device_channel_account_bindings SET last_verified_at=? WHERE binding_id=?',(n,binding['binding_id']))
  if account['contact_entry_policy']=='disabled' or not account['collection_enabled']:
   return _entry(account,'disabled',code='COLLECTION_DISABLED')
  old=c.execute('SELECT * FROM conversations WHERE organization_id=? AND channel_account_id=? AND external_conversation_id=?',(a['organization_id'],aid,ext)).fetchone()
  if old:
   if cid and old['contact_id']!=cid:return _err('CONVERSATION_CONTACT_CONFLICT','会话已经绑定其他客户',409)
   # Never trust a route hit alone: the submitted peer identity must still be
   # the active identity already bound to this conversation. This blocks stale
   # Meta/Telegram/WA headers during SPA navigation from overwriting profiles.
   typ,raw,canonical=normalize_identity(code,identity.get('identityType'),identity.get('identityValue'))
   if not canonical or not old['contact_identity_id']:
    return _err('CONVERSATION_IDENTITY_REQUIRED','已有会话必须提供稳定联系人身份',409)
   bound_identity=c.execute("SELECT contact_identity_id,contact_id,platform_id,identity_type,canonical_value,verification_status FROM contact_identities WHERE contact_identity_id=? AND organization_id=?",(old['contact_identity_id'],a['organization_id'])).fetchone()
   exact=bool(bound_identity and bound_identity['verification_status'] in ('unverified','observed','verified') and bound_identity['contact_id']==old['contact_id'] and bound_identity['platform_id']==pid and bound_identity['identity_type']==typ and bound_identity['canonical_value']==canonical)
   if code=='whatsapp' and identity_items and (not matched_contact_ids or matched_contact_ids=={old['contact_id']}):
    bound_key=(bound_identity['identity_type'],bound_identity['canonical_value']) if bound_identity else None
    submitted={(x['identityType'],x['canonicalValue']) for x in identity_items}
    if bound_key in submitted or matched_contact_ids=={old['contact_id']}:
     rows=_ensure_contact_identities(c,a,pid,old['contact_id'],identity_items,n);primary=next((r for r in rows if r['identity_type']==typ and r['canonical_value']==canonical),None);exact=True
     if primary:c.execute('UPDATE conversations SET contact_identity_id=?,updated_at=? WHERE conversation_id=?',(primary['contact_identity_id'],n,old['conversation_id']))
     _record_conversation_alias(c,a,platform,old,old['contact_id'],ext,n)
   if not exact:
    repaired=_repair_legacy_meta_thread_identity(c,a,code,pid,old,bound_identity,typ,canonical,n)
    if repaired:
     old=c.execute('SELECT * FROM conversations WHERE conversation_id=?',(old['conversation_id'],)).fetchone();bound_identity=repaired;exact=True
   repair_block=None
   if not exact and code=='instagram':
    repaired,repair_block=_repair_instagram_identity_upgrade(c,a,pid,old,bound_identity,typ,raw,canonical,identity,n)
    if repaired:
     old=c.execute('SELECT * FROM conversations WHERE conversation_id=?',(old['conversation_id'],)).fetchone()
     bound_identity=repaired;exact=True
    elif bound_identity and bound_identity['identity_type']=='instagram_user_id' and _instagram_same_contact_alias(c,a,pid,old,typ,canonical):
     # Temporary probe fallback to username: accept only an exact alias already owned by this contact.
     exact=True
   if not exact:
    detail={'reason':'BOUND_IDENTITY_NOT_EQUIVALENT','platformCode':code,'externalConversationId':ext,'conversationId':old['conversation_id'],'contactId':old['contact_id'],'boundIdentity':_identity_public(bound_identity),'observedIdentity':{'identityType':typ,'canonicalValue':canonical},'repairBlockedBy':repair_block}
    # Only WhatsApp may alternate between an already-verified @lid and @c.us identity.
    wa_types={'whatsapp_jid','whatsapp_lid'}
    if code!='whatsapp' or not bound_identity or bound_identity['identity_type'] not in wa_types or typ not in wa_types or bound_identity['identity_type']==typ:
     return _err('CONVERSATION_IDENTITY_MISMATCH','当前会话身份与已绑定客户不一致，已阻止资料更新',409,identityMismatch=detail)
    alternates=c.execute("SELECT contact_identity_id,contact_id FROM contact_identities WHERE organization_id=? AND platform_id=? AND identity_type=? AND canonical_value=? AND verification_status IN ('observed','verified') LIMIT 2",(a['organization_id'],pid,typ,canonical)).fetchall()
    if len(alternates)!=1 or alternates[0]['contact_id']!=old['contact_id']:
     detail['reason']='WHATSAPP_ALTERNATE_NOT_UNIQUE_OR_DIFFERENT_CONTACT';detail['alternateCount']=len(alternates)
     return _err('CONVERSATION_IDENTITY_MISMATCH','当前会话身份与已绑定客户不一致，已阻止资料更新',409,identityMismatch=detail)
    alternate=alternates[0]
    c.execute('UPDATE conversations SET contact_identity_id=?,updated_at=? WHERE conversation_id=?',(alternate['contact_identity_id'],n,old['conversation_id']))
    old=c.execute('SELECT * FROM conversations WHERE conversation_id=?',(old['conversation_id'],)).fetchone()
    bound_identity=c.execute("SELECT contact_identity_id,contact_id,platform_id,identity_type,canonical_value,verification_status FROM contact_identities WHERE contact_identity_id=?",(old['contact_identity_id'],)).fetchone()
   # Existing conversations may refresh the profile only after the identity
   # guard succeeds. Empty/invalid values preserve the stored profile.
   # Existing conversations must still refresh the contact's observed profile,
   # especially Telegram avatars. Empty/invalid avatar values are sanitized to
   # an empty string and therefore preserve the currently stored avatar.
   cid=old['contact_id']
   observed_name=sanitize_observed_name(identity.get('displayName'))
   observed_phone=str(identity.get('phone') or '')[:80]
   avatar=sanitize_avatar(identity.get('avatarUrl'))
   c.execute("UPDATE contacts SET display_name=CASE WHEN ?<>'' THEN ? ELSE display_name END,observed_phone=CASE WHEN ?<>'' THEN ? ELSE observed_phone END,avatar_url=CASE WHEN ?<>'' THEN ? ELSE avatar_url END,last_observed_device_id=?,last_observed_at=?,last_seen_at=?,updated_at=? WHERE contact_id=? AND organization_id=? AND workspace_id=? AND deleted_at IS NULL",(observed_name,observed_name,observed_phone,observed_phone,avatar,avatar,a['device_id'],n,n,n,cid,a['organization_id'],a['workspace_id']))
   if old['contact_identity_id']:
    c.execute('UPDATE contact_identities SET last_seen_at=? WHERE contact_identity_id=?',(n,old['contact_identity_id']))
   c.execute('UPDATE conversations SET last_collected_at=?,updated_at=? WHERE conversation_id=?',(n,n,old['conversation_id']))
   resolved_conversation=dict(c.execute('SELECT * FROM conversations WHERE conversation_id=?',(old['conversation_id'],)).fetchone());transfer_candidates=_transfer_candidates_in_tx(c,a,aid,resolved_conversation)
   return _entry(account,'registered',contactId=cid,contactIdentityId=old['contact_identity_id'],conversation=resolved_conversation,created=False,transferCandidates=transfer_candidates,transferCandidateCount=len(transfer_candidates))
  typ,raw,canonical=normalize_identity(code,identity.get('identityType'),identity.get('identityValue'))
  iid=None;ct=None
  if matched_contact_ids:
   cid=next(iter(matched_contact_ids));ir=next(r for r in identity_matches if r['contact_id']==cid);iid=ir['contact_identity_id'];ct=c.execute("SELECT * FROM contacts WHERE contact_id=? AND organization_id=? AND deleted_at IS NULL",(cid,a['organization_id'])).fetchone()
   if not ct:return _err('IDENTITY_SCOPE_CONFLICT','平台身份属于无效或已删除客户',409,entryState='identity_conflict')
   if ct['workspace_id']!=a['workspace_id']:return _entry(account,'existing_other_workspace',code='CROSS_WORKSPACE_IDENTITY',sameWorkspace=False,canReuse=False,canRequestReview=True,maskedContactId=cid[:8])
  if cid:
   ct=c.execute("SELECT * FROM contacts ct WHERE ct.contact_id=? AND ct.organization_id=? AND ct.workspace_id=? AND ct.deleted_at IS NULL AND (ct.team_id=? OR EXISTS(SELECT 1 FROM contact_team_access x WHERE x.contact_id=ct.contact_id AND x.team_id=? AND x.revoked_at IS NULL))",(cid,a['organization_id'],a['workspace_id'],a['team_id'],a['team_id'])).fetchone()
   if not ct:return _err('CONTACT_SCOPE_INVALID','联系人不存在或不属于当前作用域',404)
   if canonical:
    ir=c.execute('SELECT * FROM contact_identities WHERE contact_id=? AND platform_id=? AND identity_type=? AND canonical_value=?',(cid,pid,typ,canonical)).fetchone();iid=ir['contact_identity_id'] if ir else None
  elif canonical:
   ir=c.execute('SELECT * FROM contact_identities WHERE organization_id=? AND platform_id=? AND identity_type=? AND canonical_value=?',(a['organization_id'],pid,typ,canonical)).fetchone()
   if ir:
    cid=ir['contact_id'];iid=ir['contact_identity_id'];ct=c.execute("SELECT * FROM contacts WHERE contact_id=? AND organization_id=? AND deleted_at IS NULL",(cid,a['organization_id'])).fetchone()
    if not ct:return _err('IDENTITY_SCOPE_CONFLICT','平台身份属于无效或已删除客户',409,entryState='identity_conflict')
    if ct['workspace_id']!=a['workspace_id']:return _entry(account,'existing_other_workspace',code='CROSS_WORKSPACE_IDENTITY',sameWorkspace=False,canReuse=False,canRequestReview=True,maskedContactId=cid[:8])
    if ct['team_id']!=a['team_id']:
     from V221_identity_service import grant_access_in_tx
     grant_access_in_tx(c,a,ct,a['team_id'],'edit','identity_reuse','同平台稳定身份自动复用')
  if not ct:
   state='unmatched_transfer' if account['contact_entry_policy']=='existing_contact_first' else 'unregistered'
   transfer_candidates=_transfer_candidates_in_tx(c,a,aid)
   return _entry(account,state,stableIdentity=bool(canonical),transferCandidates=transfer_candidates,transferCandidateCount=len(transfer_candidates),**_entry_configuration(c,a,account))
  if not iid:
   ir=c.execute('SELECT contact_identity_id FROM contact_identities WHERE contact_id=? AND platform_id=? ORDER BY is_primary DESC,first_seen_at LIMIT 1',(cid,pid)).fetchone();iid=ir['contact_identity_id'] if ir else None
  if iid:c.execute('UPDATE contact_identities SET last_seen_at=? WHERE contact_identity_id=?',(n,iid))
  observed_name=sanitize_observed_name(identity.get('displayName'));observed_phone=str(identity.get('phone') or '')[:80];avatar=sanitize_avatar(identity.get('avatarUrl'))
  c.execute("UPDATE contacts SET display_name=CASE WHEN ?<>'' THEN ? ELSE display_name END,observed_phone=CASE WHEN ?<>'' THEN ? ELSE observed_phone END,avatar_url=CASE WHEN ?<>'' THEN ? ELSE avatar_url END,last_observed_device_id=?,last_observed_at=?,last_seen_at=?,updated_at=? WHERE contact_id=?",(observed_name,observed_name,observed_phone,observed_phone,avatar,avatar,a['device_id'],n,n,n,cid))
  if code=='whatsapp' and identity_items:
   rows=_ensure_contact_identities(c,a,pid,cid,identity_items,n)
   primary=next((r for r in rows if r['identity_type']==typ and r['canonical_value']==canonical),None)
   if primary:iid=primary['contact_identity_id']
  conv,created=_create_conversation(c,a,account,platform,cid,iid,ext,n)
  transfer_candidates=_transfer_candidates_in_tx(c,a,aid,conv)
  return _entry(account,'registered',contactId=cid,contactIdentityId=iid,conversation=dict(conv),created=created,transferCandidates=transfer_candidates,transferCandidateCount=len(transfer_candidates))


def _collection_generation(row):
 try:meta=json.loads(row['metadata_json'] or '{}')
 except Exception:meta={}
 try:return max(1,int(meta.get('collectionGeneration') or 1)),meta
 except (TypeError,ValueError):return 1,meta

def collection_state(db,a,conversation_id):
 with db.tx(False) as c:
  row=c.execute("SELECT * FROM conversations WHERE conversation_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND assigned_user_id=?",(conversation_id,a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'])).fetchone()
  if not row:return _err('CONVERSATION_SCOPE_INVALID','会话不存在或不属于当前采集范围',404)
  if not _account_allowed(c,a,row['channel_account_id'],row['platform_id']):return _err('ACCOUNT_NOT_AUTHORIZED','渠道账号未授权',403)
  if not c.execute("SELECT 1 FROM device_channel_account_bindings WHERE device_id=? AND user_id=? AND channel_account_id=? AND platform_id=? AND status='active'",(a['device_id'],a['user_id'],row['channel_account_id'],row['platform_id'])).fetchone():return _err('ACCOUNT_BINDING_REQUIRED','当前设备未绑定该渠道账号',403)
  generation,meta=_collection_generation(row)
  return _ok(conversationId=conversation_id,collectionGeneration=generation,messageCount=int(row['message_count'] or 0),recollectRequestedAt=meta.get('recollectRequestedAt'))

def collect_messages(db,a,p):
 if not isinstance(p,dict):return _err('INVALID_REQUEST','请求正文必须是对象')
 items=p.get('messages')
 if not isinstance(items,list) or not items or len(items)>100:return _err('INVALID_BATCH','messages 必须是 1 至 100 条的数组')
 if len(json.dumps(p,ensure_ascii=False).encode())>524288:return _err('REQUEST_TOO_LARGE','消息批次超过 512KB',413)
 out=[]
 for item in items:
  if not isinstance(item,dict):out.append({'ok':False,'code':'MESSAGE_INVALID'});continue
  try:out.append(_collect_one(db,a,item))
  except Exception as ex:
   LOG.exception('collector message write failed: %s',str(ex)[:200])
   out.append({'ok':False,'code':'MESSAGE_INTERNAL_ERROR','detail':str(ex)[:300]})
 duplicated=sum(bool(x.get('duplicate')) for x in out);accepted=sum(bool(x.get('ok')) and not x.get('duplicate') for x in out)
 rejected_codes={}
 for x in out:
  if not x.get('ok'):
   code=str(x.get('code') or 'UNKNOWN');rejected_codes[code]=rejected_codes.get(code,0)+1
 translation_received=sum(bool((x.get('metadata') or {}).get('translation')) for x in items if isinstance(x,dict) and isinstance(x.get('metadata'),dict))
 translation_enriched=sum(bool(x.get('translationEnriched')) for x in out)
 wa_items=[x for x in items if isinstance(x,dict) and str((x.get('metadata') or {}).get('platformCode') or '').lower()=='whatsapp']
 if wa_items:
  import hashlib
  conversation_fingerprints=sorted(set(hashlib.sha256(str(x.get('conversationId') or 'unregistered').encode()).hexdigest()[:12] for x in wa_items))[:10]
  probe_counts=[int(((x.get('metadata') or {}).get('waTranslationDiagnostic') or {}).get('probeTranslationCount') or 0) for x in wa_items]
  normalized_counts=[int(((x.get('metadata') or {}).get('waTranslationDiagnostic') or {}).get('normalizedTranslationCount') or 0) for x in wa_items]
  LOG.info('WA_TRANSLATION_DIAGNOSTIC version=210.2.75 conversations=%s messages=%d received=%d probeMax=%d normalizedMax=%d enriched=%d accepted=%d duplicated=%d rejected=%d',','.join(conversation_fingerprints),len(wa_items),translation_received,max(probe_counts or [0]),max(normalized_counts or [0]),translation_enriched,accepted,duplicated,max(0,len(out)-accepted-duplicated))
 elif translation_received:
  LOG.info('collector translation batch received=%d enriched=%d accepted=%d duplicated=%d',translation_received,translation_enriched,accepted,duplicated)
 if rejected_codes:LOG.warning('collector batch accepted=%d duplicated=%d rejected=%s',accepted,duplicated,json.dumps(rejected_codes,sort_keys=True))
 return _ok(results=out,accepted=accepted,duplicated=duplicated,rejected=len(out)-accepted-duplicated,total=len(out))

def _message_parts(p):
 eid=str(p.get('externalMessageId') or '').strip() or None;ceid=str(p.get('clientEventId') or '').strip() or None
 if not eid and not ceid:return None,{'ok':False,'code':'MESSAGE_ID_REQUIRED'}
 if (eid and len(eid)>500) or (ceid and len(ceid)>500):return None,{'ok':False,'code':'MESSAGE_ID_TOO_LONG'}
 metadata=p.get('metadata')
 if metadata is None:metadata={}
 if not isinstance(metadata,dict):return None,{'ok':False,'code':'MESSAGE_METADATA_INVALID'}
 metadata=dict(metadata)
 # 210.2.61: normalize translation at the collector trust boundary.
 raw_reply=metadata.get('reply')
 if isinstance(raw_reply,dict):
  reply_text=str(raw_reply.get('text') or '').replace('\x00','').strip()[:65536]
  reply_id=str(raw_reply.get('quotedExternalMessageId') or '').strip()[:500]
  if reply_text or reply_id:
   safe_reply_text=redact_text(reply_text)[0] if reply_text else ''
   raw_author=str(raw_reply.get('authorLabel') or '引用消息').replace('\x00','').strip()[:200]
   safe_author=redact_text(raw_author)[0] if raw_author else '引用消息'
   metadata['reply']={'text':safe_reply_text,'authorLabel':safe_author,'quotedExternalMessageId':reply_id,'source':str(raw_reply.get('source') or 'facebook-reply-preview')[:100],'confidence':str(raw_reply.get('confidence') or 'medium')[:16]}
  else:metadata.pop('reply',None)
 else:metadata.pop('reply',None)
 raw_translation=metadata.get('translation')
 if isinstance(raw_translation,str):raw_translation={'text':raw_translation,'source':'legacy-string'}
 if isinstance(raw_translation,dict) and raw_translation.get('visible',True) is not False:
  tr_text=str(raw_translation.get('text') or '').replace('\x00','').strip()
  if tr_text:metadata['translation']={'text':tr_text[:65536],'source':str(raw_translation.get('source') or 'page')[:120],'visible':True,'confidence':str(raw_translation.get('confidence') or '')[:16]}
  else:metadata.pop('translation',None)
 else:metadata.pop('translation',None)
 if str(metadata.get('captureMode') or '').startswith('meta-') and str(metadata.get('deliveryState') or 'sent').lower() in ('pending','sending','uploading','retrying','queued'):
  return None,{'ok':False,'code':'MESSAGE_NOT_FINAL'}
 if str(metadata.get('captureMode') or '').startswith('meta-') and str(metadata.get('timestampPrecision') or '')=='exact' and str(metadata.get('timestampAuthenticity') or '') !='platform-message-record':
  metadata['timestampPrecision']='minute';metadata['timestampConfidence']='low';metadata['timestampAuthenticity']='unverified-exact-rejected'
 sender_type=str(p.get('senderType') or 'unknown').strip()[:80] or 'unknown'
 sender_external_id=str(p.get('senderExternalId') or '').strip() or None
 if sender_external_id and len(sender_external_id)>500:return None,{'ok':False,'code':'MESSAGE_SENDER_ID_TOO_LONG'}
 text=p.get('text');text=None if text is None else str(text)
 if text is not None and len(text.encode())>65536:return None,{'ok':False,'code':'MESSAGE_TEXT_TOO_LARGE'}
 # Persist the original and translation as separate authoritative fields.
 text,_=split_translation_suffix(text,metadata)
 direction=str(p.get('direction') or 'inbound');typ=str(p.get('contentType') or 'text');raw_occurred=p.get('occurredAt')
 # 210.0.12: unresolved Instagram DOM fallbacks are snapshots, not durable messages.
 raw_ids=' '.join(str(p.get(k) or '') for k in ('externalMessageId','clientEventId')).lower()
 temporary_dom=bool(re.search(r'(?:^|:)dom(?:2|3|4)?\.',raw_ids))
 platform_hint=str(metadata.get('platformCode') or '').strip().lower();is_instagram_meta=platform_hint=='instagram' or str(metadata.get('identityVersion') or '').startswith('ig-message-')
 if is_instagram_meta and temporary_dom and (metadata.get('timestampResolved') is False or raw_occurred in (None,'')):
  return None,{'ok':False,'code':'MESSAGE_TIMESTAMP_UNRESOLVED_NOISE'}
 if str(metadata.get('captureMode') or '').startswith('meta-'):
  media_types=('image','audio','video','file','sticker')
  explicit_media=typ in media_types and metadata.get('hasMedia') is True and str(metadata.get('mediaEvidence') or '') in ('same-message-dom-media','platform-message-record')
  if not ((typ=='text' and (text or '').strip()) or explicit_media):return None,{'ok':False,'code':'MESSAGE_CONTENT_EVIDENCE_REQUIRED'}
 try:occurred=int(raw_occurred) if raw_occurred not in (None,'') else None
 except (TypeError,ValueError):return None,{'ok':False,'code':'MESSAGE_TIMESTAMP_INVALID'}
 if occurred is not None and occurred<0:return None,{'ok':False,'code':'MESSAGE_TIMESTAMP_INVALID'}
 if direction not in ('inbound','outbound','system') or typ not in ('text','image','audio','video','file','sticker','share','post','reel','story','location','contact','call','system','unknown'):return None,{'ok':False,'code':'MESSAGE_ENUM_INVALID'}
 is_facebook=platform_hint=='facebook' or str(eid).lower().startswith('facebook:')
 if is_facebook:
  dsrc=str(metadata.get('directionSource') or '')
  dconf=str(metadata.get('directionConfidence') or '')
  if dconf not in ('high','medium') or dsrc not in ('facebook-a11y-sender','facebook-message-sender-id','facebook-message-model','facebook-bubble-geometry'):
   return None,{'ok':False,'code':'FACEBOOK_DIRECTION_EVIDENCE_REQUIRED'}
  if occurred is not None and str(metadata.get('timestampPrecision') or '')!='exact':
   occurred=(occurred//60000)*60000;metadata['timestampPrecision']='minute';metadata['timestampAuthenticity']='facebook-display-minute';metadata['timeGroupAt']=occurred;metadata['displayOccurredAt']=occurred
 if is_facebook and text and (re.match(r'^(?:Enter[,，]?\s*)?(?:消息由.{0,160}?发送于|message (?:sent by|from)|.{0,160}? sent (?:a )?message at)',str(text),re.I) or re.fullmatch(r'(?:你回复了\s*[^\n]{1,100}|[^\n]{1,80}\s*回复了你|you replied to\s+[^\n]{1,120}|[^\n]{1,100}\s+replied to you)',str(text).strip(),re.I) or re.match(r'^(?:已发送|已送达|已读|发送中|正在发送|sent|delivered|seen|sending)$',str(text).strip(),re.I) or re.search(r'(?:新消息和(?:通话|谈话)|消息和(?:通话|谈话)).{0,100}端到端加密',str(text),re.I) or re.search(r'(?:new messages and calls|messages and calls).{0,100}end[- ]to[- ]end encrypted',str(text),re.I)):return None,{'ok':False,'code':'FACEBOOK_PRESENTATION_TEXT_REJECTED'}
 redacted,flags=redact_text(text);digest=message_digest(text,direction,typ,occurred)
 return {'eid':eid,'ceid':ceid,'text':text,'direction':direction,'typ':typ,'occurred':occurred,'redacted':redacted,'flags':flags,'digest':digest,'n':now_ms(),'timestamp_resolved':occurred is not None,'metadata':metadata,'sender_type':sender_type,'sender_external_id':sender_external_id},None

def _valid_first_inbound(parts,p):
 if parts['direction']!='inbound' or parts['typ'] in ('system','call','unknown'):return False
 if parts['typ']=='text':return bool((parts['text'] or '').strip())
 metadata=p.get('metadata')
 return isinstance(metadata,dict) and bool(metadata)

def _message_aliases(parts):
 aliases=parts.get('metadata',{}).get('messageAliases')
 if not isinstance(aliases,list):return []
 out=[]
 for value in aliases[:20]:
  value=str(value or '').strip()
  if value and len(value)<=500 and value not in out and value not in (parts.get('eid'),parts.get('ceid')):out.append(value)
 return out

def _normalized_message_body(value):
 import unicodedata
 body=' '.join(unicodedata.normalize('NFKC',str(value or '')).split())
 body=re.sub(r'^(?:19|20)\d{2}[\/年.\-]\d{1,2}(?:[\/月.\-]\d{1,2}日?)?\s+(?:[01]?\d|2[0-3])[:：.]\d{2}\s+','',body)
 return body.casefold()

def _semantic_message_candidate(c,a,v,parts):
 """Resolve Meta native/DOM identity drift; never use fuzzy text matching."""
 meta=parts.get('metadata') or {}
 if not str(meta.get('captureMode') or '').startswith('meta-'):return None
 body=_normalized_message_body(parts.get('text'))
 if not body:return None
 select="SELECT message_id,conversation_id,content_hash,occurred_at,collected_at,text_content,redacted_text,metadata_json,direction,sender_type,status,content_type,external_message_id,client_event_id FROM conversation_messages"
 base=" organization_id=? AND channel_account_id=? AND conversation_id=? AND direction=? AND content_type=? AND deleted_at IS NULL"
 args=[a['organization_id'],v['channel_account_id'],v['conversation_id'],parts['direction'],parts['typ']]
 rows=c.execute(select+' WHERE'+base,tuple(args)).fetchall()
 exact=[r for r in rows if _normalized_message_body(r['text_content'])==body]
 # First, displayed-minute bijection. This also safely handles short repeated phrases.
 group=meta.get('timeGroupAt')
 if group in (None,'') and parts.get('occurred') is not None:group=(int(parts['occurred'])//60000)*60000
 if group not in (None,''):
  near=[r for r in exact if r['occurred_at'] is not None and int(group)<=int(r['occurred_at'])<int(group)+60000]
  if len(near)==1:return near[0]
 # IG virtual-DOM IDs and dates both drift. For a substantial exact body, one and only
 # one candidate in this conversation is a stronger identity proof than a guessed date.
 ids=' '.join(str(x or '') for x in (parts.get('eid'),parts.get('ceid'))).lower()
 tokens=re.findall(r'[\w]+',body,flags=re.UNICODE)
 temporary=bool(re.search(r'(?:^|:)dom(?:2|3|4)?\.',ids))
 if temporary and len(body)>=24 and len(tokens)>=4 and len(exact)==1:return exact[0]
 return None

def _quarantine_unresolved_meta_noise(c,v,now):
 """Soft-delete old IG DOM snapshots which never obtained message-bound time."""
 rows=c.execute("SELECT message_id,external_message_id,client_event_id,metadata_json FROM conversation_messages WHERE conversation_id=? AND deleted_at IS NULL",(v['conversation_id'],)).fetchall()
 for row in rows:
  ids=' '.join(str(row[k] or '') for k in ('external_message_id','client_event_id'))
  if not re.search(r'(?:^|:)dom(?:2|3|4)?\.',ids,re.I):continue
  try:meta=json.loads(row['metadata_json'] or '{}')
  except Exception:meta={}
  is_ig=str(meta.get('platformCode') or '').strip().lower()=='instagram' or str(meta.get('identityVersion') or '').startswith('ig-message-')
  if is_ig and meta.get('timestampResolved') is False:
   c.execute('UPDATE conversation_messages SET deleted_at=? WHERE message_id=? AND deleted_at IS NULL',(now,row['message_id']))

class _MessageIdentityAmbiguous(Exception):
 pass

def _find_wa_message_by_alias(c,a,v,parts):
 """Fail closed if identifiers disagree; never move historical rows."""
 columns='message_id,conversation_id,content_hash,occurred_at,collected_at,text_content,redacted_text,metadata_json,direction,sender_type,status,content_type,external_message_id,client_event_id'
 direct=[x for x in (parts.get('eid'),parts.get('ceid')) if x]
 aliases=_message_aliases(parts)
 def lookup(ids):
  if not ids:return []
  marks=','.join('?' for _ in ids)
  return c.execute('SELECT '+columns+' FROM conversation_messages WHERE organization_id=? AND channel_account_id=? AND (external_message_id IN ('+marks+') OR client_event_id IN ('+marks+'))',tuple([a['organization_id'],v['channel_account_id'],*ids,*ids])).fetchall()
 rows=lookup(direct)
 if len(rows)>1:raise _MessageIdentityAmbiguous()
 if rows:return rows[0]
 rows=lookup(aliases)
 wanted=set(direct+aliases)
 found={r['message_id']:r for r in rows}
 for row in c.execute('SELECT '+columns+' FROM conversation_messages WHERE organization_id=? AND channel_account_id=? AND conversation_id=?',(a['organization_id'],v['channel_account_id'],v['conversation_id'])).fetchall():
  try:meta=json.loads(row['metadata_json'] or '{}')
  except Exception:meta={}
  raw=meta.get('messageAliases',[]);known=set(str(x) for x in raw if x) if isinstance(raw,list) else set()
  if meta.get('canonicalExternalMessageId'):known.add(str(meta['canonicalExternalMessageId']))
  if wanted & known:found[row['message_id']]=row
 if len(found)>1:raise _MessageIdentityAmbiguous()
 return next(iter(found.values()),None)

def _find_message_by_alias(c,a,v,parts):
 if str(parts.get("metadata",{}).get("platformCode") or parts.get("metadata",{}).get("sourcePlatform") or "").lower()=="whatsapp":return _find_wa_message_by_alias(c,a,v,parts)
 ids=[x for x in [parts.get('eid'),parts.get('ceid'),*_message_aliases(parts)] if x]
 if ids:
  marks=','.join('?' for _ in ids)
  row=c.execute('SELECT message_id,conversation_id,content_hash,occurred_at,collected_at,text_content,redacted_text,metadata_json,direction,sender_type,status,content_type,external_message_id,client_event_id FROM conversation_messages WHERE organization_id=? AND channel_account_id=? AND (external_message_id IN ('+marks+') OR client_event_id IN ('+marks+')) LIMIT 1',tuple([a['organization_id'],v['channel_account_id'],*ids,*ids])).fetchone()
  if row:return row
 wanted=set(ids)
 for row in c.execute('SELECT message_id,conversation_id,content_hash,occurred_at,collected_at,text_content,redacted_text,metadata_json,direction,sender_type,status,content_type,external_message_id,client_event_id FROM conversation_messages WHERE organization_id=? AND channel_account_id=? AND conversation_id=?',(a['organization_id'],v['channel_account_id'],v['conversation_id'])).fetchall():
  try:stored=json.loads(row['metadata_json'] or '{}')
  except Exception:stored={}
  known=set(str(x) for x in stored.get('messageAliases',[]) if x)
  canonical=str(stored.get('canonicalExternalMessageId') or '')
  if canonical:known.add(canonical)
  if wanted & known:return row
 return _semantic_message_candidate(c,a,v,parts)

# 210.2.63：Meta 跟进只接受部署后、会话首轮基线之后首次观测的新出站消息。
# 不对升级前遗漏或首轮加载的历史消息补完成。
META_FOLLOW_UP_TRIGGER_CUTOFF=1791364424490
def _follow_up_event(parts):
 metadata=parts.get('metadata') if isinstance(parts.get('metadata'),dict) else {}
 platform=str(metadata.get('platformCode') or '').strip().lower()
 if platform not in ('facebook','instagram','messenger'):
  return True,parts.get('occurred') if parts.get('occurred') is not None else parts.get('n')
 trigger=metadata.get('followUpTrigger') if isinstance(metadata.get('followUpTrigger'),dict) else {}
 try:first=int(trigger.get('firstObservedAt'))
 except (TypeError,ValueError):return False,None
 if metadata.get('followUpTriggerEligible') is not True or trigger.get('kind')!='live-meta-outbound-v1' or str(trigger.get('platform') or '').lower()!=platform:return False,None
 n=int(parts.get('n') or now_ms())
 if first<META_FOLLOW_UP_TRIGGER_CUTOFF or first>n+5*60000:return False,None
 exact=str(metadata.get('timestampPrecision') or '')=='exact' and str(metadata.get('timestampAuthenticity') or '')=='platform-message-record'
 return True,int(parts.get('occurred')) if exact and parts.get('occurred') is not None else first

def _write_message_in_tx(c,a,p,v,parts):
 eid,ceid=parts['eid'],parts['ceid'];_quarantine_unresolved_meta_noise(c,v,parts['n'])
 try:old=_find_message_by_alias(c,a,v,parts)
 except _MessageIdentityAmbiguous:return {'ok':False,'code':'MESSAGE_IDENTITY_AMBIGUOUS'}
 if old:
  same_conversation=old['conversation_id']==v['conversation_id'];same_payload=old['content_hash']==parts['digest']
  if not same_conversation:
   import hashlib
   fingerprint=hashlib.sha256(str(parts.get('eid') or parts.get('ceid') or '').encode()).hexdigest()[:16]
   LOG.warning('collector identity conflict fingerprint=%s targetConversation=%s matchedConversationFingerprint=%s',fingerprint,v['conversation_id'],hashlib.sha256(str(old['conversation_id']).encode()).hexdigest()[:16])
   return {'ok':False,'duplicate':False,'replayVariant':False,'code':'IDEMPOTENCY_CONFLICT','messageId':old['message_id'],'contactId':v['contact_id'],'conversationId':v['conversation_id'],'identityFingerprint':fingerprint}
  try:old_meta=json.loads(old['metadata_json'] or '{}')
  except Exception:old_meta={}
  incoming=parts['metadata'];changed=False
  # 210.0.20: visible Facebook bubble geometry may repair R2/210.0.18 model/a11y mistakes.
  old_direction=old['direction'];stored_direction=old_direction;stored_sender_type=None
  old_source=str(old_meta.get('directionSource') or '');new_source=str(incoming.get('directionSource') or '')
  platform_code=str(incoming.get('platformCode') or '').lower();trusted_sources={'facebook':('facebook-message-sender-id','facebook-bubble-geometry'),'instagram':('same-message-sender',),'messenger':('same-message-sender',)}.get(platform_code,());trusted_direction=(parts['direction'] in ('inbound','outbound') and str(incoming.get('directionConfidence') or '')=='high' and new_source in trusted_sources and parts['direction']!=old_direction)
  if trusted_direction:
   stored_direction=parts['direction'];stored_sender_type='agent' if stored_direction=='outbound' else 'contact'
   old_meta['directionCorrectedBy']='210.0.20';old_meta['previousDirection']=old_direction;old_meta['directionSource']=new_source;old_meta['directionConfidence']='high';changed=True
  # 210.0.2: exact upgrades require message-bound platform provenance.
  old_precision=str(old_meta.get('timestampPrecision') or 'unresolved');new_precision=str(incoming.get('timestampPrecision') or 'unresolved')
  authenticity=str(incoming.get('timestampAuthenticity') or '')
  trusted_exact=new_precision=='exact' and authenticity=='platform-message-record'
  # 210.0.26: one-way repair for old Instagram weekday rollover timestamps.
  resolver_upgrade=(str(incoming.get('timestampResolverVersion') or '') in ('ig-weekday-sequence-v2','fb-relative-calendar-v3') and str(old_meta.get('timestampResolverVersion') or '')!=str(incoming.get('timestampResolverVersion') or '') and old_precision!='exact')
  same_minute_refine=False  # inferred snapshot seconds are otherwise immutable
  improve_time=parts['occurred'] is not None and (old['occurred_at'] is None or (trusted_exact and old_precision!='exact') or resolver_upgrade)
  if improve_time:
   for k in ('timestampResolved','timestampSource','timestampConfidence','timestampPrecision','timestampAuthenticity','originalTimestamp','displayOccurredAt','timeGroupAt','chronologyOrdinal','chronologyRefined','timestampResolverVersion'):
    if k in incoming:old_meta[k]=incoming[k]
   old_meta['timestampResolved']=True;changed=True
  # platformOrder belongs to one virtual-DOM capture snapshot.  A later
  # history reload can restart at 1, so unrelated batches must not overwrite it.
  same_batch=bool(incoming.get('captureBatchId')) and incoming.get('captureBatchId')==old_meta.get('captureBatchId')
  for k in ('platformOrder','platformOrderSource','platformOrderConfidence'):
   if k in incoming and incoming[k] is not None and (old_meta.get(k) is None or same_batch) and old_meta.get(k)!=incoming[k]:old_meta[k]=incoming[k];changed=True
  for k in ('timeGroupAt','chronologyOrdinal','chronologyRefined','displayOccurredAt'):
   if k in incoming and incoming[k] is not None and old_meta.get(k) is None:old_meta[k]=incoming[k];changed=True
  merged_aliases=[]
  for value in [old['external_message_id'],old['client_event_id'],eid,ceid,*old_meta.get('messageAliases',[]),*_message_aliases(parts)]:
   value=str(value or '').strip()
   if value and value not in merged_aliases:merged_aliases.append(value)
  if merged_aliases[:30]!=old_meta.get('messageAliases'):old_meta['messageAliases']=merged_aliases[:30];changed=True
  if eid and not re.match(r'^dom(?:2|3|4)?\.',str(eid).split(':')[-1]) and old_meta.get('canonicalExternalMessageId')!=eid:old_meta['canonicalExternalMessageId']=eid;changed=True
  old_reply=old_meta.get('reply') if isinstance(old_meta.get('reply'),dict) else None
  new_reply=incoming.get('reply') if isinstance(incoming.get('reply'),dict) else None
  # Same stable message identity only; never search by quote text or move rows across conversations.
  if new_reply and (not old_reply or (not old_reply.get('quotedExternalMessageId') and new_reply.get('quotedExternalMessageId'))):
   old_meta['reply']=new_reply;changed=True
  old_tr=old_meta.get('translation') if isinstance(old_meta.get('translation'),dict) else None
  new_tr=incoming.get('translation') if isinstance(incoming.get('translation'),dict) else None
  # 210.0.21: translation can arrive after the original message or improve an earlier weak binding.  Permit a
  # message-owned high-confidence binding to fill or replace an older weak binding.
  old_tr_text=str((old_tr or {}).get('text') or '').strip()
  new_tr_text=str((new_tr or {}).get('text') or '').strip()
  new_tr_source=str((new_tr or {}).get('source') or '')
  old_tr_source=str((old_tr or {}).get('source') or '')
  trusted_translation=bool(new_tr_text) and (
   not old_tr_text or (
    new_tr_text!=old_tr_text and
    str((new_tr or {}).get('confidence') or '')=='high' and
    ('message-owned' in new_tr_source or 'current-reply' in new_tr_source) and
    (not ('message-owned' in old_tr_source and str((old_tr or {}).get('confidence') or '')=='high') or ('210021' in new_tr_source and '210021' not in old_tr_source))
   )
  )
  if trusted_translation:
   old_meta['translation']=new_tr;old_meta['translationEnrichedBy']='210.2.61';changed=True
  fill_text=old['text_content'] in (None,'') and parts['text'] not in (None,'')
  stored_text=parts['text'] if fill_text else old['text_content']
  stored_text,body_normalized=split_translation_suffix(stored_text,old_meta)
  if body_normalized:changed=True
  follow_up_completed=0
  if changed or fill_text:
   stored_redacted,stored_flags=redact_text(stored_text)
   stored_occurred=parts['occurred'] if improve_time else old['occurred_at']
   stored_digest=message_digest(stored_text,stored_direction,old['content_type'],stored_occurred)
   c.execute("UPDATE conversation_messages SET occurred_at=CASE WHEN ? THEN ? ELSE occurred_at END,direction=?,sender_type=CASE WHEN ? IS NULL THEN sender_type ELSE ? END,text_content=?,redacted_text=?,pii_flags_json=?,content_hash=?,metadata_json=? WHERE message_id=?",(1 if improve_time else 0,parts['occurred'],stored_direction,stored_sender_type,stored_sender_type,stored_text,stored_redacted,dumps(stored_flags),stored_digest,dumps(old_meta),old['message_id']))
   # Rebuild ordering/cache because enriching occurred_at may change first/last message.
   agg=c.execute("SELECT MIN(occurred_at) first_at,MAX(occurred_at) last_at,COUNT(*) total,SUM(CASE WHEN direction='inbound' THEN 1 ELSE 0 END) inbound,SUM(CASE WHEN direction='outbound' THEN 1 ELSE 0 END) outbound FROM conversation_messages WHERE conversation_id=? AND status='active'",(v['conversation_id'],)).fetchone()
   latest=c.execute("SELECT message_id,direction,content_type,redacted_text,text_content FROM conversation_messages WHERE conversation_id=? AND status='active' ORDER BY COALESCE(occurred_at,collected_at) DESC,message_id DESC LIMIT 1",(v['conversation_id'],)).fetchone()
   preview=((latest['redacted_text'] or latest['text_content'] or '')[:500] if latest else None)
   c.execute("UPDATE conversations SET first_message_at=?,last_message_at=?,last_message_id=?,last_message_direction=?,last_message_type=?,last_message_preview=?,message_count=?,inbound_count=?,outbound_count=?,updated_at=? WHERE conversation_id=?",(agg['first_at'],agg['last_at'],latest['message_id'] if latest else None,latest['direction'] if latest else None,latest['content_type'] if latest else None,preview,int(agg['total'] or 0),int(agg['inbound'] or 0),int(agg['outbound'] or 0),parts['n'],v['conversation_id']))
   if parts['occurred'] is not None:c.execute('UPDATE contacts SET last_touch_at=CASE WHEN last_touch_at IS NULL OR ? > last_touch_at THEN ? ELSE last_touch_at END,last_seen_at=?,updated_at=? WHERE contact_id=?',(parts['occurred'],parts['occurred'],parts['n'],parts['n'],v['contact_id']))
   final_sender=stored_sender_type or old['sender_type'];event_at=stored_occurred if stored_occurred is not None else old['collected_at']
   eligible,event_at=_follow_up_event({**parts,'direction':stored_direction,'sender_type':final_sender});follow_up_completed=_complete_follow_up_isolated(c,v['contact_id'],event_at,a.get('user_id'),old['message_id'],'outbound_message',{'source':'collector','messageId':old['message_id'],'evidence':'live-meta-outbound-v1' if str(parts.get('metadata',{}).get('platformCode') or '').lower() in ('facebook','instagram','messenger') else 'collector-outbound'}) if eligible and stored_direction=='outbound' and final_sender=='agent' and old['status']=='active' else 0
  return {'ok':True,'duplicate':True,'enriched':bool(changed or fill_text),'translationEnriched':bool(trusted_translation),'replayVariant':bool(not same_payload),'code':None,'messageId':old['message_id'],'contactId':v['contact_id'],'conversationId':v['conversation_id'],'followUpCompleted':follow_up_completed}
 mid='msg_'+uuid.uuid4().hex
 c.execute("INSERT INTO conversation_messages(message_id,organization_id,workspace_id,team_id,conversation_id,channel_account_id,contact_id,external_message_id,client_event_id,direction,sender_type,sender_external_id,content_type,text_content,redacted_text,content_hash,pii_flags_json,occurred_at,collected_at,status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active',?)",(mid,a['organization_id'],a['workspace_id'],a['team_id'],v['conversation_id'],v['channel_account_id'],v['contact_id'],eid,ceid,parts['direction'],parts['sender_type'],parts['sender_external_id'],parts['typ'],parts['text'],parts['redacted'],parts['digest'],dumps(parts['flags']),parts['occurred'],parts['n'],dumps({**parts['metadata'],'timestampResolved':parts['timestamp_resolved'],'timestampConfidence':parts['metadata'].get('timestampConfidence','high' if parts['timestamp_resolved'] else 'low'),'observedAt':parts['metadata'].get('observedAt',parts['n'])})))
 # Rebuild the denormalized conversation cache from stored rows. This keeps
 # historical backfill from replacing the actual latest message and guarantees
 # that list/detail counters match the authoritative message table.
 agg=c.execute("""SELECT COUNT(*) total,
  SUM(CASE WHEN direction='inbound' THEN 1 ELSE 0 END) inbound,
  SUM(CASE WHEN direction='outbound' THEN 1 ELSE 0 END) outbound,
   MIN(occurred_at) first_at,
   MAX(occurred_at) last_at
  FROM conversation_messages WHERE conversation_id=? AND deleted_at IS NULL""",(v['conversation_id'],)).fetchone()
 latest=c.execute("""SELECT message_id,direction,content_type,redacted_text FROM conversation_messages
 WHERE conversation_id=? AND deleted_at IS NULL
 ORDER BY COALESCE(occurred_at,collected_at) DESC,message_id DESC LIMIT 1""",(v['conversation_id'],)).fetchone()
 try:meta=json.loads(v['metadata_json'] or '{}')
 except Exception:meta={}
 if latest and latest['direction']=='inbound':meta['awaitingReply']=True
 elif latest and latest['direction']=='outbound':meta['awaitingReply']=False
 preview=(latest['redacted_text'] if latest else None)
 if preview is not None:preview=str(preview)[:500]
 c.execute("""UPDATE conversations SET first_message_at=?,last_message_at=?,last_collected_at=?,
  last_message_id=?,last_message_direction=?,last_message_type=?,last_message_preview=?,
  message_count=?,inbound_count=?,outbound_count=?,metadata_json=?,updated_at=? WHERE conversation_id=?""",
  (agg['first_at'],agg['last_at'],parts['n'],latest['message_id'] if latest else None,
   latest['direction'] if latest else None,latest['content_type'] if latest else None,preview,
   int(agg['total'] or 0),int(agg['inbound'] or 0),int(agg['outbound'] or 0),dumps(meta),parts['n'],v['conversation_id']))
 c.execute('UPDATE contacts SET last_touch_at=CASE WHEN ? IS NOT NULL AND (last_touch_at IS NULL OR ?>last_touch_at) THEN ? ELSE last_touch_at END,last_seen_at=?,updated_at=? WHERE contact_id=?',(parts['occurred'],parts['occurred'],parts['occurred'],parts['n'],parts['n'],v['contact_id']))
 eligible,event_at=_follow_up_event(parts);follow_up_completed=_complete_follow_up_isolated(c,v['contact_id'],event_at,a.get('user_id'),mid,'outbound_message',{'source':'collector','messageId':mid,'evidence':'live-meta-outbound-v1' if str(parts.get('metadata',{}).get('platformCode') or '').lower() in ('facebook','instagram','messenger') else 'collector-outbound'}) if eligible and parts['direction']=='outbound' and parts['sender_type']=='agent' else 0
 return {'ok':True,'duplicate':False,'messageId':mid,'contactId':v['contact_id'],'conversationId':v['conversation_id'],'followUpCompleted':follow_up_completed}
def _auto_registration_payload(p,parts):
 ctx=p.get('registrationContext') or {}
 message_key=parts['eid'] or parts['ceid']
 return {'platformCode':ctx.get('platformCode'),'channelAccountId':ctx.get('channelAccountId'),'accountIdentity':ctx.get('accountIdentity') or {},'contactIdentity':ctx.get('contactIdentity') or {},'contactIdentityAliases':ctx.get('contactIdentityAliases') or [],'externalConversationId':ctx.get('externalConversationId'),'profile':ctx.get('profile') or {},'fields':{},'stages':{},'tagIds':[],'idempotencyKey':ctx.get('idempotencyKey') or ('auto:'+str(ctx.get('platformCode') or '')+':'+str(ctx.get('channelAccountId') or '')+':'+str(ctx.get('externalConversationId') or '')+':'+str(message_key))}

def _collect_auto_first_inbound(db,a,p,parts):
 if not _valid_first_inbound(parts,p):return {'ok':False,'code':'FIRST_INBOUND_MESSAGE_INVALID'}
 reg=_auto_registration_payload(p,parts);ctx=p.get('registrationContext') or {}
 if not reg['platformCode'] or not reg['channelAccountId'] or not reg['externalConversationId']:return {'ok':False,'code':'AUTO_REGISTRATION_CONTEXT_REQUIRED'}
 with db.tx() as c:
  platform=_platform(c,reg)
  if not platform:return {'ok':False,'code':'PLATFORM_NOT_FOUND'}
  account=_account_allowed(c,a,reg['channelAccountId'],platform['platform_id'])
  if not account:return {'ok':False,'code':'ACCOUNT_NOT_AUTHORIZED'}
  if account['contact_entry_policy']!='first_inbound_message':return {'ok':False,'code':'AUTO_REGISTRATION_POLICY_DENIED'}
  from V208_interaction_service import register_contact
  registered,status=register_contact(db,a,reg,_connection=c,_operation='collector.first_inbound.register')
  if not registered.get('ok'):
   # Returning would commit any accidental partial work. Force rollback, then convert outside.
   raise _AutoRegisterAbort(registered)
  conv=registered.get('conversation') or {};vid=conv.get('conversation_id')
  v=c.execute("SELECT * FROM conversations WHERE conversation_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND assigned_user_id=?",(vid,a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'])).fetchone()
  if not v:raise RuntimeError('AUTO_REGISTER_CONVERSATION_MISSING')
  result=_write_message_in_tx(c,a,p,v,parts);result['contactCreated']=bool(registered.get('contactCreated'));result['autoRegistered']=True;result['registrationReplayed']=bool(registered.get('replayed'));return result

class _AutoRegisterAbort(Exception):
 def __init__(self,result):self.result=result

def _collect_one(db,a,p):
 parts,bad=_message_parts(p)
 if bad:return bad
 vid=str(p.get('conversationId') or '').strip()
 if not vid:
  try:return _collect_auto_first_inbound(db,a,p,parts)
  except _AutoRegisterAbort as ex:return ex.result
 with db.tx() as c:
  v=c.execute("SELECT * FROM conversations WHERE conversation_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND assigned_user_id=?",(vid,a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'])).fetchone()
  if not v:return {'ok':False,'code':'CONVERSATION_SCOPE_INVALID'}
  account=_account_allowed(c,a,v['channel_account_id'],v['platform_id'])
  if not account:return {'ok':False,'code':'ACCOUNT_NOT_AUTHORIZED'}
  if account['contact_entry_policy']=='disabled' or not account['collection_enabled']:return {'ok':False,'code':'COLLECTION_DISABLED'}
  if not c.execute("SELECT 1 FROM device_channel_account_bindings WHERE device_id=? AND user_id=? AND channel_account_id=? AND platform_id=? AND status='active'",(a['device_id'],a['user_id'],v['channel_account_id'],v['platform_id'])).fetchone():return {'ok':False,'code':'ACCOUNT_BINDING_REQUIRED'}
  current_generation,_meta=_collection_generation(v)
  raw_generation=p.get('collectionGeneration')
  try:requested_generation=int(raw_generation) if raw_generation not in (None,'') else 1
  except (TypeError,ValueError):return {'ok':False,'code':'COLLECTION_GENERATION_INVALID','currentGeneration':current_generation}
  if requested_generation!=current_generation:return {'ok':False,'code':'COLLECTION_GENERATION_STALE','currentGeneration':current_generation}
  return _write_message_in_tx(c,a,p,v,parts)
