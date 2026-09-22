#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1 验收：企业组织预设、字典平台关联和重复执行幂等性。"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _configure_output():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure:
            reconfigure(encoding='utf-8', errors='replace')


from V207_dict_service import handle_channel_type, handle_source_type
from V207_p1_dict import CHANNEL_TYPES_SEED, SOURCE_TYPES_SEED
from V207_p1_init import seed_p1
from V207_shared_db import Database


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def counts(db):
    with db.tx(False) as c:
        return {
            'departments': c.execute("SELECT count(*) FROM departments WHERE organization_id='jubaopen'").fetchone()[0],
            'teams': c.execute("SELECT count(*) FROM teams WHERE team_id IN ('TEAM-JBP','TEAM-ZCM','TEAM-RJDJ')").fetchone()[0],
            'business_lines': c.execute("SELECT count(*) FROM business_lines WHERE organization_id='jubaopen'").fetchone()[0],
            'markets': c.execute("SELECT count(*) FROM markets WHERE organization_id='jubaopen'").fetchone()[0],
            'positions': c.execute("SELECT count(*) FROM positions WHERE organization_id='jubaopen'").fetchone()[0],
            'channel_types': c.execute('SELECT count(*) FROM channel_types').fetchone()[0],
            'source_types': c.execute('SELECT count(*) FROM source_type_definitions').fetchone()[0],
        }


def verify(db):
    with db.tx(False) as c:
        org = c.execute("SELECT name FROM organizations WHERE organization_id='jubaopen'").fetchone()
        assert_true(org and org[0] == '聚宝盆公司', '企业名称未设置为聚宝盆公司')
        assert_true(c.execute("SELECT 1 FROM workspaces WHERE workspace_id='ws-global' AND organization_id='jubaopen'").fetchone(), '全球工作区不存在')
        assert_true(c.execute("SELECT count(*) FROM departments WHERE organization_id='jubaopen'").fetchone()[0] == 5, '部门数量不是 5')
        assert_true(c.execute("SELECT count(*) FROM teams WHERE team_id IN ('TEAM-JBP','TEAM-ZCM','TEAM-RJDJ')").fetchone()[0] == 3, '业务团队数量不是 3')
        assert_true(c.execute("SELECT count(*) FROM workspace_teams WHERE workspace_id='ws-global' AND is_primary=1").fetchone()[0] == 1, '全球工作区主团队不唯一')
        assert_true(c.execute("SELECT count(*) FROM business_lines WHERE organization_id='jubaopen'").fetchone()[0] == 2, '业务线数量不是 2')
        assert_true(c.execute("SELECT count(*) FROM workspace_business_lines WHERE workspace_id='ws-global' AND is_primary=1").fetchone()[0] == 1, '全球工作区主业务线不唯一')
        assert_true(c.execute("SELECT count(*) FROM markets WHERE organization_id='jubaopen'").fetchone()[0] == 16, '市场数量不是 16')
        assert_true(c.execute("SELECT market_type FROM markets WHERE market_id='MKT-EUROPE'").fetchone()[0] == 'region', '区域市场类型不正确')
        assert_true(c.execute("SELECT market_type, currency_code FROM markets WHERE market_id='MKT-DE'").fetchone() == ('country', 'EUR'), '国家市场字段不正确')
        assert_true(c.execute("SELECT parent_market_id FROM markets WHERE market_id='MKT-UK'").fetchone()[0] == 'MKT-EUROPE', '市场层级不正确')
        assert_true(c.execute("SELECT count(*) FROM workspace_markets WHERE workspace_id='ws-global' AND is_primary=1").fetchone()[0] == 1, '全球工作区主市场不唯一')
        assert_true(c.execute("SELECT count(*) FROM positions WHERE organization_id='jubaopen'").fetchone()[0] == 12, '职位数量不是 12')
        assert_true(c.execute('SELECT count(*) FROM channel_types').fetchone()[0] == len(CHANNEL_TYPES_SEED), '渠道类型预设不完整')
        assert_true(c.execute('SELECT count(*) FROM source_type_definitions').fetchone()[0] == len(SOURCE_TYPES_SEED), '来源类型预设不完整')
        dangling = c.execute("""
            SELECT count(*) FROM channel_types ct
            LEFT JOIN platforms p ON p.platform_id=ct.platform_id
            WHERE ct.platform_id IS NOT NULL AND p.platform_id IS NULL
        """).fetchone()[0]
        assert_true(dangling == 0, '存在未关联到平台表的渠道类型')
        linked = c.execute("""
            SELECT p.platform_name FROM channel_types ct
            JOIN platforms p ON p.platform_id=ct.platform_id
            WHERE ct.channel_type_id='ct-wa-service'
        """).fetchone()
        assert_true(linked and linked[0] == 'WhatsApp', 'WhatsApp 渠道类型未关联到平台')

    actor = {'user_id': 'admin', 'organization_id': 'jubaopen'}
    payload, status = handle_channel_type(db, actor, 'jubaopen', 'GET', 'ct-wa-service', {}, {})
    assert_true(status == 200 and payload['item']['platform_name'] == 'WhatsApp', '渠道类型接口未返回平台名称')
    payload, status = handle_source_type(db, actor, 'jubaopen', 'GET', 'st-paid-ad', {}, {})
    assert_true(status == 200 and payload['item']['source_type_code'] == 'paid_ad', '来源类型接口返回不正确')


def main():
    _configure_output()
    with tempfile.TemporaryDirectory(prefix='jubaopen-p1-') as temp_dir:
        db_path = Path(temp_dir) / 'p1.db'
        Database(db_path).initialize({'admin_password': 'StrongPass1234'})
        seed_p1(db_path)
        db = Database(db_path)
        before = counts(db)
        verify(db)
        seed_p1(db_path)
        assert_true(counts(db) == before, '重复执行 P1 初始化改变了预设数量')
        verify(db)
    print('P1 验收通过：组织预设、字典平台关联、查询接口和幂等执行完成')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
