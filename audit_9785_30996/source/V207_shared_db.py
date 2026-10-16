# -*- coding: utf-8 -*-
"""聚宝盆 V208.8.8 数据层：Schema 221，多租户/RBAC/账号授权/设备绑定。"""
from __future__ import annotations
import contextlib, hashlib, json, sqlite3, time, secrets, shutil, re, sys
from pathlib import Path
from V207_version import SCHEMA_VERSION, PRODUCT_VERSION, CATALOG_VERSION
def now_ms(): return int(time.time()*1000)
def default_workspace_id(c, organization_id):
 """优先使用全球业务工作区作为默认审计与授权上下文。"""
 row=c.execute("""SELECT workspace_id FROM workspaces WHERE organization_id=? AND status='active'
  ORDER BY CASE workspace_id WHEN 'ws-global' THEN 0 ELSE 1 END, created_at, workspace_id LIMIT 1""",(organization_id,)).fetchone()
 return row[0] if row else None
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
def _sqlite_backup(source_path,target_path):
 """Create a transactionally consistent SQLite backup, including WAL contents."""
 src=sqlite3.connect(str(source_path),timeout=30)
 dst=sqlite3.connect(str(target_path),timeout=30)
 try:src.backup(dst);dst.commit()
 finally:dst.close();src.close()

def _restore_sqlite_backup(backup_path,target_path):
 for suffix in ('-wal','-shm'):Path(str(target_path)+suffix).unlink(missing_ok=True)
 src=sqlite3.connect(str(backup_path),timeout=30)
 dst=sqlite3.connect(str(target_path),timeout=30)
 try:src.backup(dst);dst.commit()
 finally:dst.close();src.close()

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
CREATE TABLE IF NOT EXISTS team_memberships(user_id TEXT NOT NULL,team_id TEXT NOT NULL,membership_type TEXT NOT NULL DEFAULT 'member' CHECK(membership_type IN ('member','manager','operator','support')),is_primary INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0,1)),status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),joined_at INTEGER NOT NULL,left_at INTEGER,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,PRIMARY KEY(user_id,team_id),FOREIGN KEY(user_id) REFERENCES users(user_id) ON UPDATE NO ACTION ON DELETE NO ACTION,FOREIGN KEY(team_id) REFERENCES teams(team_id) ON UPDATE NO ACTION ON DELETE NO ACTION);
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
def _team_membership_schema211(c):
 cols=_cols(c,'team_memberships')
 return 'membership_type' in cols and 'role_id' not in cols
def hash_password(password,salt=None,it=260000):
 salt=salt or secrets.token_hex(16); h=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),it).hex(); return h,salt,it

