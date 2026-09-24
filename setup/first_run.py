#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Jubaopen V208.1.7 first-run initialization and P1 preset seeding."""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from V207_shared_db import Database
from setup.seed_organization import seed_p1


def main():
    parser = argparse.ArgumentParser(description="Initialize Jubaopen V208.1.7")
    parser.add_argument('--db', default=str(ROOT / 'data' / 'jubaopen-v208.db'))
    parser.add_argument('--admin-password', default=os.environ.get('JUBAOPEN_INITIAL_ADMIN_PASSWORD'))
    args = parser.parse_args()
    db_path = Path(args.db).expanduser().resolve()

    # Protect an existing database: first-run never overwrites or reseeds it.
    if db_path.exists() and db_path.stat().st_size:
        print('数据库已存在，跳过首次初始化：' + str(db_path))
        return 0
    if not args.admin_password:
        raise RuntimeError('首次初始化必须通过 --admin-password 或 JUBAOPEN_INITIAL_ADMIN_PASSWORD 提供强密码')

    db_path.parent.mkdir(parents=True, exist_ok=True)
    Database(db_path).initialize({'admin_password': args.admin_password, 'builtin_default': '0'})
    seed_p1(str(db_path), 'jubaopen')
    print('初始化完成：' + str(db_path))
    print('企业 ID：jubaopen')
    print('管理员：admin')
    print('预制用户临时密码：jubaopen518518')
    print('首次登录必须修改密码。')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('初始化失败：' + str(exc), file=sys.stderr)
        raise SystemExit(1)
