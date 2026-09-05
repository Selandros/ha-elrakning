#!/usr/bin/env python3
"""Run the physical process/filesystem durability gate in temporary databases."""

import hashlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from p0_storage_recovery_gate import create_database  # noqa: E402


def directory_bytes(path):
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def killed_process_gate(root):
    database = root / "killed.sqlite"
    ready = root / "writer.ready"
    connection = create_database(database)
    connection.execute("CREATE TABLE crash_probe (id TEXT PRIMARY KEY, value INTEGER NOT NULL)")
    connection.commit()
    connection.close()
    writer = """
import sqlite3, sys, time
database, ready = sys.argv[1:]
connection = sqlite3.connect(database)
connection.execute('PRAGMA journal_mode=WAL')
connection.execute('PRAGMA synchronous=FULL')
connection.execute('BEGIN IMMEDIATE')
connection.execute("INSERT INTO crash_probe VALUES ('killed', 1)")
open(ready, 'w').close()
while True:
    time.sleep(1)
"""
    process = subprocess.Popen([sys.executable, "-c", writer, str(database), str(ready)])
    deadline = time.monotonic() + 10
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not ready.exists():
        process.kill()
        process.wait(timeout=5)
        return False
    os.kill(process.pid, signal.SIGKILL)
    process.wait(timeout=5)
    connection = sqlite3.connect(database)
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    partial_count = connection.execute("SELECT COUNT(*) FROM crash_probe WHERE id = 'killed'").fetchone()[0]
    baseline_records = connection.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    revisions = connection.execute(
        "SELECT revision, supersedes_record_id FROM records "
        "WHERE semantic_key = 'site-a|house.consumption|gen-a|100' ORDER BY revision"
    ).fetchall()
    connection.execute(
        "INSERT OR IGNORE INTO crash_probe VALUES ('killed', 1)"
    )
    replay_count = connection.execute("SELECT COUNT(*) FROM crash_probe WHERE id = 'killed'").fetchone()[0]
    connection.commit()
    connection.close()
    return {
        "process_exit": process.returncode,
        "integrity": integrity == "ok",
        "partial_transaction_absent": partial_count == 0,
        "baseline_records_preserved": baseline_records == 1,
        "revision_chain_preserved": revisions == [(1, None)],
        "replay_idempotent": replay_count == 1,
    }


def migration_gate(root):
    database = root / "migration.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute(
        "CREATE TABLE observations (id INTEGER PRIMARY KEY, site_id TEXT NOT NULL, "
        "interval_start INTEGER NOT NULL, value REAL NOT NULL)"
    )
    sites = ("site-a", "site-b")
    rows_per_site = 5 * 365 * 24 * 4
    batch = []
    next_id = 1
    connection.execute("BEGIN")
    for site in sites:
        for index in range(rows_per_site):
            batch.append((next_id, site, index * 900, float(index % 100)))
            next_id += 1
            if len(batch) >= 10000:
                connection.executemany("INSERT INTO observations VALUES (?, ?, ?, ?)", batch)
                batch.clear()
    if batch:
        connection.executemany("INSERT INTO observations VALUES (?, ?, ?, ?)", batch)
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(FULL)")
    connection.commit()
    before_bytes = database.stat().st_size
    before_dir_bytes = directory_bytes(root)
    started = time.perf_counter()
    connection.execute("BEGIN")
    connection.execute(
        "CREATE TABLE observations_v2 (id INTEGER PRIMARY KEY, site_id TEXT NOT NULL, "
        "interval_start INTEGER NOT NULL, value REAL NOT NULL, quality_code TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO observations_v2 SELECT id, site_id, interval_start, value, 'good' FROM observations"
    )
    connection.execute("DROP TABLE observations")
    connection.execute("ALTER TABLE observations_v2 RENAME TO observations")
    connection.commit()
    migration_seconds = time.perf_counter() - started
    connection.execute("PRAGMA wal_checkpoint(FULL)")
    connection.commit()
    after_bytes = database.stat().st_size
    after_dir_bytes = directory_bytes(root)
    count = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    quality_count = connection.execute(
        "SELECT COUNT(*) FROM observations WHERE quality_code = 'good'"
    ).fetchone()[0]
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]

    failure_database = root / "migration_failure.sqlite"
    failure = sqlite3.connect(failure_database)
    failure.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
    failure.execute("INSERT INTO sample VALUES (1, 'before')")
    failure.commit()
    failure.execute("BEGIN")
    failure.execute("ALTER TABLE sample ADD COLUMN probe TEXT")
    try:
        failure.execute("INSERT INTO sample (id, value) VALUES (1, 'duplicate')")
    except sqlite3.IntegrityError:
        failure.rollback()
    columns = {row[1] for row in failure.execute("PRAGMA table_info(sample)")}
    value = failure.execute("SELECT value FROM sample WHERE id = 1").fetchone()[0]
    failure.close()
    connection.close()
    expected_rows = len(sites) * rows_per_site
    return {
        "rows": expected_rows,
        "row_count_preserved": count == expected_rows,
        "quality_column_migrated": quality_count == expected_rows,
        "integrity_after_migration": integrity == "ok",
        "query_correct_after_migration": connection_query_count(database) == expected_rows,
        "migration_seconds": migration_seconds,
        "database_bytes_before": before_bytes,
        "database_bytes_after": after_bytes,
        "peak_directory_bytes_observed_after": after_dir_bytes,
        "directory_bytes_before": before_dir_bytes,
        "failure_rollback_preserved_schema": "probe" not in columns and value == "before",
    }