V207_1_SCHEMA=r"""
CREATE TABLE IF NOT EXISTS security_events(security_event_id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT,organization_id TEXT,event_type TEXT NOT NULL,ip TEXT,user_agent TEXT,detail_json TEXT NOT NULL DEFAULT '{}',created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS schema_migrations(migration_id TEXT PRIMARY KEY,migration_name TEXT NOT NULL,checksum TEXT NOT NULL,applied_at INTEGER NOT NULL,applied_by TEXT NOT NULL,result_json TEXT NOT NULL DEFAULT '{}');
CREATE VIEW IF NOT EXISTS source_nodes AS SELECT * FROM sources;
CREATE TABLE IF NOT EXISTS platforms(platform_id TEXT PRIMARY KEY,platform_code TEXT NOT NULL UNIQUE,platform_name TEXT NOT NULL,platform_kind TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',capabilities_json TEXT NOT NULL DEFAULT '{}',metadata_json TEXT NOT NULL DEFAULT '{}',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS campaigns(campaign_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,platform_id TEXT,channel_account_id TEXT,campaign_code TEXT,campaign_name TEXT NOT NULL,campaign_type TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',start_at INTEGER,end_at INTEGER,metadata_json TEXT NOT NULL DEFAULT '{}',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,FOREIGN KEY(platform_id) REFERENCES platforms(platform_id),FOREIGN KEY(channel_account_id) REFERENCES channel_accounts(channel_account_id));
CREATE TABLE IF NOT EXISTS contact_identities(contact_identity_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,contact_id TEXT NOT NULL,platform_id TEXT,identity_type TEXT NOT NULL,identity_value TEXT NOT NULL,canonical_value TEXT NOT NULL,verification_status TEXT NOT NULL DEFAULT 'unverified',is_primary INTEGER NOT NULL DEFAULT 0,first_seen_at INTEGER NOT NULL,last_seen_at INTEGER NOT NULL,metadata_json TEXT NOT NULL DEFAULT '{}',FOREIGN KEY(contact_id) REFERENCES contacts(contact_id),FOREIGN KEY(platform_id) REFERENCES platforms(platform_id),UNIQUE(organization_id,platform_id,identity_type,canonical_value));
CREATE TABLE IF NOT EXISTS source_touchpoints(touchpoint_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,team_id TEXT,source_id TEXT NOT NULL,contact_id TEXT,platform_id TEXT,channel_account_id TEXT,campaign_id TEXT,touchpoint_type TEXT NOT NULL,direction TEXT NOT NULL DEFAULT 'inbound',initiated_by TEXT NOT NULL DEFAULT 'unknown',external_event_id TEXT,session_id TEXT,occurred_at INTEGER,metadata_json TEXT NOT NULL DEFAULT '{}',created_at INTEGER NOT NULL,FOREIGN KEY(source_id) REFERENCES sources(source_id),FOREIGN KEY(contact_id) REFERENCES contacts(contact_id),FOREIGN KEY(platform_id) REFERENCES platforms(platform_id),FOREIGN KEY(channel_account_id) REFERENCES channel_accounts(channel_account_id),FOREIGN KEY(campaign_id) REFERENCES campaigns(campaign_id));
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
  'platforms':[('platform_abbr','TEXT')],
  'channel_accounts':[('platform_id','TEXT'),('channel_type_id','TEXT'),('account_type',"TEXT NOT NULL DEFAULT 'business_account'"),('metadata_json',"TEXT NOT NULL DEFAULT '{}'")],
  'channel_account_identities':[('platform_id','TEXT'),('is_primary','INTEGER NOT NULL DEFAULT 0'),('status',"TEXT NOT NULL DEFAULT 'active'"),('valid_from','INTEGER'),('valid_to','INTEGER'),('metadata_json',"TEXT NOT NULL DEFAULT '{}'")],
  'user_credentials':[('failed_attempts','INTEGER NOT NULL DEFAULT 0'),('locked_until','INTEGER'),('last_failed_at','INTEGER')],
   'sources':[('platform_id','TEXT'),('channel_type_id','TEXT'),('source_type',"TEXT NOT NULL DEFAULT 'unknown'"),('source_subtype','TEXT'),('direction',"TEXT NOT NULL DEFAULT 'inbound'"),('initiated_by',"TEXT NOT NULL DEFAULT 'unknown'"),('campaign_id','TEXT'),('parent_source_id','TEXT'),('external_key','TEXT'),('landing_url','TEXT'),('tracking_code','TEXT'),('updated_at','INTEGER')]
 }.items():
  for col,decl in fields:_add(c,table,col,decl)
 seed=[('whatsapp','WhatsApp','messaging'),('instagram','Instagram','social'),('facebook','Facebook','social'),('messenger','Messenger','messaging'),('telegram','Telegram','messaging'),('line','LINE','messaging'),('tiktok','TikTok','social'),('google','Google','search'),('website','企业官网','owned'),('offline','线下','offline'),('google_ads','Google Ads','advertising'),('meta_ads','Meta Ads','advertising'),('import','数据导入','import')]
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
 c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('product_version',?)",(PRODUCT_VERSION,))

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
 c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('product_version',?)",(PRODUCT_VERSION,))

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
 for table,fields in {'workspaces':[('organization_id','TEXT')],'sources':[('organization_id','TEXT'),('team_id','TEXT'),('channel_account_id','TEXT')],'devices':[('organization_id','TEXT'),('team_id','TEXT'),('assigned_user_id','TEXT'),('system_device_name','TEXT'),('system_computer_name','TEXT'),('user_device_alias','TEXT'),('user_computer_alias','TEXT'),('admin_device_name','TEXT'),('admin_computer_name','TEXT')],'contacts':[('organization_id','TEXT'),('team_id','TEXT')],'events':[('user_id','TEXT') ]}.items():
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
team_memberships -> users/teams (membership fact; authorization is role_bindings)
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
 'team_memberships':{('user_id','users','user_id'),('team_id','teams','team_id')}}
IDENTITY_SCOPE_TRIGGERS={
 'trg_org_membership_scope_insert':"""CREATE TRIGGER IF NOT EXISTS trg_org_membership_scope_insert BEFORE INSERT ON organization_memberships BEGIN SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users u JOIN roles r ON r.role_id=NEW.role_id WHERE u.user_id=NEW.user_id AND u.organization_id=NEW.organization_id AND (r.organization_id IS NULL OR r.organization_id=NEW.organization_id)) THEN RAISE(ABORT,'MEMBERSHIP_SCOPE_INVALID') END; END""",
 'trg_org_membership_scope_update':"""CREATE TRIGGER IF NOT EXISTS trg_org_membership_scope_update BEFORE UPDATE OF user_id,organization_id,role_id ON organization_memberships BEGIN SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users u JOIN roles r ON r.role_id=NEW.role_id WHERE u.user_id=NEW.user_id AND u.organization_id=NEW.organization_id AND (r.organization_id IS NULL OR r.organization_id=NEW.organization_id)) THEN RAISE(ABORT,'MEMBERSHIP_SCOPE_INVALID') END; END""",
 'trg_team_membership_scope_insert':"""CREATE TRIGGER IF NOT EXISTS trg_team_membership_scope_insert BEFORE INSERT ON team_memberships BEGIN SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users u JOIN teams t ON t.team_id=NEW.team_id WHERE u.user_id=NEW.user_id AND u.organization_id=t.organization_id) THEN RAISE(ABORT,'TEAM_MEMBERSHIP_SCOPE_MISMATCH') END; END""",
 'trg_team_membership_scope_update':"""CREATE TRIGGER IF NOT EXISTS trg_team_membership_scope_update BEFORE UPDATE ON team_memberships BEGIN SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users u JOIN teams t ON t.team_id=NEW.team_id WHERE u.user_id=NEW.user_id AND u.organization_id=t.organization_id) THEN RAISE(ABORT,'TEAM_MEMBERSHIP_SCOPE_MISMATCH') END; END"""}

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
  'team_memberships.scope':"SELECT count(*) FROM team_memberships m LEFT JOIN users u ON u.user_id=m.user_id LEFT JOIN teams t ON t.team_id=m.team_id WHERE u.user_id IS NULL OR t.team_id IS NULL OR u.organization_id<>t.organization_id"}
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
   ('team_memberships',['user_id','team_id','membership_type','is_primary','status','joined_at','left_at','created_at','updated_at'],"CREATE TABLE team_memberships(user_id TEXT NOT NULL,team_id TEXT NOT NULL,membership_type TEXT NOT NULL DEFAULT 'member' CHECK(membership_type IN ('member','manager','operator','support')),is_primary INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0,1)),status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),joined_at INTEGER NOT NULL,left_at INTEGER,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,PRIMARY KEY(user_id,team_id),FOREIGN KEY(user_id) REFERENCES users(user_id) ON UPDATE NO ACTION ON DELETE NO ACTION,FOREIGN KEY(team_id) REFERENCES teams(team_id) ON UPDATE NO ACTION ON DELETE NO ACTION)"))
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
 if _team_membership_schema211(c):
  # Schema 211 intentionally removed team_memberships.role_id.  Do not replay
  # the superseded V208 identity/RBAC baseline against the final member table.
  if not _teams_fk_ready(c):raise RuntimeError('V208_OBJECT_ASSERTION_FAILED: teams foreign keys')
  actual={r[0] for r in c.execute("SELECT name FROM sqlite_schema WHERE type='trigger'")}
  required={'trg_department_cycle_insert','trg_department_cycle_update','trg_market_cycle_insert','trg_market_cycle_update','trg_business_line_cycle_insert','trg_business_line_cycle_update'}
  missing=sorted(required-actual)
  if missing:raise RuntimeError('V208_OBJECT_ASSERTION_FAILED: '+dumps(missing))
  identity_result={'status':'success','supersededBy':'Schema 211 membership/authorization separation'}
 else:
  identity_result=_ensure_identity_rbac_fk_baseline(c)
  _assert_v208_objects(c)
 _v208_record(c,'V208_030_foreign_key_baseline',{'status':'success','crossTenantTriggers':len(triggers),'hierarchyTriggers':len(hierarchy_triggers),'teamsForeignKeys':3})
 _v208_record(c,'V208_040_catalog_baseline',{'status':'success','catalogVersion':CATALOG_VERSION})
 _v208_record(c,'V208_050_identity_rbac_foreign_keys',identity_result)

BOOTSTRAP_FIELDS=('organization_id','organization_name','workspace_id','workspace_name','team_id','team_name','admin_user_id','admin_login','admin_display_name','admin_password')
def validate_bootstrap(bootstrap):
 if bootstrap is None:bootstrap={}
 b0={'organization_id':'jubaopen','organization_name':'聚宝盆企业','workspace_id':'ws-global','workspace_name':'全球业务工作区','team_id':'TEAM-JBP','team_name':'聚宝盆团队','admin_user_id':'platform_admin','admin_login':'admin','admin_display_name':'平台超级管理员','admin_password':'','builtin_default':'0'}
 bootstrap={**b0,**{k:v for k,v in bootstrap.items() if v is not None}}
 # Schema 217 fresh installs have one canonical workspace and primary team.
 bootstrap.update({'workspace_id':'ws-global','workspace_name':'全球业务工作区','team_id':'TEAM-JBP','team_name':'聚宝盆团队'})
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
 quick_fields=[('F'+str(i),str(i),'text','') for i in range(1,10)]
 for order,(key,label,typ,placeholder) in enumerate(quick_fields,1):
  c.execute("INSERT INTO custom_field_definitions(workspace_id,field_key,label,field_type,sort_order,enabled,created_at,updated_at,field_role,display_zone,is_quick_edit,options_json,placeholder) VALUES(?,?,?,?,?,1,?,?,'custom','interaction_panel',1,'[]',?)",(b['workspace_id'],key,label,typ,order,t,t,placeholder))
 c.execute("INSERT INTO custom_field_definitions(workspace_id,field_key,label,field_type,sort_order,enabled,created_at,updated_at,field_role,display_zone,is_quick_edit,options_json,placeholder) VALUES(?,?,?,?,?,1,?,?,'stage_customer','interaction_panel',0,?,'')",(b['workspace_id'],'customer_stage','客户阶段','multi_select',0,t,t,dumps(['一切','二切','三切'])))
 # Schema 217 workspace-scoped defaults: status is mutually exclusive; portrait is multi-select.
 preset_tags=[
  ('观察','status','#64748b','客户状态'),('开户','status','#2563eb','客户状态'),('入金','status','#16a34a','客户状态'),
   ('加金','status','#0891b2','客户状态'),('完成','status','#7c3aed','客户状态'),('放弃','status','#dc2626','客户状态'),
  ('高净值','portrait','#d97706','客户画像'),('股民','portrait','#0284c7','客户画像'),('有房','portrait','#059669','客户画像'),
  ('企业主','portrait','#7c3aed','客户画像'),('高意向','portrait','#e11d48','客户画像'),('低风险','portrait','#0f766e','客户画像'),('长期客户','portrait','#4f46e5','客户画像')]
 for order,(name,kind,color,category) in enumerate(preset_tags,1):
  c.execute("INSERT INTO tags(tag_id,workspace_id,name,color,category,tag_kind,sort_order,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,1,?,?)",('tag_seed_'+kind+'_'+str(order),b['workspace_id'],name,color,category,kind,order,t,t))

def _connect_strict_readonly(path):
 """Open a read-only consistent view; include committed WAL frames when present."""
 p=Path(path).resolve();wal=Path(str(p)+'-wal')
 # immutable=1 deliberately ignores WAL. Use ordinary read-only mode when WAL
 # exists so migration preflight validates the complete committed database.
 uri=p.as_uri()+'?mode=ro'+('' if wal.exists() and wal.stat().st_size else '&immutable=1')
 c=sqlite3.connect(uri,uri=True,timeout=30)
 c.execute('PRAGMA query_only=ON');c.execute('PRAGMA busy_timeout=30000')
 return c

def validate_registered_migration_checksums(path):
 """只读预检迁移登记；任何已知迁移校验和漂移均阻止启动。"""
 c=_connect_strict_readonly(path)
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
  expected[V211_MIGRATION_ID]=hashlib.sha256(V211_SIGNATURE.encode()).hexdigest() if 'V211_SIGNATURE' in globals() else None
  if 'V220_MIGRATION_ID' in globals():expected[V220_MIGRATION_ID]=hashlib.sha256(V220_SIGNATURE.encode()).hexdigest()
  bad=[]
  for mid,checksum in c.execute('SELECT migration_id,checksum FROM schema_migrations'):
   if mid in expected and checksum!=expected[mid]:bad.append(mid)
  if bad:raise RuntimeError('MIGRATION_CHECKSUM_MISMATCH: '+', '.join(bad))
 finally:c.close()

def readonly_preflight(path):
 """在备份和任何迁移写入前，以只读连接阻断损坏、歧义、孤立和跨租户数据。"""
 c=_connect_strict_readonly(path)
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
   ('team_memberships',"SELECT count(*) FROM team_memberships r LEFT JOIN users u ON u.user_id=r.user_id LEFT JOIN teams t ON t.team_id=r.team_id WHERE u.user_id IS NULL OR t.team_id IS NULL"),
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
 _add(c,'permissions','module_code',"TEXT NOT NULL DEFAULT '99'")
 _add(c,'permissions','sort_order','INTEGER NOT NULL DEFAULT 0')
 _add(c,'permissions','recommendation',"TEXT NOT NULL DEFAULT ''")
 _add(c,'permissions','related_pages_json',"TEXT NOT NULL DEFAULT '[]'")
 _add(c,'permissions','related_apis_json',"TEXT NOT NULL DEFAULT '[]'")
 _add(c,'sessions','revoked_reason','TEXT')
 _add(c,'sessions','revoked_by','TEXT')
 c.execute("UPDATE roles SET role_code=COALESCE(NULLIF(role_code,''),role_id),description=COALESCE(description,''),is_system=CASE WHEN role_id IN ('role_superadmin','role_orgadmin','role_teamlead','role_operator','role_readonly','role_auditor') THEN 1 ELSE is_system END")
 c.execute("UPDATE permissions SET display_name=COALESCE(NULLIF(display_name,''),description,permission_key),resource=COALESCE(NULLIF(resource,''),CASE WHEN instr(permission_key,'.')>0 THEN substr(permission_key,1,instr(permission_key,'.')-1) ELSE permission_key END),action=COALESCE(NULLIF(action,''),CASE WHEN instr(permission_key,'.')>0 THEN substr(permission_key,instr(permission_key,'.')+1) ELSE 'access' END)")
 # Dedicated authorization-center permissions; legacy role.manage grants are copied for upgrade compatibility.
 dedicated=(
  ('permission.read','查看权限目录和权限矩阵','07','low',63),
  ('permission.manage','维护企业自定义角色权限','07','high',30),
  ('role.binding.read','查看用户角色授权关系','07','medium',30),
  ('role.binding.manage','新增、调整、续期和撤销角色授权','07','high',30),
  ('role.template.read','查看平台标准角色模板','07','medium',48),
  ('role.template.manage','维护平台标准角色模板版本','07','critical',32),
  ('source.reference.read','在业务表单中引用来源名称','03','low',31),
 )
 for key,desc,module,risk,mask in dedicated:
  c.execute('INSERT OR IGNORE INTO permissions(permission_key,description,display_name,resource,action,scope_mask,risk_level,module_code,recommendation) VALUES(?,?,?,?,?,?,?,?,?)',(key,desc,desc,key.split('.')[0],key.split('.')[-1],mask,risk,module,'遵循最小权限原则并定期复核。'))
 for key in ('permission.read','permission.manage','role.binding.read','role.binding.manage'):
  c.execute("INSERT OR IGNORE INTO role_permissions(role_id,permission_key) SELECT role_id,? FROM role_permissions WHERE permission_key='role.manage'",(key,))
 for key in ('role.template.read','role.template.manage'):
  c.execute("INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES('role_superadmin',?)",(key,))
 c.execute("UPDATE permissions SET scope_mask=1,module_code='08',risk_level='medium' WHERE permission_key='device.rename.self'")
 c.execute("UPDATE permissions SET module_code=CASE WHEN permission_key LIKE 'contact.%' THEN '01' WHEN permission_key LIKE 'conversation.%' OR permission_key LIKE 'message.%' OR permission_key LIKE 'transfer.%' THEN '02' WHEN permission_key LIKE 'source.%' OR permission_key LIKE 'campaign.%' THEN '03' WHEN permission_key LIKE 'touchpoint.%' OR permission_key LIKE 'attribution.%' OR permission_key LIKE 'conversion.%' THEN '04' WHEN permission_key LIKE 'account.%' OR permission_key LIKE 'platform.%' THEN '05' WHEN permission_key LIKE 'organization.%' OR permission_key LIKE 'team.%' OR permission_key LIKE 'user.%' THEN '06' WHEN permission_key LIKE 'role.%' OR permission_key LIKE 'permission.%' THEN '07' WHEN permission_key LIKE 'device.%' OR permission_key LIKE 'collector.%' THEN '08' WHEN permission_key LIKE 'audit.%' THEN '09' ELSE COALESCE(NULLIF(module_code,''),'99') END")
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
 if not old:c.execute('INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES(?,?,?,?,?,?)',(V210_MIGRATION_ID,'Unified RBAC authorization center',checksum,t,'system',dumps({'status':'success'})))


# V207.8 / Schema 211：团队成员是组织事实，role_bindings 是唯一权限来源。
V211_MIGRATION_ID='V211_000_legacy_organization_cleanup'
V211_SIGNATURE="""Schema 211 / catalog 211.0
team_memberships(user_id,team_id,membership_type,is_primary,status,joined_at,left_at,created_at,updated_at)
role_bindings is the only authorization source; platform bootstrap has no implicit team role
organization/team membership scope triggers and primary workspace constraints are mandatory
"""
def ensure_v211(c):
 checksum=hashlib.sha256(V211_SIGNATURE.encode()).hexdigest()
 old=c.execute('SELECT checksum FROM schema_migrations WHERE migration_id=?',(V211_MIGRATION_ID,)).fetchone()
 if old and old[0]!=checksum:raise RuntimeError('MIGRATION_CHECKSUM_MISMATCH: '+V211_MIGRATION_ID)
 cols=_cols(c,'team_memberships')
 required={'user_id','team_id','membership_type','is_primary','status','joined_at','left_at','created_at','updated_at'}
 if cols!=required:raise RuntimeError('SCHEMA_211_TEAM_MEMBERSHIP_INVALID: '+dumps(sorted(cols)))
 for name in ('trg_org_membership_scope_insert','trg_org_membership_scope_update'):
  c.execute(IDENTITY_SCOPE_TRIGGERS[name])
 execute_sql_script(c,"""
 CREATE INDEX IF NOT EXISTS idx_team_memberships_team ON team_memberships(team_id,status,is_primary);
 CREATE INDEX IF NOT EXISTS idx_team_memberships_user ON team_memberships(user_id,status,is_primary);
 CREATE UNIQUE INDEX IF NOT EXISTS uq_user_primary_team ON team_memberships(user_id) WHERE is_primary=1 AND status='active';
 CREATE UNIQUE INDEX IF NOT EXISTS uq_team_primary_workspace ON workspace_teams(team_id) WHERE is_primary=1 AND status='active';
 CREATE TRIGGER IF NOT EXISTS trg_team_membership_scope_insert BEFORE INSERT ON team_memberships BEGIN
  SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users u JOIN teams t ON t.team_id=NEW.team_id WHERE u.user_id=NEW.user_id AND u.organization_id=t.organization_id) THEN RAISE(ABORT,'TEAM_MEMBERSHIP_SCOPE_MISMATCH') END;
 END;
 CREATE TRIGGER IF NOT EXISTS trg_team_membership_scope_update BEFORE UPDATE ON team_memberships BEGIN
  SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users u JOIN teams t ON t.team_id=NEW.team_id WHERE u.user_id=NEW.user_id AND u.organization_id=t.organization_id) THEN RAISE(ABORT,'TEAM_MEMBERSHIP_SCOPE_MISMATCH') END;
 END;
 CREATE TRIGGER IF NOT EXISTS trg_team_primary_workspace_insert BEFORE INSERT ON workspace_teams WHEN NEW.is_primary=1 AND NEW.status='active' BEGIN
  SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM teams t WHERE t.team_id=NEW.team_id AND t.workspace_id=NEW.workspace_id AND t.organization_id=NEW.organization_id) THEN RAISE(ABORT,'TEAM_PRIMARY_WORKSPACE_MISMATCH') END;
 END;
 CREATE TRIGGER IF NOT EXISTS trg_team_primary_workspace_update BEFORE UPDATE OF workspace_id,team_id,organization_id,is_primary,status ON workspace_teams WHEN NEW.is_primary=1 AND NEW.status='active' BEGIN
  SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM teams t WHERE t.team_id=NEW.team_id AND t.workspace_id=NEW.workspace_id AND t.organization_id=NEW.organization_id) THEN RAISE(ABORT,'TEAM_PRIMARY_WORKSPACE_MISMATCH') END;
 END;
 """)
 c.execute("DELETE FROM role_bindings WHERE binding_id LIKE 'bootstrap:team:%' AND user_id IN (SELECT user_id FROM platform_administrators WHERE is_builtin=1)")
 t=now_ms()
 if not old:c.execute('INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES(?,?,?,?,?,?)',(V211_MIGRATION_ID,'Schema 211 成员权限分离与主工作区约束',checksum,t,'system',dumps({'status':'success'})))

# Schema 213：全新安装基线，不提供旧数据库升级路径。
def ensure_v212(c):
 c.execute("""CREATE TABLE IF NOT EXISTS device_enrollments(
  enrollment_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, workspace_id TEXT NOT NULL, team_id TEXT NOT NULL,
  assigned_user_id TEXT NOT NULL, admin_device_name TEXT NOT NULL DEFAULT '', admin_computer_name TEXT NOT NULL DEFAULT '',
  binding_code_hash TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','consumed','expired','revoked')),
  expires_at INTEGER NOT NULL, consumed_at INTEGER, consumed_device_id TEXT, created_by TEXT NOT NULL, created_at INTEGER NOT NULL,
  revoked_at INTEGER, revoked_by TEXT, reason TEXT NOT NULL,
  FOREIGN KEY(organization_id) REFERENCES organizations(organization_id), FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
  FOREIGN KEY(team_id) REFERENCES teams(team_id), FOREIGN KEY(assigned_user_id) REFERENCES users(user_id),
  FOREIGN KEY(consumed_device_id) REFERENCES devices(device_id), FOREIGN KEY(created_by) REFERENCES users(user_id), FOREIGN KEY(revoked_by) REFERENCES users(user_id)
 )""")
 c.execute('CREATE INDEX IF NOT EXISTS idx_device_enrollment_org_status ON device_enrollments(organization_id,status,expires_at)')
 c.execute('CREATE INDEX IF NOT EXISTS idx_device_enrollment_team ON device_enrollments(team_id,status)')


# V208.0.0 / Schema 213：插件采集、会话消息、客户转移与互动面板服务端基线。
def ensure_v213(c):
 _add(c,'channel_accounts','business_purpose',"TEXT NOT NULL DEFAULT 'hybrid' CHECK(business_purpose IN ('acquisition','conversion','hybrid'))")
 _add(c,'channel_accounts','collection_enabled','INTEGER NOT NULL DEFAULT 1 CHECK(collection_enabled IN (0,1))')
 _add(c,'custom_field_definitions','field_role',"TEXT NOT NULL DEFAULT 'custom'")
 _add(c,'custom_field_definitions','display_zone',"TEXT NOT NULL DEFAULT 'workbench'")
 _add(c,'custom_field_definitions','is_quick_edit','INTEGER NOT NULL DEFAULT 0 CHECK(is_quick_edit IN (0,1))')
 _add(c,'custom_field_definitions','options_json',"TEXT NOT NULL DEFAULT '[]'")
 _add(c,'custom_field_definitions','placeholder',"TEXT NOT NULL DEFAULT ''")
 execute_sql_script(c,"""
 CREATE TABLE IF NOT EXISTS plugin_sessions(
  plugin_session_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,team_id TEXT NOT NULL,
  user_id TEXT NOT NULL,device_id TEXT NOT NULL,token_hash TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','revoked','expired')),
  issued_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,last_seen_at INTEGER NOT NULL,revoked_at INTEGER,revoked_by TEXT,
  revoked_reason TEXT NOT NULL DEFAULT '',client_version TEXT NOT NULL DEFAULT '',metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
  FOREIGN KEY(team_id) REFERENCES teams(team_id),FOREIGN KEY(user_id) REFERENCES users(user_id),FOREIGN KEY(device_id) REFERENCES devices(device_id),
  FOREIGN KEY(revoked_by) REFERENCES users(user_id));
 CREATE INDEX IF NOT EXISTS idx_plugin_sessions_subject ON plugin_sessions(user_id,device_id,status,expires_at);
 CREATE TABLE IF NOT EXISTS device_channel_account_bindings(
  binding_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,team_id TEXT NOT NULL,device_id TEXT NOT NULL,
  user_id TEXT NOT NULL,channel_account_id TEXT NOT NULL,platform_id TEXT NOT NULL,external_account_key TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled','revoked')),bound_at INTEGER NOT NULL,bound_by TEXT NOT NULL,
  last_verified_at INTEGER NOT NULL,metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
  FOREIGN KEY(team_id) REFERENCES teams(team_id),FOREIGN KEY(device_id) REFERENCES devices(device_id),FOREIGN KEY(user_id) REFERENCES users(user_id),
  FOREIGN KEY(channel_account_id) REFERENCES channel_accounts(channel_account_id),FOREIGN KEY(platform_id) REFERENCES platforms(platform_id),
  FOREIGN KEY(bound_by) REFERENCES users(user_id),UNIQUE(device_id,platform_id,external_account_key));
 CREATE INDEX IF NOT EXISTS idx_device_account_binding ON device_channel_account_bindings(device_id,status,last_verified_at);
 CREATE TABLE IF NOT EXISTS device_rebind_requests(
  rebind_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,device_id TEXT NOT NULL,from_user_id TEXT,to_user_id TEXT NOT NULL,
  from_team_id TEXT,to_team_id TEXT NOT NULL,to_workspace_id TEXT NOT NULL,code_hash TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','consumed','revoked','expired')),
  expires_at INTEGER NOT NULL,created_by TEXT NOT NULL,created_at INTEGER NOT NULL,consumed_at INTEGER,revoked_at INTEGER,revoked_by TEXT,
  reason TEXT NOT NULL,FOREIGN KEY(device_id) REFERENCES devices(device_id),FOREIGN KEY(to_user_id) REFERENCES users(user_id),
  FOREIGN KEY(to_team_id) REFERENCES teams(team_id),FOREIGN KEY(to_workspace_id) REFERENCES workspaces(workspace_id));
 CREATE UNIQUE INDEX IF NOT EXISTS uq_device_pending_rebind ON device_rebind_requests(device_id) WHERE status='pending';
 CREATE INDEX IF NOT EXISTS idx_device_rebind_code ON device_rebind_requests(code_hash,status,expires_at);
 CREATE TABLE IF NOT EXISTS conversations(
  conversation_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,team_id TEXT NOT NULL,
  channel_account_id TEXT NOT NULL,platform_id TEXT NOT NULL,contact_id TEXT NOT NULL,contact_identity_id TEXT,
  external_conversation_id TEXT NOT NULL,conversation_type TEXT NOT NULL DEFAULT 'direct' CHECK(conversation_type='direct'),
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','closed','archived')),assigned_user_id TEXT,source_id TEXT,
  first_message_at INTEGER,last_message_at INTEGER,last_collected_at INTEGER,metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
  FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
  FOREIGN KEY(team_id) REFERENCES teams(team_id),FOREIGN KEY(channel_account_id) REFERENCES channel_accounts(channel_account_id),
  FOREIGN KEY(platform_id) REFERENCES platforms(platform_id),FOREIGN KEY(contact_id) REFERENCES contacts(contact_id) ON DELETE RESTRICT,
  FOREIGN KEY(contact_identity_id) REFERENCES contact_identities(contact_identity_id),FOREIGN KEY(assigned_user_id) REFERENCES users(user_id),
  FOREIGN KEY(source_id) REFERENCES sources(source_id),UNIQUE(organization_id,channel_account_id,external_conversation_id));
 CREATE INDEX IF NOT EXISTS idx_conversations_contact_time ON conversations(contact_id,last_message_at);
 CREATE INDEX IF NOT EXISTS idx_conversations_team_time ON conversations(team_id,last_message_at);
 CREATE INDEX IF NOT EXISTS idx_conversations_assignee ON conversations(assigned_user_id,status,last_message_at);
 CREATE TABLE IF NOT EXISTS conversation_messages(
  message_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,team_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,channel_account_id TEXT NOT NULL,contact_id TEXT NOT NULL,external_message_id TEXT,client_event_id TEXT,
  direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound','system')),sender_type TEXT NOT NULL DEFAULT 'unknown',sender_external_id TEXT,
  content_type TEXT NOT NULL CHECK(content_type IN ('text','image','audio','video','file','sticker','share','post','reel','story','location','contact','call','system','unknown')),
  text_content TEXT,redacted_text TEXT,content_hash TEXT NOT NULL,pii_flags_json TEXT NOT NULL DEFAULT '[]',occurred_at INTEGER,
  collected_at INTEGER NOT NULL,edited_at INTEGER,deleted_at INTEGER,content_deleted_at INTEGER,content_deleted_by TEXT,
  content_delete_reason TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','edited','deleted','content_deleted')),
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
  FOREIGN KEY(team_id) REFERENCES teams(team_id),FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id),
  FOREIGN KEY(channel_account_id) REFERENCES channel_accounts(channel_account_id),FOREIGN KEY(contact_id) REFERENCES contacts(contact_id) ON DELETE RESTRICT,
  FOREIGN KEY(content_deleted_by) REFERENCES users(user_id));
 CREATE UNIQUE INDEX IF NOT EXISTS uq_message_external ON conversation_messages(organization_id,channel_account_id,external_message_id) WHERE external_message_id IS NOT NULL AND external_message_id<>'';
 CREATE UNIQUE INDEX IF NOT EXISTS uq_message_client_event ON conversation_messages(organization_id,channel_account_id,client_event_id) WHERE client_event_id IS NOT NULL AND client_event_id<>'';
 CREATE INDEX IF NOT EXISTS idx_messages_conversation_time ON conversation_messages(conversation_id,occurred_at);
 CREATE INDEX IF NOT EXISTS idx_messages_contact_time ON conversation_messages(contact_id,occurred_at);
 CREATE INDEX IF NOT EXISTS idx_messages_team_time ON conversation_messages(team_id,occurred_at);
 CREATE TABLE IF NOT EXISTS contact_transfers(
  transfer_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,team_id TEXT NOT NULL,contact_id TEXT NOT NULL,
  from_channel_account_id TEXT,from_conversation_id TEXT,to_channel_account_id TEXT NOT NULL,to_conversation_id TEXT,
  transfer_method TEXT NOT NULL CHECK(transfer_method IN ('phone_shared','username_shared','invite_link','qr_code','manual_link','system_match','other')),
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','confirmed','failed','cancelled')),transferred_by TEXT NOT NULL,
  transferred_at INTEGER NOT NULL,confirmed_by TEXT,confirmed_at INTEGER,reason TEXT NOT NULL DEFAULT '',metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
  FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
  FOREIGN KEY(team_id) REFERENCES teams(team_id),FOREIGN KEY(contact_id) REFERENCES contacts(contact_id) ON DELETE RESTRICT,
  FOREIGN KEY(from_channel_account_id) REFERENCES channel_accounts(channel_account_id),FOREIGN KEY(from_conversation_id) REFERENCES conversations(conversation_id),
  FOREIGN KEY(to_channel_account_id) REFERENCES channel_accounts(channel_account_id),FOREIGN KEY(to_conversation_id) REFERENCES conversations(conversation_id),
  FOREIGN KEY(transferred_by) REFERENCES users(user_id),FOREIGN KEY(confirmed_by) REFERENCES users(user_id));
 CREATE INDEX IF NOT EXISTS idx_transfers_contact_time ON contact_transfers(contact_id,transferred_at);
 CREATE TRIGGER IF NOT EXISTS trg_plugin_session_scope_insert BEFORE INSERT ON plugin_sessions BEGIN
  SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users u,devices d,teams t,workspaces w WHERE u.user_id=NEW.user_id AND u.organization_id=NEW.organization_id AND u.status='active' AND d.device_id=NEW.device_id AND d.organization_id=NEW.organization_id AND d.workspace_id=NEW.workspace_id AND d.team_id=NEW.team_id AND d.status='active' AND t.team_id=NEW.team_id AND t.organization_id=NEW.organization_id AND t.workspace_id=NEW.workspace_id AND w.workspace_id=NEW.workspace_id AND w.organization_id=NEW.organization_id) THEN RAISE(ABORT,'PLUGIN_SESSION_SCOPE_MISMATCH') END; END;
 CREATE TRIGGER IF NOT EXISTS trg_device_account_scope_insert BEFORE INSERT ON device_channel_account_bindings BEGIN
  SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM devices d JOIN teams t ON t.team_id=NEW.team_id JOIN channel_accounts a ON a.channel_account_id=NEW.channel_account_id JOIN team_channel_accounts x ON x.team_id=NEW.team_id AND x.channel_account_id=NEW.channel_account_id JOIN users u ON u.user_id=NEW.user_id WHERE d.device_id=NEW.device_id AND d.organization_id=NEW.organization_id AND d.workspace_id=NEW.workspace_id AND d.team_id=NEW.team_id AND t.organization_id=NEW.organization_id AND t.workspace_id=NEW.workspace_id AND a.organization_id=NEW.organization_id AND a.platform_id=NEW.platform_id AND a.status='active' AND a.collection_enabled=1 AND u.organization_id=NEW.organization_id AND u.status='active') THEN RAISE(ABORT,'DEVICE_ACCOUNT_SCOPE_MISMATCH') END; END;
 CREATE TRIGGER IF NOT EXISTS trg_conversation_scope_insert BEFORE INSERT ON conversations BEGIN
  SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM channel_accounts a JOIN team_channel_accounts x ON x.channel_account_id=a.channel_account_id AND x.team_id=NEW.team_id JOIN contacts c ON c.contact_id=NEW.contact_id JOIN teams t ON t.team_id=NEW.team_id WHERE a.channel_account_id=NEW.channel_account_id AND a.organization_id=NEW.organization_id AND a.platform_id=NEW.platform_id AND c.organization_id=NEW.organization_id AND c.workspace_id=NEW.workspace_id AND c.team_id=NEW.team_id AND t.organization_id=NEW.organization_id AND t.workspace_id=NEW.workspace_id) THEN RAISE(ABORT,'CONVERSATION_SCOPE_MISMATCH') END; END;
 CREATE TRIGGER IF NOT EXISTS trg_message_scope_insert BEFORE INSERT ON conversation_messages BEGIN
  SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM conversations v WHERE v.conversation_id=NEW.conversation_id AND v.organization_id=NEW.organization_id AND v.workspace_id=NEW.workspace_id AND v.team_id=NEW.team_id AND v.channel_account_id=NEW.channel_account_id AND v.contact_id=NEW.contact_id) THEN RAISE(ABORT,'MESSAGE_SCOPE_MISMATCH') END; END;
 """)
 perms=[
 ('collector.session.issue','签发插件会话','collector','session.issue','high'),('collector.write','插件采集写入','collector','write','medium'),('contact.create','新建客户','contact','create','medium'),
 ('collector.account.resolve','解析采集账号','collector','account.resolve','medium'),('collector.conversation.resolve','解析采集会话','collector','conversation.resolve','medium'),
 ('contact.read.assigned','读取分配客户','contact','read.assigned','low'),('contact.update.assigned','更新分配客户','contact','update.assigned','medium'),
 ('conversation.read.self','读取本人会话','conversation','read.self','low'),('conversation.read.team','读取团队会话','conversation','read.team','medium'),
 ('conversation.manage','管理会话','conversation','manage','medium'),('message.read.self','读取本人消息','message','read.self','medium'),
 ('message.read.team','读取团队消息','message','read.team','high'),('message.read.raw','读取消息原文','message','read.raw','critical'),
 ('message.export.redacted','导出脱敏消息','message','export.redacted','high'),('message.export.raw','导出原文消息','message','export.raw','critical'),
 ('message.delete.content','删除消息正文','message','delete.content','critical'),('transfer.create','创建客户转移','transfer','create','medium'),
 ('transfer.manage','管理客户转移','transfer','manage','high'),('pii.read.full','读取完整敏感信息','pii','read.full','critical')]
 for k,d,res,act,risk in perms:c.execute('INSERT OR IGNORE INTO permissions(permission_key,description,display_name,resource,action,scope_mask,risk_level) VALUES(?,?,?,?,?,63,?)',(k,d,d,res,act,risk))
 for role in ('role_superadmin','role_orgadmin'):
  for k,*_ in perms:c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',(role,k))
 for role in ('role_teamlead','role_operator'):
  for k in ('collector.session.issue','collector.write','collector.account.resolve','collector.conversation.resolve','contact.create','contact.read.assigned','contact.update.assigned','conversation.read.self','message.read.self','transfer.create'):
   c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',(role,k))
 t=now_ms(); sig=hashlib.sha256(b'Schema 213 V208 phase1 server truth center').hexdigest()
 c.execute("INSERT OR IGNORE INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES('V213_000_phase1_collector','V208阶段1采集会话消息基线',?,?,?,?)",(sig,t,'system',dumps({'status':'success','schema':213})))

def ensure_v214(c):
 """Schema 214: account claim slots, approval queue, and WA canonical repair."""
 execute_sql_script(c,"""
 CREATE TABLE IF NOT EXISTS account_binding_slots(
  slot_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,team_id TEXT NOT NULL,user_id TEXT NOT NULL,
  platform_id TEXT NOT NULL,channel_account_id TEXT,expected_phone TEXT,expected_username TEXT,
  claim_policy TEXT NOT NULL DEFAULT 'auto' CHECK(claim_policy IN ('auto','approval')),
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','claimed','disabled')),
  claimed_identity_type TEXT,claimed_canonical_value TEXT,claimed_device_id TEXT,claimed_at INTEGER,
  created_by TEXT NOT NULL,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,disabled_at INTEGER,disabled_by TEXT,reason TEXT,
  FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
  FOREIGN KEY(team_id) REFERENCES teams(team_id),FOREIGN KEY(user_id) REFERENCES users(user_id),
  FOREIGN KEY(platform_id) REFERENCES platforms(platform_id),FOREIGN KEY(channel_account_id) REFERENCES channel_accounts(channel_account_id)
 );
 CREATE INDEX IF NOT EXISTS idx_binding_slots_subject ON account_binding_slots(organization_id,user_id,platform_id,status);
 CREATE INDEX IF NOT EXISTS idx_binding_slots_team ON account_binding_slots(organization_id,team_id,status);
 CREATE UNIQUE INDEX IF NOT EXISTS uq_binding_slot_active_user_platform ON account_binding_slots(organization_id,user_id,platform_id) WHERE status='pending';
 CREATE TABLE IF NOT EXISTS account_identity_discoveries(
  discovery_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,team_id TEXT NOT NULL,user_id TEXT NOT NULL,
  platform_id TEXT NOT NULL,identity_type TEXT NOT NULL,canonical_value TEXT NOT NULL,identity_value TEXT NOT NULL,
  auxiliary_json TEXT NOT NULL DEFAULT '{}',device_id TEXT,plugin_session_id TEXT,slot_id TEXT,channel_account_id TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','auto_claimed','approved','rejected','conflict','expired')),
  reason_code TEXT,first_seen_at INTEGER NOT NULL,last_seen_at INTEGER NOT NULL,resolved_at INTEGER,resolved_by TEXT,resolution_reason TEXT,
  FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
  FOREIGN KEY(team_id) REFERENCES teams(team_id),FOREIGN KEY(user_id) REFERENCES users(user_id),FOREIGN KEY(platform_id) REFERENCES platforms(platform_id),
  FOREIGN KEY(slot_id) REFERENCES account_binding_slots(slot_id),FOREIGN KEY(channel_account_id) REFERENCES channel_accounts(channel_account_id)
 );
 CREATE INDEX IF NOT EXISTS idx_identity_discoveries_status ON account_identity_discoveries(organization_id,status,last_seen_at DESC);
 CREATE INDEX IF NOT EXISTS idx_identity_discoveries_subject ON account_identity_discoveries(organization_id,user_id,platform_id);
 CREATE UNIQUE INDEX IF NOT EXISTS uq_identity_discovery_subject ON account_identity_discoveries(organization_id,user_id,platform_id,identity_type,canonical_value);
 """)
 # Repair only unambiguous numeric WhatsApp identities; conflicts are preserved for administrator review.
 wa_platforms=[r[0] for r in c.execute("SELECT platform_id FROM platforms WHERE lower(platform_code)='whatsapp' OR lower(platform_name)='whatsapp'")]
 repaired=conflicts=0
 for pid in wa_platforms:
  records=list(c.execute("""SELECT i.identity_id,i.channel_account_id,i.identity_type,i.identity_value,i.canonical_value
   FROM channel_account_identities i JOIN channel_accounts a ON a.channel_account_id=i.channel_account_id
   WHERE a.platform_id=?""",(pid,)))
  for r in records:
   raw=str(r[4] or r[3] or '');digits=''.join(x for x in raw.split('@',1)[0] if x.isdigit())
   if not (7<=len(digits)<=20) or '@lid' in raw.lower():continue
   canonical=digits+'@c.us'
   duplicate=c.execute("""SELECT 1 FROM channel_account_identities i JOIN channel_accounts a ON a.channel_account_id=i.channel_account_id
    WHERE a.platform_id=? AND i.identity_id<>? AND i.identity_type='whatsapp_jid' AND i.canonical_value=? LIMIT 1""",(pid,r[0],canonical)).fetchone()
   if duplicate:conflicts+=1;continue
   if r[2]!='whatsapp_jid' or r[4]!=canonical or r[3]!=canonical:
    c.execute("UPDATE channel_account_identities SET identity_type='whatsapp_jid',identity_value=?,canonical_value=? WHERE identity_id=?",(canonical,canonical,r[0]));repaired+=1
 sig=hashlib.sha256(b'Schema 214 account identity claim slots and discovery approval').hexdigest();t=now_ms()
 c.execute("INSERT OR IGNORE INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES('V214_000_account_identity_claim','账号身份自动认领与审批',?,?,?,?)",(sig,t,'system',dumps({'status':'success','schema':214,'whatsappRepaired':repaired,'whatsappConflicts':conflicts})))

def _read_existing_schema_version(path):
 """只读识别现有数据库；不猜测、升级或修改未知结构。"""
 c=_connect_strict_readonly(path)
 try:
  if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone():
   return None
  row=c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
  return str(row[0]).strip() if row and row[0] is not None else None
 finally:c.close()

def validate_schema213_readonly(path):
 """Schema 213 重启路径：严格只读校验，绝不重放历史迁移。"""
 c=_connect_strict_readonly(path);c.row_factory=sqlite3.Row
 try:
  required_tables={
   'meta','schema_migrations','organizations','workspaces','teams','users',
   'user_credentials','roles','permissions','role_permissions','role_bindings',
   'team_memberships','audit_logs','sessions','device_enrollments','channel_types','source_type_definitions',
    'plugin_sessions','device_channel_account_bindings','conversations','conversation_messages','contact_transfers'
  }
  actual={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  missing=sorted(required_tables-actual)
  if missing:raise RuntimeError('SCHEMA_213_INVALID: missing tables: '+','.join(missing))
  cols={r[1] for r in c.execute('PRAGMA table_info(team_memberships)')}
  required_cols={'user_id','team_id','membership_type','is_primary','status','joined_at','left_at','created_at','updated_at'}
  missing_cols=sorted(required_cols-cols)
  if missing_cols:raise RuntimeError('SCHEMA_213_INVALID: team_memberships missing columns: '+','.join(missing_cols))
  if 'role_id' in cols:raise RuntimeError('SCHEMA_213_INVALID: legacy team_memberships.role_id exists')
  device_cols={r[1] for r in c.execute('PRAGMA table_info(devices)')}
  legacy_device_cols=sorted({'binding_code','binding_code_expires_at','binding_code_hash'} & device_cols)
  if legacy_device_cols:raise RuntimeError('SCHEMA_213_INVALID: legacy devices columns exist: '+','.join(legacy_device_cols))
  # 固定 Schema 213 约束基线：防止结构可读但关键业务约束已被误删。
  required_indexes={
   'idx_attribution_contact',
   'idx_attribution_contact_rule',
   'idx_business_line_org_parent',
   'idx_campaign_org',
   'idx_changes_cursor',
   'idx_contact_identity_lookup',
   'idx_contacts_source',
   'idx_department_org_parent',
   'idx_identity_lookup',
   'idx_market_org_parent',
   'idx_positions_org_department',
   'idx_rbac_confirmations_user',
   'idx_role_bindings_scope',
   'idx_role_bindings_subject',
   'idx_source_links_from',
   'idx_source_links_to',
   'idx_tags_workspace_kind',
   'idx_team_bl_org_line',
   'idx_team_markets_org_market',
   'idx_device_enrollment_org_status','idx_device_enrollment_team','idx_plugin_sessions_subject','idx_device_account_binding',
    'idx_conversations_contact_time','idx_messages_conversation_time','idx_transfers_contact_time',
   'idx_team_memberships_team',
   'idx_team_memberships_user',
   'idx_touchpoint_contact_occurred',
   'idx_touchpoint_contact_time',
   'idx_touchpoint_session',
   'idx_touchpoint_source_time',
   'idx_user_positions_org',
   'idx_workspace_bl_org',
   'idx_workspace_market_org',
   'idx_workspace_team_org',
   'uq_attribution_primary',
   'uq_contact_identity_primary',
   'uq_roles_role_code',
   'uq_team_primary_business_line',
   'uq_team_primary_market',
   'uq_touchpoint_external_event',
   'uq_user_primary_position',
   'uq_user_primary_team',
   'uq_team_primary_workspace',
   'uq_workspace_primary_bl',
   'uq_workspace_primary_market','uq_message_external','uq_message_client_event',
   'uq_workspace_primary_team',
  }
  indexes={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'")}
  missing_indexes=sorted(required_indexes-indexes)
  if missing_indexes:raise RuntimeError('SCHEMA_213_INVALID: missing indexes: '+','.join(missing_indexes))
  required_triggers={
   'trg_business_line_cycle_insert',
   'trg_business_line_cycle_update',
   'trg_department_cycle_insert',
   'trg_department_cycle_update',
   'trg_market_cycle_insert',
   'trg_market_cycle_update',
   'trg_org_membership_scope_insert',
   'trg_org_membership_scope_update',
   'trg_position_department_scope_insert',
   'trg_position_department_scope_update',
   'trg_role_binding_guard_insert',
   'trg_role_binding_guard_update',
   'trg_role_status_insert',
   'trg_role_status_update',
   'trg_team_bl_scope_insert',
   'trg_team_bl_scope_update',
   'trg_team_department_scope_insert',
   'trg_team_department_scope_update',
   'trg_team_market_scope_insert',
   'trg_team_market_scope_update',
   'trg_team_membership_scope_insert',
   'trg_team_membership_scope_update',
   'trg_team_primary_workspace_insert',
   'trg_team_primary_workspace_update',
   'trg_user_position_scope_insert',
   'trg_user_position_scope_update',
  }
  triggers={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
  missing_triggers=sorted(required_triggers-triggers)
  if missing_triggers:raise RuntimeError('SCHEMA_213_INVALID: missing triggers: '+','.join(missing_triggers))
  qc=c.execute('PRAGMA quick_check').fetchone()[0]
  if qc!='ok':raise RuntimeError('SCHEMA_213_INVALID: quick_check: '+str(qc))
  fk=list(c.execute('PRAGMA foreign_key_check'))
  if fk:raise RuntimeError('SCHEMA_213_INVALID: foreign_key_check: '+str(len(fk)))
  validate_registered_migration_checksums(path)
  return True
 finally:c.close()

def validate_schema214_readonly(path):
 validate_schema213_readonly(path)
 c=_connect_strict_readonly(path)
 try:
  required={'account_binding_slots','account_identity_discoveries'}
  actual={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  missing=sorted(required-actual)
  if missing:raise RuntimeError('SCHEMA_214_INVALID: missing tables: '+','.join(missing))
  version=c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
  if not version or str(version[0])!='214':raise RuntimeError('SCHEMA_214_INVALID: version')
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('SCHEMA_214_INVALID: quick_check')
  if list(c.execute('PRAGMA foreign_key_check')):raise RuntimeError('SCHEMA_214_INVALID: foreign_key_check')
 finally:c.close()

def ensure_v215(c):
 # Schema 217 is a fresh-install configuration-integrity baseline; no 214 upgrade is offered.
 c.execute("UPDATE custom_field_definitions SET field_type='single_select' WHERE field_type='select'")
 c.execute("UPDATE contacts SET display_name='' WHERE manual_name='' AND lower(trim(display_name)) IN ('个人主页详情','联系人信息','联系方式','个人资料','群组信息','contact info','profile details','group info','click to view contact info')")

# V208.2.0 更新说明（2026-09-25）：Schema 219 — 客户运营工作台(Phase 3)
#   客户运营工作台驱动增量：
#   - contacts 增加 stage / owner_user_id / next_follow_up_at / last_touch_at 4 列
#   - 3 个复合索引用于 scope 收敛 + 工作清单分桶
#   - 新增 user_dashboard_pins 表(工作台区块个人偏好)
#   所有迁移幂等,可重入,回填全部基于已有 interactions + audit_logs.
V216_WORKBENCH_MIGRATION_ID = 'V216_workbench_contacts'
V216_WORKBENCH_SIGNATURE = 'contacts.stage,contacts.owner_user_id,contacts.next_follow_up_at,contacts.last_touch_at,user_dashboard_pins'

def _v216_has_column(c, table, column):
 return column in [r[1] for r in c.execute(f"PRAGMA table_info({table})")]

def _v216_index_exists(c, name):
 row = c.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)).fetchone()
 return bool(row)

def ensure_v216(c):
 """Schema 219 — 客户运营工作台(Phase 3)数据层增量。幂等可重入。"""
 checksum = hashlib.sha256(V216_WORKBENCH_SIGNATURE.encode()).hexdigest()
 old = c.execute("SELECT checksum FROM schema_migrations WHERE migration_id=?", (V216_WORKBENCH_MIGRATION_ID,)).fetchone()
 if old and old[0] != checksum:
  raise RuntimeError('MIGRATION_CHECKSUM_MISMATCH: ' + V216_WORKBENCH_MIGRATION_ID)

 changes = []

 # 1) contacts.stage —— 仅保留结构兼容；漏斗以单选 status 标签为唯一依据
 if not _v216_has_column(c, 'contacts', 'stage'):
  c.execute("ALTER TABLE contacts ADD COLUMN stage TEXT NOT NULL DEFAULT ''")
  changes.append('add_contacts_stage')
  changes.append('stage_initialized_empty')

 # 2) contacts.owner_user_id —— scope 收敛关键,避免每次 JOIN team_memberships
 if not _v216_has_column(c, 'contacts', 'owner_user_id'):
  c.execute("ALTER TABLE contacts ADD COLUMN owner_user_id TEXT")
  changes.append('add_contacts_owner_user_id')
  # 回填:取最近一次 update_workspace/contacts 相关的 audit_logs actor
  try:
   c.execute("""
    UPDATE contacts
       SET owner_user_id = COALESCE((
        SELECT al.actor_id
          FROM audit_logs al
         WHERE al.entity_type = 'contacts'
           AND al.entity_id = contacts.contact_id
           AND al.operation IN ('contact.create','contact.update','admin_contact.update')
         ORDER BY al.created_at DESC
         LIMIT 1
        ), (
        SELECT user_id FROM users WHERE organization_id = contacts.organization_id ORDER BY created_at LIMIT 1
        ))
    WHERE deleted_at IS NULL AND owner_user_id IS NULL
   """)
   backfilled = c.total_changes
  except Exception:
   backfilled = 0
  changes.append(f'owner_backfilled_rows={backfilled}')

 # 3) contacts.next_follow_up_at —— MyQueue 分桶驱动
 if not _v216_has_column(c, 'contacts', 'next_follow_up_at'):
  c.execute("ALTER TABLE contacts ADD COLUMN next_follow_up_at INTEGER")
  changes.append('add_contacts_next_follow_up_at')
  # 回填:取最近一次 conversation 触发或 7 天兜底
  try:
   c.execute("""
    UPDATE contacts
       SET next_follow_up_at = COALESCE((
        SELECT MAX(c2.started_at) FROM conversations c2 WHERE c2.contact_id = contacts.contact_id
        ), created_at + 7*86400*1000)
    WHERE deleted_at IS NULL AND next_follow_up_at IS NULL
   """)
   backfilled = c.total_changes
  except Exception:
   backfilled = 0
  changes.append(f'next_due_backfilled_rows={backfilled}')

 # 4) contacts.last_touch_at —— 沟通脉搏
 if not _v216_has_column(c, 'contacts', 'last_touch_at'):
  c.execute("ALTER TABLE contacts ADD COLUMN last_touch_at INTEGER")
  changes.append('add_contacts_last_touch_at')
  try:
   c.execute("""
    UPDATE contacts
       SET last_touch_at = COALESCE((
        SELECT MAX(c2.started_at) FROM conversations c2 WHERE c2.contact_id = contacts.contact_id
        ), created_at)
    WHERE deleted_at IS NULL AND last_touch_at IS NULL
   """)
   backfilled = c.total_changes
  except Exception:
   backfilled = 0
  changes.append(f'last_touch_backfilled_rows={backfilled}')

 # 5) 索引 (幂等)
 if not _v216_index_exists(c, 'idx_contacts_owner_scope'):
  c.execute("CREATE INDEX IF NOT EXISTS idx_contacts_owner_scope ON contacts(organization_id, owner_user_id, deleted_at)")
  changes.append('add_idx_contacts_owner_scope')
 if not _v216_index_exists(c, 'idx_contacts_next_due'):
  c.execute("CREATE INDEX IF NOT EXISTS idx_contacts_next_due ON contacts(organization_id, next_follow_up_at)")
  changes.append('add_idx_contacts_next_due')
 if not _v216_index_exists(c, 'idx_contacts_stage_due'):
  c.execute("CREATE INDEX IF NOT EXISTS idx_contacts_stage_due ON contacts(organization_id, stage, next_follow_up_at)")
  changes.append('add_idx_contacts_stage_due')
 if not _v216_index_exists(c, 'idx_contacts_last_touch'):
  c.execute("CREATE INDEX IF NOT EXISTS idx_contacts_last_touch ON contacts(organization_id, last_touch_at DESC)")
  changes.append('add_idx_contacts_last_touch')

 # 6) user_dashboard_pins —— 用户对工作台区块的置顶/折叠
 c.execute("""
  CREATE TABLE IF NOT EXISTS user_dashboard_pins(
   user_id TEXT NOT NULL,
   pin_key TEXT NOT NULL,
   pinned_at INTEGER NOT NULL,
   PRIMARY KEY (user_id, pin_key)
  )
 """)
 changes.append('ensure_user_dashboard_pins_table')

 if not old:
  t = now_ms()
  c.execute("""
   INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json)
   VALUES(?,?,?,?,?,?)
  """, (
   V216_WORKBENCH_MIGRATION_ID,
   '客户运营工作台(Phase 3) — contacts 阶段/owner/due/last_touch + user_dashboard_pins',
   checksum, t, 'system',
   dumps({'status': 'success', 'changes': changes})
  ))

 return changes

# V208.2.5 / Schema 217 — 六状态客户漏斗基线
V217_STATUS_MIGRATION_ID = 'V217_six_customer_statuses'
V217_STATUS_SPECS = (
 ('观察','#64748b'),('开户','#2563eb'),('入金','#16a34a'),
 ('加金','#0891b2'),('完成','#7c3aed'),('放弃','#dc2626'),
)
V217_STATUS_SIGNATURE = 'status-single-v3:' + '|'.join(name+':'+color for name,color in V217_STATUS_SPECS)

def ensure_v217(c):
 """补齐六个基础客户状态；保留自定义状态和已有联系人关联。"""
 checksum=hashlib.sha256(V217_STATUS_SIGNATURE.encode()).hexdigest()
 for trigger_name in ('trg_contact_tags_single_status_insert','trg_contact_tags_single_status_update','trg_tags_single_status_kind_update'):
  c.execute("DROP TRIGGER IF EXISTS "+trigger_name)
 c.execute("""CREATE TRIGGER trg_contact_tags_single_status_insert BEFORE INSERT ON contact_tags
 WHEN (SELECT tag_kind FROM tags WHERE tag_id=NEW.tag_id)='status'
  AND EXISTS(SELECT 1 FROM contact_tags ct JOIN tags t ON t.tag_id=ct.tag_id WHERE ct.contact_id=NEW.contact_id AND t.tag_kind='status' AND ct.tag_id<>NEW.tag_id)
 BEGIN SELECT RAISE(ABORT,'MULTIPLE_STATUS_TAGS'); END""")
 c.execute("""CREATE TRIGGER trg_contact_tags_single_status_update BEFORE UPDATE OF contact_id,tag_id ON contact_tags
 WHEN (SELECT tag_kind FROM tags WHERE tag_id=NEW.tag_id)='status'
  AND EXISTS(SELECT 1 FROM contact_tags ct JOIN tags t ON t.tag_id=ct.tag_id WHERE ct.contact_id=NEW.contact_id AND t.tag_kind='status' AND NOT (ct.contact_id=OLD.contact_id AND ct.tag_id=OLD.tag_id))
 BEGIN SELECT RAISE(ABORT,'MULTIPLE_STATUS_TAGS'); END""")
 c.execute("""CREATE TRIGGER trg_tags_single_status_kind_update BEFORE UPDATE OF tag_kind ON tags
 WHEN NEW.tag_kind='status' AND OLD.tag_kind<>'status'
  AND EXISTS(SELECT 1 FROM contact_tags changed JOIN contact_tags existing ON existing.contact_id=changed.contact_id JOIN tags current ON current.tag_id=existing.tag_id WHERE changed.tag_id=OLD.tag_id AND current.tag_kind='status' AND existing.tag_id<>OLD.tag_id)
 BEGIN SELECT RAISE(ABORT,'MULTIPLE_STATUS_TAGS'); END""")
 old=c.execute("SELECT checksum FROM schema_migrations WHERE migration_id=?",(V217_STATUS_MIGRATION_ID,)).fetchone()
 if old and old[0]!=checksum:raise RuntimeError('MIGRATION_CHECKSUM_MISMATCH: '+V217_STATUS_MIGRATION_ID)
 changes=[];t=now_ms()
 workspaces=[r[0] for r in c.execute("SELECT workspace_id FROM workspaces ORDER BY workspace_id")]
 for workspace_id in workspaces:
  for order,(name,color) in enumerate(V217_STATUS_SPECS,1):
   row=c.execute("SELECT tag_id,tag_kind FROM tags WHERE workspace_id=? AND name=?",(workspace_id,name)).fetchone()
   if row and row[1]!='status':
    raise RuntimeError('V217_STATUS_NAME_CONFLICT: workspace='+workspace_id+', name='+name+', kind='+str(row[1]))
   if row:
    c.execute("UPDATE tags SET color=?,category='客户状态',sort_order=?,enabled=1,updated_at=? WHERE tag_id=?",(color,order,t,row[0]))
    changes.append('normalize:'+workspace_id+':'+name)
   else:
    tag_id='tag_status_'+hashlib.sha256((workspace_id+'\0'+name).encode()).hexdigest()[:24]
    c.execute("INSERT INTO tags(tag_id,workspace_id,name,color,category,tag_kind,sort_order,enabled,created_at,updated_at) VALUES(?,?,?,?,?,'status',?,1,?,?)",(tag_id,workspace_id,name,color,'客户状态',order,t,t))
    changes.append('add:'+workspace_id+':'+name)
 if not old:
  c.execute("INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES(?,?,?,?,?,?)",(V217_STATUS_MIGRATION_ID,'六状态客户漏斗基线',checksum,t,'system',dumps({'status':'success','changes':changes})))
 return changes

def validate_schema215_readonly(path):
 # Schema 217 inherits the 214 object set, but validates its own version below.
 validate_schema213_readonly(path)
 c=_connect_strict_readonly(path)
 try:
  version=c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
  if not version or str(version[0])!='215':raise RuntimeError('SCHEMA_215_INVALID: version')
  if c.execute('PRAGMA user_version').fetchone()[0]!=215:raise RuntimeError('SCHEMA_215_INVALID: user_version')
  required={'account_binding_slots','account_identity_discoveries'}
  actual={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  if required-actual:raise RuntimeError('SCHEMA_215_INVALID: missing tables: '+','.join(sorted(required-actual)))
  workspaces=[r[0] for r in c.execute('SELECT workspace_id FROM workspaces ORDER BY workspace_id')]
  if workspaces!=['ws-global']:raise RuntimeError('SCHEMA_215_INVALID: canonical workspace required')
  status_presets={r[0] for r in c.execute("SELECT name FROM tags WHERE workspace_id='ws-global' AND tag_kind='status' AND enabled=1")}
  if not {'加金','放弃'}.issubset(status_presets):raise RuntimeError('SCHEMA_215_INVALID: status presets')
  if c.execute("SELECT COUNT(*) FROM tags WHERE workspace_id='ws-global' AND tag_kind='portrait'").fetchone()[0]<7:raise RuntimeError('SCHEMA_215_INVALID: portrait presets')
  if c.execute("SELECT COUNT(*) FROM custom_field_definitions WHERE field_type='select'").fetchone()[0]:raise RuntimeError('SCHEMA_215_INVALID: legacy select type')
  stage=c.execute("SELECT field_type,options_json FROM custom_field_definitions WHERE workspace_id='ws-global' AND field_key='customer_stage'").fetchone()
  if not stage or stage[0]!='multi_select' or loads(stage[1])!=['一切','二切','三切']:raise RuntimeError('SCHEMA_215_INVALID: customer stage baseline')
  if c.execute("SELECT COUNT(*) FROM (SELECT ct.contact_id FROM contact_tags ct JOIN tags t ON t.tag_id=ct.tag_id WHERE t.tag_kind='status' GROUP BY ct.contact_id HAVING COUNT(*)>1)").fetchone()[0]:raise RuntimeError('SCHEMA_215_INVALID: multiple status tags')
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('SCHEMA_215_INVALID: quick_check')
  if list(c.execute('PRAGMA foreign_key_check')):raise RuntimeError('SCHEMA_215_INVALID: foreign_key_check')
 finally:c.close()

# Phase 3: 客户运营工作台(Schema 219)
def validate_schema216_readonly(path):
 """Schema 219 校验:继承 Schema 217 全部约束(但不复用 validate_schema215_readonly 的版本断言),并增加 Phase 3 数据层校验。"""
 c=_connect_strict_readonly(path)
 try:
  version=c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
  if not version or str(version[0])!='216':raise RuntimeError('SCHEMA_216_INVALID: version')
  if c.execute('PRAGMA user_version').fetchone()[0]!=216:raise RuntimeError('SCHEMA_216_INVALID: user_version')
  # Schema 217 强约束子集(逐项内联,避免与 SCHEMA_VERSION=216 冲突)
  required={'account_binding_slots','account_identity_discoveries'}
  actual={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  if required-actual:raise RuntimeError('SCHEMA_216_INVALID: missing tables: '+','.join(sorted(required-actual)))
  workspaces=[r[0] for r in c.execute('SELECT workspace_id FROM workspaces ORDER BY workspace_id')]
  if workspaces!=['ws-global']:raise RuntimeError('SCHEMA_216_INVALID: canonical workspace required')
  status_presets={r[0] for r in c.execute("SELECT name FROM tags WHERE workspace_id='ws-global' AND tag_kind='status' AND enabled=1")}
  if not {'加金','放弃'}.issubset(status_presets):raise RuntimeError('SCHEMA_216_INVALID: status presets')
  if c.execute("SELECT COUNT(*) FROM tags WHERE workspace_id='ws-global' AND tag_kind='portrait'").fetchone()[0]<7:raise RuntimeError('SCHEMA_216_INVALID: portrait presets')
  if c.execute("SELECT COUNT(*) FROM custom_field_definitions WHERE field_type='select'").fetchone()[0]:raise RuntimeError('SCHEMA_216_INVALID: legacy select type')
  stage=c.execute("SELECT field_type,options_json FROM custom_field_definitions WHERE workspace_id='ws-global' AND field_key='customer_stage'").fetchone()
  if not stage or stage[0]!='multi_select' or loads(stage[1])!=['一切','二切','三切']:raise RuntimeError('SCHEMA_216_INVALID: customer stage baseline')
  if c.execute("SELECT COUNT(*) FROM (SELECT ct.contact_id FROM contact_tags ct JOIN tags t ON t.tag_id=ct.tag_id WHERE t.tag_kind='status' GROUP BY ct.contact_id HAVING COUNT(*)>1)").fetchone()[0]:raise RuntimeError('SCHEMA_216_INVALID: multiple status tags')
  # Schema 219 增量
  contacts_cols={r[1] for r in c.execute("PRAGMA table_info(contacts)")}
  required_cols={'stage','owner_user_id','next_follow_up_at','last_touch_at'}
  missing=required_cols-contacts_cols
  if missing:raise RuntimeError('SCHEMA_216_INVALID: contacts missing columns: '+','.join(sorted(missing)))
  if 'user_dashboard_pins' not in actual:raise RuntimeError("SCHEMA_216_INVALID: missing table 'user_dashboard_pins'")
  required_idx={'idx_contacts_owner_scope','idx_contacts_next_due','idx_contacts_stage_due','idx_contacts_last_touch'}
  actual_idx={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
  if required_idx-actual_idx:raise RuntimeError('SCHEMA_216_INVALID: missing indexes: '+','.join(sorted(required_idx-actual_idx)))
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('SCHEMA_216_INVALID: quick_check')
  if list(c.execute('PRAGMA foreign_key_check')):raise RuntimeError('SCHEMA_216_INVALID: foreign_key_check')
 finally:c.close()

def validate_schema217_readonly(path):
 """Schema 217：Schema 219 结构 + 六状态基线 + 状态单选完整性。"""
 c=_connect_strict_readonly(path)
 try:
  version=c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
  if not version or str(version[0])!='217':raise RuntimeError('SCHEMA_217_INVALID: version')
  if c.execute('PRAGMA user_version').fetchone()[0]!=217:raise RuntimeError('SCHEMA_217_INVALID: user_version')
  actual={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  required={'account_binding_slots','account_identity_discoveries','user_dashboard_pins'}
  if required-actual:raise RuntimeError('SCHEMA_217_INVALID: missing tables: '+','.join(sorted(required-actual)))
  cols={r[1] for r in c.execute('PRAGMA table_info(contacts)')}
  missing={'stage','owner_user_id','next_follow_up_at','last_touch_at'}-cols
  if missing:raise RuntimeError('SCHEMA_217_INVALID: contacts missing columns: '+','.join(sorted(missing)))
  idx={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
  required_idx={'idx_contacts_owner_scope','idx_contacts_next_due','idx_contacts_stage_due','idx_contacts_last_touch'}
  if required_idx-idx:raise RuntimeError('SCHEMA_217_INVALID: missing indexes: '+','.join(sorted(required_idx-idx)))
  required_status_triggers={'trg_contact_tags_single_status_insert','trg_contact_tags_single_status_update','trg_tags_single_status_kind_update'}
  status_triggers={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
  if required_status_triggers-status_triggers:raise RuntimeError('SCHEMA_217_INVALID: status singleton triggers: '+','.join(sorted(required_status_triggers-status_triggers)))
  required_names={x[0] for x in V217_STATUS_SPECS}
  for workspace_id, in c.execute('SELECT workspace_id FROM workspaces'):
   enabled={r[0] for r in c.execute("SELECT name FROM tags WHERE workspace_id=? AND tag_kind='status' AND enabled=1",(workspace_id,))}
   if not required_names.issubset(enabled):raise RuntimeError('SCHEMA_217_INVALID: status presets: '+workspace_id)
   stage=c.execute("SELECT field_type,options_json FROM custom_field_definitions WHERE workspace_id=? AND field_key='customer_stage'",(workspace_id,)).fetchone()
   if not stage or stage[0]!='multi_select' or loads(stage[1])!=['一切','二切','三切']:raise RuntimeError('SCHEMA_217_INVALID: customer stage baseline: '+workspace_id)
  if c.execute("SELECT COUNT(*) FROM (SELECT ct.contact_id FROM contact_tags ct JOIN tags t ON t.tag_id=ct.tag_id WHERE t.tag_kind='status' GROUP BY ct.contact_id HAVING COUNT(*)>1)").fetchone()[0]:raise RuntimeError('SCHEMA_217_INVALID: multiple status tags')
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('SCHEMA_217_INVALID: quick_check')
  if list(c.execute('PRAGMA foreign_key_check')):raise RuntimeError('SCHEMA_217_INVALID: foreign_key_check')
  validate_registered_migration_checksums(path)
 finally:c.close()

# V208.3.0 / Schema 218：全新安装业务场景、建档策略与三阶段基线。
def ensure_v218(c):
 _add(c,'channel_accounts','business_scene',"TEXT NOT NULL DEFAULT 'social_acquisition' CHECK(business_scene IN ('social_acquisition','lead_intake','conversion','hybrid','internal'))")
 _add(c,'channel_accounts','contact_entry_policy',"TEXT NOT NULL DEFAULT 'manual_on_record' CHECK(contact_entry_policy IN ('manual_on_record','first_inbound_message','existing_contact_first','disabled'))")
 execute_sql_script(c,"""
 CREATE TABLE IF NOT EXISTS interaction_idempotency(
  idempotency_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,team_id TEXT NOT NULL,user_id TEXT NOT NULL,
  operation TEXT NOT NULL,idempotency_key TEXT NOT NULL,request_hash TEXT NOT NULL,entity_type TEXT NOT NULL DEFAULT '',entity_id TEXT,
  response_json TEXT NOT NULL DEFAULT '{}',created_at INTEGER NOT NULL,expires_at INTEGER,
  FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
  FOREIGN KEY(team_id) REFERENCES teams(team_id),FOREIGN KEY(user_id) REFERENCES users(user_id),
  UNIQUE(organization_id,workspace_id,team_id,user_id,operation,idempotency_key));
 CREATE INDEX IF NOT EXISTS idx_interaction_idempotency_expiry ON interaction_idempotency(expires_at);

 DROP TRIGGER IF EXISTS trg_channel_account_policy_insert;
 DROP TRIGGER IF EXISTS trg_channel_account_policy_update;
 DROP TRIGGER IF EXISTS trg_device_account_scope_insert;
 CREATE TRIGGER trg_channel_account_policy_insert BEFORE INSERT ON channel_accounts BEGIN
  SELECT CASE WHEN NOT ((NEW.business_scene='social_acquisition' AND NEW.contact_entry_policy='manual_on_record' AND NEW.business_purpose='acquisition' AND NEW.collection_enabled=1) OR (NEW.business_scene='lead_intake' AND NEW.contact_entry_policy='first_inbound_message' AND NEW.business_purpose='conversion' AND NEW.collection_enabled=1) OR (NEW.business_scene='conversion' AND NEW.contact_entry_policy='existing_contact_first' AND NEW.business_purpose='conversion' AND NEW.collection_enabled=1) OR (NEW.business_scene='hybrid' AND NEW.contact_entry_policy IN ('manual_on_record','first_inbound_message','existing_contact_first') AND NEW.business_purpose='hybrid' AND NEW.collection_enabled=1) OR (NEW.business_scene='internal' AND NEW.contact_entry_policy='disabled' AND NEW.collection_enabled=0)) THEN RAISE(ABORT,'INVALID_BUSINESS_SCENE_POLICY') END;
 END;
 CREATE TRIGGER trg_channel_account_policy_update BEFORE UPDATE OF business_scene,contact_entry_policy,business_purpose,collection_enabled ON channel_accounts BEGIN
  SELECT CASE WHEN NOT ((NEW.business_scene='social_acquisition' AND NEW.contact_entry_policy='manual_on_record' AND NEW.business_purpose='acquisition' AND NEW.collection_enabled=1) OR (NEW.business_scene='lead_intake' AND NEW.contact_entry_policy='first_inbound_message' AND NEW.business_purpose='conversion' AND NEW.collection_enabled=1) OR (NEW.business_scene='conversion' AND NEW.contact_entry_policy='existing_contact_first' AND NEW.business_purpose='conversion' AND NEW.collection_enabled=1) OR (NEW.business_scene='hybrid' AND NEW.contact_entry_policy IN ('manual_on_record','first_inbound_message','existing_contact_first') AND NEW.business_purpose='hybrid' AND NEW.collection_enabled=1) OR (NEW.business_scene='internal' AND NEW.contact_entry_policy='disabled' AND NEW.collection_enabled=0)) THEN RAISE(ABORT,'INVALID_BUSINESS_SCENE_POLICY') END;
 END;
 CREATE TRIGGER trg_device_account_scope_insert BEFORE INSERT ON device_channel_account_bindings BEGIN
  SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM devices d JOIN teams t ON t.team_id=NEW.team_id JOIN channel_accounts a ON a.channel_account_id=NEW.channel_account_id JOIN team_channel_accounts x ON x.team_id=NEW.team_id AND x.channel_account_id=NEW.channel_account_id JOIN users u ON u.user_id=NEW.user_id WHERE d.device_id=NEW.device_id AND d.organization_id=NEW.organization_id AND d.workspace_id=NEW.workspace_id AND d.team_id=NEW.team_id AND t.organization_id=NEW.organization_id AND t.workspace_id=NEW.workspace_id AND a.organization_id=NEW.organization_id AND a.platform_id=NEW.platform_id AND a.status='active' AND u.organization_id=NEW.organization_id AND u.status='active') THEN RAISE(ABORT,'DEVICE_ACCOUNT_SCOPE_MISMATCH') END; END;
 CREATE TRIGGER IF NOT EXISTS trg_contacts_owner_required_insert BEFORE INSERT ON contacts WHEN NEW.owner_user_id IS NULL OR trim(NEW.owner_user_id)='' BEGIN SELECT RAISE(ABORT,'CONTACT_OWNER_REQUIRED'); END;
 CREATE TRIGGER IF NOT EXISTS trg_contacts_owner_required_update BEFORE UPDATE OF owner_user_id ON contacts WHEN NEW.owner_user_id IS NULL OR trim(NEW.owner_user_id)='' BEGIN SELECT RAISE(ABORT,'CONTACT_OWNER_REQUIRED'); END;
 """)
 t=now_ms()
 c.execute("DELETE FROM custom_field_definitions WHERE field_key='customer_stage'")
 specs=(
  ('communication_stage','沟通','stage_communication',100,['投资','看盘','财经']),
  ('intention_stage','意向','stage_intention',110,['盈利','交易','量化']),
  ('conversion_stage','转化','stage_conversion',120,['体验','赠金','联合']),
 )
 for key,label,role,order,options in specs:
  c.execute("INSERT OR REPLACE INTO custom_field_definitions(workspace_id,field_key,label,field_type,sort_order,enabled,created_at,updated_at,field_role,display_zone,is_quick_edit,options_json,placeholder) SELECT workspace_id,?,?, 'multi_select',?,1,?,?,?,'workbench',1,?,'' FROM workspaces",(key,label,order,t,t,role,dumps(options)))
 signature='schema218-three-multi-stage-stamps:'+PRODUCT_VERSION
 checksum=hashlib.sha256(signature.encode()).hexdigest()
 c.execute("INSERT OR REPLACE INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES('V218_p0_business_correctness','P0 业务正确性全新安装基线',?,?,?,?)",(checksum,t,'system',dumps({'status':'success','freshInstallOnly':True})))

# V208.4.7 / Schema 219：社交获客来源解析全新安装基线；禁止旧库迁移。
V219_SOCIAL_SOURCE_TYPES=(
 ('st_social_outbound','social_outbound','业务员主动开发','业务员主动联系客户',310),
 ('st_social_inbound','social_inbound','客户主动添加','客户主动建立联系',320),
 ('st_social_community','social_community','社群/群组认识','在社群或群组中认识',330),
 ('st_social_referral','social_referral','好友推荐/转介绍','经好友推荐或转介绍',340),
 ('st_social_content','social_content','广告或内容引流','经广告或内容建立联系',350),
 ('st_social_other','social_other','线下或其他','线下或其他可说明来源',360),
 ('st_social_pending','social_pending','待确认','来源尚未确认',370),
)

def ensure_v219(c):
 """仅在全新空库创建事务中调用；不是数据库迁移入口。"""
 _add(c,'channel_accounts','default_market_id','TEXT REFERENCES markets(market_id)')
 _add(c,'channel_accounts','suggested_source_type_id','TEXT REFERENCES source_type_definitions(source_type_id)')
 for col,decl in (
  ('market_id','TEXT REFERENCES markets(market_id)'),('source_fingerprint','TEXT'),('entry_url','TEXT'),('referrer_url','TEXT'),
  ('platform_object_type','TEXT'),('platform_object_id','TEXT'),('platform_actor_id','TEXT'),('platform_actor_name','TEXT'),
  ('campaign_name','TEXT'),('ad_set_name','TEXT'),('ad_name','TEXT'),('utm_source','TEXT'),('utm_medium','TEXT'),
  ('utm_campaign','TEXT'),('utm_content','TEXT'),('utm_term','TEXT'),('resolver_version',"TEXT NOT NULL DEFAULT 'v219.1'"),
  ('resolution_method',"TEXT NOT NULL DEFAULT 'manual'"),('resolution_confidence','REAL NOT NULL DEFAULT 0')):
  _add(c,'sources',col,decl)
 _add(c,'source_touchpoints','event_key','TEXT')
 execute_sql_script(c,"""
 CREATE TABLE IF NOT EXISTS user_contact_center_preferences(
  organization_id TEXT NOT NULL,user_id TEXT NOT NULL,preferences_json TEXT NOT NULL DEFAULT '{}',version INTEGER NOT NULL DEFAULT 1,updated_at INTEGER NOT NULL,
  PRIMARY KEY(organization_id,user_id),FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(user_id) REFERENCES users(user_id));
 CREATE INDEX IF NOT EXISTS idx_channel_accounts_default_market ON channel_accounts(default_market_id);
 CREATE INDEX IF NOT EXISTS idx_channel_accounts_suggested_source ON channel_accounts(suggested_source_type_id);
 CREATE UNIQUE INDEX IF NOT EXISTS uq_sources_fingerprint ON sources(organization_id,workspace_id,source_fingerprint) WHERE source_fingerprint IS NOT NULL AND source_fingerprint<>'';
 CREATE INDEX IF NOT EXISTS idx_sources_market ON sources(organization_id,market_id,status);
 CREATE UNIQUE INDEX IF NOT EXISTS uq_touchpoint_event_key ON source_touchpoints(organization_id,workspace_id,event_key) WHERE event_key IS NOT NULL AND event_key<>'';
 CREATE UNIQUE INDEX IF NOT EXISTS uq_touchpoint_external_event ON source_touchpoints(organization_id,workspace_id,external_event_id) WHERE external_event_id IS NOT NULL AND external_event_id<>'';
 CREATE TABLE IF NOT EXISTS source_resolution_logs(
  resolution_log_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,channel_account_id TEXT,
  market_id TEXT,source_type_id TEXT,source_id TEXT,input_digest TEXT NOT NULL,resolver_version TEXT NOT NULL,
  resolution_method TEXT NOT NULL,confidence REAL NOT NULL DEFAULT 0,status TEXT NOT NULL,error_code TEXT,
  input_summary_json TEXT NOT NULL DEFAULT '{}',created_at INTEGER NOT NULL,
  FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
  FOREIGN KEY(channel_account_id) REFERENCES channel_accounts(channel_account_id),FOREIGN KEY(market_id) REFERENCES markets(market_id),
  FOREIGN KEY(source_type_id) REFERENCES source_type_definitions(source_type_id),FOREIGN KEY(source_id) REFERENCES sources(source_id));
 CREATE INDEX IF NOT EXISTS idx_source_resolution_scope ON source_resolution_logs(organization_id,workspace_id,created_at);
 CREATE TABLE IF NOT EXISTS contact_conversions(
  conversion_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,team_id TEXT,contact_id TEXT NOT NULL,
  owner_user_id TEXT,source_id TEXT,attribution_id TEXT,conversion_status TEXT NOT NULL DEFAULT 'won',amount_minor INTEGER,
  currency_code TEXT NOT NULL DEFAULT '',converted_at INTEGER NOT NULL,external_conversion_key TEXT,metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
  FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
  FOREIGN KEY(team_id) REFERENCES teams(team_id),FOREIGN KEY(contact_id) REFERENCES contacts(contact_id),FOREIGN KEY(owner_user_id) REFERENCES users(user_id),
  FOREIGN KEY(source_id) REFERENCES sources(source_id),FOREIGN KEY(attribution_id) REFERENCES contact_attributions(attribution_id));
 CREATE UNIQUE INDEX IF NOT EXISTS uq_conversion_external_key ON contact_conversions(organization_id,external_conversion_key) WHERE external_conversion_key IS NOT NULL AND external_conversion_key<>'';
 CREATE INDEX IF NOT EXISTS idx_conversion_contact_time ON contact_conversions(organization_id,contact_id,converted_at);
 """)
 t=now_ms()
 conversion_perms=(('conversion.read','读取转化','read','medium'),('conversion.manage','管理转化','manage','high'))
 for key,label,action,risk in conversion_perms:
  c.execute("INSERT OR IGNORE INTO permissions(permission_key,description,display_name,resource,action,scope_mask,risk_level) VALUES(?,?,?,?,?,63,?)",(key,label,label,'conversion',action,risk))
 for role in ('role_superadmin','role_orgadmin'):
  for key,*_ in conversion_perms:c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',(role,key))
 for role in ('role_teamlead','role_operator'):
  for key in ('conversion.read','conversion.manage'):c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',(role,key))
 for role in ('role_readonly','role_auditor'):c.execute("INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,'conversion.read')",(role,))
 for row in V219_SOCIAL_SOURCE_TYPES:
  c.execute("""INSERT INTO source_type_definitions(source_type_id,source_type_code,name,description,is_active,sort_order,created_at,updated_at)
   VALUES(?,?,?,?,1,?,?,?) ON CONFLICT(source_type_code) DO UPDATE SET name=excluded.name,description=excluded.description,
   is_active=1,sort_order=excluded.sort_order,updated_at=excluded.updated_at""",(*row,t,t))
 signature='schema219-fresh-social-acquisition-v1'
 c.execute("INSERT OR REPLACE INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES('V219_social_acquisition','Schema 219 社交获客全新安装基线',?,?,?,?)",(hashlib.sha256(signature.encode()).hexdigest(),t,'system',dumps({'status':'success','freshInstallOnly':True,'reuseMarkets':True,'reuseSourceTypes':True})))

V220_MIGRATION_ID='V220_meta_message_types'
V220_SIGNATURE='schema220-meta-message-types-v1'
V220_CONTENT_TYPES=('text','image','audio','video','file','sticker','share','post','reel','story','location','contact','call','system','unknown')
V220_MESSAGE_COLUMNS=('message_id','organization_id','workspace_id','team_id','conversation_id','channel_account_id','contact_id','external_message_id','client_event_id','direction','sender_type','sender_external_id','content_type','text_content','redacted_text','content_hash','pii_flags_json','occurred_at','collected_at','edited_at','deleted_at','content_deleted_at','content_deleted_by','content_delete_reason','status','metadata_json')
V220_MESSAGE_INDEX_SQL=(
 "CREATE UNIQUE INDEX uq_message_external ON conversation_messages(organization_id,channel_account_id,external_message_id) WHERE external_message_id IS NOT NULL AND external_message_id<>''",
 "CREATE UNIQUE INDEX uq_message_client_event ON conversation_messages(organization_id,channel_account_id,client_event_id) WHERE client_event_id IS NOT NULL AND client_event_id<>''",
 'CREATE INDEX idx_messages_conversation_time ON conversation_messages(conversation_id,occurred_at)',
 'CREATE INDEX idx_messages_contact_time ON conversation_messages(contact_id,occurred_at)',
 'CREATE INDEX idx_messages_team_time ON conversation_messages(team_id,occurred_at)',
)
V220_MESSAGE_TABLE_SQL="""CREATE TABLE conversation_messages(
 message_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,team_id TEXT NOT NULL,
 conversation_id TEXT NOT NULL,channel_account_id TEXT NOT NULL,contact_id TEXT NOT NULL,external_message_id TEXT,client_event_id TEXT,
 direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound','system')),sender_type TEXT NOT NULL DEFAULT 'unknown',sender_external_id TEXT,
 content_type TEXT NOT NULL CHECK(content_type IN ('text','image','audio','video','file','sticker','share','post','reel','story','location','contact','call','system','unknown')),
 text_content TEXT,redacted_text TEXT,content_hash TEXT NOT NULL,pii_flags_json TEXT NOT NULL DEFAULT '[]',occurred_at INTEGER,
 collected_at INTEGER NOT NULL,edited_at INTEGER,deleted_at INTEGER,content_deleted_at INTEGER,content_deleted_by TEXT,
 content_delete_reason TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','edited','deleted','content_deleted')),
 metadata_json TEXT NOT NULL DEFAULT '{}',
 FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
 FOREIGN KEY(team_id) REFERENCES teams(team_id),FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id),
 FOREIGN KEY(channel_account_id) REFERENCES channel_accounts(channel_account_id),FOREIGN KEY(contact_id) REFERENCES contacts(contact_id) ON DELETE RESTRICT,
 FOREIGN KEY(content_deleted_by) REFERENCES users(user_id))"""
V220_MESSAGE_TRIGGER_SQL="""CREATE TRIGGER trg_message_scope_insert BEFORE INSERT ON conversation_messages BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM conversations v WHERE v.conversation_id=NEW.conversation_id AND v.organization_id=NEW.organization_id AND v.workspace_id=NEW.workspace_id AND v.team_id=NEW.team_id AND v.channel_account_id=NEW.channel_account_id AND v.contact_id=NEW.contact_id) THEN RAISE(ABORT,'MESSAGE_SCOPE_MISMATCH') END; END"""

def _message_table_supports_v220(c):
 row=c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='conversation_messages'").fetchone()
 sql=(row[0] if row else '') or ''
 return all("'"+x+"'" in sql for x in ('share','post','reel','story'))

def _rebuild_messages_v220(c):
 if _message_table_supports_v220(c):return False
 old_cols=tuple(r[1] for r in c.execute('PRAGMA table_info(conversation_messages)'))
 if old_cols!=V220_MESSAGE_COLUMNS:raise RuntimeError('SCHEMA_220_MESSAGE_COLUMNS_MISMATCH')
 before=c.execute('SELECT COUNT(*) FROM conversation_messages').fetchone()[0]
 c.execute('DROP TRIGGER IF EXISTS trg_message_scope_insert')
 for name in ('uq_message_external','uq_message_client_event','idx_messages_conversation_time','idx_messages_contact_time','idx_messages_team_time'):
  c.execute('DROP INDEX IF EXISTS '+name)
 c.execute('ALTER TABLE conversation_messages RENAME TO conversation_messages_v219')
 c.execute(V220_MESSAGE_TABLE_SQL)
 cols=','.join(V220_MESSAGE_COLUMNS)
 c.execute('INSERT INTO conversation_messages('+cols+') SELECT '+cols+' FROM conversation_messages_v219')
 after=c.execute('SELECT COUNT(*) FROM conversation_messages').fetchone()[0]
 if before!=after:raise RuntimeError('SCHEMA_220_MESSAGE_COPY_COUNT_MISMATCH')
 c.execute('DROP TABLE conversation_messages_v219')
 for sql in V220_MESSAGE_INDEX_SQL:c.execute(sql)
 c.execute(V220_MESSAGE_TRIGGER_SQL)
 return True

def ensure_v220(c):
 rebuilt=_rebuild_messages_v220(c);t=now_ms();checksum=hashlib.sha256(V220_SIGNATURE.encode()).hexdigest()
 result={'status':'success','schema':220,'rebuilt':rebuilt,'contentTypes':list(V220_CONTENT_TYPES)}
 c.execute("INSERT OR REPLACE INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES(?,?,?,?,?,?)",(V220_MIGRATION_ID,'Schema 220 Meta 消息类型',checksum,t,'system',dumps(result)))
 return result

def validate_schema220_readonly(path):
 c=_connect_strict_readonly(path)
 try:
  version=c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
  if not version or str(version[0])!='220' or c.execute('PRAGMA user_version').fetchone()[0]!=220:raise RuntimeError('SCHEMA_220_INVALID: version')
  if not _message_table_supports_v220(c):raise RuntimeError('SCHEMA_220_INVALID: message content types')
  indexes={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
  required={'uq_message_external','uq_message_client_event','idx_messages_conversation_time','idx_messages_contact_time','idx_messages_team_time'}
  if required-indexes:raise RuntimeError('SCHEMA_220_INVALID: message indexes '+','.join(sorted(required-indexes)))
  trigger=c.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='trg_message_scope_insert'").fetchone()
  if not trigger or 'MESSAGE_SCOPE_MISMATCH' not in (trigger[0] or ''):raise RuntimeError('SCHEMA_220_INVALID: message trigger')
  conversation_trigger=c.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='trg_conversation_scope_insert'").fetchone()
  if not conversation_trigger or 'CONVERSATION_SCOPE_MISMATCH' not in (conversation_trigger[0] or ''):raise RuntimeError('SCHEMA_220_INVALID: conversation trigger')
  expected=hashlib.sha256(V220_SIGNATURE.encode()).hexdigest()
  migration=c.execute('SELECT checksum FROM schema_migrations WHERE migration_id=?',(V220_MIGRATION_ID,)).fetchone()
  if not migration or migration[0]!=expected:raise RuntimeError('SCHEMA_220_INVALID: migration checksum')
  platforms={r[0] for r in c.execute("SELECT platform_code FROM platforms WHERE platform_code IN ('instagram','messenger','facebook') AND status='active'")}
  if platforms!={'instagram','messenger','facebook'}:raise RuntimeError('SCHEMA_220_INVALID: Meta platforms')
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('SCHEMA_220_INVALID: quick_check')
  if list(c.execute('PRAGMA foreign_key_check')):raise RuntimeError('SCHEMA_220_INVALID: foreign_key_check')
  validate_registered_migration_checksums(path)
 finally:c.close()

def migrate_schema219_to_220(path):
 path=Path(path).resolve()
 version=_read_existing_schema_version(path)
 if version=='220':validate_schema220_readonly(path);return None
 if version!='219':raise RuntimeError('SCHEMA_220_MIGRATION_REQUIRES_219: detected '+repr(version))
 validate_schema219_readonly(path)
 backup=_exclusive_backup_path(path);_sqlite_backup(path,backup)
 c=sqlite3.connect(str(path),timeout=30,isolation_level=None);c.row_factory=sqlite3.Row
 try:
  c.execute('PRAGMA busy_timeout=30000');c.execute('PRAGMA foreign_keys=OFF');c.execute('BEGIN IMMEDIATE')
  ensure_v220(c)
  c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version','220')")
  c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('product_version',?)",(PRODUCT_VERSION,))
  c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('catalog_version',?)",(CATALOG_VERSION,))
  c.execute('PRAGMA user_version=220')
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('SCHEMA_220_MIGRATION_QUICK_CHECK_FAILED')
  c.execute('COMMIT');c.close();validate_schema220_readonly(path);return backup
 except Exception as exc:
  try:
   if c.in_transaction:c.execute('ROLLBACK')
   c.close()
  except Exception:pass
  _restore_sqlite_backup(backup,path);_write_failure_report(path,exc,backup);raise


V221_MIGRATION_ID='schema_221_contact_identity_access'
V221_SIGNATURE='schema221:contact-team-access:match-review:merge-history:workspace-identity:scope-triggers:v1'
V221_SCHEMA="""
CREATE TABLE IF NOT EXISTS contact_team_access(
 access_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,contact_id TEXT NOT NULL,team_id TEXT NOT NULL,
 access_level TEXT NOT NULL DEFAULT 'read' CHECK(access_level IN ('read','edit','manage')),
 source_type TEXT NOT NULL DEFAULT 'manual_link' CHECK(source_type IN ('primary','identity_reuse','manual_link','transfer','merge')),
 granted_by TEXT,granted_at INTEGER NOT NULL,revoked_by TEXT,revoked_at INTEGER,reason TEXT NOT NULL DEFAULT '',metadata_json TEXT NOT NULL DEFAULT '{}',
 FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
 FOREIGN KEY(contact_id) REFERENCES contacts(contact_id) ON DELETE CASCADE,FOREIGN KEY(team_id) REFERENCES teams(team_id),
 FOREIGN KEY(granted_by) REFERENCES users(user_id),FOREIGN KEY(revoked_by) REFERENCES users(user_id),
 UNIQUE(organization_id,workspace_id,contact_id,team_id));
