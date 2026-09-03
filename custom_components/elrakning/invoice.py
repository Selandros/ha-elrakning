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
