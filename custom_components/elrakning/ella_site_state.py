"""Deterministic, site-scoped ELLA decision state for Stage 2."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import math
from zoneinfo import ZoneInfo
from typing import Any, Iterable

from .price_only_planner import select_load_slot_points

SCHEMA = "ella_site_state.v1"
INTERVAL_SECONDS = 900


def resolve_timezone(site_timezone: str | None, installation_timezone: str | None) -> tuple[str, str]:
    """Resolve an explicit site timezone or the configured HA installation timezone."""
    for candidate, source in ((site_timezone, "site_location"), (installation_timezone, "home_assistant_config_default")):
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        try:
            ZoneInfo(candidate)
        except (KeyError, TypeError, ValueError):
            continue
        return candidate, source
    raise ValueError("site_timezone_unavailable")


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value is not None else None


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def local_day_slots(target_date: date, timezone_name: str) -> list[tuple[datetime, datetime]]:
    """Return UTC quarter-hour slots for a local calendar day, including DST days."""
    zone = ZoneInfo(timezone_name)
    start = datetime.combine(target_date, time.min, tzinfo=zone).astimezone(timezone.utc)
    end = datetime.combine(target_date + timedelta(days=1), time.min, tzinfo=zone).astimezone(timezone.utc)
    slots = []
    cursor = start
    while cursor < end:
        next_cursor = cursor + timedelta(seconds=INTERVAL_SECONDS)
        slots.append((cursor, min(next_cursor, end)))
        cursor = next_cursor
    return slots


def _coverage(value: dict[str, Any] | None) -> dict[str, Any]:
    return value if value is not None else {"availability": "unavailable", "reason": "no_verified_observation"}


def _source_point(point: dict[str, Any], source: str) -> dict[str, Any]:
    result = {
        "availability": "available",
        "source": source,
        "value": point.get("value"),
        "unit": point.get("unit") or "W",
        "observed_at": _iso(point.get("observed_at")) if isinstance(point.get("observed_at"), datetime) else point.get("observed_at"),
        "valid_at": _iso(point.get("valid_at")) if isinstance(point.get("valid_at"), datetime) else point.get("valid_at"),
        "source_generation_id": point.get("source_generation_id"),
        "frame_id": point.get("frame_id"),
    }
    if point.get("quality"):
        result["quality"] = point["quality"]
    return result


def _slot_for_row(row: dict[str, Any], start: datetime, end: datetime) -> dict[str, Any] | None:
    if row.get("interval_start") != start or row.get("interval_end") != end:
        return None
    value = _number(row.get("value"))
    if value is None or row.get("quality_status") not in {"good", "partial"}:
        return None
    return {
        "value": value,
        "unit": row.get("unit"),
        "source_generation_id": row.get("source_generation_id"),
        "quality": {"status": row.get("quality_status"), "coverage_ratio": row.get("coverage_ratio")},
        "observed_at": row.get("interval_end"),
    }


def _canonical_resources(rows: Iterable[dict[str, Any]], role: str, site_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("logical_role") != role or row.get("site_id") not in {None, site_id}:
            continue
        resource = str(row.get("source_generation_id") or "unknown")
        point = _slot_for_row(row, start, end)
        if point is not None:
            grouped.setdefault(resource, []).append({**point, "resource_id": row.get("resource_id")})
    return [
        {"source_generation_id": resource, "points": sorted(points, key=lambda item: item.get("observed_at") or "")}
        for resource, points in sorted(grouped.items())
    ]


def _actual_load(rows: Iterable[dict[str, Any]], site_id: str, start: datetime, end: datetime, decision_at: datetime) -> dict[str, Any] | None:
    for row in rows:
        if row.get("site_id") not in {None, site_id}:
            continue
        if row.get("logical_role") != "house.consumption" or row.get("unit") != "W":
            continue
        if row.get("interval_end") > decision_at:
            continue
        point = _slot_for_row(row, start, end)
        if point is not None:
            return {**point, "source": "actual", "valid_at": start}
    return None


def _forecast_load(frames: Iterable[dict[str, Any]], start: datetime, end: datetime, decision_at: datetime, site_id: str) -> dict[str, Any] | None:
    for frame in frames:
        if frame.get("site_id") != site_id or frame.get("payload_schema") != "load_forecast.v1":
            continue
        known_at = frame.get("known_at")
        if isinstance(known_at, str):
            try:
                known_at = datetime.fromisoformat(known_at)
            except ValueError:
                continue
        if not isinstance(known_at, datetime) or known_at > decision_at:
            continue
        valid_from = frame.get("valid_from")
        valid_to = frame.get("valid_to")
        if isinstance(valid_from, str):
            valid_from = datetime.fromisoformat(valid_from)
        if isinstance(valid_to, str):
            valid_to = datetime.fromisoformat(valid_to)
        if valid_from and start < valid_from or valid_to and end > valid_to:
            continue
        for point in frame.get("points") or []:
            valid_at = point.get("valid_at")
            if isinstance(valid_at, str):
                valid_at = datetime.fromisoformat(valid_at)
            value = _number(point.get("value"))
            if valid_at == start and value is not None and point.get("unit") == "W" and point.get("quality_status") == "good":
                return {"source": "forecast", "value": value, "unit": "W", "valid_at": start,
                        "frame_id": frame.get("frame_id"), "source_generation_id": frame.get("source_generation_id"),
                        "quality": frame.get("quality") or {}, "forecast": point.get("point") or {}}
    return None


def _price_slot(periods: Iterable[Any], start: datetime, end: datetime, source_id: str | None) -> dict[str, Any] | None:
    for period in periods:
        p_start, p_end = getattr(period, "start", None), getattr(period, "end", None)
        price = _number(getattr(period, "price", None))
        if p_start and p_end and price is not None and p_start <= start and p_end >= end:
            return {"availability": "available", "value": price, "unit": "SEK/kWh", "source": "nord_pool.price_periods.v1", "source_generation_id": source_id, "valid_from": _iso(p_start), "valid_to": _iso(p_end)}
    return None


def build_site_state(
    site_id: str,
    timezone_name: str,
    target_date: date,
    decision_at: datetime,
    *,
    periods: Iterable[Any] = (),
    price_source_generation_id: str | None = None,
    actual_rows: Iterable[dict[str, Any]] = (),
    load_frames: Iterable[dict[str, Any]] = (),
    model_points: Iterable[dict[str, Any]] = (),
    capability_snapshot: dict[str, Any] | None = None,
    individual_loads: Iterable[dict[str, Any]] = (),
    solar_forecast_frames: Iterable[dict[str, Any]] = (),
    economic_frames: Iterable[dict[str, Any]] = (),
    forecast_evaluation: dict[str, Any] | None = None,
    stage6: dict[str, Any] | None = None,
    ess_digital_twin: dict[str, Any] | None = None,
    timezone_source: str = "site_location",
) -> dict[str, Any]:
    """Build a read-only state snapshot from already verified facts."""
    slots = []
    rows = list(actual_rows)
    frames = list(load_frames)
    model = list(model_points)
    for start, end in local_day_slots(target_date, timezone_name):
        load = _actual_load(rows, site_id, start, end, decision_at)
        if load is None:
            load = _forecast_load(frames, start, end, decision_at, site_id)
        if load is None:
            points = select_load_slot_points(start, end, frames, site_id, decision_at, actual_rows=rows, model_points=model)
            load = points[0] if points and points[0] else None
        if load is None:
            load = {"availability": "unavailable", "reason": "no_verified_actual_forecast_or_model"}
        elif load.get("source") == "model":
            # Historical profile values are watts by contract; normalize the
            # unit here as the state boundary before net-load arithmetic.
            load = {**load, "availability": "available", "unit": load.get("unit") or "W"}
        else:
            load = {**load, "availability": "available"}
        solar_resources = _canonical_resources(rows, "solar.production", site_id, start, end)
        expected_solar = {
            item.get("generation_id") or item.get("source_generation_id")
            for item in (((capability_snapshot or {}).get("capabilities") or []))
            if isinstance(item, dict) and item.get("capability_id") == "solar.actual"
            for item in ((item.get("source") or {}).get("resources") or [])
            if isinstance(item, dict)
        }
        present_solar = {item.get("source_generation_id") for item in solar_resources}
        solar_complete = bool(solar_resources) and (not expected_solar or expected_solar <= present_solar)
        solar = (
            {"availability": "available", "resources": solar_resources, "source": "canonical", "aggregate": {"availability": "available", "value_w": sum(point.get("value", 0) for item in solar_resources for point in item.get("points", [])), "source_generation_ids": sorted(present_solar)}}
            if solar_complete else
            {"availability": "partial" if solar_resources else "unavailable", "reason": "incomplete_resource_coverage" if solar_resources else "canonical_role_missing", "resources": solar_resources}
        )
        ess = {}
        for role in ("battery.power", "battery.soc", "battery.capacity"):
            resources = _canonical_resources(rows, role, site_id, start, end)
            ess[role] = {"availability": "available", "resources": resources} if resources else {"availability": "unavailable", "reason": "canonical_role_missing"}
        price = _price_slot(periods, start, end, price_source_generation_id)
        net_load = {"availability": "unavailable", "reason": "load_or_solar_unavailable"}
        if load.get("availability") == "available" and solar.get("aggregate", {}).get("availability") == "available":
            load_value = _number(load.get("value"))
            solar_value = _number(solar["aggregate"].get("value_w"))
            if load_value is not None and solar_value is not None and load.get("unit") == "W":
                net_load = {
                    "availability": "available", "value_w": load_value - solar_value,
                    "source": "load_minus_solar", "sign_convention": "positive_import_need_negative_surplus",
                    "load_source": load.get("source"), "load_source_generation_id": load.get("source_generation_id"),
                    "solar_source_generation_ids": solar["aggregate"].get("source_generation_ids", []),
                }
        slots.append({
            "start": _iso(start), "end": _iso(end),
            "price": price or {"availability": "unavailable", "reason": "verified_price_period_missing"},
            "load": load,
            "solar": solar,
            "ess": ess,
            "net_load": net_load,
            "cost_stack": {"availability": "available" if price else "unavailable", "completeness": "partial" if price else "unavailable", "components": ([price] if price else [])},
        })
    horizon_start = slots[0]["start"] if slots else None
    horizon_end = slots[-1]["end"] if slots else None
    source_candidates = []
    for frame in solar_forecast_frames:
        if frame.get("site_id") == site_id and frame.get("payload_schema") == "forecast_solar.observed_fact.v1":
            valid_from = _iso(frame.get("valid_from"))
            valid_to = _iso(frame.get("valid_to"))
            overlaps = (valid_from is None and valid_to is None) or (valid_to is not None and valid_from is not None and valid_from < horizon_end and valid_to > horizon_start)
            if overlaps:
                source_candidates.append(frame)
    latest_facts = {}
    for frame in source_candidates:
        key = (frame.get("logical_role"), frame.get("semantic_key") or frame.get("point_key") or "current")
        previous = latest_facts.get(key)
        rank = (_iso(frame.get("known_at")) or "", int(frame.get("revision") or 0), frame.get("frame_id") or "")
        previous_rank = ((_iso(previous.get("known_at")) or "", int(previous.get("revision") or 0), previous.get("frame_id") or "") if previous else ())
        if previous is None or rank > previous_rank:
            latest_facts[key] = frame
    source_facts = [
        {"frame_id": frame.get("frame_id"), "logical_role": frame.get("logical_role"), "valid_from": _iso(frame.get("valid_from")), "valid_to": _iso(frame.get("valid_to")), "known_at": _iso(frame.get("known_at")), "provenance": frame.get("provenance") or {}}
        for frame in latest_facts.values()
    ]
    economic_facts = []
    for frame in economic_frames:
        if frame.get("site_id") != site_id or frame.get("payload_schema") != "eon.grid_economic_active_snapshot.v1":
            continue
        economic_facts.append({
            "frame_id": frame.get("frame_id"),
            "logical_role": frame.get("logical_role"),
            "source_generation_id": frame.get("source_generation_id"),
            "known_at": _iso(frame.get("known_at")),
            "valid_from": _iso(frame.get("valid_from")),
            "valid_to": _iso(frame.get("valid_to")),
            "applicability": "unknown_unresolved_utc_boundaries",
            "provenance": frame.get("provenance") or {},
        })
    state = {
        "schema": SCHEMA, "site_id": site_id, "timezone": timezone_name, "timezone_source": timezone_source,
        "known_at": _iso(decision_at), "interval_seconds": INTERVAL_SECONDS,
        "horizon": {"start": slots[0]["start"] if slots else None, "end": slots[-1]["end"] if slots else None, "date": target_date.isoformat()},
        "capabilities": capability_snapshot or {},
        "forecast_evaluation": forecast_evaluation or {
            "available": False, "reason": "no_evaluation_history", "records": [],
        },
        "stage6": stage6 or {
            "schema": "ella_stage6_state.v1", "site_id": site_id,
            "solar": {"calibration": {"available": False, "reason": "stage6_not_loaded"}},
            "ess": {"action_eligibility": {}},
            "execution_eligible": False, "actuator_writes_enabled": False,
        },
        "ess_digital_twin": ess_digital_twin or {
            "schema": "ella_ess_digital_twin.v1", "site_id": site_id,
            "available": False, "reason": "ess_twin_not_loaded",
            "execution_eligible": False, "actuator_writes_enabled": False,
        },
        "source_facts": sorted(source_facts, key=lambda item: (item.get("logical_role") or "", item.get("frame_id") or "")),
        "economic_facts": sorted(economic_facts, key=lambda item: (item.get("logical_role") or "", item.get("frame_id") or "")),
        "slots": slots,
        "individual_loads": sorted(list(individual_loads), key=lambda item: item.get("load_id", "")),
        "execution_eligible": False,
        "actuator_writes_enabled": False,
    }
    state["state_id"] = "ella-state-" + sha256(_json(state).encode()).hexdigest()[:32]
    return state
