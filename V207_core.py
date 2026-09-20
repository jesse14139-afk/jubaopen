# -*- coding: utf-8 -*-
"""V207 多租户业务扩展。"""
from V207_shared_db import now_ms,dumps
from V207_version import PRODUCT_VERSION,SCHEMA_VERSION
from V207_security import canonical,permissions,can
VERSION=PRODUCT_VERSION
DOMAIN_CHANNEL={'web.whatsapp.com':'whatsapp','www.instagram.com':'instagram','www.messenger.com':'messenger','www.facebook.com':'facebook','web.telegram.org':'telegram'}
def ok(**x):return {'ok':True,**x},200
def err(code,message,status=400,**x):return {'ok':False,'code':code,'message':message,**x},status
def trusted_channel(host,path=''):
 host=str(host or '').lower().split(':')[0]
 if host=='www.facebook.com' and not str(path).startswith('/messages'):return None
 return DOMAIN_CHANNEL.get(host)
def session_context(db,a):
 with db.tx(False) as c:
  ms=[dict(x) for x in c.execute("""SELECT t.team_id,t.name team_name,t.workspace_id,b.role_id,r.name role_name
  FROM role_bindings b JOIN teams t ON b.scope_type='team' AND b.scope_id=t.team_id JOIN roles r ON r.role_id=b.role_id
  WHERE b.user_id=? AND b.organization_id=? AND b.status='active' AND t.status='active' AND r.status='active'
  ORDER BY t.created_at,r.name""",(a['user_id'],a['organization_id']))]
  for m in ms:m['permissions']=sorted(permissions(db,a['user_id'],team_id=m['team_id'],workspace_id=m['workspace_id'],organization_id=a['organization_id']))
  orgrow=c.execute('SELECT * FROM organizations WHERE organization_id=?',(a['organization_id'],)).fetchone()
  if not orgrow:return err('ORGANIZATION_NOT_FOUND','企业不存在',404)
  org=dict(orgrow)
  return ok(user={k:a[k] for k in ('user_id','login_name','display_name')},organization=org,memberships=ms)
def resolve_account(db,a,p):
 ch=trusted_channel(p.get('host'),p.get('path',''))
 if not ch:return err('UNTRUSTED_CHANNEL','当前页面不是受信任渠道页面',400)
 claimed=str(p.get('channel') or ch).lower()
 if claimed!=ch:return err('CHANNEL_MISMATCH','请求渠道与受信任域名不一致',409,expectedChannel=ch)
 identity=canonical(p.get('identity'))
 if not identity:return err('ACCOUNT_IDENTITY_REQUIRED',f'无法识别当前 {ch} 登录账号，请刷新后重试',409,channel=ch)
 with db.tx(False) as c:
  candidates=[dict(x) for x in c.execute("""SELECT DISTINCT ca.channel_account_id,ca.display_name,s.source_id,s.source_name,t.team_id,t.name team_name,t.workspace_id
  FROM channel_account_identities i JOIN channel_accounts ca ON ca.channel_account_id=i.channel_account_id
  JOIN team_channel_accounts ta ON ta.channel_account_id=ca.channel_account_id JOIN teams t ON t.team_id=ta.team_id
  LEFT JOIN sources s ON s.channel_account_id=ca.channel_account_id AND s.team_id=t.team_id AND s.status='active'
  WHERE ca.organization_id=? AND t.organization_id=ca.organization_id AND ca.channel=? AND i.canonical_value=? AND ca.status='active' AND t.status='active'""",(a['organization_id'],ch,identity))]
 rows=[x for x in candidates if can(db,a,'account.read',x['workspace_id'],x['team_id'],organization_id=a['organization_id'])]
 if not rows:return err('ACCOUNT_NOT_BOUND',f'当前 {ch.title()} 账号尚未绑定企业账号来源，请联系管理员',409,channel=ch)
 valid=[x for x in rows if x.get('source_id')]
 if len(valid)!=1:return err('ACCOUNT_BINDING_CONFLICT','当前账号未形成唯一来源绑定，请联系管理员处理',409,channel=ch,matches=len(valid))
 return ok(channel=ch,binding=valid[0])
