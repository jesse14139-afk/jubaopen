# -*- coding: utf-8 -*-
"""聚宝盆 V207 数据层：Schema 207，多租户/RBAC/账号授权/设备双命名。"""
from __future__ import annotations
import contextlib, hashlib, json, sqlite3, time, secrets, shutil
from pathlib import Path
SCHEMA_VERSION=207; PRODUCT_VERSION="207.3.0-dev"
def now_ms(): return int(time.time()*1000)
def dumps(v): return json.dumps(v,ensure_ascii=False,separators=(",",":"))
def loads(v,default=None):
 try:return json.loads(v) if v else default
 except Exception:return default
def sha256_bytes(v):return hashlib.sha256(v).hexdigest()
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
PERMS=['organization.read','organization.manage','team.read','team.manage','user.read','user.manage','role.read','role.manage','account.read','account.bind','source.read','source.manage','device.read','device.rename.self','device.rename.admin','device.disable','contact.read','contact.update','contact.delete','contact.restore','contact.export','audit.read']
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
 c.executescript(V207_1_SCHEMA)
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
 if existing and existing[0]!=checksum:
  c.execute("DELETE FROM schema_migrations WHERE migration_id='V207_100_channel_attribution'")
  existing=None
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
 if existing and existing[0]!=checksum:
  c.execute('DELETE FROM schema_migrations WHERE migration_id=?',(migration_id,))
  existing=None
 if not existing:
  # Repair legacy duplicate primaries deterministically before installing the partial unique index.
  groups=list(c.execute('SELECT organization_id,workspace_id,contact_id FROM contact_identities WHERE is_primary=1 GROUP BY organization_id,workspace_id,contact_id HAVING count(*)>1'))
  repaired=0
  for org,wid,cid in groups:
   keep=c.execute('SELECT contact_identity_id FROM contact_identities WHERE organization_id=? AND workspace_id=? AND contact_id=? AND is_primary=1 ORDER BY first_seen_at,contact_identity_id LIMIT 1',(org,wid,cid)).fetchone()[0]
   cur=c.execute('UPDATE contact_identities SET is_primary=0 WHERE organization_id=? AND workspace_id=? AND contact_id=? AND is_primary=1 AND contact_identity_id<>?',(org,wid,cid,keep));repaired+=cur.rowcount
  c.executescript(V207_101_SCHEMA)
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
 if existing and existing[0]!=checksum:
  c.execute('DELETE FROM schema_migrations WHERE migration_id=?',(mid,))
  existing=None
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
  c.executescript(V207_200_SCHEMA)
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
 if existing and existing[0]!=checksum:
  c.execute('DELETE FROM schema_migrations WHERE migration_id=?',(mid,))
  existing=None
 if not existing:
  c.executescript(V207_300_SCHEMA)
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
 c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('product_version','207.3.0-dev')")

V207_301_SCHEMA=r"""
-- 标签分类：status（业务状态标签）vs portrait（客户画像标签）
"""
def ensure_v207_301(c):
 t=now_ms();mid='V207_301_tag_kind';checksum=hashlib.sha256(V207_301_SCHEMA.encode()).hexdigest()
 existing=c.execute('SELECT checksum FROM schema_migrations WHERE migration_id=?',(mid,)).fetchone()
 if existing and existing[0]!=checksum:
  c.execute('DELETE FROM schema_migrations WHERE migration_id=?',(mid,))
  existing=None
 if not existing:
  # Add tag_kind column with CHECK constraint
  _add(c,'tags','tag_kind',"TEXT NOT NULL DEFAULT 'portrait' CHECK(tag_kind IN ('status','portrait'))")
  # Backfill existing tags: if category contains '状态'/'status', mark as status; otherwise portrait
  c.execute("UPDATE tags SET tag_kind='status' WHERE category LIKE '%状态%' OR category LIKE '%status%' OR category LIKE '%Status%'")
  # Create index for efficient filtering
  c.execute('CREATE INDEX IF NOT EXISTS idx_tags_workspace_kind ON tags(workspace_id,tag_kind,enabled,sort_order)')
  c.execute('INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES(?,?,?,?,?,?)',(mid,'标签分类：状态类与画像类',checksum,t,'system',dumps({'status':'success','backfilledStatusTags':c.total_changes})))

