#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P1 企业预设初始化脚本 - 聚宝盆公司组织架构预设

本脚本在 Schema 211 基础上初始化：
- 企业
- 工作区（全球业务工作区）
- 部门（5个一级部门）
- 团队（3个业务团队）
- 业务线（2条）
- 市场树（全球地域结构）
- 职位预设

运行方式：
  python V207_p1_init.py --db jubaopen-v207.db

前置条件：
  1. 数据库已通过 V207_first_run.py 完成基础初始化
  2. 平台管理员已创建并可登录
  3. 企业 ID 为 jubaopen

本脚本幂等：重复运行会检测已存在数据并跳过。
"""
import argparse, sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from V207_shared_db import Database, now_ms
from V207_p1_dict import CHANNEL_TYPES_SEED, SOURCE_TYPES_SEED, seed_channel_and_source_types
from V207_p1_users import P1_USERS, seed_p1_people


def _configure_output():
    """让 Windows 默认控制台也能稳定输出初始化进度。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure:
            reconfigure(encoding='utf-8', errors='replace')


def seed_p1(db_path, org_id='jubaopen'):
    """执行 P1 组织预设初始化。"""
    db = Database(str(db_path))
    n = now_ms()
    
    # 确保企业存在
    with db.tx() as c:
        org = c.execute(
            "SELECT organization_id FROM organizations WHERE organization_id=?",
            (org_id,)
        ).fetchone()
        if not org:
            raise RuntimeError(f"企业 {org_id} 不存在，请先运行 V207_first_run.py 完成基础初始化")
        c.execute(
            "UPDATE organizations SET name='聚宝盆公司', updated_at=? WHERE organization_id=? AND name='聚宝盆企业'",
            (n, org_id)
        )
    
    # ===== 1. 工作区 =====
    WS_GLOBAL_ID = 'ws-global'
    ws_global_name = '全球业务工作区'
    
    with db.tx() as c:
        existing_ws = c.execute(
            "SELECT workspace_id FROM workspaces WHERE workspace_id=?",
            (WS_GLOBAL_ID,)
        ).fetchone()
        
        if not existing_ws:
            c.execute(
                "INSERT INTO workspaces(workspace_id,name,status,created_at,updated_at,organization_id) VALUES(?,?,'active',?,?,?)",
                (WS_GLOBAL_ID, ws_global_name, n, n, org_id)
            )
            c.execute(
                "INSERT INTO workspace_configs(workspace_id,revision,items_json,updated_at,updated_by) VALUES(?,0,'[]',?,?)",
                (WS_GLOBAL_ID, n, 'SYSTEM')
            )
            print(f"✓ 创建工作区：{WS_GLOBAL_ID} - {ws_global_name}")
        else:
            print(f"○ 工作区已存在：{WS_GLOBAL_ID} - {ws_global_name}，跳过")
    
    # ===== 2. 部门 =====
    departments = [
        ('DEPT-BIZ',     '业务运营部',       1),
        ('DEPT-CHANNEL', '渠道运营部',       2),
        ('DEPT-RISK',    '风控合规部',       3),
        ('DEPT-RESEARCH','策略研究部',       4),
        ('DEPT-QUANT',   '量化交易部',       5),
    ]
    
    with db.tx() as c:
        for dept_id, dept_name, sort_order in departments:
            existing = c.execute(
                "SELECT department_id FROM departments WHERE department_id=?",
                (dept_id,)
            ).fetchone()
            if not existing:
                c.execute(
                    "INSERT INTO departments(department_id,organization_id,name,code,description,status,sort_order,created_at,updated_at) VALUES(?,?,?,?,'P1预设部门',?,?,?,?)",
                    (dept_id, org_id, dept_name, dept_id, 'active', sort_order, n, n)
                )
                print(f"✓ 创建部门：{dept_id} - {dept_name}")
            else:
                print(f"○ 部门已存在：{dept_id} - {dept_name}，跳过")
    
    # ===== 3. 团队 =====
    teams = [
        ('TEAM-JBP',  '聚宝盆团队',  WS_GLOBAL_ID, 'DEPT-BIZ'),
        ('TEAM-ZCM',  '招财猫团队',  WS_GLOBAL_ID, 'DEPT-BIZ'),
        ('TEAM-RJDJ', '日进斗金团队', WS_GLOBAL_ID, 'DEPT-BIZ'),
    ]
    
    with db.tx() as c:
        for team_index, (team_id, team_name, ws_id, dept_id) in enumerate(teams):
            existing = c.execute(
                "SELECT team_id FROM teams WHERE team_id=?",
                (team_id,)
            ).fetchone()
            if not existing:
                c.execute(
                    "INSERT INTO teams(team_id,organization_id,workspace_id,department_id,name,status,created_at,updated_at) VALUES(?,?,?,?,?,'active',?,?)",
                    (team_id, org_id, ws_id, dept_id, team_name, n, n)
                )
                c.execute(
                    "INSERT INTO workspace_teams(workspace_id,team_id,organization_id,relation_type,is_primary,access_level,status,created_at,updated_at) VALUES(?,?,?,?,?,'manage','active',?,?)",
                    (ws_id, team_id, org_id, 'primary' if team_index == 0 else 'collaborator', 1 if team_index == 0 else 0, n, n)
                )
                print(f"✓ 创建团队：{team_id} - {team_name}")
            else:
                print(f"○ 团队已存在：{team_id} - {team_name}，跳过")
    
    # ===== 4. 业务线 =====
    business_lines = [
        ('BL-QUANT',   '量化交易',     1),
        ('BL-ADVISOR', '股票咨询',     2),
    ]
    
    with db.tx() as c:
        for bl_index, (bl_id, bl_name, sort_order) in enumerate(business_lines):
            existing = c.execute(
                "SELECT business_line_id FROM business_lines WHERE business_line_id=?",
                (bl_id,)
            ).fetchone()
            if not existing:
                c.execute(
                    "INSERT INTO business_lines(business_line_id,organization_id,name,code,description,status,sort_order,created_at,updated_at) VALUES(?,?,?,?,'P1预设业务线',?,?,?,?)",
                    (bl_id, org_id, bl_name, bl_id, 'active', sort_order, n, n)
                )
                c.execute(
                    "INSERT INTO workspace_business_lines(workspace_id,business_line_id,organization_id,is_primary,status,created_at,updated_at) VALUES(?,?,?,?,'active',?,?)",
                    (WS_GLOBAL_ID, bl_id, org_id, 1 if bl_index == 0 else 0, n, n)
                )
                print(f"✓ 创建业务线：{bl_id} - {bl_name}")
            else:
                print(f"○ 业务线已存在：{bl_id} - {bl_name}，跳过")
    
    # ===== 5. 市场树 =====
    markets = [
        # (market_id, name, parent_id, code, currency, language, timezone)
        ('MKT-GLOBAL', '全球',           None,         'GLOBAL', 'USD', 'en',    'UTC'),
        ('MKT-EUROPE', '欧洲',           'MKT-GLOBAL', 'EUROPE', 'EUR', 'multi', 'CET'),
        ('MKT-UK',     '英国',           'MKT-EUROPE', 'GB',     'GBP', 'en',    'GMT'),
        ('MKT-DE',     '德国',           'MKT-EUROPE', 'DE',     'EUR', 'de',    'CET'),
        ('MKT-FR',     '法国',           'MKT-EUROPE', 'FR',     'EUR', 'fr',    'CET'),
        ('MKT-ES',     '西班牙',         'MKT-EUROPE', 'ES',     'EUR', 'es',    'CET'),
        ('MKT-IT',     '意大利',         'MKT-EUROPE', 'IT',     'EUR', 'it',    'CET'),
        ('MKT-ASIA',   '亚洲',           'MKT-GLOBAL', 'ASIA',   'USD', 'multi', 'Asia/Shanghai'),
        ('MKT-KR',     '韩国',           'MKT-ASIA',   'KR',     'KRW', 'ko',    'KST'),
        ('MKT-JP',     '日本',           'MKT-ASIA',   'JP',     'JPY', 'ja',    'JST'),
        ('MKT-TW',     '台湾地区',       'MKT-ASIA',   'TW',     'TWD', 'zh-TW', 'CST'),
        ('MKT-AMERICAS','美洲',          'MKT-GLOBAL', 'AMERICAS','USD', 'en',    'America/New_York'),
        ('MKT-US',     '美国',           'MKT-AMERICAS','US',    'USD', 'en',    'America/New_York'),
        ('MKT-CA',     '加拿大',         'MKT-AMERICAS','CA',    'CAD', 'en',    'America/Toronto'),
        ('MKT-OCEANIA','大洋洲',         'MKT-GLOBAL', 'OCEANIA','AUD', 'en',    'Australia/Sydney'),
        ('MKT-AU',     '澳大利亚',       'MKT-OCEANIA','AU',     'AUD', 'en',    'Australia/Sydney'),
    ]
    
    with db.tx() as c:
        for mkt_id, mkt_name, parent_id, code, currency, language, tz in markets:
            existing = c.execute(
                "SELECT market_id FROM markets WHERE market_id=?",
                (mkt_id,)
            ).fetchone()
            if not existing:
                market_type = 'country' if len(code) == 2 else 'region'
                c.execute(
                    "INSERT INTO markets(market_id,organization_id,parent_market_id,name,code,market_type,country_code,region_code,timezone,currency_code,description,status,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,'active',?,?,?)",
                    (mkt_id, org_id, parent_id, mkt_name, code, market_type, code if market_type == 'country' else '', code if market_type == 'region' else '', tz, currency, 'P1预设市场', 0, n, n)
                )
                print(f"✓ 创建市场：{mkt_id} - {mkt_name}")
            else:
                print(f"○ 市场已存在：{mkt_id} - {mkt_name}，跳过")
    
    # ===== 6. 工作区市场关联 =====
    # 将全球市场关联到全球工作区
    with db.tx() as c:
        for mkt_id, _, _, _, _, _, _ in markets:
            existing = c.execute(
                "SELECT 1 FROM workspace_markets WHERE workspace_id=? AND market_id=?",
                (WS_GLOBAL_ID, mkt_id)
            ).fetchone()
            if not existing:
                c.execute(
                    "INSERT INTO workspace_markets(workspace_id,market_id,organization_id,is_primary,scope_type,status,created_at,updated_at) VALUES(?,?,?,?,'direct','active',?,?)",
                    (WS_GLOBAL_ID, mkt_id, org_id, 1 if mkt_id == 'MKT-GLOBAL' else 0, n, n)
                )
                print(f"✓ 关联市场到工作区：{mkt_id} -> {WS_GLOBAL_ID}")
            # 跳过已存在的情况
    
    # ===== 7. 职位预设 =====
    positions = [
        # (position_id, name, code, department_id, sort_order)
        ('POS-GM',       '全球业务总监',  'GLOBAL_DIRECTOR',  'DEPT-BIZ',     1),
        ('POS-AREA',     '区域总监',       'AREA_DIRECTOR',    'DEPT-BIZ',     2),
        ('POS-TEAM-LDR', '团队经理',       'TEAM_LEADER',      'DEPT-BIZ',     3),
        ('POS-SALES',    '业务员',          'SALES',            'DEPT-BIZ',     4),
        ('POS-OPS',      '运营专员',        'OPS',              'DEPT-BIZ',     5),
        ('POS-CH-DIR',   '渠道总监',       'CHANNEL_DIRECTOR', 'DEPT-CHANNEL', 1),
        ('POS-CH-SPEC',  '渠道专员',        'CHANNEL_SPEC',     'DEPT-CHANNEL', 2),
        ('POS-STRAT',    '策略研究员',      'STRATEGIST',       'DEPT-RESEARCH',1),
        ('POS-TRADER',   '交易操盘手',      'TRADER',           'DEPT-QUANT',   1),
        ('POS-RISK-MGR', '风控合规经理',    'RISK_MANAGER',     'DEPT-RISK',    1),
        ('POS-RISK-SPEC','风控专员',        'RISK_SPEC',        'DEPT-RISK',    2),
        ('POS-AUDIT',    '审计专员',        'AUDITOR',          'DEPT-RISK',    3),
    ]
    
    with db.tx() as c:
        for pos_id, pos_name, pos_code, dept_id, sort_order in positions:
            existing = c.execute(
                "SELECT position_id FROM positions WHERE position_id=?",
                (pos_id,)
            ).fetchone()
            if not existing:
                c.execute(
                    "INSERT INTO positions(position_id,organization_id,department_id,name,code,description,status,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,'P1预设职位','active',?,?,?)",
                    (pos_id, org_id, dept_id, pos_name, pos_code, sort_order, n, n)
                )
                print(f"✓ 创建职位：{pos_id} - {pos_name}")
            else:
                print(f"○ 职位已存在：{pos_id} - {pos_name}，跳过")

    # ===== 8. 渠道类型与来源类型字典 =====
    dictionary = seed_channel_and_source_types(db, n)
    print(
        "✓ 字典预设：渠道类型 {created}/{total} 新增，来源类型 {source_created}/{source_total} 新增，平台关联修正 {relinked} 条".format(
            created=dictionary['channel_types_created'],
            total=len(CHANNEL_TYPES_SEED),
            source_created=dictionary['source_types_created'],
            source_total=len(SOURCE_TYPES_SEED),
            relinked=dictionary['channel_types_relinked'],
        )
    )

    people = seed_p1_people(db, org_id, WS_GLOBAL_ID)
    print(
        "✓ 人员预设：角色 {roles} 新增，用户 {users}/{total} 新增，团队业务线 {bl} 条，团队市场 {mkt} 条".format(
            roles=people['roles_created'],
            users=people['users_created'],
            total=len(P1_USERS),
            bl=people['team_business_lines_created'],
            mkt=people['team_markets_created'],
        )
    )
    
    print("\n✓ P1 组织预设初始化完成")
    print("  企业：jubaopen 聚宝盆公司")
    print("  工作区：ws-global 全球业务工作区")
    print("  部门：5个")
    print("  团队：3个")
    print("  业务线：2条")
    print("  市场：16个（含地域层级）")
    print("  职位：12个")
    print("  模板用户：8个（不自动授予企业管理员）")
    return True


def main():
    _configure_output()
    p = argparse.ArgumentParser(description="P1 企业组织预设初始化")
    p.add_argument('--db', default=str(ROOT / 'data' / 'jubaopen-v207.db'))
    args = p.parse_args()
    
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        print(f"错误：数据库文件不存在：{db_path}", file=sys.stderr)
        print("请先运行 python V207_first_run.py 完成基础初始化", file=sys.stderr)
        return 1
    
    try:
        seed_p1(db_path)
        return 0
    except Exception as e:
        print(f"错误：{e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
