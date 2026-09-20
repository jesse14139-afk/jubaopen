# -*- coding: utf-8 -*-
"""聚宝盆 V207.5 数据层：Schema 208，多租户/RBAC/账号授权/设备双命名。"""
from __future__ import annotations
import contextlib, hashlib, json, sqlite3, time, secrets, shutil, re
from pathlib import Path
from V207_version import SCHEMA_VERSION, PRODUCT_VERSION, CATALOG_VERSION
def now_ms(): return int(time.time()*1000)
def dumps(v): return json.dumps(v,ensure_ascii=False,separators=(",",":"))
def loads(v,default=None):
 try:return json.loads(v) if v else default
 except Exception:return default
def sha256_bytes(v):return hashlib.sha256(v).hexdigest()
def execute_sql_script(c,script):
 """Execute a SQL script statement-by-statement without implicit COMMIT."""
 statement=''
 for line in script.splitlines(True):
  statement+=line
  if sqlite3.complete_statement(statement):
   sql=statement.strip()
   if sql:c.execute(sql)
   statement=''
 if statement.strip():raise RuntimeError('不完整的 SQL 迁移脚本')
def _exclusive_backup_path(path):
 stamp=time.strftime('%Y%m%dT%H%M%S',time.gmtime())
 ns=time.time_ns()%1000000000
 for seq in range(1000):
  candidate=path.with_name(f'{path.name}.pre-v2075.{stamp}.{ns:09d}Z'+(f'.{seq}' if seq else '')+'.bak')
  try:
   with candidate.open('xb'):pass
   return candidate
  except FileExistsError:continue
 raise RuntimeError('无法创建不可覆盖的迁移备份文件名')
def _write_failure_report(path,exc,backup):
 report=path.with_name(path.name+'.migration-failure.'+time.strftime('%Y%m%dT%H%M%S',time.gmtime())+f'.{time.time_ns()%1000000000:09d}Z.json')
 payload={'status':'failed','database':str(path),'backup':str(backup) if backup else None,'errorType':type(exc).__name__,'error':str(exc),'failedAt':now_ms()}
 with report.open('x',encoding='utf-8') as f:json.dump(payload,f,ensure_ascii=False,indent=2)
 return report
BASE_SCHEMA=r"""
CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE workspaces(workspace_id TEXT PRIMARY KEY,name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
CREATE TABLE devices(device_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,installation_id TEXT NOT NULL,device_name TEXT NOT NULL,computer_name TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'active',first_seen_at INTEGER NOT NULL,last_seen_at INTEGER NOT NULL,metadata_json TEXT NOT NULL DEFAULT '{}',FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),UNIQUE(workspace_id,installation_id));
CREATE TABLE sources(source_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,channel TEXT NOT NULL,account_identity TEXT NOT NULL,source_name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',first_seen_at INTEGER NOT NULL,last_seen_at INTEGER NOT NULL,last_device_id TEXT,metadata_json TEXT NOT NULL DEFAULT '{}',FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),FOREIGN KEY(last_device_id) REFERENCES devices(device_id),UNIQUE(workspace_id,channel,account_identity));
CREATE TABLE source_devices(workspace_id TEXT NOT NULL,source_id TEXT NOT NULL,device_id TEXT NOT NULL,first_seen_at INTEGER NOT NULL,last_seen_at INTEGER NOT NULL,event_count INTEGER NOT NULL DEFAULT 0,contact_observe_count INTEGER NOT NULL DEFAULT 0,last_operation TEXT NOT NULL DEFAULT '',PRIMARY KEY(workspace_id,source_id,device_id));
CREATE TABLE contacts(contact_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,source_id TEXT NOT NULL,channel TEXT NOT NULL,external_contact_id TEXT NOT NULL,display_name TEXT NOT NULL DEFAULT '',observed_phone TEXT NOT NULL DEFAULT '',avatar_url TEXT NOT NULL DEFAULT '',observed_json TEXT NOT NULL DEFAULT '{}',observation_hash TEXT NOT NULL DEFAULT '',manual_name TEXT NOT NULL DEFAULT '',manual_phone TEXT NOT NULL DEFAULT '',remark TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT '',business_json TEXT NOT NULL DEFAULT '{}',last_observed_device_id TEXT,last_observed_at INTEGER,version INTEGER NOT NULL DEFAULT 1,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,last_seen_at INTEGER NOT NULL,deleted_at INTEGER,deleted_by TEXT,delete_reason TEXT,UNIQUE(workspace_id,source_id,channel,external_contact_id));
CREATE INDEX idx_contacts_source ON contacts(workspace_id,source_id,deleted_at);
CREATE TABLE tags(tag_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,name TEXT NOT NULL,color TEXT NOT NULL DEFAULT '#64748b',category TEXT NOT NULL DEFAULT '',sort_order INTEGER NOT NULL DEFAULT 0,enabled INTEGER NOT NULL DEFAULT 1,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,UNIQUE(workspace_id,name));
CREATE TABLE contact_tags(contact_id TEXT NOT NULL,tag_id TEXT NOT NULL,created_at INTEGER NOT NULL,PRIMARY KEY(contact_id,tag_id));
CREATE TABLE custom_field_definitions(workspace_id TEXT NOT NULL,field_key TEXT NOT NULL,label TEXT NOT NULL,field_type TEXT NOT NULL DEFAULT 'text',sort_order INTEGER NOT NULL DEFAULT 0,enabled INTEGER NOT NULL DEFAULT 1,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,PRIMARY KEY(workspace_id,field_key));
CREATE TABLE contact_custom_values(contact_id TEXT NOT NULL,field_key TEXT NOT NULL,value_json TEXT NOT NULL DEFAULT 'null',updated_at INTEGER NOT NULL,updated_by TEXT NOT NULL,PRIMARY KEY(contact_id,field_key));
CREATE TABLE events(event_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,device_id TEXT NOT NULL,installation_id TEXT,source_id TEXT,session_id TEXT,request_id TEXT,entity_type TEXT NOT NULL,entity_id TEXT,operation TEXT NOT NULL,base_version INTEGER,payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL,status TEXT NOT NULL,result_version INTEGER,error_code TEXT,created_at INTEGER NOT NULL,applied_at INTEGER,result_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE changes(change_id INTEGER PRIMARY KEY AUTOINCREMENT,workspace_id TEXT NOT NULL,entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,operation TEXT NOT NULL,version INTEGER NOT NULL,source_id TEXT,device_id TEXT,changed_at INTEGER NOT NULL,payload_json TEXT NOT NULL,event_id TEXT);
CREATE INDEX idx_changes_cursor ON changes(workspace_id,change_id);
CREATE TABLE audit_logs(audit_id INTEGER PRIMARY KEY AUTOINCREMENT,workspace_id TEXT NOT NULL,actor_id TEXT NOT NULL,device_id TEXT,operation TEXT NOT NULL,entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,before_json TEXT NOT NULL,after_json TEXT NOT NULL,reason TEXT,created_at INTEGER NOT NULL);
CREATE TABLE delete_confirmations(confirmation_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,expected_version INTEGER NOT NULL,impact_hash TEXT NOT NULL,expires_at INTEGER NOT NULL,used_at INTEGER,created_by TEXT NOT NULL);
CREATE TABLE workspace_configs(workspace_id TEXT PRIMARY KEY,revision INTEGER NOT NULL DEFAULT 0,items_json TEXT NOT NULL DEFAULT '[]',updated_at INTEGER NOT NULL,updated_by TEXT NOT NULL DEFAULT 'system');
"""
V207_SCHEMA=r"""
CREATE TABLE IF NOT EXISTS organizations(organization_id TEXT PRIMARY KEY,name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS teams(team_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,UNIQUE(organization_id,workspace_id,name));
CREATE TABLE IF NOT EXISTS users(user_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,login_name TEXT NOT NULL COLLATE NOCASE,display_name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,UNIQUE(organization_id,login_name));
CREATE TABLE IF NOT EXISTS user_credentials(user_id TEXT PRIMARY KEY,password_hash TEXT NOT NULL,salt TEXT NOT NULL,iterations INTEGER NOT NULL,must_change INTEGER NOT NULL DEFAULT 1,updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(session_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,access_token_hash TEXT NOT NULL UNIQUE,expires_at INTEGER NOT NULL,ip TEXT,user_agent TEXT,created_at INTEGER NOT NULL,last_seen_at INTEGER NOT NULL,revoked_at INTEGER);
CREATE TABLE IF NOT EXISTS roles(role_id TEXT PRIMARY KEY,organization_id TEXT,name TEXT NOT NULL,scope_level TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',UNIQUE(organization_id,name));
CREATE TABLE IF NOT EXISTS permissions(permission_key TEXT PRIMARY KEY,description TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS role_permissions(role_id TEXT NOT NULL,permission_key TEXT NOT NULL,PRIMARY KEY(role_id,permission_key));
CREATE TABLE IF NOT EXISTS organization_memberships(user_id TEXT NOT NULL,organization_id TEXT NOT NULL,role_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',PRIMARY KEY(user_id,organization_id,role_id));
CREATE TABLE IF NOT EXISTS team_memberships(user_id TEXT NOT NULL,team_id TEXT NOT NULL,role_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',PRIMARY KEY(user_id,team_id,role_id));
CREATE TABLE IF NOT EXISTS channel_accounts(channel_account_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,channel TEXT NOT NULL CHECK(channel IN ('whatsapp','instagram','facebook','messenger','telegram')),display_name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS channel_account_identities(identity_id TEXT PRIMARY KEY,channel_account_id TEXT NOT NULL,identity_type TEXT NOT NULL,identity_value TEXT NOT NULL,canonical_value TEXT NOT NULL,created_at INTEGER NOT NULL,UNIQUE(channel_account_id,identity_type,canonical_value));
CREATE INDEX IF NOT EXISTS idx_identity_lookup ON channel_account_identities(identity_type,canonical_value);
CREATE TABLE IF NOT EXISTS team_channel_accounts(team_id TEXT NOT NULL,channel_account_id TEXT NOT NULL,granted_by TEXT NOT NULL,granted_at INTEGER NOT NULL,PRIMARY KEY(team_id,channel_account_id));
CREATE TABLE IF NOT EXISTS user_channel_account_grants(user_id TEXT NOT NULL,channel_account_id TEXT NOT NULL,permission_scope TEXT NOT NULL DEFAULT 'use',granted_by TEXT NOT NULL,granted_at INTEGER NOT NULL,PRIMARY KEY(user_id,channel_account_id));
CREATE TABLE IF NOT EXISTS device_assignments(assignment_id TEXT PRIMARY KEY,device_id TEXT NOT NULL,assigned_user_id TEXT NOT NULL,team_id TEXT NOT NULL,assigned_at INTEGER NOT NULL,released_at INTEGER);
"""
PERMS=['organization.read','organization.manage','team.read','team.manage','user.read','user.manage','role.read','role.manage','account.read','account.bind','source.read','source.manage','device.read','device.rename.self','device.rename.admin','device.disable','device.bind','contact.read','contact.update','contact.delete','contact.restore','contact.export','audit.read']
def _cols(c,t):return {x[1] for x in c.execute('PRAGMA table_info('+t+')')}
def _add(c,t,col,decl):
 if col not in _cols(c,t):c.execute(f'ALTER TABLE {t} ADD COLUMN {col} {decl}')
def hash_password(password,salt=None,it=260000):
 salt=salt or secrets.token_hex(16); h=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),it).hex(); return h,salt,it