CREATE INDEX IF NOT EXISTS idx_contact_team_access_team ON contact_team_access(organization_id,workspace_id,team_id,revoked_at,contact_id);
CREATE INDEX IF NOT EXISTS idx_contact_team_access_contact ON contact_team_access(contact_id,revoked_at,access_level);
CREATE TABLE IF NOT EXISTS contact_match_reviews(
 review_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,contact_id_a TEXT NOT NULL,contact_id_b TEXT NOT NULL,
 match_type TEXT NOT NULL,confidence TEXT NOT NULL CHECK(confidence IN ('weak','medium','high','exact')),evidence_json TEXT NOT NULL DEFAULT '{}',
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','confirmed','ignored','merged')),
 reviewed_by TEXT,reviewed_at INTEGER,reason TEXT NOT NULL DEFAULT '',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
 FOREIGN KEY(contact_id_a) REFERENCES contacts(contact_id),FOREIGN KEY(contact_id_b) REFERENCES contacts(contact_id),FOREIGN KEY(reviewed_by) REFERENCES users(user_id),
 CHECK(contact_id_a<contact_id_b),UNIQUE(organization_id,workspace_id,contact_id_a,contact_id_b,match_type));
CREATE INDEX IF NOT EXISTS idx_contact_match_pending ON contact_match_reviews(organization_id,workspace_id,status,confidence,updated_at);
CREATE TABLE IF NOT EXISTS contact_merge_history(
 merge_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,target_contact_id TEXT NOT NULL,source_contact_id TEXT NOT NULL,
 target_version_before INTEGER NOT NULL,source_version_before INTEGER NOT NULL,resolution_json TEXT NOT NULL DEFAULT '{}',impact_json TEXT NOT NULL DEFAULT '{}',
 before_json TEXT NOT NULL DEFAULT '{}',after_json TEXT NOT NULL DEFAULT '{}',status TEXT NOT NULL CHECK(status IN ('completed','failed')),
 merged_by TEXT NOT NULL,reason TEXT NOT NULL,created_at INTEGER NOT NULL,
 FOREIGN KEY(target_contact_id) REFERENCES contacts(contact_id),FOREIGN KEY(source_contact_id) REFERENCES contacts(contact_id),FOREIGN KEY(merged_by) REFERENCES users(user_id));
