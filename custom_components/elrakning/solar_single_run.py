"""Causal Open-Meteo Single Run capture for Solar model provenance."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .solar_open_meteo import (
    _number,
    _resolve_timestamp_sequence,
    _valid_timezone,
    build_open_meteo_targets,
)


DATASET = "open_meteo.single_run_day_ahead_pv.v1"
LOGICAL_ROLE = "solar.irradiance.day_ahead_pv_forecast"
ENDPOINT = "https://single-runs-api.open-meteo.com/v1/forecast"
MODEL = "metno_seamless"
TRANSFORMATION_VERSION = "gti_to_pv_kwh.v1"
NORMALIZATION_VERSION = "open_meteo_single_run_hourly.v1"


def decision_at_for_target(target_date: date, timezone_name: str) -> datetime:
    zone = ZoneInfo(timezone_name)
    return datetime.combine(target_date, datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)


def target_day_bounds(target_date: date, timezone_name: str) -> tuple[datetime, datetime]:
    return decision_at_for_target(target_date, timezone_name), decision_at_for_target(target_date + timedelta(days=1), timezone_name)


def source_generation_id(target: dict[str, Any]) -> str:
    identity = {
        "provider": "open-meteo", "dataset": DATASET, "model": MODEL,
        "adapter_version": 1, "normalization_version": NORMALIZATION_VERSION,
        "transformation_version": TRANSFORMATION_VERSION,
        "site_id": target["site_id"], "timezone": target["timezone"],
        "latitude": target["latitude"], "longitude": target["longitude"],
        "tilt_deg": target["tilt_deg"],
        "open_meteo_azimuth_deg": target["open_meteo_azimuth_deg"],
        "peak_power_kwp": target["peak_power_kwp"],
        "variable": "global_tilted_irradiance",
    }
    return "om-sr-" + hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]


def build_single_run_targets(site_configs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    targets = []
    for manager_target in build_open_meteo_targets(site_configs):
        target = deepcopy(manager_target)
        target.update({
            "dataset": DATASET, "logical_role": LOGICAL_ROLE, "endpoint": ENDPOINT,
            "model": MODEL, "normalization_version": NORMALIZATION_VERSION,
            "transformation_version": TRANSFORMATION_VERSION,
            "allow_capture_after_knowledge": True,
        })
        target["generation_id"] = source_generation_id(target)
        target["single_run_request_fingerprint"] = hashlib.sha256(json.dumps({
            key: target[key] for key in (
                "dataset", "endpoint", "model", "site_id", "timezone", "latitude",
                "longitude", "tilt_deg", "open_meteo_azimuth_deg", "peak_power_kwp",
                "normalization_version", "transformation_version",
            )
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]
        targets.append(target)
    return targets


def candidate_run_times(now: datetime, decision_at: datetime, limit: int = 8) -> list[datetime]:
    current = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [candidate for offset in range(limit)
            if (candidate := current - timedelta(hours=offset)) < decision_at]


def build_single_run_request(target: dict[str, Any], run_initialization_at: datetime) -> dict[str, str]:
    return {
        "latitude": str(target["latitude"]), "longitude": str(target["longitude"]),
        "run": run_initialization_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M"),
        "models": MODEL, "hourly": "global_tilted_irradiance",
        "tilt": str(target["tilt_deg"]), "azimuth": str(target["open_meteo_azimuth_deg"]),
        "timezone": target["timezone"], "forecast_days": "3",
    }


def normalize_single_run_payload(payload: dict[str, Any], target: dict[str, Any], target_date: date, run_initialization_at: datetime) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or payload.get("model") not in {None, MODEL, "metno"}:
        return None
    expected_timezone = _valid_timezone(target.get("timezone"))
    provider_timezone = _valid_timezone(payload.get("timezone"))
    if not expected_timezone or not provider_timezone or provider_timezone != expected_timezone:
        return None
    timezone_name = expected_timezone
    start, end = target_day_bounds(target_date, timezone_name)
    hourly = payload.get("hourly")
    times = hourly.get("time") if isinstance(hourly, dict) else None
    values = hourly.get("global_tilted_irradiance") if isinstance(hourly, dict) else None
    hourly_units = payload.get("hourly_units")
    if (
        not isinstance(times, list)
        or not isinstance(values, list)
        or len(times) != len(values)
        or not isinstance(hourly_units, dict)
        or hourly_units.get("global_tilted_irradiance") != "W/m²"
    ):
        return None
    resolved, gaps = _resolve_timestamp_sequence(times, timezone_name)
    selected = []
    for timestamp, value, valid_at in zip(times, values, resolved):
        number = _number(value)
        if valid_at is None or number is None or not start <= valid_at < end:
            continue
        selected.append({"source_timestamp": timestamp, "valid_at": valid_at, "value": number, "unit": "W/m²", "quality_status": "good"})
    expected_hours = int((end - start).total_seconds() // 3600)
    selected.sort(key=lambda item: item["valid_at"])
    valid_times = [item["valid_at"] for item in selected]
    complete = (
        len(selected) == expected_hours and len(set(valid_times)) == expected_hours
        and all(right - left == timedelta(hours=1) for left, right in zip(valid_times, valid_times[1:]))
        and not any(gap.get("reason") in {"ambiguous_timestamp", "nonexistent_timestamp", "nonmonotonic_timestamp_sequence"} for gap in gaps)
    )
    if not complete:
        return None
    derived_kwh = sum(item["value"] for item in selected) / 1000.0 * float(target["peak_power_kwp"])
    return {
        "points": selected, "quality_status": "good",
        "quality": {"status": "good", "target_hours": expected_hours, "gaps": gaps},
        "source_valid_from": start, "source_valid_to": end,
        "target_date": target_date.isoformat(),
        "run_initialization_at": run_initialization_at.astimezone(timezone.utc).isoformat(),
        "derived_target_day_pv_kwh": derived_kwh,
        "api_metadata": {key: payload[key] for key in ("model", "timezone", "utc_offset_seconds", "generationtime_ms") if payload.get(key) is not None},
    }


async def async_fetch_single_run_target(hass, target: dict[str, Any], target_date: date, run_initialization_at: datetime) -> tuple[dict[str, Any], datetime]:
    session = async_get_clientsession(hass)
    async with session.get(ENDPOINT, params=build_single_run_request(target, run_initialization_at), timeout=30) as response:
        if response.status != 200:
            raise ValueError(f"http_{response.status}")
        payload = await response.json()
    received_at = dt_util.now().astimezone(timezone.utc)
    normalized = normalize_single_run_payload(payload, target, target_date, run_initialization_at)
    if normalized is None:
        raise ValueError("incomplete_or_invalid_target_day")
    return {**normalized, "provider_model": payload.get("model", MODEL)}, received_at


def select_for_decision(
    frames: list[dict[str, Any]],
    *,
    site_id: str,
    target_date: date,
    timezone_name: str,
    source_generation_id: str,
    decision_at: datetime | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Classify and select Single Run frames using the locked contract."""
    decision = decision_at or decision_at_for_target(target_date, timezone_name)
    target_start, target_end = target_day_bounds(target_date, timezone_name)
    scoped = []
    for frame in frames:
        provenance = frame.get("provenance") if isinstance(frame, dict) else None
        provenance = provenance if isinstance(provenance, dict) else {}
        frame_target_date = frame.get("target_date", provenance.get("target_date"))
        target_matches = frame_target_date == target_date.isoformat()
        if frame_target_date is None:
            target_matches = (
                frame.get("valid_from") == target_start
                and frame.get("valid_to") == target_end
            )
        if (
            frame.get("site_id") != site_id
            or frame.get("source_generation_id") != source_generation_id
            or frame.get("payload_schema") != DATASET
            or not target_matches
            or frame.get("logical_role") != LOGICAL_ROLE
        ):
            continue
        valid_from = frame.get("valid_from")
        valid_to = frame.get("valid_to")
        if valid_from is not None and valid_from != target_start:
            continue
        if valid_to is not None and valid_to != target_end:
            continue
        scoped.append((frame, provenance))
    if not scoped:
        return "MISSING", None

    candidates = []
    insufficient = False
    for frame, provenance in scoped:
        known_at = frame.get("known_at")
        raw_run = provenance.get("run_initialization_at")
        raw_received = provenance.get("provider_response_received_at")
        fingerprint = provenance.get("knowledge_fingerprint")
        try:
            if not isinstance(known_at, datetime):
                raise ValueError("known_at")
            if not isinstance(raw_run, str):
                raise ValueError("run_initialization_at")
            if provenance.get("provider") != "open-meteo":
                raise ValueError("provider")
            if provenance.get("model") not in {MODEL, "metno"}:
                raise ValueError("model")
            if frame.get("valid_from") != target_start or frame.get("valid_to") != target_end:
                raise ValueError("target_interval")
            run_at = datetime.fromisoformat(raw_run.replace("Z", "+00:00")).astimezone(timezone.utc)
            received_at = datetime.fromisoformat(str(raw_received).replace("Z", "+00:00")).astimezone(timezone.utc)
            if not isinstance(fingerprint, str) or not fingerprint:
                raise ValueError("knowledge_fingerprint")
            if known_at.astimezone(timezone.utc) < received_at:
                raise ValueError("known_at_before_response")
        except (TypeError, ValueError):
            insufficient = True
            continue
        try:
            known_at = known_at.astimezone(timezone.utc)
        except (AttributeError, ValueError):
            insufficient = True
            continue
        candidates.append((known_at, run_at, fingerprint, frame))
    if insufficient:
        return "INSUFFICIENT_PROVENANCE", None
    if not candidates:
        return "INSUFFICIENT_PROVENANCE", None
    pre = [item for item in candidates if item[0] <= decision]
    if not pre:
        return "VERIFIED_POST_DECISION", None

    boundary = max((known, run_at) for known, run_at, _fingerprint, _frame in pre)
    boundary_items = [item for item in pre if item[0:2] == boundary]
    if len({item[2] for item in boundary_items}) > 1:
        return "AMBIGUOUS", None
    selected = max(boundary_items, key=lambda item: item[2])
    return "VERIFIED_PRE_DECISION", selected[3]
