#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepare or validate a dedicated, fresh Schema 222 database."""
import argparse,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from V207_shared_db import Database,backfill_v222_hotfix_permissions,validate_schema222_readonly
DEFAULT_DB=Path(r'I:\jubaopen_data\jubaopen-v208-schema222.db')
def detected_version(path):
 if not path.exists() or path.stat().st_size==0:return 'fresh'
 try:
  con=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
  try:
   row=con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone();return str(row[0]) if row else None
  finally:con.close()
 except sqlite3.Error:return None
def main():
 ap=argparse.ArgumentParser(description='创建或验证全新 Schema 222 数据库；不迁移旧数据库。')
 ap.add_argument('--db',default=str(DEFAULT_DB));ap.add_argument('--bootstrap',help='初始化 JSON 文件；新建数据库时必需')
 args=ap.parse_args();target=Path(args.db).expanduser().resolve();target.parent.mkdir(parents=True,exist_ok=True);version=detected_version(target)
 if version=='222':backfill_v222_hotfix_permissions(target);validate_schema222_readonly(target);print('Schema 222 数据库校验通过：'+str(target));return 0
 if version!='fresh':raise RuntimeError('仅支持全新 Schema 222 初始化；检测到旧版或未知数据库 '+repr(version)+'，原文件未修改：'+str(target))
 if not args.bootstrap:raise RuntimeError('创建新数据库必须提供 --bootstrap JSON，避免生成未知管理员凭据')
 bootstrap=json.loads(Path(args.bootstrap).read_text('utf-8'));Database(target).initialize(bootstrap);validate_schema222_readonly(target)
 print('Schema 222 数据库创建并校验通过：'+str(target));return 0
if __name__=='__main__':
 try:raise SystemExit(main())
 except Exception as exc:print('数据库准备失败：'+str(exc),file=sys.stderr);raise SystemExit(1)
