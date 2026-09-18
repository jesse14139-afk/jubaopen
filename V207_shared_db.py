# -*- coding: utf-8 -*-
"""聚宝盆 V207 数据层：Schema 207，多租户/RBAC/账号授权/设备双命名。"""
from __future__ import annotations
import contextlib, hashlib, json, sqlite3, time, secrets
from pathlib import Path
SCHEMA_VERSION=207; PRODUCT_VERSION="207.1.0"
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
 checksum=hashlib.sha256(V207_1_SCHEMA.encode()).hexdigest()
 c.execute("INSERT OR IGNORE INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES('V207_100_channel_attribution','渠道平台、来源触点与客户归因兼容升级',?,?,?,'{}')",(checksum,t,'system'))
 c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('product_version','207.1.0')")

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
 roles={'role_superadmin':('平台超级管理员','organization',PERMS),'role_orgadmin':('企业管理员','organization',PERMS),'role_teamlead':('团队主管','team',['team.read','user.read','account.read','source.read','device.read','device.disable','contact.read','contact.update','contact.delete','contact.restore','audit.read']),'role_operator':('操作员','team',['team.read','account.read','source.read','device.read','device.rename.self','contact.read','contact.update']),'role_readonly':('只读用户','team',['team.read','account.read','source.read','device.read','contact.read']),'role_auditor':('审计员','organization',['organization.read','team.read','user.read','role.read','account.read','source.read','device.read','contact.read','audit.read'])}
 for rid,(name,scope,ps) in roles.items():
  c.execute('INSERT OR IGNORE INTO roles(role_id,organization_id,name,scope_level,status) VALUES(?,?,?,?,?)',(rid,None,name,scope,'active'))
  for x in ps:c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',(rid,x))
 if not c.execute('SELECT 1 FROM users').fetchone():
  pwd=admin_password or 'ChangeMe-'+secrets.token_urlsafe(9);h,salt,it=hash_password(pwd)
  c.execute("INSERT INTO users(user_id,organization_id,login_name,display_name,status,created_at,updated_at) VALUES('usr_admin','org_default','admin','系统管理员','active',?,?)",(t,t));c.execute('INSERT INTO user_credentials(user_id,password_hash,salt,iterations,must_change,updated_at) VALUES(?,?,?,?,?,?)',('usr_admin',h,salt,it,1,t));c.execute("INSERT INTO organization_memberships(user_id,organization_id,role_id,status) VALUES('usr_admin','org_default','role_superadmin','active')")
  c.execute("INSERT INTO team_memberships(user_id,team_id,role_id,status) VALUES('usr_admin','team_default','role_superadmin','active')");c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('initial_admin_password',?)",(pwd,))
 c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version','207')");c.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('product_version','207.0.0')")
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
 def initialize(self,admin_password=None):
  fresh=not self.path.exists() or not self.path.stat().st_size;c=self.connect()
  try:
   if fresh:
    c.executescript(BASE_SCHEMA);t=now_ms();c.execute("INSERT INTO workspaces(workspace_id,name,status,created_at,updated_at) VALUES('default','默认工作区','active',?,?)",(t,t));c.execute("INSERT INTO workspace_configs(workspace_id,revision,items_json,updated_at,updated_by) VALUES('default',0,'[]',?,'system')",(t,));
    for i in range(1,9):c.execute('INSERT INTO custom_field_definitions(workspace_id,field_key,label,field_type,sort_order,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',('default',f'f{i}',str(i),'text',i,1,t,t))
   ensure_v207(c,admin_password);ensure_v207_1(c);c.commit()
   if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('DATABASE_INTEGRITY_ERROR')
  finally:c.close()
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