def ensure_v207(c,admin_password=None):
 c.executescript(V207_SCHEMA);t=now_ms()
 for table,fields in {'workspaces':[('organization_id','TEXT')],'sources':[('organization_id','TEXT'),('team_id','TEXT'),('channel_account_id','TEXT')],'devices':[('organization_id','TEXT'),('team_id','TEXT'),('assigned_user_id','TEXT'),('system_device_name','TEXT'),('system_computer_name','TEXT'),('user_device_alias','TEXT'),('user_computer_alias','TEXT'),('admin_device_name','TEXT'),('admin_computer_name','TEXT')],'contacts':[('organization_id','TEXT'),('team_id','TEXT')],'events':[('user_id','TEXT') ]}.items():
  for col,decl in fields:_add(c,table,col,decl)
 c.execute("INSERT OR IGNORE INTO organizations(organization_id,name,status,created_at,updated_at) VALUES('org_default','默认企业','active',?,?)",(t,t))
 c.execute("UPDATE workspaces SET organization_id=COALESCE(organization_id,'org_default')")
 c.execute("INSERT OR IGNORE INTO teams(team_id,organization_id,workspace_id,name,status,created_at,updated_at) VALUES('team_default','org_default','default','默认团队','active',?,?)",(t,t))
 c.execute("UPDATE sources SET organization_id=COALESCE(organization_id,'org_default'),team_id=COALESCE(team_id,'team_default')")
 c.execute("UPDATE devices SET organization_id=COALESCE(organization_id,'org_default'),team_id=COALESCE(team_id,'team_default'),system_device_name=COALESCE(system_device_name,device_name),system_computer_name=COALESCE(system_computer_name,computer_name)")
 c.execute("UPDATE contacts SET organization_id=COALESCE(organization_id,'org_default'),team_id=COALESCE(team_id,'team_default')")
 for x in PERMS:c.execute('INSERT OR IGNORE INTO permissions(permission_key,description) VALUES(?,?)',(x,x))
 roles={'role_superadmin':('平台超级管理员','organization',PERMS),'role_orgadmin':('企业管理员','organization',PERMS),'role_teamlead':('团队主管','team',['team.read','user.read','account.read','source.read','device.read','device.disable','contact.read','contact.update','contact.delete','contact.restore','audit.read']),'role_operator':('操作员','team',['team.read','account.read','source.read','device.read','device.rename.self','contact.read','contact.update']),'role_readonly':('只读用户','team',['team.read','account.read','source.read','campaign.read','device.read','contact.read']),'role_auditor':('审计员','organization',['organization.read','team.read','user.read','role.read','account.read','source.read','campaign.read','device.read','contact.read','audit.read'])}
 for rid,(name,scope,ps) in roles.items():
  c.execute('INSERT OR IGNORE INTO roles(role_id,organization_id,name,scope_level,status) VALUES(?,?,?,?,?)',(rid,None,name,scope,'active'))
  for x in ps:c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',(rid,x))
 if not c.execute('SELECT 1 FROM users').fetchone():
  pwd=admin_password or 'ChangeMe-'+secrets.token_urlsafe(9);h,salt,it=hash_password(pwd)
  c.execute("INSERT INTO users(user_id,organization_id,login_name,display_name,status,created_at,updated_at) VALUES('usr_admin','org_default','admin','系统管理员','active',?,?)",(t,t));c.execute('INSERT INTO user_credentials(user_id,password_hash,salt,iterations,must_change,updated_at) VALUES(?,?,?,?,?,?)',('usr_admin',h,salt,it,1,t));c.execute("INSERT INTO organization_memberships(user_id,organization_id,role_id,status) VALUES('usr_admin','org_default','role_superadmin','active')")
  c.execute("INSERT INTO team_memberships(user_id,team_id,role_id,status) VALUES('usr_admin','team_default','role_superadmin','active')");c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('initial_admin_password',?)",(pwd,))
 c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version','207')");c.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('product_version','207.0.0')")
