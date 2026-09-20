"""Deterministic, read-only load forecast frames for ELLA and billing UI."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .canonical_storage import CanonicalStorage


DATASET = "load_forecast.v1"
PAYLOAD_SCHEMA = "load_forecast.v1"
LOGICAL_ROLE = "load.forecast"
MODEL_VERSION = "load-profile-v1"
MIN_DISTINCT_DAYS = 7
SLOT_SECONDS = 900


def _quarter_start(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc).replace(second=0, microsecond=0)
    return value - timedelta(minutes=value.minute % 15)


def _generation_id(site_id: str, source_generations: set[str]) -> str:
    identity = {"dataset": DATASET, "model_version": MODEL_VERSION, "site_id": site_id,
                "source_generations": sorted(source_generations)}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]
    return f"load-{digest}"


def _profile_buckets(history: list[dict[str, Any]], timezone_name: str):
    """Build the shared weekday/time-of-day profile used by load forecasts."""
    try:
        zone = ZoneInfo(timezone_name)
    except Exception:
        return None
    rows = []
    for row in history:
        if row.get("logical_role") != "house.consumption" or row.get("value") is None:
            continue
        if row.get("quality_status") not in {"good", "partial"}:
            continue
        interval_start = row.get("interval_start")
        if not isinstance(interval_start, datetime) or interval_start.tzinfo is None:
            continue
        try:
            value = float(row["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if value < 0 or not math.isfinite(value):
            continue
        rows.append((row, interval_start.astimezone(zone), value))
    if not rows:
        return None
    by_weekday_slot: dict[tuple[int, int], list[tuple[float, dict[str, Any]]]] = defaultdict(list)
    by_slot: dict[int, list[tuple[float, dict[str, Any]]]] = defaultdict(list)
    for row, local, value in rows:
        slot = local.hour * 4 + local.minute // 15
        by_weekday_slot[(local.weekday(), slot)].append((value, row))
        by_slot[slot].append((value, row))
    return zone, by_weekday_slot, by_slot


def build_historical_model_points(
    history: list[dict[str, Any]],
    timezone_name: str,
    target_start: datetime,
    target_end: datetime,
) -> list[dict[str, Any]]:
    """Return supported model estimates using the canonical forecast profile."""
    profile = _profile_buckets(history, timezone_name)
    if profile is None or target_start.tzinfo is None or target_end.tzinfo is None:
        return []
    zone, by_weekday_slot, by_slot = profile
    points = []
    cursor = _quarter_start(target_start)
    while cursor < target_end:
        local = cursor.astimezone(zone)
        slot = local.hour * 4 + local.minute // 15
        candidates = by_weekday_slot.get((local.weekday(), slot), [])
        support = "weekday_slot"
        if not candidates:
            candidates = by_slot.get(slot, [])
            support = "all_weekdays_slot"
        if candidates:
            values = [value for value, _row in candidates]
            source_generations = sorted({str(row.get("source_generation_id")) for _value, row in candidates if row.get("source_generation_id")})
            points.append({
                "valid_at": cursor,
                "value": sum(values) / len(values),
                "unit": "W",
                "frame_id": None,
                "quality": {"status": "model", "sample_support": len(values), "support_method": support},
                "source_generation_id": source_generations[0] if len(source_generations) == 1 else None,
                "source_generation_ids": source_generations,
                "source": "model",
            })
        cursor += timedelta(seconds=SLOT_SECONDS)
    return points


def build_load_forecast_frame(
    site_id: str,
    timezone_name: str,
    history: list[dict[str, Any]],
    known_at: datetime,
    horizon_hours: int = 36,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Build a 15-minute forecast only from observed canonical load points.

    A target is omitted when no comparable historical support exists. No zero
    values are used as an unknown-data placeholder.
    """
    if not site_id or not isinstance(history, list) or known_at.tzinfo is None:
        return None, []
    try:
        zone = ZoneInfo(timezone_name)
    except Exception:
        return None, []
    rows = [row for row in history if row.get("logical_role") == "house.consumption"
            and row.get("value") is not None and row.get("quality_status") in {"good", "partial"}]
    if not rows:
        return None, []
    observed_days = {row["interval_start"].astimezone(zone).date() for row in rows}
    if len(observed_days) < MIN_DISTINCT_DAYS:
        return None, []
    source_generations = {str(row["source_generation_id"]) for row in rows if row.get("source_generation_id")}
    if not source_generations:
        return None, []
    profile = _profile_buckets(rows, timezone_name)
    if profile is None:
        return None, []
    _zone, by_weekday_slot, by_slot = profile
    target_start = _quarter_start(known_at.astimezone(zone) + timedelta(minutes=15)).astimezone(timezone.utc)
    target_end = target_start + timedelta(hours=horizon_hours)
    points: list[dict[str, Any]] = []
    cursor = target_start
    while cursor < target_end:
        local = cursor.astimezone(zone)
        slot = local.hour * 4 + local.minute // 15
        candidates = by_weekday_slot.get((local.weekday(), slot), [])
        support = "weekday_slot"
        if not candidates:
            candidates = by_slot.get(slot, [])
            support = "all_weekdays_slot"
        if candidates:
            value = sum(item[0] for item in candidates) / len(candidates)
            points.append({
                "point_id": "", "point_key": cursor.isoformat(), "valid_at": cursor,
                "value": value, "unit": "W", "quality_status": "good",
                "point": {"forecast_w": value, "sample_support": len(candidates),
                          "support_method": support, "model_version": MODEL_VERSION},
            })
        cursor += timedelta(seconds=SLOT_SECONDS)
    if not points:
        return None, []
    generation_id = _generation_id(site_id, source_generations)
    semantic_key = f"{DATASET}|site:{site_id}|generation:{generation_id}|target:{target_start.date().isoformat()}"
    # Canonical quality_status is schema-bound; retain confidence detail in
    # the quality object instead of introducing a non-canonical status value.
    quality_status = "good" if all(point["point"]["sample_support"] >= 2 for point in points) else "partial"
    confidence_status = "good" if quality_status == "good" else "low_confidence"
    quality = {
        "status": confidence_status, "model_version": MODEL_VERSION,
        "sample_support_min": min(point["point"]["sample_support"] for point in points),
        "sample_support_max": max(point["point"]["sample_support"] for point in points),
        "observed_days": len(observed_days), "source_generations": sorted(source_generations),
    }
    content = json.dumps([{key: value for key, value in point.items() if key != "point_id"}
                          for point in points], sort_keys=True, default=str, separators=(",", ":"))
    frame_id = "frame-" + hashlib.sha256((semantic_key + "|" + content).encode()).hexdigest()[:32]
    for index, point in enumerate(points, 1):
        point["point_id"] = f"{frame_id}-p{index:03d}"
    frame = {
        "frame_id": frame_id, "schema_version": 1, "dataset_version": 1,
        "semantic_key": semantic_key, "revision": 1, "supersedes_frame_id": None,
        "source_generation_id": generation_id, "source_scope": "site", "site_id": site_id,
        "logical_role": LOGICAL_ROLE, "classification": "forecast", "published_at": None,
        "fetched_at": None, "known_at": known_at.astimezone(timezone.utc),
        "captured_at": known_at.astimezone(timezone.utc), "valid_from": target_start,
        "valid_to": target_end, "quality_status": quality_status, "quality": quality,
        "provenance": {"origin_type": "canonical_energy_observations", "site_id": site_id,
                        "model_version": MODEL_VERSION, "source_generations": sorted(source_generations),
                        "capture_contract": PAYLOAD_SCHEMA}, "payload_schema": PAYLOAD_SCHEMA,
    }
    return frame, points