V207_1_SCHEMA=r"""
CREATE TABLE IF NOT EXISTS security_events(security_event_id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT,organization_id TEXT,event_type TEXT NOT NULL,ip TEXT,user_agent TEXT,detail_json TEXT NOT NULL DEFAULT '{}',created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS schema_migrations(migration_id TEXT PRIMARY KEY,migration_name TEXT NOT NULL,checksum TEXT NOT NULL,applied_at INTEGER NOT NULL,applied_by TEXT NOT NULL,result_json TEXT NOT NULL DEFAULT '{}');
CREATE VIEW IF NOT EXISTS source_nodes AS SELECT * FROM sources;
CREATE TABLE IF NOT EXISTS platforms(platform_id TEXT PRIMARY KEY,platform_code TEXT NOT NULL UNIQUE,platform_name TEXT NOT NULL,platform_kind TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',capabilities_json TEXT NOT NULL DEFAULT '{}',metadata_json TEXT NOT NULL DEFAULT '{}',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS campaigns(campaign_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,platform_id TEXT,channel_account_id TEXT,campaign_code TEXT,campaign_name TEXT NOT NULL,campaign_type TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',start_at INTEGER,end_at INTEGER,metadata_json TEXT NOT NULL DEFAULT '{}',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,FOREIGN KEY(platform_id) REFERENCES platforms(platform_id),FOREIGN KEY(channel_account_id) REFERENCES channel_accounts(channel_account_id));
CREATE TABLE IF NOT EXISTS contact_identities(contact_identity_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,contact_id TEXT NOT NULL,platform_id TEXT,identity_type TEXT NOT NULL,identity_value TEXT NOT NULL,canonical_value TEXT NOT NULL,verification_status TEXT NOT NULL DEFAULT 'unverified',is_primary INTEGER NOT NULL DEFAULT 0,first_seen_at INTEGER NOT NULL,last_seen_at INTEGER NOT NULL,metadata_json TEXT NOT NULL DEFAULT '{}',FOREIGN KEY(contact_id) REFERENCES contacts(contact_id),FOREIGN KEY(platform_id) REFERENCES platforms(platform_id),UNIQUE(organization_id,platform_id,identity_type,canonical_value));
CREATE TABLE IF NOT EXISTS source_touchpoints(touchpoint_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,source_id TEXT NOT NULL,contact_id TEXT,platform_id TEXT,channel_account_id TEXT,campaign_id TEXT,touchpoint_type TEXT NOT NULL,direction TEXT NOT NULL DEFAULT 'inbound',initiated_by TEXT NOT NULL DEFAULT 'unknown',external_event_id TEXT,session_id TEXT,occurred_at INTEGER NOT NULL,metadata_json TEXT NOT NULL DEFAULT '{}',created_at INTEGER NOT NULL,FOREIGN KEY(source_id) REFERENCES sources(source_id),FOREIGN KEY(contact_id) REFERENCES contacts(contact_id),FOREIGN KEY(platform_id) REFERENCES platforms(platform_id),FOREIGN KEY(channel_account_id) REFERENCES channel_accounts(channel_account_id),FOREIGN KEY(campaign_id) REFERENCES campaigns(campaign_id));
CREATE TABLE IF NOT EXISTS contact_attributions(attribution_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,contact_id TEXT NOT NULL,source_id TEXT NOT NULL,touchpoint_id TEXT,attribution_type TEXT NOT NULL,attribution_weight REAL,confidence TEXT NOT NULL DEFAULT 'unknown',is_primary INTEGER NOT NULL DEFAULT 0,attributed_at INTEGER NOT NULL,metadata_json TEXT NOT NULL DEFAULT '{}',FOREIGN KEY(contact_id) REFERENCES contacts(contact_id),FOREIGN KEY(source_id) REFERENCES sources(source_id),FOREIGN KEY(touchpoint_id) REFERENCES source_touchpoints(touchpoint_id));
CREATE TABLE IF NOT EXISTS source_links(source_link_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,from_source_id TEXT NOT NULL,to_source_id TEXT NOT NULL,link_type TEXT NOT NULL,sort_order INTEGER NOT NULL DEFAULT 0,metadata_json TEXT NOT NULL DEFAULT '{}',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,FOREIGN KEY(from_source_id) REFERENCES sources(source_id),FOREIGN KEY(to_source_id) REFERENCES sources(source_id),UNIQUE(from_source_id,to_source_id,link_type));
CREATE INDEX IF NOT EXISTS idx_campaign_org ON campaigns(organization_id,workspace_id,status);
CREATE INDEX IF NOT EXISTS idx_touchpoint_contact_time ON source_touchpoints(organization_id,contact_id,occurred_at);
CREATE INDEX IF NOT EXISTS idx_touchpoint_source_time ON source_touchpoints(source_id,occurred_at);
CREATE INDEX IF NOT EXISTS idx_attribution_contact ON contact_attributions(organization_id,contact_id,attribution_type);
CREATE INDEX IF NOT EXISTS idx_contact_identity_lookup ON contact_identities(organization_id,platform_id,canonical_value);
CREATE INDEX IF NOT EXISTS idx_source_links_from ON source_links(organization_id,from_source_id);
"""
def ensure_v207_1(c):
 t=now_ms()
 # Remove the legacy fixed platform CHECK while retaining the compatibility channel column.
 sql=(c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='channel_accounts'").fetchone() or [''])[0] or ''
 if "CHECK(channel IN" in sql:
  c.execute('PRAGMA legacy_alter_table=ON')
  c.execute('ALTER TABLE channel_accounts RENAME TO channel_accounts_legacy_207')
  c.execute("CREATE TABLE channel_accounts(channel_account_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,channel TEXT NOT NULL,display_name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL)")
  c.execute('INSERT INTO channel_accounts(channel_account_id,organization_id,channel,display_name,status,created_at,updated_at) SELECT channel_account_id,organization_id,channel,display_name,status,created_at,updated_at FROM channel_accounts_legacy_207')
  c.execute('DROP TABLE channel_accounts_legacy_207')
  c.execute('PRAGMA legacy_alter_table=OFF')
 execute_sql_script(c,V207_1_SCHEMA)
 for table,fields in {
  'channel_accounts':[('platform_id','TEXT'),('account_type',"TEXT NOT NULL DEFAULT 'business_account'"),('metadata_json',"TEXT NOT NULL DEFAULT '{}'")],
  'channel_account_identities':[('platform_id','TEXT'),('is_primary','INTEGER NOT NULL DEFAULT 0'),('status',"TEXT NOT NULL DEFAULT 'active'"),('valid_from','INTEGER'),('valid_to','INTEGER'),('metadata_json',"TEXT NOT NULL DEFAULT '{}'")],
  'user_credentials':[('failed_attempts','INTEGER NOT NULL DEFAULT 0'),('locked_until','INTEGER'),('last_failed_at','INTEGER')],
   'sources':[('platform_id','TEXT'),('source_type',"TEXT NOT NULL DEFAULT 'unknown'"),('source_subtype','TEXT'),('direction',"TEXT NOT NULL DEFAULT 'inbound'"),('initiated_by',"TEXT NOT NULL DEFAULT 'unknown'"),('campaign_id','TEXT'),('parent_source_id','TEXT'),('external_key','TEXT'),('landing_url','TEXT'),('tracking_code','TEXT'),('updated_at','INTEGER')]
 }.items():
  for col,decl in fields:_add(c,table,col,decl)
 seed=[('whatsapp','WhatsApp','messaging'),('instagram','Instagram','social'),('facebook','Facebook','social'),('messenger','Messenger','messaging'),('telegram','Telegram','messaging'),('line','LINE','messaging'),('tiktok','TikTok','social'),('website','企业官网','owned'),('offline','线下','offline'),('google_ads','Google Ads','advertising'),('meta_ads','Meta Ads','advertising'),('import','数据导入','import')]
 for code,name,kind in seed:c.execute("INSERT OR IGNORE INTO platforms(platform_id,platform_code,platform_name,platform_kind,status,created_at,updated_at) VALUES(?,?,?,?,'active',?,?)",('plt_'+code,code,name,kind,t,t))
 c.execute("UPDATE channel_accounts SET platform_id=COALESCE(platform_id,'plt_'||channel)")
 c.execute("UPDATE channel_account_identities SET platform_id=COALESCE(platform_id,(SELECT platform_id FROM channel_accounts a WHERE a.channel_account_id=channel_account_id)),valid_from=COALESCE(valid_from,created_at)")
 c.execute("UPDATE sources SET platform_id=COALESCE(platform_id,'plt_'||channel),source_type=CASE WHEN source_type='unknown' THEN 'direct' ELSE source_type END,updated_at=COALESCE(updated_at,last_seen_at)")
 for key in ('platform.read','platform.manage','campaign.read','campaign.manage','touchpoint.read','touchpoint.manage','attribution.read','attribution.manage','contact.identity.manage'):
  c.execute('INSERT OR IGNORE INTO permissions(permission_key,description) VALUES(?,?)',(key,key));c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',('role_superadmin',key));c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',('role_orgadmin',key))
 # V207.1：只读与审计角色需要读取活动；使用 INSERT OR IGNORE 兼容已有数据库升级
 for role_id in ('role_readonly','role_auditor'):
  c.execute("INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?, 'campaign.read')",(role_id,))
 checksum=hashlib.sha256(V207_1_SCHEMA.encode()).hexdigest()
 existing=c.execute("SELECT checksum FROM schema_migrations WHERE migration_id='V207_100_channel_attribution'").fetchone()
 if existing and existing[0]!=checksum:raise RuntimeError('MIGRATION_CHECKSUM_MISMATCH: V207_100_channel_attribution')
 if not existing:
  c.execute("INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES('V207_100_channel_attribution','渠道平台、来源触点与客户归因兼容升级',?,?,?,?)",(checksum,t,'system',dumps({'status':'success'})))
 c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('product_version','207.1.0')")

V207_101_SCHEMA=r"""
CREATE UNIQUE INDEX IF NOT EXISTS uq_contact_identity_primary
ON contact_identities(organization_id,workspace_id,contact_id)
WHERE is_primary=1;
"""
def ensure_v207_101(c):
 t=now_ms();migration_id='V207_101_contact_identity_integrity';checksum=hashlib.sha256(V207_101_SCHEMA.encode()).hexdigest()
 existing=c.execute('SELECT checksum FROM schema_migrations WHERE migration_id=?',(migration_id,)).fetchone()
 if existing and existing[0]!=checksum:raise RuntimeError('MIGRATION_CHECKSUM_MISMATCH: '+str(locals().get('mid',locals().get('migration_id','UNKNOWN'))))
 if not existing:
  # Repair legacy duplicate primaries deterministically before installing the partial unique index.
  groups=list(c.execute('SELECT organization_id,workspace_id,contact_id FROM contact_identities WHERE is_primary=1 GROUP BY organization_id,workspace_id,contact_id HAVING count(*)>1'))
  repaired=0
  for org,wid,cid in groups:
   keep=c.execute('SELECT contact_identity_id FROM contact_identities WHERE organization_id=? AND workspace_id=? AND contact_id=? AND is_primary=1 ORDER BY first_seen_at,contact_identity_id LIMIT 1',(org,wid,cid)).fetchone()[0]
   cur=c.execute('UPDATE contact_identities SET is_primary=0 WHERE organization_id=? AND workspace_id=? AND contact_id=? AND is_primary=1 AND contact_identity_id<>?',(org,wid,cid,keep));repaired+=cur.rowcount
  execute_sql_script(c,V207_101_SCHEMA)
  # Dedicated permission replaces broad contact.update; copy grants to preserve existing roles.
  c.execute("INSERT OR IGNORE INTO permissions(permission_key,description) VALUES('contact.identity.manage','contact.identity.manage')")
  c.execute("INSERT OR IGNORE INTO role_permissions(role_id,permission_key) SELECT role_id,'contact.identity.manage' FROM role_permissions WHERE permission_key='contact.update'")
  c.execute('INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES(?,?,?,?,?,?)',(migration_id,'联系人身份主记录唯一性与专用权限加固',checksum,t,'system',dumps({'status':'success','duplicatePrimariesRepaired':repaired})))


