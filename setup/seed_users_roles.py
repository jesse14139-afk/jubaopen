#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1 企业角色、8 个模板用户，以及团队业务线/市场覆盖。

约束：
- 授权只写入 role_bindings；team_memberships 只表示成员事实
- 8 人全部显式给出登录名、显示名、主职位、主部门、主团队或无团队、附属团队、角色与数据范围
- 不按姓名或职位自动授予企业管理员等高权限
- 无团队用户必须能登录
"""
from V207_shared_db import hash_password, now_ms
from V207_security import grant_binding_in_tx

P1_PASSWORD = 'jubaopen518518'
P1_WORKSPACE_ID = 'ws-global'

READ_PERMS = (
    'organization.read', 'team.read', 'user.read', 'role.read',
    'account.read', 'source.read', 'campaign.read', 'device.read', 'contact.read',
)
RISK_PERMS = READ_PERMS + ('audit.read',)
WS_OPERATOR_PERMS = (
    'team.read', 'account.read', 'source.read', 'device.read',
    'contact.read', 'contact.update',
)
WS_READONLY_PERMS = (
    'team.read', 'account.read', 'source.read', 'campaign.read', 'device.read', 'contact.read',
)

P1_ROLES = (
    {
        'role_id': 'role-jbp-sales-self',
        'name': '业务员本人客户岗',
        'scope_level': 'self',
        'role_code': 'jbp_sales_self',
        'description': '普通业务员可在已授权设备和本人作用域内采集会话、新建并维护本人客户。',
        'permissions': ('collector.session.issue','collector.write','collector.account.resolve','collector.conversation.resolve','contact.create','contact.read.assigned','contact.update.assigned','conversation.read.self','message.read.self','transfer.create','contact.read','contact.update','team.read','account.read','source.read','source.path.read','campaign.read','touchpoint.read','attribution.read','contact.identity.link','contact.duplicate.review'),
    },
    {
        'role_id': 'role-jbp-risk-admin',
        'name': '风控审计岗',
        'scope_level': 'organization',
        'role_code': 'jbp_risk_admin',
        'description': 'P1 保守企业角色：只读组织与审计，不含用户/角色/组织管理。',
        'permissions': RISK_PERMS,
    },
    {
        'role_id': 'role-jbp-org-readonly',
        'name': '企业只读观察员',
        'scope_level': 'organization',
        'role_code': 'jbp_org_readonly',
        'description': 'P1 保守企业角色：企业范围只读，不含审计与写操作。',
        'permissions': READ_PERMS,
    },
    {
        'role_id': 'role-jbp-ws-operator',
        'name': '工作区操作员',
        'scope_level': 'workspace',
        'role_code': 'jbp_ws_operator',
        'description': 'P1 工作区角色：联系人更新与资源只读，不含企业管理。',
        'permissions': WS_OPERATOR_PERMS,
    },
    {
        'role_id': 'role-jbp-ws-readonly',
        'name': '工作区只读员',
        'scope_level': 'workspace',
        'role_code': 'jbp_ws_readonly',
        'description': 'P1 工作区角色：工作区资源只读。',
        'permissions': WS_READONLY_PERMS,
    },
)

# 每个用户必须显式给出：登录名、显示名、主职位、主部门、主团队或无团队、附属团队、企业/工作区/团队角色、数据范围。
P1_USERS = (
    {
        'user_id': 'usr-p1-risk-spec',
        'login_name': 'risk.spec',
        'display_name': '风控专员',
        'position_id': 'POS-RISK-SPEC',
        'department_id': 'DEPT-RISK',
        'primary_team_id': None,
        'affiliate_teams': (),
        'org_role_id': 'role-jbp-risk-admin',
        'workspace_role_id': None,
        'team_role_id': None,
        'data_scope': ('organization', None),
    },
    {
        'user_id': 'usr-p1-auditor-spec',
        'login_name': 'auditor.spec',
        'display_name': '审计专员',
        'position_id': 'POS-AUDIT',
        'department_id': 'DEPT-RISK',
        'primary_team_id': None,
        'affiliate_teams': (),
        'org_role_id': 'role_auditor',
        'workspace_role_id': None,
        'team_role_id': None,
        'data_scope': ('organization', None),
    },
    {
        'user_id': 'usr-p1-research-spec',
        'login_name': 'research.spec',
        'display_name': '策略研究员',
        'position_id': 'POS-STRAT',
        'department_id': 'DEPT-RESEARCH',
        'primary_team_id': None,
        'affiliate_teams': (),
        'org_role_id': None,
        'workspace_role_id': 'role-jbp-ws-readonly',
        'team_role_id': None,
        'data_scope': ('workspace', P1_WORKSPACE_ID),
    },
    {
        'user_id': 'usr-p1-channel-spec',
        'login_name': 'channel.spec',
        'display_name': '渠道专员',
        'position_id': 'POS-CH-SPEC',
        'department_id': 'DEPT-CHANNEL',
        'primary_team_id': None,
        'affiliate_teams': (('TEAM-JBP', 'support'),),
        'org_role_id': None,
        'workspace_role_id': 'role-jbp-ws-operator',
        'team_role_id': None,
        'data_scope': ('workspace', P1_WORKSPACE_ID),
    },
    {
        'user_id': 'usr-p1-sales-jbp',
        'login_name': 'sales.jbp',
        'display_name': '聚宝盆业务员',
        'position_id': 'POS-SALES',
        'department_id': 'DEPT-BIZ',
        'primary_team_id': 'TEAM-JBP',
        'affiliate_teams': (),
        'org_role_id': None,
        'workspace_role_id': None,
        'team_role_id': 'role-jbp-sales-self',
        'membership_type': 'member',
        'data_scope': ('self', 'usr-p1-sales-jbp'),
    },
    {
        'user_id': 'usr-p1-sales-zcm',
        'login_name': 'sales.zcm',
        'display_name': '招财猫业务员',
        'position_id': 'POS-SALES',
        'department_id': 'DEPT-BIZ',
        'primary_team_id': 'TEAM-ZCM',
        'affiliate_teams': (),
        'org_role_id': None,
        'workspace_role_id': None,
        'team_role_id': 'role-jbp-sales-self',
        'membership_type': 'member',
        'data_scope': ('self', 'usr-p1-sales-zcm'),
    },
    {
        'user_id': 'usr-p1-lead-rjdj',
        'login_name': 'lead.rjdj',
        'display_name': '日进斗金团队经理',
        'position_id': 'POS-TEAM-LDR',
        'department_id': 'DEPT-BIZ',
        'primary_team_id': 'TEAM-RJDJ',
        'affiliate_teams': (),
        'org_role_id': None,
        'workspace_role_id': None,
        'team_role_id': 'role_teamlead',
        'membership_type': 'manager',
        'data_scope': ('team', 'TEAM-RJDJ'),
    },
    {
        'user_id': 'usr-p1-observer-org',
        'login_name': 'observer.org',
        'display_name': '组织观察员',
        'position_id': 'POS-OPS',
        'department_id': 'DEPT-BIZ',
        'primary_team_id': None,
        'affiliate_teams': (),
        'org_role_id': 'role-jbp-org-readonly',
        'workspace_role_id': None,
        'team_role_id': None,
        'data_scope': ('organization', None),
    },
)

P1_USER_LOGINS = tuple(user['login_name'] for user in P1_USERS)
NO_TEAM_LOGINS = tuple(user['login_name'] for user in P1_USERS if not user['primary_team_id'] and not user['affiliate_teams'])

TEAM_COVERAGE = (
    (
        'TEAM-JBP',
        (('BL-QUANT', 1), ('BL-ADVISOR', 0)),
        (('MKT-EUROPE', 1, 'descendants'), ('MKT-ASIA', 0, 'descendants')),
    ),
    (
        'TEAM-ZCM',
        (('BL-ADVISOR', 1),),
        (('MKT-AMERICAS', 1, 'descendants'), ('MKT-US', 0, 'direct')),
    ),
    (
        'TEAM-RJDJ',
        (('BL-QUANT', 1), ('BL-ADVISOR', 0)),
        (('MKT-UK', 1, 'direct'), ('MKT-DE', 0, 'direct'), ('MKT-FR', 0, 'direct')),
    ),
)

FORBIDDEN_TEMPLATE_ROLES = frozenset(('role_orgadmin', 'role_superadmin'))


def _ensure_roles(c, org_id):
    created = 0
    for role in P1_ROLES:
        existing = c.execute('SELECT 1 FROM roles WHERE role_id=?', (role['role_id'],)).fetchone()
        if not existing:
            c.execute(
                "INSERT INTO roles(role_id,organization_id,name,scope_level,status,role_code,description,is_system) VALUES(?,?,?,?,?,?,?,0)",
                (role['role_id'], org_id, role['name'], role['scope_level'], 'active', role['role_code'], role['description']),
            )
            created += 1
        for perm in role['permissions']:
            c.execute('INSERT OR IGNORE INTO role_permissions(role_id,permission_key) VALUES(?,?)', (role['role_id'], perm))
    return created


def _ensure_team_coverage(c, org_id, n):
    created_bl = created_mkt = 0
    for team_id, lines, markets in TEAM_COVERAGE:
        for line_id, primary in lines:
            if c.execute('SELECT 1 FROM team_business_lines WHERE team_id=? AND business_line_id=?', (team_id, line_id)).fetchone():
                continue
            c.execute(
                "INSERT INTO team_business_lines(team_id,business_line_id,organization_id,is_primary,status,created_at,updated_at) VALUES(?,?,?,?,'active',?,?)",
                (team_id, line_id, org_id, primary, n, n),
            )
            created_bl += 1
        for market_id, primary, scope_type in markets:
            if c.execute('SELECT 1 FROM team_markets WHERE team_id=? AND market_id=?', (team_id, market_id)).fetchone():
                continue
            c.execute(
                "INSERT INTO team_markets(team_id,market_id,organization_id,is_primary,scope_type,status,created_at,updated_at) VALUES(?,?,?,?,?,'active',?,?)",
                (team_id, market_id, org_id, primary, scope_type, n, n),
            )
            created_mkt += 1
    return created_bl, created_mkt


def _granter(c, org_id):
    row = c.execute(
        "SELECT u.user_id FROM users u JOIN platform_administrators p ON p.user_id=u.user_id WHERE u.organization_id=? ORDER BY p.is_builtin DESC, u.created_at LIMIT 1",
        (org_id,),
    ).fetchone()
    if row:
        return row[0]
    row = c.execute("SELECT user_id FROM users WHERE organization_id=? ORDER BY created_at LIMIT 1", (org_id,)).fetchone()
    return row[0] if row else None


def _bind(c, user_id, role_id, org_id, scope_type, scope_id, granted_by):
    if not role_id:
        return
    if role_id in FORBIDDEN_TEMPLATE_ROLES:
        raise RuntimeError('P1_FORBIDDEN_ROLE: 模板用户不得授予 ' + role_id)
    grant_binding_in_tx(c, user_id, role_id, org_id, scope_type, scope_id, granted_by)


def _ensure_users(c, org_id, workspace_id, n, granted_by):
    """创建缺失用户，并对已存在模板用户逐项补齐关系；绝不重置已有密码。"""
    created = 0
    password_hash = salt = iterations = None
    for spec in P1_USERS:
        if spec['org_role_id'] in FORBIDDEN_TEMPLATE_ROLES or spec['workspace_role_id'] in FORBIDDEN_TEMPLATE_ROLES or spec['team_role_id'] in FORBIDDEN_TEMPLATE_ROLES:
            raise RuntimeError('P1_FORBIDDEN_ROLE: 模板用户不得授予企业管理员或平台超级管理员')
        row = c.execute(
            "SELECT user_id FROM users WHERE organization_id=? AND login_name=? COLLATE NOCASE",
            (org_id, spec['login_name']),
        ).fetchone()
        if row:
            uid = row[0]
            c.execute("UPDATE users SET status='active',updated_at=? WHERE user_id=?", (n, uid))
        else:
            uid = spec['user_id']
            if password_hash is None:
                password_hash, salt, iterations = hash_password(P1_PASSWORD)
            c.execute(
                "INSERT INTO users(user_id,organization_id,login_name,display_name,status,created_at,updated_at) VALUES(?,?,?,?,? ,?,?)",
                (uid, org_id, spec['login_name'], spec['display_name'], 'active', n, n),
            )
            c.execute(
                'INSERT INTO user_credentials(user_id,password_hash,salt,iterations,must_change,updated_at) VALUES(?,?,?,?,1,?)',
                (uid, password_hash, salt, iterations, n),
            )
            created += 1
        # 仅在凭据完全缺失时为模板账号创建初始凭据，不覆盖已有密码。
        if not c.execute('SELECT 1 FROM user_credentials WHERE user_id=?', (uid,)).fetchone():
            if password_hash is None:
                password_hash, salt, iterations = hash_password(P1_PASSWORD)
            c.execute('INSERT INTO user_credentials(user_id,password_hash,salt,iterations,must_change,updated_at) VALUES(?,?,?,?,1,?)', (uid,password_hash,salt,iterations,n))
        c.execute("UPDATE user_positions SET is_primary=0,updated_at=? WHERE user_id=? AND is_primary=1 AND position_id<>?", (n,uid,spec['position_id']))
        c.execute(
            "INSERT INTO user_positions(user_id,position_id,organization_id,is_primary,status,created_at,updated_at) VALUES(?,?,?,1,'active',?,?) "
            "ON CONFLICT(user_id,position_id) DO UPDATE SET organization_id=excluded.organization_id,is_primary=1,status='active',updated_at=excluded.updated_at",
            (uid,spec['position_id'],org_id,n,n),
        )
        desired = []
        if spec['primary_team_id']:
            desired.append((spec['primary_team_id'], spec.get('membership_type') or 'member', 1))
        desired.extend((team_id, kind, 0) for team_id, kind in spec['affiliate_teams'])
        if spec['primary_team_id']:
            c.execute("UPDATE team_memberships SET is_primary=0,updated_at=? WHERE user_id=? AND is_primary=1 AND team_id<>?", (n,uid,spec['primary_team_id']))
        for team_id, kind, primary in desired:
            c.execute(
                "INSERT INTO team_memberships(user_id,team_id,membership_type,is_primary,status,joined_at,left_at,created_at,updated_at) VALUES(?,?,?,?, 'active',?,NULL,?,?) "
                "ON CONFLICT(user_id,team_id) DO UPDATE SET membership_type=excluded.membership_type,is_primary=excluded.is_primary,status='active',left_at=NULL,updated_at=excluded.updated_at",
                (uid,team_id,kind,primary,n,n,n),
            )
        _bind(c, uid, spec['org_role_id'], org_id, 'organization', org_id, granted_by)
        _bind(c, uid, spec['workspace_role_id'], org_id, 'workspace', workspace_id, granted_by)
        if spec['team_role_id']:
            scope_type, scope_id = spec.get('data_scope') or ('team', spec['primary_team_id'])
            if scope_type == 'self':
                # Upgrade existing installs: remove the historical team-wide operator grant.
                c.execute("DELETE FROM role_bindings WHERE user_id=? AND organization_id=? AND scope_type='team' AND role_id IN ('role_operator','role-jbp-sales-self')", (uid, org_id))
            _bind(c, uid, spec['team_role_id'], org_id, scope_type, scope_id, granted_by)
    return created


def seed_p1_people(db, org_id='jubaopen', workspace_id=P1_WORKSPACE_ID):
    """幂等写入 P1 角色、团队覆盖和 8 个模板用户。"""
    n = now_ms()
    with db.tx() as c:
        granter = _granter(c, org_id)
        if not granter:
            raise RuntimeError('P1_GRANTER_MISSING: 缺少可用于授权的企业用户')
        if not c.execute("SELECT 1 FROM workspaces WHERE workspace_id=? AND organization_id=? AND status='active'", (workspace_id, org_id)).fetchone():
            raise RuntimeError('P1_WORKSPACE_MISSING: ' + workspace_id)
        roles_created = _ensure_roles(c, org_id)
        bl_created, mkt_created = _ensure_team_coverage(c, org_id, n)
        users_created = _ensure_users(c, org_id, workspace_id, n, granter)
    return {
        'roles_created': roles_created,
        'users_created': users_created,
        'team_business_lines_created': bl_created,
        'team_markets_created': mkt_created,
    }
