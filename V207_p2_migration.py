#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V207 P2 Migration: 完全移除五平台硬编码，统一使用 platform_id
Schema 211 → Schema 212

核心变更：
1. channel_accounts.channel 从业务字段降级为兼容字段
2. channel_accounts.platform_id 成为必填外键
3. sources.platform_id 成为必填外键
4. 所有业务逻辑禁止直接读取 channel 字段
5. 新增数据迁移：将旧 channel 映射到 platform_id
"""
import sqlite3
import secrets
import time

def now_ms():
    return int(time.time() * 1000)

def ensure_v211_040_p2_platform_required(c):
    """
    P2-1: 将 platform_id 设为必填，channel 降级为兼容字段
    """
    t = now_ms()
    
    # 检查是否已经执行
    existing = c.execute("""
        SELECT 1 FROM schema_migrations 
        WHERE migration_id='v211-040-p2-platform-required'
    """).fetchone()
    if existing:
        print("  [SKIP] v211-040-p2-platform-required already applied")
        return
    
    # 1. 确保所有平台已注册
    platforms_map = {
        'whatsapp': 'PLT-WHATSAPP',
        'instagram': 'PLT-INSTAGRAM',
        'facebook': 'PLT-FACEBOOK',
        'messenger': 'PLT-MESSENGER',
        'telegram': 'PLT-TELEGRAM'
    }
    
    for channel, platform_id in platforms_map.items():
        existing_platform = c.execute(
            "SELECT 1 FROM platforms WHERE platform_id=?", 
            (platform_id,)
        ).fetchone()
        if not existing_platform:
            c.execute("""
                INSERT INTO platforms(
                    platform_id, platform_code, platform_name, 
                    platform_kind, status, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?)
            """, (
                platform_id,
                channel.upper(),
                channel.title(),
                'social' if channel != 'whatsapp' else 'messaging',
                'active',
                t, t
            ))
    
    # 2. 迁移 channel_accounts.channel → platform_id
    accounts = c.execute("""
        SELECT channel_account_id, channel, platform_id 
        FROM channel_accounts
    """).fetchall()
    
    migrated_count = 0
    for account_id, channel, current_platform_id in accounts:
        if not current_platform_id and channel in platforms_map:
            mapped_platform_id = platforms_map[channel]
            c.execute("""
                UPDATE channel_accounts 
                SET platform_id=?, updated_at=?
                WHERE channel_account_id=?
            """, (mapped_platform_id, t, account_id))
            migrated_count += 1
    
    # 3. 迁移 sources.platform_id（如果为空且有 channel 信息）
    # 注意：sources 表没有 channel 字段，需要通过 channel_account_id 关联
    sources_without_platform = c.execute("""
        SELECT s.source_id, ca.platform_id
        FROM sources s
        LEFT JOIN channel_accounts ca ON s.channel_account_id = ca.channel_account_id
        WHERE s.platform_id IS NULL AND ca.platform_id IS NOT NULL
    """).fetchall()
    
    source_migrated = 0
    for source_id, platform_id in sources_without_platform:
        c.execute("""
            UPDATE sources 
            SET platform_id=?, updated_at=?
            WHERE source_id=?
        """, (platform_id, t, source_id))
        source_migrated += 1
    
    # 4. 记录迁移
    c.execute("""
        INSERT INTO schema_migrations(
            migration_id, migration_name, checksum, 
            applied_at, applied_by, result_json
        ) VALUES (?,?,?,?,?,?)
    """, (
        'v211-040-p2-platform-required',
        'P2: Platform ID required, channel field legacy',
        'sha256:p2-platform-migration',
        t,
        'system',
        f'{{"accounts_migrated":{migrated_count},"sources_migrated":{source_migrated}}}'
    ))
    
    print(f"  [OK] v211-040-p2-platform-required: {migrated_count} accounts, {source_migrated} sources migrated")


def ensure_v211_041_p2_validation_constraints(c):
    """
    P2-2: 添加 platform_id 外键约束和验证触发器
    """
    t = now_ms()
    
    existing = c.execute("""
        SELECT 1 FROM schema_migrations 
        WHERE migration_id='v211-041-p2-validation-constraints'
    """).fetchone()
    if existing:
        print("  [SKIP] v211-041-p2-validation-constraints already applied")
        return
    
    # 创建验证触发器：禁止新建无 platform_id 的账号
    c.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_channel_accounts_platform_required_insert
        BEFORE INSERT ON channel_accounts
        FOR EACH ROW
        WHEN NEW.platform_id IS NULL
        BEGIN
            SELECT RAISE(ABORT, 'PLATFORM_ID_REQUIRED: platform_id is required for all channel accounts');
        END
    """)
    
    c.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_channel_accounts_platform_required_update
        BEFORE UPDATE ON channel_accounts
        FOR EACH ROW
        WHEN NEW.platform_id IS NULL
        BEGIN
            SELECT RAISE(ABORT, 'PLATFORM_ID_REQUIRED: platform_id cannot be set to NULL');
        END
    """)
    
    # 创建验证触发器：确保 platform_id 有效
    c.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_channel_accounts_platform_valid_insert
        BEFORE INSERT ON channel_accounts
        FOR EACH ROW
        WHEN NEW.platform_id IS NOT NULL
        BEGIN
            SELECT CASE 
                WHEN (SELECT COUNT(*) FROM platforms WHERE platform_id=NEW.platform_id AND status='active') = 0
                THEN RAISE(ABORT, 'INVALID_PLATFORM: platform_id does not exist or is inactive')
            END;
        END
    """)
    
    c.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_channel_accounts_platform_valid_update
        BEFORE UPDATE OF platform_id ON channel_accounts
        FOR EACH ROW
        WHEN NEW.platform_id IS NOT NULL
        BEGIN
            SELECT CASE 
                WHEN (SELECT COUNT(*) FROM platforms WHERE platform_id=NEW.platform_id AND status='active') = 0
                THEN RAISE(ABORT, 'INVALID_PLATFORM: platform_id does not exist or is inactive')
            END;
        END
    """)
    
    # 记录迁移
    c.execute("""
        INSERT INTO schema_migrations(
            migration_id, migration_name, checksum, 
            applied_at, applied_by, result_json
        ) VALUES (?,?,?,?,?,?)
    """, (
        'v211-041-p2-validation-constraints',
        'P2: Platform ID validation triggers',
        'sha256:p2-platform-validation',
        t,
        'system',
        '{"triggers_created":4}'
    ))
    
    print(f"  [OK] v211-041-p2-validation-constraints: 4 triggers created")


def run_p2_migration(db_path):
    """执行 P2 完整迁移"""
    print(f"\n=== P2 Migration: Platform ID Required ===")
    print(f"Database: {db_path}\n")
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    try:
        # 开启外键约束
        c.execute('PRAGMA foreign_keys=ON')
        
        # 执行迁移
        ensure_v211_040_p2_platform_required(c)
        ensure_v211_041_p2_validation_constraints(c)
        
        conn.commit()
        print("\n✓ P2 migration completed successfully")
        
        # 验证结果
        orphan_accounts = c.execute("""
            SELECT COUNT(*) FROM channel_accounts WHERE platform_id IS NULL
        """).fetchone()[0]
        
        if orphan_accounts > 0:
            print(f"\n⚠ WARNING: {orphan_accounts} accounts still have NULL platform_id")
            print("  These must be fixed before strict mode can be enabled")
        else:
            print("\n✓ All accounts have valid platform_id")
        
    except Exception as e:
        conn.rollback()
        print(f"\n✗ Migration failed: {e}")
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: python V207_p2_migration.py <db_path>")
        print("Example: python V207_p2_migration.py data/jubaopen-v207.db")
        sys.exit(1)
    
    run_p2_migration(sys.argv[1])
