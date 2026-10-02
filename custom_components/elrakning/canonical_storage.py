"""SQLite storage for immutable P0 canonical observations."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
DATASET_VERSION = 1
INTEGRITY_MIGRATION_VERSION = 2
INTEGRITY_MIGRATION_CHECKSUM = hashlib.sha256(
    b"external_input_points_immutable_v2|external_frames_replay_index_v2"
).hexdigest()
HISTORY_FOUND = "HISTORY_FOUND"
HISTORY_NONE = "NO_HISTORY"
HISTORY_UNKNOWN = "UNKNOWN"
QUARTER_SECONDS = 900
SCHEMA_PATH = Path(__file__).with_name("p0_storage_schema_v1.sql")


def _serialized(method):
    """Serialize operations that share the process-local SQLite connection."""
    def wrapped(self, *args, **kwargs):
        with self._connection_lock:
            return method(self, *args, **kwargs)

    wrapped.__name__ = method.__name__
    wrapped.__doc__ = method.__doc__
    return wrapped


def timestamp_us(value: datetime) -> int:
    """Convert an aware UTC timestamp to integer microseconds."""
    if value.tzinfo is None:
        raise ValueError("naive_timestamp")
    return int(value.astimezone(timezone.utc).timestamp() * 1_000_000)


def quarter_start(value: datetime) -> datetime:
    """Return the UTC-aligned fifteen-minute interval containing value."""
    utc = value.astimezone(timezone.utc)
    minute = utc.minute - (utc.minute % 15)
    return utc.replace(minute=minute, second=0, microsecond=0)


def _is_provenance_enrichment(existing_json: str, incoming_json: str) -> bool:
    """Accept only additive provenance changes for the same immutable fact."""
    try:
        existing = json.loads(existing_json) if existing_json else {}
        incoming = json.loads(incoming_json) if incoming_json else {}
    except (TypeError, ValueError):
        return False
    if not isinstance(existing, dict) or not isinstance(incoming, dict) or len(incoming) <= len(existing):
        return False
    return all(incoming.get(key) == value for key, value in existing.items())


class CanonicalStorage:
    """Own a durable, immutable SQLite P0 observation store."""

    def __init__(self, path: str | Path, schema_path: str | Path = SCHEMA_PATH) -> None:
        self.path = Path(path)
        self.schema_path = Path(schema_path)
        self.connection: sqlite3.Connection | None = None
        self._connection_lock = threading.RLock()

    def open(self) -> None:
        """Open and initialize the store with the selected durability profile."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        sql = self.schema_path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode()).hexdigest()
        if not self.path.exists():
            staging_path = self.path.with_name(self.path.name + ".initializing")
            if staging_path.exists():
                raise RuntimeError("canonical_initialization_incomplete")
            staging = sqlite3.connect(staging_path, check_same_thread=False)
            try:
                self._configure_connection(staging)
                staging.executescript(sql)
                staging.executemany(
                    "INSERT INTO schema_meta(key, value) VALUES (?, ?)",
                    (("schema_name", "p0_storage_schema_v1"), ("schema_version", str(SCHEMA_VERSION))),
                )
                staging.execute(
                    "INSERT INTO schema_migrations(version, applied_at_us, checksum) VALUES (?, ?, ?)",
                    (SCHEMA_VERSION, timestamp_us(datetime.now(timezone.utc)), checksum),
                )
                staging.commit()
                if staging.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("canonical_initialization_integrity_failure")
            except Exception:
                staging.close()
                raise
            else:
                staging.close()
            os.replace(staging_path, self.path)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self._configure_connection(self.connection)
        has_schema = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_meta'"
        ).fetchone()
        if not has_schema:
            self.connection.close()
            self.connection = None
            raise RuntimeError("canonical_initialization_incomplete")
        else:
            recorded = dict(self.connection.execute("SELECT key, value FROM schema_meta").fetchall())
            migration = self.connection.execute(
                "SELECT checksum FROM schema_migrations WHERE version = ?", (SCHEMA_VERSION,)
            ).fetchone()
            if (
                recorded.get("schema_name") != "p0_storage_schema_v1"
                or recorded.get("schema_version") != str(SCHEMA_VERSION)
                or migration is None
                or migration[0] != checksum
            ):
                self.connection.close()
                self.connection = None
                raise RuntimeError("canonical_schema_mismatch")
        self._apply_integrity_migration()
        self.connection.commit()

    def _apply_integrity_migration(self) -> None:
        """Apply additive external-frame integrity protection without rewriting data."""
        connection = self._connection()
        migration = connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version = ?",
            (INTEGRITY_MIGRATION_VERSION,),
        ).fetchone()
        connection.execute("""CREATE TABLE IF NOT EXISTS reconciled_grid_import (
            reconciliation_id TEXT PRIMARY KEY, site_id TEXT NOT NULL, logical_role TEXT NOT NULL,
            interval_start_us INTEGER NOT NULL, interval_end_us INTEGER NOT NULL,
            resolution_seconds INTEGER NOT NULL CHECK (resolution_seconds > 0), value REAL,
            unit TEXT NOT NULL, source_status TEXT NOT NULL, correction_reason TEXT NOT NULL,
            local_record_id TEXT, provider_record_id TEXT, known_at_us INTEGER, provenance_json TEXT NOT NULL,
            UNIQUE(site_id, interval_start_us, interval_end_us, resolution_seconds)
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS reconciled_grid_import_by_site_time ON reconciled_grid_import(site_id, interval_start_us)")
        for column in ("local_value", "provider_value"):
            try:
                connection.execute(f"ALTER TABLE reconciled_grid_import ADD COLUMN {column} REAL")
            except sqlite3.OperationalError as error:
                if "duplicate column name" not in str(error):
                    raise
        if migration is not None:
            if migration[0] != INTEGRITY_MIGRATION_CHECKSUM:
                raise RuntimeError("canonical_integrity_migration_mismatch")
            return
        connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS frames_by_replay_decision
                ON external_input_frames(
                    source_scope, site_id, logical_role, known_at_us,
                    semantic_key, revision
                );
            CREATE INDEX IF NOT EXISTS points_by_valid_time
                ON external_input_points(valid_at_us, frame_id);
            CREATE TRIGGER IF NOT EXISTS point_immutable_update
            BEFORE UPDATE ON external_input_points
            BEGIN
                SELECT RAISE(ABORT, 'external_input_points are immutable; insert a revision');
            END;
            CREATE TRIGGER IF NOT EXISTS point_immutable_delete
            BEFORE DELETE ON external_input_points
            BEGIN
                SELECT RAISE(ABORT, 'external_input_points are immutable');
            END;
            """
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at_us, checksum) VALUES (?, ?, ?)",
            (
                INTEGRITY_MIGRATION_VERSION,
                timestamp_us(datetime.now(timezone.utc)),
                INTEGRITY_MIGRATION_CHECKSUM,
            ),
        )

    @staticmethod
    def _configure_connection(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=5000")

    def close(self) -> None:
        with self._connection_lock:
            if self.connection is not None:
                self.connection.commit()
                self.connection.close()
                self.connection = None

    def connection_lock(self):
        """Return the lock for callers that must use the raw connection."""
        return self._connection_lock

    @_serialized
    def integrity_check(self) -> str:
        return str(self._connection().execute("PRAGMA integrity_check").fetchone()[0])

    def _connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("canonical_storage_not_open")
        return self.connection

    @_serialized
    def ensure_source_generation(self, target: dict[str, Any], now: datetime) -> None:
        connection = self._connection()
        identity = target.get("source_identity") or {}
        identity_key = identity.get("identity_key")
        fingerprint = hashlib.sha256(identity_key.encode()).hexdigest() if identity_key else None
        strength = identity.get("identity_strength", "uncertain")
        if strength not in {"strong", "medium", "weak", "uncertain"}:
            strength = "uncertain"
        provenance = identity.get("identity_provenance") or "site_source_ledger"
        site_id = target["site_id"]
        effective_from = target.get("effective_from")
        valid_from_us = None
        if isinstance(effective_from, str):
            try:
                valid_from_us = timestamp_us(datetime.fromisoformat(effective_from.replace("Z", "+00:00")))
            except ValueError:
                valid_from_us = None
        connection.execute(
            """INSERT OR IGNORE INTO source_generations(
                source_generation_id, schema_version, source_scope, owner_site_id,
                logical_role, source_identity_fingerprint, source_identity_strength,
                source_identity_provenance, source_resolution_kind,
                source_resolution_seconds, timezone_state, valid_from_us,
                valid_to_us, created_at_us
            ) VALUES (?, ?, 'site', ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
            (
                target["generation_id"], SCHEMA_VERSION, site_id,
                target["logical_role"], fingerprint, strength, provenance,
                target.get("source_resolution_kind", "event_stream"),
                target.get("source_resolution_seconds"),
                target.get("timezone_state", "unknown"),
                valid_from_us, timestamp_us(now),
            ),
        )

    @_serialized
    def recanonicalize_source_generation(
        self,
        site_id: str,
        logical_role: str,
        old_generation_id: str,
        new_generation_id: str,
        migration_id: str,
        now: datetime,
        value_transform,
    ) -> int:
        """Append an auditable corrected generation without rewriting immutable rows."""
        if logical_role != "battery.power":
            raise ValueError("recanonicalization_role_not_supported")
        connection = self._connection()
        old_generation = connection.execute(
            """SELECT source_scope, owner_site_id, logical_role,
                      source_identity_fingerprint, source_identity_strength,
                      source_identity_provenance, source_resolution_kind,
                      source_resolution_seconds, timezone_state, valid_from_us
                 FROM source_generations
                WHERE source_generation_id = ?""",
            (old_generation_id,),
        ).fetchone()
        if old_generation is None or old_generation[1] != site_id or old_generation[2] != logical_role:
            raise ValueError("recanonicalization_source_generation_mismatch")
        existing_new = connection.execute(
            "SELECT COUNT(*) FROM energy_observations WHERE source_generation_id = ?",
            (new_generation_id,),
        ).fetchone()[0]
        if existing_new:
            return 0
        connection.execute(
            """INSERT OR IGNORE INTO source_generations(
                source_generation_id, schema_version, source_scope, owner_site_id,
                logical_role, source_identity_fingerprint, source_identity_strength,
                source_identity_provenance, source_resolution_kind,
                source_resolution_seconds, timezone_state, valid_from_us,
                valid_to_us, created_at_us
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
            (
                new_generation_id, SCHEMA_VERSION, old_generation[0], site_id,
                logical_role, old_generation[3], old_generation[4],
                old_generation[5], old_generation[6], old_generation[7],
                old_generation[8], old_generation[9], timestamp_us(now),
            ),
        )
        source_rows = []
        for table in ("historical_energy_observations", "energy_observations"):
            source_rows.extend(connection.execute(
                f"""SELECT record_id, revision, interval_start_us, interval_end_us,
                           resolution_seconds, observed_at_us, captured_at_us,
                           known_at_us, classification, value, unit,
                           quality_status, coverage_ratio, gap_status,
                           quality_json, provenance_json
                      FROM {table} AS current
                     WHERE site_id = ? AND logical_role = ?
                       AND source_generation_id = ?
                       AND NOT EXISTS (
                           SELECT 1 FROM {table} AS newer
                            WHERE newer.semantic_key = current.semantic_key
                              AND newer.revision > current.revision
                       )""",
                (site_id, logical_role, old_generation_id),
            ).fetchall())
        deduped = {}
        for row in source_rows:
            key = (int(row[2]), int(row[3]))
            previous = deduped.get(key)
            if previous is None or int(row[1]) > int(previous[1]):
                deduped[key] = row
        observations = []
        for row in deduped.values():
            provenance = json.loads(row[15]) if row[15] else {}
            provenance.update({
                "canonicalization_migration": migration_id,
                "recanonicalized_from_generation_id": old_generation_id,
                "recanonicalized_at": now.astimezone(timezone.utc).isoformat(),
                "recanonicalization_transform": "negate_signed_battery_power",
                "source_generation_id": new_generation_id,
                "source_mapping_invert_battery_power": True,
                "raw_sign_convention": "positive_charge_negative_discharge",
                "canonical_sign_convention": "positive_discharge_negative_charge",
            })
            observations.append({
                "semantic_key": f"{site_id}|{logical_role}|{new_generation_id}|{datetime.fromtimestamp(row[2] / 1_000_000, tz=timezone.utc).isoformat()}",
                "revision": 1,
                "site_id": site_id,
                "logical_role": logical_role,
                "source_generation_id": new_generation_id,
                "interval_start": datetime.fromtimestamp(row[2] / 1_000_000, tz=timezone.utc),
                "interval_end": datetime.fromtimestamp(row[3] / 1_000_000, tz=timezone.utc),
                "resolution_seconds": int(row[4]),
                "observed_at": datetime.fromtimestamp(row[5] / 1_000_000, tz=timezone.utc) if row[5] else None,
                "captured_at": datetime.fromtimestamp(row[6] / 1_000_000, tz=timezone.utc) if row[6] else None,
                "known_at": datetime.fromtimestamp(row[7] / 1_000_000, tz=timezone.utc) if row[7] else None,
                "classification": row[8],
                "value": value_transform(row[9]) if row[9] is not None else None,
                "unit": row[10],
                "sign_convention": "positive_discharge_negative_charge",
                "quality_status": row[11],
                "coverage_ratio": row[12],
                "gap_status": row[13],
                "quality": json.loads(row[14]) if row[14] else {},
                "provenance": provenance,
            })
        try:
            for observation in observations:
                self._insert_observation(connection, observation)
            connection.execute(
                "UPDATE source_generations SET valid_to_us = ? WHERE source_generation_id = ? AND valid_to_us IS NULL",
                (timestamp_us(now), old_generation_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return len(observations)

    @_serialized
    def ensure_global_source_generation(self, target: dict[str, Any], now: datetime) -> None:
        """Ensure one deterministic global external-source generation exists."""
        identity = target.get("source_identity") or {}
        identity_key = identity.get("identity_key")
        fingerprint = hashlib.sha256(identity_key.encode()).hexdigest() if identity_key else None
        strength = identity.get("identity_strength", "uncertain")
        if strength not in {"strong", "medium", "weak", "uncertain"}:
            strength = "uncertain"
        provenance = identity.get("identity_provenance") or "runtime_source_binding"
        connection = self._connection()
        connection.execute(
            """INSERT OR IGNORE INTO source_generations(
                source_generation_id, schema_version, source_scope, owner_site_id,
                logical_role, source_identity_fingerprint, source_identity_strength,
                source_identity_provenance, source_resolution_kind,
                source_resolution_seconds, timezone_state, valid_from_us,
                valid_to_us, created_at_us
            ) VALUES (?, ?, 'global', NULL, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
            (
                target["generation_id"], SCHEMA_VERSION, target["logical_role"],
                fingerprint, strength, provenance,
                target.get("source_resolution_kind", "native_bucket"),
                target.get("source_resolution_seconds"),
                target.get("timezone_state", "verified"),
                None,
                timestamp_us(now),
            ),
        )

    @_serialized
    def insert_external_frame(self, frame: dict[str, Any], points: list[dict[str, Any]]) -> bool:
        """Insert an immutable external frame and its points atomically."""
        connection = self._connection()
        scope = frame["source_scope"]
        site_id = frame.get("site_id")
        if scope == "global" and site_id is not None:
            raise ValueError("global_frame_site_id")
        if scope == "site" and not site_id:
            raise ValueError("site_frame_site_id")
        revision = int(frame.get("revision", 1))
        semantic_key = frame["semantic_key"]
        existing = connection.execute(
            "SELECT frame_id, revision FROM external_input_frames WHERE semantic_key = ? AND revision = ?",
            (semantic_key, revision),
        ).fetchone()
        if existing:
            if self._external_frame_matches(connection, frame, points):
                return False
            raise ValueError("canonical_frame_revision_conflict")
        generation = connection.execute(
            "SELECT source_scope, owner_site_id FROM source_generations WHERE source_generation_id = ?",
            (frame["source_generation_id"],),
        ).fetchone()
        if generation is None:
            raise ValueError("external_frame_source_generation_missing")
        if generation[0] != scope or (scope == "site" and generation[1] != site_id):
            raise ValueError("external_frame_source_scope_mismatch")
        supersedes = frame.get("supersedes_frame_id")
        if supersedes:
            predecessor = connection.execute(
                "SELECT semantic_key, revision FROM external_input_frames WHERE frame_id = ?",
                (supersedes,),
            ).fetchone()
            if predecessor != (semantic_key, revision - 1):
                raise ValueError("external_frame_revision_chain")
        values = (
            frame["frame_id"], int(frame.get("schema_version", SCHEMA_VERSION)),
            int(frame.get("dataset_version", DATASET_VERSION)), semantic_key, revision,
            supersedes, frame["source_generation_id"], scope, site_id,
            frame["logical_role"], frame["classification"],
            self._timestamp_optional(frame.get("published_at")),
            self._timestamp_optional(frame.get("fetched_at")), timestamp_us(frame["known_at"]),
            timestamp_us(frame["captured_at"]), self._timestamp_optional(frame.get("valid_from")),
            self._timestamp_optional(frame.get("valid_to")), frame["quality_status"],
            json.dumps(frame.get("quality", {}), sort_keys=True),
            json.dumps(frame.get("provenance", {}), sort_keys=True), frame["payload_schema"],
        )
        try:
            connection.execute(
                """INSERT INTO external_input_frames(
                    frame_id, schema_version, dataset_version, semantic_key, revision,
                    supersedes_frame_id, source_generation_id, source_scope, site_id,
                    logical_role, classification, published_at_us, fetched_at_us,
                    known_at_us, captured_at_us, valid_from_us, valid_to_us,
                    quality_status, quality_json, provenance_json, payload_schema
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
            valid_from = self._timestamp_optional(frame.get("valid_from"))
            valid_to = self._timestamp_optional(frame.get("valid_to"))
            for point in points:
                value = point.get("value")
                if value is not None and not math.isfinite(float(value)):
                    raise ValueError("nonfinite_external_point")
                valid_at = timestamp_us(point["valid_at"])
                if valid_from is not None and valid_at < valid_from:
                    raise ValueError("external_point_before_frame")
                if valid_to is not None and valid_at >= valid_to:
                    raise ValueError("external_point_after_frame")
                connection.execute(
                    """INSERT INTO external_input_points(
                        point_id, frame_id, point_key, valid_at_us, value, unit,
                        quality_status, point_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        point["point_id"], frame["frame_id"], point["point_key"], valid_at,
                        float(value) if value is not None else None, point["unit"],
                        point["quality_status"], json.dumps(point.get("point", {}), sort_keys=True),
                    ),
                )
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise

    @_serialized
    def latest_external_frame(self, semantic_key: str) -> tuple[str, int, str | None] | None:
        """Return the newest immutable revision for one semantic frame."""
        return self._connection().execute(
            "SELECT frame_id, revision, supersedes_frame_id FROM external_input_frames WHERE semantic_key = ? ORDER BY revision DESC LIMIT 1",
            (semantic_key,),
        ).fetchone()

    @_serialized
    def latest_external_frame_snapshot(self, semantic_key: str) -> dict[str, Any] | None:
        """Return the latest frame and point payload for deterministic deduplication."""
        row = self._connection().execute(
            """SELECT frame_id, revision, supersedes_frame_id, source_generation_id,
                      source_scope, site_id, logical_role, classification,
                      published_at_us, fetched_at_us, known_at_us, captured_at_us,
                      valid_from_us, valid_to_us, quality_status, quality_json,
                      provenance_json, payload_schema
                 FROM external_input_frames
                WHERE semantic_key = ? ORDER BY revision DESC LIMIT 1""",
            (semantic_key,),
        ).fetchone()
        if row is None:
            return None
        points = self._connection().execute(
            """SELECT point_id, point_key, valid_at_us, value, unit, quality_status, point_json
                 FROM external_input_points WHERE frame_id = ? ORDER BY point_key""",
            (row[0],),
        ).fetchall()
        keys = (
            "frame_id", "revision", "supersedes_frame_id", "source_generation_id", "source_scope",
            "site_id", "logical_role", "classification", "published_at_us", "fetched_at_us",
            "known_at_us", "captured_at_us", "valid_from_us", "valid_to_us", "quality_status",
            "quality_json", "provenance_json", "payload_schema",
        )
        return {"frame": dict(zip(keys, row)), "points": [dict(zip(("point_id", "point_key", "valid_at_us", "value", "unit", "quality_status", "point_json"), item)) for item in points]}

    @_serialized
    def external_history_status_for_identity_domain(self, dataset: str, identity_domain_id: str) -> str:
        """Classify dependent history without requiring the current secret key."""
        if not dataset or not identity_domain_id:
            raise ValueError("external_history_identity_required")
        try:
            rows = self._connection().execute(
                """SELECT f.provenance_json, g.source_identity_provenance
                     FROM external_input_frames AS f
                     JOIN source_generations AS g
                       ON g.source_generation_id = f.source_generation_id
                    WHERE f.logical_role = ?""",
                (dataset,),
            ).fetchall()
        except sqlite3.Error as err:
            raise RuntimeError("external_history_query_failed") from err
        for provenance_json, source_identity_provenance in rows:
            parsed_values = []
            for raw in (provenance_json, source_identity_provenance):
                try:
                    value = json.loads(raw) if isinstance(raw, str) else raw
                except (TypeError, ValueError) as err:
                    return HISTORY_UNKNOWN
                if value is not None and not isinstance(value, dict):
                    return HISTORY_UNKNOWN
                parsed_values.append(value)
            if any(isinstance(value, dict) and value.get("identity_domain_id") == identity_domain_id for value in parsed_values):
                return HISTORY_FOUND
            if not any(isinstance(value, dict) and isinstance(value.get("identity_domain_id"), str) for value in parsed_values):
                return HISTORY_UNKNOWN
        return HISTORY_NONE

    def has_external_history_for_identity_domain(self, dataset: str, identity_domain_id: str) -> bool:
        """Compatibility wrapper; unknown history is fail-closed."""
        status = self.external_history_status_for_identity_domain(dataset, identity_domain_id)
        if status == HISTORY_UNKNOWN:
            raise RuntimeError("external_history_unknown")
        return status == HISTORY_FOUND

    @_serialized
    def read_external_input_frames(
        self,
        decision_at: datetime,
        *,
        source_scope: str | None = None,
        site_id: str | None = None,
        logical_role: str | None = None,
        valid_at: datetime | None = None,
        source_generation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read external frames visible to one decision time without current-state lookup."""
        decision_us = timestamp_us(decision_at)
        valid_at_us = timestamp_us(valid_at) if valid_at is not None else None
        if source_scope not in {None, "site", "global"}:
            raise ValueError("external_source_scope_invalid")
        if source_scope == "site" and not site_id:
            raise ValueError("external_site_id_required")
        if source_scope == "global" and site_id is not None:
            raise ValueError("external_global_site_id")
        if site_id is not None and source_scope is None:
            raise ValueError("external_site_scope_required")

        clauses = [
            "f.known_at_us <= ?",
            "g.created_at_us <= ?",
        ]
        params: list[Any] = [decision_us, decision_us]
        if source_scope is not None:
            clauses.append("f.source_scope = ?")
            params.append(source_scope)
        if site_id is not None:
            clauses.append("f.site_id = ?")
            params.append(site_id)
        if logical_role is not None:
            clauses.append("f.logical_role = ?")
            params.append(logical_role)
        if source_generation_id is not None:
            clauses.append("f.source_generation_id = ?")
            params.append(source_generation_id)
        if valid_at_us is not None:
            clauses.append(
                "(f.valid_from_us IS NULL OR f.valid_from_us <= ?) "
                "AND (f.valid_to_us IS NULL OR f.valid_to_us > ?)"
            )
            params.extend([valid_at_us, valid_at_us])
        rows = self._connection().execute(
            """
            SELECT f.frame_id, f.schema_version, f.dataset_version, f.semantic_key,
                   f.revision, f.supersedes_frame_id, f.source_generation_id,
                   f.source_scope, f.site_id, f.logical_role, f.classification,
                   f.published_at_us, f.fetched_at_us, f.known_at_us,
                   f.captured_at_us, f.valid_from_us, f.valid_to_us,
                   f.quality_status, f.quality_json, f.provenance_json,
                   f.payload_schema
              FROM external_input_frames AS f
              JOIN source_generations AS g
                ON g.source_generation_id = f.source_generation_id
             WHERE """
            + " AND ".join(clauses)
            + " ORDER BY f.semantic_key, f.known_at_us, f.revision, f.frame_id",
            params,
        ).fetchall()

        eligible: dict[str, tuple[Any, ...]] = {}
        for row in rows:
            key = str(row[3])
            previous = eligible.get(key)
            if previous is None or (int(row[13]), int(row[4]), str(row[0])) > (
                int(previous[13]), int(previous[4]), str(previous[0])
            ):
                eligible[key] = row

        results: list[dict[str, Any]] = []
        connection = self._connection()
        for row in eligible.values():
            points = connection.execute(
                """
                SELECT point_id, point_key, valid_at_us, value, unit,
                       quality_status, point_json
                  FROM external_input_points
                 WHERE frame_id = ?
                 ORDER BY point_key
                """,
                (row[0],),
            ).fetchall()
            if valid_at_us is not None:
                points = [point for point in points if int(point[2]) == valid_at_us]
                if not points:
                    continue
            result = {
                "frame_id": row[0],
                "schema_version": row[1],
                "dataset_version": row[2],
                "semantic_key": row[3],
                "revision": row[4],
                "supersedes_frame_id": row[5],
                "source_generation_id": row[6],
                "source_scope": row[7],
                "site_id": row[8],
                "logical_role": row[9],
                "classification": row[10],
                "published_at": self._datetime_optional(row[11]),
                "fetched_at": self._datetime_optional(row[12]),
                "known_at": self._datetime_optional(row[13]),
                "captured_at": self._datetime_optional(row[14]),
                "valid_from": self._datetime_optional(row[15]),
                "valid_to": self._datetime_optional(row[16]),
                "quality_status": row[17],
                "quality": json.loads(row[18]),
                "provenance": json.loads(row[19]),
                "payload_schema": row[20],
                "points": [
                    {
                        "point_id": point[0],
                        "point_key": point[1],
                        "valid_at": self._datetime_optional(point[2]),
                        "value": point[3],
                        "unit": point[4],
                        "quality_status": point[5],
                        "point": json.loads(point[6]),
                    }
                    for point in points
                ],
            }
            known_at_us = int(row[13])
            if known_at_us > decision_us:
                raise RuntimeError("external_replay_known_at_invariant")
            results.append(result)
        return results

    @staticmethod
    def _timestamp_optional(value: datetime | None) -> int | None:
        return timestamp_us(value) if value is not None else None

    @staticmethod
    def _datetime_optional(value: int | None) -> datetime | None:
        return datetime.fromtimestamp(value / 1_000_000, tz=timezone.utc) if value is not None else None

    def _external_frame_matches(self, connection, frame: dict[str, Any], points: list[dict[str, Any]]) -> bool:
        row = connection.execute(
            """SELECT frame_id, schema_version, dataset_version, semantic_key, revision,
                      supersedes_frame_id, source_generation_id, source_scope, site_id,
                      logical_role, classification, published_at_us, fetched_at_us,
                      known_at_us, captured_at_us, valid_from_us, valid_to_us,
                      quality_status, quality_json, provenance_json, payload_schema
                 FROM external_input_frames WHERE semantic_key = ? AND revision = ?""",
            (frame["semantic_key"], int(frame.get("revision", 1))),
        ).fetchone()
        if row is None:
            return False
        expected_provenance = dict(frame.get("provenance", {}))
        stored_provenance = json.loads(row[19])
        # A single-run response receipt is transport metadata that can change
        # when the same provider run is observed again.  Keep this exception
        # scoped to that immutable dataset; every other dataset compares its
        # provenance byte-for-byte as part of its revision identity.
        if frame.get("payload_schema") == "open_meteo.single_run_day_ahead_pv.v1":
            expected_provenance.pop("provider_response_received_at", None)
            stored_provenance.pop("provider_response_received_at", None)
        expected = (
            int(frame.get("schema_version", SCHEMA_VERSION)),
            int(frame.get("dataset_version", DATASET_VERSION)), frame["semantic_key"],
            int(frame.get("revision", 1)), frame.get("supersedes_frame_id"),
            frame["source_generation_id"], frame["source_scope"], frame.get("site_id"),
            frame["logical_role"], frame["classification"],
            self._timestamp_optional(frame.get("published_at")),
            self._timestamp_optional(frame.get("valid_from")),
            self._timestamp_optional(frame.get("valid_to")), frame["quality_status"],
            json.dumps(frame.get("quality", {}), sort_keys=True),
            json.dumps(expected_provenance, sort_keys=True), frame["payload_schema"],
        )
        comparable = row[1:11] + (row[11], row[15], row[16], row[17], row[18], json.dumps(stored_provenance, sort_keys=True), row[20])
        if comparable != expected:
            return False
        stored = connection.execute(
            "SELECT point_id, point_key, valid_at_us, value, unit, quality_status, point_json FROM external_input_points WHERE frame_id = ? ORDER BY point_key",
            (frame["frame_id"],),
        ).fetchall()
        expected_points = sorted(
            (
                point["point_id"], point["point_key"], timestamp_us(point["valid_at"]),
                float(point["value"]) if point.get("value") is not None else None, point["unit"],
                point["quality_status"], json.dumps(point.get("point", {}), sort_keys=True),
            )
            for point in points
        )
        return stored == expected_points

    @_serialized
    def count_external_frames(self) -> int:
        return int(self._connection().execute("SELECT COUNT(*) FROM external_input_frames").fetchone()[0])

    @_serialized
    def insert_observation(self, observation: dict[str, Any]) -> bool:
        """Insert one immutable revision; return false for an exact replay."""
        connection = self._connection()
        try:
            inserted = self._insert_observation(connection, observation)
            connection.commit()
            return inserted
        except Exception:
            connection.rollback()
            raise

    @_serialized
    def insert_observations_atomic(self, observations: list[dict[str, Any]]) -> int:
        """Insert a finalized quarter batch in one durable transaction."""
        connection = self._connection()
        inserted = 0
        try:
            for observation in observations:
                inserted += int(self._insert_observation(connection, observation))
            connection.commit()
            return inserted
        except Exception:
            connection.rollback()
            raise

    @_serialized
    def insert_historical_observations_atomic(self, observations: list[dict[str, Any]]) -> int:
        """Insert immutable provider observations with their native resolution."""
        connection = self._connection()
        inserted = 0
        try:
            for observation in observations:
                inserted += int(self._insert_historical_observation(connection, observation))
            connection.commit()
            return inserted
        except Exception:
            connection.rollback()
            raise

    def _insert_historical_observation(self, connection: sqlite3.Connection, observation: dict[str, Any]) -> bool:
        """Insert one native-resolution observation without committing."""
        value = observation.get("value")
        if value is not None:
            value = float(value)
            if not math.isfinite(value):
                raise ValueError("nonfinite_observation")
        start = observation["interval_start"]
        end = observation["interval_end"]
        resolution_seconds = int(observation["resolution_seconds"])
        if start.tzinfo is None or end.tzinfo is None or resolution_seconds <= 0 or end <= start:
            raise ValueError("historical_observation_interval_invalid")
        columns = (
            "record_id, schema_version, dataset_version, semantic_key, revision, supersedes_record_id, "
            "site_id, logical_role, source_generation_id, interval_start_us, interval_end_us, "
            "resolution_seconds, source_resolution_kind, source_resolution_seconds, observed_at_us, "
            "captured_at_us, fetched_at_us, known_at_us, classification, value, unit, sign_convention, "
            "quality_status, coverage_ratio, gap_status, quality_json, provenance_json"
        )
        values = (
            observation.get("record_id") or str(uuid.uuid4()), SCHEMA_VERSION, DATASET_VERSION,
            observation["semantic_key"], int(observation.get("revision", 1)), observation.get("supersedes_record_id"),
            observation["site_id"], observation["logical_role"], observation["source_generation_id"],
            timestamp_us(start), timestamp_us(end), resolution_seconds,
            observation.get("source_resolution_kind", "native_bucket"),
            int(observation.get("source_resolution_seconds", resolution_seconds)),
            timestamp_us(observation["observed_at"]) if observation.get("observed_at") else None,
            timestamp_us(observation["captured_at"]), timestamp_us(observation["fetched_at"]) if observation.get("fetched_at") else None,
            timestamp_us(observation["known_at"]), observation.get("classification", "measured"), value,
            observation["unit"], observation["sign_convention"], observation["quality_status"],
            observation.get("coverage_ratio"), observation["gap_status"],
            json.dumps(observation.get("quality", {}), sort_keys=True),
            json.dumps(observation.get("provenance", {}), sort_keys=True),
        )
        try:
            cursor = connection.execute(
                f"INSERT INTO historical_energy_observations({columns}) VALUES ({','.join('?' for _ in values)})",
                values,
            )
        except sqlite3.DatabaseError as error:
            if "historical_energy_observations.semantic_key, historical_energy_observations.revision" not in str(error):
                raise
            existing = connection.execute(
                """SELECT record_id, site_id, logical_role, source_generation_id, interval_start_us, interval_end_us,
                          resolution_seconds, source_resolution_kind, source_resolution_seconds, observed_at_us,
                          value, unit, sign_convention, quality_status, coverage_ratio, gap_status,
                          quality_json, provenance_json
                     FROM historical_energy_observations WHERE semantic_key = ? AND revision = ?""",
                (observation["semantic_key"], int(observation.get("revision", 1))),
            ).fetchone()
            expected = (
                observation["site_id"], observation["logical_role"], observation["source_generation_id"],
                timestamp_us(start), timestamp_us(end), resolution_seconds,
                observation.get("source_resolution_kind", "native_bucket"), int(observation.get("source_resolution_seconds", resolution_seconds)),
                timestamp_us(observation["observed_at"]) if observation.get("observed_at") else None, value,
                observation["unit"], observation["sign_convention"], observation["quality_status"],
                observation.get("coverage_ratio"), observation["gap_status"],
                json.dumps(observation.get("quality", {}), sort_keys=True),
                json.dumps(observation.get("provenance", {}), sort_keys=True),
            )
            if existing is None:
                raise
            if existing[1:] == expected:
                return False
            if (
                existing[1:16] == expected[:15]
                and existing[16] == expected[15]
                and _is_provenance_enrichment(existing[17], expected[16])
            ):
                latest = connection.execute(
                    """SELECT record_id, revision, site_id, logical_role, source_generation_id,
                              interval_start_us, interval_end_us, resolution_seconds,
                              source_resolution_kind, source_resolution_seconds, observed_at_us,
                              value, unit, sign_convention, quality_status, coverage_ratio, gap_status,
                              quality_json, provenance_json
                         FROM historical_energy_observations
                        WHERE semantic_key = ? ORDER BY revision DESC LIMIT 1""",
                    (observation["semantic_key"],),
                ).fetchone()
                if latest is None or latest[2:17] != expected[:15] or latest[17] != expected[15]:
                    raise ValueError("canonical_historical_revision_conflict") from error
                if latest[18] == expected[16]:
                    return False
                if not _is_provenance_enrichment(latest[18], expected[16]):
                    raise ValueError("canonical_historical_revision_conflict") from error
                revision = int(latest[1]) + 1
                revision_values = list(values)
                revision_values[0] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{observation['semantic_key']}|revision={revision}"))
                revision_values[4] = revision
                revision_values[5] = latest[0]
                connection.execute(
                    f"INSERT INTO historical_energy_observations({columns}) VALUES ({','.join('?' for _ in revision_values)})",
                    tuple(revision_values),
                )
                return True
            raise ValueError("canonical_historical_revision_conflict") from error
        return cursor.rowcount == 1

    def _insert_observation(self, connection: sqlite3.Connection, observation: dict[str, Any]) -> bool:
        """Insert one row without committing; the caller owns the transaction."""
        value = observation.get("value")
        if value is not None:
            value = float(value)
            if not math.isfinite(value):
                raise ValueError("nonfinite_observation")
        start = observation["interval_start"]
        end = start.timestamp() + QUARTER_SECONDS
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
        columns = (
            "record_id, schema_version, dataset_version, semantic_key, revision, supersedes_record_id, "
            "site_id, logical_role, source_generation_id, interval_start_us, interval_end_us, "
            "resolution_seconds, source_resolution_kind, source_resolution_seconds, observed_at_us, "
            "captured_at_us, fetched_at_us, known_at_us, classification, value, unit, sign_convention, "
            "quality_status, coverage_ratio, gap_status, quality_json, provenance_json"
        )
        values = (
            observation.get("record_id") or str(uuid.uuid4()), SCHEMA_VERSION, DATASET_VERSION,
            observation["semantic_key"], int(observation.get("revision", 1)), observation.get("supersedes_record_id"),
            observation["site_id"], observation["logical_role"], observation["source_generation_id"],
            timestamp_us(start), timestamp_us(end_dt), QUARTER_SECONDS, "event_stream", None,
            timestamp_us(observation["observed_at"]) if observation.get("observed_at") else None,
            timestamp_us(observation["captured_at"]), None, timestamp_us(observation["known_at"]),
            observation.get("classification", "measured"), value, observation["unit"], observation["sign_convention"],
            observation["quality_status"], observation.get("coverage_ratio"), observation["gap_status"],
            json.dumps(observation.get("quality", {}), sort_keys=True),
            json.dumps(observation.get("provenance", {}), sort_keys=True),
        )
        try:
            cursor = connection.execute(
                f"INSERT INTO energy_observations({columns}) VALUES ({','.join('?' for _ in values)})",
                values,
            )
        except sqlite3.IntegrityError as error:
            if "energy_observations.semantic_key, energy_observations.revision" not in str(error):
                raise
            existing = connection.execute(
                """SELECT site_id, logical_role, source_generation_id,
                   interval_start_us, interval_end_us, resolution_seconds,
                   source_resolution_kind, observed_at_us,
                   value, unit, sign_convention, quality_status, coverage_ratio,
                   gap_status, quality_json, provenance_json
                   FROM energy_observations WHERE semantic_key = ? AND revision = ?""",
                (observation["semantic_key"], int(observation.get("revision", 1))),
            ).fetchone()
            expected = (
                observation["site_id"], observation["logical_role"],
                observation["source_generation_id"], timestamp_us(start), timestamp_us(end_dt), QUARTER_SECONDS,
                "event_stream", timestamp_us(observation["observed_at"]) if observation.get("observed_at") else None, value,
                observation["unit"], observation["sign_convention"], observation["quality_status"],
                observation.get("coverage_ratio"), observation["gap_status"],
                json.dumps(observation.get("quality", {}), sort_keys=True),
                json.dumps(observation.get("provenance", {}), sort_keys=True),
            )
            if existing == expected:
                return False
            raise ValueError("canonical_revision_conflict") from error
        return cursor.rowcount == 1

    def read_site_energy_history(self, site_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Read immutable site energy rows through a dedicated read-only WAL connection."""
        if not site_id or start.tzinfo is None or end.tzinfo is None or end <= start:
            return []
        start_us = timestamp_us(start)
        end_us = timestamp_us(end)
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            rows: list[tuple[Any, ...]] = []
            for table in ("historical_energy_observations", "energy_observations"):
                rows.extend(connection.execute(
                    f"""SELECT record_id, logical_role, source_generation_id, interval_start_us, interval_end_us,
                               resolution_seconds, value, unit, sign_convention, quality_status,
                               coverage_ratio, gap_status, semantic_key, revision,
                               CASE WHEN ? = 'energy_observations' THEN 1 ELSE 0 END AS live_priority,
                               site_id, provenance_json
                          FROM {table} AS current
                         WHERE site_id = ?
                           AND interval_start_us < ?
                           AND interval_end_us > ?
                           AND NOT EXISTS (
                               SELECT 1 FROM {table} AS newer
                                WHERE newer.semantic_key = current.semantic_key
                                  AND newer.revision > current.revision
                           )""",
                    (table, site_id, end_us, start_us),
                ).fetchall())
        finally:
            connection.close()
        latest: dict[tuple[str, str, int, int], tuple[Any, ...]] = {}
        for row in rows:
            key = (str(row[1]), str(row[2]), int(row[3]), int(row[4]))
            previous = latest.get(key)
            if previous is None or (int(row[14]), int(row[13])) > (int(previous[14]), int(previous[13])):
                latest[key] = row
        return [
            {
                "record_id": row[0],
                "logical_role": row[1],
                "source_generation_id": row[2],
                "interval_start": datetime.fromtimestamp(row[3] / 1_000_000, tz=timezone.utc),
                "interval_end": datetime.fromtimestamp(row[4] / 1_000_000, tz=timezone.utc),
                "resolution_seconds": int(row[5]),
                "value": row[6],
                "unit": row[7],
                "sign_convention": row[8],
                "quality_status": row[9],
                "coverage_ratio": row[10],
                "gap_status": row[11],
                "semantic_key": row[12],
                "revision": int(row[13]),
                "storage_class": "canonical" if int(row[14]) else "historical",
                "site_id": row[15],
                "provenance": json.loads(row[16]) if row[16] else {},
            }
            for row in sorted(latest.values(), key=lambda item: (item[3], item[1], item[2]))
        ]

    @_serialized
    def count_observations(self) -> int:
        return int(self._connection().execute("SELECT COUNT(*) FROM energy_observations").fetchone()[0])

    @_serialized
    def reconcile_grid_import(self, site_id: str, start: datetime, end: datetime) -> int:
        """Persist the derived view while leaving raw rows immutable."""
        from .grid_reconciliation import reconcile_grid_import
        rows = self.read_site_energy_history(site_id, start, end)
        derived = reconcile_grid_import(rows)
        connection = self._connection()
        for item in derived:
            connection.execute(
                """INSERT INTO reconciled_grid_import(
                    reconciliation_id, site_id, logical_role, interval_start_us, interval_end_us,
                    resolution_seconds, value, unit, source_status, correction_reason,
                    local_record_id, provider_record_id, local_value, provider_value, known_at_us, provenance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_id, interval_start_us, interval_end_us, resolution_seconds) DO UPDATE SET
                    value=excluded.value, source_status=excluded.source_status,
                    correction_reason=excluded.correction_reason, local_record_id=excluded.local_record_id,
                    provider_record_id=excluded.provider_record_id, local_value=excluded.local_value,
                    provider_value=excluded.provider_value, known_at_us=excluded.known_at_us,
                    provenance_json=excluded.provenance_json""",
                (f"{site_id}|grid.energy_import|{item['interval_start'].isoformat()}|{item['resolution_seconds']}",
                 site_id, item["logical_role"], timestamp_us(item["interval_start"]), timestamp_us(item["interval_end"]),
                 item["resolution_seconds"], item["value"], item["unit"], item["source_status"], item["correction_reason"],
                 item.get("local_record_id"), item.get("provider_record_id"), item.get("local_value"), item.get("provider_value"),
                 timestamp_us(item["known_at"]) if item.get("known_at") else None,
                 json.dumps(item["provenance"], sort_keys=True)),
            )
        connection.commit()
        return len(derived)

    @_serialized
    def read_reconciled_grid_import(self, site_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Read the derived site-scoped grid-import series."""
        rows = self._connection().execute(
            """SELECT interval_start_us, interval_end_us, resolution_seconds, value, unit,
                      source_status, correction_reason, local_record_id, provider_record_id,
                      local_value, provider_value, known_at_us, provenance_json FROM reconciled_grid_import
                WHERE site_id = ? AND interval_start_us < ? AND interval_end_us > ?
                ORDER BY interval_start_us""",
            (site_id, timestamp_us(end), timestamp_us(start)),
        ).fetchall()
        return [{
            "site_id": site_id, "logical_role": "grid.energy_import",
            "interval_start": datetime.fromtimestamp(row[0] / 1_000_000, tz=timezone.utc),
            "interval_end": datetime.fromtimestamp(row[1] / 1_000_000, tz=timezone.utc),
            "resolution_seconds": row[2], "value": row[3], "unit": row[4],
            "source_status": row[5], "correction_reason": row[6],
            "local_record_id": row[7], "provider_record_id": row[8],
            "local_value": row[9], "provider_value": row[10],
            "known_at": datetime.fromtimestamp(row[11] / 1_000_000, tz=timezone.utc) if row[11] else None,
            "provenance": json.loads(row[12]) if row[12] else {},
        } for row in rows]

    @_serialized
    def observation_exists(self, semantic_key: str, revision: int = 1) -> bool:
        return self._connection().execute(
            "SELECT 1 FROM energy_observations WHERE semantic_key = ? AND revision = ?",
            (semantic_key, revision),
        ).fetchone() is not None

    @_serialized
    def existing_observation_keys(self, semantic_keys: list[str]) -> set[str]:
        if not semantic_keys:
            return set()
        placeholders = ",".join("?" for _ in semantic_keys)
        rows = self._connection().execute(
            f"SELECT semantic_key FROM energy_observations WHERE revision = 1 AND semantic_key IN ({placeholders})",
            semantic_keys,
        ).fetchall()
        return {row[0] for row in rows}
