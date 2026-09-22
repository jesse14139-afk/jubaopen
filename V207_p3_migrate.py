#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P3 数据迁移脚本：填充 sources 历史数据的 source_type_id

本脚本处理：
根据 source_type 字段映射填充 source_type_id

运行方式：
  python V207_p3_migrate.py --db jubaopen-v207.db

前置条件：
  1. 数据库已完成 P1 初始化（source_type_definitions 表存在）
  2. 数据库已完成 P3 迁移（sources.source_type_id 列存在）

本脚本幂等：重复运行会检测已填充数据并跳过。
"""
import argparse, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from V207_shared_db import Database, now_ms

# source_type 旧枚举到 source_type_code 的映射
TYPE_MAPPING = {
    'unknown': 'unknown',
    'organic': 'organic_direct',
    'paid': 'paid_advertising',
    'referral': 'referral_partner',
    'direct': 'organic_direct',
    'social': 'social_media',
    'messaging': 'messaging_app',
    'offline': 'offline_channel',
    'import': 'data_import',
    'campaign': 'marketing_campaign',
    'website': 'website_form'
}

def migrate_source_type_ids(db_path):
    """执行 P3 source_type_id 数据迁移。"""
    db = Database(str(db_path))
    n = now_ms()
    stats = {'updated': 0, 'skipped': 0, 'failed': 0}
    
    with db.tx() as c:
        # 查找所有 source_type_id 为空的记录
        sources = c.execute("""
            SELECT source_id, source_type 
            FROM sources 
            WHERE source_type_id IS NULL OR source_type_id = ''
        """).fetchall()
        
        print(f"找到 {len(sources)} 条需要迁移的来源记录")
        
        for src_id, source_type in sources:
            if not source_type or source_type not in TYPE_MAPPING:
                print(f"  ⚠ 跳过来源 {src_id}：source_type '{source_type}' 无效")
                stats['skipped'] += 1
                continue
            
            # 映射到 source_type_code
            code = TYPE_MAPPING[source_type]
            
            # 查找对应的 source_type_id
            st = c.execute("""
                SELECT source_type_id 
                FROM source_type_definitions 
                WHERE source_type_code = ? AND is_active = 1
            """, (code,)).fetchone()
            
            if st:
                c.execute("""
                    UPDATE sources 
                    SET source_type_id = ?, updated_at = ?
                    WHERE source_id = ?
                """, (st[0], n, src_id))
                stats['updated'] += 1
                if stats['updated'] % 100 == 0:
                    print(f"  已处理 {stats['updated']} 条...")
            else:
                print(f"  ⚠ 来源 {src_id}：未找到类型码 '{code}'")
                stats['failed'] += 1
    
    print("\n" + "="*60)
    print("✓ P3 数据迁移完成")
    print(f"  更新成功：{stats['updated']} 条")
    print(f"  跳过无效：{stats['skipped']} 条")
    print(f"  未找到类型：{stats['failed']} 条")
    print("="*60)
    
    return True


def main():
    p = argparse.ArgumentParser(description="P3 source_type_id 数据迁移")
    p.add_argument('--db', default=str(ROOT / 'data' / 'jubaopen-v207.db'))
    args = p.parse_args()
    
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        print(f"错误：数据库文件不存在：{db_path}", file=sys.stderr)
        return 1
    
    try:
        migrate_source_type_ids(db_path)
        return 0
    except Exception as e:
        print(f"错误：{e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
