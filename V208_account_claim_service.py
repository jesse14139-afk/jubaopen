# -*- coding: utf-8 -*-
"""Schema 214 account identity discovery and conservative slot auto-claim domain service."""
import uuid
from V207_shared_db import now_ms,dumps
from V208_identity import normalize_identity


def _dict(row): return dict(row) if row else None


def record_discovery_in_tx(c,a,platform,identity_type,raw_value,canonical,status='pending',reason_code=None,slot_id=None,channel_account_id=None):
 n=now_ms(); did='acd_'+uuid.uuid4().hex
 c.execute("""INSERT INTO account_identity_discoveries(
  discovery_id,organization_id,workspace_id,team_id,user_id,platform_id,identity_type,canonical_value,identity_value,
  auxiliary_json,device_id,plugin_session_id,slot_id,channel_account_id,status,reason_code,first_seen_at,last_seen_at)
  VALUES(?,?,?,?,?,?,?,?,?,'{}',?,?,?,?,?,?,?,?)
  ON CONFLICT(organization_id,user_id,platform_id,identity_type,canonical_value) DO UPDATE SET
   workspace_id=excluded.workspace_id,team_id=excluded.team_id,identity_value=excluded.identity_value,
   device_id=excluded.device_id,plugin_session_id=excluded.plugin_session_id,last_seen_at=excluded.last_seen_at,
   slot_id=COALESCE(excluded.slot_id,account_identity_discoveries.slot_id),
   channel_account_id=COALESCE(excluded.channel_account_id,account_identity_discoveries.channel_account_id),
   status=CASE WHEN account_identity_discoveries.status IN ('approved','auto_claimed') THEN account_identity_discoveries.status ELSE excluded.status END,
   reason_code=CASE WHEN account_identity_discoveries.status IN ('approved','auto_claimed') THEN account_identity_discoveries.reason_code ELSE excluded.reason_code END""",
  (did,a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'],platform['platform_id'],identity_type,canonical,raw_value,
   a.get('device_id'),a.get('plugin_session_id'),slot_id,channel_account_id,status,reason_code,n,n))
 return _dict(c.execute("""SELECT * FROM account_identity_discoveries WHERE organization_id=? AND user_id=? AND platform_id=? AND identity_type=? AND canonical_value=?""",
  (a['organization_id'],a['user_id'],platform['platform_id'],identity_type,canonical)).fetchone())


def _scope_valid(c,a,slot):
 if any(slot[k]!=a[k] for k in ('organization_id','workspace_id','team_id','user_id')): return False
 member=c.execute("SELECT 1 FROM team_memberships WHERE user_id=? AND team_id=? AND status='active'",(a['user_id'],a['team_id'])).fetchone()
 admin=c.execute("SELECT 1 FROM platform_administrators WHERE user_id=?",(a['user_id'],)).fetchone()
 workspace=c.execute("SELECT 1 FROM workspaces WHERE workspace_id=? AND organization_id=? AND status='active'",(a['workspace_id'],a['organization_id'])).fetchone()
 team=c.execute("SELECT workspace_id FROM teams WHERE team_id=? AND organization_id=? AND status='active'",(a['team_id'],a['organization_id'])).fetchone()
 relation=c.execute("SELECT 1 FROM workspace_teams WHERE workspace_id=? AND team_id=? AND organization_id=? AND status='active'",(a['workspace_id'],a['team_id'],a['organization_id'])).fetchone()
 direct=bool(team and team['workspace_id']==a['workspace_id'])
 return bool((member or admin) and workspace and team and (direct or relation))


def _expectation_matches(platform_code,slot,identity_type,raw_value,canonical):
 phone=str(slot['expected_phone'] or '').strip()
 username=str(slot['expected_username'] or '').strip()
 if phone:
  _,_,expected=normalize_identity(platform_code,'phone' if platform_code=='telegram' else 'whatsapp_jid',phone)
  if not expected or expected!=canonical:return False
 if username:
  _,_,expected=normalize_identity(platform_code,'telegram_username' if platform_code=='telegram' else 'username',username)
  if not expected or expected!=canonical:return False
 return True


