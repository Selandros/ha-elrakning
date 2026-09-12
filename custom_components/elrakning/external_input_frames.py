"""Canonical external input frame producers."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .canonical_storage import DATASET_VERSION, SCHEMA_VERSION, CanonicalStorage
from .solar_forecast import normalize_forecast_value


FORECAST_SOLAR_DATASET = "forecast_solar.observed_facts.v1"
FORECAST_SOLAR_CONTRACT_VERSION = 1
FORECAST_SOLAR_ADAPTER_VERSION = 1
SUPPORTED_FORECAST_SOLAR_ROLES = frozenset({
    "today_kwh",
    "tomorrow_kwh",
    "remaining_today_kwh",
    "power_now_kw",
    "peak_time_today",
    "peak_time_tomorrow",
})
_FORECAST_SOLAR_ROLE_UNITS = {
    "today_kwh": "kWh",
    "tomorrow_kwh": "kWh",
    "remaining_today_kwh": "kWh",
    "power_now_kw": "kW",
    "peak_time_today": "timestamp",
    "peak_time_tomorrow": "timestamp",
}
_FORECAST_SOLAR_TARGET_DAY_OFFSETS = {
    "today_kwh": 0,
    "tomorrow_kwh": 1,
    "remaining_today_kwh": 0,
    "peak_time_today": 0,
    "peak_time_tomorrow": 1,
}

OPEN_METEO_DATASET = "open_meteo.manager_forecast.v1"
OPEN_METEO_LOGICAL_ROLE = "solar.irradiance.forecast"


def build_nord_pool_frame(
    data: Any,
    binding: dict[str, Any],
    captured_at: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Normalize one real Nord Pool response into a global immutable frame."""
    if not data.periods or not binding.get("config_entry_id") or not data.area or not data.currency:
        raise ValueError("nord_pool_frame_inputs_missing")
    captured_at = captured_at.astimezone(timezone.utc)
    entry_id = str(binding["config_entry_id"])
    area = str(data.area)
    currency = str(data.currency)
    identity_key = f"nord_pool|{entry_id}|{area}|{currency}"
    generation_id = "np-" + hashlib.sha256(identity_key.encode()).hexdigest()[:32]
    semantic_key = f"global|market.price.energy|{identity_key}|{data.date.isoformat()}"
    valid_from = min(period.start for period in data.periods).astimezone(timezone.utc)
    valid_to = max(period.end for period in data.periods).astimezone(timezone.utc)
    frame_id = "frame-" + hashlib.sha256(
        (
            f"{semantic_key}|" +
            "|".join(f"{p.start.isoformat()}={p.price:.12g}" for p in data.periods)
        ).encode()
    ).hexdigest()[:32]
    frame = {
        "frame_id": frame_id,
        "schema_version": SCHEMA_VERSION,
        "dataset_version": DATASET_VERSION,
        "semantic_key": semantic_key,
        "revision": 1,
        "source_generation_id": generation_id,
        "source_scope": "global",
        "site_id": None,
        "logical_role": "market.price.energy",
        "classification": "published",
        "published_at": None,
        "fetched_at": captured_at,
        "known_at": captured_at,
        "captured_at": captured_at,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "quality_status": "good",
        "quality": {"status": "good", "period_count": len(data.periods)},
        "provenance": {
            "origin_type": "home_assistant_nord_pool_service",
            "config_entry_id": entry_id,
            "area": area,
            "currency": currency,
            "requested_date": data.date.isoformat(),
            "resolution_minutes": 15,
        },
        "payload_schema": "nord_pool.price_periods.v1",
    }
    points = [
        {
            "point_id": f"{frame_id}-p{index:03d}",
            "point_key": period.start.astimezone(timezone.utc).isoformat(),
            "valid_at": period.start.astimezone(timezone.utc),
            "value": period.price,
            "unit": f"{currency}/kWh",
            "quality_status": "good",
            "point": {"start": period.start.astimezone(timezone.utc).isoformat(), "end": period.end.astimezone(timezone.utc).isoformat()},
        }
        for index, period in enumerate(data.periods)
    ]
    return frame, points


