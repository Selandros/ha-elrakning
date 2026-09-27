"""Deterministic, causal monthly cost forecast primitives.

This module only evaluates already-qualified forecast slots. It never creates
energy, prices, weather, or battery behavior that is not present in inputs.
"""

from __future__ import annotations

import hashlib
import json
import math
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


SCHEMA = "ella_monthly_cost_forecast.v1"
MODEL_VERSION = "causal-slotwise-cost-v1"
SLOT_SECONDS = 900


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _moment(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def month_window(target_month: str, timezone_name: str) -> tuple[datetime, datetime] | None:
    try:
        year, month = (int(item) for item in target_month.split("-", 1))
        zone = ZoneInfo(timezone_name)
        start = datetime.combine(date(year, month, 1), time.min, zone)
        next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
        return start.astimezone(timezone.utc), datetime.combine(next_month, time.min, zone).astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        return None


def _next_slot_boundary(value: datetime) -> datetime:
    """Start future replay at the next canonical 15-minute boundary."""
    value = value.astimezone(timezone.utc)
    epoch = int(value.timestamp())
    boundary = ((epoch + SLOT_SECONDS - 1) // SLOT_SECONDS) * SLOT_SECONDS
    return datetime.fromtimestamp(boundary, timezone.utc)


def _price_at(periods: list[dict[str, Any]], moment: datetime) -> tuple[float | None, dict[str, Any] | None]:
    matches = []
    for period in periods:
        start = _moment(period.get("start"))
        end = _moment(period.get("end"))
        price = _number(
            period.get("total_ore_per_kwh_gross", period.get("total_customer_price_ore_per_kwh"))
        )
        if price is None:
            trade = _number(period.get("trade_customer_price_ore_per_kwh"))
            grid = _number(period.get("grid_variable_ore_per_kwh"))
            if trade is not None and grid is not None:
                price = trade + grid
        if start and end and start <= moment < end and price is not None and price >= 0:
            matches.append((start, end, price, period))
    if not matches:
        return None, None
    matches.sort(key=lambda item: (item[0], item[1], json.dumps(item[3], sort_keys=True, default=str)))
    first = matches[0]
    if any(item[0] != first[0] or item[1] != first[1] or item[2] != first[2] for item in matches[1:]):
        return None, None
    return first[2], first[3]


def _causal_price_fallback(
    periods: list[dict[str, Any]], decision: datetime,
) -> tuple[float | None, dict[str, Any] | None]:
    """Reuse the latest complete price basis known at decision time."""
    candidates = []
    for period in periods or []:
        start = _moment(period.get("start"))
        end = _moment(period.get("end"))
        if not start or not end or end <= start or start > decision:
            continue
        price = _number(
            period.get("total_ore_per_kwh_gross", period.get("total_customer_price_ore_per_kwh"))
        )
        if price is None:
            trade = _number(period.get("trade_customer_price_ore_per_kwh"))
            grid = _number(period.get("grid_variable_ore_per_kwh"))
            price = trade + grid if trade is not None and grid is not None else None
        if price is not None and price >= 0:
            candidates.append((start, end, price, period))
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: (item[0], item[1], json.dumps(item[3], sort_keys=True, default=str)))
    start, end, price, source = candidates[-1]
    return price, {
        **source,
        "method": "causal_recent_known_price_fallback",
        "fallback_known_at": decision.isoformat(),
        "fallback_basis_start": start.isoformat(),
        "fallback_basis_end": end.isoformat(),
    }


def _causal_trade_price_profile(
    periods: list[dict[str, Any]], moment: datetime, decision: datetime,
) -> tuple[float | None, dict[str, Any] | None]:
    """Build a bounded trade/spot profile from observed periods only."""
    candidates = []
    for period in periods or []:
        start = _moment(period.get("start"))
        end = _moment(period.get("end"))
        known_at = _moment(period.get("price_known_at"))
        trade = _number(period.get("trade_customer_price_ore_per_kwh"))
        spot = _number(period.get("spot_price_ore_per_kwh"))
        value = trade if trade is not None else spot
        basis = "trade_customer_gross" if trade is not None else "nord_pool_spot"
        if (
            not start or not end or end <= start or end > decision
            or (known_at and known_at > decision) or value is None or value < 0
        ):
            continue
        candidates.append((start, end, value, basis, period))
    if not candidates:
        return None, None
    slot_key = moment.hour * 4 + moment.minute // 15
    exact = [item for item in candidates if item[0].weekday() == moment.weekday() and item[0].hour * 4 + item[0].minute // 15 == slot_key]
    broader = [item for item in candidates if item[0].weekday() == moment.weekday() and item[0].hour == moment.hour]
    daypart = [item for item in candidates if item[0].weekday() == moment.weekday() and item[0].hour // 6 == moment.hour // 6]
    area_recent = candidates
    selected = exact or broader
    fallback_level = "exact_slot" if exact else "weekday_hour" if broader else None
    if not selected and len(daypart) >= 2:
        selected = daypart
        fallback_level = "weekday_daypart"
    if not selected and len(area_recent) >= 4:
        selected = area_recent
        fallback_level = "area_recent"
    if not selected:
        return None, None
    available_bases = {item[3] for item in selected}
    basis = "trade_customer_gross" if "trade_customer_gross" in available_bases else "nord_pool_spot"
    selected = [item for item in selected if item[3] == basis]
    selected = sorted(selected, key=lambda item: (item[0], item[1], json.dumps(item[3], sort_keys=True, default=str)))[-28:]
    latest = selected[-1][4]
    basis_label = "trade_customer_gross_ex_grid" if basis == "trade_customer_gross" else "nord_pool_spot_ex_grid"
    method_prefix = "trade" if basis == "trade_customer_gross" else "spot"
    method_name = {
        "exact_slot": f"causal_weekday_slot_{method_prefix}_price_profile",
        "weekday_hour": f"causal_weekday_hour_{method_prefix}_price_profile",
        "weekday_daypart": f"causal_weekday_daypart_{method_prefix}_price_profile",
        "area_recent": f"causal_area_recent_{method_prefix}_price_profile",
    }[fallback_level]
    return sum(item[2] for item in selected) / len(selected), {
        "method": method_name,
        "basis": basis_label,
        "fallback_level": fallback_level,
        "sample_support": len(selected),
        "historical_window_start": selected[0][0].isoformat(),
        "historical_window_end": selected[-1][1].isoformat(),
        "known_at": decision.isoformat(),
        "source_generation_id": latest.get("price_source_generation_id"),
        "area": latest.get("price_area"),
        "currency": latest.get("price_currency"),
        "fallback_reason": "provider_horizon_exhausted",
    }


def canonical_spot_price_periods(
    frames: list[dict[str, Any]], *, area: str | None, currency: str | None,
) -> list[dict[str, Any]]:
    """Flatten decision-time-visible canonical Nord Pool frames into spot periods."""
    periods = []
    for frame in frames or []:
        provenance = frame.get("provenance") or {}
        frame_area = provenance.get("area") or frame.get("area")
        frame_currency = provenance.get("currency") or frame.get("currency")
        if area and frame_area != area:
            continue
        if currency and frame_currency != currency:
            continue
        for point in frame.get("points") or []:
            start = _moment(point.get("valid_at"))
            content = point.get("point") or {}
            end = _moment(content.get("end"))
            value = _number(point.get("value"))
            known_at = _moment(frame.get("known_at"))
            if not start or not end or end <= start or value is None or value < 0 or not known_at:
                continue
            periods.append({
                "start": start.isoformat(),
                "end": end.isoformat(),
                "spot_price_ore_per_kwh": value * 100.0,
                "price_known_at": known_at.isoformat(),
                "price_source_generation_id": frame.get("source_generation_id"),
                "price_area": frame_area,
                "price_currency": frame_currency,
                "price_provenance": {
                    "method": "canonical_nord_pool_spot_history",
                    "source_generation_id": frame.get("source_generation_id"),
                    "frame_id": frame.get("frame_id"),
                    "area": frame_area,
                    "currency": frame_currency,
                    "known_at": known_at.isoformat(),
                },
            })
    return sorted(periods, key=lambda item: (item["start"], item["end"], item.get("price_source_generation_id") or ""))


def _integrated_import(points: list[dict[str, Any]], start: datetime, end: datetime) -> float:
    normalized = []
    for point in points or []:
        timestamp = _moment(point.get("timestamp"))
        value = _number(point.get("import_kw"))
        if timestamp and value is not None and value >= 0:
            normalized.append((timestamp, value))
    normalized.sort()
    total = 0.0
    for (left_time, left_value), (right_time, right_value) in zip(normalized, normalized[1:]):
        if right_time - left_time > timedelta(minutes=30):
            continue
        overlap_start = max(start, left_time)
        overlap_end = min(end, right_time)
        if overlap_end <= overlap_start:
            continue
        duration = (right_time - left_time).total_seconds()
        if duration <= 0:
            continue
        def value_at(moment: datetime) -> float:
            return left_value + (right_value - left_value) * ((moment - left_time).total_seconds() / duration)
        total += (value_at(overlap_start) + value_at(overlap_end)) / 2 * ((overlap_end - overlap_start).total_seconds() / 3600)
    return total


def build_actual_priced_cost_to_date(
    *,
    points: list[dict[str, Any]],
    price_periods: list[dict[str, Any]],
    month_start: datetime,
    now: datetime,
    trade_fixed_fee_sek: float | None = None,
    grid_fixed_fee_sek: float | None = None,
) -> dict[str, Any]:
    """Build backend billing facts using the frontend's strict coverage rules."""
    actual_import = _integrated_import(points, month_start, now)
    trade = 0.0
    grid = 0.0
    priced_import = 0.0
    covered_until = month_start
    for period in price_periods or []:
        start = _moment(period.get("start"))
        end = _moment(period.get("end"))
        trade_ore = _number(period.get("trade_customer_price_ore_per_kwh"))
        grid_ore = _number(period.get("grid_variable_ore_per_kwh"))
        if not start or not end or end <= month_start or start >= now or trade_ore is None or grid_ore is None:
            continue
        segment_start = max(month_start, start)
        segment_end = min(now, end)
        segment_import = _integrated_import(points, segment_start, segment_end)
        if segment_import <= 0:
            continue
        expected_next = min(now, max(covered_until, segment_start))
        if segment_start <= expected_next + timedelta(milliseconds=1) and segment_end > covered_until:
            covered_until = segment_end
        trade += segment_import * trade_ore / 100
        grid += segment_import * grid_ore / 100
        priced_import += segment_import
    elapsed = max(0.0, min(1.0, (now - month_start).total_seconds() / max(1.0, (now.replace(day=28) + timedelta(days=4)).replace(day=1).timestamp() - month_start.timestamp())))
    trade_fixed = _number(trade_fixed_fee_sek)
    grid_fixed = _number(grid_fixed_fee_sek)
    fixed = (trade_fixed or 0.0) * elapsed + (grid_fixed or 0.0) * elapsed
    missing_past = max(0.0, actual_import - priced_import)
    return {
        "actual_import_to_date_kwh": actual_import,
        "priced_import_to_date_kwh": priced_import,
        "missing_past_import_kwh": missing_past,
        "trade_variable_cost_sek": trade,
        "grid_variable_cost_sek": grid,
        "fixed_cost_to_date_sek": fixed,
        "actual_cost_to_date_sek": trade + grid + fixed,
        "price_coverage_complete": missing_past <= 1e-9,
        "provenance": {"method": "canonical_trapezoidal_import_with_complete_price_coverage", "missingPast_excluded_from_future": True},
    }


def build_month_end_slots(
    *,
    decision_at: datetime,
    month_end: datetime,
    near_term_points: list[dict[str, Any]],
    historical_rows: list[dict[str, Any]],
    timezone_name: str,
    known_price_periods: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fill month-end slots from causal forecast points, then bounded actual profile."""
    decision = _moment(decision_at)
    end = _moment(month_end)
    if decision is None or end is None or end <= decision:
        return {"available": False, "reason": "month_window_invalid", "slots": []}
    zone = ZoneInfo(timezone_name)
    by_slot = {}
    for point in near_term_points or []:
        valid = _moment(point.get("valid_at"))
        value = _number(point.get("import_kw", point.get("value_w")))
        known = _moment(point.get("known_at") or (point.get("provenance") or {}).get("known_at"))
        if valid and value is not None and value >= 0 and valid >= decision and valid < end and known and known <= decision:
            by_slot[valid] = {"valid_at": valid, "end_at": min(end, valid + timedelta(seconds=SLOT_SECONDS)), "import_kw": value, "known_at": known, "provenance": point.get("provenance") or {}, "method": "canonical_power_forecast"}
    profile = {}
    for row in historical_rows or []:
        start = row.get("interval_start")
        value = _number(row.get("value"))
        if not isinstance(start, datetime) or value is None or value < 0 or row.get("logical_role") not in {"grid.power/import", "house.consumption"}:
            continue
        local = start.astimezone(zone)
        profile.setdefault((local.weekday(), local.hour * 4 + local.minute // 15), []).append(value)
    fallback = {key: sum(values) / len(values) for key, values in profile.items() if values}
    slots = []
    cursor = _next_slot_boundary(decision)
    while cursor < end:
        point = by_slot.get(cursor)
        if point is None:
            local = cursor.astimezone(zone)
            value = fallback.get((local.weekday(), local.hour * 4 + local.minute // 15))
            if value is not None:
                point = {"valid_at": cursor, "end_at": min(end, cursor + timedelta(seconds=SLOT_SECONDS)), "import_kw": value / 1000.0, "known_at": decision, "method": "causal_weekday_slot_profile", "provenance": {"method": "historical_actual_profile", "sample_count": len(profile.get((local.weekday(), local.hour * 4 + local.minute // 15), [])), "weather_corrected": False}}
        if point is not None:
            price, source = _price_at(known_price_periods, cursor)
            price_method = "causal_known_price"
            energy_price = None
            energy_source = None
            if price is None:
                price, source = _causal_price_fallback(known_price_periods, decision)
                if price is not None:
                    price_method = "causal_recent_known_price_fallback"
                else:
                    energy_price, energy_source = _causal_trade_price_profile(known_price_periods, cursor, decision)
                    price_method = energy_source.get("method") if energy_source else "price_missing"
            point = {
                **point,
                "price_ore_per_kwh_gross": price,
                "price_provenance": source or {"method": price_method},
                "price_method": price_method,
                "energy_price_ore_per_kwh_gross": energy_price,
                "energy_price_provenance": energy_source or {},
            }
            slots.append(point)
        cursor += timedelta(seconds=SLOT_SECONDS)
    expected = int((end - decision).total_seconds() / SLOT_SECONDS)
    method_counts = {}
    price_method_counts = {}
    for item in slots:
        method = item.get("method", "unknown")
        price_method = item.get("price_method", "unknown")
        method_counts[method] = method_counts.get(method, 0) + 1
        price_method_counts[price_method] = price_method_counts.get(price_method, 0) + 1
    price_complete = all(item.get("price_ore_per_kwh_gross") is not None for item in slots)
    return {
        "available": len(slots) == expected and price_complete,
        "slots": slots,
        "slot_count": len(slots),
        "expected_slot_count": expected,
        "fallback_slot_count": sum(item.get("method") != "canonical_power_forecast" for item in slots),
        "method_counts": method_counts,
        "price_method_counts": price_method_counts,
        "energy_price_method_counts": {
            method: sum(1 for slot in slots if slot.get("energy_price_provenance", {}).get("method") == method)
            for method in sorted({slot.get("energy_price_provenance", {}).get("method") for slot in slots if slot.get("energy_price_provenance", {}).get("method")})
        },
        "price_missing_slot_count": sum(item.get("price_ore_per_kwh_gross") is None for item in slots),
        "weather_corrected_slot_count": 0,
        "weather_support_count": 0,
        "reason": None if len(slots) == expected and price_complete else "month_end_slot_support_missing",
    }


def build_monthly_cost_forecast(
    *,
    site_id: str,
    timezone_name: str,
    decision_at: datetime,
    target_month: str,
    actual_cost_to_date_sek: float | None,
    actual_import_to_date_kwh: float | None,
    future_points: list[dict[str, Any]],
    price_periods: list[dict[str, Any]],
    remaining_fixed_cost_sek: float = 0.0,
    source_generations: list[str] | None = None,
    calibration: dict[str, Any] | None = None,
    weather: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculate a month estimate from causal future grid-import slots only."""
    decision = _moment(decision_at)
    window = month_window(target_month, timezone_name)
    actual_cost = _number(actual_cost_to_date_sek)
    actual_import = _number(actual_import_to_date_kwh)
    if not site_id or decision is None or window is None:
        return _unavailable(site_id, target_month, "input_missing")
    if actual_cost is None or actual_cost < 0 or actual_import is None or actual_import < 0:
        return _unavailable(site_id, target_month, "actual_to_date_missing")
    start, end = window
    points: dict[datetime, dict[str, Any]] = {}
    for raw in future_points:
        valid_at = _moment(raw.get("valid_at"))
        point_end = _moment(raw.get("end_at")) or (valid_at + timedelta(seconds=SLOT_SECONDS) if valid_at else None)
        known_at = _moment(raw.get("known_at") or (raw.get("provenance") or {}).get("known_at"))
        import_kw = _number(raw.get("import_kw", raw.get("value_w")))
        if not valid_at or not point_end or valid_at < decision or point_end > end or valid_at >= end:
            continue
        if known_at is None or known_at > decision or import_kw is None or import_kw < 0:
            continue
        if point_end <= valid_at:
            continue
        candidate = {
            "valid_at": valid_at,
            "end_at": point_end,
            "import_kw": import_kw,
            "known_at": known_at,
            "method": raw.get("method", "canonical_power_forecast"),
            "provenance": raw.get("provenance") or {},
            "price_ore_per_kwh_gross": _number(raw.get("price_ore_per_kwh_gross")),
            "price_provenance": raw.get("price_provenance") or {},
            "price_method": raw.get("price_method", "unknown"),
            "energy_price_ore_per_kwh_gross": _number(raw.get("energy_price_ore_per_kwh_gross")),
            "energy_price_provenance": raw.get("energy_price_provenance") or {},
        }
        previous = points.get(valid_at)
        if previous is not None and json.dumps(previous, sort_keys=True, default=str) != json.dumps(candidate, sort_keys=True, default=str):
            return _unavailable(site_id, target_month, "ambiguous_forecast_slot")
        points[valid_at] = candidate
    ordered = [points[key] for key in sorted(points)]
    expected_future_cost = 0.0
    expected_future_import = 0.0
    days: dict[str, dict[str, float]] = {}
    missing = []
    missing_reasons: dict[str, int] = {}
    first_missing: dict[str, str] = {}
    method_counts: dict[str, int] = {}
    price_method_counts: dict[str, int] = {}
    energy_price_method_counts: dict[str, int] = {}
    grid_tariff_missing_count = 0
    cursor = _next_slot_boundary(decision)
    while cursor < end:
        point = points.get(cursor)
        if point is None:
            missing.append(cursor.isoformat())
            missing_reasons["forecast_slot_missing"] = missing_reasons.get("forecast_slot_missing", 0) + 1
            first_missing.setdefault("forecast_slot_missing", cursor.isoformat())
            cursor += timedelta(seconds=SLOT_SECONDS)
            continue
        method = point.get("method", "unknown")
        method_counts[method] = method_counts.get(method, 0) + 1
        duration_hours = (point["end_at"] - point["valid_at"]).total_seconds() / 3600
        price_ore, price_source = _price_at(price_periods, point["valid_at"])
        if price_ore is None:
            price_ore = _number(point.get("price_ore_per_kwh_gross"))
            price_source = point.get("price_provenance") if price_ore is not None else None
        if price_ore is None:
            energy_price = _number(point.get("energy_price_ore_per_kwh_gross"))
            energy_source = point.get("energy_price_provenance") or {}
            if energy_price is not None:
                method = str(energy_source.get("method") or "energy_price_available")
                energy_price_method_counts[method] = energy_price_method_counts.get(method, 0) + 1
                grid_tariff_missing_count += 1
                missing_reasons["grid_tariff_missing"] = missing_reasons.get("grid_tariff_missing", 0) + 1
                first_missing.setdefault("grid_tariff_missing", cursor.isoformat())
            else:
                missing_reasons["price_missing"] = missing_reasons.get("price_missing", 0) + 1
                first_missing.setdefault("price_missing", cursor.isoformat())
            missing.append(cursor.isoformat())
            cursor += timedelta(seconds=SLOT_SECONDS)
            continue
        price_method = point.get("price_method") or "causal_point_price"
        price_method_counts[price_method] = price_method_counts.get(price_method, 0) + 1
        energy = point["import_kw"] * duration_hours
        cost = energy * price_ore / 100
        expected_future_import += energy
        expected_future_cost += cost
        local_day = point["valid_at"].astimezone(ZoneInfo(timezone_name)).date().isoformat()
        day = days.setdefault(local_day, {"import_kwh": 0.0, "cost_sek": 0.0, "slot_count": 0})
        day["import_kwh"] += energy
        day["cost_sek"] += cost
        day["slot_count"] += 1
        cursor = point["end_at"]
    quality = "qualified" if not missing else "unavailable"
    reasons = []
    if missing_reasons.get("grid_tariff_missing"):
        reasons.append("grid_tariff_missing")
    if missing_reasons.get("price_missing") or missing_reasons.get("forecast_slot_missing"):
        reasons.append("causal_future_slot_or_price_missing")
    remaining_fixed = _number(remaining_fixed_cost_sek)
    if remaining_fixed is None or remaining_fixed < 0:
        return _unavailable(site_id, target_month, "remaining_fixed_cost_missing")
    expected_future_cost += remaining_fixed if quality == "qualified" else 0.0
    estimate = actual_cost + expected_future_cost if quality == "qualified" else None
    total_import = actual_import + expected_future_import if quality == "qualified" else None
    identity = {
        "schema": SCHEMA,
        "model_version": MODEL_VERSION,
        "site_id": site_id,
        "decision_at": decision.isoformat(),
        "target_month": target_month,
        "source_generations": sorted({str(item) for item in (source_generations or []) if item}),
        "calibration": calibration or {},
        "weather": weather or {},
        "points": [{
            "valid_at": item["valid_at"].isoformat(),
            "end_at": item["end_at"].isoformat(),
            "import_kw": item["import_kw"],
            "method": item.get("method"),
            "price_ore_per_kwh_gross": item.get("price_ore_per_kwh_gross"),
            "price_method": item.get("price_method"),
            "provenance": item["provenance"],
            "price_provenance": item.get("price_provenance") or {},
            "energy_price_ore_per_kwh_gross": item.get("energy_price_ore_per_kwh_gross"),
            "energy_price_provenance": item.get("energy_price_provenance") or {},
        } for item in ordered],
        "prices": price_periods,
    }
    return {
        "schema": SCHEMA,
        "model_version": MODEL_VERSION,
        "site_id": site_id,
        "timezone": timezone_name,
        "decision_at": decision.isoformat(),
        "known_at": decision.isoformat(),
        "target_month": target_month,
        "actual_cost_to_date_sek": actual_cost,
        "expected_future_cost_sek": expected_future_cost if quality == "qualified" else None,
        "estimated_month_total_sek": estimate,
        "actual_import_to_date_kwh": actual_import,
        "expected_future_import_kwh": expected_future_import if quality == "qualified" else None,
        "estimated_month_import_kwh": total_import,
        "per_day": days,
        "slot_count": len(ordered),
        "quality": quality,
        "available": quality == "qualified",
        "reasons": reasons,
        "missing_slot_count": len(missing),
        "missing_reasons": missing_reasons,
        "first_missing_slot_by_reason": first_missing,
        "slot_method_counts": method_counts,
        "price_method_counts": price_method_counts,
        "energy_price_method_counts": energy_price_method_counts,
        "grid_tariff_missing_count": grid_tariff_missing_count,
        "source_generations": identity["source_generations"],
        "calibration": calibration or {},
        "weather": weather or {},
        "forecast_fallback": "none" if quality == "qualified" else "legacy_explicit_fallback_required",
        "execution_eligible": False,
        "actuator_writes_enabled": False,
        "fingerprint": _fingerprint(identity),
    }


def _unavailable(site_id: str, target_month: str, reason: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA, "model_version": MODEL_VERSION, "site_id": site_id,
        "target_month": target_month, "available": False, "quality": "unavailable",
        "reasons": [reason], "execution_eligible": False,
        "actuator_writes_enabled": False, "fingerprint": _fingerprint({"site_id": site_id, "target_month": target_month, "reason": reason}),
    }
