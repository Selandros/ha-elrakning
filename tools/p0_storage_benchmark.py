#!/usr/bin/env python3
"""Benchmark storage candidates against the frozen P0 contract workload."""

import argparse
import json
import os
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROLE_DEFS = (
    ("house.consumption", "house"),
    ("solar.production", "pv1"),
    ("solar.production", "pv2"),
    ("grid.power/import", "grid"),
    ("battery.power", "battery"),
    ("battery.soc", "soc"),
)


def records(sites: int, days: int):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for site_number in range(sites):
        site_id = f"site-{site_number + 1}"
        for day in range(days):
            day_start = start + timedelta(days=day)
            for quarter in range(96):
                observed_at = int((day_start + timedelta(minutes=15 * quarter)).timestamp())
                interval_end = observed_at + 900
                for role_number, (role, source_key) in enumerate(ROLE_DEFS):
                    generation = f"generation-{site_number + 1}-{source_key}"
                    record = {
                        "schema_name": "elrakning.canonical_data",
                        "schema_version": 1,
                        "dataset": "energy_observation",
                        "dataset_version": 1,
                        "record_id": f"{site_id}-{role_number}-{observed_at}",
                        "semantic_key": f"{site_id}|{role}|{generation}|{observed_at}",
                        "revision": 1,
                        "supersedes_record_id": None,
                        "scope": "site",
                        "site_id": site_id,
                        "logical_role": role,
                        "source_generation_id": generation,
                        "source_scope": "site",
                        "source_identity_fingerprint": f"fingerprint-{generation}",
                        "source_identity_strength": "strong",
                        "source_identity_provenance": "benchmark fixture",
                        "interval_start": datetime.fromtimestamp(observed_at, timezone.utc).isoformat(),
                        "interval_end": datetime.fromtimestamp(interval_end, timezone.utc).isoformat(),
                        "resolution_seconds": 900,
                        "source_resolution_kind": "native_bucket",
                        "source_resolution_seconds": 900,
                        "observed_at": None,
                        "captured_at": datetime.fromtimestamp(interval_end, timezone.utc).isoformat(),
                        "fetched_at": None,
                        "known_at": datetime.fromtimestamp(interval_end, timezone.utc).isoformat(),
                        "classification": "measured",
                        "value": float((day * 96 + quarter + role_number) % 5000),
                        "unit": "%" if role == "battery.soc" else "W",
                        "sign_convention": "unsigned_0_100" if role == "battery.soc" else "canonical",
                        "quality": {"status": "good", "coverage_ratio": 1.0, "gap": {"status": "none"}},
                        "provenance": {"origin_type": "benchmark", "lineage_status": "complete"},
                    }
                    yield (site_id, role, observed_at, generation, json.dumps(record, separators=(",", ":")))


def benchmark_sqlite(rows, root, query_ranges):
    path = root / "observations.sqlite"
    started = time.perf_counter()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE observations (site_id TEXT NOT NULL, logical_role TEXT NOT NULL, "
            "observed_at INTEGER NOT NULL, source_generation_id TEXT NOT NULL, payload_json TEXT NOT NULL, "
            "PRIMARY KEY (site_id, logical_role, observed_at, source_generation_id))"
        )
        connection.executemany(
            "INSERT INTO observations VALUES (?, ?, ?, ?, ?)", rows
        )
        connection.execute("CREATE INDEX by_site_time ON observations(site_id, observed_at)")
        connection.execute(
            "CREATE INDEX by_site_role_time ON observations(site_id, logical_role, observed_at)"
        )
        connection.commit()
        write_seconds = time.perf_counter() - started
        query_seconds = {}
        for label, end_at, start_at in query_ranges:
            query_started = time.perf_counter()
            count = connection.execute(
                "SELECT COUNT(*) FROM observations WHERE site_id = ? AND observed_at >= ? AND observed_at < ?",
                ("site-1", start_at, end_at),
            ).fetchone()[0]
            query_seconds[label] = {"seconds": time.perf_counter() - query_started, "rows": count}
    backup_started = time.perf_counter()
    backup_path = root / "observations.sqlite.backup"
    shutil.copy2(path, backup_path)
    backup_seconds = time.perf_counter() - backup_started
    return {
        "bytes": path.stat().st_size,
        "write_seconds": write_seconds,
        "query_seconds": query_seconds,
        "backup_seconds": backup_seconds,
        "backup_bytes": backup_path.stat().st_size,
    }


