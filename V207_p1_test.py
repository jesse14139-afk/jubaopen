#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1 验收：企业组织预设、8 个模板用户、无团队登录、团队多选和幂等执行。"""
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


from V207_admin_api import _audit_workspace
from V207_dict_service import handle_channel_type, handle_source_type
from V207_p1_dict import CHANNEL_TYPES_SEED, SOURCE_TYPES_SEED
from V207_p1_init import seed_p1
from V207_p1_users import FORBIDDEN_TEMPLATE_ROLES, NO_TEAM_LOGINS, P1_PASSWORD, P1_USER_LOGINS, P1_USERS
from V207_security import can, login
from V207_shared_db import Database, _hierarchy_cycle, default_workspace_id


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
            'p1_users': c.execute(
                "SELECT count(*) FROM users WHERE organization_id='jubaopen' AND login_name IN ({})".format(
                    ','.join('?' * len(P1_USER_LOGINS))
                ),
                P1_USER_LOGINS,
            ).fetchone()[0],
            'p1_roles': c.execute(
                "SELECT count(*) FROM roles WHERE role_id IN ('role-jbp-risk-admin','role-jbp-org-readonly','role-jbp-ws-operator','role-jbp-ws-readonly')"
            ).fetchone()[0],
            'team_business_lines': c.execute(
                "SELECT count(*) FROM team_business_lines WHERE team_id IN ('TEAM-JBP','TEAM-ZCM','TEAM-RJDJ') AND status='active'"
            ).fetchone()[0],
            'team_markets': c.execute(
                "SELECT count(*) FROM team_markets WHERE team_id IN ('TEAM-JBP','TEAM-ZCM','TEAM-RJDJ') AND status='active'"
            ).fetchone()[0],
        }