def register_device(db,a,p):
 did=str(p.get('device_id') or '').strip();iid=str(p.get('installation_id') or '').strip();team=str(p.get('team_id') or '').strip()
 if not did or not iid or not team:return err('INVALID_DEVICE','device_id、installation_id、team_id 必填')
 with db.tx() as c:
  trow=c.execute('SELECT * FROM teams WHERE team_id=? AND organization_id=?',(team,a['organization_id'])).fetchone()
  if not trow:return err('TEAM_NOT_FOUND','团队不存在',404)
  t=now_ms();sysd=str(p.get('system_device_name') or p.get('device_name') or did)[:120];sysc=str(p.get('system_computer_name') or p.get('computer_name') or '')[:120]
  c.execute("INSERT INTO devices(device_id,workspace_id,installation_id,device_name,computer_name,status,first_seen_at,last_seen_at,metadata_json,organization_id,team_id,assigned_user_id,system_device_name,system_computer_name,user_device_alias,user_computer_alias) VALUES(?,?,?,?,?,'active',?,?,'{}',?,?,?,?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET last_seen_at=excluded.last_seen_at,assigned_user_id=excluded.assigned_user_id,team_id=excluded.team_id,system_device_name=excluded.system_device_name,system_computer_name=excluded.system_computer_name,user_device_alias=COALESCE(excluded.user_device_alias,devices.user_device_alias),user_computer_alias=COALESCE(excluded.user_computer_alias,devices.user_computer_alias)",(did,trow['workspace_id'],iid,sysd,sysc,t,t,a['organization_id'],team,a['user_id'],sysd,sysc,p.get('user_device_alias'),p.get('user_computer_alias')))
  if not c.execute('SELECT 1 FROM device_assignments WHERE device_id=? AND released_at IS NULL',(did,)).fetchone():c.execute('INSERT INTO device_assignments(assignment_id,device_id,assigned_user_id,team_id,assigned_at,released_at) VALUES(?,?,?,?,?,NULL)',('asn_'+did,did,a['user_id'],team,t))
  r=dict(c.execute('SELECT * FROM devices WHERE device_id=?',(did,)).fetchone());r['display_name']=r.get('admin_device_name') or r.get('user_device_alias') or r.get('system_device_name') or did
  return ok(device=r)
def rename_device(db,a,p,admin=False):
 did=str(p.get('device_id') or '')
 with db.tx() as c:
  d=c.execute('SELECT * FROM devices WHERE device_id=? AND organization_id=?',(did,a['organization_id'])).fetchone()
  if not d:return err('DEVICE_NOT_FOUND','设备不存在',404)
  if not admin and d['assigned_user_id']!=a['user_id']:return err('FORBIDDEN','只能修改自己的设备别名',403)
  cols=('admin_device_name','admin_computer_name') if admin else ('user_device_alias','user_computer_alias');c.execute(f'UPDATE devices SET {cols[0]}=?,{cols[1]}=? WHERE device_id=?',(str(p.get('device_name') or '')[:120],str(p.get('computer_name') or '')[:120],did));return ok(deviceId=did)
def graph(db,a):
 with db.tx(False) as c:
  org=a['organization_id'];tables={'organizations':('SELECT * FROM organizations WHERE organization_id=?',(org,)),'teams':('SELECT * FROM teams WHERE organization_id=?',(org,)),'users':('SELECT user_id,display_name,status FROM users WHERE organization_id=?',(org,)),'accounts':('SELECT * FROM channel_accounts WHERE organization_id=?',(org,)),'sources':('SELECT source_id,source_name,channel,team_id,channel_account_id,status FROM sources WHERE organization_id=?',(org,)),'devices':('SELECT device_id,team_id,assigned_user_id,system_device_name,user_device_alias,admin_device_name,status FROM devices WHERE organization_id=?',(org,))}
  return ok(graph={k:[dict(x) for x in c.execute(q,args)] for k,(q,args) in tables.items()})
# V207.0.0 更新说明：可信域名定渠道，禁止识别失败降级 other；来源由管理员预授权并自动解析。