def persist_nord_pool_frame(storage: CanonicalStorage, data: Any, binding: dict[str, Any], captured_at: datetime) -> bool:
    """Persist one real Nord Pool frame without changing price semantics."""
    frame, points = build_nord_pool_frame(data, binding, captured_at)
    storage.ensure_global_source_generation(
        {
            "generation_id": frame["source_generation_id"],
            "logical_role": frame["logical_role"],
            "source_identity": {
                "identity_key": f"nord_pool|{binding['config_entry_id']}|{data.area}|{data.currency}",
                "identity_strength": "strong",
                "identity_provenance": "home_assistant_config_entry_and_area",
            },
            "source_resolution_kind": "native_bucket",
            "source_resolution_seconds": 900,
            "timezone_state": "verified",
        },
        captured_at,
    )
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
            frame["frame_id"] = "frame-" + hashlib.sha256(
                (
                    f"{frame['semantic_key']}|{frame['revision']}|" +
                    "|".join(point["point_key"] + f"={point['value']:.12g}" for point in points)
                ).encode()
            ).hexdigest()[:32]
    return storage.insert_external_frame(frame, points)


def _forecast_timezone(timezone_name: str | None) -> ZoneInfo:
    if not isinstance(timezone_name, str) or not timezone_name.strip():
        raise ValueError("forecast_solar_timezone_missing")
    try:
        return ZoneInfo(timezone_name)
    except Exception as err:
        raise ValueError("forecast_solar_timezone_invalid") from err