V207_200_SCHEMA=r"""
CREATE UNIQUE INDEX IF NOT EXISTS uq_touchpoint_external_event ON source_touchpoints(organization_id,workspace_id,external_event_id) WHERE external_event_id IS NOT NULL AND external_event_id<>'';
CREATE INDEX IF NOT EXISTS idx_touchpoint_contact_occurred ON source_touchpoints(organization_id,workspace_id,contact_id,occurred_at,touchpoint_id);
CREATE INDEX IF NOT EXISTS idx_touchpoint_session ON source_touchpoints(organization_id,workspace_id,session_id,occurred_at);
CREATE INDEX IF NOT EXISTS idx_attribution_contact_rule ON contact_attributions(organization_id,workspace_id,contact_id,attribution_type);
CREATE UNIQUE INDEX IF NOT EXISTS uq_attribution_primary ON contact_attributions(organization_id,workspace_id,contact_id) WHERE is_primary=1;
CREATE INDEX IF NOT EXISTS idx_source_links_to ON source_links(organization_id,workspace_id,to_source_id);
"""
def ensure_v207_200(c):
 t=now_ms();mid='V207_200_touchpoint_attribution_path';checksum=hashlib.sha256(V207_200_SCHEMA.encode()).hexdigest()
 existing=c.execute('SELECT checksum FROM schema_migrations WHERE migration_id=?',(mid,)).fetchone()
 if existing and existing[0]!=checksum:raise RuntimeError('MIGRATION_CHECKSUM_MISMATCH: '+str(locals().get('mid',locals().get('migration_id','UNKNOWN'))))
 if not existing:
  repaired_events=repaired_primaries=0
  groups=list(c.execute("SELECT organization_id,workspace_id,external_event_id FROM source_touchpoints WHERE external_event_id IS NOT NULL AND external_event_id<>'' GROUP BY organization_id,workspace_id,external_event_id HAVING count(*)>1"))
  for org,wid,eid in groups:
   keep=c.execute('SELECT touchpoint_id FROM source_touchpoints WHERE organization_id=? AND workspace_id=? AND external_event_id=? ORDER BY occurred_at,touchpoint_id LIMIT 1',(org,wid,eid)).fetchone()[0]
   repaired_events+=c.execute('UPDATE source_touchpoints SET external_event_id=NULL WHERE organization_id=? AND workspace_id=? AND external_event_id=? AND touchpoint_id<>?',(org,wid,eid,keep)).rowcount
  groups=list(c.execute('SELECT organization_id,workspace_id,contact_id FROM contact_attributions WHERE is_primary=1 GROUP BY organization_id,workspace_id,contact_id HAVING count(*)>1'))
  for org,wid,cid in groups:
   keep=c.execute('SELECT attribution_id FROM contact_attributions WHERE organization_id=? AND workspace_id=? AND contact_id=? AND is_primary=1 ORDER BY attributed_at DESC,attribution_id DESC LIMIT 1',(org,wid,cid)).fetchone()[0]
   repaired_primaries+=c.execute('UPDATE contact_attributions SET is_primary=0 WHERE organization_id=? AND workspace_id=? AND contact_id=? AND is_primary=1 AND attribution_id<>?',(org,wid,cid,keep)).rowcount
  execute_sql_script(c,V207_200_SCHEMA)
  for key in ('source.path.read','source.path.manage','attribution.recalculate'):
   c.execute('INSERT OR IGNORE INTO permissions(permission_key,description) VALUES(?,?)',(key,key))
  grants={'role_superadmin':('source.path.read','source.path.manage','attribution.recalculate'),'role_orgadmin':('source.path.read','source.path.manage','attribution.recalculate'),'role_teamlead':('touchpoint.read','touchpoint.manage','attribution.read','attribution.recalculate','source.path.read','source.path.manage'),'role_operator':('touchpoint.read','touchpoint.manage','attribution.read','source.path.read'),'role_readonly':('touchpoint.read','attribution.read','source.path.read'),'role_auditor':('touchpoint.read','attribution.read','source.path.read')}
  for role,ps in grants.items():
   for key in ps:c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',(role,key))
  c.execute('INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES(?,?,?,?,?,?)',(mid,'客户旅程触点、归因与来源路径加固',checksum,t,'system',dumps({'status':'success','duplicateExternalEventsRepaired':repaired_events,'duplicatePrimariesRepaired':repaired_primaries})))
 c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('product_version','207.2.0-dev')")

V207_300_SCHEMA=r"""
CREATE TABLE IF NOT EXISTS departments(
 department_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,parent_department_id TEXT,
 name TEXT NOT NULL,code TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'active',
 created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
 FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(parent_department_id) REFERENCES departments(department_id),
 UNIQUE(organization_id,code),UNIQUE(organization_id,parent_department_id,name));
CREATE TABLE IF NOT EXISTS business_lines(
 business_line_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,parent_business_line_id TEXT,
 name TEXT NOT NULL,code TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'active',
 created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
 FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(parent_business_line_id) REFERENCES business_lines(business_line_id),
 UNIQUE(organization_id,code),UNIQUE(organization_id,parent_business_line_id,name));
CREATE TABLE IF NOT EXISTS markets(
 market_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,parent_market_id TEXT,
 name TEXT NOT NULL,code TEXT NOT NULL,market_type TEXT NOT NULL DEFAULT 'country',country_code TEXT NOT NULL DEFAULT '',
 region_code TEXT NOT NULL DEFAULT '',timezone TEXT NOT NULL DEFAULT '',description TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'active',
 created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
 FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(parent_market_id) REFERENCES markets(market_id),
 UNIQUE(organization_id,code),UNIQUE(organization_id,parent_market_id,name));
CREATE TABLE IF NOT EXISTS workspace_teams(
 workspace_id TEXT NOT NULL,team_id TEXT NOT NULL,organization_id TEXT NOT NULL,relation_type TEXT NOT NULL DEFAULT 'collaborator',
 is_primary INTEGER NOT NULL DEFAULT 0,access_level TEXT NOT NULL DEFAULT 'operate',status TEXT NOT NULL DEFAULT 'active',
 created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,PRIMARY KEY(workspace_id,team_id),
 FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),FOREIGN KEY(team_id) REFERENCES teams(team_id),FOREIGN KEY(organization_id) REFERENCES organizations(organization_id));
CREATE TABLE IF NOT EXISTS workspace_business_lines(
 workspace_id TEXT NOT NULL,business_line_id TEXT NOT NULL,organization_id TEXT NOT NULL,is_primary INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'active',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,PRIMARY KEY(workspace_id,business_line_id),
 FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),FOREIGN KEY(business_line_id) REFERENCES business_lines(business_line_id),FOREIGN KEY(organization_id) REFERENCES organizations(organization_id));
CREATE TABLE IF NOT EXISTS workspace_markets(
 workspace_id TEXT NOT NULL,market_id TEXT NOT NULL,organization_id TEXT NOT NULL,is_primary INTEGER NOT NULL DEFAULT 0,
 scope_type TEXT NOT NULL DEFAULT 'direct',status TEXT NOT NULL DEFAULT 'active',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
 PRIMARY KEY(workspace_id,market_id),FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
 FOREIGN KEY(market_id) REFERENCES markets(market_id),FOREIGN KEY(organization_id) REFERENCES organizations(organization_id));
CREATE INDEX IF NOT EXISTS idx_department_org_parent ON departments(organization_id,parent_department_id,status);
CREATE INDEX IF NOT EXISTS idx_business_line_org_parent ON business_lines(organization_id,parent_business_line_id,status);
CREATE INDEX IF NOT EXISTS idx_market_org_parent ON markets(organization_id,parent_market_id,status);
CREATE INDEX IF NOT EXISTS idx_workspace_team_org ON workspace_teams(organization_id,team_id,status);
CREATE INDEX IF NOT EXISTS idx_workspace_bl_org ON workspace_business_lines(organization_id,business_line_id,status);
CREATE INDEX IF NOT EXISTS idx_workspace_market_org ON workspace_markets(organization_id,market_id,status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_primary_team ON workspace_teams(workspace_id) WHERE is_primary=1 AND status='active';
CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_primary_bl ON workspace_business_lines(workspace_id) WHERE is_primary=1 AND status='active';
CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_primary_market ON workspace_markets(workspace_id) WHERE is_primary=1 AND status='active';
"""
def ensure_v207_300(c):
 t=now_ms();mid='V207_300_organization_operating_model';checksum=hashlib.sha256(V207_300_SCHEMA.encode()).hexdigest()
 existing=c.execute('SELECT checksum FROM schema_migrations WHERE migration_id=?',(mid,)).fetchone()
 if existing and existing[0]!=checksum:raise RuntimeError('MIGRATION_CHECKSUM_MISMATCH: '+str(locals().get('mid',locals().get('migration_id','UNKNOWN'))))
 if not existing:
  execute_sql_script(c,V207_300_SCHEMA)
  _add(c,'teams','department_id','TEXT')
  for col,decl in [('organization_id','TEXT'),('team_id','TEXT'),('request_id','TEXT'),('ip_address','TEXT'),('user_agent','TEXT')]:_add(c,'audit_logs',col,decl)
  # Preserve the legacy one-team/one-workspace relation as the primary compatibility link.
  migrated=0
  for team in c.execute("SELECT team_id,organization_id,workspace_id,created_at,updated_at FROM teams WHERE workspace_id IS NOT NULL AND workspace_id<>''").fetchall():
   w=c.execute('SELECT organization_id FROM workspaces WHERE workspace_id=?',(team['workspace_id'],)).fetchone()
   if w and w[0]==team['organization_id']:
    before=c.total_changes;c.execute("INSERT OR IGNORE INTO workspace_teams(workspace_id,team_id,organization_id,relation_type,is_primary,access_level,status,created_at,updated_at) VALUES(?,?,?,'primary',1,'manage','active',?,?)",(team['workspace_id'],team['team_id'],team['organization_id'],team['created_at'],team['updated_at']));migrated+=c.total_changes-before
  for key in ('organization.structure.read','organization.structure.manage'):
   c.execute('INSERT OR IGNORE INTO permissions(permission_key,description) VALUES(?,?)',(key,key))
  for role in ('role_superadmin','role_orgadmin'):
   for key in ('organization.structure.read','organization.structure.manage'):c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',(role,key))
  for role in ('role_auditor',):c.execute("INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,'organization.structure.read')",(role,))
  c.execute('INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES(?,?,?,?,?,?)',(mid,'部门、业务线、市场与业务空间多维关系升级',checksum,t,'system',dumps({'status':'success','legacyWorkspaceTeamLinksMigrated':migrated})))
 c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('product_version',?)",(PRODUCT_VERSION,))

V207_301_SCHEMA=r"""
-- 标签分类：status（业务状态标签）vs portrait（客户画像标签）
"""
def ensure_v207_301(c):
 t=now_ms();mid='V207_301_tag_kind';checksum=hashlib.sha256(V207_301_SCHEMA.encode()).hexdigest()
 existing=c.execute('SELECT checksum FROM schema_migrations WHERE migration_id=?',(mid,)).fetchone()
 if existing and existing[0]!=checksum:raise RuntimeError('MIGRATION_CHECKSUM_MISMATCH: '+str(locals().get('mid',locals().get('migration_id','UNKNOWN'))))
 if not existing:
  # Add tag_kind column with CHECK constraint
  _add(c,'tags','tag_kind',"TEXT NOT NULL DEFAULT 'portrait' CHECK(tag_kind IN ('status','portrait'))")
  # Backfill existing tags: if category contains '状态'/'status', mark as status; otherwise portrait
  c.execute("UPDATE tags SET tag_kind='status' WHERE category LIKE '%状态%' OR category LIKE '%status%' OR category LIKE '%Status%'")
  # Create index for efficient filtering
  c.execute('CREATE INDEX IF NOT EXISTS idx_tags_workspace_kind ON tags(workspace_id,tag_kind,enabled,sort_order)')
  c.execute('INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES(?,?,?,?,?,?)',(mid,'标签分类：状态类与画像类',checksum,t,'system',dumps({'status':'success','backfilledStatusTags':c.total_changes})))

def ensure_v207(c,fresh=False):
 execute_sql_script(c,V207_SCHEMA)
 for table,fields in {'workspaces':[('organization_id','TEXT')],'sources':[('organization_id','TEXT'),('team_id','TEXT'),('channel_account_id','TEXT')],'devices':[('organization_id','TEXT'),('team_id','TEXT'),('assigned_user_id','TEXT'),('system_device_name','TEXT'),('system_computer_name','TEXT'),('user_device_alias','TEXT'),('user_computer_alias','TEXT'),('admin_device_name','TEXT'),('admin_computer_name','TEXT'),('binding_code','TEXT'),('binding_code_expires_at','INTEGER')],'contacts':[('organization_id','TEXT'),('team_id','TEXT')],'events':[('user_id','TEXT') ]}.items():
  for col,decl in fields:_add(c,table,col,decl)
 # 已有库只做严格预检；禁止推断、回填或创建任何默认租户。
 if not fresh:
  checks=(('workspaces','organization_id IS NULL'),('sources','organization_id IS NULL OR team_id IS NULL'),('devices','organization_id IS NULL OR team_id IS NULL'),('contacts','organization_id IS NULL OR team_id IS NULL'))
  missing={table:c.execute('SELECT count(*) FROM '+table+' WHERE '+where).fetchone()[0] for table,where in checks}
  missing={k:v for k,v in missing.items() if v}
  if missing:raise RuntimeError('LEGACY_SCOPE_MIGRATION_REQUIRED: '+dumps(missing)+'；请从备份执行显式离线归属迁移。')
 for x in PERMS:c.execute('INSERT OR IGNORE INTO permissions(permission_key,description) VALUES(?,?)',(x,x))
 roles={'role_superadmin':('平台超级管理员','organization',PERMS),'role_orgadmin':('企业管理员','organization',PERMS),'role_teamlead':('团队主管','team',['team.read','user.read','account.read','source.read','device.read','device.disable','device.bind','contact.read','contact.update','contact.delete','contact.restore','audit.read']),'role_operator':('操作员','team',['team.read','account.read','source.read','device.read','device.rename.self','contact.read','contact.update']),'role_readonly':('只读用户','team',['team.read','account.read','source.read','campaign.read','device.read','contact.read']),'role_auditor':('审计员','organization',['organization.read','team.read','user.read','role.read','account.read','source.read','campaign.read','device.read','contact.read','audit.read'])}
 for rid,(name,scope,ps) in roles.items():
  c.execute('INSERT OR IGNORE INTO roles(role_id,organization_id,name,scope_level,status) VALUES(?,?,?,?,?)',(rid,None,name,scope,'active'))
  for x in ps:c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',(rid,x))



