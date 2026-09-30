"""Canonical invoice-derived values shared with the frontend."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def build_today_variable_cost(
    points: list[dict[str, Any]] | None,
    periods: list[dict[str, Any]] | None,
    now: datetime,
) -> dict[str, float] | None:
    """Calculate today's observed import cost from canonical power and price periods."""
    if now.tzinfo is None:
        return None
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    normalized_points = sorted(
        (
            (timestamp, import_kw)
            for point in points or []
            if (timestamp := _timestamp(point.get("timestamp"))) is not None
            and (import_kw := _number(point.get("import_kw"))) is not None
        ),
        key=lambda point: point[0],
    )
    if len(normalized_points) < 2:
        return None
    trade_total = 0.0
    grid_total = 0.0
    imported_total = 0.0
    included = 0
    for period in periods or []:
        if period.get("forecast") is True:
            continue
        start = _timestamp(period.get("start"))
        end = _timestamp(period.get("end"))
        trade_ore = _number(period.get("trade_customer_price_ore_per_kwh"))
        grid_ore = _number(period.get("grid_variable_ore_per_kwh"))
        if not start or not end or end <= day_start or start >= now or trade_ore is None or grid_ore is None:
            continue
        limit = min(end, now)
        observed_start = max(start, day_start)
        covered_until = observed_start
        imported_kwh = 0.0
        for left, right in zip(normalized_points, normalized_points[1:]):
            left_time, left_kw = left
            right_time, right_kw = right
            if right_time - left_time > timedelta(minutes=30):
                continue
            overlap_start = max(observed_start, left_time)
            overlap_end = min(limit, right_time)
            if overlap_end <= overlap_start:
                continue
            duration = (right_time - left_time).total_seconds()
            if duration <= 0:
                continue
            def value_at(timestamp: datetime) -> float:
                return left_kw + (right_kw - left_kw) * ((timestamp - left_time).total_seconds() / duration)
            imported_kwh += (value_at(overlap_start) + value_at(overlap_end)) / 2 * ((overlap_end - overlap_start).total_seconds() / 3600)
            if overlap_start <= covered_until + timedelta(milliseconds=1) and overlap_end > covered_until:
                covered_until = overlap_end
        if covered_until < limit - timedelta(milliseconds=1):
            continue
        trade_total += imported_kwh * trade_ore / 100
        grid_total += imported_kwh * grid_ore / 100
        imported_total += imported_kwh
        included += 1
    if not included:
        return None
    return {
        "variable_cost_sek": trade_total + grid_total,
        "trade_cost_sek": trade_total,
        "grid_cost_sek": grid_total,
        "imported_kwh": imported_total,
    }


def build_daily_actual_cost(
    points: list[dict[str, Any]] | None,
    periods: list[dict[str, Any]] | None,
    day_start: datetime,
    day_end: datetime,
    observed_end: datetime | None = None,
) -> dict[str, Any] | None:
    """Build one actual day without inventing values across uncovered gaps."""
    if day_start.tzinfo is None or day_end.tzinfo is None or day_end <= day_start:
        return None
    limit = min(day_end, observed_end) if observed_end is not None else day_end
    if limit <= day_start:
        return None
    normalized_points = sorted(
        (
            (_timestamp(point.get("timestamp")), _number(point.get("import_kw")))
            for point in points or []
        ),
        key=lambda item: item[0] or datetime.min.replace(tzinfo=day_start.tzinfo),
    )
    normalized_points = [(timestamp, value) for timestamp, value in normalized_points if timestamp is not None and value is not None]
    if len(normalized_points) < 2:
        return None
    trade_total = 0.0
    grid_total = 0.0
    imported_total = 0.0
    covered_until = day_start
    priced_until = day_start
    price_samples = []
    for period in periods or []:
        start = _timestamp(period.get("start"))
        end = _timestamp(period.get("end"))
        trade_ore = _number(period.get("trade_customer_price_ore_per_kwh"))
        grid_ore = _number(period.get("grid_variable_ore_per_kwh"))
        if not start or not end or end <= day_start or start >= limit or trade_ore is None or grid_ore is None:
            continue
        segment_start = max(day_start, start)
        segment_end = min(limit, end)
        segment_import = 0.0
        segment_covered_until = segment_start
        for left, right in zip(normalized_points, normalized_points[1:]):
            left_time, left_value = left
            right_time, right_value = right
            if right_time <= left_time or right_time - left_time > timedelta(minutes=30):
                continue
            overlap_start = max(segment_start, left_time)
            overlap_end = min(segment_end, right_time)
            if overlap_end <= overlap_start:
                continue
            duration = (right_time - left_time).total_seconds()
            value_at = lambda timestamp: left_value + (right_value - left_value) * ((timestamp - left_time).total_seconds() / duration)
            segment_import += (value_at(overlap_start) + value_at(overlap_end)) / 2 * ((overlap_end - overlap_start).total_seconds() / 3600)
            if overlap_start <= segment_covered_until + timedelta(milliseconds=1) and overlap_end > segment_covered_until:
                segment_covered_until = overlap_end
        if segment_covered_until < segment_end - timedelta(milliseconds=1):
            continue
        trade_total += segment_import * trade_ore / 100
        grid_total += segment_import * grid_ore / 100
        imported_total += segment_import
        covered_until = max(covered_until, segment_end)
        priced_until = max(priced_until, segment_end)
        price_samples.append((segment_import, trade_ore + grid_ore))
    if covered_until < limit - timedelta(milliseconds=1) or priced_until < limit - timedelta(milliseconds=1):
        return None
    weighted_price = sum(imported * price for imported, price in price_samples)
    return {
        "import_kwh": imported_total,
        "elhandel_sek": trade_total,
        "elnat_variable_sek": grid_total,
        "total_variable_cost_sek": trade_total + grid_total,
        "average_price_ore_per_kwh": weighted_price / imported_total if imported_total > 0 else None,
        "status": "actual" if limit >= day_end else "actual_to_date",
        "quality": "qualified",
        "method": "canonical_trapezoidal_import_by_day",
        "source": "recorder_power_history_plus_effective_price_periods",
        "observed_until": limit.isoformat(),
    }
