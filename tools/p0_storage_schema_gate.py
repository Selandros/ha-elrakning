#!/usr/bin/env python3
"""Validate the frozen P0 storage schema against the canonical contract fixtures."""

import hashlib
import json
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = ROOT / "custom_components/elrakning/p0_storage_schema_v1.sql"
MAPPING_PATH = ROOT / "docs/architecture/contracts/p0_storage_schema_v1.mapping.json"
CONTRACT_PATH = ROOT / "docs/architecture/contracts/p0_data_contract_v1.contract.json"


def timestamp(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1_000_000)


def source_row(source_id, scope, owner, role, fingerprint, created="2026-01-01T00:00:00Z"):
    return (source_id, 1, scope, owner, role, fingerprint, "strong", "runtime audit",
            "native_bucket", 900, "verified", None, None, timestamp(created))


def energy_row(record_id, semantic_key, revision, supersedes, source_id, site="site-a", start="2026-01-01T00:00:00Z"):
    start_us = timestamp(start)
    return (record_id, 1, 1, semantic_key, revision, supersedes, site, "house.consumption", source_id,
            start_us, start_us + 900_000_000, 900, "native_bucket", 900, None, start_us + 900_000_000,
            None, start_us + 900_000_000, "measured", 100.0, "W", "positive_consumption", "good", 1.0,
            "none", '{"status":"good"}', '{"origin_type":"fixture"}')


def historical_row(record_id, semantic_key, source_id):
    start_us = timestamp("2026-01-01T00:00:00Z")
    return (record_id, 1, 1, semantic_key, 1, None, "site-a", "house.consumption", source_id,
            start_us, start_us + 3_600_000_000, 3600, "native_bucket", 3600, None,
            start_us + 3_600_000_000, None, start_us + 3_600_000_000, "measured", 400.0, "W",
            "positive_consumption", "partial", 0.95, "gap", '{"status":"partial"}',
            '{"origin_type":"lts_bootstrap"}')


def frame_row(frame_id, semantic_key, revision, supersedes, source_id, scope="global", site=None):
    captured = timestamp("2026-01-01T00:00:00Z")
    return (frame_id, 1, 1, semantic_key, revision, supersedes, source_id, scope, site,
            "market.price.energy", "published", captured, captured, captured, captured,
            captured + 86_400_000_000, captured + 172_800_000_000, "good", '{"status":"good"}',
            '{"origin_type":"fixture"}',
            "price.v1")