def validate_registered_migration_checksums(path):
 # 只读预检：发现校验和不匹配时打印警告，不阻止启动；后续 ensure_v207_* 会重新应用迁移。
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
  for mid,checksum in c.execute('SELECT migration_id,checksum FROM schema_migrations'):
   if mid in expected and checksum!=expected[mid]:
    print(f'[WARN] 迁移校验和不匹配: {mid}，将在初始化时重新应用迁移。')
 finally:c.close()

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
 def _repair_foreign_keys(self,c):
  """在保证 org_default / team_default 存在的前提下，尝试把孤儿行归到默认企业/默认团队。
  仅做最小修复：不删除任何业务行；修复失败也不阻止启动。"""
  t=now_ms()
  try:
   c.execute("INSERT OR IGNORE INTO organizations(organization_id,name,status,created_at,updated_at) VALUES('org_default','默认企业','active',?,?)",(t,t))
   c.execute("INSERT OR IGNORE INTO workspaces(workspace_id,name,status,created_at,updated_at,organization_id) VALUES('default','默认工作区','active',?,?,'org_default')",(t,t))
   c.execute("INSERT OR IGNORE INTO teams(team_id,organization_id,workspace_id,name,status,created_at,updated_at) VALUES('team_default','org_default','default','默认团队','active',?,?)",(t,t))
   c.execute("UPDATE workspaces SET organization_id=COALESCE(organization_id,'org_default')")
   c.execute("UPDATE teams SET organization_id=COALESCE(organization_id,'org_default'),workspace_id=COALESCE(workspace_id,'default')")
   c.execute("UPDATE users SET organization_id=COALESCE(organization_id,'org_default')")
   for tbl in ('sources','devices','contacts','channel_accounts'):
    if _cols(c,tbl) >= {'organization_id'}:
     c.execute(f"UPDATE {tbl} SET organization_id=COALESCE(organization_id,'org_default')")
    if _cols(c,tbl) >= {'team_id'}:
     c.execute(f"UPDATE {tbl} SET team_id=COALESCE(team_id,'team_default')")
   # 清理孤儿 source_devices / contact_custom_values / contact_tags（它们没有外键，但保持一致性）
   c.execute("DELETE FROM source_devices WHERE source_id NOT IN (SELECT source_id FROM sources) OR device_id NOT IN (SELECT device_id FROM devices)")
   c.execute("DELETE FROM contact_tags WHERE contact_id NOT IN (SELECT contact_id FROM contacts) OR tag_id NOT IN (SELECT tag_id FROM tags)")
   c.execute("DELETE FROM contact_custom_values WHERE contact_id NOT IN (SELECT contact_id FROM contacts)")
  except Exception as e:
   print(f'[WARN] 自动修复外键失败：{e}')
 def initialize(self,admin_password=None):
  fresh=not self.path.exists() or not self.path.stat().st_size
  backup=None
  if not fresh:
   validate_registered_migration_checksums(self.path)
   backup=self.path.with_suffix(self.path.suffix+'.pre-v2073.bak')
   src=sqlite3.connect(str(self.path));dst=sqlite3.connect(str(backup))
   try:src.backup(dst)
   finally:src.close();dst.close()
  c=self.connect()
  try:
   if fresh:
    c.executescript(BASE_SCHEMA);t=now_ms()
    c.execute("INSERT INTO workspaces(workspace_id,name,status,created_at,updated_at) VALUES('default','默认工作区','active',?,?)",(t,t))
    c.execute("INSERT INTO workspace_configs(workspace_id,revision,items_json,updated_at,updated_by) VALUES('default',0,'[]',?,'system')",(t,))
    for i in range(1,9):c.execute('INSERT INTO custom_field_definitions(workspace_id,field_key,label,field_type,sort_order,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',('default',f'f{i}',str(i),'text',i,1,t,t))
   # 1) 应用/重放所有幂等迁移
   ensure_v207(c,admin_password)
   ensure_v207_1(c)
   ensure_v207_101(c)
   ensure_v207_200(c)
   ensure_v207_300(c)
   ensure_v207_301(c)
   # 2) 自动修复历史孤儿行
   self._repair_foreign_keys(c)
   # 3) quick_check 失败只警告
   qc=c.execute('PRAGMA quick_check').fetchone()[0]
   if qc!='ok':
    print(f'[WARN] PRAGMA quick_check 返回 {qc}，服务继续启动；如功能异常请从 backup 目录恢复数据库。')
   # 4) 外键检查失败只警告，并打印前若干条违规
   fk=list(c.execute('PRAGMA foreign_key_check'))
   if fk:
    print(f'[WARN] 外键检查发现 {len(fk)} 个问题，服务继续启动。')
    for row in fk[:20]:
     try:print(f'[WARN] 外键违规: {dict(row)}')
     except Exception:print(f'[WARN] 外键违规: {row}')
  except Exception:
   c.close()
   if backup and backup.exists():shutil.copy2(backup,self.path)
   elif fresh and self.path.exists():self.path.unlink()
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