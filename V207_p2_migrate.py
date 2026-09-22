#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P2 数据迁移脚本：填充历史数据的 platform_id

本脚本处理：
1. channel_accounts: 根据 channel 字段填充 platform_id
2. channel_account_identities: 根据关联账号填充 platform_id
3. sources: 根据 channel 字段填充 platform_id

运行方式：
  python V207_p2_migrate.py --db jubaopen-v207.db

前置条件：
  1. 数据库已完成 P1 初始化（platforms 表存在且有数据）
  2. 企业已创建并有历史数据

本脚本幂等：重复运行会检测已填充数据并跳过。
"""
import argparse, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from V207_shared_db import Database, now_ms


def migrate_platform_ids(db_path):
    """执行 P2 platform_id 数据迁移。"""
    db = Database(str(db_path))
    n = now_ms()
    
    stats = {
        'channel_accounts': 0,
        'identities': 0,
        'sources': 0
    }
    
    with db.tx() as c:
        # ===== 1. 迁移 channel_accounts =====
        print("正在迁移 channel_accounts...")
        
        # 查找所有 platform_id 为空的记录
        accounts = c.execute("""
            SELECT channel_account_id, channel 
            FROM channel_accounts 
            WHERE platform_id IS NULL OR platform_id = ''
        """).fetchall()
        
        for acc_id, channel in accounts:
            if not channel:
                print(f"  ⚠ 跳过账号 {acc_id}：channel 字段为空")
                continue
            
            # 根据 channel 查找对应的 platform_id
            platform = c.execute("""
                SELECT platform_id 
                FROM platforms 
                WHERE platform_code = ? AND status = 'active'
            """, (channel.lower(),)).fetchone()
            
            if platform:
                c.execute("""
                    UPDATE channel_accounts 
                    SET platform_id = ?, updated_at = ?
                    WHERE channel_account_id = ?
                """, (platform[0], n, acc_id))
                stats['channel_accounts'] += 1
                print(f"  ✓ 账号 {acc_id}: {channel} -> {platform[0]}")
            else:
                print(f"  ⚠ 账号 {acc_id}：未找到平台 '{channel}'")
        
        # ===== 2. 迁移 channel_account_identities =====
        print("\n正在迁移 channel_account_identities...")
        
        identities = c.execute("""
            SELECT i.identity_id, i.channel_account_id, ca.platform_id
            FROM channel_account_identities i
            JOIN channel_accounts ca ON ca.channel_account_id = i.channel_account_id
            WHERE (i.platform_id IS NULL OR i.platform_id = '')
              AND ca.platform_id IS NOT NULL
        """).fetchall()
        
        for idn_id, acc_id, platform_id in identities:
            c.execute("""
                UPDATE channel_account_identities 
                SET platform_id = ?
                WHERE identity_id = ?
            """, (platform_id, idn_id))
            stats['identities'] += 1
        
        if stats['identities'] > 0:
            print(f"  ✓ 更新了 {stats['identities']} 条身份记录")
        
        # ===== 3. 迁移 sources =====
        print("\n正在迁移 sources...")
        
        sources = c.execute("""
            SELECT source_id, channel 
            FROM sources 
            WHERE platform_id IS NULL OR platform_id = ''
        """).fetchall()
        
        for src_id, channel in sources:
            if not channel:
                print(f"  ⚠ 跳过来源 {src_id}：channel 字段为空")
                continue
            
            platform = c.execute("""
                SELECT platform_id 
                FROM platforms 
                WHERE platform_code = ? AND status = 'active'
            """, (channel.lower(),)).fetchone()
            
            if platform:
                c.execute("""
                    UPDATE sources 
                    SET platform_id = ?, updated_at = ?
                    WHERE source_id = ?
                """, (platform[0], n, src_id))
                stats['sources'] += 1
                print(f"  ✓ 来源 {src_id}: {channel} -> {platform[0]}")
            else:
                print(f"  ⚠ 来源 {src_id}：未找到平台 '{channel}'")
    
    print("\n" + "="*60)
    print("✓ P2 数据迁移完成")
    print(f"  channel_accounts:     {stats['channel_accounts']} 条")
    print(f"  identities:           {stats['identities']} 条")
    print(f"  sources:              {stats['sources']} 条")
    print("="*60)
    
    return True


def main():
    p = argparse.ArgumentParser(description="P2 platform_id 数据迁移")
    p.add_argument('--db', default=str(ROOT / 'data' / 'jubaopen-v207.db'))
    args = p.parse_args()
    
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        print(f"错误：数据库文件不存在：{db_path}", file=sys.stderr)
        return 1
    
    try:
        migrate_platform_ids(db_path)
        return 0
    except Exception as e:
        print(f"错误：{e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
