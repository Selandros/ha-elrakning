"""Immutable provenance records for future Solar Evidence inputs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any


PROVENANCE_SCHEMA = "solar_evidence.provenance.v1"
FORECAST_SOLAR_DATASET = "forecast_solar.observed_facts.v1"
OPEN_METEO_EVIDENCE_DATASET = "open_meteo.evidence_previous_day1.v1"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def frame_fingerprint(record: dict[str, Any]) -> str:
    """Identify the source knowledge, excluding capture/knowledge timestamps."""
    identity = {
        key: record.get(key)
        for key in (
            "site_id", "source", "dataset", "target", "value", "unit",
            "source_generation_id", "valid_from", "valid_to", "payload",
        )
    }
    return hashlib.sha256(_json(identity).encode()).hexdigest()


def build_provenance_record(
    *,
    site_id: str,
    source: str,
    dataset: str,
    target: str,
    value: float,
    unit: str,
    captured_at: datetime,
    known_at: datetime,
    fetched_at: datetime | None = None,
    source_generation_id: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one immutable source observation without inventing timestamps."""
    record = {
        "schema": PROVENANCE_SCHEMA,
        "site_id": site_id,
        "source": source,
        "dataset": dataset,
        "target": target,
        "value": float(value),
        "unit": unit,
        "captured_at": captured_at.isoformat(),
        "known_at": known_at.isoformat(),
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
        "source_generation_id": source_generation_id,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "payload": payload or {},
    }
    record["frame_fingerprint"] = frame_fingerprint(record)
    return record


def append_immutable(records: list[dict[str, Any]], record: dict[str, Any]) -> bool:
    """Deduplicate identical knowledge and retain changed knowledge."""
    fingerprint = record["frame_fingerprint"]
    if any(item.get("frame_fingerprint") == fingerprint for item in records):
        return False
    semantic_identity = (
        record.get("site_id"),
        record.get("source"),
        record.get("dataset"),
        record.get("target"),
    )
    revisions = []
    for item in records:
        if (
            item.get("site_id"),
            item.get("source"),
            item.get("dataset"),
            item.get("target"),
        ) != semantic_identity:
            continue
        raw_revision = item.get("revision", 0)
        if isinstance(raw_revision, int) and raw_revision >= 0:
            revisions.append(raw_revision)
    stored = dict(record)
    stored["revision"] = max(revisions, default=0) + 1
    records.append(stored)
    records.sort(key=lambda item: (item.get("known_at") or "", item.get("frame_fingerprint") or ""))
    return True


def classify_record(record: dict[str, Any], decision_at: datetime) -> str:
    """Classify an observation using only persisted knowledge time."""
    raw = record.get("known_at")
    if not isinstance(raw, str):
        return "INSUFFICIENT_PROVENANCE"
    try:
        known_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return "INSUFFICIENT_PROVENANCE"
    if known_at <= decision_at:
        return "VERIFIED_PRE_DECISION"
    return "VERIFIED_POST_DECISION"


def select_for_decision(
    records: list[dict[str, Any]],
    *,
    site_id: str,
    dataset: str,
    target: str,
    decision_at: datetime,
) -> tuple[str, dict[str, Any] | None]:
    """Select the latest unambiguous pre-decision observation, fail closed."""
    candidates = [
        item for item in records
        if item.get("site_id") == site_id
        and item.get("dataset") == dataset
        and item.get("target") == target
        and classify_record(item, decision_at) == "VERIFIED_PRE_DECISION"
    ]
    if not candidates:
        return "MISSING", None
    candidates.sort(key=lambda item: (item.get("known_at") or "", item.get("frame_fingerprint") or ""))
    latest_time = candidates[-1].get("known_at")
    latest = [item for item in candidates if item.get("known_at") == latest_time]
    if len({item.get("frame_fingerprint") for item in latest}) != 1:
        return "AMBIGUOUS", None
    return "VERIFIED_PRE_DECISION", latest[0]
