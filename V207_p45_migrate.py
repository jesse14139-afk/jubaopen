#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P4/P5 综合数据迁移脚本：触点渠道类型与活动业务线市场关联

本脚本处理：
1. source_touchpoints: 根据 platform_id 和 channel_account_id 推断 channel_type_id
2. campaigns: 根据 workspace_id 关联 business_line_id 和 market_id

运行方式：
  python V207_p45_migrate.py --db jubaopen-v207.db

前置条件：
  1. P1 字典表已初始化
  2. P4/P5 迁移已执行（列已添加）

本脚本幂等：重复运行会检测已填充数据并跳过。
"""
import argparse, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from V207_shared_db import Database, now_ms

def migrate_touchpoints_and_campaigns(db_path):
    """执行 P4/P5 综合数据迁移。"""
    db = Database(str(db_path))
    n = now_ms()
    stats = {
        'touchpoints': {'updated': 0, 'skipped': 0},
        'campaigns': {'updated': 0, 'skipped': 0}
    }
    
    with db.tx() as c:
        # ===== P4: source_touchpoints 填充 channel_type_id =====
        print("P4: 正在迁移 source_touchpoints.channel_type_id...")
        
        # 查找所有 channel_type_id 为空的触点
        touchpoints = c.execute("""
            SELECT tp.touchpoint_id, tp.platform_id, tp.channel_account_id
            FROM source_touchpoints tp
            WHERE tp.channel_type_id IS NULL OR tp.channel_type_id = ''
        """).fetchall()
        
        print(f"  找到 {len(touchpoints)} 条触点记录需要迁移")
        
        for tp_id, platform_id, account_id in touchpoints:
            # 优先使用平台默认渠道类型（通用双向）
            if platform_id:
                ct = c.execute("""
                    SELECT channel_type_id 
                    FROM channel_types 
                    WHERE platform_id = ? AND direction = 'bidirectional' AND is_active = 1
                    ORDER BY sort_order LIMIT 1
                """, (platform_id,)).fetchone()
                
                if ct:
                    c.execute("""
                        UPDATE source_touchpoints 
                        SET channel_type_id = ?
                        WHERE touchpoint_id = ?
                    """, (ct[0], tp_id))
                    stats['touchpoints']['updated'] += 1
                else:
                    stats['touchpoints']['skipped'] += 1
            else:
                stats['touchpoints']['skipped'] += 1
        
        print(f"  ✓ 更新 {stats['touchpoints']['updated']} 条，跳过 {stats['touchpoints']['skipped']} 条")
        
        # ===== P5: campaigns 填充 business_line_id 和 market_id =====
        print("\nP5: 正在迁移 campaigns 业务线和市场关联...")
        
        campaigns = c.execute("""
            SELECT campaign_id, workspace_id, organization_id
            FROM campaigns
            WHERE (business_line_id IS NULL OR business_line_id = '')
               OR (market_id IS NULL OR market_id = '')
        """).fetchall()
        
        print(f"  找到 {len(campaigns)} 条活动记录需要迁移")
        
        for camp_id, ws_id, org_id in campaigns:
            # 获取工作区的主业务线和主市场
            bl = c.execute("""
                SELECT business_line_id 
                FROM workspace_business_lines 
                WHERE workspace_id = ? AND is_primary = 1 AND status = 'active'
                LIMIT 1
            """, (ws_id,)).fetchone()
            
            mk = c.execute("""
                SELECT market_id 
                FROM workspace_markets 
                WHERE workspace_id = ? AND is_primary = 1 AND status = 'active'
                LIMIT 1
            """, (ws_id,)).fetchone()
            
            if bl or mk:
                updates = []
                params = []
                if bl:
                    updates.append("business_line_id = ?")
                    params.append(bl[0])
                if mk:
                    updates.append("market_id = ?")
                    params.append(mk[0])
                
                params.extend([n, camp_id])
                c.execute(f"""
                    UPDATE campaigns 
                    SET {', '.join(updates)}, updated_at = ?
                    WHERE campaign_id = ?
                """, params)
                stats['campaigns']['updated'] += 1
            else:
                stats['campaigns']['skipped'] += 1
        
        print(f"  ✓ 更新 {stats['campaigns']['updated']} 条，跳过 {stats['campaigns']['skipped']} 条")
    
    print("\n" + "="*60)
    print("✓ P4/P5 综合数据迁移完成")
    print(f"  触点渠道类型：{stats['touchpoints']['updated']} 条")
    print(f"  活动业务线市场：{stats['campaigns']['updated']} 条")
    print("="*60)
    
    return True


def main():
    p = argparse.ArgumentParser(description="P4/P5 综合数据迁移")
    p.add_argument('--db', default=str(ROOT / 'data' / 'jubaopen-v207.db'))
    args = p.parse_args()
    
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        print(f"错误：数据库文件不存在：{db_path}", file=sys.stderr)
        return 1
    
    try:
        migrate_touchpoints_and_campaigns(db_path)
        return 0
    except Exception as e:
        print(f"错误：{e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
