"""Read-only, site-scoped forecast power flows for the price chart."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, time, timedelta, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from .solar_single_run import select_for_decision


SCHEMA = "ella_power_forecast.v1"
BATTERY_SCHEMA = "battery_power_forecast.v1"
MODEL_VERSION = "battery-behavior-profile-v2"
MODEL_KIND = "autonomous_behavior_baseline"
MIN_BATTERY_SUPPORT = 3
MIN_COVERAGE = 0.9
RATIO_THRESHOLD_W = 100.0


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _finite(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _slot_key(value: datetime, zone: ZoneInfo) -> str:
    local = value.astimezone(zone)
    return f"{local.weekday()}:{local.hour * 4 + local.minute // 15}"


def _local_slots(day: date, zone: ZoneInfo) -> list[tuple[datetime, datetime]]:
    start = datetime.combine(day, time.min, tzinfo=zone).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone).astimezone(timezone.utc)
    slots = []
    cursor = start
    while cursor < end:
        next_cursor = min(cursor + timedelta(minutes=15), end)
        slots.append((cursor, next_cursor))
        cursor = next_cursor
    return slots


def _usable_row(row: dict[str, Any], site_id: str, known_at: datetime) -> bool:
    if row.get("site_id") != site_id:
        return False
    start = _datetime(row.get("interval_start"))
    end = _datetime(row.get("interval_end"))
    value = _finite(row.get("value"))
    coverage = _finite(row.get("coverage_ratio"))
    if not start or not end or end > known_at or value is None or value < -1e12:
        return False
    if str(row.get("unit", "")).upper() != "W" or coverage is None or coverage < MIN_COVERAGE:
        return False
    if row.get("quality_status") not in {"good", "partial"} or row.get("gap_status") in {"unavailable", "stale", "unknown"}:
        return False
    return end > start


def _usable_soc_row(row: dict[str, Any], site_id: str, known_at: datetime) -> bool:
    if row.get("site_id") != site_id:
        return False
    start = _datetime(row.get("interval_start"))
    end = _datetime(row.get("interval_end"))
    value = _finite(row.get("value"))
    coverage = _finite(row.get("coverage_ratio"))
    if not start or not end or end > known_at or value is None or not 0 <= value <= 100:
        return False
    if str(row.get("unit", "")).lower() not in {"%", "percent"} or coverage is None or coverage < MIN_COVERAGE:
        return False
    if row.get("quality_status") not in {"good", "partial"} or row.get("gap_status") in {"unavailable", "stale", "unknown"}:
        return False
    return end > start


def _band(value: float, bounds: tuple[float, ...], labels: tuple[str, ...]) -> str:
    for bound, label in zip(bounds, labels):
        if value <= bound:
            return label
    return labels[-1]


def _soc_band(value: float) -> str:
    return _band(value, (20.0, 40.0, 60.0, 80.0), ("0-20", "20-40", "40-60", "60-80", "80-100"))


def _net_load_band(value: float) -> str:
    return _band(value, (0.0, 500.0, 1000.0, 2000.0), ("<=0", "0-500", "500-1000", "1000-2000", ">2000"))


def _source_generation(site_id: str, role: str, rows: list[dict[str, Any]]) -> list[str]:
    return sorted({str(row.get("source_generation_id")) for row in rows if row.get("source_generation_id")})


def _derived_generation(site_id: str, binding: dict[str, Any] | None) -> str:
    identity = {"site_id": site_id, "source": "forecast_solar", "binding_fingerprint": (binding or {}).get("binding_fingerprint"), "entities": sorted(((binding or {}).get("entities") or {}).items())}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]
    return f"solar-derived-{digest}"


def _point(value_w: float, start: datetime, end: datetime, *, provenance: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "valid_at": start.isoformat(),
        "end_at": end.isoformat(),
        "value_w": float(value_w),
        "value_kw": float(value_w) / 1000.0,
        "unit": "W",
        "forecast": True,
        "classification": "forecast",
        "source": source,
        "provenance": provenance,
    }


def _battery_forecast(rows: list[dict[str, Any]], site_id: str, zone: ZoneInfo, slots: list[tuple[datetime, datetime]], load: dict[str, dict[str, Any]], solar: dict[str, dict[str, Any]], known_at: datetime, active_generation_ids: set[str] | None = None, *, use_ratio_projection: bool = False, learning_calibration: dict[str, Any] | None = None) -> dict[str, Any]:
    candidate_battery_rows = [row for row in rows if row.get("logical_role") == "battery.power" and _usable_row(row, site_id, known_at)]
    candidate_generations = {str(row.get("source_generation_id")) for row in candidate_battery_rows if row.get("source_generation_id")}
    if active_generation_ids is None and len(candidate_generations) > 1:
        return {"schema": BATTERY_SCHEMA, "site_id": site_id, "model_version": MODEL_VERSION, "model_kind": MODEL_KIND, "method": "robust_context_median", "known_at": known_at.isoformat(), "minimum_support": MIN_BATTERY_SUPPORT, "source_generation_ids": sorted(candidate_generations), "forecast_points": [], "available": False, "reason": "ambiguous_battery_source_generations", "execution_eligible": False, "actuator_writes_enabled": False}
    battery_rows = [row for row in candidate_battery_rows if active_generation_ids is None or str(row.get("source_generation_id")) in active_generation_ids]
    soc_rows = {row["interval_start"]: row for row in rows if row.get("logical_role") == "battery.soc" and _usable_soc_row(row, site_id, known_at)}
    load_rows = {row["interval_start"]: row for row in rows if row.get("logical_role") == "house.consumption" and _usable_row(row, site_id, known_at)}
    solar_rows: dict[str, list[dict[str, Any]]] = {}
    solar_generations = {
        str(row.get("source_generation_id")) for row in rows
        if row.get("logical_role") == "solar.production" and row.get("source_generation_id")
    }
    for row in rows:
        if row.get("logical_role") == "solar.production" and _usable_row(row, site_id, known_at):
            solar_rows.setdefault(row["interval_start"], []).append(row)

    by_quarter: dict[int, list[float]] = {}
    by_soc_net: dict[tuple[str, str], list[float]] = {}
    by_quarter_soc_net: dict[tuple[int, str, str], list[float]] = {}
    by_solar_context: dict[str, list[float]] = {"solar_surplus": [], "no_solar_surplus": []}
    by_discharge_ratio: dict[str, list[float]] = {}
    by_charge_ratio: dict[str, list[float]] = {}
    global_values: list[float] = []
    for row in battery_rows:
        start_value = row.get("interval_start")
        start = _datetime(start_value)
        if not start:
            continue
        local = start.astimezone(zone)
        quarter = local.hour * 4 + local.minute // 15
        value = float(row["value"])
        by_quarter.setdefault(quarter, []).append(value)
        global_values.append(value)
        soc = soc_rows.get(start_value)
        load_row = load_rows.get(start_value)
        solar_at_slot = solar_rows.get(start_value, [])
        solar_at_slot_generations = {str(item.get("source_generation_id")) for item in solar_at_slot if item.get("source_generation_id")}
        if not load_row or not solar_generations or solar_at_slot_generations != solar_generations:
            continue
        solar_value = sum(float(item["value"]) for item in solar_at_slot)
        net_load = float(load_row["value"]) - solar_value
        by_solar_context["solar_surplus" if net_load < 0 else "no_solar_surplus"].append(value)
        if use_ratio_projection and net_load > RATIO_THRESHOLD_W and value >= 0:
            ratio = min(2.0, max(0.0, value / net_load))
            by_discharge_ratio.setdefault(_net_load_band(net_load), []).append(ratio)
        elif use_ratio_projection and net_load < -RATIO_THRESHOLD_W and value <= 0:
            ratio = min(2.0, max(0.0, (-value) / (-net_load)))
            by_charge_ratio.setdefault(_net_load_band(net_load), []).append(ratio)
        if not soc:
            continue
        soc_key = _soc_band(float(soc["value"]))
        net_key = _net_load_band(net_load)
        by_soc_net.setdefault((soc_key, net_key), []).append(value)
        by_quarter_soc_net.setdefault((quarter, soc_key, net_key), []).append(value)

    current_soc = max((row for row in rows if row.get("logical_role") == "battery.soc" and _usable_soc_row(row, site_id, known_at)), key=lambda row: _datetime(row["interval_end"]) or datetime.min.replace(tzinfo=timezone.utc), default=None)
    current_soc_value = float(current_soc["value"]) if current_soc else None
    generations = _source_generation(site_id, "battery.power", battery_rows)
    points = []
    selected_support = []

    def select_values(start: datetime, load_point: dict[str, Any], solar_point: dict[str, Any]) -> tuple[str, list[float], dict[str, Any], str | None, float]:
        local = start.astimezone(zone)
        quarter = local.hour * 4 + local.minute // 15
        load_value = float(load_point["value_w"])
        solar_value = float(solar_point["value_w"])
        net_key = _net_load_band(load_value - solar_value)
        soc_key = _soc_band(current_soc_value) if current_soc_value is not None else None
        candidates = []
        net_load = load_value - solar_value
        near_zero = abs(net_load) < RATIO_THRESHOLD_W
        if use_ratio_projection and near_zero:
            if net_load < 0:
                candidates.append(("near_zero_charge_capture_ratio", by_charge_ratio.get("<=0", []), {"net_load_band": "<=0", "projection": "charge_capture_ratio", "near_zero": True}, "charge_ratio", net_load))
            elif net_load > 0:
                candidates.append(("near_zero_discharge_coverage_ratio", by_discharge_ratio.get("0-500", []), {"net_load_band": "0-500", "projection": "discharge_coverage_ratio", "near_zero": True}, "discharge_ratio", net_load))
        else:
            if use_ratio_projection and net_load > RATIO_THRESHOLD_W:
                candidates.append(("net_load_ratio", by_discharge_ratio.get(net_key, []), {"net_load_band": net_key, "projection": "discharge_coverage_ratio"}, "discharge_ratio", net_load))
            elif use_ratio_projection and net_load < -RATIO_THRESHOLD_W:
                candidates.append(("net_load_ratio", by_charge_ratio.get(net_key, []), {"net_load_band": net_key, "projection": "charge_capture_ratio"}, "charge_ratio", net_load))
            if soc_key is not None:
                candidates.append(("quarter_soc_net", by_quarter_soc_net.get((quarter, soc_key, net_key), []), {"quarter": quarter, "soc_band": soc_key, "net_load_band": net_key}, None, 0.0))
                candidates.append(("soc_net", by_soc_net.get((soc_key, net_key), []), {"soc_band": soc_key, "net_load_band": net_key}, None, 0.0))
            solar_context = "solar_surplus" if net_load < 0 else "no_solar_surplus"
            candidates.append(("solar_context", by_solar_context[solar_context], {"solar_context": solar_context, "net_load_band": net_key}, None, 0.0))
            candidates.append(("quarter", by_quarter.get(quarter, []), {"quarter": quarter}, None, 0.0))
            candidates.append(("global", global_values, {}, None, 0.0))
        for level, values, context, projection, projection_net_load in candidates:
            if len(values) >= MIN_BATTERY_SUPPORT:
                return level, values, context, projection, projection_net_load
        return "unavailable", [], {"net_load_band": net_key, "soc_band": soc_key}, None, 0.0

    for start, end in slots:
        if start < known_at:
            continue
        key = start.isoformat()
        load_point = load.get(key)
        solar_point = solar.get(key)
        if not load_point or not solar_point:
            continue
        level, values, context, projection, projection_net_load = select_values(start, load_point, solar_point)
        if not values:
            continue
        current_net_load = float(load_point["value_w"]) - float(solar_point["value_w"])
        selected_median = float(median(values))
        if projection == "discharge_ratio":
            value = selected_median * projection_net_load
        elif projection == "charge_ratio":
            value = -selected_median * (-projection_net_load)
        else:
            value = selected_median
        learning = (learning_calibration or {}).get("by_context", {}).get(level, {})
        learning_factor = float(learning.get("factor", 1.0)) if projection and isinstance(learning, dict) else 1.0
        if projection:
            learning_factor = min(1.2, max(0.8, learning_factor))
            value *= learning_factor
        selected_support.append(len(values))
        points.append(_point(value, start, end, source=BATTERY_SCHEMA, provenance={
            "schema": BATTERY_SCHEMA,
            "model_version": MODEL_VERSION,
            "model_kind": MODEL_KIND,
            "method": "robust_context_median",
            "projection": projection,
            "median_ratio": selected_median if projection else None,
            "ratio_threshold_w": RATIO_THRESHOLD_W,
            "near_zero": abs(current_net_load) < RATIO_THRESHOLD_W,
            "learning_factor": learning_factor,
            "learning_support_count": learning.get("support_count", 0) if isinstance(learning, dict) else 0,
            "learning_model_version": learning.get("model_version") if isinstance(learning, dict) else None,
            "learning_prior_mae_w": learning.get("prior_mae_w") if isinstance(learning, dict) else None,
            "learning_prior_bias_w": learning.get("prior_bias_w") if isinstance(learning, dict) else None,
            "context_level": level,
            "context": context,
            "site_id": site_id,
            "sample_count": len(values),
            "support_minimum": MIN_BATTERY_SUPPORT,
            "history_window": "canonical_settled_actuals_before_known_at",
            "known_at": known_at.isoformat(),
            "current_soc_percent": current_soc_value,
            "source_generation_ids": generations,
            "raw_behavior_sign_convention": "positive_discharge_negative_charge",
            "confidence": "supported" if len(values) >= 5 else "limited_support",
        }))
    return {
        "schema": BATTERY_SCHEMA,
        "site_id": site_id,
        "model_version": MODEL_VERSION,
        "model_kind": MODEL_KIND,
        "method": "robust_context_median",
        "context_fallback_order": ["quarter_soc_net", "soc_net", "solar_context", "quarter", "global"],
        "known_at": known_at.isoformat(),
        "minimum_support": MIN_BATTERY_SUPPORT,
        "history_window": "canonical_settled_actuals_before_known_at",
        "source_generation_ids": generations,
        "current_soc_percent": current_soc_value,
        "support_count_min": min(selected_support) if selected_support else 0,
        "support_count_max": max(selected_support) if selected_support else 0,
        "confidence": "supported" if points and min(selected_support) >= 5 else ("limited_support" if points else "insufficient_support"),
        "forecast_points": points,
        "available": bool(points),
        "execution_eligible": False,
        "actuator_writes_enabled": False,
    }


def _single_run_solar_forecast(site_id: str, zone: ZoneInfo, slots: list[tuple[datetime, datetime]], known_at: datetime, target_date: date, frames: list[dict[str, Any]], targets: list[dict[str, Any]]) -> dict[str, Any]:
    scoped_targets = [target for target in targets if target.get("site_id") == site_id]
    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for target in scoped_targets:
        status, frame = select_for_decision(
            frames,
            site_id=site_id,
            target_date=target_date,
            timezone_name=target.get("timezone") or zone.key,
            source_generation_id=str(target.get("generation_id") or ""),
            decision_at=known_at,
        )
        if status != "VERIFIED_PRE_DECISION" or frame is None:
            return {"schema": "solar.slot_forecast.v1", "site_id": site_id, "known_at": known_at.isoformat(), "available": False, "reason": "open_meteo_section_unavailable", "forecast_points": [], "execution_eligible": False, "actuator_writes_enabled": False}
        selected.append((target, frame))
    if not selected:
        return {"schema": "solar.slot_forecast.v1", "site_id": site_id, "known_at": known_at.isoformat(), "available": False, "reason": "open_meteo_targets_unavailable", "forecast_points": [], "execution_eligible": False, "actuator_writes_enabled": False}
    by_target_hour: list[dict[datetime, dict[str, Any]]] = []
    for _target, frame in selected:
        by_target_hour.append({item["valid_at"] if isinstance(item.get("valid_at"), datetime) else _datetime(item.get("valid_at")): item for item in frame.get("points", []) if _datetime(item.get("valid_at")) is not None})
    points = []
    for slot_start, slot_end in slots:
        hour = slot_start.replace(minute=0, second=0, microsecond=0)
        if any(hour not in mapping for mapping in by_target_hour):
            continue
        section_values = [float(mapping[hour]["value"]) for mapping in by_target_hour]
        if any(not math.isfinite(value) or value < 0 for value in section_values):
            continue
        watts = sum((value / 1000.0) * float(target["peak_power_kwp"]) * 1000.0 for value, (target, _frame) in zip(section_values, selected))
        frame_ids = [str(frame.get("frame_id")) for _target, frame in selected]
        generation_ids = [str(target.get("generation_id")) for target, _frame in selected]
        points.append(_point(watts, slot_start, slot_end, source="solar.slot_forecast.v1", provenance={
            "schema": "solar.slot_forecast.v1",
            "method": "open_meteo_hourly_gti_to_four_equal_15m_average_power",
            "site_id": site_id,
            "target_date": target_date.isoformat(),
            "frame_ids": frame_ids,
            "source_generation_ids": generation_ids,
            "section_peak_power_kwp": [float(target["peak_power_kwp"]) for target, _frame in selected],
            "known_at": known_at.isoformat(),
            "run_initialization_at": [frame.get("provenance", {}).get("run_initialization_at") for _target, frame in selected],
            "confidence": "complete_section_hour",
        }))
    return {"schema": "solar.slot_forecast.v1", "site_id": site_id, "known_at": known_at.isoformat(), "target_date": target_date.isoformat(), "method": "open_meteo_hourly_gti_to_four_equal_15m_average_power", "available": bool(points), "forecast_points": points, "execution_eligible": False, "actuator_writes_enabled": False}


def _solar_forecast(site_id: str, zone: ZoneInfo, facts: dict[str, Any], binding: dict[str, Any] | None, slots: list[tuple[datetime, datetime]], known_at: datetime, *, target_date: date, open_meteo_frames: list[dict[str, Any]] | None = None, open_meteo_targets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if target_date != known_at.astimezone(zone).date() and open_meteo_frames and open_meteo_targets:
        return _single_run_solar_forecast(site_id, zone, slots, known_at, target_date, open_meteo_frames, open_meteo_targets)
    local = known_at.astimezone(zone)
    hourly = []
    entities = (binding or {}).get("entities", {}) if isinstance(binding, dict) else {}
    for role, start in (("this_hour_kwh", local.replace(minute=0, second=0, microsecond=0)), ("next_hour_kwh", (local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)))):
        value = _finite(facts.get(role))
        if value is None or value < 0:
            continue
        hourly.append((role, start, value, entities.get(role)))
    points = []
    generation_id = _derived_generation(site_id, binding)
    for role, local_start, energy_kwh, entity_id in hourly:
        start_utc = local_start.astimezone(timezone.utc)
        end_utc = (local_start + timedelta(hours=1)).astimezone(timezone.utc)
        average_w = energy_kwh * 1000.0
        for slot_start, slot_end in slots:
            if slot_start < max(known_at, start_utc) or slot_start >= end_utc:
                continue
            points.append(_point(average_w, slot_start, slot_end, source="solar.slot_forecast.v1", provenance={
                "schema": "solar.slot_forecast.v1",
                "method": "hour_energy_as_four_equal_15m_average_power",
                "source": "forecast_solar",
                "source_role": role,
                "source_entity": entity_id,
                "site_id": site_id,
                "known_at": known_at.isoformat(),
                "valid_hour_start": start_utc.isoformat(),
                "valid_hour_end": end_utc.isoformat(),
                "binding_fingerprint": (binding or {}).get("binding_fingerprint"),
                "source_generation_id": generation_id,
                "confidence": "source_hour_average",
            }))
    points.sort(key=lambda item: item["valid_at"])
    return {"schema": "solar.slot_forecast.v1", "site_id": site_id, "known_at": known_at.isoformat(), "method": "hour_energy_as_four_equal_15m_average_power", "available": bool(points), "forecast_points": points, "execution_eligible": False, "actuator_writes_enabled": False}


def _load_points(load_forecast: dict[str, Any], site_id: str, known_at: datetime, *, horizon_start: datetime, horizon_end: datetime) -> dict[str, dict[str, Any]]:
    candidates = [frame for frame in (load_forecast or {}).get("frames", []) if isinstance(frame, dict) and frame.get("site_id") == site_id and frame.get("payload_schema") == "load_forecast.v1" and (_datetime(frame.get("known_at")) or datetime.min.replace(tzinfo=timezone.utc)) <= known_at]
    if not candidates:
        return {}
    frame = sorted(candidates, key=lambda item: (_datetime(item.get("known_at")) or datetime.min.replace(tzinfo=timezone.utc), int(item.get("revision") or 0), str(item.get("frame_id") or "")))[-1]
    result = {}
    for raw in frame.get("points", []):
        start = _datetime(raw.get("valid_at"))
        value = _finite(raw.get("value"))
        if start and value is not None and raw.get("unit") == "W" and start >= max(known_at, horizon_start) and start < horizon_end:
            result[start.isoformat()] = _point(value, start, start + timedelta(minutes=15), source="load_forecast.v1", provenance={"frame_id": frame.get("frame_id"), "revision": frame.get("revision"), "model_version": (frame.get("quality") or {}).get("model_version"), "known_at": frame.get("known_at"), "site_id": site_id})
    return result


def build_power_forecast(site_id: str, timezone_name: str, rows: list[dict[str, Any]], load_forecast: dict[str, Any], solar_facts: dict[str, Any], solar_binding: dict[str, Any] | None, known_at: datetime, active_battery_generation_ids: set[str] | None = None, *, target_date: date | None = None, open_meteo_frames: list[dict[str, Any]] | None = None, open_meteo_targets: list[dict[str, Any]] | None = None, learning_calibration: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build read-only forecast flows without changing execution or policy gates."""
    zone = ZoneInfo(timezone_name)
    local_day = target_date or known_at.astimezone(zone).date()
    slots = _local_slots(local_day, zone)
    solar = _solar_forecast(site_id, zone, solar_facts, solar_binding, slots, known_at, target_date=local_day, open_meteo_frames=open_meteo_frames, open_meteo_targets=open_meteo_targets)
    load = _load_points(load_forecast, site_id, known_at, horizon_start=slots[0][0], horizon_end=slots[-1][1])
    solar_by_slot = {point["valid_at"]: point for point in solar["forecast_points"]}
    battery = _battery_forecast(
        rows, site_id, zone, slots, load, solar_by_slot, known_at,
        active_battery_generation_ids,
        use_ratio_projection=local_day != known_at.astimezone(zone).date(),
        learning_calibration=learning_calibration,
    )
    series = {
        "solar": solar,
        "consumption": {"schema": "load_forecast.v1", "site_id": site_id, "available": bool(load), "forecast_points": list(load.values()), "execution_eligible": False, "actuator_writes_enabled": False},
        "charging": {"schema": BATTERY_SCHEMA, "site_id": site_id, "available": battery["available"], "forecast_points": [_point(max(0.0, -float(point["value_w"])), _datetime(point["valid_at"]), _datetime(point["end_at"]), source=BATTERY_SCHEMA, provenance={**point["provenance"], "split": "negative_signed_power_to_charge", "display_sign_convention": "positive_charge_magnitude"}) for point in battery["forecast_points"]], "execution_eligible": False, "actuator_writes_enabled": False},
        "discharging": {"schema": BATTERY_SCHEMA, "site_id": site_id, "available": battery["available"], "forecast_points": [_point(max(0.0, float(point["value_w"])), _datetime(point["valid_at"]), _datetime(point["end_at"]), source=BATTERY_SCHEMA, provenance={**point["provenance"], "split": "positive_signed_power_to_discharge", "display_sign_convention": "positive_discharge_magnitude"}) for point in battery["forecast_points"]], "execution_eligible": False, "actuator_writes_enabled": False},
        "import": {"schema": "grid_power_forecast.v1", "site_id": site_id, "available": False, "forecast_points": [], "execution_eligible": False, "actuator_writes_enabled": False},
        "export": {"schema": "grid_power_forecast.v1", "site_id": site_id, "available": False, "forecast_points": [], "execution_eligible": False, "actuator_writes_enabled": False},
    }
    battery_by_slot = {point["valid_at"]: point for point in battery["forecast_points"]}
    grid_import, grid_export = [], []
    for start, end in slots:
        key = start.isoformat()
        if key not in load or key not in solar_by_slot or key not in battery_by_slot:
            continue
        balance_w = float(load[key]["value_w"]) - float(solar_by_slot[key]["value_w"]) - float(battery_by_slot[key]["value_w"])
        provenance = {"schema": "grid_power_forecast.v1", "method": "load_minus_solar_minus_signed_battery_behavior", "model_kind": MODEL_KIND, "site_id": site_id, "known_at": known_at.isoformat(), "load": load[key]["provenance"], "solar": solar_by_slot[key]["provenance"], "battery": battery_by_slot[key]["provenance"], "battery_sign_convention": "positive_discharge_negative_charge", "sign_convention": "positive_import_negative_export"}
        grid_import.append(_point(max(0.0, balance_w), start, end, source="grid_power_forecast.v1", provenance=provenance))
        grid_export.append(_point(max(0.0, -balance_w), start, end, source="grid_power_forecast.v1", provenance=provenance))
    series["import"].update({"available": bool(grid_import), "forecast_points": grid_import})
    series["export"].update({"available": bool(grid_export), "forecast_points": grid_export})
    return {"schema": SCHEMA, "site_id": site_id, "timezone": timezone_name, "known_at": known_at.isoformat(), "horizon": {"date": local_day.isoformat(), "start": slots[0][0].isoformat(), "end": slots[-1][1].isoformat()}, "battery": battery, "series": series, "available": any(item.get("available") for item in series.values()), "execution_eligible": False, "actuator_writes_enabled": False}
