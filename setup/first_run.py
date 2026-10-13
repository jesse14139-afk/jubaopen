#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Initialize a fresh JubaOpen 208.9.0 / Schema 222 installation."""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from V207_shared_db import Database
from setup.seed_organization import seed_p1

DEFAULT_DB = Path(r'I:\jubaopen_data\jubaopen-v208-schema222.db')

def main():
    parser = argparse.ArgumentParser(description='Initialize JubaOpen 208.9.0 / Schema 222')
    parser.add_argument('--db', default=str(DEFAULT_DB))
    parser.add_argument('--admin-password', default=os.environ.get('JUBAOPEN_INITIAL_ADMIN_PASSWORD'))
    args = parser.parse_args()
    db_path = Path(args.db).expanduser().resolve()
    if db_path.exists():
        raise RuntimeError('仅支持全新部署：目标数据库已存在，请删除 data 目录后重试')
    if not args.admin_password:
        raise RuntimeError('首次初始化必须通过 --admin-password 或 JUBAOPEN_INITIAL_ADMIN_PASSWORD 提供强密码')
    db_path.parent.mkdir(parents=True, exist_ok=True)
    Database(db_path).initialize({'admin_password': args.admin_password, 'builtin_default': '0'})
    print('基础数据库初始化完成：' + str(db_path))
    seed_p1(str(db_path), 'jubaopen')
    print('全新部署初始化完成。')
    return 0

if __name__ == '__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        print('初始化/补齐失败：' + str(exc), file=sys.stderr)
        raise SystemExit(1)
