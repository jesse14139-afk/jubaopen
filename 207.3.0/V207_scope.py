# -*- coding: utf-8 -*-
"""V207 统一多租户作用域解析器。

所有领域服务通过本模块校验引用对象，客户端提供的 organization/workspace/team
仅表达业务意图，最终归属以数据库对象及登录主体为准。
"""

SCOPE_SPECS = {
    "workspace": ("workspaces", "workspace_id"),
    "team": ("teams", "team_id"),
    "account": ("channel_accounts", "channel_account_id"),
    "contact": ("contacts", "contact_id"),
    "source": ("sources", "source_id"),
    "campaign": ("campaigns", "campaign_id"),
    "touchpoint": ("source_touchpoints", "touchpoint_id"),
}


def _one(cursor, sql, args=()):
    row = cursor.execute(sql, args).fetchone()
    return dict(row) if row else None


def resolve_scope(cursor, organization_id, **references):
    """解析引用并强制同企业、同工作区。

    返回已解析对象以及 ``organization_id``、``workspace_id``。平台是系统级注册表，
    不参与租户归属推导；企业级渠道账号没有固定工作区，其可用工作区由团队授权决定。
    """
    if not organization_id:
        raise ValueError("ORGANIZATION_REQUIRED")
    found = {"organization_id": str(organization_id)}
    workspace_ids = set()
    for kind, entity_id in references.items():
        if entity_id in (None, ""):
            continue
        if kind not in SCOPE_SPECS:
            raise ValueError("UNSUPPORTED_SCOPE")
        table, key = SCOPE_SPECS[kind]
        row = _one(
            cursor,
            f"SELECT * FROM {table} WHERE {key}=? AND organization_id=?",
            (str(entity_id), str(organization_id)),
        )
        if not row:
            raise LookupError(kind)
        found[kind] = row
        if row.get("workspace_id"):
            workspace_ids.add(row["workspace_id"])
    if len(workspace_ids) > 1:
        raise ValueError("SCOPE_MISMATCH")
    found["workspace_id"] = next(iter(workspace_ids), None)
    return found


def require_platform(cursor, platform_id, active_only=False):
    """解析系统级平台；平台本身不接受企业归属字段。"""
    if not platform_id:
        return None
    sql = "SELECT * FROM platforms WHERE platform_id=?"
    args = (str(platform_id),)
    if active_only:
        sql += " AND status='active'"
    row = _one(cursor, sql, args)
    if not row:
        raise LookupError("platform")
    return row


def require_account_grant(cursor, organization_id, account_id, team_id):
    """校验账号和团队同企业，并返回现有授权（授权可为空）。"""
    scope = resolve_scope(
        cursor, organization_id, account=account_id, team=team_id
    )
    scope["grant"] = _one(
        cursor,
        "SELECT * FROM team_channel_accounts WHERE team_id=? AND channel_account_id=?",
        (str(team_id), str(account_id)),
    )
    return scope