def verify(db):
    with db.tx(False) as c:
        org = c.execute("SELECT name FROM organizations WHERE organization_id='jubaopen'").fetchone()
        assert_true(org and org[0] == '聚宝盆公司', '企业名称未设置为聚宝盆公司')
        assert_true(c.execute("SELECT 1 FROM workspaces WHERE workspace_id='ws-global' AND organization_id='jubaopen'").fetchone(), '全球工作区不存在')
        assert_true(default_workspace_id(c, 'jubaopen') == 'ws-global', '默认工作区不是全球业务工作区')
        assert_true(_audit_workspace(c, {'organization_id': 'jubaopen'}) == 'ws-global', '默认审计工作区不是全球业务工作区')
        assert_true(c.execute("SELECT count(*) FROM departments WHERE organization_id='jubaopen'").fetchone()[0] == 5, '部门数量不是 5')
        assert_true(c.execute("SELECT count(*) FROM teams WHERE team_id IN ('TEAM-JBP','TEAM-ZCM','TEAM-RJDJ')").fetchone()[0] == 3, '业务团队数量不是 3')
        assert_true(c.execute("SELECT count(*) FROM workspace_teams WHERE workspace_id='ws-global' AND is_primary=1").fetchone()[0] == 1, '全球工作区主团队不唯一')
        assert_true(c.execute("SELECT count(*) FROM business_lines WHERE organization_id='jubaopen'").fetchone()[0] == 2, '业务线数量不是 2')
        assert_true(c.execute("SELECT count(*) FROM workspace_business_lines WHERE workspace_id='ws-global' AND is_primary=1").fetchone()[0] == 1, '全球工作区主业务线不唯一')
        assert_true(c.execute("SELECT count(*) FROM markets WHERE organization_id='jubaopen'").fetchone()[0] == 16, '市场数量不是 16')
        assert_true(c.execute("SELECT market_type FROM markets WHERE market_id='MKT-EUROPE'").fetchone()[0] == 'region', '区域市场类型不正确')
        assert_true(tuple(c.execute("SELECT market_type, currency_code FROM markets WHERE market_id='MKT-DE'").fetchone()) == ('country', 'EUR'), '国家市场字段不正确')
        assert_true(c.execute("SELECT parent_market_id FROM markets WHERE market_id='MKT-UK'").fetchone()[0] == 'MKT-EUROPE', '市场层级不正确')
        assert_true(not _hierarchy_cycle(c, 'markets', 'market_id', 'parent_market_id'), '市场树存在循环')
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

        assert_true(c.execute(
            "SELECT count(*) FROM users WHERE organization_id='jubaopen' AND login_name IN ({})".format(','.join('?' * len(P1_USER_LOGINS))),
            P1_USER_LOGINS,
        ).fetchone()[0] == 8, '模板用户数量不是 8')
        for spec in P1_USERS:
            row = c.execute("""
                SELECT u.display_name,u.status,p.position_id,p.department_id,d.name department_name
                FROM users u
                JOIN user_positions up ON up.user_id=u.user_id AND up.is_primary=1 AND up.status='active'
                JOIN positions p ON p.position_id=up.position_id
                LEFT JOIN departments d ON d.department_id=p.department_id
                WHERE u.login_name=? COLLATE NOCASE
            """, (spec['login_name'],)).fetchone()
            assert_true(row, spec['login_name'] + ' 缺少主职位或部门')
            assert_true(row['display_name'] == spec['display_name'], spec['login_name'] + ' 显示名不匹配')
            assert_true(row['position_id'] == spec['position_id'], spec['login_name'] + ' 主职位不匹配')
            assert_true(row['department_id'] == spec['department_id'], spec['login_name'] + ' 主部门不匹配')
            memberships = [x['team_id'] for x in c.execute(
                "SELECT team_id,is_primary FROM team_memberships WHERE user_id=? AND status='active' ORDER BY is_primary DESC, team_id",
                (spec['user_id'],),
            )]
            if spec['primary_team_id']:
                assert_true(spec['primary_team_id'] in memberships, spec['login_name'] + ' 缺少主团队')
            else:
                primary = c.execute(
                    "SELECT team_id FROM team_memberships WHERE user_id=? AND is_primary=1 AND status='active'",
                    (spec['user_id'],),
                ).fetchone()
                assert_true(primary is None, spec['login_name'] + ' 不应有主团队')
            bindings = {x['role_id']: (x['scope_type'], x['scope_id']) for x in c.execute(
                "SELECT role_id,scope_type,scope_id FROM role_bindings WHERE user_id=? AND status='active'",
                (spec['user_id'],),
            )}
            assert_true(not (FORBIDDEN_TEMPLATE_ROLES & set(bindings)), spec['login_name'] + ' 被授予了禁止的高权限角色')
            if spec['org_role_id']:
                assert_true(bindings.get(spec['org_role_id']) == ('organization', 'jubaopen'), spec['login_name'] + ' 企业角色或数据范围不正确')
            if spec['workspace_role_id']:
                assert_true(bindings.get(spec['workspace_role_id']) == ('workspace', 'ws-global'), spec['login_name'] + ' 工作区角色或数据范围不正确')
            if spec['team_role_id'] and spec['primary_team_id']:
                assert_true(bindings.get(spec['team_role_id']) == ('team', spec['primary_team_id']), spec['login_name'] + ' 团队角色或数据范围不正确')

        assert_true(c.execute("SELECT count(*) FROM team_memberships WHERE user_id='usr-p1-risk-spec'").fetchone()[0] == 0, '风控专员不应有团队成员关系')
        assert_true(c.execute("SELECT count(*) FROM team_business_lines WHERE team_id='TEAM-JBP' AND status='active'").fetchone()[0] >= 2, '聚宝盆团队业务线未多选')
        assert_true(c.execute("SELECT count(*) FROM team_markets WHERE team_id='TEAM-RJDJ' AND status='active'").fetchone()[0] >= 2, '日进斗金团队市场未多选')
        listed = c.execute("""
            SELECT u.login_name,u.display_name,
              (SELECT group_concat(t.name) FROM team_memberships tm JOIN teams t ON t.team_id=tm.team_id WHERE tm.user_id=u.user_id AND tm.status='active') teams,
              (SELECT group_concat(r.name) FROM role_bindings b JOIN roles r ON r.role_id=b.role_id WHERE b.user_id=u.user_id AND b.organization_id=u.organization_id AND b.status='active') roles,
              (SELECT p.name FROM user_positions up JOIN positions p ON p.position_id=up.position_id WHERE up.user_id=u.user_id AND up.is_primary=1 AND up.status='active' LIMIT 1) position_name,
              (SELECT d.name FROM user_positions up JOIN positions p ON p.position_id=up.position_id LEFT JOIN departments d ON d.department_id=p.department_id WHERE up.user_id=u.user_id AND up.is_primary=1 AND up.status='active' LIMIT 1) department_name
            FROM users u WHERE u.login_name='observer.org' COLLATE NOCASE
        """).fetchone()
        assert_true(listed and listed['position_name'] and listed['department_name'] and listed['roles'] and not listed['teams'], '用户列表未展示无团队观察员的职位、部门和角色')
        membership_graph = c.execute(
            "SELECT count(*) FROM team_memberships tm JOIN teams t ON t.team_id=tm.team_id WHERE t.organization_id='jubaopen' AND tm.status='active'"
        ).fetchone()[0]
        assert_true(membership_graph >= 4, '组织图成员关系应来自 team_memberships')

    actor = {'user_id': 'admin', 'organization_id': 'jubaopen'}
    payload, status = handle_channel_type(db, actor, 'jubaopen', 'GET', 'ct-wa-service', {}, {})
    assert_true(status == 200 and payload['item']['platform_name'] == 'WhatsApp', '渠道类型接口未返回平台名称')
    payload, status = handle_source_type(db, actor, 'jubaopen', 'GET', 'st-paid-ad', {}, {})
    assert_true(status == 200 and payload['item']['source_type_code'] == 'paid_ad', '来源类型接口返回不正确')

    for login_name in NO_TEAM_LOGINS:
        payload, status = login(db, 'jubaopen', login_name, P1_PASSWORD)
        assert_true(status == 200 and payload.get('ok'), login_name + ' 无团队用户无法登录')
        assert_true(payload.get('mustChangePassword'), login_name + ' 未要求首次改密')
        user = payload['user']
        assert_true(not can(db, user, 'user.manage'), login_name + ' 不应拥有用户管理权限')
        assert_true(not can(db, user, 'organization.manage'), login_name + ' 不应拥有企业管理权限')
    payload, status = login(db, 'jubaopen', 'observer.org', P1_PASSWORD)
    assert_true(can(db, payload['user'], 'organization.read'), '组织观察员缺少企业只读权限')
    payload, status = login(db, 'jubaopen', 'research.spec', P1_PASSWORD)
    assert_true(can(db, payload['user'], 'team.read'), '无团队的工作区只读用户在默认全球工作区下应能读取团队')
    payload, status = login(db, 'jubaopen', 'sales.jbp', P1_PASSWORD)
    assert_true(can(db, payload['user'], 'contact.update', team_id='TEAM-JBP'), '聚宝盆业务员在所属团队内应能更新联系人')
    assert_true(not can(db, payload['user'], 'contact.update', team_id='TEAM-ZCM'), '聚宝盆业务员不应获得其他团队写权限')


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
    print('P1 验收通过：组织预设、8 个模板用户、无团队登录、团队多选、默认全球工作区和幂等执行完成')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