CREATE INDEX IF NOT EXISTS idx_contact_merge_target ON contact_merge_history(organization_id,workspace_id,target_contact_id,created_at);
CREATE TABLE IF NOT EXISTS contact_merge_requests(request_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,target_contact_id TEXT NOT NULL,source_contact_id TEXT NOT NULL,requested_by TEXT NOT NULL,requested_team_id TEXT,reason TEXT NOT NULL,evidence_json TEXT NOT NULL DEFAULT '{}',suggested_resolution_json TEXT NOT NULL DEFAULT '{}',status TEXT NOT NULL DEFAULT 'pending',target_version INTEGER NOT NULL,source_version INTEGER NOT NULL,reviewed_by TEXT,reviewed_at INTEGER,review_comment TEXT NOT NULL DEFAULT '',executed_merge_id TEXT,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_merge_requests_queue ON contact_merge_requests(organization_id,status,workspace_id,updated_at);
CREATE TABLE IF NOT EXISTS contact_merge_request_events(event_id TEXT PRIMARY KEY,request_id TEXT NOT NULL,event_type TEXT NOT NULL,actor_id TEXT NOT NULL,detail_json TEXT NOT NULL DEFAULT '{}',created_at INTEGER NOT NULL);
"""

def _rebuild_contact_identities_v221(c):
 sql=(c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='contact_identities'").fetchone() or [''])[0] or ''
 if 'UNIQUE(organization_id,workspace_id,platform_id,identity_type,canonical_value)' in sql:return False
 c.execute('DROP TRIGGER IF EXISTS trg_contact_identity_scope_insert')
 # Never rename the referenced parent table: SQLite would rewrite conversations FK
 # to the temporary name and leave a dangling reference after the table is dropped.
 c.execute("""CREATE TABLE contact_identities_v221_new(contact_identity_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,contact_id TEXT NOT NULL,platform_id TEXT,identity_type TEXT NOT NULL,identity_value TEXT NOT NULL,canonical_value TEXT NOT NULL,verification_status TEXT NOT NULL DEFAULT 'unverified',is_primary INTEGER NOT NULL DEFAULT 0,first_seen_at INTEGER NOT NULL,last_seen_at INTEGER NOT NULL,metadata_json TEXT NOT NULL DEFAULT '{}',FOREIGN KEY(contact_id) REFERENCES contacts(contact_id),FOREIGN KEY(platform_id) REFERENCES platforms(platform_id),UNIQUE(organization_id,workspace_id,platform_id,identity_type,canonical_value))""")
 c.execute('INSERT INTO contact_identities_v221_new SELECT * FROM contact_identities')
 c.execute('DROP TABLE contact_identities')
 c.execute('ALTER TABLE contact_identities_v221_new RENAME TO contact_identities')
 c.execute('CREATE INDEX IF NOT EXISTS idx_contact_identity_lookup ON contact_identities(organization_id,workspace_id,platform_id,canonical_value)')
 c.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_contact_primary_identity ON contact_identities(organization_id,workspace_id,contact_id) WHERE is_primary=1')
 return True

def _install_v221_scope_triggers(c):
 for name in ('trg_conversation_scope_insert','trg_conversation_scope_update','trg_message_scope_insert','trg_message_scope_update','trg_contact_team_access_insert'):
  c.execute('DROP TRIGGER IF EXISTS '+name)
 access="(ct.team_id=NEW.team_id OR EXISTS(SELECT 1 FROM contact_team_access x WHERE x.organization_id=NEW.organization_id AND x.workspace_id=NEW.workspace_id AND x.contact_id=NEW.contact_id AND x.team_id=NEW.team_id AND x.revoked_at IS NULL))"
 c.execute("""CREATE TRIGGER trg_contact_team_access_insert BEFORE INSERT ON contact_team_access BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM contacts ct JOIN teams t ON t.team_id=NEW.team_id WHERE ct.contact_id=NEW.contact_id AND ct.organization_id=NEW.organization_id AND ct.workspace_id=NEW.workspace_id AND t.organization_id=NEW.organization_id AND t.workspace_id=NEW.workspace_id) THEN RAISE(ABORT,'CONTACT_TEAM_ACCESS_SCOPE_MISMATCH') END; END""")
 conv=f"""SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM channel_accounts a JOIN team_channel_accounts g ON g.channel_account_id=a.channel_account_id AND g.team_id=NEW.team_id JOIN contacts ct ON ct.contact_id=NEW.contact_id JOIN teams t ON t.team_id=NEW.team_id WHERE a.channel_account_id=NEW.channel_account_id AND a.organization_id=NEW.organization_id AND a.platform_id=NEW.platform_id AND ct.organization_id=NEW.organization_id AND ct.workspace_id=NEW.workspace_id AND ct.deleted_at IS NULL AND t.organization_id=NEW.organization_id AND t.workspace_id=NEW.workspace_id AND {access}) THEN RAISE(ABORT,'CONVERSATION_SCOPE_MISMATCH') END"""
 c.execute('CREATE TRIGGER trg_conversation_scope_insert BEFORE INSERT ON conversations BEGIN '+conv+'; END')
 c.execute('CREATE TRIGGER trg_conversation_scope_update BEFORE UPDATE OF organization_id,workspace_id,team_id,channel_account_id,platform_id,contact_id ON conversations BEGIN '+conv+'; END')
 msg="""SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM conversations v WHERE v.conversation_id=NEW.conversation_id AND v.organization_id=NEW.organization_id AND v.workspace_id=NEW.workspace_id AND v.team_id=NEW.team_id AND v.channel_account_id=NEW.channel_account_id AND v.contact_id=NEW.contact_id) THEN RAISE(ABORT,'MESSAGE_SCOPE_MISMATCH') END"""
 c.execute('CREATE TRIGGER trg_message_scope_insert BEFORE INSERT ON conversation_messages BEGIN '+msg+'; END')
 c.execute('CREATE TRIGGER trg_message_scope_update BEFORE UPDATE OF organization_id,workspace_id,team_id,conversation_id,channel_account_id,contact_id ON conversation_messages BEGIN '+msg+'; END')

def _ensure_v221_governance_permissions(c):
 # Idempotent hot-backfill for databases that were already initialized as Schema 221.
 governance_perms=[
  ('contact.identity.link','关联客户身份','contact','identity.link','high'),
  ('contact.duplicate.review','审核重复客户','contact','duplicate.review','high'),
  ('contact.merge','合并客户','contact','merge','critical'),
   ('contact.merge.request','申请合并客户','contact','merge.request','high'),('contact.merge.review','审批合并申请','contact','merge.review','critical'),
  ('contact.team_access','管理客户团队访问','contact','team_access','critical'),
  ('contact.delete','删除客户','contact','delete','critical')]
 for k,d,res,act,risk in governance_perms:
  c.execute('INSERT OR IGNORE INTO permissions(permission_key,description,display_name,resource,action,scope_mask,risk_level) VALUES(?,?,?,?,?,63,?)',(k,d,d,res,act,risk))
 for role in ('role_superadmin','role_orgadmin'):
  for k,*_ in governance_perms:c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',(role,k))
 # 客户治理默认权限：销售/操作员可关联本人客户并提交申请；主管可审批并执行原子合并。
 for role in ('role_operator','role_sales','role-jbp-sales-self'):
  if c.execute('SELECT 1 FROM roles WHERE role_id=?',(role,)).fetchone():
   for k in ('contact.identity.link','contact.merge.request'):c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',(role,k))
 for role in ('role_teamlead','role-jbp-teamlead'):
  if c.execute('SELECT 1 FROM roles WHERE role_id=?',(role,)).fetchone():
   for k in ('contact.identity.link','contact.merge.request','contact.merge.review','contact.merge'):c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',(role,k))
 for k in ('contact.identity.link','contact.duplicate.review','contact.merge.request','contact.merge.review','contact.merge'):
  c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',('role_teamlead',k))
 for role in ('role_operator','role_sales'):
  if c.execute('SELECT 1 FROM roles WHERE role_id=?',(role,)).fetchone():c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',(role,'contact.merge.request'))

def backfill_v221_governance_permissions(path):
 path=Path(path).resolve();validate_schema221_readonly(path)
 c=sqlite3.connect(str(path),timeout=30,isolation_level=None);c.row_factory=sqlite3.Row
 try:
  c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=30000');c.execute('BEGIN IMMEDIATE')
  _ensure_v221_governance_permissions(c);c.execute('COMMIT')
 except Exception:
  if c.in_transaction:c.execute('ROLLBACK')
  raise
 finally:c.close()
 validate_schema221_readonly(path)

def ensure_v221(c):
 # Registration persists the resolved team on touchpoints; add it for both fresh installs and 220 upgrades.
 _add(c,'source_touchpoints','team_id','TEXT')
 rebuilt=_rebuild_contact_identities_v221(c);execute_sql_script(c,V221_SCHEMA);n=now_ms()
 _ensure_v221_governance_permissions(c)
 # Every primary team receives an explicit, auditable manage grant.
 for r in c.execute("SELECT contact_id,organization_id,workspace_id,team_id,owner_user_id FROM contacts WHERE organization_id IS NOT NULL AND team_id IS NOT NULL"):
  c.execute("INSERT OR IGNORE INTO contact_team_access(access_id,organization_id,workspace_id,contact_id,team_id,access_level,source_type,granted_by,granted_at,reason) VALUES(?,?,?,?,?,'manage','primary',?,?,?)",('cta_'+uuid.uuid4().hex,r['organization_id'],r['workspace_id'],r['contact_id'],r['team_id'],r['owner_user_id'],n,'Schema 221 主团队授权'))
 _install_v221_scope_triggers(c)
 checksum=hashlib.sha256(V221_SIGNATURE.encode()).hexdigest();result={'status':'success','schema':221,'identityRebuilt':rebuilt}
 c.execute("INSERT OR REPLACE INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES(?,?,?,?,?,?)",(V221_MIGRATION_ID,'Schema 221 客户身份关联与安全合并',checksum,n,'system',dumps(result)))
 return result

def validate_schema221_readonly(path):
 c=_connect_strict_readonly(path)
 try:
  version=c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
  if not version or str(version[0])!='221' or c.execute('PRAGMA user_version').fetchone()[0]!=221:raise RuntimeError('SCHEMA_221_INVALID: version')
  tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  # Registration touches these objects in one transaction. Reject incomplete upgrades at startup.
  required={'contact_team_access','contact_match_reviews','contact_merge_history','contacts','contact_identities',
   'interaction_idempotency','conversations','source_touchpoints','contact_attributions','source_resolution_logs','audit_logs'}
  if required-tables:raise RuntimeError('SCHEMA_221_INVALID: missing tables '+','.join(sorted(required-tables)))
  required_columns={
   'contacts':{'contact_id','organization_id','workspace_id','team_id','deleted_at','deleted_by','delete_reason','version'},
   'contact_identities':{'contact_identity_id','organization_id','workspace_id','contact_id','platform_id','identity_type','canonical_value'},
   'interaction_idempotency':{'organization_id','workspace_id','operation','idempotency_key','request_hash','response_json'},
   'conversations':{'conversation_id','organization_id','workspace_id','team_id','contact_id','channel_account_id','external_conversation_id'},
   'source_touchpoints':{'touchpoint_id','organization_id','workspace_id','team_id','contact_id','channel_type_id','event_key'},
   'contact_attributions':{'attribution_id','organization_id','workspace_id','contact_id'},
   'source_resolution_logs':{'resolution_log_id','organization_id','workspace_id'},
   'audit_logs':{'audit_id','organization_id','workspace_id','team_id','actor_id','operation','entity_type','entity_id'}}
  for table,expected_columns in required_columns.items():
   actual_columns={x[1] for x in c.execute('PRAGMA table_info("'+table+'")')}
   missing_columns=sorted(expected_columns-actual_columns)
   if missing_columns:raise RuntimeError('SCHEMA_221_INVALID: '+table+' missing columns '+','.join(missing_columns))
  sql=(c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='contact_identities'").fetchone() or [''])[0] or ''
  if 'UNIQUE(organization_id,workspace_id,platform_id,identity_type,canonical_value)' not in sql:raise RuntimeError('SCHEMA_221_INVALID: identity scope')
  identity_fk=[r for r in c.execute('PRAGMA foreign_key_list(conversations)') if r[3]=='contact_identity_id']
  if len(identity_fk)!=1 or identity_fk[0][2]!='contact_identities':
   raise RuntimeError('SCHEMA_221_INVALID: conversations.contact_identity_id target '+repr([r[2] for r in identity_fk]))
  triggers={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
  reqt={'trg_conversation_scope_insert','trg_conversation_scope_update','trg_message_scope_insert','trg_message_scope_update','trg_contact_team_access_insert'}
  if reqt-triggers:raise RuntimeError('SCHEMA_221_INVALID: triggers')
  expected=hashlib.sha256(V221_SIGNATURE.encode()).hexdigest();row=c.execute('SELECT checksum FROM schema_migrations WHERE migration_id=?',(V221_MIGRATION_ID,)).fetchone()
  if not row or row[0]!=expected:raise RuntimeError('SCHEMA_221_INVALID: migration checksum')
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('SCHEMA_221_INVALID: quick_check')
  if list(c.execute('PRAGMA foreign_key_check')):raise RuntimeError('SCHEMA_221_INVALID: foreign_key_check')
 finally:c.close()

def migrate_schema220_to_221(path):
 path=Path(path).resolve();version=_read_existing_schema_version(path)
 if version=='221':backfill_v221_governance_permissions(path);return None
 if version!='220':raise RuntimeError('SCHEMA_221_MIGRATION_REQUIRES_220: detected '+repr(version))
 validate_schema220_readonly(path);backup=_exclusive_backup_path(path);_sqlite_backup(path,backup)
 c=sqlite3.connect(str(path),timeout=30,isolation_level=None);c.row_factory=sqlite3.Row
 try:
  c.execute('PRAGMA busy_timeout=30000');c.execute('PRAGMA foreign_keys=OFF');c.execute('BEGIN IMMEDIATE');ensure_v221(c)
  c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version','221')");c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('product_version',?)",(PRODUCT_VERSION,));c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('catalog_version',?)",(CATALOG_VERSION,));c.execute('PRAGMA user_version=221')
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('SCHEMA_221_MIGRATION_QUICK_CHECK_FAILED')
  c.execute('COMMIT');c.close();validate_schema221_readonly(path);return backup
 except Exception as exc:
  try:
   if c.in_transaction:c.execute('ROLLBACK')
   c.close()
  except Exception:pass
  _restore_sqlite_backup(backup,path);_write_failure_report(path,exc,backup);raise

def validate_schema219_readonly(path):
 c=_connect_strict_readonly(path)
 try:
  version=c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
  if not version or str(version[0])!='219' or c.execute('PRAGMA user_version').fetchone()[0]!=219:raise RuntimeError('SCHEMA_219_INVALID: version')
  tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  required={'source_type_definitions','markets','source_resolution_logs','contact_conversions'}
  if required-tables:raise RuntimeError('SCHEMA_219_INVALID: missing tables: '+','.join(sorted(required-tables)))
  account_cols={r[1] for r in c.execute('PRAGMA table_info(channel_accounts)')}
  if {'default_market_id','suggested_source_type_id'}-account_cols:raise RuntimeError('SCHEMA_219_INVALID: channel account columns')
  source_cols={r[1] for r in c.execute('PRAGMA table_info(sources)')}
  if {'market_id','source_fingerprint','resolution_method','resolution_confidence'}-source_cols:raise RuntimeError('SCHEMA_219_INVALID: source columns')
  touchpoint_cols={r[1]:r for r in c.execute('PRAGMA table_info(source_touchpoints)')}
  if 'occurred_at' not in touchpoint_cols:raise RuntimeError('SCHEMA_219_INVALID: source_touchpoints.occurred_at missing')
  if int(touchpoint_cols['occurred_at'][3])!=0:raise RuntimeError('SCHEMA_219_INVALID: source_touchpoints.occurred_at must be nullable')
  codes={r[0] for r in c.execute("SELECT source_type_code FROM source_type_definitions WHERE is_active=1")}
  if {x[1] for x in V219_SOCIAL_SOURCE_TYPES}-codes:raise RuntimeError('SCHEMA_219_INVALID: social source types')
  indexes={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
  if {'uq_sources_fingerprint','uq_touchpoint_event_key','uq_touchpoint_external_event','uq_conversion_external_key'}-indexes:raise RuntimeError('SCHEMA_219_INVALID: unique indexes')
  perms={r[0] for r in c.execute("SELECT permission_key FROM permissions WHERE permission_key IN ('conversion.read','conversion.manage')")}
  if perms!={'conversion.read','conversion.manage'}:raise RuntimeError('SCHEMA_219_INVALID: conversion permissions')
  for role in ('role_superadmin','role_orgadmin'):
   grants={r[0] for r in c.execute("SELECT permission_key FROM role_permissions WHERE role_id=? AND permission_key IN ('conversion.read','conversion.manage')",(role,))}
   if grants!={'conversion.read','conversion.manage'}:raise RuntimeError('SCHEMA_219_INVALID: conversion role grants '+role)
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('SCHEMA_219_INVALID: quick_check')
  if list(c.execute('PRAGMA foreign_key_check')):raise RuntimeError('SCHEMA_219_INVALID: foreign_key_check')
  validate_registered_migration_checksums(path)
 finally:c.close()

def validate_schema218_readonly(path):
 c=_connect_strict_readonly(path)
 try:
  version=c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
  if not version or str(version[0])!='218' or c.execute('PRAGMA user_version').fetchone()[0]!=218:raise RuntimeError('SCHEMA_218_INVALID: version')
  account_cols={r[1] for r in c.execute('PRAGMA table_info(channel_accounts)')}
  if {'business_scene','contact_entry_policy'}-account_cols:raise RuntimeError('SCHEMA_218_INVALID: channel account columns')
  idem_cols={r[1] for r in c.execute('PRAGMA table_info(interaction_idempotency)')}
  if {'organization_id','workspace_id','team_id','user_id','operation','idempotency_key','request_hash','response_json'}-idem_cols:raise RuntimeError('SCHEMA_218_INVALID: interaction idempotency')
  stages=list(c.execute("SELECT field_key FROM custom_field_definitions WHERE field_role LIKE 'stage_%' ORDER BY sort_order"))
  if [x[0] for x in stages]!=['communication_stage','intention_stage','conversion_stage']:raise RuntimeError('SCHEMA_218_INVALID: three stages')
  triggers={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
  required={'trg_channel_account_policy_insert','trg_channel_account_policy_update','trg_contacts_owner_required_insert','trg_contacts_owner_required_update'}
  if required-triggers:raise RuntimeError('SCHEMA_218_INVALID: triggers')
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('SCHEMA_218_INVALID: quick_check')
  if list(c.execute('PRAGMA foreign_key_check')):raise RuntimeError('SCHEMA_218_INVALID: foreign_key_check')
  validate_registered_migration_checksums(path)
 finally:c.close()

V222_MIGRATION_ID='V222_conversation_transfer_center'
V222_SIGNATURE='schema222:conversation-summary,stable-message-order,transfer-state-machine,transfer-events,scope-triggers-v2,rbac'
V222_PERMISSIONS={
 'conversation.close':'关闭或重新打开授权范围内的会话',
 'conversation.archive':'归档或恢复授权范围内的会话',
 'conversation.recollect':'删除会话消息并发起重新采集',
 'transfer.read.self':'读取本人发起或处理的客户转交',
 'transfer.read.team':'读取授权团队范围的客户转交',
 'transfer.match':'匹配客户转交的目标会话',
 'transfer.confirm':'确认客户跨渠道转交',
 'transfer.reject':'拒绝客户跨渠道转交',
 'transfer.cancel.self':'取消本人发起的待处理客户转交',
 'transfer.audit.read':'读取客户转交事件与审计记录'}

def _create_v222_transfer_tables(c):
 # Schema 222 is a clean-install baseline. Rebuild the empty legacy table to replace its status CHECK.
 count=c.execute('SELECT COUNT(*) FROM contact_transfers').fetchone()[0]
 if count:raise RuntimeError('SCHEMA_222_CLEAN_INSTALL_REQUIRED: contact_transfers is not empty')
 c.execute('DROP INDEX IF EXISTS idx_transfers_contact_time')
 c.execute('DROP TABLE contact_transfers')
 c.execute("""CREATE TABLE contact_transfers(
  transfer_id TEXT PRIMARY KEY,
  organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,team_id TEXT NOT NULL,contact_id TEXT NOT NULL,
  transfer_type TEXT NOT NULL DEFAULT 'channel_transfer' CHECK(transfer_type IN ('channel_transfer','owner_reassignment','team_handoff')),
  from_channel_account_id TEXT,from_conversation_id TEXT,from_platform_id TEXT,
  to_channel_account_id TEXT NOT NULL,to_conversation_id TEXT,to_platform_id TEXT,
  transfer_method TEXT NOT NULL CHECK(transfer_method IN ('phone_shared','username_shared','invite_link','qr_code','manual_link','system_match','other')),
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','matched','confirmed','rejected','failed','cancelled','expired')),
  requested_by TEXT NOT NULL,requested_at INTEGER NOT NULL,
  accepted_by TEXT,accepted_at INTEGER,rejected_by TEXT,rejected_at INTEGER,cancelled_by TEXT,cancelled_at INTEGER,
  failed_at INTEGER,expired_at INTEGER,expires_at INTEGER,
  reason TEXT NOT NULL DEFAULT '',rejection_reason TEXT NOT NULL DEFAULT '',failure_code TEXT,failure_reason TEXT NOT NULL DEFAULT '',
  matched_identity_id TEXT,match_confidence INTEGER CHECK(match_confidence IS NULL OR (match_confidence>=0 AND match_confidence<=100)),
  match_evidence_json TEXT NOT NULL DEFAULT '{}',idempotency_key TEXT NOT NULL,request_hash TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1 CHECK(version>=1),metadata_json TEXT NOT NULL DEFAULT '{}',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
  FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
  FOREIGN KEY(team_id) REFERENCES teams(team_id),FOREIGN KEY(contact_id) REFERENCES contacts(contact_id) ON DELETE RESTRICT,
  FOREIGN KEY(from_channel_account_id) REFERENCES channel_accounts(channel_account_id),FOREIGN KEY(from_conversation_id) REFERENCES conversations(conversation_id),
  FOREIGN KEY(from_platform_id) REFERENCES platforms(platform_id),FOREIGN KEY(to_channel_account_id) REFERENCES channel_accounts(channel_account_id),
  FOREIGN KEY(to_conversation_id) REFERENCES conversations(conversation_id),FOREIGN KEY(to_platform_id) REFERENCES platforms(platform_id),
  FOREIGN KEY(requested_by) REFERENCES users(user_id),FOREIGN KEY(accepted_by) REFERENCES users(user_id),
  FOREIGN KEY(rejected_by) REFERENCES users(user_id),FOREIGN KEY(cancelled_by) REFERENCES users(user_id),
  FOREIGN KEY(matched_identity_id) REFERENCES contact_identities(contact_identity_id),
  UNIQUE(organization_id,idempotency_key))""")
 c.execute("""CREATE TABLE contact_transfer_events(
  event_id TEXT PRIMARY KEY,transfer_id TEXT NOT NULL,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,team_id TEXT NOT NULL,contact_id TEXT NOT NULL,
  event_type TEXT NOT NULL CHECK(event_type IN ('created','matched','confirmed','rejected','cancelled','failed','expired','target_conversation_linked','match_evidence_updated')),
  from_status TEXT,to_status TEXT,actor_id TEXT NOT NULL,conversation_id TEXT,channel_account_id TEXT,reason TEXT NOT NULL DEFAULT '',details_json TEXT NOT NULL DEFAULT '{}',created_at INTEGER NOT NULL,
  FOREIGN KEY(transfer_id) REFERENCES contact_transfers(transfer_id) ON DELETE RESTRICT,
  FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
  FOREIGN KEY(team_id) REFERENCES teams(team_id),FOREIGN KEY(contact_id) REFERENCES contacts(contact_id) ON DELETE RESTRICT,
  FOREIGN KEY(actor_id) REFERENCES users(user_id),FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id),
  FOREIGN KEY(channel_account_id) REFERENCES channel_accounts(channel_account_id))""")

def _install_v222_indexes_and_triggers(c):
 statements=[
  "CREATE INDEX idx_conversations_scope_activity ON conversations(organization_id,workspace_id,team_id,last_message_at DESC,conversation_id DESC)",
  "CREATE INDEX idx_conversations_scope_contact_activity ON conversations(organization_id,workspace_id,team_id,contact_id,last_message_at DESC,conversation_id DESC)",
  "CREATE INDEX idx_messages_scope_conversation_time ON conversation_messages(organization_id,workspace_id,team_id,conversation_id,occurred_at DESC,message_id DESC)",
  "CREATE INDEX idx_messages_scope_contact_time ON conversation_messages(organization_id,workspace_id,team_id,contact_id,occurred_at DESC,message_id DESC)",
  "CREATE INDEX idx_transfers_scope_status_time ON contact_transfers(organization_id,workspace_id,team_id,status,requested_at DESC,transfer_id DESC)",
  "CREATE INDEX idx_transfers_contact_time ON contact_transfers(organization_id,workspace_id,contact_id,requested_at DESC,transfer_id DESC)",
  "CREATE UNIQUE INDEX uq_transfers_pending_target ON contact_transfers(organization_id,workspace_id,contact_id,to_channel_account_id) WHERE status IN ('pending','matched')",
  "CREATE INDEX idx_transfer_events_transfer_time ON contact_transfer_events(transfer_id,created_at,event_id)"]
 for sql in statements:c.execute(sql)
 transfer_scope="""NOT EXISTS(SELECT 1 FROM contacts x JOIN teams t ON t.team_id=NEW.team_id JOIN workspaces w ON w.workspace_id=NEW.workspace_id JOIN users u ON u.user_id=NEW.requested_by JOIN channel_accounts ta ON ta.channel_account_id=NEW.to_channel_account_id WHERE x.contact_id=NEW.contact_id AND x.organization_id=NEW.organization_id AND x.workspace_id=NEW.workspace_id AND x.team_id=NEW.team_id AND t.organization_id=NEW.organization_id AND t.workspace_id=NEW.workspace_id AND w.organization_id=NEW.organization_id AND u.organization_id=NEW.organization_id AND ta.organization_id=NEW.organization_id AND (NEW.to_platform_id IS NULL OR ta.platform_id=NEW.to_platform_id)) OR (NEW.from_channel_account_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM channel_accounts a WHERE a.channel_account_id=NEW.from_channel_account_id AND a.organization_id=NEW.organization_id AND (NEW.from_platform_id IS NULL OR a.platform_id=NEW.from_platform_id))) OR (NEW.from_conversation_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM conversations v WHERE v.conversation_id=NEW.from_conversation_id AND v.organization_id=NEW.organization_id AND v.workspace_id=NEW.workspace_id AND v.team_id=NEW.team_id AND v.contact_id=NEW.contact_id AND (NEW.from_channel_account_id IS NULL OR v.channel_account_id=NEW.from_channel_account_id))) OR (NEW.to_conversation_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM conversations v WHERE v.conversation_id=NEW.to_conversation_id AND v.organization_id=NEW.organization_id AND v.workspace_id=NEW.workspace_id AND v.team_id=NEW.team_id AND v.contact_id=NEW.contact_id AND v.channel_account_id=NEW.to_channel_account_id)) OR (NEW.matched_identity_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM contact_identities i WHERE i.contact_identity_id=NEW.matched_identity_id AND i.organization_id=NEW.organization_id AND i.contact_id=NEW.contact_id))"""
 c.execute("CREATE TRIGGER trg_transfer_scope_insert BEFORE INSERT ON contact_transfers BEGIN SELECT CASE WHEN "+transfer_scope+" THEN RAISE(ABORT,'TRANSFER_SCOPE_MISMATCH') END; END")
 c.execute("CREATE TRIGGER trg_transfer_scope_update BEFORE UPDATE OF organization_id,workspace_id,team_id,contact_id,from_channel_account_id,from_conversation_id,from_platform_id,to_channel_account_id,to_conversation_id,to_platform_id,requested_by,matched_identity_id ON contact_transfers BEGIN SELECT CASE WHEN "+transfer_scope+" THEN RAISE(ABORT,'TRANSFER_SCOPE_MISMATCH') END; END")
 event_scope="""NOT EXISTS(SELECT 1 FROM contact_transfers t WHERE t.transfer_id=NEW.transfer_id AND t.organization_id=NEW.organization_id AND t.workspace_id=NEW.workspace_id AND t.team_id=NEW.team_id AND t.contact_id=NEW.contact_id) OR NOT EXISTS(SELECT 1 FROM users u WHERE u.user_id=NEW.actor_id AND u.organization_id=NEW.organization_id) OR (NEW.conversation_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM conversations v WHERE v.conversation_id=NEW.conversation_id AND v.organization_id=NEW.organization_id AND v.workspace_id=NEW.workspace_id AND v.team_id=NEW.team_id AND v.contact_id=NEW.contact_id AND (NEW.channel_account_id IS NULL OR v.channel_account_id=NEW.channel_account_id))) OR (NEW.channel_account_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM channel_accounts a WHERE a.channel_account_id=NEW.channel_account_id AND a.organization_id=NEW.organization_id))"""
 c.execute("CREATE TRIGGER trg_transfer_event_scope_insert BEFORE INSERT ON contact_transfer_events BEGIN SELECT CASE WHEN "+event_scope+" THEN RAISE(ABORT,'TRANSFER_EVENT_SCOPE_MISMATCH') END; END")
 c.execute("CREATE TRIGGER trg_transfer_event_scope_update BEFORE UPDATE OF transfer_id,organization_id,workspace_id,team_id,contact_id,actor_id,conversation_id,channel_account_id ON contact_transfer_events BEGIN SELECT CASE WHEN "+event_scope+" THEN RAISE(ABORT,'TRANSFER_EVENT_SCOPE_MISMATCH') END; END")

def _ensure_whatsapp_identity_foundation(c):
 execute_sql_script(c,"""
 CREATE TABLE IF NOT EXISTS conversation_external_aliases(
  alias_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,
  channel_account_id TEXT NOT NULL,platform_id TEXT NOT NULL,conversation_id TEXT NOT NULL,
  contact_id TEXT NOT NULL,alias_type TEXT NOT NULL,alias_value TEXT NOT NULL,
  evidence_source TEXT NOT NULL,first_seen_at INTEGER NOT NULL,last_seen_at INTEGER NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
  FOREIGN KEY(contact_id) REFERENCES contacts(contact_id),
  UNIQUE(organization_id,channel_account_id,alias_value));
 CREATE INDEX IF NOT EXISTS idx_conversation_alias_contact ON conversation_external_aliases(organization_id,workspace_id,platform_id,contact_id);
 CREATE TABLE IF NOT EXISTS whatsapp_identity_links(
  link_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,platform_id TEXT NOT NULL,
  contact_id TEXT NOT NULL,lid_canonical TEXT NOT NULL,jid_canonical TEXT NOT NULL,
  evidence_source TEXT NOT NULL,verification_status TEXT NOT NULL DEFAULT 'observed' CHECK(verification_status IN ('observed','verified','revoked')),
  first_seen_at INTEGER NOT NULL,last_seen_at INTEGER NOT NULL,metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(contact_id) REFERENCES contacts(contact_id),
  UNIQUE(organization_id,workspace_id,platform_id,lid_canonical),
  UNIQUE(organization_id,workspace_id,platform_id,jid_canonical),
  UNIQUE(organization_id,workspace_id,platform_id,lid_canonical,jid_canonical));
 CREATE UNIQUE INDEX IF NOT EXISTS uq_direct_conversation_account_contact
  ON conversations(organization_id,channel_account_id,contact_id) WHERE conversation_type='direct';
 """)

def _ensure_follow_up_notification_tables(c):
 execute_sql_script(c,"""
 CREATE TABLE IF NOT EXISTS follow_up_notifications(
  notification_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,team_id TEXT,
  contact_id TEXT NOT NULL,owner_user_id TEXT,follow_up_at INTEGER NOT NULL,follow_up_reason TEXT NOT NULL DEFAULT '',
  customer_name TEXT NOT NULL DEFAULT '',platform_id TEXT,platform_code TEXT,platform_abbr TEXT,
  channel_account_id TEXT,channel_account_name TEXT,source_device_id TEXT,source_device_name TEXT,
  status TEXT NOT NULL DEFAULT 'scheduled' CHECK(status IN ('scheduled','due','overdue','completed','cancelled','superseded')),
  completed_at INTEGER,completed_by_user_id TEXT,completion_mode TEXT,completion_message_id TEXT,
  completion_evidence_json TEXT NOT NULL DEFAULT '{}',cancelled_at INTEGER,cancellation_reason TEXT,
  first_due_at INTEGER,last_scanned_at INTEGER,contact_version INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1 CHECK(version>=1),created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
  FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
  FOREIGN KEY(team_id) REFERENCES teams(team_id),FOREIGN KEY(contact_id) REFERENCES contacts(contact_id) ON DELETE RESTRICT,
  FOREIGN KEY(owner_user_id) REFERENCES users(user_id),FOREIGN KEY(platform_id) REFERENCES platforms(platform_id),
  FOREIGN KEY(channel_account_id) REFERENCES channel_accounts(channel_account_id),FOREIGN KEY(source_device_id) REFERENCES devices(device_id),
  FOREIGN KEY(completed_by_user_id) REFERENCES users(user_id),FOREIGN KEY(completion_message_id) REFERENCES conversation_messages(message_id),
  UNIQUE(organization_id,contact_id,follow_up_at));
 CREATE TABLE IF NOT EXISTS follow_up_notification_receipts(
  receipt_id TEXT PRIMARY KEY,notification_id TEXT NOT NULL,organization_id TEXT NOT NULL,recipient_user_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'unread' CHECK(status IN ('unread','alerted','read','snoozed','dismissed','closed')),
  first_alerted_at INTEGER,last_alerted_at INTEGER,next_alert_at INTEGER,alert_count INTEGER NOT NULL DEFAULT 0,
  read_at INTEGER,snooze_until INTEGER,dismissed_at INTEGER,claimed_by_consumer TEXT,claim_expires_at INTEGER,
  last_consumer_type TEXT,last_consumer_id TEXT,version INTEGER NOT NULL DEFAULT 1 CHECK(version>=1),
  created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
  FOREIGN KEY(notification_id) REFERENCES follow_up_notifications(notification_id) ON DELETE CASCADE,
  FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),FOREIGN KEY(recipient_user_id) REFERENCES users(user_id),
  UNIQUE(notification_id,recipient_user_id));
 CREATE INDEX IF NOT EXISTS idx_follow_notifications_due ON follow_up_notifications(organization_id,status,follow_up_at);
 CREATE INDEX IF NOT EXISTS idx_follow_notifications_contact ON follow_up_notifications(contact_id,status);
 CREATE INDEX IF NOT EXISTS idx_follow_receipts_recipient ON follow_up_notification_receipts(organization_id,recipient_user_id,status,next_alert_at);
 CREATE INDEX IF NOT EXISTS idx_follow_receipts_notification ON follow_up_notification_receipts(notification_id);
 CREATE TABLE IF NOT EXISTS platform_admin_notification_subscriptions(
  admin_user_id TEXT NOT NULL,organization_id TEXT NOT NULL,owner_user_id TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
  created_by TEXT NOT NULL,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
  PRIMARY KEY(admin_user_id,organization_id,owner_user_id),
  FOREIGN KEY(admin_user_id) REFERENCES users(user_id),FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
  FOREIGN KEY(owner_user_id) REFERENCES users(user_id),FOREIGN KEY(created_by) REFERENCES users(user_id));
 CREATE INDEX IF NOT EXISTS idx_admin_notification_subscriptions_owner ON platform_admin_notification_subscriptions(organization_id,owner_user_id,enabled,admin_user_id);
 CREATE INDEX IF NOT EXISTS idx_messages_followup_completion ON conversation_messages(contact_id,direction,sender_type,status,occurred_at);
 """)
 # 210.2.38 legacy follow-up state repair: exact equality preserves a newer plan.
 # Idempotent startup repair; no recurring scanner, network request or new table.
 c.execute("""UPDATE contacts SET next_follow_up_at=NULL,version=version+1,updated_at=CASE
  WHEN updated_at IS NULL OR updated_at < COALESCE((SELECT MAX(fn.completed_at) FROM follow_up_notifications fn WHERE fn.contact_id=contacts.contact_id AND fn.follow_up_at=contacts.next_follow_up_at AND fn.status='completed'),updated_at)
  THEN COALESCE((SELECT MAX(fn.completed_at) FROM follow_up_notifications fn WHERE fn.contact_id=contacts.contact_id AND fn.follow_up_at=contacts.next_follow_up_at AND fn.status='completed'),updated_at)
  ELSE updated_at END
  WHERE next_follow_up_at IS NOT NULL AND EXISTS(SELECT 1 FROM follow_up_notifications fn WHERE fn.contact_id=contacts.contact_id AND fn.follow_up_at=contacts.next_follow_up_at AND fn.status='completed')""")
 # 210.2.35 legacy follow-up split-state repair: exact-time match protects newer plans.
 c.execute("""UPDATE contacts
  SET next_follow_up_at=NULL,version=version+1,
      updated_at=MAX(COALESCE(updated_at,0),COALESCE((SELECT MAX(f.completed_at) FROM follow_up_notifications f
       WHERE f.contact_id=contacts.contact_id AND f.follow_up_at=contacts.next_follow_up_at AND f.status='completed'),0))
  WHERE next_follow_up_at IS NOT NULL
    AND EXISTS(SELECT 1 FROM follow_up_notifications f WHERE f.contact_id=contacts.contact_id
     AND f.follow_up_at=contacts.next_follow_up_at AND f.status='completed')""")

def ensure_v222(c):
 for col,decl in (
  ('version','INTEGER NOT NULL DEFAULT 1'),('closed_at','INTEGER'),('closed_by','TEXT'),('archived_at','INTEGER'),('archived_by','TEXT'),
  ('last_message_id','TEXT'),('last_message_direction','TEXT'),('last_message_type','TEXT'),('last_message_preview',"TEXT NOT NULL DEFAULT ''"),
  ('message_count','INTEGER NOT NULL DEFAULT 0'),('inbound_count','INTEGER NOT NULL DEFAULT 0'),('outbound_count','INTEGER NOT NULL DEFAULT 0')):_add(c,'conversations',col,decl)
 for col,decl in (('reply_to_message_id','TEXT'),('attachment_count','INTEGER NOT NULL DEFAULT 0'),('has_sensitive_content','INTEGER NOT NULL DEFAULT 0'),('source_event_id','TEXT'),('ingestion_version','INTEGER NOT NULL DEFAULT 1')):_add(c,'conversation_messages',col,decl)
 _create_v222_transfer_tables(c);_install_v222_indexes_and_triggers(c);_ensure_whatsapp_identity_foundation(c);_ensure_follow_up_notification_tables(c)
 for key,description in V222_PERMISSIONS.items():c.execute('INSERT OR IGNORE INTO permissions(permission_key,description) VALUES(?,?)',(key,description))
 # Canonical role IDs seeded by BASE_SCHEMA.
 for role in ('role_superadmin','role_orgadmin'):
  for key in V222_PERMISSIONS:c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',(role,key))
 for key in ('conversation.read.team','conversation.close','conversation.archive','conversation.recollect','transfer.read.team','transfer.match','transfer.confirm','transfer.reject','transfer.cancel.self','transfer.audit.read'):
  c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',('role_teamlead',key))
 for key in ('conversation.read.self','conversation.close','transfer.read.self','transfer.match','transfer.cancel.self'):
  c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',('role_operator',key))
 checksum=hashlib.sha256(V222_SIGNATURE.encode()).hexdigest();n=now_ms();result={'status':'success','schema':222}
 c.execute("INSERT OR REPLACE INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES(?,?,?,?,?,?)",(V222_MIGRATION_ID,'Schema 222 跨平台会话与客户转交基础',checksum,n,'system',dumps(result)))
 return result

V222_HOTFIX_PERMISSIONS={
 'conversation.recollect':'删除会话消息并发起重新采集'}
V222_HOTFIX_GRANTS={
 'role_superadmin':('conversation.recollect',),
 'role_orgadmin':('conversation.recollect',),
 'role_teamlead':('conversation.recollect',)}

STAGE_210_1_PRESETS=(
 ('communication_stage','沟通','stage_communication',100,['投资','看盘','财经']),
 ('intention_stage','意向','stage_intention',110,['盈利','交易','量化']),
 ('conversion_stage','转化','stage_conversion',120,['体验','赠金','联合']),
)

def _apply_210_1_stage_presets(c):
 """210.1.0 配置热修复：定义是唯一数据源；旧值仅保留仍在新候选中的成员。"""
 n=now_ms()
 for key,label,role,order,options in STAGE_210_1_PRESETS:
  c.execute("UPDATE custom_field_definitions SET label=?,field_type='multi_select',sort_order=?,enabled=1,updated_at=?,field_role=?,display_zone='workbench',is_quick_edit=1,options_json=? WHERE field_key=?",(label,order,n,role,dumps(options),key))
  # 补齐新增工作区中意外缺失的预制。
  c.execute("INSERT INTO custom_field_definitions(workspace_id,field_key,label,field_type,sort_order,enabled,created_at,updated_at,field_role,display_zone,is_quick_edit,options_json,placeholder) SELECT workspace_id,?,?, 'multi_select',?,1,?,?,?,'workbench',1,?,'' FROM workspaces w WHERE NOT EXISTS(SELECT 1 FROM custom_field_definitions d WHERE d.workspace_id=w.workspace_id AND d.field_key=?)",(key,label,order,n,n,role,dumps(options),key))
  rows=c.execute("SELECT v.contact_id,v.value_json FROM contact_custom_values v JOIN contacts ct ON ct.contact_id=v.contact_id WHERE v.field_key=?",(key,)).fetchall()
  allowed=set(options)
  for row in rows:
   old=loads(row[1],[])
   values=old if isinstance(old,list) else ([] if old in (None,'') else [old])
   clean=[]
   for value in values:
    if isinstance(value,str) and value in allowed and value not in clean:clean.append(value)
   if clean!=old:c.execute("UPDATE contact_custom_values SET value_json=?,updated_at=? WHERE contact_id=? AND field_key=?",(dumps(clean),n,row[0],key))
 c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('stage_presets_version','210.1.0')")
 c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('product_version',?)",(PRODUCT_VERSION,))


# 210.2.2-210.2.4: minimum-compatible RBAC governance hardening.
V223_RBAC_MIGRATION_ID='V223_010_role_business_mapping'
V223_RBAC_SIGNATURE='standard role display mapping; finance template; binding validity and reason; platform administrator all permissions'
STANDARD_ROLE_MAPPING={
 'role_superadmin':('平台超级管理员','platform_admin','platform','平台级全部权限；跨企业访问必须审计。'),
 'role_orgadmin':('企业系统管理员','organization_admin','organization','管理企业用户、组织、角色、渠道与配置。'),
 'role_teamlead':('业务团队主管','business_team_manager','team','管理本团队客户、会话、分配与运营。'),
 'role_operator':('客户业务专员','client_business_specialist','team','处理授权范围内的客户、会话与转交。'),
 'role_readonly':('团队只读分析岗','team_readonly_analyst','team','只读查看授权团队业务资料。'),
 'role_auditor':('合规审计岗','compliance_auditor','organization','只读审阅授权、操作与高风险日志。'),
 'role-jbp-risk-admin':('风控合规管理岗','risk_compliance_manager','organization','业务风险、合规复核与异常审阅。'),
 'role-jbp-org-readonly':('企业运营观察岗','executive_operations_observer','organization','业务运营部企业范围只读观察角色。'),
 'role-jbp-ws-operator':('渠道运营专员','channel_operations_specialist','workspace','管理授权工作区的渠道、来源与客户运营。'),
 'role-jbp-ws-readonly':('策略研究分析岗','research_analyst','workspace','承担策略研究、投资分析与执行分析职责。')}
FINANCE_PERMISSIONS=('conversion.read','attribution.read','campaign.read','source.read','audit.read')
ORGADMIN_PERMISSIONS=('organization.read', 'organization.manage', 'organization.structure.read', 'organization.structure.manage', 'team.read', 'team.manage', 'user.read', 'user.manage', 'role.read', 'role.manage', 'permission.read', 'account.read', 'account.manage', 'source.read', 'source.manage', 'source.path.read', 'source.path.manage', 'campaign.read', 'campaign.manage', 'touchpoint.read', 'touchpoint.manage', 'attribution.read', 'attribution.manage', 'attribution.recalculate', 'contact.read', 'contact.update', 'contact.delete', 'contact.restore', 'contact.identity.manage', 'device.read', 'device.bind', 'device.disable', 'device.rename.self', 'conversion.read', 'conversion.manage', 'conversation.read.self', 'conversation.read.team', 'message.read.self', 'message.read.team', 'transfer.read.self', 'transfer.read.team', 'transfer.create', 'transfer.manage', 'audit.read')

def ensure_v223_rbac_governance(c):
 checksum=hashlib.sha256(V223_RBAC_SIGNATURE.encode()).hexdigest();old=c.execute('SELECT checksum FROM schema_migrations WHERE migration_id=?',(V223_RBAC_MIGRATION_ID,)).fetchone()
 if old and old[0]!=checksum:raise RuntimeError('MIGRATION_CHECKSUM_MISMATCH: '+V223_RBAC_MIGRATION_ID)
 for col,decl in (('valid_from','INTEGER'),('expires_at','INTEGER'),('grant_reason',"TEXT NOT NULL DEFAULT ''"),('grant_type',"TEXT NOT NULL DEFAULT 'standard'"),('approved_by','TEXT')):_add(c,'role_bindings',col,decl)
 c.execute('CREATE INDEX IF NOT EXISTS idx_role_bindings_effective ON role_bindings(user_id,status,valid_from,expires_at)')
 n=now_ms();c.execute('UPDATE role_bindings SET valid_from=COALESCE(valid_from,created_at,?)',(n,))
 # Temporarily move legacy codes so the global unique index cannot block deterministic swaps.
 existing={r[0] for r in c.execute('SELECT role_id FROM roles')}
 # Reserve canonical codes for canonical IDs; rename conflicting custom roles deterministically.
 used={r[0] for r in c.execute('SELECT role_code FROM roles WHERE role_code IS NOT NULL')}
 for canonical_id,(_,canonical_code,_,_) in STANDARD_ROLE_MAPPING.items():
  conflicts=c.execute('SELECT role_id,organization_id FROM roles WHERE role_code=? AND role_id<>?',(canonical_code,canonical_id)).fetchall()
  for row in conflicts:
   base=(str(row['organization_id'] or 'global')+'.'+str(row['role_id'])+'.custom')[:180];candidate=base;i=1
   while candidate in used:candidate=(base+'.'+str(i))[:200];i+=1
   c.execute('UPDATE roles SET role_code=? WHERE role_id=?',(candidate,row['role_id']));used.add(candidate)
 for rid in STANDARD_ROLE_MAPPING:
  if rid in existing:c.execute('UPDATE roles SET role_code=? WHERE role_id=?',("legacy_v223_"+rid,rid))
 for rid,(name,code,scope,desc) in STANDARD_ROLE_MAPPING.items():
  if rid in existing:c.execute('UPDATE roles SET name=?,role_code=?,scope_level=?,description=? WHERE role_id=?',(name,code,scope,desc,rid))
 # Global system template: one technical role can be bound independently inside every enterprise.
 c.execute("INSERT OR IGNORE INTO roles(role_id,organization_id,name,scope_level,status,role_code,description,is_system) VALUES('role-jbp-finance-operator',NULL,'财务经办岗','organization','active','finance_operator','财务数据只读与经办；不含退款或调整审批。',1)")
 for key in FINANCE_PERMISSIONS:
  if c.execute('SELECT 1 FROM permissions WHERE permission_key=?',(key,)).fetchone():c.execute("INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES('role-jbp-finance-operator',?)",(key,))
 # Platform administrator is the sole role automatically synchronized to every registered permission.
 c.execute("INSERT OR IGNORE INTO role_permissions(role_id,permission_key) SELECT 'role_superadmin',permission_key FROM permissions")
 # Normalize enterprise administrator; remove legacy platform/database grants.
 c.execute("DELETE FROM role_permissions WHERE role_id='role_orgadmin'")
 for key in ORGADMIN_PERMISSIONS:
  if c.execute('SELECT 1 FROM permissions WHERE permission_key=?',(key,)).fetchone():
   c.execute("INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES('role_orgadmin',?)",(key,))
 if not old:c.execute('INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES(?,?,?,?,?,?)',(V223_RBAC_MIGRATION_ID,'权限角色业务化与临时授权基础',checksum,n,'system',dumps({'status':'success','standardRoles':11})))

# 210.2.6 final RBAC governance overlay; intentionally separate from immutable V223 checksum.
V224_RBAC_MIGRATION_ID='V224_010_rbac_unification_210_2_6'
V224_RBAC_SIGNATURE='210.2.6 standard role completion; least privilege orgadmin; platform permission sync; role-binding data scopes'
STANDARD_ROLE_DEFAULT_PERMISSIONS={
 'role-jbp-risk-admin':('audit.read','contact.read','conversion.read'),
 'role-jbp-org-readonly':('organization.read','team.read','user.read','account.read','source.read','campaign.read','touchpoint.read','attribution.read','conversion.read'),
 'role-jbp-ws-operator':('account.read','source.read','source.manage','campaign.read','campaign.manage','touchpoint.read','touchpoint.manage','attribution.read','contact.read','contact.update'),
 'role-jbp-ws-readonly':('source.read','source.path.read','campaign.read','touchpoint.read','attribution.read','conversion.read')}
ORGADMIN_210_2_6_PERMISSIONS=('organization.read','organization.manage','organization.structure.read','organization.structure.manage','team.read','team.manage','user.read','user.manage','role.read','role.manage','permission.read','account.read','account.manage','device.read','device.bind','device.disable','platform.read','audit.read')

SALES_SELF_COLLECTOR_PERMISSIONS=('collector.session.issue','collector.write','collector.account.resolve','collector.conversation.resolve','contact.create','contact.read.assigned','contact.update.assigned','conversation.read.self','message.read.self','transfer.create','contact.read','contact.update','team.read','account.read','source.read','source.path.read','campaign.read','touchpoint.read','attribution.read','contact.identity.link','contact.duplicate.review')

def _ensure_210_2_55_sales_collector_permissions(c):
 # Only the canonical built-in sales role is repaired; custom roles are never inferred by name.
 if not c.execute("SELECT 1 FROM roles WHERE role_id='role-jbp-sales-self' AND status='active'").fetchone():return 0
 missing=[k for k in SALES_SELF_COLLECTOR_PERMISSIONS if not c.execute('SELECT 1 FROM permissions WHERE permission_key=?',(k,)).fetchone()]
 if missing:raise RuntimeError('SALES_COLLECTOR_PERMISSION_CATALOG_MISSING:'+','.join(missing))
 before=c.total_changes
 for key in SALES_SELF_COLLECTOR_PERMISSIONS:c.execute("INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES('role-jbp-sales-self',?)",(key,))
 return c.total_changes-before

def ensure_v224_rbac_unification(c):
 checksum=hashlib.sha256(V224_RBAC_SIGNATURE.encode()).hexdigest();old=c.execute('SELECT checksum FROM schema_migrations WHERE migration_id=?',(V224_RBAC_MIGRATION_ID,)).fetchone()
 if old and old[0]!=checksum:raise RuntimeError('MIGRATION_CHECKSUM_MISMATCH: '+V224_RBAC_MIGRATION_ID)
 n=now_ms();existing={r[0] for r in c.execute('SELECT role_id FROM roles')}
 _ensure_210_2_55_sales_collector_permissions(c)
 # Complete missing P1 templates as global standards; existing role IDs and bindings remain untouched.
 for rid in ('role-jbp-risk-admin','role-jbp-org-readonly','role-jbp-ws-operator','role-jbp-ws-readonly'):
  name,code,scope,desc=STANDARD_ROLE_MAPPING[rid]
  if rid not in existing:c.execute("INSERT INTO roles(role_id,organization_id,name,scope_level,status,role_code,description,is_system) VALUES(?,NULL,?,?,'active',?,?,1)",(rid,name,scope,code,desc))
  else:c.execute('UPDATE roles SET name=?,scope_level=?,description=? WHERE role_id=?',(name,scope,desc,rid))
  for key in STANDARD_ROLE_DEFAULT_PERMISSIONS[rid]:
   if c.execute('SELECT 1 FROM permissions WHERE permission_key=?',(key,)).fetchone():c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',(rid,key))
 # Canonical standard codes are globally unique; custom copies keep generated role IDs as codes.
 for rid,(name,code,scope,desc) in STANDARD_ROLE_MAPPING.items():
  if c.execute('SELECT 1 FROM roles WHERE role_id=?',(rid,)).fetchone():c.execute('UPDATE roles SET name=?,role_code=?,scope_level=?,description=?,is_system=1 WHERE role_id=?',(name,code,scope,desc,rid))
 c.execute("UPDATE roles SET name='财务经办岗',role_code='finance_operator',scope_level='organization',description='只读查看现有经营与转化报表；不含退款、金额调整、会话正文或权限管理。',is_system=1 WHERE role_id='role-jbp-finance-operator'")
 c.execute("DELETE FROM role_permissions WHERE role_id='role-jbp-finance-operator'")
 for key in FINANCE_PERMISSIONS:
  if c.execute('SELECT 1 FROM permissions WHERE permission_key=?',(key,)).fetchone():c.execute("INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES('role-jbp-finance-operator',?)",(key,))
 c.execute("DELETE FROM role_permissions WHERE role_id='role_orgadmin'")
 for key in ORGADMIN_210_2_6_PERMISSIONS:
  if c.execute('SELECT 1 FROM permissions WHERE permission_key=?',(key,)).fetchone():c.execute("INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES('role_orgadmin',?)",(key,))
 # R6: sales-self is a business role, not a contact-only shell. All grants retain the binding's self scope.
 for key in ('collector.session.issue','collector.write','collector.account.resolve','collector.conversation.resolve','contact.create','contact.read.assigned','contact.update.assigned','conversation.read.self','message.read.self','transfer.create','contact.read','contact.update','team.read','account.read','source.read','source.path.read','campaign.read','touchpoint.read','attribution.read','contact.identity.link','contact.duplicate.review'):
  if c.execute('SELECT 1 FROM permissions WHERE permission_key=?',(key,)).fetchone():
   c.execute("INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES('role-jbp-sales-self',?)",(key,))
 c.execute("INSERT OR IGNORE INTO role_permissions(role_id,permission_key) SELECT 'role_superadmin',permission_key FROM permissions")
 if not old:c.execute('INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES(?,?,?,?,?,?)',(V224_RBAC_MIGRATION_ID,'210.2.6 权限范围统一与管理界面治理',checksum,n,'system',dumps({'status':'success','standardRoles':11})))

def backfill_v222_hotfix_permissions(path):
 """在可信 Schema 222 上幂等补齐 hotfix，并重建 210.0.6 消息时间索引。"""
 path=Path(path).resolve()
 # Full read-only validation; only exact hotfix grants and legacy time-index expressions are tolerated.
 validate_schema222_readonly(path,allow_missing_hotfix=True)
 c=_connect_strict_readonly(path)
 try:
  roles={r[0] for r in c.execute("SELECT role_id FROM roles WHERE role_id IN ('role_superadmin','role_orgadmin','role_teamlead')")}
  if roles!=set(V222_HOTFIX_GRANTS):raise RuntimeError('SCHEMA_222_INVALID: canonical roles')
 finally:c.close()
 c=sqlite3.connect(str(path),timeout=30,isolation_level=None);c.row_factory=sqlite3.Row
 try:
  c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=30000');c.execute('BEGIN IMMEDIATE')
  # 210.0.6: atomically replace legacy collected_at fallback indexes.
  c.execute('DROP INDEX IF EXISTS idx_messages_scope_conversation_time')
  c.execute('DROP INDEX IF EXISTS idx_messages_scope_contact_time')
  c.execute('CREATE INDEX idx_messages_scope_conversation_time ON conversation_messages(organization_id,workspace_id,team_id,conversation_id,occurred_at DESC,message_id DESC)')
  c.execute('CREATE INDEX idx_messages_scope_contact_time ON conversation_messages(organization_id,workspace_id,team_id,contact_id,occurred_at DESC,message_id DESC)')
  for key,description in V222_HOTFIX_PERMISSIONS.items():c.execute('INSERT OR IGNORE INTO permissions(permission_key,description) VALUES(?,?)',(key,description))
  for role,keys in V222_HOTFIX_GRANTS.items():
   for key in keys:c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',(role,key))
  _apply_210_1_stage_presets(c);ensure_v223_rbac_governance(c);ensure_v224_rbac_unification(c)
  c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('product_version',?)",(PRODUCT_VERSION,))
  # 210.2.55 normal-start self-heal; no external patch script and no custom-role mutation.
  added=_ensure_210_2_55_sales_collector_permissions(c)
  sig=hashlib.sha256(b'210.2.55 canonical sales-self collector permission baseline').hexdigest()
  c.execute("INSERT OR REPLACE INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES('V224_055_sales_collector_permissions','210.2.55 业务员新建客户与采集写入权限闭环',?,?,?,?)",(sig,now_ms(),'system',dumps({'status':'success','grantsAdded':added})))
  c.execute('COMMIT')
 except Exception:
  if c.in_transaction:c.execute('ROLLBACK')
  raise
 finally:c.close()
 validate_schema222_readonly(path)

def validate_schema222_readonly(path,allow_missing_hotfix=False):
 c=_connect_strict_readonly(path)
 try:
  version=c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
  if not version or str(version[0])!='222' or c.execute('PRAGMA user_version').fetchone()[0]!=222:raise RuntimeError('SCHEMA_222_INVALID: version')
  tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  required={'conversations','conversation_messages','contact_transfers','contact_transfer_events','audit_logs','follow_up_notifications','follow_up_notification_receipts'}
  if required-tables:raise RuntimeError('SCHEMA_222_INVALID: missing tables '+','.join(sorted(required-tables)))
  required_columns={'conversations':{'version','closed_at','archived_at','last_message_id','last_message_preview','message_count','inbound_count','outbound_count'},'conversation_messages':{'reply_to_message_id','attachment_count','has_sensitive_content','source_event_id','ingestion_version'},'contact_transfers':{'transfer_type','from_platform_id','to_platform_id','status','requested_by','idempotency_key','request_hash','version','match_evidence_json'},'contact_transfer_events':{'event_id','transfer_id','event_type','from_status','to_status','actor_id'}}
  for table,expected in required_columns.items():
   actual={x[1] for x in c.execute('PRAGMA table_info("'+table+'")')}
   if expected-actual:raise RuntimeError('SCHEMA_222_INVALID: '+table+' missing '+','.join(sorted(expected-actual)))
  indexes={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
  required_indexes={'idx_conversations_scope_activity','idx_messages_scope_conversation_time','idx_transfers_scope_status_time','uq_transfers_pending_target','idx_transfer_events_transfer_time','idx_follow_notifications_due','idx_follow_receipts_recipient'}
  if required_indexes-indexes:raise RuntimeError('SCHEMA_222_INVALID: indexes')
  for name,column in (('idx_messages_scope_conversation_time','conversation_id'),('idx_messages_scope_contact_time','contact_id')):
   row=c.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?",(name,)).fetchone();sql=(row[0] if row else '') or ''
   compact=re.sub(r'\s+','',sql.lower()).replace('\"','').replace('`','').replace('[','').replace(']','')
   prefix='createindex'+name+'onconversation_messages(organization_id,workspace_id,team_id,'+column+','
   canonical={prefix+'occurred_atdesc,message_iddesc)', 'createindexifnotexists'+name+'onconversation_messages(organization_id,workspace_id,'+column+',occurred_atdesc,message_iddesc)'}
   legacy={prefix+'coalesce(occurred_at,collected_at)desc,message_iddesc)', 'createindexifnotexists'+name+'onconversation_messages(organization_id,workspace_id,'+column+',coalesce(occurred_at,collected_at)desc,message_iddesc)'}
   if compact not in canonical and (not allow_missing_hotfix or compact not in legacy):raise RuntimeError('SCHEMA_222_INVALID: index semantics '+name)
  triggers={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
  required_triggers={'trg_transfer_scope_insert','trg_transfer_scope_update','trg_transfer_event_scope_insert','trg_transfer_event_scope_update'}
  if required_triggers-triggers:raise RuntimeError('SCHEMA_222_INVALID: triggers')
  seeded={r[0] for r in c.execute('SELECT permission_key FROM permissions WHERE permission_key IN ('+','.join('?' for _ in V222_PERMISSIONS)+')',tuple(V222_PERMISSIONS))}
  missing_permissions=set(V222_PERMISSIONS)-seeded
  sales_exists=bool(c.execute("SELECT 1 FROM roles WHERE role_id='role-jbp-sales-self' AND status='active'").fetchone())
  if sales_exists and not allow_missing_hotfix:
   actual_sales={r[0] for r in c.execute("SELECT permission_key FROM role_permissions WHERE role_id='role-jbp-sales-self'")}
   missing_sales=set(SALES_SELF_COLLECTOR_PERMISSIONS)-actual_sales
   if missing_sales:raise RuntimeError('SCHEMA_222_INVALID: sales collector grants '+','.join(sorted(missing_sales)))
  if missing_permissions and (not allow_missing_hotfix or missing_permissions-set(V222_HOTFIX_PERMISSIONS)):raise RuntimeError('SCHEMA_222_INVALID: permission seeds')
  required_grants={('role_superadmin',k) for k in V222_PERMISSIONS}|{(role,key) for role,keys in V222_HOTFIX_GRANTS.items() for key in keys if role!='role_orgadmin'}
  actual_grants={(r[0],r[1]) for r in c.execute("SELECT role_id,permission_key FROM role_permissions WHERE role_id IN ('role_superadmin','role_orgadmin','role_teamlead')")}
  missing_grants=required_grants-actual_grants
  allowed_missing={(role,key) for role,keys in V222_HOTFIX_GRANTS.items() for key in keys}
  if missing_grants and (not allow_missing_hotfix or missing_grants-allowed_missing):raise RuntimeError('SCHEMA_222_INVALID: administrator permission grants')
  expected=hashlib.sha256(V222_SIGNATURE.encode()).hexdigest();row=c.execute('SELECT checksum FROM schema_migrations WHERE migration_id=?',(V222_MIGRATION_ID,)).fetchone()
  if not row or row[0]!=expected:raise RuntimeError('SCHEMA_222_INVALID: migration checksum')
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('SCHEMA_222_INVALID: quick_check')
  if list(c.execute('PRAGMA foreign_key_check')):raise RuntimeError('SCHEMA_222_INVALID: foreign_key_check')
 finally:c.close()

def ensure_210_2_74_follow_up_schema(path):
 """Additive/idempotent repair for databases upgraded in place from 210.2.64-era builds."""
 path=Path(path).resolve();c=sqlite3.connect(str(path),timeout=30,isolation_level=None);c.row_factory=sqlite3.Row
 def exists(name):return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() is not None
 def cols(name):return {x[1] for x in c.execute("PRAGMA table_info('"+name+"')")}
 def add(table,name,definition):
  if name not in cols(table):c.execute('ALTER TABLE '+table+' ADD COLUMN '+name+' '+definition)
 try:
  c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=30000');c.execute('BEGIN IMMEDIATE')
  c.execute("""CREATE TABLE IF NOT EXISTS follow_up_notifications(
   notification_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,team_id TEXT,
   contact_id TEXT NOT NULL,owner_user_id TEXT,follow_up_at INTEGER NOT NULL,follow_up_reason TEXT NOT NULL DEFAULT '',
   customer_name TEXT NOT NULL DEFAULT '',platform_id TEXT,platform_code TEXT,platform_abbr TEXT,
   channel_account_id TEXT,channel_account_name TEXT,source_device_id TEXT,source_device_name TEXT,
   status TEXT NOT NULL DEFAULT 'scheduled' CHECK(status IN ('scheduled','due','overdue','completed','cancelled','superseded')),
   completed_at INTEGER,completed_by_user_id TEXT,completion_mode TEXT,completion_message_id TEXT,
   completion_evidence_json TEXT NOT NULL DEFAULT '{}',cancelled_at INTEGER,cancellation_reason TEXT,
   first_due_at INTEGER,last_scanned_at INTEGER,contact_version INTEGER NOT NULL DEFAULT 0,
   version INTEGER NOT NULL DEFAULT 1 CHECK(version>=1),created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
   UNIQUE(organization_id,contact_id,follow_up_at))""")
  c.execute("""CREATE TABLE IF NOT EXISTS follow_up_notification_receipts(
   receipt_id TEXT PRIMARY KEY,notification_id TEXT NOT NULL,organization_id TEXT NOT NULL,recipient_user_id TEXT NOT NULL,
   status TEXT NOT NULL DEFAULT 'unread' CHECK(status IN ('unread','alerted','read','snoozed','dismissed','closed')),
   first_alerted_at INTEGER,last_alerted_at INTEGER,next_alert_at INTEGER,alert_count INTEGER NOT NULL DEFAULT 0,
   read_at INTEGER,snooze_until INTEGER,dismissed_at INTEGER,claimed_by_consumer TEXT,claim_expires_at INTEGER,
   last_consumer_type TEXT,last_consumer_id TEXT,version INTEGER NOT NULL DEFAULT 1 CHECK(version>=1),
   created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,UNIQUE(notification_id,recipient_user_id))""")
  notification_columns={
   'team_id':'TEXT','owner_user_id':'TEXT','follow_up_reason':"TEXT NOT NULL DEFAULT ''",'customer_name':"TEXT NOT NULL DEFAULT ''",
   'platform_id':'TEXT','platform_code':'TEXT','platform_abbr':'TEXT','channel_account_id':'TEXT','channel_account_name':'TEXT',
   'source_device_id':'TEXT','source_device_name':'TEXT','status':"TEXT NOT NULL DEFAULT 'scheduled'",'completed_at':'INTEGER',
   'completed_by_user_id':'TEXT','completion_mode':'TEXT','completion_message_id':'TEXT','completion_evidence_json':"TEXT NOT NULL DEFAULT '{}'",
   'cancelled_at':'INTEGER','cancellation_reason':'TEXT','first_due_at':'INTEGER','last_scanned_at':'INTEGER',
   'contact_version':'INTEGER NOT NULL DEFAULT 0','version':'INTEGER NOT NULL DEFAULT 1','created_at':'INTEGER NOT NULL DEFAULT 0','updated_at':'INTEGER NOT NULL DEFAULT 0'}
  receipt_columns={'status':"TEXT NOT NULL DEFAULT 'unread'",'first_alerted_at':'INTEGER','last_alerted_at':'INTEGER','next_alert_at':'INTEGER',
   'alert_count':'INTEGER NOT NULL DEFAULT 0','read_at':'INTEGER','snooze_until':'INTEGER','dismissed_at':'INTEGER','claimed_by_consumer':'TEXT',
   'claim_expires_at':'INTEGER','last_consumer_type':'TEXT','last_consumer_id':'TEXT','version':'INTEGER NOT NULL DEFAULT 1',
   'created_at':'INTEGER NOT NULL DEFAULT 0','updated_at':'INTEGER NOT NULL DEFAULT 0'}
  for name,definition in notification_columns.items():add('follow_up_notifications',name,definition)
  for name,definition in receipt_columns.items():add('follow_up_notification_receipts',name,definition)
  required_n={'notification_id','organization_id','workspace_id','contact_id','follow_up_at'}|set(notification_columns)
  required_r={'receipt_id','notification_id','organization_id','recipient_user_id'}|set(receipt_columns)
  missing_n=required_n-cols('follow_up_notifications');missing_r=required_r-cols('follow_up_notification_receipts')
  if missing_n or missing_r:raise RuntimeError('FOLLOW_UP_SCHEMA_INVALID: notifications='+','.join(sorted(missing_n))+' receipts='+','.join(sorted(missing_r)))
  c.execute("CREATE INDEX IF NOT EXISTS idx_follow_notifications_due ON follow_up_notifications(organization_id,status,follow_up_at)")
  c.execute("CREATE INDEX IF NOT EXISTS idx_follow_notifications_contact ON follow_up_notifications(contact_id,status)")
  c.execute("CREATE INDEX IF NOT EXISTS idx_follow_receipts_recipient ON follow_up_notification_receipts(organization_id,recipient_user_id,status,next_alert_at)")
  c.execute("CREATE INDEX IF NOT EXISTS idx_follow_receipts_notification ON follow_up_notification_receipts(notification_id)")
  if exists('schema_migrations'):
   checksum=hashlib.sha256(b'210.2.74-follow-up-schema-additive-v2').hexdigest()
   c.execute("INSERT OR REPLACE INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES(?,?,?,?,?,?)",('V210_2_74_follow_up_schema','跟进时间旧库结构完整性修复',checksum,now_ms(),'system',dumps({'status':'ok','strategy':'additive-no-table-rebuild'})))
  c.execute('COMMIT')
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('FOLLOW_UP_SCHEMA_QUICK_CHECK_FAILED')
  fk=list(c.execute('PRAGMA foreign_key_check'))
  if fk:raise RuntimeError('FOLLOW_UP_SCHEMA_FOREIGN_KEY_CHECK_FAILED: '+str(len(fk)))
 except Exception:
  if c.in_transaction:c.execute('ROLLBACK')
  raise
 finally:c.close()

def ensure_210_2_72_notification_subscription_schema(path):
 """210.2.73: safely backfill notification-subscription schema for existing Schema 222 databases."""
 required={'admin_user_id','organization_id','owner_user_id','enabled','created_by','created_at','updated_at'}
 c=sqlite3.connect(str(path),timeout=30,isolation_level=None)
 try:
  c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=30000');c.execute('BEGIN IMMEDIATE')
  c.execute("""CREATE TABLE IF NOT EXISTS platform_admin_notification_subscriptions(
   admin_user_id TEXT NOT NULL,organization_id TEXT NOT NULL,owner_user_id TEXT NOT NULL,
   enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),created_by TEXT NOT NULL,
   created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
   PRIMARY KEY(admin_user_id,organization_id,owner_user_id),
   FOREIGN KEY(admin_user_id) REFERENCES users(user_id),
   FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
   FOREIGN KEY(owner_user_id) REFERENCES users(user_id),FOREIGN KEY(created_by) REFERENCES users(user_id))""")
  actual={row[1] for row in c.execute("PRAGMA table_info('platform_admin_notification_subscriptions')")}
  if not required.issubset(actual):raise RuntimeError('NOTIFICATION_SUBSCRIPTION_SCHEMA_INVALID: missing '+','.join(sorted(required-actual)))
  c.execute("CREATE INDEX IF NOT EXISTS idx_admin_notification_subscriptions_owner ON platform_admin_notification_subscriptions(organization_id,owner_user_id,enabled,admin_user_id)")
  if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone():
   checksum=hashlib.sha256(b'210.2.73-notification-subscription-schema-v1').hexdigest()
   c.execute("INSERT OR IGNORE INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json) VALUES(?,?,?,?,?,?)",('V210_2_72_notification_subscription_schema','通知代管旧库启动迁移',checksum,now_ms(),'system',dumps({'status':'ok','nonDestructive':True})))
  c.execute('COMMIT')
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('NOTIFICATION_SUBSCRIPTION_MIGRATION_QUICK_CHECK_FAILED')
 except Exception:
  if c.in_transaction:c.execute('ROLLBACK')
  raise
 finally:c.close()

class Database:
 def __init__(self,path):self.path=Path(path).resolve();self.path.parent.mkdir(parents=True,exist_ok=True)
 def connect(self):
  # Keep lock waits below the HTTP timeout. WAL still permits concurrent readers.
  c=sqlite3.connect(str(self.path),timeout=5,isolation_level=None,check_same_thread=False);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=5000');c.execute('PRAGMA journal_mode=WAL');return c
 @contextlib.contextmanager
 def tx(self,immediate=True):
  c=self.connect()
  try:
   c.execute('BEGIN IMMEDIATE' if immediate else 'BEGIN');yield c
   if c.in_transaction:c.execute('COMMIT')
  except Exception:
   # BEGIN may fail before a transaction exists; preserve the original error.
   if c.in_transaction:
    try:c.execute('ROLLBACK')
    except sqlite3.Error:pass
   raise
  finally:c.close()
 @contextlib.contextmanager
 def read(self):
  with self.tx(False) as c:yield c
 @contextlib.contextmanager
 def write(self):
  with self.tx(True) as c:yield c
 def initialize(self,bootstrap=None):
  """创建或校验全新 Schema 222 数据库。"""
  fresh=not self.path.exists() or not self.path.stat().st_size
  if not fresh:
   version=_read_existing_schema_version(self.path)
   if version=='222':
    ensure_210_2_74_follow_up_schema(self.path)
    ensure_210_2_72_notification_subscription_schema(self.path)
    backfill_v222_hotfix_permissions(self.path)
    return
   raise RuntimeError('SCHEMA_222_FRESH_INSTALL_REQUIRED: detected '+repr(version))
  b=validate_bootstrap(bootstrap);c=self.connect()
  try:
   c.execute('PRAGMA foreign_keys=OFF');c.execute('BEGIN IMMEDIATE')
   execute_sql_script(c,BASE_SCHEMA)
   ensure_v207(c,fresh=True);ensure_v207_1(c);ensure_v207_101(c);ensure_v207_200(c);ensure_v207_300(c);ensure_v207_301(c);ensure_v208(c);ensure_v209(c);ensure_v210(c);ensure_v211(c);ensure_v211_030(c);ensure_v211_040(c);ensure_v211_050(c);ensure_v212(c);ensure_v213(c);ensure_v214(c);ensure_v215(c);ensure_v216(c)
   bootstrap_fresh_database(c,b);ensure_v217(c);ensure_v218(c);ensure_v219(c);ensure_v220(c);ensure_v221(c);ensure_v222(c);_apply_210_1_stage_presets(c);ensure_v223_rbac_governance(c);ensure_v224_rbac_unification(c)
   c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version','222')");c.execute('PRAGMA user_version=222')
   c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('product_version',?)",(PRODUCT_VERSION,));c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('catalog_version',?)",(CATALOG_VERSION,));c.execute("DELETE FROM meta WHERE key='initial_admin_password'")
   qc=c.execute('PRAGMA quick_check').fetchone()[0]
   if qc!='ok':raise RuntimeError('PRAGMA quick_check 失败: '+str(qc))
   fk=list(c.execute('PRAGMA foreign_key_check'))
   if fk:raise RuntimeError('外键完整性检查失败，共 %d 项；数据库已回滚。'%len(fk))
   c.execute('COMMIT');c.execute('PRAGMA foreign_keys=ON')
  except Exception as exc:
   if c.in_transaction:c.execute('ROLLBACK')
   c.close();self.path.unlink(missing_ok=True);_write_failure_report(self.path,exc,None);raise
  finally:
   try:c.close()
   except Exception:pass
  ensure_210_2_74_follow_up_schema(self.path)
  ensure_210_2_72_notification_subscription_schema(self.path)
  validate_schema222_readonly(self.path)

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

# V211.0.1 更新说明（2026-09-22）：P1 扩展 - 渠道类型与来源类型独立字典表。
V211_030_MIGRATION_ID = 'V211_030_channel_and_source_types'
V211_030_SIGNATURE = 'channel_types,source_type_definitions,platform_id,channel_type_code,source_type_code'

def ensure_v211_030(c):
    """创建渠道类型和来源类型独立字典表。幂等迁移。"""
    checksum = hashlib.sha256(V211_030_SIGNATURE.encode()).hexdigest()
    old = c.execute("SELECT checksum FROM schema_migrations WHERE migration_id=?", (V211_030_MIGRATION_ID,)).fetchone()
    if old and old[0] != checksum:
        raise RuntimeError('MIGRATION_CHECKSUM_MISMATCH: ' + V211_030_MIGRATION_ID)

    # 渠道类型表
    c.execute("""
        CREATE TABLE IF NOT EXISTS channel_types(
            channel_type_id    TEXT PRIMARY KEY,
            platform_id        TEXT,
            channel_type_code  TEXT NOT NULL UNIQUE,
            name               TEXT NOT NULL,
            description        TEXT,
            direction          TEXT NOT NULL DEFAULT 'bidirectional'
                              CHECK(direction IN ('inbound','outbound','bidirectional')),
            is_active          INTEGER NOT NULL DEFAULT 1,
            sort_order         INTEGER NOT NULL DEFAULT 0,
            created_at         INTEGER NOT NULL,
            updated_at         INTEGER NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_channel_type_platform ON channel_types(platform_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_channel_type_active ON channel_types(is_active)")

    # 来源类型表
    c.execute("""
        CREATE TABLE IF NOT EXISTS source_type_definitions(
            source_type_id    TEXT PRIMARY KEY,
            source_type_code  TEXT NOT NULL UNIQUE,
            name              TEXT NOT NULL,
            description       TEXT,
            is_active         INTEGER NOT NULL DEFAULT 1,
            sort_order        INTEGER NOT NULL DEFAULT 0,
            created_at        INTEGER NOT NULL,
            updated_at        INTEGER NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_source_type_active ON source_type_definitions(is_active)")

    t = now_ms()
    if not old:
        # 插入预设渠道类型数据
        from setup.seed_dictionaries import CHANNEL_TYPES_SEED, ensure_dictionary_platforms, resolve_platform_id
        ensure_dictionary_platforms(c, t)
        for row in CHANNEL_TYPES_SEED:
            ct_id, platform_id, ct_code, name, desc, direction, sort_order = row
            c.execute("""
                INSERT OR IGNORE INTO channel_types
                (channel_type_id, platform_id, channel_type_code, name, description, direction, is_active, sort_order, created_at, updated_at)
                VALUES(?,?,?,?,?,?,1,?,?,?)
            """, (ct_id, resolve_platform_id(c, platform_id), ct_code, name, desc or '', direction, sort_order, t, t))

        # 插入预设来源类型数据
        from setup.seed_dictionaries import SOURCE_TYPES_SEED
        for row in SOURCE_TYPES_SEED:
            st_id, st_code, name, desc, sort_order = row
            c.execute("""
                INSERT OR IGNORE INTO source_type_definitions
                (source_type_id, source_type_code, name, description, is_active, sort_order, created_at, updated_at)
                VALUES(?,?,?,?,1,?,?,?)
            """, (st_id, st_code, name, desc or '', sort_order, t, t))

        c.execute("""
            INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json)
            VALUES(?,?,?,?,?,?)
        """, (
            V211_030_MIGRATION_ID,
            '渠道类型与来源类型独立字典表',
            checksum,
            t,
            'system',
            dumps({'status': 'success', 'channel_types': len(CHANNEL_TYPES_SEED), 'source_types': len(SOURCE_TYPES_SEED)})
        ))

# P3: sources 表添加 source_type_id 外键
V211_040_MIGRATION_ID = 'V211_040_sources_type_id'
V211_040_SIGNATURE = 'sources.source_type_id,FK:source_type_definitions'

def ensure_v211_040(c):
    """为 sources 表添加 source_type_id 外键。幂等迁移。"""
    checksum = hashlib.sha256(V211_040_SIGNATURE.encode()).hexdigest()
    old = c.execute("SELECT checksum FROM schema_migrations WHERE migration_id=?", (V211_040_MIGRATION_ID,)).fetchone()
    if old and old[0] != checksum:
        raise RuntimeError('MIGRATION_CHECKSUM_MISMATCH: ' + V211_040_MIGRATION_ID)
    
    # 检查列是否已存在
    cols = [r[1] for r in c.execute("PRAGMA table_info(sources)")]
    if 'source_type_id' in cols:
        if not old:
            t = now_ms()
            c.execute("""
                INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json)
                VALUES(?,?,?,?,?,?)
            """, (V211_040_MIGRATION_ID, 'sources表添加source_type_id外键', checksum, t, 'system', dumps({'status': 'skip', 'reason': 'column exists'})))
        return
    
    # 添加列并建立外键
    c.execute("ALTER TABLE sources ADD COLUMN source_type_id TEXT")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(source_type_id)")
    
    if not old:
        t = now_ms()
        c.execute("""
            INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json)
            VALUES(?,?,?,?,?,?)
        """, (V211_040_MIGRATION_ID, 'sources表添加source_type_id外键', checksum, t, 'system', dumps({'status': 'success'})))

# P4: source_touchpoints 添加 channel_type_id，campaigns 添加 business_line_id
V211_050_MIGRATION_ID = 'V211_050_touchpoints_campaigns_enhance'
V211_050_SIGNATURE = 'source_touchpoints.channel_type_id,campaigns.business_line_id,campaigns.market_id'

def ensure_v211_050(c):
    """为 source_touchpoints 和 campaigns 添加字典外键。幂等迁移。"""
    checksum = hashlib.sha256(V211_050_SIGNATURE.encode()).hexdigest()
    old = c.execute("SELECT checksum FROM schema_migrations WHERE migration_id=?", (V211_050_MIGRATION_ID,)).fetchone()
    if old and old[0] != checksum:
        raise RuntimeError('MIGRATION_CHECKSUM_MISMATCH: ' + V211_050_MIGRATION_ID)
    
    changed = []
    
    # 1. source_touchpoints 添加 channel_type_id
    tp_cols = [r[1] for r in c.execute("PRAGMA table_info(source_touchpoints)")]
    if 'channel_type_id' not in tp_cols:
        c.execute("ALTER TABLE source_touchpoints ADD COLUMN channel_type_id TEXT")
        c.execute("CREATE INDEX IF NOT EXISTS idx_touchpoints_channel_type ON source_touchpoints(channel_type_id)")
        changed.append('source_touchpoints.channel_type_id')
    
    # 2. campaigns 添加 business_line_id 和 market_id
    camp_cols = [r[1] for r in c.execute("PRAGMA table_info(campaigns)")]
    if 'business_line_id' not in camp_cols:
        c.execute("ALTER TABLE campaigns ADD COLUMN business_line_id TEXT")
        c.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_business_line ON campaigns(business_line_id)")
        changed.append('campaigns.business_line_id')
    if 'market_id' not in camp_cols:
        c.execute("ALTER TABLE campaigns ADD COLUMN market_id TEXT")
        c.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_market ON campaigns(market_id)")
        changed.append('campaigns.market_id')
    
    if not old:
        t = now_ms()
        c.execute("""
            INSERT INTO schema_migrations(migration_id,migration_name,checksum,applied_at,applied_by,result_json)
            VALUES(?,?,?,?,?,?)
        """, (V211_050_MIGRATION_ID, '触点渠道类型与活动业务线市场关联', checksum, t, 'system', dumps({'status': 'success', 'changed': changed})))

def ensure_v211_040_p2(c):
    """
    P2-1: platform_id 必填，channel 降级为兼容字段
    P2-2: 添加平台验证触发器
    """
    migration_id = 'v211-040-p2-platform-required'
    old = c.execute("SELECT 1 FROM schema_migrations WHERE migration_id=?", (migration_id,)).fetchone()
    if old:
        return
    
    t = now_ms()
    
    # 1. 确保所有平台已注册
    platforms_map = {
        'whatsapp': ('PLT-WHATSAPP', 'WHATSAPP', 'WhatsApp', 'messaging'),
        'instagram': ('PLT-INSTAGRAM', 'INSTAGRAM', 'Instagram', 'social'),
        'facebook': ('PLT-FACEBOOK', 'FACEBOOK', 'Facebook', 'social'),
        'messenger': ('PLT-MESSENGER', 'MESSENGER', 'Messenger', 'messaging'),
        'telegram': ('PLT-TELEGRAM', 'TELEGRAM', 'Telegram', 'messaging')
    }
    
    for channel, (platform_id, code, name, kind) in platforms_map.items():
        existing = c.execute("SELECT 1 FROM platforms WHERE platform_id=?", (platform_id,)).fetchone()
        if not existing:
            c.execute("""
                INSERT INTO platforms(platform_id, platform_code, platform_name, platform_kind, status, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?)
            """, (platform_id, code, name, kind, 'active', t, t))
    
    # 2. 迁移 channel_accounts.channel → platform_id
    accounts = c.execute("SELECT channel_account_id, channel, platform_id FROM channel_accounts").fetchall()
    migrated_count = 0
    for account_id, channel, current_platform_id in accounts:
        if not current_platform_id and channel in platforms_map:
            mapped_platform_id = platforms_map[channel][0]
            c.execute("UPDATE channel_accounts SET platform_id=?, updated_at=? WHERE channel_account_id=?",
                     (mapped_platform_id, t, account_id))
            migrated_count += 1
    
    # 3. 迁移 sources.platform_id（通过 channel_account_id 关联）
    sources_to_migrate = c.execute("""
        SELECT s.source_id, ca.platform_id
        FROM sources s
        LEFT JOIN channel_accounts ca ON s.channel_account_id = ca.channel_account_id
        WHERE s.platform_id IS NULL AND ca.platform_id IS NOT NULL
    """).fetchall()
    
    source_migrated = 0
    for source_id, platform_id in sources_to_migrate:
        c.execute("UPDATE sources SET platform_id=?, updated_at=? WHERE source_id=?",
                 (platform_id, t, source_id))
        source_migrated += 1
    
    # 4. 创建验证触发器
    c.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_channel_accounts_platform_required_insert
        BEFORE INSERT ON channel_accounts
        WHEN NEW.platform_id IS NULL
        BEGIN
            SELECT RAISE(ABORT, 'PLATFORM_ID_REQUIRED: platform_id is required for all channel accounts');
        END
    """)
    
    c.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_channel_accounts_platform_required_update
        BEFORE UPDATE ON channel_accounts
        WHEN NEW.platform_id IS NULL
        BEGIN
            SELECT RAISE(ABORT, 'PLATFORM_ID_REQUIRED: platform_id cannot be set to NULL');
        END
    """)
    
    c.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_channel_accounts_platform_valid_insert
        BEFORE INSERT ON channel_accounts
        WHEN NEW.platform_id IS NOT NULL
        BEGIN
            SELECT CASE 
                WHEN (SELECT COUNT(*) FROM platforms WHERE platform_id=NEW.platform_id AND status='active') = 0
                THEN RAISE(ABORT, 'INVALID_PLATFORM: platform_id does not exist or is inactive')
            END;
        END
    """)
    
    c.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_channel_accounts_platform_valid_update
        BEFORE UPDATE OF platform_id ON channel_accounts
        WHEN NEW.platform_id IS NOT NULL
        BEGIN
            SELECT CASE 
                WHEN (SELECT COUNT(*) FROM platforms WHERE platform_id=NEW.platform_id AND status='active') = 0
                THEN RAISE(ABORT, 'INVALID_PLATFORM: platform_id does not exist or is inactive')
            END;
        END
    """)
    
    # 5. 记录迁移
    c.execute("""
        INSERT INTO schema_migrations(migration_id, migration_name, checksum, applied_at, applied_by, result_json)
        VALUES(?,?,?,?,?,?)
    """, (
        migration_id,
        'P2: Platform ID required, channel field legacy',
        'sha256:p2-platform-migration-v1',
        t,
        'system',
        dumps({'accounts_migrated': migrated_count, 'sources_migrated': source_migrated, 'triggers_created': 4})
    ))