def benchmark_sqlite_normalized(rows, root, query_ranges):
    path = root / "observations-normalized.sqlite"
    started = time.perf_counter()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE source_generations (source_generation_id TEXT PRIMARY KEY, site_id TEXT NOT NULL, "
            "logical_role TEXT NOT NULL, source_scope TEXT NOT NULL, fingerprint TEXT NOT NULL, "
            "identity_strength TEXT NOT NULL, identity_provenance TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE observations (site_id TEXT NOT NULL, logical_role TEXT NOT NULL, "
            "observed_at INTEGER NOT NULL, source_generation_id TEXT NOT NULL, record_id TEXT NOT NULL, "
            "semantic_key TEXT NOT NULL, revision INTEGER NOT NULL, supersedes_record_id TEXT, "
            "interval_end TEXT NOT NULL, resolution_seconds INTEGER NOT NULL, source_resolution_kind TEXT NOT NULL, "
            "source_resolution_seconds INTEGER NOT NULL, captured_at TEXT NOT NULL, known_at TEXT NOT NULL, "
            "classification TEXT NOT NULL, value REAL, unit TEXT NOT NULL, sign_convention TEXT NOT NULL, "
            "quality_json TEXT NOT NULL, provenance_json TEXT NOT NULL, "
            "PRIMARY KEY (site_id, logical_role, observed_at, source_generation_id))"
        )
        source_rows = {}
        observation_rows = []
        for site_id, role, observed_at, generation, payload_json in rows:
            payload = json.loads(payload_json)
            source_rows[generation] = (
                generation,
                site_id,
                role,
                payload["source_scope"],
                payload["source_identity_fingerprint"],
                payload["source_identity_strength"],
                payload["source_identity_provenance"],
            )
            observation_rows.append(
                (
                    site_id,
                    role,
                    observed_at,
                    generation,
                    payload["record_id"],
                    payload["semantic_key"],
                    payload["revision"],
                    payload["supersedes_record_id"],
                    payload["interval_end"],
                    payload["resolution_seconds"],
                    payload["source_resolution_kind"],
                    payload["source_resolution_seconds"],
                    payload["captured_at"],
                    payload["known_at"],
                    payload["classification"],
                    payload["value"],
                    payload["unit"],
                    payload["sign_convention"],
                    json.dumps(payload["quality"], separators=(",", ":")),
                    json.dumps(payload["provenance"], separators=(",", ":")),
                )
            )
        connection.executemany("INSERT INTO source_generations VALUES (?, ?, ?, ?, ?, ?, ?)", source_rows.values())
        connection.executemany(
            "INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            observation_rows,
        )
        connection.execute("CREATE INDEX normalized_by_site_time ON observations(site_id, observed_at)")
        connection.execute(
            "CREATE INDEX normalized_by_site_role_time ON observations(site_id, logical_role, observed_at)"
        )
        connection.commit()
        write_seconds = time.perf_counter() - started
        query_seconds = {}
        for label, end_at, start_at in query_ranges:
            query_started = time.perf_counter()
            count = connection.execute(
                "SELECT COUNT(*) FROM observations WHERE site_id = ? AND observed_at >= ? AND observed_at < ?",
                ("site-1", start_at, end_at),
            ).fetchone()[0]
            query_seconds[label] = {"seconds": time.perf_counter() - query_started, "rows": count}
    backup_started = time.perf_counter()
    backup_path = root / "observations-normalized.sqlite.backup"
    shutil.copy2(path, backup_path)
    backup_seconds = time.perf_counter() - backup_started
    return {
        "bytes": path.stat().st_size,
        "write_seconds": write_seconds,
        "query_seconds": query_seconds,
        "backup_seconds": backup_seconds,
        "backup_bytes": backup_path.stat().st_size,
    }


def benchmark_jsonl(rows, root, query_ranges):
    path = root / "observations.jsonl"
    started = time.perf_counter()
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, separators=(",", ":")) + "\n")
    write_seconds = time.perf_counter() - started
    query_seconds = {}
    for label, end_at, start_at in query_ranges:
        query_started = time.perf_counter()
        count = 0
        with path.open(encoding="utf-8") as source:
            for line in source:
                row = json.loads(line)
                if row[0] == "site-1" and start_at <= row[2] < end_at:
                    count += 1
        query_seconds[label] = {"seconds": time.perf_counter() - query_started, "rows": count}
    backup_started = time.perf_counter()
    backup_path = root / "observations.jsonl.backup"
    shutil.copy2(path, backup_path)
    backup_seconds = time.perf_counter() - backup_started
    return {
        "bytes": path.stat().st_size,
        "write_seconds": write_seconds,
        "query_seconds": query_seconds,
        "backup_seconds": backup_seconds,
        "backup_bytes": backup_path.stat().st_size,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--sites", type=int, default=1)
    args = parser.parse_args()
    if args.days < 1 or args.sites < 1:
        raise SystemExit("days and sites must be positive")
    total_seconds = args.days * 86400
    end_at = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()) + total_seconds
    query_ranges = (
        ("24h", end_at, end_at - 86400),
        ("30d", end_at, end_at - 30 * 86400),
        ("1y", end_at, end_at - 365 * 86400),
    )
    with tempfile.TemporaryDirectory(prefix="elrakning-p0-storage-") as temp_dir:
        root = Path(temp_dir)
        rows = list(records(args.sites, args.days))
        result = {
            "workload": {
                "sites": args.sites,
                "days": args.days,
                "roles_per_quarter": len(ROLE_DEFS),
                "rows": len(rows),
            },
            "candidates": {
                "sqlite": benchmark_sqlite(rows, root, query_ranges),
                "sqlite_normalized": benchmark_sqlite_normalized(rows, root, query_ranges),
                "jsonl": benchmark_jsonl(rows, root, query_ranges),
            },
            "environment": {
                "python": os.sys.version.split()[0],
                "sqlite": sqlite3.sqlite_version,
            },
        }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
