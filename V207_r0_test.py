#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R0 基线验收：全新 Schema 211 初始化、幂等重启和关键入口。"""
import argparse
import json
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from V207_shared_db import Database, validate_schema211_readonly
from V207_version import SCHEMA_VERSION


def _configure_output():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure:
            reconfigure(encoding='utf-8', errors='replace')


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def request_json(url, method='GET', body=None):
    data = None if body is None else json.dumps(body).encode('utf-8')
    request = Request(url, data=data, method=method, headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode('utf-8'))


def test_database_baseline(db_path):
    db = Database(str(db_path))
    db.initialize({
        'organization_id': 'r0-org',
        'organization_name': 'R0 Test Organization',
        'workspace_id': 'r0-workspace',
        'workspace_name': 'R0 Workspace',
        'team_id': 'r0-team',
        'team_name': 'R0 Team',
        'admin_user_id': 'r0-admin',
        'admin_login': 'r0-admin',
        'admin_display_name': 'R0 Admin',
        'admin_password': 'R0-password-123',
    })
    validate_schema211_readonly(db_path)
    with db.tx(False) as c:
        version = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        migration_ids = {row[0] for row in c.execute('SELECT migration_id FROM schema_migrations')}
        assert_true(version == str(SCHEMA_VERSION), 'schema_version is not 211')
        assert_true({'V211_030_channel_and_source_types', 'V211_040_sources_type_id',
                     'V211_050_touchpoints_campaigns_enhance'} <= migration_ids,
                    'V211 dictionary migrations are incomplete')
    db.initialize()
    validate_schema211_readonly(db_path)


def test_deprecated_user_endpoint(base_url):
    status, payload = request_json(base_url + '/api/v207/center/user', 'POST', {})
    assert_true(status == 410, 'deprecated user endpoint must return HTTP 410')
    assert_true(payload.get('code') == 'DEPRECATED', 'deprecated user endpoint code mismatch')


def main():
    _configure_output()
    parser = argparse.ArgumentParser(description='Jubaopen R0 baseline acceptance test')
    parser.add_argument('--server-url', help='optional running server URL, e.g. http://127.0.0.1:8765')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='jubaopen-r0-') as temp_dir:
        test_database_baseline(Path(temp_dir) / 'r0.db')
    if args.server_url:
        test_deprecated_user_endpoint(args.server_url.rstrip('/'))
    print('R0 验收通过：Schema 211 基线、迁移记录、幂等重启校验完成')
    if args.server_url:
        print('R0 验收通过：旧用户创建入口返回 410 DEPRECATED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
