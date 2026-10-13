#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JubaOpen read-only release gate (live product version / Schema 222)."""
import argparse,hashlib,json,re,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from V207_shared_db import Database,validate_schema222_readonly,V222_MIGRATION_ID,V222_SIGNATURE
from V207_schema_catalog import build_schema_catalog
from V207_version import SCHEMA_VERSION,PRODUCT_VERSION
ZH=re.compile(r'[\u4e00-\u9fff]')
TABLES={'whatsapp_identity_links','conversation_external_aliases','contact_team_access','contact_match_reviews','contact_merge_history','contact_transfers','contact_transfer_events'}
INDEXES={'uq_direct_conversation_account_contact','idx_conversation_alias_contact','uq_message_external','uq_message_client_event','idx_messages_conversation_time','idx_messages_contact_time','idx_messages_team_time','idx_transfers_scope_status_time','idx_transfers_contact_time','idx_transfer_events_transfer_time','uq_transfers_pending_target'}
TRIGGERS={'trg_message_scope_insert':'MESSAGE_SCOPE_MISMATCH','trg_message_scope_update':'MESSAGE_SCOPE_MISMATCH','trg_conversation_scope_insert':'CONVERSATION_SCOPE_MISMATCH','trg_conversation_scope_update':'CONVERSATION_SCOPE_MISMATCH','trg_contact_team_access_insert':'CONTACT_TEAM_ACCESS_SCOPE_MISMATCH','trg_transfer_scope_insert':'TRANSFER_SCOPE_MISMATCH','trg_transfer_scope_update':'TRANSFER_SCOPE_MISMATCH','trg_transfer_event_scope_insert':'TRANSFER_EVENT_SCOPE_MISMATCH','trg_transfer_event_scope_update':'TRANSFER_EVENT_SCOPE_MISMATCH'}
def meta(path):
 out={'schema222Validator':False,'missingTables':[],'missingIndexes':[],'invalidTriggers':[],'migrationChecksum':False,'metaPlatforms':[]}
 try:validate_schema222_readonly(path);out['schema222Validator']=True
 except Exception as e:out['schema222Error']=str(e)
 c=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
 try:
  names=lambda typ:{x[0] for x in c.execute('SELECT name FROM sqlite_master WHERE type=?',(typ,))}
  out['missingTables']=sorted(TABLES-names('table'));out['missingIndexes']=sorted(INDEXES-names('index'))
  for n,token in TRIGGERS.items():
   row=c.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",(n,)).fetchone()
   if not row or token not in (row[0] or ''):out['invalidTriggers'].append(n)
  out['metaPlatforms']=sorted(x[0] for x in c.execute("SELECT platform_code FROM platforms WHERE platform_code IN ('facebook','instagram','messenger') AND status='active'"))
  row=c.execute('SELECT checksum FROM schema_migrations WHERE migration_id=?',(V222_MIGRATION_ID,)).fetchone();expected=hashlib.sha256(V222_SIGNATURE.encode()).hexdigest();out['migrationChecksum']=bool(row and row[0]==expected);out['expectedChecksum']=expected;out['actualChecksum']=row[0] if row else None
 finally:c.close()
 out['ok']=out['schema222Validator'] and not out['missingTables'] and not out['missingIndexes'] and not out['invalidTriggers'] and out['migrationChecksum'] and out['metaPlatforms']==['facebook','instagram','messenger'];return out
def main():
 a=argparse.ArgumentParser();a.add_argument('--db',required=True);a.add_argument('--skip-documentation',action='store_true');x=a.parse_args();catalog=build_schema_catalog(Database(x.db));objs=catalog['tables']
 bt=[t['name'] for t in objs if not t['documented'] or not ZH.search(t['label']) or not ZH.search(t['purpose']) or '暂无' in t['purpose']]
 bf=[t['name']+'.'+f['name'] for t in objs for f in t['fields'] if f['label']==f['name'] or not ZH.search(f['label']) or not ZH.search(f['description']) or '暂无' in f['description']]
 m=meta(x.db);docs=x.skip_documentation or not(bt or bf);ok=str(catalog.get('schemaVersion'))==str(SCHEMA_VERSION)=='222' and docs and catalog['integrity']['quickCheck']=='ok' and not catalog['integrity']['foreignKeyIssues'] and m['ok']
 out={'ok':ok,'expectedSchemaVersion':SCHEMA_VERSION,'schemaVersion':catalog.get('schemaVersion'),'productVersion':PRODUCT_VERSION,'tableCount':sum(o['objectType']=='table' for o in objs),'viewCount':sum(o['objectType']=='view' for o in objs),'totalFieldCount':sum(o['fieldCount'] for o in objs),'badTables':bt,'badFields':bf,'quickCheck':catalog['integrity']['quickCheck'],'foreignKeyIssueCount':len(catalog['integrity']['foreignKeyIssues']),'documentationCoverage':catalog['summary']['documentationCoverage'],'documentationSkipped':x.skip_documentation,'meta':m};print(json.dumps(out,ensure_ascii=False,indent=2));return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