def _local_day_bounds(local_day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(local_day, time.min, tzinfo=zone)
    end = datetime.combine(local_day + timedelta(days=1), time.min, tzinfo=zone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _forecast_source_identity(site_id: str, binding: dict[str, Any], role: str, timezone_name: str) -> tuple[str, str]:
    identity = {
        "adapter": "forecast_solar",
        "adapter_version": FORECAST_SOLAR_ADAPTER_VERSION,
        "contract_version": FORECAST_SOLAR_CONTRACT_VERSION,
        "site_id": site_id,
        "role": role,
        "config_entry_id": binding.get("config_entry_id"),
        "binding_fingerprint": binding.get("binding_fingerprint"),
        "entities": binding.get("entities"),
        "timezone": timezone_name,
    }
    identity_key = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "fs-" + hashlib.sha256(identity_key.encode()).hexdigest()[:32], identity_key


def _forecast_target(
    role: str,
    local_day: date,
    observed_at: datetime,
    zone: ZoneInfo,
) -> tuple[str, datetime | None, datetime | None, datetime]:
    if role == "power_now_kw":
        return "instant:current", None, None, observed_at
    if role == "remaining_today_kwh":
        start, end = _local_day_bounds(local_day, zone)
        return f"local_day_remainder:{local_day.isoformat()}", observed_at, end, observed_at
    target_day = local_day + timedelta(days=_FORECAST_SOLAR_TARGET_DAY_OFFSETS.get(role, 0))
    start, end = _local_day_bounds(target_day, zone)
    return f"local_day:{target_day.isoformat()}", start, end, start


def _forecast_observed_at(state: Any) -> datetime | None:
    """Return the HA state timestamp that identifies the observed source fact."""
    observed_at = getattr(state, "last_updated", None)
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        return None
    return observed_at.astimezone(timezone.utc)


def _forecast_value_and_point(role: str, state: Any, observed_at: datetime, target_point: datetime) -> tuple[Any, str, dict[str, Any]] | None:
    value = normalize_forecast_value(state, role)
    if value is None:
        return None
    unit = _FORECAST_SOLAR_ROLE_UNITS[role]
    if role.startswith("peak_time"):
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        parsed_utc = parsed.astimezone(timezone.utc)
        return None, unit, {
            "source_timestamp": value,
            "predicted_peak_at": parsed_utc.isoformat(),
            "observed_at": observed_at.isoformat(),
        }
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return float(value), unit, {"observed_at": observed_at.isoformat(), "target_point": target_point.isoformat()}


def build_forecast_solar_frames(
    hass: Any,
    site_id: str,
    binding: dict[str, Any],
    captured_at: datetime,
) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Build immutable Forecast.Solar frames from one explicit site binding."""
    if not isinstance(site_id, str) or not site_id or not isinstance(binding, dict):
        raise ValueError("forecast_solar_binding_missing")
    captured_at = captured_at.astimezone(timezone.utc)
    timezone_name = getattr(getattr(hass, "config", None), "time_zone", None)
    zone = _forecast_timezone(timezone_name)
    local_day = captured_at.astimezone(zone).date()
    entities = binding.get("entities")
    if not isinstance(entities, dict):
        return []
    frames = []
    for role in sorted(SUPPORTED_FORECAST_SOLAR_ROLES):
        entity_id = entities.get(role)
        if not isinstance(entity_id, str) or not entity_id:
            continue
        state = hass.states.get(entity_id)
        observed_at = _forecast_observed_at(state)
        if observed_at is None:
            continue
        target, valid_from, valid_to, point_time = _forecast_target(
            role, local_day, observed_at, zone
        )
        normalized = _forecast_value_and_point(role, state, observed_at, point_time)
        if normalized is None:
            continue
        value, unit, point_payload = normalized
        generation_id, identity_key = _forecast_source_identity(site_id, binding, role, timezone_name)
        semantic_key = f"{FORECAST_SOLAR_DATASET}|site:{site_id}|generation:{generation_id}|role:{role}|target:{target}"
        point_key = target
        frame_seed = json.dumps({"semantic_key": semantic_key, "value": value, "unit": unit, "point": point_payload}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        frame_id = "frame-" + hashlib.sha256(frame_seed.encode()).hexdigest()[:32]
        frame = {
            "frame_id": frame_id,
            "schema_version": SCHEMA_VERSION,
            "dataset_version": DATASET_VERSION,
            "semantic_key": semantic_key,
            "revision": 1,
            "source_generation_id": generation_id,
            "source_scope": "site",
            "site_id": site_id,
            "logical_role": f"forecast_solar.{role}",
            "classification": "forecast",
            "published_at": None,
            "fetched_at": None,
            "known_at": captured_at,
            "captured_at": captured_at,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "quality_status": "good",
            "quality": {"status": "good", "source_role": role},
            "provenance": {
                "origin_type": "home_assistant_forecast_solar_entity",
                "provider": "forecast_solar",
                "config_entry_id": binding.get("config_entry_id"),
                "binding_fingerprint": binding.get("binding_fingerprint"),
                "entity_id": entity_id,
                "source_identity_key": identity_key,
                "site_id": site_id,
                "site_timezone": timezone_name,
                "target": target,
                "observed_at": observed_at.isoformat(),
            },
            "payload_schema": "forecast_solar.observed_fact.v1",
        }
        points = [{
            "point_id": f"{frame_id}-p001",
            "point_key": point_key,
            "valid_at": point_time,
            "value": value,
            "unit": unit,
            "quality_status": "good",
            "point": point_payload,
        }]
        frames.append((frame, points))
    return frames


def _points_with_stored_ids(storage: CanonicalStorage, frame_id: str, points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Align a recapture with stored point IDs without changing C.1 matching."""
    connection = storage.connection
    if connection is None:
        raise RuntimeError("canonical_storage_not_open")
    stored = connection.execute(
        "SELECT point_key, point_id FROM external_input_points WHERE frame_id = ?",
        (frame_id,),
    ).fetchall()
    stored_ids = {str(point_key): str(point_id) for point_key, point_id in stored}
    if len(stored_ids) != len(points) or {point["point_key"] for point in points} != set(stored_ids):
        return points
    return [dict(point, point_id=stored_ids[point["point_key"]]) for point in points]


def _points_with_revision_ids(frame_id: str, points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign deterministic storage IDs after a new final revision ID exists."""
    ordered = sorted(points, key=lambda point: point["point_key"])
    return [
        dict(point, point_id=f"{frame_id}-p{index:03d}")
        for index, point in enumerate(ordered, start=1)
    ]


def _point_content_for_revision_hash(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return deterministic point content without storage-only point IDs."""
    return [
        {key: value for key, value in point.items() if key != "point_id"}
        for point in sorted(points, key=lambda point: point["point_key"])
    ]


def persist_forecast_solar_frames(storage: CanonicalStorage, frames: list[tuple[dict[str, Any], list[dict[str, Any]]]], captured_at: datetime) -> dict[str, int]:
    """Persist one explicit site's Forecast.Solar frames with immutable revisions."""
    result = {"written": 0, "unchanged": 0, "revised": 0}
    for frame, points in frames:
        storage.ensure_source_generation(
            {
                "site_id": frame["site_id"],
                "logical_role": frame["logical_role"],
                "generation_id": frame["source_generation_id"],
                "source_identity": {
                    "identity_key": frame["provenance"]["source_identity_key"],
                    "identity_strength": "strong" if frame["provenance"].get("binding_fingerprint") else "medium",
                    "identity_provenance": "forecast_solar_binding_and_entity_mapping",
                },
            },
            captured_at,
        )
        latest = storage.latest_external_frame(frame["semantic_key"])
        if latest:
            frame["revision"] = latest[1]
            frame["frame_id"] = latest[0]
            frame["supersedes_frame_id"] = latest[2]
            comparable_points = _points_with_stored_ids(storage, frame["frame_id"], points)
            try:
                inserted = storage.insert_external_frame(frame, comparable_points)
            except ValueError as error:
                if str(error) != "canonical_frame_revision_conflict":
                    raise
                frame["revision"] = latest[1] + 1
                frame["supersedes_frame_id"] = latest[0]
                frame["frame_id"] = "frame-" + hashlib.sha256(
                    (
                        f"{frame['semantic_key']}|{frame['revision']}|"
                        + json.dumps(_point_content_for_revision_hash(comparable_points), sort_keys=True, default=str)
                    ).encode()
                ).hexdigest()[:32]
                comparable_points = _points_with_revision_ids(frame["frame_id"], comparable_points)
                inserted = storage.insert_external_frame(frame, comparable_points)
                result["revised"] += int(inserted)
            result["written"] += int(inserted)
            result["unchanged"] += int(not inserted)
        else:
            inserted = storage.insert_external_frame(frame, points)
            result["written"] += int(inserted)
    return result


def build_open_meteo_frame(
    target: dict[str, Any],
    normalized: dict[str, Any],
    fetched_at: datetime,
    captured_at: datetime | None = None,
    known_at: datetime | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build one immutable raw-GTI frame for one explicit request section."""
    points = normalized.get("points") if isinstance(normalized, dict) else None
    if not isinstance(points, list) or not points:
        raise ValueError("open_meteo_points_missing")
    fetched_at = fetched_at.astimezone(timezone.utc)
    captured_at = (captured_at or fetched_at).astimezone(timezone.utc)
    known_at = (known_at or captured_at).astimezone(timezone.utc)
    if fetched_at > known_at or captured_at > known_at:
        raise ValueError("open_meteo_timestamp_order_invalid")
    request_fingerprint = target["section_request_fingerprint"]
    generation_id = target["generation_id"]
    semantic_key = (
        f"{OPEN_METEO_DATASET}|{target['site_id']}|{generation_id}|"
        f"{OPEN_METEO_LOGICAL_ROLE}|{request_fingerprint}"
    )
    knowledge = {
        "semantic_key": semantic_key,
        "quality_status": normalized.get("quality_status", "good"),
        "quality": normalized.get("quality", {}),
        "points": [
            {
                "point_key": point["valid_at"].astimezone(timezone.utc).isoformat(),
                "source_timestamp": point.get("source_timestamp"),
                "value": point["value"],
                "unit": point["unit"],
                "quality_status": point.get("quality_status", "good"),
            }
            for point in points
        ],
    }
    knowledge_fingerprint = hashlib.sha256(json.dumps(knowledge, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()
    frame_seed = json.dumps(knowledge, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    frame_id = "frame-" + hashlib.sha256(frame_seed.encode("utf-8")).hexdigest()[:32]
    valid_at_values = [point["valid_at"].astimezone(timezone.utc) for point in points]
    frame = {
        "frame_id": frame_id,
        "schema_version": SCHEMA_VERSION,
        "dataset_version": DATASET_VERSION,
        "semantic_key": semantic_key,
        "revision": 1,
        "source_generation_id": generation_id,
        "source_scope": "site",
        "site_id": target["site_id"],
        "logical_role": OPEN_METEO_LOGICAL_ROLE,
        "classification": "forecast",
        "published_at": None,
        "fetched_at": fetched_at,
        "known_at": known_at,
        "captured_at": captured_at,
        "valid_from": min(valid_at_values),
        "valid_to": max(valid_at_values) + timedelta(hours=1),
        "quality_status": normalized.get("quality_status", "good"),
        "quality": dict(normalized.get("quality", {}), knowledge_fingerprint=knowledge_fingerprint),
        "provenance": {
            "origin_type": "open_meteo_http_response",
            "provider": "open-meteo",
            "endpoint": "https://api.open-meteo.com/v1/metno",
            "model": "metno",
            "site_id": target["site_id"],
            "timezone": target["timezone"],
            "latitude": target["latitude"],
            "longitude": target["longitude"],
            "tilt_deg": target["tilt_deg"],
            "open_meteo_azimuth_deg": target["open_meteo_azimuth_deg"],
            "section_request_fingerprint": request_fingerprint,
            "source_generation_id": generation_id,
            "source_timezone": normalized.get("api_metadata", {}).get("timezone", target["timezone"]),
            "raw_unit": "W/m²",
            "source_timestamp_semantics": "provider_local_or_offset_aware",
            "knowledge_fingerprint": knowledge_fingerprint,
        },
        "payload_schema": "open_meteo.global_tilted_irradiance.v1",
    }
    frame_points = [
        {
            "point_id": f"{frame_id}-p{index:03d}",
            "point_key": point["valid_at"].astimezone(timezone.utc).isoformat(),
            "valid_at": point["valid_at"].astimezone(timezone.utc),
            "value": point["value"],
            "unit": "W/m²",
            "quality_status": point.get("quality_status", "good"),
            "point": {"source_timestamp": point.get("source_timestamp")},
        }
        for index, point in enumerate(points, start=1)
    ]
    return frame, frame_points


def persist_open_meteo_frames(
    storage: CanonicalStorage,
    frames: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    captured_at: datetime,
) -> dict[str, int]:
    """Persist site-scoped Open-Meteo frames with immutable revisions."""
    result = {"written": 0, "unchanged": 0, "revised": 0, "frames": {}}
    for frame, points in frames:
        frame_result = {"written": 0, "unchanged": 0, "revised": 0}
        storage.ensure_source_generation(
            {
                "site_id": frame["site_id"],
                "logical_role": frame["logical_role"],
                "generation_id": frame["source_generation_id"],
                "source_identity": {
                    "identity_key": frame["provenance"]["section_request_fingerprint"],
                    "identity_strength": "strong",
                    "identity_provenance": "open_meteo_request_contract",
                },
                "source_resolution_kind": "native_bucket",
                "source_resolution_seconds": 3600,
                "timezone_state": "verified",
            },
            captured_at,
        )
        latest = storage.latest_external_frame(frame["semantic_key"])
        if latest:
            frame["revision"] = latest[1]
            frame["frame_id"] = latest[0]
            frame["supersedes_frame_id"] = latest[2]
            comparable = _points_with_stored_ids(storage, frame["frame_id"], points)
            try:
                inserted = storage.insert_external_frame(frame, comparable)
            except ValueError as error:
                if str(error) != "canonical_frame_revision_conflict":
                    raise
                frame["revision"] = latest[1] + 1
                frame["supersedes_frame_id"] = latest[0]
                frame["frame_id"] = "frame-" + hashlib.sha256(
                    (
                        f"{frame['semantic_key']}|{frame['revision']}|"
                        + json.dumps(_point_content_for_revision_hash(comparable), sort_keys=True, default=str)
                    ).encode("utf-8")
                ).hexdigest()[:32]
                comparable = _points_with_revision_ids(frame["frame_id"], comparable)
                inserted = storage.insert_external_frame(frame, comparable)
                result["revised"] += int(inserted)
                frame_result["revised"] += int(inserted)
        else:
            inserted = storage.insert_external_frame(frame, points)
        result["written"] += int(inserted)
        result["unchanged"] += int(not inserted)
        frame_result["written"] += int(inserted)
        frame_result["unchanged"] += int(not inserted)
        result["frames"][frame["semantic_key"]] = frame_result
    return result