def round_trip(connection):
    connection.execute("INSERT INTO source_generations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       source_row("gen-a", "site", "site-a", "house.consumption", "fp-a"))
    connection.execute("INSERT INTO source_generations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       source_row("gen-global", "global", None, "market.price.energy", "fp-global"))
    connection.execute("INSERT INTO source_generations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       source_row("gen-replacement", "site", "site-a", "house.consumption", "fp-replacement"))
    record = energy_row("rec-1", "site-a|house.consumption|gen-a|start", 1, None, "gen-a")
    connection.execute("INSERT INTO energy_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", record)
    connection.execute("INSERT INTO energy_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       energy_row("rec-2", "site-a|house.consumption|gen-a|start", 2, "rec-1", "gen-a"))
    connection.execute("INSERT INTO energy_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       energy_row("rec-replaced", "site-a|house.consumption|gen-replacement|start", 1, None, "gen-replacement"))
    connection.execute("INSERT INTO historical_energy_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       historical_row("hist-1", "site-a|house.consumption|gen-a|hour", "gen-a"))
    frame = frame_row("frame-1", "global-market|2026-01-01", 1, None, "gen-global")
    connection.execute("INSERT INTO external_input_frames VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", frame)
    connection.execute("INSERT INTO external_input_frames VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       frame_row("frame-2", "global-market|2026-01-01", 2, "frame-1", "gen-global"))
    connection.execute("INSERT INTO external_input_points VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       ("point-1", "frame-1", "2026-01-01T00:00Z", timestamp("2026-01-01T00:00:00Z"), 42.5, "EUR/MWh", "good", '{"source":"fixture"}'))
    connection.commit()
    energy = connection.execute("SELECT site_id, logical_role, source_generation_id, interval_start_us, known_at_us, value, unit FROM energy_observations WHERE record_id = 'rec-1'").fetchone()
    point = connection.execute("SELECT frame_id, value, unit FROM external_input_points").fetchone()
    return (
        energy == ("site-a", "house.consumption", "gen-a", timestamp("2026-01-01T00:00:00Z"), timestamp("2026-01-01T00:15:00Z"), 100.0, "W")
        and point == ("frame-1", 42.5, "EUR/MWh")
        and connection.execute("SELECT COUNT(*) FROM historical_energy_observations").fetchone()[0] == 1
        and connection.execute("SELECT COUNT(*) FROM energy_observations").fetchone()[0] == 3
        and connection.execute("SELECT COUNT(*) FROM external_input_frames").fetchone()[0] == 2
        and connection.execute("SELECT supersedes_record_id FROM energy_observations WHERE record_id = 'rec-2'").fetchone()[0] == "rec-1"
        and connection.execute("SELECT source_generation_id FROM energy_observations WHERE record_id = 'rec-replaced'").fetchone()[0] == "gen-replacement"
        and connection.execute("SELECT supersedes_frame_id FROM external_input_frames WHERE frame_id = 'frame-2'").fetchone()[0] == "frame-1"
    )


def constraint_gate(connection):
    checks = {}
    try:
        connection.execute("INSERT INTO source_generations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           source_row("bad-global", "global", "site-a", "x", "fp"))
    except sqlite3.IntegrityError:
        checks["global_owner_rejected"] = True
    else:
        checks["global_owner_rejected"] = False
    try:
        connection.execute("INSERT INTO energy_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           energy_row("rec-duplicate", "site-a|house.consumption|gen-a|start", 1, None, "gen-a"))
    except sqlite3.IntegrityError:
        checks["duplicate_revision_rejected"] = True
    else:
        checks["duplicate_revision_rejected"] = False
    try:
        connection.execute("INSERT INTO energy_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           energy_row("rec-bad-supersedes", "different", 2, "rec-1", "gen-a"))
    except sqlite3.IntegrityError:
        checks["cross_semantic_supersedes_rejected"] = True
    else:
        checks["cross_semantic_supersedes_rejected"] = False
    try:
        connection.execute("DELETE FROM energy_observations WHERE record_id = 'rec-1'")
    except sqlite3.DatabaseError:
        checks["immutable_delete_rejected"] = True
    else:
        checks["immutable_delete_rejected"] = False
    try:
        connection.execute("UPDATE external_input_frames SET logical_role = 'changed' WHERE frame_id = 'frame-1'")
    except sqlite3.DatabaseError:
        checks["immutable_update_rejected"] = True
    else:
        checks["immutable_update_rejected"] = False
    try:
        connection.execute("INSERT INTO external_input_points VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           ("point-duplicate", "frame-1", "2026-01-01T00:00Z", timestamp("2026-01-01T00:00:00Z"), 44.0, "EUR/MWh", "good", '{}'))
    except sqlite3.IntegrityError:
        checks["duplicate_frame_point_rejected"] = True
    else:
        checks["duplicate_frame_point_rejected"] = False
    connection.rollback()
    return checks


def encoding_benchmark():
    results = {}
    for name, declaration in (("text", "TEXT"), ("blob", "BLOB")):
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as temporary:
            connection = sqlite3.connect(temporary.name)
            connection.execute(f"CREATE TABLE ids (id {declaration} PRIMARY KEY, value INTEGER NOT NULL)")
            rows = []
            for index in range(10000):
                value = f"00000000-0000-4000-8000-{index:012d}"
                rows.append((value if name == "text" else bytes.fromhex(value.replace('-', '')), index))
            connection.executemany("INSERT INTO ids VALUES (?, ?)", rows)
            connection.commit()
            results[name] = temporary.seek(0, 2) or Path(temporary.name).stat().st_size
            connection.close()
    return results


def run_gate():
    started = time.perf_counter()
    contract = json.loads(CONTRACT_PATH.read_text())
    mapping = json.loads(MAPPING_PATH.read_text())
    sql = SQL_PATH.read_text()
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as temporary:
        connection = sqlite3.connect(temporary.name)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(sql)
        connection.execute("INSERT INTO schema_meta VALUES (?, ?)", ("schema_name", mapping["schema_name"]))
        connection.execute("INSERT INTO schema_meta VALUES (?, ?)", ("schema_version", "1"))
        connection.execute("INSERT INTO schema_migrations VALUES (?, ?, ?)", (1, timestamp("2026-01-01T00:00:00Z"), hashlib.sha256(sql.encode()).hexdigest()))
        round_trip_ok = round_trip(connection)
        constraint_results = constraint_gate(connection)
        connection.commit()
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        all_fields_mapped = all(name in mapping["fields"] for name in (
            "site_id", "logical_role", "source_generation_id", "known_at", "value", "quality", "provenance", "revision", "supersedes"
        ))
        active_site_absent = "active_site_id" not in {row[1] for table in tables for row in connection.execute(f"PRAGMA table_info({table})")}
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        connection.close()
    encoding = encoding_benchmark()
    checks = {
        "required_tables": {"schema_meta", "schema_migrations", "source_generations", "energy_observations", "historical_energy_observations", "external_input_frames", "external_input_points"}.issubset(tables),
        "contract_version": contract["schema_version"] == 1 and mapping["schema_version"] == 1,
        "round_trip": round_trip_ok,
        "constraints": all(constraint_results.values()),
        "all_fields_mapped": all_fields_mapped,
        "active_site_not_storage_identity": active_site_absent,
        "foreign_keys": foreign_keys,
        "encoding_benchmark": encoding["text"] > 0 and encoding["blob"] > 0,
    }
    return {"ok": all(checks.values()), "checks": checks, "constraint_results": constraint_results,
            "encoding_bytes": encoding, "sql_sha256": hashlib.sha256(sql.encode()).hexdigest(),
            "seconds": time.perf_counter() - started}


if __name__ == "__main__":
    print(json.dumps(run_gate(), indent=2, sort_keys=True))
