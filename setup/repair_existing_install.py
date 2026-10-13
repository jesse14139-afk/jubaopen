#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Safely and idempotently repair presets in an existing installation."""
import argparse, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from setup.seed_organization import seed_p1

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--db',default=str(Path('I:\\jubaopen_data\\jubaopen-v208.db')))
    args=ap.parse_args(); db=Path(args.db).expanduser().resolve()
    if not db.is_file() or db.stat().st_size==0:
        raise RuntimeError('未找到现有数据库：'+str(db))
    seed_p1(str(db),'jubaopen')
    print('现有安装其他预设补齐完成（不含测试联系人）：'+str(db))
if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('补齐失败：'+str(exc),file=sys.stderr);raise SystemExit(1)
