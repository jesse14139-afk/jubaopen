-- JubaOpen Schema 223: Threads platform registration
-- 本迁移使用幂等 INSERT OR IGNORE，不覆盖管理员已有配置。

INSERT OR IGNORE INTO platforms(
    platform_id,
    platform_code,
    platform_name,
    platform_kind,
    status,
    capabilities_json,
    metadata_json,
    created_at,
    updated_at
)
SELECT
    'threads',
    'threads',
    'Threads',
    'social',
    'active',
    '{"messaging":true,"domCollection":true,"readonlyByDefault":true}',
    '{"provider":"Meta","adapterVersion":"210.3.0"}',
    CAST(strftime('%s','now') AS INTEGER) * 1000,
    CAST(strftime('%s','now') AS INTEGER) * 1000
WHERE EXISTS(
    SELECT 1
    FROM sqlite_master
    WHERE type='table' AND name='platforms'
);

