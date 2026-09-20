#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Jubaopen V207.7 安全无交互首次初始化。"""
import argparse,sys,os
from pathlib import Path
ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from V207_shared_db import Database

def main():
 p=argparse.ArgumentParser(description="初始化 Jubaopen V207.7 默认组织和平台管理员")
 p.add_argument('--db',default=str(ROOT/'data'/'jubaopen-v207.db'))
 p.add_argument('--admin-password',default=os.environ.get('JUBAOPEN_INITIAL_ADMIN_PASSWORD'),help='初始管理员密码；也可使用 JUBAOPEN_INITIAL_ADMIN_PASSWORD')
 a=p.parse_args();db=Path(a.db).expanduser().resolve()
 if db.exists() and db.stat().st_size:
  print('数据库已存在，跳过首次初始化：'+str(db));return 0
 if not a.admin_password:raise RuntimeError('首次初始化必须通过 --admin-password 或 JUBAOPEN_INITIAL_ADMIN_PASSWORD 提供强密码')
 db.parent.mkdir(parents=True,exist_ok=True);Database(db).initialize({'admin_password':a.admin_password,'builtin_default':'0'})
 print('初始化完成：'+str(db));print('企业 ID：jubaopen');print('管理员：admin');print('首次登录必须修改密码。');return 0
if __name__=='__main__':
 try:raise SystemExit(main())
 except Exception as e:print('初始化失败：'+str(e),file=sys.stderr);raise SystemExit(1)
