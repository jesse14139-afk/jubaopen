#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P1 渠道类型与来源类型字典 API 服务（V207.8.0 / Schema 211）

本模块处理：
- channel_types 的 CRUD
- source_type_definitions 的 CRUD

API 路径：
- GET  /api/v207/admin/channel-types
- GET  /api/v207/admin/channel-types/:id
- PATCH /api/v207/admin/channel-types/:id
- GET  /api/v207/admin/source-types
- GET  /api/v207/admin/source-types/:id
- PATCH /api/v207/admin/source-types/:id
"""
import json
from V207_shared_db import now_ms, dumps, loads
from V207_security import can, is_platform_admin


def _rows(c, sql, args=()):
    return [dict(x) for x in c.execute(sql, args)]


def _one(c, sql, args=()):
    r = c.execute(sql, args).fetchone()
    return dict(r) if r else None


def handle_channel_type(db, a, org, m, ident, q, body):
    """
    处理渠道类型字典 API。
    - 平台管理员可管理
    - 企业管理员可读取
    """
    platform = is_platform_admin(db, a)

    if m == 'GET' and not ident:
        # 列出所有渠道类型
        with db.tx(False) as c:
            rows = _rows(c, """
                SELECT ct.*, p.platform_name, p.platform_code
                FROM channel_types ct
                LEFT JOIN platforms p ON p.platform_id = ct.platform_id
                ORDER BY ct.sort_order, ct.name
            """)
        return {'ok': True, 'items': rows}, 200

    if m == 'GET' and ident:
        # 获取单个渠道类型
        with db.tx(False) as c:
            row = _one(c, """
                SELECT ct.*, p.platform_name, p.platform_code
                FROM channel_types ct
                LEFT JOIN platforms p ON p.platform_id = ct.platform_id
                WHERE ct.channel_type_id = ?
            """, (ident,))
        if not row:
            return {'ok': False, 'code': 'NOT_FOUND', 'message': '渠道类型不存在'}, 404
        return {'ok': True, 'item': row}, 200

    if m == 'PATCH' and ident:
        # 修改渠道类型（仅平台管理员）
        if not platform:
            return {'ok': False, 'code': 'FORBIDDEN', 'message': '仅平台管理员可修改渠道类型'}, 403

        with db.tx() as c:
            existing = _one(c, "SELECT * FROM channel_types WHERE channel_type_id = ?", (ident,))
            if not existing:
                return {'ok': False, 'code': 'NOT_FOUND', 'message': '渠道类型不存在'}, 404

            updates = []
            args = []
            for field in ('name', 'description', 'direction', 'is_active', 'sort_order'):
                if field in body:
                    val = body[field]
                    if field == 'is_active':
                        val = 1 if val else 0
                    updates.append(f"{field} = ?")
                    args.append(val)

            if updates:
                updates.append("updated_at = ?")
                args.append(now_ms())
                args.append(ident)
                c.execute(
                    f"UPDATE channel_types SET {', '.join(updates)} WHERE channel_type_id = ?",
                    tuple(args)
                )

            new_row = _one(c, "SELECT * FROM channel_types WHERE channel_type_id = ?", (ident,))

        return {'ok': True, 'item': new_row}, 200

    return {'ok': False, 'code': 'NOT_FOUND', 'message': 'API 不存在'}, 404


def handle_source_type(db, a, org, m, ident, q, body):
    """
    处理来源类型字典 API。
    - 平台管理员可管理
    - 企业管理员可读取
    """
    platform = is_platform_admin(db, a)

    if m == 'GET' and not ident:
        # 列出所有来源类型
        with db.tx(False) as c:
            rows = _rows(c, """
                SELECT * FROM source_type_definitions
                ORDER BY sort_order, name
            """)
        return {'ok': True, 'items': rows}, 200

    if m == 'GET' and ident:
        # 获取单个来源类型
        with db.tx(False) as c:
            row = _one(c, "SELECT * FROM source_type_definitions WHERE source_type_id = ?", (ident,))
        if not row:
            return {'ok': False, 'code': 'NOT_FOUND', 'message': '来源类型不存在'}, 404
        return {'ok': True, 'item': row}, 200

    if m == 'PATCH' and ident:
        # 修改来源类型（仅平台管理员）
        if not platform:
            return {'ok': False, 'code': 'FORBIDDEN', 'message': '仅平台管理员可修改来源类型'}, 403

        with db.tx() as c:
            existing = _one(c, "SELECT * FROM source_type_definitions WHERE source_type_id = ?", (ident,))
            if not existing:
                return {'ok': False, 'code': 'NOT_FOUND', 'message': '来源类型不存在'}, 404

            updates = []
            args = []
            for field in ('name', 'description', 'is_active', 'sort_order'):
                if field in body:
                    val = body[field]
                    if field == 'is_active':
                        val = 1 if val else 0
                    updates.append(f"{field} = ?")
                    args.append(val)

            if updates:
                updates.append("updated_at = ?")
                args.append(now_ms())
                args.append(ident)
                c.execute(
                    f"UPDATE source_type_definitions SET {', '.join(updates)} WHERE source_type_id = ?",
                    tuple(args)
                )

            new_row = _one(c, "SELECT * FROM source_type_definitions WHERE source_type_id = ?", (ident,))

        return {'ok': True, 'item': new_row}, 200

    return {'ok': False, 'code': 'NOT_FOUND', 'message': 'API 不存在'}, 404