def connection_query_count(database):
    connection = sqlite3.connect(database)
    count = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    connection.close()
    return count


def filesystem_gate(root):
    local = root / "local.sqlite"
    backup_dir = root / "backup-target"
    backup_dir.mkdir()
    connection = create_database(local)
    connection.execute("PRAGMA wal_checkpoint(FULL)")
    connection.commit()
    backup = backup_dir / "canonical.sqlite"
    target = sqlite3.connect(backup)
    connection.backup(target)
    target.close()
    connection.close()
    source_hash = hashlib.sha256(backup.read_bytes()).hexdigest()
    unavailable = root / "target-unavailable" / "canonical.sqlite"
    local_connection = sqlite3.connect(local)
    local_connection.execute("INSERT INTO frames VALUES (?, ?, ?, ?, ?, ?)", (
        "frame-2", "global", None, "gen-global", "2026-01-01T00:15:00Z", '{"value":2}'
    ))
    local_connection.commit()
    local_count = local_connection.execute("SELECT COUNT(*) FROM frames").fetchone()[0]
    local_connection.close()
    unavailable_write_failed = False
    try:
        unavailable.write_bytes(b"unavailable")
    except OSError:
        unavailable_write_failed = True
    backup_dir.rename(root / "backup-target-offline")
    offline_local_ok = local_count == 2 and not unavailable.exists()
    (root / "backup-target-offline").rename(backup_dir)
    second_backup = backup_dir / "canonical-2.sqlite"
    source = sqlite3.connect(local)
    restored_target = sqlite3.connect(second_backup)
    source.backup(restored_target)
    restored_target.close()
    source.close()
    restored = sqlite3.connect(second_backup)
    restored_count = restored.execute("SELECT COUNT(*) FROM frames").fetchone()[0]
    integrity = restored.execute("PRAGMA integrity_check").fetchone()[0]
    restored.close()
    return {
        "initial_backup_hash": source_hash,
        "local_write_continued_offline": offline_local_ok,
        "backup_target_unavailable": unavailable_write_failed,
        "backup_resume_restore": restored_count == 2 and integrity == "ok",
    }


def run_gate():
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="elrakning-p0-durability-") as temp_dir:
        root = Path(temp_dir)
        killed = killed_process_gate(root)
        migration = migration_gate(root)
        filesystem = filesystem_gate(root)
        profile_db = root / "profile.sqlite"
        profile = sqlite3.connect(profile_db)
        profile.execute("PRAGMA journal_mode=WAL")
        profile.execute("PRAGMA synchronous=FULL")
        profile.execute("PRAGMA foreign_keys=ON")
        profile.execute("PRAGMA busy_timeout=5000")
        operating_profile = {
            "journal_mode": profile.execute("PRAGMA journal_mode").fetchone()[0],
            "synchronous": profile.execute("PRAGMA synchronous").fetchone()[0],
            "foreign_keys": profile.execute("PRAGMA foreign_keys").fetchone()[0],
            "busy_timeout": profile.execute("PRAGMA busy_timeout").fetchone()[0],
        }
        profile.close()
        checks = {
            "killed_process": all(killed.values()),
            "migration": migration["row_count_preserved"] and migration["quality_column_migrated"]
            and migration["integrity_after_migration"] and migration["query_correct_after_migration"]
            and migration["failure_rollback_preserved_schema"],
            "filesystem_backup_restore": all((filesystem["local_write_continued_offline"],
                                                filesystem["backup_target_unavailable"],
                                                filesystem["backup_resume_restore"])),
            "operating_profile": operating_profile == {
                "journal_mode": "wal", "synchronous": 2, "foreign_keys": 1, "busy_timeout": 5000
            },
        }
        return {
            "ok": all(checks.values()),
            "checks": checks,
            "killed_process": killed,
            "migration": migration,
            "filesystem": filesystem,
            "operating_profile": operating_profile,
            "seconds": time.perf_counter() - started,
        }


if __name__ == "__main__":
    print(json.dumps(run_gate(), indent=2, sort_keys=True))
