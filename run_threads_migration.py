#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


REQUIRED_PLATFORM_COLUMNS = {
    "platform_id",
    "platform_code",
    "platform_name",
    "platform_kind",
    "status",
    "capabilities_json",
    "metadata_json",
    "created_at",
    "updated_at",
}


def stop(message):
    print(f"\n[失败] {message}")
    sys.exit(1)


def main():
    root = Path(__file__).resolve().parent
    sql_path = root / "setup" / "V223_threads_platform.sql"

    if not sql_path.is_file():
        stop(f"找不到迁移文件：{sql_path}")

    print("=" * 68)
    print("JubaOpen Threads 平台数据库迁移")
    print("=" * 68)
    print()
    print("请输入 JubaOpen SQLite 数据库文件的完整路径。")
    print(r"例如：C:\JubaOpen\data\jubaopen.db")
    print()

    raw = input("数据库路径：").strip().strip('"')
    if not raw:
        stop("没有输入数据库路径")

    db_path = Path(raw).expanduser().resolve()

    if not db_path.is_file():
        stop(f"数据库文件不存在：{db_path}")

    if db_path.stat().st_size == 0:
        stop("数据库文件为空，可能选择了错误的文件")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_name(
        f"{db_path.name}.before_threads_{timestamp}.bak"
    )

    print()
    print(f"数据库：{db_path}")
    print(f"备份到：{backup_path}")
    print(f"迁移文件：{sql_path}")
    print()

    confirmation = input("确认停止了 JubaOpen 并开始迁移？输入 YES：").strip()
    if confirmation != "YES":
        stop("用户取消，数据库没有被修改")

    connection = None

    try:
        # 先复制文件级备份。
        shutil.copy2(db_path, backup_path)

        connection = sqlite3.connect(
            str(db_path),
            timeout=30,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row

        # 检查 SQLite 文件完整性。
        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        if integrity != "ok":
            stop(f"数据库完整性检查失败：{integrity}")

        # 检查 platforms 表是否存在。
        table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table' AND name='platforms'
            """
        ).fetchone()

        if not table:
            stop(
                "当前数据库没有 platforms 表。"
                "可能选择了错误数据库，或者基础数据库尚未初始化。"
            )

        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(platforms)"
            ).fetchall()
        }

        missing = REQUIRED_PLATFORM_COLUMNS - columns
        if missing:
            stop(
                "platforms 表结构与迁移要求不一致，缺少字段："
                + ", ".join(sorted(missing))
            )

        existing = connection.execute(
            """
            SELECT
                platform_id,
                platform_code,
                platform_name,
                status
            FROM platforms
            WHERE lower(platform_id)='threads'
               OR lower(platform_code)='threads'
            """
        ).fetchall()

        if existing:
            print("\n数据库中已经存在 Threads 平台：")
            for row in existing:
                print(dict(row))

            print("\n不重复执行迁移。")
            print(f"备份文件仍已保留：{backup_path}")
            return

        sql = sql_path.read_text(encoding="utf-8")

        # 此迁移脚本只允许操作 platforms 表。
        lowered = sql.lower()
        forbidden = (
            "drop table",
            "drop index",
            "delete from",
            "truncate",
            "alter table",
            "attach database",
            "detach database",
            "vacuum",
        )

        detected = [word for word in forbidden if word in lowered]
        if detected:
            stop(
                "迁移文件包含当前安全执行器禁止的操作："
                + ", ".join(detected)
            )

        connection.execute("BEGIN IMMEDIATE")

        try:
            connection.executescript(sql)

            result = connection.execute(
                """
                SELECT
                    platform_id,
                    platform_code,
                    platform_name,
                    platform_kind,
                    status,
                    capabilities_json,
                    metadata_json
                FROM platforms
                WHERE lower(platform_id)='threads'
                   OR lower(platform_code)='threads'
                """
            ).fetchall()

            if len(result) != 1:
                raise RuntimeError(
                    "执行后没有得到唯一的 Threads 平台记录"
                )

            row = dict(result[0])

            if (
                str(row["platform_id"]).lower() != "threads"
                or str(row["platform_code"]).lower() != "threads"
                or row["status"] != "active"
            ):
                raise RuntimeError(
                    "Threads 平台记录内容不符合预期"
                )

            # executescript 可能根据 Python/SQLite 版本处理事务边界，
            # 因此只有事务仍处于活动状态时才显式提交。
            if connection.in_transaction:
                connection.execute("COMMIT")

        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

        print()
        print("=" * 68)
        print("迁移成功")
        print("=" * 68)
        print("Threads 平台记录：")
        print(row)
        print()
        print(f"迁移前备份：{backup_path}")
        print("现在可以重新启动 JubaOpen。")

    except Exception as exc:
        if connection and connection.in_transaction:
            try:
                connection.execute("ROLLBACK")
            except Exception:
                pass

        print(f"\n[迁移失败] {type(exc).__name__}: {exc}")
        print("请不要删除备份文件。")
        print(f"备份位置：{backup_path}")
        sys.exit(1)

    finally:
        if connection:
            connection.close()


if __name__ == "__main__":
    main()