# V207.5 / Schema 208：完整审计与组织模型安全基线。
V208_STAGES={
 'V208_000_preflight':'只读完整性、租户归属、孤立关系与层级循环预检',
 'V208_010_scope_hardening':'默认租户清理后的显式作用域门禁',
 'V208_020_organization_model':'部门、市场、业务线与团队关系模型基线',
 'V208_030_foreign_key_baseline':'核心物理外键、跨企业组合约束与主关系唯一性',
 'V208_040_catalog_baseline':'中文数据字典 208.0 基线',
 'V208_050_identity_rbac_foreign_keys':'身份、认证、成员关系与角色权限物理外键基线'}
V208_SIGNATURE="""Schema 208 / catalog 208.0
markets:+local_name,+currency_code,+sort_order
business_lines:+sort_order; departments:+sort_order
team_markets(team,market,organization,is_primary,scope_type,status,timestamps)
team_business_lines(team,business_line,organization,is_primary,status,timestamps)
audit_logs:+scope_type,+scope_id
cross-tenant triggers; hierarchy-cycle triggers; one active primary relation
"""
V208_IDENTITY_SIGNATURE="""identity-rbac foreign keys v1
workspaces/users/roles -> organizations
sessions/user_credentials -> users
role_permissions -> roles/permissions
organization_memberships -> users/organizations/roles
team_memberships -> users/teams/roles
membership scope triggers; all delete/update actions NO ACTION
"""
def _v208_checksum(mid):
 payload=mid+'\n'+V208_SIGNATURE
 if mid=='V208_050_identity_rbac_foreign_keys':payload+='\n'+V208_IDENTITY_SIGNATURE
 return hashlib.sha256(payload.encode()).hexdigest()

