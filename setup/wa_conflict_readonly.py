#!/usr/bin/env python3
"""Local authorized-admin read-only lookup. Never prints message bodies."""
import argparse,sqlite3,json,hashlib
from pathlib import Path

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',required=True);p.add_argument('--organization',required=True);p.add_argument('--account',required=True);p.add_argument('--fingerprint',required=True);args=p.parse_args()
 if len(args.fingerprint)!=16 or any(x not in '0123456789abcdef' for x in args.fingerprint):p.error('fingerprint must be 16 lowercase hex characters')
 db=Path(args.db).resolve()
 if not db.is_file():p.error('database file does not exist')
 c=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
 try:
  c.execute('PRAGMA query_only=ON')
  out=[]
  rows=c.execute('SELECT message_id,conversation_id,external_message_id,client_event_id,direction,occurred_at,deleted_at FROM conversation_messages WHERE organization_id=? AND channel_account_id=?',(args.organization,args.account))
  for row in rows:
   fingerprints={hashlib.sha256(str(row[k]).encode()).hexdigest()[:16] for k in ('external_message_id','client_event_id') if row[k]}
   if args.fingerprint in fingerprints:out.append({k:row[k] for k in ('message_id','conversation_id','direction','occurred_at','deleted_at')})
  print(json.dumps({'readOnly':True,'matches':out},ensure_ascii=False,indent=2))
 finally:c.close()
if __name__=='__main__':main()
