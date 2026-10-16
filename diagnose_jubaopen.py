#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only diagnostic collector; does not import project code or modify DB."""
import argparse
import ast
import hashlib
import json
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

COMMIT = "0339640d7dde42b592c053ee7843c7d3500983ad"
BASE = f"https://raw.githubusercontent.com/jesse14139-afk/jubaopen/{COMMIT}/"
FILES = [
    "V207_shared_db.py",
    "V207_center_service.py",
    "V207_security.py",
    "V207_core.py",
    "V207_admin_api.py",
    "V208_api.py",
    "V208_collector_service.py",
    "V208_contact_center_service.py",
    "V208_follow_up_notification_service.py",
    "setup/test_db_concurrency_hotfix.py",
    "V207_version.py",
    "extension/background/service-worker.js",
]
TARGETS = {
    "Database", "safe_route", "route", "login", "actor_from_token",
    "permissions", "session_context", "plugin_actor", "heartbeat",
    "poll_notifications", "start_scanner", "collect_messages",
    "list_contacts", "list_conversations",
}

def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def collect_source(out):
    report = []
    manifest = []
    for name in FILES:
        try:
            request = urllib.request.Request(
                BASE + name, headers={"User-Agent": "JubaOpen-ReadOnly-Audit"}
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
            target = out / "source" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            text = raw.decode("utf-8-sig")
            manifest.append({
                "path": name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "status": "downloaded",
            })
            if not name.endswith(".py"):
                continue
            tree = ast.parse(text, filename=name)
            lines = text.splitlines()
            # Only inspect top-level definitions and direct class methods.
            nodes = []
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    nodes.append(node)
                elif isinstance(node, ast.ClassDef):
                    nodes.append(node)
                    if node.name != "Database":
                        nodes.extend(
                            x for x in node.body
                            if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
                        )
            for node in nodes:
                start = min(
                    [node.lineno] +
                    [x.lineno for x in getattr(node, "decorator_list", [])]
                )
                body = "\n".join(lines[start - 1:node.end_lineno])
                selected = node.name in TARGETS
                # Static candidates, NOT confirmed lock holders.
                candidate = (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and any(x in body for x in (
                        "db.tx(", "DB.tx(", "db.write(",
                        "BEGIN IMMEDIATE", "DATABASE_BUSY",
                    ))
                )
                if selected or candidate:
                    report.append(
                        f"\n=== {name}:{start}-{node.end_lineno} "
                        f"{node.name} [static evidence only] ===\n{body}\n"
                    )
        except Exception as exc:
            manifest.append({
                "path": name, "status": "failed", "error": str(exc),
            })
    write_json(out / "source_manifest.json", manifest)
    (out / "source_focus.txt").write_text(
        "".join(report), encoding="utf-8"
    )
    return sum(x["status"] == "failed" for x in manifest)

def collect_database(db_path, out):
    path = Path(db_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("Database path is not a file")
    result = {
        "python": sys.version,
        "collector_sqlite_version": sqlite3.sqlite_version,
        "note": (
            "Read-only observation. busy_timeout belongs to this collector "
            "connection, not the application's connections. "
            "No integrity check, load test, migration or checkpoint is run."
        ),
    }
    connection = sqlite3.connect(
        path.as_uri() + "?mode=ro", uri=True, timeout=2.0
    )
    try:
        connection.execute("PRAGMA query_only=ON")
        for pragma in (
            "journal_mode", "page_size", "page_count",
            "freelist_count", "user_version",
        ):
            result[pragma] = connection.execute(
                "PRAGMA " + pragma
            ).fetchone()[0]
        result["indexes"] = [
            dict(zip(("name", "table", "sql"), row))
            for row in connection.execute(
                "SELECT name,tbl_name,sql FROM sqlite_master "
                "WHERE type='index' ORDER BY tbl_name,name"
            )
        ]
    finally:
        connection.close()
    result["files"] = {}
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        result["files"][suffix or "database"] = (
            candidate.stat().st_size if candidate.exists() else None
        )
    write_json(out / "database_readonly.json", result)

def collect_logs(log_dir, out):
    pattern = re.compile(
        r"DATABASE_BUSY|database (?:is |table is |schema is )?locked|"
        r"SQLITE_(?:BUSY|LOCKED)|database is busy",
        re.IGNORECASE,
    )
    sections = []
    for path in sorted(Path(log_dir).rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".log", ".txt"):
            continue
        if path.stat().st_size > 50 * 1024 * 1024:
            sections.append(f"\nSKIPPED oversized log: {path.name}\n")
            continue
        lines = path.read_text(
            encoding="utf-8-sig", errors="replace"
        ).splitlines()
        hits = [i for i, line in enumerate(lines) if pattern.search(line)]
        emitted = set()
        for hit in hits[:200]:
            sections.append(
                f"\n=== {path.name}: error near line {hit + 1} ===\n"
            )
            for i in range(max(0, hit - 8), min(len(lines), hit + 13)):
                if i not in emitted:
                    sections.append(f"{i + 1}: {lines[i]}\n")
                    emitted.add(i)
        sections.append(
            f"\nSUMMARY {path.name}: matched={len(hits)} "
            "maximum 200 contexts exported\n"
        )
    (out / "log_context_REVIEW_BEFORE_SHARING.txt").write_text(
        "".join(sections), encoding="utf-8"
    )

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", help="Optional existing production DB; read-only")
    parser.add_argument("--logs", help="Optional log folder; review before sharing")
    parser.add_argument("--out", default="jubaopen_diagnostics")
    args = parser.parse_args()
    if sys.version_info < (3, 9):
        parser.error("Python 3.9+ is required")
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / "collection.json", {
        "commit": COMMIT,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "scope": "source download and read-only observations; no runtime test",
    })
    failures = collect_source(out)
    for label, value, operation in (
        ("database", args.db, collect_database),
        ("logs", args.logs, collect_logs),
    ):
        if value:
            try:
                operation(value, out)
            except Exception as exc:
                failures += 1
                (out / f"{label}_error.txt").write_text(
                    str(exc), encoding="utf-8"
                )
    print(f"Output: {out}")
    print(f"Collection failures: {failures}")
    print("Review log excerpts for secrets and personal data before sharing.")
    print("This output does NOT identify the runtime lock holder by itself.")
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())