def _table_exists(c,name):return bool(c.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?",(name,)).fetchone())
def _v208_record(c,mid,result=None):
 checksum=_v208_checksum(mid);old=c.execute('SELECT checksum FROM schema_migrations WHERE migration_id=?',(mid,)).fetchone()
 if old and old[0]!=checksum:raise RuntimeError('MIGRATION_CHECKSUM_MISMATCH: '+mid)
 if not old:c.execute('INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES(?,?,?,?,?,?)',(mid,V208_STAGES[mid],checksum,now_ms(),'system',dumps(result or {'status':'success'})))

def _hierarchy_cycle(c,table,key,parent):
 # 只读递归检查；发现任一闭环即阻断，不自动修复历史数据。
 q=f"""WITH RECURSIVE walk(root,node,path,cycle) AS (
 SELECT {key},{parent},','||{key}||',',0 FROM {table} WHERE {parent} IS NOT NULL
 UNION ALL SELECT walk.root,t.{parent},walk.path||t.{key}||',',instr(walk.path,','||t.{key}||',')>0
 FROM walk JOIN {table} t ON t.{key}=walk.node WHERE walk.node IS NOT NULL AND walk.cycle=0)
 SELECT 1 FROM walk WHERE cycle=1 LIMIT 1"""
 return bool(c.execute(q).fetchone())

def preflight_v208(c):
 if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('PRECHECK_QUICK_CHECK_FAILED')
 if list(c.execute('PRAGMA foreign_key_check')):raise RuntimeError('PRECHECK_FOREIGN_KEY_FAILED')
 checks=[]
 for table,where in (('workspaces','organization_id IS NULL OR organization_id=""'),('teams','organization_id IS NULL OR organization_id=""'),('sources','organization_id IS NULL OR organization_id="" OR team_id IS NULL OR team_id=""'),('devices','organization_id IS NULL OR organization_id="" OR team_id IS NULL OR team_id=""'),('contacts','organization_id IS NULL OR organization_id="" OR team_id IS NULL OR team_id=""')):
  if _table_exists(c,table):
   n=c.execute('SELECT count(*) FROM '+table+' WHERE '+where).fetchone()[0]
   if n:checks.append((table,n))
 if checks:raise RuntimeError('LEGACY_SCOPE_MIGRATION_REQUIRED: '+dumps(dict(checks)))
 cross=[]
 tests=(
  ('teams/workspaces','SELECT count(*) FROM teams t JOIN workspaces w ON w.workspace_id=t.workspace_id WHERE t.organization_id<>w.organization_id'),
  ('teams/departments','SELECT count(*) FROM teams t JOIN departments d ON d.department_id=t.department_id WHERE t.department_id IS NOT NULL AND t.organization_id<>d.organization_id'),
  ('workspace_teams','SELECT count(*) FROM workspace_teams r JOIN workspaces w ON w.workspace_id=r.workspace_id JOIN teams t ON t.team_id=r.team_id WHERE r.organization_id<>w.organization_id OR r.organization_id<>t.organization_id'),
  ('workspace_markets','SELECT count(*) FROM workspace_markets r JOIN workspaces w ON w.workspace_id=r.workspace_id JOIN markets m ON m.market_id=r.market_id WHERE r.organization_id<>w.organization_id OR r.organization_id<>m.organization_id'),
  ('workspace_business_lines','SELECT count(*) FROM workspace_business_lines r JOIN workspaces w ON w.workspace_id=r.workspace_id JOIN business_lines b ON b.business_line_id=r.business_line_id WHERE r.organization_id<>w.organization_id OR r.organization_id<>b.organization_id'))
 for name,sql in tests:
  try:n=c.execute(sql).fetchone()[0]
  except sqlite3.OperationalError:n=0
  if n:cross.append((name,n))
 if cross:raise RuntimeError('CROSS_TENANT_REFERENCE_DETECTED: '+dumps(dict(cross)))
 for table,key,parent in (('departments','department_id','parent_department_id'),('markets','market_id','parent_market_id'),('business_lines','business_line_id','parent_business_line_id')):
  if _table_exists(c,table) and _hierarchy_cycle(c,table,key,parent):raise RuntimeError('HIERARCHY_CYCLE_DETECTED: '+table)
 return {'status':'success','scopeIssues':0,'crossTenantIssues':0,'hierarchyCycles':0}

def _teams_fk_ready(c):
 expected={('department_id','departments','department_id'),('workspace_id','workspaces','workspace_id'),('organization_id','organizations','organization_id')}
 actual={(r['from'],r['table'],r['to']) for r in c.execute('PRAGMA foreign_key_list(teams)')}
 return expected.issubset(actual)

def _ensure_teams_fk_baseline(c):
 """以显式字段映射重建 teams；调用方必须在事务前关闭 foreign_keys。"""
 if _teams_fk_ready(c):return False
 if c.execute('PRAGMA foreign_keys').fetchone()[0]:raise RuntimeError('TEAMS_REBUILD_REQUIRES_FOREIGN_KEYS_OFF')
 required={'team_id','organization_id','workspace_id','department_id','name','status','created_at','updated_at'}
 columns={r['name'] for r in c.execute('PRAGMA table_info(teams)')}
 if not required.issubset(columns):raise RuntimeError('TEAMS_SCHEMA_UNEXPECTED: '+dumps(sorted(columns)))
 invalid={
  'organization':c.execute("SELECT count(*) FROM teams t LEFT JOIN organizations o ON o.organization_id=t.organization_id WHERE o.organization_id IS NULL").fetchone()[0],
  'workspace':c.execute("SELECT count(*) FROM teams t LEFT JOIN workspaces w ON w.workspace_id=t.workspace_id WHERE w.workspace_id IS NULL OR w.organization_id<>t.organization_id").fetchone()[0],
  'department':c.execute("SELECT count(*) FROM teams t LEFT JOIN departments d ON d.department_id=t.department_id WHERE t.department_id IS NOT NULL AND (d.department_id IS NULL OR d.organization_id<>t.organization_id)").fetchone()[0]}
 invalid={k:v for k,v in invalid.items() if v}
 if invalid:raise RuntimeError('TEAMS_FOREIGN_KEY_BASELINE_BLOCKED: '+dumps(invalid))
 before=c.execute('SELECT count(*) FROM teams').fetchone()[0]
 c.execute('PRAGMA legacy_alter_table=ON')
 c.execute('ALTER TABLE teams RENAME TO teams__v208_old')
 c.execute("""CREATE TABLE teams(
  team_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,
  name TEXT NOT NULL,status TEXT NOT NULL,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
  department_id TEXT,
  UNIQUE(organization_id,workspace_id,name),
  FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
  FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
  FOREIGN KEY(department_id) REFERENCES departments(department_id))""")
 c.execute("""INSERT INTO teams(team_id,organization_id,workspace_id,name,status,created_at,updated_at,department_id)
 SELECT team_id,organization_id,workspace_id,name,status,created_at,updated_at,department_id FROM teams__v208_old""")
 after=c.execute('SELECT count(*) FROM teams').fetchone()[0]
 if before!=after:raise RuntimeError('TEAMS_REBUILD_ROW_COUNT_MISMATCH')
 c.execute('DROP TABLE teams__v208_old')
 c.execute('PRAGMA legacy_alter_table=OFF')
 if not _teams_fk_ready(c):raise RuntimeError('TEAMS_FOREIGN_KEY_BASELINE_MISSING')
 return True

def _ensure_hierarchy_guards(c):
 specs=(('department','departments','department_id','parent_department_id'),('market','markets','market_id','parent_market_id'),('business_line','business_lines','business_line_id','parent_business_line_id'))
 made=[]
 for label,table,key,parent in specs:
  for action in ('insert','update'):
   name=f'trg_{label}_cycle_{action}'
   event='INSERT' if action=='insert' else f'UPDATE OF {parent},organization_id'
   sql=f"""CREATE TRIGGER IF NOT EXISTS {name} BEFORE {event} ON {table}
   WHEN NEW.{parent} IS NOT NULL BEGIN
    SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM {table} p WHERE p.{key}=NEW.{parent} AND p.organization_id=NEW.organization_id)
     THEN RAISE(ABORT,'CROSS_TENANT_HIERARCHY_REFERENCE') END;
    WITH RECURSIVE ancestors(id) AS (
     SELECT NEW.{parent} UNION ALL
     SELECT p.{parent} FROM {table} p JOIN ancestors a ON p.{key}=a.id WHERE p.{parent} IS NOT NULL)
    SELECT CASE WHEN EXISTS(SELECT 1 FROM ancestors WHERE id=NEW.{key})
     THEN RAISE(ABORT,'HIERARCHY_CYCLE_DETECTED') END;
   END"""
   c.execute(sql);made.append(name)
 return made

IDENTITY_FK_EXPECTED={
 'workspaces':{('organization_id','organizations','organization_id')},
 'users':{('organization_id','organizations','organization_id')},
 'sessions':{('user_id','users','user_id')},
 'user_credentials':{('user_id','users','user_id')},
 'roles':{('organization_id','organizations','organization_id')},
 'role_permissions':{('role_id','roles','role_id'),('permission_key','permissions','permission_key')},
 'organization_memberships':{('user_id','users','user_id'),('organization_id','organizations','organization_id'),('role_id','roles','role_id')},
 'team_memberships':{('user_id','users','user_id'),('team_id','teams','team_id'),('role_id','roles','role_id')}}
IDENTITY_SCOPE_TRIGGERS={
 'trg_org_membership_scope_insert':"""CREATE TRIGGER IF NOT EXISTS trg_org_membership_scope_insert BEFORE INSERT ON organization_memberships BEGIN SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users u JOIN roles r ON r.role_id=NEW.role_id WHERE u.user_id=NEW.user_id AND u.organization_id=NEW.organization_id AND (r.organization_id IS NULL OR r.organization_id=NEW.organization_id)) THEN RAISE(ABORT,'MEMBERSHIP_SCOPE_INVALID') END; END""",
 'trg_org_membership_scope_update':"""CREATE TRIGGER IF NOT EXISTS trg_org_membership_scope_update BEFORE UPDATE OF user_id,organization_id,role_id ON organization_memberships BEGIN SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users u JOIN roles r ON r.role_id=NEW.role_id WHERE u.user_id=NEW.user_id AND u.organization_id=NEW.organization_id AND (r.organization_id IS NULL OR r.organization_id=NEW.organization_id)) THEN RAISE(ABORT,'MEMBERSHIP_SCOPE_INVALID') END; END""",
 'trg_team_membership_scope_insert':"""CREATE TRIGGER IF NOT EXISTS trg_team_membership_scope_insert BEFORE INSERT ON team_memberships BEGIN SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users u JOIN teams t JOIN roles r ON r.role_id=NEW.role_id WHERE u.user_id=NEW.user_id AND t.team_id=NEW.team_id AND u.organization_id=t.organization_id AND (r.organization_id IS NULL OR r.organization_id=t.organization_id)) THEN RAISE(ABORT,'MEMBERSHIP_SCOPE_INVALID') END; END""",
 'trg_team_membership_scope_update':"""CREATE TRIGGER IF NOT EXISTS trg_team_membership_scope_update BEFORE UPDATE OF user_id,team_id,role_id ON team_memberships BEGIN SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users u JOIN teams t JOIN roles r ON r.role_id=NEW.role_id WHERE u.user_id=NEW.user_id AND t.team_id=NEW.team_id AND u.organization_id=t.organization_id AND (r.organization_id IS NULL OR r.organization_id=t.organization_id)) THEN RAISE(ABORT,'MEMBERSHIP_SCOPE_INVALID') END; END"""}

def _identity_fk_ready(c):
 for table,expected in IDENTITY_FK_EXPECTED.items():
  actual={(r['from'],r['table'],r['to']) for r in c.execute('PRAGMA foreign_key_list('+table+')')}
  if not expected.issubset(actual):return False
 return True

def _identity_preflight(c):
 checks={
  'workspaces.organization':"SELECT count(*) FROM workspaces x LEFT JOIN organizations p ON p.organization_id=x.organization_id WHERE x.organization_id IS NULL OR x.organization_id='' OR p.organization_id IS NULL",
  'users.organization':"SELECT count(*) FROM users x LEFT JOIN organizations p ON p.organization_id=x.organization_id WHERE p.organization_id IS NULL",
  'sessions.user':"SELECT count(*) FROM sessions x LEFT JOIN users p ON p.user_id=x.user_id WHERE p.user_id IS NULL",
  'user_credentials.user':"SELECT count(*) FROM user_credentials x LEFT JOIN users p ON p.user_id=x.user_id WHERE p.user_id IS NULL",
  'roles.organization':"SELECT count(*) FROM roles x LEFT JOIN organizations p ON p.organization_id=x.organization_id WHERE x.organization_id IS NOT NULL AND p.organization_id IS NULL",
  'role_permissions.role':"SELECT count(*) FROM role_permissions x LEFT JOIN roles p ON p.role_id=x.role_id WHERE p.role_id IS NULL",
  'role_permissions.permission':"SELECT count(*) FROM role_permissions x LEFT JOIN permissions p ON p.permission_key=x.permission_key WHERE p.permission_key IS NULL",
  'organization_memberships.scope':"SELECT count(*) FROM organization_memberships m LEFT JOIN users u ON u.user_id=m.user_id LEFT JOIN organizations o ON o.organization_id=m.organization_id LEFT JOIN roles r ON r.role_id=m.role_id WHERE u.user_id IS NULL OR o.organization_id IS NULL OR r.role_id IS NULL OR u.organization_id<>m.organization_id OR (r.organization_id IS NOT NULL AND r.organization_id<>m.organization_id)",
  'team_memberships.scope':"SELECT count(*) FROM team_memberships m LEFT JOIN users u ON u.user_id=m.user_id LEFT JOIN teams t ON t.team_id=m.team_id LEFT JOIN roles r ON r.role_id=m.role_id WHERE u.user_id IS NULL OR t.team_id IS NULL OR r.role_id IS NULL OR u.organization_id<>t.organization_id OR (r.organization_id IS NOT NULL AND r.organization_id<>t.organization_id)"}
 bad={k:c.execute(sql).fetchone()[0] for k,sql in checks.items()}
 bad={k:v for k,v in bad.items() if v}
 if bad:raise RuntimeError('IDENTITY_RBAC_FOREIGN_KEY_BASELINE_BLOCKED: '+dumps(bad))
 return checks

def _rebuild_identity_table(c,table,columns,ddl):
 actual=[r['name'] for r in c.execute('PRAGMA table_info('+table+')')]
 if set(actual)!=set(columns):raise RuntimeError('IDENTITY_RBAC_SCHEMA_UNEXPECTED: '+table+':'+dumps(actual))
 before=c.execute('SELECT count(*) FROM '+table).fetchone()[0]
 old=table+'__v208_050_old'
 c.execute('ALTER TABLE '+table+' RENAME TO '+old)
 c.execute(ddl)
 names=','.join(columns)
 c.execute('INSERT INTO '+table+'('+names+') SELECT '+names+' FROM '+old)
 after=c.execute('SELECT count(*) FROM '+table).fetchone()[0]
 if before!=after:raise RuntimeError('IDENTITY_RBAC_ROW_COUNT_MISMATCH: '+table)
 c.execute('DROP TABLE '+old)
 return before

def _ensure_identity_rbac_fk_baseline(c):
 _identity_preflight(c)
 if not _identity_fk_ready(c):
  if c.execute('PRAGMA foreign_keys').fetchone()[0]:raise RuntimeError('IDENTITY_RBAC_REBUILD_REQUIRES_FOREIGN_KEYS_OFF')
  definitions=(
   ('workspaces',['workspace_id','name','status','created_at','updated_at','organization_id'],"CREATE TABLE workspaces(workspace_id TEXT PRIMARY KEY,name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,organization_id TEXT NOT NULL,FOREIGN KEY(organization_id) REFERENCES organizations(organization_id) ON UPDATE NO ACTION ON DELETE NO ACTION)"),
   ('users',['user_id','organization_id','login_name','display_name','status','created_at','updated_at'],"CREATE TABLE users(user_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,login_name TEXT NOT NULL COLLATE NOCASE,display_name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,UNIQUE(organization_id,login_name),FOREIGN KEY(organization_id) REFERENCES organizations(organization_id) ON UPDATE NO ACTION ON DELETE NO ACTION)"),
   ('roles',['role_id','organization_id','name','scope_level','status'],"CREATE TABLE roles(role_id TEXT PRIMARY KEY,organization_id TEXT,name TEXT NOT NULL,scope_level TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',UNIQUE(organization_id,name),FOREIGN KEY(organization_id) REFERENCES organizations(organization_id) ON UPDATE NO ACTION ON DELETE NO ACTION)"),
   ('sessions',['session_id','user_id','access_token_hash','expires_at','ip','user_agent','created_at','last_seen_at','revoked_at'],"CREATE TABLE sessions(session_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,access_token_hash TEXT NOT NULL UNIQUE,expires_at INTEGER NOT NULL,ip TEXT,user_agent TEXT,created_at INTEGER NOT NULL,last_seen_at INTEGER NOT NULL,revoked_at INTEGER,FOREIGN KEY(user_id) REFERENCES users(user_id) ON UPDATE NO ACTION ON DELETE NO ACTION)"),
   ('user_credentials',['user_id','password_hash','salt','iterations','must_change','updated_at','failed_attempts','locked_until','last_failed_at'],"CREATE TABLE user_credentials(user_id TEXT PRIMARY KEY,password_hash TEXT NOT NULL,salt TEXT NOT NULL,iterations INTEGER NOT NULL,must_change INTEGER NOT NULL DEFAULT 1,updated_at INTEGER NOT NULL,failed_attempts INTEGER NOT NULL DEFAULT 0,locked_until INTEGER,last_failed_at INTEGER,FOREIGN KEY(user_id) REFERENCES users(user_id) ON UPDATE NO ACTION ON DELETE NO ACTION)"),
   ('role_permissions',['role_id','permission_key'],"CREATE TABLE role_permissions(role_id TEXT NOT NULL,permission_key TEXT NOT NULL,PRIMARY KEY(role_id,permission_key),FOREIGN KEY(role_id) REFERENCES roles(role_id) ON UPDATE NO ACTION ON DELETE NO ACTION,FOREIGN KEY(permission_key) REFERENCES permissions(permission_key) ON UPDATE NO ACTION ON DELETE NO ACTION)"),
   ('organization_memberships',['user_id','organization_id','role_id','status'],"CREATE TABLE organization_memberships(user_id TEXT NOT NULL,organization_id TEXT NOT NULL,role_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',PRIMARY KEY(user_id,organization_id,role_id),FOREIGN KEY(user_id) REFERENCES users(user_id) ON UPDATE NO ACTION ON DELETE NO ACTION,FOREIGN KEY(organization_id) REFERENCES organizations(organization_id) ON UPDATE NO ACTION ON DELETE NO ACTION,FOREIGN KEY(role_id) REFERENCES roles(role_id) ON UPDATE NO ACTION ON DELETE NO ACTION)"),
   ('team_memberships',['user_id','team_id','role_id','status'],"CREATE TABLE team_memberships(user_id TEXT NOT NULL,team_id TEXT NOT NULL,role_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',PRIMARY KEY(user_id,team_id,role_id),FOREIGN KEY(user_id) REFERENCES users(user_id) ON UPDATE NO ACTION ON DELETE NO ACTION,FOREIGN KEY(team_id) REFERENCES teams(team_id) ON UPDATE NO ACTION ON DELETE NO ACTION,FOREIGN KEY(role_id) REFERENCES roles(role_id) ON UPDATE NO ACTION ON DELETE NO ACTION)"))
  c.execute('PRAGMA legacy_alter_table=ON')
  counts={}
  try:
   for table,columns,ddl in definitions:counts[table]=_rebuild_identity_table(c,table,columns,ddl)
  finally:c.execute('PRAGMA legacy_alter_table=OFF')
 else:counts={t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in IDENTITY_FK_EXPECTED}
 for sql in IDENTITY_SCOPE_TRIGGERS.values():c.execute(sql)
 if not _identity_fk_ready(c):raise RuntimeError('IDENTITY_RBAC_FOREIGN_KEY_BASELINE_MISSING')
 fk=list(c.execute('PRAGMA foreign_key_check'))
 if fk:raise RuntimeError('IDENTITY_RBAC_FOREIGN_KEY_CHECK_FAILED: '+str(len(fk)))
 return {'status':'success','foreignKeys':13,'scopeTriggers':4,'rows':counts}

def _assert_v208_objects(c):
 if not _teams_fk_ready(c):raise RuntimeError('V208_OBJECT_ASSERTION_FAILED: teams foreign keys')
 if not _identity_fk_ready(c):raise RuntimeError('V208_OBJECT_ASSERTION_FAILED: identity rbac foreign keys')
 required={'trg_department_cycle_insert','trg_department_cycle_update','trg_market_cycle_insert','trg_market_cycle_update','trg_business_line_cycle_insert','trg_business_line_cycle_update'} | set(IDENTITY_SCOPE_TRIGGERS)
 actual={r[0] for r in c.execute("SELECT name FROM sqlite_schema WHERE type='trigger'")}
 missing=sorted(required-actual)
 if missing:raise RuntimeError('V208_OBJECT_ASSERTION_FAILED: '+dumps(missing))

def ensure_v208(c):
 # 六阶段均有独立、稳定校验和；重复执行只校验，不重复生成数据。
 result=preflight_v208(c);_v208_record(c,'V208_000_preflight',result)
 _v208_record(c,'V208_010_scope_hardening',{'status':'success','implicitDefaults':False})
 for table,fields in {
  'departments':[('sort_order','INTEGER NOT NULL DEFAULT 0')],
  'business_lines':[('sort_order','INTEGER NOT NULL DEFAULT 0')],
  'markets':[('local_name',"TEXT NOT NULL DEFAULT ''"),('currency_code',"TEXT NOT NULL DEFAULT ''"),('sort_order','INTEGER NOT NULL DEFAULT 0')],
  'audit_logs':[('scope_type',"TEXT NOT NULL DEFAULT 'workspace'"),('scope_id','TEXT')]
 }.items():
  for col,decl in fields:_add(c,table,col,decl)
 _ensure_teams_fk_baseline(c)
 for sql in (
  """CREATE TABLE IF NOT EXISTS team_markets(team_id TEXT NOT NULL,market_id TEXT NOT NULL,organization_id TEXT NOT NULL,is_primary INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0,1)),scope_type TEXT NOT NULL DEFAULT 'direct' CHECK(scope_type IN ('direct','descendants')),status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,PRIMARY KEY(team_id,market_id),FOREIGN KEY(team_id) REFERENCES teams(team_id),FOREIGN KEY(market_id) REFERENCES markets(market_id),FOREIGN KEY(organization_id) REFERENCES organizations(organization_id))""",
  """CREATE TABLE IF NOT EXISTS team_business_lines(team_id TEXT NOT NULL,business_line_id TEXT NOT NULL,organization_id TEXT NOT NULL,is_primary INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0,1)),status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,PRIMARY KEY(team_id,business_line_id),FOREIGN KEY(team_id) REFERENCES teams(team_id),FOREIGN KEY(business_line_id) REFERENCES business_lines(business_line_id),FOREIGN KEY(organization_id) REFERENCES organizations(organization_id))""",
  "CREATE UNIQUE INDEX IF NOT EXISTS uq_team_primary_market ON team_markets(team_id) WHERE is_primary=1 AND status='active'",
  "CREATE UNIQUE INDEX IF NOT EXISTS uq_team_primary_business_line ON team_business_lines(team_id) WHERE is_primary=1 AND status='active'",
  'CREATE INDEX IF NOT EXISTS idx_team_markets_org_market ON team_markets(organization_id,market_id,status)',
  'CREATE INDEX IF NOT EXISTS idx_team_bl_org_line ON team_business_lines(organization_id,business_line_id,status)'):c.execute(sql)
 _v208_record(c,'V208_020_organization_model',{'status':'success','tables':['team_markets','team_business_lines']})
 triggers={
 'trg_team_market_scope_insert':"""CREATE TRIGGER IF NOT EXISTS trg_team_market_scope_insert BEFORE INSERT ON team_markets BEGIN SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM teams t JOIN markets m ON m.market_id=NEW.market_id WHERE t.team_id=NEW.team_id AND t.organization_id=NEW.organization_id AND m.organization_id=NEW.organization_id) THEN RAISE(ABORT,'CROSS_TENANT_REFERENCE_DETECTED') END; END""",
 'trg_team_market_scope_update':"""CREATE TRIGGER IF NOT EXISTS trg_team_market_scope_update BEFORE UPDATE ON team_markets BEGIN SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM teams t JOIN markets m ON m.market_id=NEW.market_id WHERE t.team_id=NEW.team_id AND t.organization_id=NEW.organization_id AND m.organization_id=NEW.organization_id) THEN RAISE(ABORT,'CROSS_TENANT_REFERENCE_DETECTED') END; END""",
 'trg_team_bl_scope_insert':"""CREATE TRIGGER IF NOT EXISTS trg_team_bl_scope_insert BEFORE INSERT ON team_business_lines BEGIN SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM teams t JOIN business_lines b ON b.business_line_id=NEW.business_line_id WHERE t.team_id=NEW.team_id AND t.organization_id=NEW.organization_id AND b.organization_id=NEW.organization_id) THEN RAISE(ABORT,'CROSS_TENANT_REFERENCE_DETECTED') END; END""",
 'trg_team_bl_scope_update':"""CREATE TRIGGER IF NOT EXISTS trg_team_bl_scope_update BEFORE UPDATE ON team_business_lines BEGIN SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM teams t JOIN business_lines b ON b.business_line_id=NEW.business_line_id WHERE t.team_id=NEW.team_id AND t.organization_id=NEW.organization_id AND b.organization_id=NEW.organization_id) THEN RAISE(ABORT,'CROSS_TENANT_REFERENCE_DETECTED') END; END""",
 'trg_team_department_scope_insert':"""CREATE TRIGGER IF NOT EXISTS trg_team_department_scope_insert BEFORE INSERT ON teams WHEN NEW.department_id IS NOT NULL BEGIN SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM departments d WHERE d.department_id=NEW.department_id AND d.organization_id=NEW.organization_id AND d.status='active') THEN RAISE(ABORT,'TEAM_DEPARTMENT_SCOPE_INVALID') END; END""",
 'trg_team_department_scope_update':"""CREATE TRIGGER IF NOT EXISTS trg_team_department_scope_update BEFORE UPDATE OF department_id,organization_id ON teams WHEN NEW.department_id IS NOT NULL BEGIN SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM departments d WHERE d.department_id=NEW.department_id AND d.organization_id=NEW.organization_id AND d.status='active') THEN RAISE(ABORT,'TEAM_DEPARTMENT_SCOPE_INVALID') END; END"""}
 for sql in triggers.values():c.execute(sql)
 hierarchy_triggers=_ensure_hierarchy_guards(c)
 identity_result=_ensure_identity_rbac_fk_baseline(c)
 _assert_v208_objects(c)
 _v208_record(c,'V208_030_foreign_key_baseline',{'status':'success','crossTenantTriggers':len(triggers),'hierarchyTriggers':len(hierarchy_triggers),'teamsForeignKeys':3})
 _v208_record(c,'V208_040_catalog_baseline',{'status':'success','catalogVersion':CATALOG_VERSION})
 _v208_record(c,'V208_050_identity_rbac_foreign_keys',identity_result)

BOOTSTRAP_FIELDS=('organization_id','organization_name','workspace_id','workspace_name','team_id','team_name','admin_user_id','admin_login','admin_display_name','admin_password')
def validate_bootstrap(bootstrap):
 if bootstrap is None:bootstrap={}
 b0={'organization_id':'jubaopen','organization_name':'聚宝盆企业','workspace_id':'default','workspace_name':'默认业务空间','team_id':'default','team_name':'默认团队','admin_user_id':'platform_admin','admin_login':'admin','admin_display_name':'平台超级管理员','admin_password':'','builtin_default':'0'}
 bootstrap={**b0,**{k:v for k,v in bootstrap.items() if v is not None}}
 b={k:str(bootstrap.get(k) or '').strip() for k in BOOTSTRAP_FIELDS}
 missing=[k for k,v in b.items() if not v]
 if missing:raise RuntimeError('BOOTSTRAP_REQUIRED: '+','.join(missing))
 for k in ('organization_id','workspace_id','team_id','admin_user_id'):
  if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{1,63}',b[k]):raise RuntimeError('BOOTSTRAP_INVALID_ID: '+k)
 if not re.fullmatch(r'[^\s]{2,128}',b['admin_login']):raise RuntimeError('BOOTSTRAP_INVALID_LOGIN')
 if len(b['admin_password'])<12 or not any(x.isalpha() for x in b['admin_password']) or not any(x.isdigit() for x in b['admin_password']):raise RuntimeError('BOOTSTRAP_PASSWORD_WEAK: 至少12位且必须同时包含字母和数字')
 return b

def bootstrap_fresh_database(c,b):
 t=now_ms();h,salt,it=hash_password(b['admin_password'])
 c.execute("INSERT INTO organizations(organization_id,name,status,created_at,updated_at) VALUES(?,?,'active',?,?)",(b['organization_id'],b['organization_name'],t,t))
 c.execute("INSERT INTO workspaces(workspace_id,name,status,created_at,updated_at,organization_id) VALUES(?,?,'active',?,?,?)",(b['workspace_id'],b['workspace_name'],t,t,b['organization_id']))
 c.execute("INSERT INTO workspace_configs(workspace_id,revision,items_json,updated_at,updated_by) VALUES(?,0,'[]',?,?)",(b['workspace_id'],t,b['admin_user_id']))
 c.execute("INSERT INTO teams(team_id,organization_id,workspace_id,name,status,created_at,updated_at) VALUES(?,?,?,?,'active',?,?)",(b['team_id'],b['organization_id'],b['workspace_id'],b['team_name'],t,t))
 c.execute("INSERT INTO workspace_teams(workspace_id,team_id,organization_id,relation_type,is_primary,access_level,status,created_at,updated_at) VALUES(?,?,?,'primary',1,'manage','active',?,?)",(b['workspace_id'],b['team_id'],b['organization_id'],t,t))
 c.execute("INSERT INTO users(user_id,organization_id,login_name,display_name,status,created_at,updated_at) VALUES(?,?,?,?,'active',?,?)",(b['admin_user_id'],b['organization_id'],b['admin_login'],b['admin_display_name'],t,t))
 c.execute('INSERT INTO user_credentials(user_id,password_hash,salt,iterations,must_change,updated_at) VALUES(?,?,?,?,1,?)',(b['admin_user_id'],h,salt,it,t))
 c.execute('INSERT INTO platform_administrators(user_id,is_builtin,onboarding_completed,created_at,updated_at) VALUES(?,1,0,?,?)',(b['admin_user_id'],t,t))
 c.execute("INSERT INTO role_bindings(binding_id,user_id,role_id,organization_id,scope_type,scope_id,status,granted_by,created_at,updated_at) VALUES(?,?,?,?,?,?,'active',?,?,?)",('bootstrap:org:'+b['admin_user_id'],b['admin_user_id'],'role_orgadmin',b['organization_id'],'organization',b['organization_id'],b['admin_user_id'],t,t))
 c.execute("INSERT INTO role_bindings(binding_id,user_id,role_id,organization_id,scope_type,scope_id,status,granted_by,created_at,updated_at) VALUES(?,?,?,?,?,?,'active',?,?,?)",('bootstrap:team:'+b['admin_user_id'],b['admin_user_id'],'role_teamlead',b['organization_id'],'team',b['team_id'],b['admin_user_id'],t,t))
 for i in range(1,9):c.execute('INSERT INTO custom_field_definitions(workspace_id,field_key,label,field_type,sort_order,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(b['workspace_id'],f'f{i}',str(i),'text',i,1,t,t))

def validate_registered_migration_checksums(path):
 """只读预检迁移登记；任何已知迁移校验和漂移均阻止启动。"""
 uri='file:'+Path(path).resolve().as_posix()+'?mode=ro'
 c=sqlite3.connect(uri,uri=True)
 try:
  if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone():return
  expected={
   'V207_100_channel_attribution':hashlib.sha256(V207_1_SCHEMA.encode()).hexdigest(),
   'V207_101_contact_identity_integrity':hashlib.sha256(V207_101_SCHEMA.encode()).hexdigest(),
   'V207_200_touchpoint_attribution_path':hashlib.sha256(V207_200_SCHEMA.encode()).hexdigest(),
   'V207_300_organization_operating_model':hashlib.sha256(V207_300_SCHEMA.encode()).hexdigest(),
   'V207_301_tag_kind':hashlib.sha256(V207_301_SCHEMA.encode()).hexdigest(),
  }
  expected.update({mid:_v208_checksum(mid) for mid in V208_STAGES})
  expected[V209_MIGRATION_ID]=hashlib.sha256(V209_SIGNATURE.encode()).hexdigest() if 'V209_SIGNATURE' in globals() else None
  expected[V210_MIGRATION_ID]=hashlib.sha256(V210_SIGNATURE.encode()).hexdigest() if 'V210_SIGNATURE' in globals() else None
  bad=[]
  for mid,checksum in c.execute('SELECT migration_id,checksum FROM schema_migrations'):
   if mid in expected and checksum!=expected[mid]:bad.append(mid)
  if bad:raise RuntimeError('MIGRATION_CHECKSUM_MISMATCH: '+', '.join(bad))
 finally:c.close()

def readonly_preflight(path):
 """在备份和任何迁移写入前，以只读连接阻断损坏、歧义、孤立和跨租户数据。"""
 uri='file:'+Path(path).resolve().as_posix()+'?mode=ro'
 c=sqlite3.connect(uri,uri=True)
 try:
  c.row_factory=sqlite3.Row
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('PRECHECK_QUICK_CHECK_FAILED')
  tables={x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  def cols(t):return {x[1] for x in c.execute('PRAGMA table_info('+t+')')} if t in tables else set()
  required_scopes={'workspaces':('organization_id',),'teams':('organization_id','workspace_id'),'sources':('organization_id','team_id'),'devices':('organization_id','team_id'),'contacts':('organization_id','team_id')}
  for t,required in required_scopes.items():
   cs=cols(t)
   if not cs:continue
   missing=[x for x in required if x not in cs]
   if missing:raise RuntimeError('LEGACY_SCOPE_MIGRATION_REQUIRED: '+t+':'+','.join(missing))
  ambiguous={}
  for t in ('sources','devices','contacts'):
   cs=cols(t)
   if {'workspace_id','team_id'}.issubset(cs) and 'workspace_teams' in tables:
    active=" AND wt.status='active'" if 'status' in cols('workspace_teams') else ''
    sql="SELECT count(*) FROM "+t+" x WHERE (x.team_id IS NULL OR x.team_id='') AND (SELECT count(*) FROM workspace_teams wt WHERE wt.workspace_id=x.workspace_id"+active+")>1"
    n=c.execute(sql).fetchone()[0]
    if n:ambiguous[t]=n
  if ambiguous:raise RuntimeError('AMBIGUOUS_TEAM_SCOPE: '+dumps(ambiguous))
  orphan={}
  for row in c.execute('PRAGMA foreign_key_check'):
   orphan[row[0]]=orphan.get(row[0],0)+1
  orphan_checks=[
   ('teams/workspaces',"SELECT count(*) FROM teams t LEFT JOIN workspaces w ON w.workspace_id=t.workspace_id WHERE w.workspace_id IS NULL"),
   ('team_memberships',"SELECT count(*) FROM team_memberships r LEFT JOIN users u ON u.user_id=r.user_id LEFT JOIN teams t ON t.team_id=r.team_id LEFT JOIN roles p ON p.role_id=r.role_id WHERE u.user_id IS NULL OR t.team_id IS NULL OR p.role_id IS NULL"),
   ('organization_memberships',"SELECT count(*) FROM organization_memberships r LEFT JOIN users u ON u.user_id=r.user_id LEFT JOIN organizations o ON o.organization_id=r.organization_id LEFT JOIN roles p ON p.role_id=r.role_id WHERE u.user_id IS NULL OR o.organization_id IS NULL OR p.role_id IS NULL"),
   ('sessions',"SELECT count(*) FROM sessions r LEFT JOIN users u ON u.user_id=r.user_id WHERE u.user_id IS NULL"),
   ('role_permissions',"SELECT count(*) FROM role_permissions r LEFT JOIN roles p ON p.role_id=r.role_id LEFT JOIN permissions q ON q.permission_key=r.permission_key WHERE p.role_id IS NULL OR q.permission_key IS NULL"),
   ('workspace_teams',"SELECT count(*) FROM workspace_teams r LEFT JOIN workspaces w ON w.workspace_id=r.workspace_id LEFT JOIN teams t ON t.team_id=r.team_id WHERE w.workspace_id IS NULL OR t.team_id IS NULL"),
   ('team_markets',"SELECT count(*) FROM team_markets r LEFT JOIN teams t ON t.team_id=r.team_id LEFT JOIN markets m ON m.market_id=r.market_id WHERE t.team_id IS NULL OR m.market_id IS NULL"),
   ('team_business_lines',"SELECT count(*) FROM team_business_lines r LEFT JOIN teams t ON t.team_id=r.team_id LEFT JOIN business_lines b ON b.business_line_id=r.business_line_id WHERE t.team_id IS NULL OR b.business_line_id IS NULL")]
  for name,sql in orphan_checks:
   if name.split('/')[0] not in tables:continue
   try:n=c.execute(sql).fetchone()[0]
   except sqlite3.OperationalError:continue
   if n:orphan[name]=max(orphan.get(name,0),n)
  if orphan:raise RuntimeError('ORPHAN_RELATION_DETECTED: '+dumps(orphan))
  cross_checks=[
   ('teams/workspaces',"SELECT count(*) FROM teams t JOIN workspaces w ON w.workspace_id=t.workspace_id WHERE t.organization_id<>w.organization_id"),
   ('team_memberships',"SELECT count(*) FROM team_memberships r JOIN users u ON u.user_id=r.user_id JOIN teams t ON t.team_id=r.team_id WHERE u.organization_id<>t.organization_id"),
   ('organization_memberships',"SELECT count(*) FROM organization_memberships r JOIN users u ON u.user_id=r.user_id WHERE u.organization_id<>r.organization_id"),
   ('workspace_teams',"SELECT count(*) FROM workspace_teams r JOIN workspaces w ON w.workspace_id=r.workspace_id JOIN teams t ON t.team_id=r.team_id WHERE r.organization_id<>w.organization_id OR r.organization_id<>t.organization_id"),
   ('team_markets',"SELECT count(*) FROM team_markets r JOIN teams t ON t.team_id=r.team_id JOIN markets m ON m.market_id=r.market_id WHERE r.organization_id<>t.organization_id OR r.organization_id<>m.organization_id"),
   ('team_business_lines',"SELECT count(*) FROM team_business_lines r JOIN teams t ON t.team_id=r.team_id JOIN business_lines b ON b.business_line_id=r.business_line_id WHERE r.organization_id<>t.organization_id OR r.organization_id<>b.organization_id")]
  cross={}
  for name,sql in cross_checks:
   if name.split('/')[0] not in tables:continue
   try:n=c.execute(sql).fetchone()[0]
   except sqlite3.OperationalError:continue
   if n:cross[name]=n
  if cross:raise RuntimeError('CROSS_TENANT_REFERENCE_DETECTED: '+dumps(cross))
  scope_issues={}
  for t,required in required_scopes.items():
   if not cols(t):continue
   where=' OR '.join(x+' IS NULL OR '+x+"=''" for x in required)
   n=c.execute('SELECT count(*) FROM '+t+' WHERE '+where).fetchone()[0]
   if n:scope_issues[t]=n
  if scope_issues:raise RuntimeError('LEGACY_SCOPE_MIGRATION_REQUIRED: '+dumps(scope_issues))
  for t,key,parent in (('departments','department_id','parent_department_id'),('markets','market_id','parent_market_id'),('business_lines','business_line_id','parent_business_line_id')):
   if t in tables and {key,parent}.issubset(cols(t)) and _hierarchy_cycle(c,t,key,parent):raise RuntimeError('HIERARCHY_CYCLE_DETECTED: '+t)
  for t in ('team_markets','team_business_lines'):
   if t in tables:
    n=c.execute("SELECT count(*) FROM (SELECT team_id FROM "+t+" WHERE is_primary=1 AND status='active' GROUP BY team_id HAVING count(*)>1)").fetchone()[0]
    if n:raise RuntimeError('DUPLICATE_PRIMARY_RELATION: '+t)
 finally:c.close()


# V207.6 / Schema 210：平台主体、职位模型与首次登录设置。
V209_MIGRATION_ID='V209_000_organization_identity_positions'
V209_SIGNATURE="""Schema 210 / catalog 209.0
platform_administrators(user_id,is_builtin,onboarding_completed,created_at,updated_at)
positions(position_id,organization_id,department_id,name,code,description,status,sort_order,timestamps)
user_positions(user_id,position_id,organization_id,is_primary,status,timestamps)
platform identity is independent from organization role membership
"""
def ensure_v209(c):
 checksum=hashlib.sha256(V209_SIGNATURE.encode()).hexdigest()
 old=c.execute('SELECT checksum FROM schema_migrations WHERE migration_id=?',(V209_MIGRATION_ID,)).fetchone()
 if old and old[0]!=checksum:raise RuntimeError('MIGRATION_CHECKSUM_MISMATCH: '+V209_MIGRATION_ID)
 execute_sql_script(c,"""
 CREATE TABLE IF NOT EXISTS platform_administrators(
  user_id TEXT PRIMARY KEY,is_builtin INTEGER NOT NULL DEFAULT 0 CHECK(is_builtin IN (0,1)),
  onboarding_completed INTEGER NOT NULL DEFAULT 0 CHECK(onboarding_completed IN (0,1)),
  created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(user_id) ON UPDATE NO ACTION ON DELETE NO ACTION);
 CREATE TABLE IF NOT EXISTS positions(
  position_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,department_id TEXT,
  name TEXT NOT NULL,code TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled','archived')),
  sort_order INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
  FOREIGN KEY(organization_id) REFERENCES organizations(organization_id) ON UPDATE NO ACTION ON DELETE NO ACTION,
  FOREIGN KEY(department_id) REFERENCES departments(department_id) ON UPDATE NO ACTION ON DELETE NO ACTION,
  UNIQUE(organization_id,code));
 CREATE TABLE IF NOT EXISTS user_positions(
  user_id TEXT NOT NULL,position_id TEXT NOT NULL,organization_id TEXT NOT NULL,
  is_primary INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0,1)),
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
  created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,PRIMARY KEY(user_id,position_id),
  FOREIGN KEY(user_id) REFERENCES users(user_id) ON UPDATE NO ACTION ON DELETE NO ACTION,
  FOREIGN KEY(position_id) REFERENCES positions(position_id) ON UPDATE NO ACTION ON DELETE NO ACTION,
  FOREIGN KEY(organization_id) REFERENCES organizations(organization_id) ON UPDATE NO ACTION ON DELETE NO ACTION);
 CREATE UNIQUE INDEX IF NOT EXISTS uq_user_primary_position ON user_positions(user_id) WHERE is_primary=1 AND status='active';
 CREATE INDEX IF NOT EXISTS idx_positions_org_department ON positions(organization_id,department_id,status,sort_order);
 CREATE INDEX IF NOT EXISTS idx_user_positions_org ON user_positions(organization_id,user_id,status);
 CREATE TRIGGER IF NOT EXISTS trg_position_department_scope_insert BEFORE INSERT ON positions WHEN NEW.department_id IS NOT NULL BEGIN
  SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM departments d WHERE d.department_id=NEW.department_id AND d.organization_id=NEW.organization_id) THEN RAISE(ABORT,'POSITION_DEPARTMENT_SCOPE_MISMATCH') END; END;
 CREATE TRIGGER IF NOT EXISTS trg_position_department_scope_update BEFORE UPDATE OF department_id,organization_id ON positions WHEN NEW.department_id IS NOT NULL BEGIN
  SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM departments d WHERE d.department_id=NEW.department_id AND d.organization_id=NEW.organization_id) THEN RAISE(ABORT,'POSITION_DEPARTMENT_SCOPE_MISMATCH') END; END;
 CREATE TRIGGER IF NOT EXISTS trg_user_position_scope_insert BEFORE INSERT ON user_positions BEGIN
  SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users u JOIN positions p ON p.position_id=NEW.position_id WHERE u.user_id=NEW.user_id AND u.organization_id=NEW.organization_id AND p.organization_id=NEW.organization_id) THEN RAISE(ABORT,'USER_POSITION_SCOPE_MISMATCH') END; END;
 CREATE TRIGGER IF NOT EXISTS trg_user_position_scope_update BEFORE UPDATE ON user_positions BEGIN
  SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users u JOIN positions p ON p.position_id=NEW.position_id WHERE u.user_id=NEW.user_id AND u.organization_id=NEW.organization_id AND p.organization_id=NEW.organization_id) THEN RAISE(ABORT,'USER_POSITION_SCOPE_MISMATCH') END; END;
 """)
 # 仅迁移明确拥有历史超级管理员角色的用户，不把企业管理员隐式提升为平台管理员。
 t=now_ms()
 c.execute("INSERT OR IGNORE INTO platform_administrators(user_id,is_builtin,onboarding_completed,created_at,updated_at) SELECT DISTINCT user_id,0,1,?,? FROM organization_memberships WHERE role_id='role_superadmin' AND status='active'",(t,t))
 if not old:c.execute('INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES(?,?,?,?,?,?)',(V209_MIGRATION_ID,'平台管理员主体、职位与首次设置状态',checksum,t,'system',dumps({'status':'success'})))

# V207.7 / Schema 210: unified RBAC authorization center.
V210_MIGRATION_ID='V210_000_rbac_authorization_center'
V210_SIGNATURE="""Schema 210/catalog 210.0; role and permission metadata; scoped role bindings; high-risk confirmations; session revocation audit; isolated platform administrators."""

def ensure_v210(c):
 checksum=hashlib.sha256(V210_SIGNATURE.encode()).hexdigest()
 old=c.execute('SELECT checksum FROM schema_migrations WHERE migration_id=?',(V210_MIGRATION_ID,)).fetchone()
 if old and old[0]!=checksum:raise RuntimeError('MIGRATION_CHECKSUM_MISMATCH: '+V210_MIGRATION_ID)
 _add(c,'roles','role_code','TEXT')
 _add(c,'roles','description',"TEXT NOT NULL DEFAULT ''")
 _add(c,'roles','is_system','INTEGER NOT NULL DEFAULT 0 CHECK(is_system IN (0,1))')
 _add(c,'permissions','display_name','TEXT')
 _add(c,'permissions','resource','TEXT')
 _add(c,'permissions','action','TEXT')
 _add(c,'permissions','scope_mask','INTEGER NOT NULL DEFAULT 63')
 _add(c,'permissions','risk_level',"TEXT NOT NULL DEFAULT 'low' CHECK(risk_level IN ('low','medium','high','critical'))")
 _add(c,'sessions','revoked_reason','TEXT')
 _add(c,'sessions','revoked_by','TEXT')
 c.execute("UPDATE roles SET role_code=COALESCE(NULLIF(role_code,''),role_id),description=COALESCE(description,''),is_system=CASE WHEN role_id IN ('role_superadmin','role_orgadmin','role_teamlead','role_operator','role_readonly','role_auditor') THEN 1 ELSE is_system END")
 c.execute("UPDATE permissions SET display_name=COALESCE(NULLIF(display_name,''),description,permission_key),resource=COALESCE(NULLIF(resource,''),CASE WHEN instr(permission_key,'.')>0 THEN substr(permission_key,1,instr(permission_key,'.')-1) ELSE permission_key END),action=COALESCE(NULLIF(action,''),CASE WHEN instr(permission_key,'.')>0 THEN substr(permission_key,instr(permission_key,'.')+1) ELSE 'access' END)")
 execute_sql_script(c,"""
 CREATE UNIQUE INDEX IF NOT EXISTS uq_roles_role_code ON roles(role_code);
 CREATE TABLE IF NOT EXISTS role_bindings(binding_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,role_id TEXT NOT NULL,organization_id TEXT,scope_type TEXT NOT NULL CHECK(scope_type IN ('platform','organization','workspace','department','team','self')),scope_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled','archived')),granted_by TEXT,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,FOREIGN KEY(user_id) REFERENCES users(user_id),FOREIGN KEY(role_id) REFERENCES roles(role_id),FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(granted_by) REFERENCES users(user_id) ON DELETE SET NULL,UNIQUE(user_id,role_id,scope_type,scope_id));
 CREATE INDEX IF NOT EXISTS idx_role_bindings_subject ON role_bindings(user_id,status,scope_type);
 CREATE INDEX IF NOT EXISTS idx_role_bindings_scope ON role_bindings(organization_id,scope_type,scope_id,status);
 CREATE TABLE IF NOT EXISTS rbac_confirmations(confirmation_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,action_key TEXT NOT NULL,token_digest TEXT NOT NULL UNIQUE,context_json TEXT NOT NULL DEFAULT '{}',expires_at INTEGER NOT NULL,consumed_at INTEGER,created_at INTEGER NOT NULL,FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE);
 CREATE INDEX IF NOT EXISTS idx_rbac_confirmations_user ON rbac_confirmations(user_id,action_key,expires_at,consumed_at);
 CREATE TRIGGER IF NOT EXISTS trg_role_status_insert BEFORE INSERT ON roles WHEN NEW.status NOT IN ('active','disabled','archived') BEGIN SELECT RAISE(ABORT,'RBAC_ROLE_STATUS_INVALID'); END;
 CREATE TRIGGER IF NOT EXISTS trg_role_status_update BEFORE UPDATE OF status ON roles WHEN NEW.status NOT IN ('active','disabled','archived') BEGIN SELECT RAISE(ABORT,'RBAC_ROLE_STATUS_INVALID'); END;
 CREATE TRIGGER IF NOT EXISTS trg_role_binding_guard_insert BEFORE INSERT ON role_bindings BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users u WHERE u.user_id=NEW.user_id AND u.status='active') THEN RAISE(ABORT,'RBAC_SUBJECT_INVALID') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM roles r WHERE r.role_id=NEW.role_id AND r.status='active') THEN RAISE(ABORT,'RBAC_ROLE_INVALID') END;
 SELECT CASE WHEN NEW.scope_type='platform' AND (NEW.organization_id IS NOT NULL OR NEW.scope_id<>'*' OR NEW.role_id<>'role_superadmin' OR NOT EXISTS(SELECT 1 FROM platform_administrators p WHERE p.user_id=NEW.user_id)) THEN RAISE(ABORT,'RBAC_PLATFORM_BINDING_FORBIDDEN') END;
 SELECT CASE WHEN NEW.scope_type<>'platform' AND (NEW.organization_id IS NULL OR NEW.role_id='role_superadmin' OR NOT EXISTS(SELECT 1 FROM users u WHERE u.user_id=NEW.user_id AND u.organization_id=NEW.organization_id)) THEN RAISE(ABORT,'RBAC_CROSS_TENANT_BINDING') END;
 SELECT CASE WHEN NEW.scope_type='organization' AND NEW.scope_id<>NEW.organization_id THEN RAISE(ABORT,'RBAC_SCOPE_MISMATCH') END;
 SELECT CASE WHEN NEW.scope_type='workspace' AND NOT EXISTS(SELECT 1 FROM workspaces x WHERE x.workspace_id=NEW.scope_id AND x.organization_id=NEW.organization_id) THEN RAISE(ABORT,'RBAC_SCOPE_MISMATCH') END;
 SELECT CASE WHEN NEW.scope_type='department' AND NOT EXISTS(SELECT 1 FROM departments x WHERE x.department_id=NEW.scope_id AND x.organization_id=NEW.organization_id) THEN RAISE(ABORT,'RBAC_SCOPE_MISMATCH') END;
 SELECT CASE WHEN NEW.scope_type='team' AND NOT EXISTS(SELECT 1 FROM teams x WHERE x.team_id=NEW.scope_id AND x.organization_id=NEW.organization_id) THEN RAISE(ABORT,'RBAC_SCOPE_MISMATCH') END;
 SELECT CASE WHEN NEW.scope_type='self' AND NEW.scope_id<>NEW.user_id THEN RAISE(ABORT,'RBAC_SCOPE_MISMATCH') END;
 END;
 CREATE TRIGGER IF NOT EXISTS trg_role_binding_guard_update BEFORE UPDATE ON role_bindings BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users u WHERE u.user_id=NEW.user_id AND u.status='active') THEN RAISE(ABORT,'RBAC_SUBJECT_INVALID') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM roles r WHERE r.role_id=NEW.role_id AND r.status='active') THEN RAISE(ABORT,'RBAC_ROLE_INVALID') END;
 SELECT CASE WHEN NEW.scope_type='platform' AND (NEW.organization_id IS NOT NULL OR NEW.scope_id<>'*' OR NEW.role_id<>'role_superadmin' OR NOT EXISTS(SELECT 1 FROM platform_administrators p WHERE p.user_id=NEW.user_id)) THEN RAISE(ABORT,'RBAC_PLATFORM_BINDING_FORBIDDEN') END;
 SELECT CASE WHEN NEW.scope_type<>'platform' AND (NEW.organization_id IS NULL OR NEW.role_id='role_superadmin' OR NOT EXISTS(SELECT 1 FROM users u WHERE u.user_id=NEW.user_id AND u.organization_id=NEW.organization_id)) THEN RAISE(ABORT,'RBAC_CROSS_TENANT_BINDING') END;
 SELECT CASE WHEN NEW.scope_type='organization' AND NEW.scope_id<>NEW.organization_id THEN RAISE(ABORT,'RBAC_SCOPE_MISMATCH') END;
 SELECT CASE WHEN NEW.scope_type='workspace' AND NOT EXISTS(SELECT 1 FROM workspaces x WHERE x.workspace_id=NEW.scope_id AND x.organization_id=NEW.organization_id) THEN RAISE(ABORT,'RBAC_SCOPE_MISMATCH') END;
 SELECT CASE WHEN NEW.scope_type='department' AND NOT EXISTS(SELECT 1 FROM departments x WHERE x.department_id=NEW.scope_id AND x.organization_id=NEW.organization_id) THEN RAISE(ABORT,'RBAC_SCOPE_MISMATCH') END;
 SELECT CASE WHEN NEW.scope_type='team' AND NOT EXISTS(SELECT 1 FROM teams x WHERE x.team_id=NEW.scope_id AND x.organization_id=NEW.organization_id) THEN RAISE(ABORT,'RBAC_SCOPE_MISMATCH') END;
 SELECT CASE WHEN NEW.scope_type='self' AND NEW.scope_id<>NEW.user_id THEN RAISE(ABORT,'RBAC_SCOPE_MISMATCH') END;
 END;
 """)
 t=now_ms()
 c.execute("INSERT OR IGNORE INTO role_bindings(binding_id,user_id,role_id,organization_id,scope_type,scope_id,status,granted_by,created_at,updated_at) SELECT 'legacy:org:'||m.user_id||':'||m.organization_id||':'||m.role_id,m.user_id,m.role_id,m.organization_id,'organization',m.organization_id,m.status,NULL,?,? FROM organization_memberships m JOIN users u ON u.user_id=m.user_id AND u.organization_id=m.organization_id JOIN roles r ON r.role_id=m.role_id AND r.status='active' WHERE m.role_id<>'role_superadmin' AND m.status IN ('active','disabled')",(t,t))
 c.execute("INSERT OR IGNORE INTO role_bindings(binding_id,user_id,role_id,organization_id,scope_type,scope_id,status,granted_by,created_at,updated_at) SELECT 'legacy:team:'||m.user_id||':'||m.team_id||':'||m.role_id,m.user_id,m.role_id,x.organization_id,'team',m.team_id,m.status,NULL,?,? FROM team_memberships m JOIN teams x ON x.team_id=m.team_id JOIN users u ON u.user_id=m.user_id AND u.organization_id=x.organization_id JOIN roles r ON r.role_id=m.role_id AND r.status='active' WHERE m.role_id<>'role_superadmin' AND m.status IN ('active','disabled')",(t,t))
 if not old:c.execute('INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES(?,?,?,?,?,?)',(V210_MIGRATION_ID,'Unified RBAC authorization center',checksum,t,'system',dumps({'status':'success'})))

class Database:
 def __init__(self,path):self.path=Path(path).resolve();self.path.parent.mkdir(parents=True,exist_ok=True)
 def connect(self):
  c=sqlite3.connect(str(self.path),timeout=30,isolation_level=None,check_same_thread=False);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=30000');c.execute('PRAGMA journal_mode=WAL');return c
 @contextlib.contextmanager
 def tx(self,immediate=True):
  c=self.connect()
  try:c.execute('BEGIN IMMEDIATE' if immediate else 'BEGIN');yield c;c.execute('COMMIT')
  except Exception:c.execute('ROLLBACK');raise
  finally:c.close()
 def initialize(self,bootstrap=None):
  """初始化或幂等升级；新库使用安全内置模板，已有库绝不创建或重归属租户。"""
  fresh=not self.path.exists() or not self.path.stat().st_size
  b=validate_bootstrap(bootstrap) if fresh else None
  backup=None
  if not fresh:
   validate_registered_migration_checksums(self.path)
   readonly_preflight(self.path)
   backup=_exclusive_backup_path(self.path)
   src=sqlite3.connect(str(self.path));dst=sqlite3.connect(str(backup))
   try:src.backup(dst)
   except Exception:
    dst.close();src.close();backup.unlink(missing_ok=True);raise
   finally:
    try:src.close();dst.close()
    except Exception:pass
  c=self.connect()
  try:
   # SQLite 表重建要求在事务开始前关闭写入期外键检查；提交前强制 foreign_key_check。
   c.execute('PRAGMA foreign_keys=OFF')
   c.execute('BEGIN IMMEDIATE')
   if fresh:execute_sql_script(c,BASE_SCHEMA)
   ensure_v207(c,fresh=fresh);ensure_v207_1(c);ensure_v207_101(c);ensure_v207_200(c);ensure_v207_300(c);ensure_v207_301(c);ensure_v208(c);ensure_v209(c);ensure_v210(c)
   if fresh:bootstrap_fresh_database(c,b)
   c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",(str(SCHEMA_VERSION),))
   c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('product_version',?)",(PRODUCT_VERSION,))
   c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('catalog_version',?)",(CATALOG_VERSION,))
   c.execute("DELETE FROM meta WHERE key='initial_admin_password'")
   qc=c.execute('PRAGMA quick_check').fetchone()[0]
   if qc!='ok':raise RuntimeError('PRAGMA quick_check 失败: '+str(qc))
   fk=list(c.execute('PRAGMA foreign_key_check'))
   if fk:raise RuntimeError('外键完整性检查失败，共 %d 项；数据库已回滚，请先离线修复。'%len(fk))
   c.execute('COMMIT')
   c.execute('PRAGMA foreign_keys=ON')
   if c.execute('PRAGMA foreign_keys').fetchone()[0]!=1:raise RuntimeError('FOREIGN_KEYS_REENABLE_FAILED')
  except Exception as exc:
   try:
    if c.in_transaction:c.execute('ROLLBACK')
   finally:c.close()
   if backup and backup.exists():
    for suffix in ('-wal','-shm'):Path(str(self.path)+suffix).unlink(missing_ok=True)
    shutil.copy2(backup,self.path)
   elif fresh and self.path.exists():self.path.unlink()
   _write_failure_report(self.path,exc,backup)
   raise
  finally:
   try:c.close()
   except Exception:pass

 def quick_check(self):
  c=self.connect()
  try:return c.execute('PRAGMA quick_check').fetchone()[0]
  finally:c.close()
 def foreign_key_check(self):
  c=self.connect()
  try:return [dict(x) for x in c.execute('PRAGMA foreign_key_check')]
  finally:c.close()
# V207.0.0 更新说明（2026-09-17）：升级 Schema 207；新增企业、团队、用户、会话、RBAC、渠道账号授权、设备双命名与可信审计基础。

# V207.1.0 更新说明（2026-09-18）：保持 Schema 207 兼容，新增动态平台、活动、来源分类/路径、客户外部身份、来源触点、多触点归因与迁移登记；移除渠道平台固定枚举限制。

# V207.3.0-dev 更新说明（2026-09-19）：保持 Schema 207，新增部门、业务线、市场、工作区多团队/业务线/市场关联，回填旧团队主工作区关系，并扩展审计作用域字段。
# V207.4.0-dev 更新说明（2026-09-20）：采用严格迁移校验与完整性门禁；删除启动时隐式删除、重归属数据的修复逻辑；所有连接强制启用物理外键。
