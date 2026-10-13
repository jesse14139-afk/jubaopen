#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained release gate; no packaged test fixtures required."""
from pathlib import Path
import subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from V207_shared_db import Database,validate_schema222_readonly

def run(args,token=None):
 p=subprocess.run(args,cwd=ROOT,capture_output=True,text=True)
 s=(p.stdout or '')+(p.stderr or '')
 if p.returncode or (token and token not in s):raise RuntimeError(' '.join(map(str,args))+'\n'+s)
 print(s.strip())

def main():
 with tempfile.TemporaryDirectory(prefix='jubaopen-gate-') as d:
  db=Path(d)/'schema222.sqlite3'
  Database(db).initialize({'admin_password':'UnifiedGate!Schema222'})
  validate_schema222_readonly(db)
  if Database(db).quick_check()!='ok':raise RuntimeError('Schema 222 quick_check failed')
  if Database(db).foreign_key_check():raise RuntimeError('Schema 222 foreign_key_check failed')
  run([sys.executable,str(ROOT/'setup/release_gate.py'),'--db',str(db)],'"ok": true')
  run([sys.executable,str(ROOT/'setup/test_whatsapp_identity_v210_1_11.py')],'WHATSAPP_IDENTITY_V210_1_11_OK')
  run([sys.executable,str(ROOT/'setup/test_whatsapp_v210_1_13.py')],'WHATSAPP_V210_1_13_REGRESSION_OK')
  run([sys.executable,str(ROOT/'setup/test_whatsapp_followup_v210_1_13.py')],'WHATSAPP_FOLLOWUP_V210_1_13_SECURITY_OK')
 print('UNIFIED_RELEASE_GATE_OK')
if __name__=='__main__':main()
