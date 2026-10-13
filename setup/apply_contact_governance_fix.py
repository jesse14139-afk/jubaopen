# -*- coding: utf-8 -*-
import sqlite3,sys,time,shutil,json,os
DDL="""CREATE TABLE IF NOT EXISTS contact_merge_requests(request_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,workspace_id TEXT NOT NULL,target_contact_id TEXT NOT NULL,source_contact_id TEXT NOT NULL,requested_by TEXT NOT NULL,requested_team_id TEXT,reason TEXT NOT NULL,evidence_json TEXT NOT NULL DEFAULT '{}',suggested_resolution_json TEXT NOT NULL DEFAULT '{}',status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','executing','rejected','merged','failed','cancelled')),target_version INTEGER NOT NULL,source_version INTEGER NOT NULL,reviewed_by TEXT,reviewed_at INTEGER,review_comment TEXT NOT NULL DEFAULT '',executed_merge_id TEXT,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);CREATE INDEX IF NOT EXISTS idx_merge_requests_queue ON contact_merge_requests(organization_id,status,workspace_id,updated_at);CREATE UNIQUE INDEX IF NOT EXISTS uq_merge_request_pending_pair ON contact_merge_requests(organization_id,workspace_id,target_contact_id,source_contact_id) WHERE status='pending';CREATE TABLE IF NOT EXISTS contact_merge_request_events(event_id TEXT PRIMARY KEY,request_id TEXT NOT NULL,event_type TEXT NOT NULL,actor_id TEXT NOT NULL,detail_json TEXT NOT NULL DEFAULT '{}',created_at INTEGER NOT NULL);CREATE INDEX IF NOT EXISTS idx_merge_request_events ON contact_merge_request_events(request_id,created_at);"""
def apply(db):
 db=os.path.abspath(db);backup=db+'.pre-210.2.24-'+time.strftime('%Y%m%d%H%M%S')+'.bak';shutil.copy2(db,backup);c=sqlite3.connect(db)
 try:
  c.execute('PRAGMA foreign_keys=ON');c.executescript(DDL)
  cols=lambda t:{r[1] for r in c.execute('PRAGMA table_info('+t+')')}
  need={'contact_merge_requests':{'request_id','organization_id','workspace_id','target_contact_id','source_contact_id','requested_by','status','target_version','source_version'},'contact_merge_request_events':{'event_id','request_id','event_type','actor_id','detail_json','created_at'}}
  for t,n in need.items():
   miss=n-cols(t)
   if miss:raise RuntimeError('数据库表结构不兼容：'+t+' 缺少 '+','.join(sorted(miss)))
  for k,d,a,risk in [('contact.merge.request','申请合并客户','merge.request','high'),('contact.merge.review','审批合并申请','merge.review','critical')]:c.execute('INSERT OR IGNORE INTO permissions(permission_key,description,display_name,resource,action,scope_mask,risk_level) VALUES(?,?,?,?,?,63,?)',(k,d,d,'contact',a,risk))
  roles={r[0] for r in c.execute('SELECT role_id FROM roles')}
  admins={r[0] for r in c.execute("SELECT DISTINCT role_id FROM role_permissions WHERE permission_key IN ('system.manage','organization.manage')")}|(roles&{'role_superadmin','role_orgadmin'})
  leads={r[0] for r in c.execute("SELECT DISTINCT role_id FROM role_permissions WHERE permission_key IN ('team.manage','contact.duplicate.review')")}|(roles&{'role_teamlead','role-jbp-teamlead'})
  workers={r[0] for r in c.execute("SELECT DISTINCT role_id FROM role_permissions WHERE permission_key IN ('contact.update.assigned','contact.read.assigned')")}|(roles&{'role_operator','role_sales','role-jbp-sales-self'})
  for role in admins|leads:
   for k in ('contact.identity.link','contact.merge.request','contact.merge.review','contact.merge'):c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',(role,k))
  for role in workers-(admins|leads):
   for k in ('contact.identity.link','contact.merge.request'):c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)',(role,k))
  c.commit()
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('quick_check 未通过')
  fk=list(c.execute('PRAGMA foreign_key_check'))
  if fk:raise RuntimeError('foreign_key_check 未通过')
  result={'ok':True,'backup':backup,'workerRoles':sorted(workers-(admins|leads)),'reviewRoles':sorted(admins|leads)};print(json.dumps(result,ensure_ascii=False));return result
 except Exception:
  c.rollback();c.close();shutil.copy2(backup,db);raise
 finally:
  try:c.close()
  except:pass
if __name__=='__main__':
 if len(sys.argv)!=2:raise SystemExit('用法：python apply_contact_governance_fix.py 数据库路径')
 apply(sys.argv[1])
