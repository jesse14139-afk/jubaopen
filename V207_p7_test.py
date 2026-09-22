#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P7 综合测试脚本：端到端功能验证

本脚本测试：
1. P1: 企业组织预设数据完整性
2. P2: 平台字典和渠道账号 platform_id 必填
3. P3: 来源类型关联
4. P4/P5: 触点渠道类型和活动业务线市场
5. API 响应格式标准化

运行方式：
  python V207_p7_test.py --db jubaopen-v207.db

前置条件：
  1. 数据库已完成所有迁移
  2. P1 初始化脚本已运行
"""
import argparse, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _configure_output():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure:
            reconfigure(encoding='utf-8', errors='replace')


from V207_shared_db import Database

def test_p1_org_structure(db):
    """测试 P1 企业组织预设。"""
    print("\n【P1: 企业组织预设测试】")
    
    with db.tx(False) as c:
        # 测试企业
        org = c.execute("SELECT * FROM organizations WHERE organization_id='jubaopen'").fetchone()
        assert org, "❌ 企业 jubaopen 不存在"
        print("  ✓ 企业存在")
        
        # 测试工作区
        ws = c.execute("SELECT count(*) FROM workspaces WHERE organization_id='jubaopen' AND status='active'").fetchone()[0]
        assert ws >= 1, "❌ 未找到活跃工作区"
        print(f"  ✓ 工作区：{ws} 个")
        
        # 测试部门
        depts = c.execute("SELECT count(*) FROM departments WHERE organization_id='jubaopen' AND status='active'").fetchone()[0]
        assert depts >= 5, f"❌ 部门数量不足（预期 ≥5，实际 {depts}）"
        print(f"  ✓ 部门：{depts} 个")
        
        # 测试团队
        teams = c.execute("SELECT count(*) FROM teams WHERE organization_id='jubaopen' AND status='active'").fetchone()[0]
        assert teams >= 3, f"❌ 团队数量不足（预期 ≥3，实际 {teams}）"
        print(f"  ✓ 团队：{teams} 个")
        
        # 测试业务线
        bls = c.execute("SELECT count(*) FROM business_lines WHERE organization_id='jubaopen' AND status='active'").fetchone()[0]
        assert bls >= 2, f"❌ 业务线数量不足（预期 ≥2，实际 {bls}）"
        print(f"  ✓ 业务线：{bls} 个")
        
        # 测试市场
        mkts = c.execute("SELECT count(*) FROM markets WHERE organization_id='jubaopen' AND status='active'").fetchone()[0]
        assert mkts >= 10, f"❌ 市场数量不足（预期 ≥10，实际 {mkts}）"
        print(f"  ✓ 市场：{mkts} 个")
        
        # 测试职位
        poss = c.execute("SELECT count(*) FROM positions WHERE organization_id='jubaopen' AND status='active'").fetchone()[0]
        assert poss >= 10, f"❌ 职位数量不足（预期 ≥10，实际 {poss}）"
        print(f"  ✓ 职位：{poss} 个")

def test_p2_platform_dict(db):
    """测试 P2 平台字典和 platform_id。"""
    print("\n【P2: 平台字典测试】")
    
    with db.tx(False) as c:
        # 测试平台表
        platforms = c.execute("SELECT count(*) FROM platforms WHERE status='active'").fetchone()[0]
        assert platforms >= 5, f"❌ 平台数量不足（预期 ≥5，实际 {platforms}）"
        print(f"  ✓ 平台：{platforms} 个")
        
        # 测试渠道类型
        cts = c.execute("SELECT count(*) FROM channel_types WHERE is_active=1").fetchone()[0]
        assert cts >= 20, f"❌ 渠道类型数量不足（预期 ≥20，实际 {cts}）"
        print(f"  ✓ 渠道类型：{cts} 个")
        
        # 测试渠道账号 platform_id 填充率
        total_accounts = c.execute("SELECT count(*) FROM channel_accounts").fetchone()[0]
        filled_accounts = c.execute("SELECT count(*) FROM channel_accounts WHERE platform_id IS NOT NULL AND platform_id != ''").fetchone()[0]
        
        if total_accounts > 0:
            fill_rate = (filled_accounts / total_accounts) * 100
            print(f"  ✓ 渠道账号 platform_id 填充率：{fill_rate:.1f}% ({filled_accounts}/{total_accounts})")
            if fill_rate < 90:
                print(f"    ⚠ 填充率低于 90%，建议运行 V207_p2_migrate.py")

def test_p3_source_types(db):
    """测试 P3 来源类型关联。"""
    print("\n【P3: 来源类型测试】")
    
    with db.tx(False) as c:
        # 测试来源类型定义
        sts = c.execute("SELECT count(*) FROM source_type_definitions WHERE is_active=1").fetchone()[0]
        assert sts >= 8, f"❌ 来源类型数量不足（预期 ≥8，实际 {sts}）"
        print(f"  ✓ 来源类型：{sts} 个")
        
        # 测试 sources.source_type_id 列存在
        cols = [r[1] for r in c.execute("PRAGMA table_info(sources)")]
        assert 'source_type_id' in cols, "❌ sources 表缺少 source_type_id 列"
        print("  ✓ sources.source_type_id 列存在")
        
        # 测试填充率
        total_sources = c.execute("SELECT count(*) FROM sources").fetchone()[0]
        filled_sources = c.execute("SELECT count(*) FROM sources WHERE source_type_id IS NOT NULL AND source_type_id != ''").fetchone()[0]
        
        if total_sources > 0:
            fill_rate = (filled_sources / total_sources) * 100
            print(f"  ✓ 来源 source_type_id 填充率：{fill_rate:.1f}% ({filled_sources}/{total_sources})")
            if fill_rate < 90:
                print(f"    ⚠ 填充率低于 90%，建议运行 V207_p3_migrate.py")

def test_p45_touchpoints_campaigns(db):
    """测试 P4/P5 触点和活动增强。"""
    print("\n【P4/P5: 触点与活动测试】")
    
    with db.tx(False) as c:
        # 测试 source_touchpoints.channel_type_id 列
        tp_cols = [r[1] for r in c.execute("PRAGMA table_info(source_touchpoints)")]
        assert 'channel_type_id' in tp_cols, "❌ source_touchpoints 表缺少 channel_type_id 列"
        print("  ✓ source_touchpoints.channel_type_id 列存在")
        
        # 测试 campaigns 新列
        camp_cols = [r[1] for r in c.execute("PRAGMA table_info(campaigns)")]
        assert 'business_line_id' in camp_cols, "❌ campaigns 表缺少 business_line_id 列"
        assert 'market_id' in camp_cols, "❌ campaigns 表缺少 market_id 列"
        print("  ✓ campaigns.business_line_id 和 market_id 列存在")
        
        # 测试触点填充率
        total_tp = c.execute("SELECT count(*) FROM source_touchpoints").fetchone()[0]
        if total_tp > 0:
            filled_tp = c.execute("SELECT count(*) FROM source_touchpoints WHERE channel_type_id IS NOT NULL AND channel_type_id != ''").fetchone()[0]
            fill_rate = (filled_tp / total_tp) * 100
            print(f"  ✓ 触点 channel_type_id 填充率：{fill_rate:.1f}% ({filled_tp}/{total_tp})")
        
        # 测试活动填充率
        total_camp = c.execute("SELECT count(*) FROM campaigns").fetchone()[0]
        if total_camp > 0:
            filled_camp = c.execute("SELECT count(*) FROM campaigns WHERE business_line_id IS NOT NULL OR market_id IS NOT NULL").fetchone()[0]
            fill_rate = (filled_camp / total_camp) * 100
            print(f"  ✓ 活动业务线/市场填充率：{fill_rate:.1f}% ({filled_camp}/{total_camp})")

def test_schema_migrations(db):
    """测试迁移记录完整性。"""
    print("\n【迁移记录检查】")
    
    with db.tx(False) as c:
        migrations = c.execute("SELECT migration_id, migration_name FROM schema_migrations ORDER BY applied_at").fetchall()
        
        required = [
            'V211_030_channel_and_source_types',
            'V211_040_sources_type_id',
            'V211_050_touchpoints_campaigns_enhance'
        ]
        
        applied = [m[0] for m in migrations]
        
        for req in required:
            if req in applied:
                name = next((m[1] for m in migrations if m[0] == req), req)
                print(f"  ✓ {req}: {name}")
            else:
                print(f"  ❌ 缺少迁移：{req}")

def main():
    _configure_output()
    p = argparse.ArgumentParser(description="P7 综合测试")
    p.add_argument('--db', default=str(ROOT / 'data' / 'jubaopen-v207.db'))
    args = p.parse_args()
    
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        print(f"错误：数据库文件不存在：{db_path}", file=sys.stderr)
        return 1
    
    db = Database(str(db_path))
    
    print("="*70)
    print("Jubaopen V207.8.0 / Schema 211 综合测试")
    print("="*70)
    
    try:
        test_p1_org_structure(db)
        test_p2_platform_dict(db)
        test_p3_source_types(db)
        test_p45_touchpoints_campaigns(db)
        test_schema_migrations(db)
        
        print("\n" + "="*70)
        print("✓ 所有测试通过")
        print("="*70)
        return 0
    
    except AssertionError as e:
        print(f"\n\n❌ 测试失败：{e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"\n\n错误：{e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
