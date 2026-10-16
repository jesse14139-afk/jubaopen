import sqlite3,tempfile,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from V207_shared_db import Database
with tempfile.TemporaryDirectory() as d:
 db=Database(Path(d)/'test.db')
 with db.write() as c:c.execute('CREATE TABLE t(id INTEGER PRIMARY KEY,v TEXT)')
 try:
  with db.write() as c:c.execute("INSERT INTO t(v) VALUES('rollback')");raise RuntimeError('expected')
 except RuntimeError:pass
 with db.read() as c:assert c.execute('SELECT count(*) FROM t').fetchone()[0]==0
 holder=db.connect();holder.execute('BEGIN IMMEDIATE')
 try:
  try:
   with db.write() as c:c.execute("INSERT INTO t(v) VALUES('blocked')")
  except sqlite3.OperationalError as e:assert 'locked' in str(e).lower() and 'rollback' not in str(e).lower(),str(e)
  else:raise AssertionError('lock expected')
 finally:holder.execute('ROLLBACK');holder.close()
print('db concurrency hotfix tests: PASS')