def persist_load_forecast(storage: CanonicalStorage, frame: dict[str, Any], points: list[dict[str, Any]], captured_at: datetime) -> bool:
    """Persist one immutable forecast revision using existing canonical storage."""
    storage.ensure_source_generation({
        "site_id": frame["site_id"], "logical_role": frame["logical_role"],
        "generation_id": frame["source_generation_id"],
        "source_identity": {"identity_key": frame["source_generation_id"], "identity_strength": "strong",
                             "identity_provenance": "canonical_load_observation_profile"},
        # The storage contract describes the 15-minute source buckets used by
        # this profile; derived provenance is carried separately below.
        "source_resolution_kind": "native_bucket", "source_resolution_seconds": SLOT_SECONDS,
        "timezone_state": "verified",
    }, captured_at)
    latest = storage.latest_external_frame(frame["semantic_key"])
    if latest:
        frame["revision"] = latest[1]
        frame["frame_id"] = latest[0]
        frame["supersedes_frame_id"] = latest[2]
        try:
            return storage.insert_external_frame(frame, points)
        except ValueError as error:
            if str(error) != "canonical_frame_revision_conflict":
                raise
            frame["revision"] = latest[1] + 1
            frame["supersedes_frame_id"] = latest[0]
            digest = hashlib.sha256((frame["semantic_key"] + "|" + str(frame["revision"]) + "|" + json.dumps([point["point"] for point in points], sort_keys=True)).encode()).hexdigest()[:32]
            frame["frame_id"] = "frame-" + digest
            for index, point in enumerate(points, 1):
                point["point_id"] = f"{frame['frame_id']}-p{index:03d}"
            return storage.insert_external_frame(frame, points)
    return storage.insert_external_frame(frame, points)


def build_site_load_forecast(storage: CanonicalStorage, site_id: str, timezone_name: str, now: datetime) -> dict[str, Any]:
    """Build and persist one site's forecast without active-site dependence."""
    history = storage.read_site_energy_history(site_id, now - timedelta(days=60), now)
    frame, points = build_load_forecast_frame(site_id, timezone_name, history, now)
    if frame is None:
        return {"site_id": site_id, "available": False, "reason": "insufficient_historical_support", "point_count": 0}
    written = persist_load_forecast(storage, frame, points, now)
    return {
        "site_id": site_id, "available": True, "frame_id": frame["frame_id"],
        "semantic_key": frame["semantic_key"], "revision": frame["revision"],
        "point_count": len(points), "quality_status": frame["quality_status"],
        "known_at": frame["known_at"].isoformat(), "written": bool(written),
    }