def discover_or_auto_claim_in_tx(c,a,platform,identity_type,raw_value,canonical,existing_account_id=None):
 """Return outcome=claimed|pending|conflict. Caller owns the write transaction."""
 slots=c.execute("""SELECT * FROM account_binding_slots WHERE organization_id=? AND workspace_id=? AND team_id=? AND user_id=? AND platform_id=? AND status='pending' ORDER BY created_at,slot_id LIMIT 2""",
  (a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'],platform['platform_id'])).fetchall()
 if len(slots)!=1:
  reason='no_binding_slot' if not slots else 'multiple_binding_slots'
  d=record_discovery_in_tx(c,a,platform,identity_type,raw_value,canonical,'pending',reason)
  return {'outcome':'pending','reason':reason,'discovery':d}
 slot=slots[0]; sid=slot['slot_id']; aid=slot['channel_account_id']
 if slot['claim_policy']!='auto' or not aid:
  reason='approval_required' if slot['claim_policy']=='approval' else 'slot_account_required'
  d=record_discovery_in_tx(c,a,platform,identity_type,raw_value,canonical,'pending',reason,sid,aid)
  return {'outcome':'pending','reason':reason,'discovery':d}
 if existing_account_id and existing_account_id!=aid:
  d=record_discovery_in_tx(c,a,platform,identity_type,raw_value,canonical,'conflict','slot_account_mismatch',sid,aid)
  return {'outcome':'conflict','reason':'slot_account_mismatch','discovery':d}
 if not _scope_valid(c,a,slot) or not _expectation_matches(platform['platform_code'],slot,identity_type,raw_value,canonical):
  reason='slot_scope_invalid' if not _scope_valid(c,a,slot) else 'slot_expectation_mismatch'
  d=record_discovery_in_tx(c,a,platform,identity_type,raw_value,canonical,'pending',reason,sid,aid)
  return {'outcome':'pending','reason':reason,'discovery':d}
 account=c.execute("""SELECT * FROM channel_accounts WHERE channel_account_id=? AND organization_id=? AND platform_id=? AND status='active' AND collection_enabled=1""",
  (aid,a['organization_id'],platform['platform_id'])).fetchone()
 if not account:
  d=record_discovery_in_tx(c,a,platform,identity_type,raw_value,canonical,'pending','slot_account_invalid',sid,aid)
  return {'outcome':'pending','reason':'slot_account_invalid','discovery':d}
 conflicts=c.execute("""SELECT DISTINCT i.channel_account_id FROM channel_account_identities i
 JOIN channel_accounts ca ON ca.channel_account_id=i.channel_account_id
 WHERE ca.organization_id=? AND ca.platform_id=? AND ca.status='active'
 AND i.platform_id=? AND i.identity_type=? AND i.canonical_value=? AND i.status='active' AND i.channel_account_id<>?""",
  (a['organization_id'],platform['platform_id'],platform['platform_id'],identity_type,canonical,aid)).fetchall()
 if conflicts:
  d=record_discovery_in_tx(c,a,platform,identity_type,raw_value,canonical,'conflict','identity_conflict',sid,aid)
  return {'outcome':'conflict','reason':'identity_conflict','matches':len(conflicts)+1,'discovery':d}
 n=now_ms()
 changed=c.execute("""UPDATE account_binding_slots SET status='claimed',claimed_identity_type=?,claimed_canonical_value=?,claimed_device_id=?,claimed_at=?,updated_at=? WHERE slot_id=? AND organization_id=? AND workspace_id=? AND team_id=? AND user_id=? AND platform_id=? AND status='pending'""",
  (identity_type,canonical,a.get('device_id'),n,n,sid,a['organization_id'],a['workspace_id'],a['team_id'],a['user_id'],platform['platform_id'])).rowcount
 if changed!=1:
  d=record_discovery_in_tx(c,a,platform,identity_type,raw_value,canonical,'pending','slot_claim_race',sid,aid)
  return {'outcome':'pending','reason':'slot_claim_race','discovery':d}
 old=c.execute("SELECT identity_id FROM channel_account_identities WHERE channel_account_id=? AND identity_type=? AND canonical_value=?",(aid,identity_type,canonical)).fetchone()
 if old:
  c.execute("UPDATE channel_account_identities SET platform_id=?,identity_value=?,status='active',valid_to=NULL WHERE identity_id=?",(platform['platform_id'],raw_value,old['identity_id']))
 else:
  c.execute("""INSERT INTO channel_account_identities(identity_id,channel_account_id,identity_type,identity_value,canonical_value,created_at,platform_id,is_primary,status,valid_from,metadata_json) VALUES(?,?,?,?,?,?,?,1,'active',?,'{}')""",
   ('cai_'+uuid.uuid4().hex,aid,identity_type,raw_value,canonical,n,platform['platform_id'],n))
 c.execute("INSERT OR IGNORE INTO team_channel_accounts(team_id,channel_account_id,granted_by,granted_at) VALUES(?,?,?,?)",(a['team_id'],aid,a['user_id'],n))
 c.execute("INSERT OR IGNORE INTO user_channel_account_grants(user_id,channel_account_id,permission_scope,granted_by,granted_at) VALUES(?,?,'use',?,?)",(a['user_id'],aid,a['user_id'],n))
 d=record_discovery_in_tx(c,a,platform,identity_type,raw_value,canonical,'auto_claimed','unique_auto_slot',sid,aid)
 c.execute("UPDATE account_identity_discoveries SET resolved_at=?,resolved_by=?,resolution_reason=? WHERE discovery_id=?",(n,a['user_id'],'unique_auto_slot',d['discovery_id']))
 c.execute("""INSERT INTO audit_logs(workspace_id,actor_id,device_id,operation,entity_type,entity_id,before_json,after_json,reason,created_at,organization_id,team_id,scope_type,scope_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
  (a['workspace_id'],a['user_id'],a.get('device_id'),'auto_claim','account_binding_slot',sid,'{}',dumps({'channelAccountId':aid,'identityType':identity_type,'canonicalValue':canonical}),'唯一自动槽位认领',n,a['organization_id'],a['team_id'],'team',a['team_id']))
 return {'outcome':'claimed','reason':'unique_auto_slot','account':_dict(account),'slotId':sid,'discovery':d}
