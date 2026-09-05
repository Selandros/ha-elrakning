#!/usr/bin/env python3
"""Run an isolated recovery gate for the normalized SQLite candidate."""

import hashlib
import json
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path


def create_database(path):
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE source_generations (
            source_generation_id TEXT PRIMARY KEY,
            scope TEXT NOT NULL,
            owner_site_id TEXT,
            logical_role TEXT NOT NULL,
            identity_fingerprint TEXT NOT NULL
        );
        CREATE TABLE records (
            record_id TEXT PRIMARY KEY,
            semantic_key TEXT NOT NULL,
            revision INTEGER NOT NULL,
            supersedes_record_id TEXT,
            site_id TEXT,
            scope TEXT NOT NULL,
            source_generation_id TEXT NOT NULL REFERENCES source_generations(source_generation_id),
            logical_role TEXT NOT NULL,
            interval_start INTEGER NOT NULL,
            interval_end INTEGER NOT NULL,
            known_at TEXT NOT NULL,
            quality_json TEXT NOT NULL,
            provenance_json TEXT NOT NULL,
            value REAL,
            UNIQUE (semantic_key, revision)
        );
        CREATE TABLE frames (
            frame_id TEXT PRIMARY KEY,
            scope TEXT NOT NULL,
            site_id TEXT,
            source_generation_id TEXT NOT NULL REFERENCES source_generations(source_generation_id),
            known_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        """
    )
    connection.execute(
        "INSERT INTO source_generations VALUES (?, ?, ?, ?, ?)",
        ("gen-a", "site", "site-a", "house.consumption", "fp-a"),
    )
    connection.execute(
        "INSERT INTO source_generations VALUES (?, ?, ?, ?, ?)",
        ("gen-global", "global", None, "market.price.energy", "fp-global"),
    )
    connection.execute(
        "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "record-1", "site-a|house.consumption|gen-a|100", 1, None, "site-a", "site",
            "gen-a", "house.consumption", 100, 115, "2026-01-01T00:00:00Z",
            '{"status":"good"}', '{"origin_type":"benchmark"}', 100.0,
        ),
    )
    connection.execute(
        "INSERT INTO frames VALUES (?, ?, ?, ?, ?, ?)",
        ("frame-1", "global", None, "gen-global", "2026-01-01T00:00:00Z", '{"value":1}'),
    )
    connection.commit()
    return connection


def record_row(record_id, semantic_key, revision, supersedes, generation="gen-a"):
    return (
        record_id, semantic_key, revision, supersedes, "site-a", "site", generation,
        "house.consumption", 100, 115, "2026-01-01T00:00:00Z", '{"status":"good"}',
        '{"origin_type":"benchmark"}', 100.0,
    )


def run_gate():
    started = time.perf_counter()
    results = {}
    with tempfile.TemporaryDirectory(prefix="elrakning-p0-recovery-") as temp_dir:
        root = Path(temp_dir)
        database = root / "canonical.sqlite"
        connection = create_database(database)
        baseline = connection.execute("SELECT COUNT(*) FROM records").fetchone()[0]

        connection.execute("BEGIN")
        connection.execute(
            "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            record_row("partial", "partial", 1, None),
        )
        connection.rollback()
        results["transaction_rollback"] = connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == baseline

        connection.execute(
            "INSERT OR IGNORE INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            record_row("record-1", "site-a|house.consumption|gen-a|100", 1, None),
        )
        connection.commit()
        results["duplicate_idempotency"] = connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == baseline

        connection.execute(
            "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            record_row("record-1-r2", "site-a|house.consumption|gen-a|100", 2, "record-1"),
        )
        connection.commit()
        revision_rows = connection.execute(
            "SELECT revision, supersedes_record_id FROM records WHERE semantic_key = ? ORDER BY revision",
            ("site-a|house.consumption|gen-a|100",),
        ).fetchall()
        results["revision_chain"] = revision_rows == [(1, None), (2, "record-1")]

        connection.execute(
            "INSERT INTO source_generations VALUES (?, ?, ?, ?, ?)",
            ("gen-new", "site", "site-a", "house.consumption", "fp-new"),
        )
        connection.execute(
            "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            record_row("record-new-source", "site-a|house.consumption|gen-new|100", 1, None, "gen-new"),
        )
        connection.commit()
        results["source_replacement_preserves_history"] = connection.execute(
            "SELECT COUNT(*) FROM records WHERE source_generation_id IN ('gen-a', 'gen-new')"
        ).fetchone()[0] == 3

        connection.execute("BEGIN")
        connection.execute("ALTER TABLE records ADD COLUMN retention_class TEXT NOT NULL DEFAULT 'canonical'")
        connection.commit()
        results["schema_migration"] = connection.execute(
            "SELECT retention_class FROM records WHERE record_id = 'record-1'"
        ).fetchone()[0] == "canonical"

        connection.execute("BEGIN")
        connection.execute("ALTER TABLE records ADD COLUMN migration_probe TEXT")
        connection.rollback()
        columns = {row[1] for row in connection.execute("PRAGMA table_info(records)")}
        results["migration_rollback"] = "migration_probe" not in columns

        connection.execute("PRAGMA wal_checkpoint(FULL)")
        connection.commit()
        backup_path = root / "backup.sqlite"
        backup_connection = sqlite3.connect(backup_path)
        connection.backup(backup_connection)
        backup_connection.close()
        restored = sqlite3.connect(backup_path)
        results["backup_restore"] = restored.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 3
        results["global_frame_restore"] = restored.execute(
            "SELECT scope, site_id, known_at FROM frames WHERE frame_id = 'frame-1'"
        ).fetchone() == ("global", None, "2026-01-01T00:00:00Z")
        results["integrity_check"] = restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        restored.close()

        corrupted = root / "corrupted.sqlite"
        shutil.copy2(backup_path, corrupted)
        with corrupted.open("r+b") as file_handle:
            file_handle.seek(100)
            byte = file_handle.read(1)
            file_handle.seek(100)
            file_handle.write(bytes([byte[0] ^ 0xFF]))
        try:
            corrupted_connection = sqlite3.connect(corrupted)
            integrity = corrupted_connection.execute("PRAGMA integrity_check").fetchone()[0]
            corrupted_connection.close()
            results["corruption_detection"] = integrity != "ok"
        except sqlite3.DatabaseError:
            results["corruption_detection"] = True

        missing_backup = root / "missing-target" / "backup.sqlite"
        try:
            shutil.copy2(database, missing_backup)
        except OSError:
            results["nas_unavailable_does_not_block_local_write"] = (
                connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 3
            )
        else:
            results["nas_unavailable_does_not_block_local_write"] = False

        connection.close()
    return {"ok": all(results.values()), "results": results, "seconds": time.perf_counter() - started}


if __name__ == "__main__":
    print(json.dumps(run_gate(), indent=2, sort_keys=True))
