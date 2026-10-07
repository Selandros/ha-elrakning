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


def select_billing_energy_source(raw_points, reconciled_points, canonical_points):
    """Select the canonical site-scoped billing series before raw fallback data."""
    if reconciled_points:
        return reconciled_points, "reconciled_grid_import"
    if canonical_points:
        return canonical_points, "canonical_energy_history"
    return raw_points, "local_meter_history"


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


def build_bucketed_actual_cost(
    buckets: list[dict[str, Any]] | None,
    periods: list[dict[str, Any]] | None,
    interval_start: datetime,
    interval_end: datetime,
    observed_end: datetime | None = None,
) -> dict[str, Any] | None:
    """Price complete native energy buckets without converting kWh to power."""
    if interval_start.tzinfo is None or interval_end.tzinfo is None or interval_end <= interval_start:
        return None
    limit = min(interval_end, observed_end) if observed_end is not None else interval_end
    if limit <= interval_start:
        return None
    eligible = []
    for bucket in buckets or []:
        start = _timestamp(bucket.get("timestamp"))
        end = _timestamp(bucket.get("end"))
        energy = _number(bucket.get("import_kwh"))
        if not start or not end or end <= start or energy is None or energy < 0:
            continue
        if start < interval_start or end > limit:
            continue
        matching = []
        for period in periods or []:
            p_start = _timestamp(period.get("start"))
            p_end = _timestamp(period.get("end"))
            trade = _number(period.get("trade_customer_price_ore_per_kwh"))
            grid = _number(period.get("grid_variable_ore_per_kwh"))
            if p_start and p_end and p_start <= start and p_end >= end and grid is not None:
                matching.append((p_start, p_end, trade, grid))
        if len(matching) != 1:
            continue
        eligible.append((start, end, energy, matching[0], bucket))
    cursor = interval_start
    trade_total = grid_total = imported_total = 0.0
    trade_complete = True
    for start, end, energy, (_p_start, _p_end, trade, grid), _bucket in sorted(eligible):
        if start != cursor:
            return None
        imported_total += energy
        if trade is None:
            trade_complete = False
        else:
            trade_total += energy * trade / 100
        grid_total += energy * grid / 100
        cursor = end
    if cursor < limit:
        return None
    return {
        "import_kwh": imported_total,
        "elhandel_sek": trade_total if trade_complete else None,
        "elnat_variable_sek": grid_total,
        "total_variable_cost_sek": grid_total + (trade_total if trade_complete else 0.0),
        "average_price_ore_per_kwh": (grid_total + (trade_total if trade_complete else 0.0)) / imported_total * 100 if imported_total else None,
        "status": "actual" if limit >= interval_end else "actual_to_date",
        "quality": "qualified" if trade_complete else "partial",
        "method": "native_energy_bucket_by_effective_price_periods",
        "source": "reconciled_grid_import",
        "observed_until": limit.isoformat(),
        "trade_cost_status": "verified" if trade_complete else "unavailable",
        "unavailable_components": [] if trade_complete else ["elhandel_tariff"],
    }


def build_canonical_cost_result(
    *,
    month: str,
    daily_breakdown: list[dict[str, Any]] | None,
    grid_fixed_monthly_sek: float | None,
    trade_invoice_actual_sek: float | None,
    trade_actual_status: str,
    site_id: str | None,
    timezone_name: str = "Europe/Stockholm",
    monthly_forecast: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one additive, source-separated cost contract for consumers."""
    def forecast_summary(value: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        summary: dict[str, Any] = {
            "schema": "elrakning.canonical_forecast_summary.v1",
            "available": value.get("available") is True,
            "status": value.get("quality") or ("available" if value.get("available") is True else "unavailable"),
            "source": "monthly_forecast",
        }
        for key in (
            "target_month",
            "estimated_month_total_sek",
            "expected_future_cost_sek",
            "estimated_month_import_kwh",
            "expected_future_import_kwh",
            "forecast_method",
            "forecast_confidence",
        ):
            if key in value and value[key] is not None:
                summary[key] = value[key]
        for key in ("reason", "unavailable_reason"):
            if isinstance(value.get(key), str) and value[key]:
                summary[key] = value[key]
        return summary

    actual_days = [
        item.get("actual")
        for item in daily_breakdown or []
        if isinstance(item, dict) and isinstance(item.get("actual"), dict)
    ]

    def total(field: str) -> float | None:
        values = [_number(item.get(field)) for item in actual_days]
        values = [value for value in values if value is not None]
        return sum(values) if values else None

    import_kwh = total("import_kwh")
    grid_variable = total("elnat_variable_sek")
    fixed = _number(grid_fixed_monthly_sek)
    trade_invoice = _number(trade_invoice_actual_sek)
    grid_known = (grid_variable or 0.0) + (fixed or 0.0) if grid_variable is not None or fixed is not None else None
    trade_available = trade_invoice is not None and trade_actual_status == "invoice"
    known_subtotal = grid_known
    if trade_available:
        known_subtotal = (known_subtotal or 0.0) + trade_invoice
    full_available = grid_known is not None and trade_available
    daily_variable = [
        {
            "date": item.get("date"),
            "actual": item.get("actual"),
            "availability": item.get("availability"),
            "provenance": item.get("provenance"),
        }
        for item in daily_breakdown or []
        if isinstance(item, dict) and isinstance(item.get("actual"), dict)
    ]
    return {
        "schema": "elrakning.canonical_cost.v1",
        "month": month,
        "site_id": site_id,
        "actual": {
            "import_kwh": import_kwh,
            "grid_variable_sek": grid_variable,
            "trade_invoice_sek": trade_invoice if trade_available else None,
            "status": "actual" if import_kwh is not None else "unavailable",
        },
        "partial": {
            "known_month_subtotal_sek": known_subtotal,
            "status": "complete" if full_available else "partial" if known_subtotal is not None else "unavailable",
        },
        "forecast": forecast_summary(monthly_forecast),
        "fixed_monthly": {
            "grid_sek": fixed,
            "trade_sek": trade_invoice if trade_available else None,
            "total_sek": fixed if fixed is not None else (trade_invoice if trade_available else None),
            "allocation": "monthly_summary_only",
        },
        "daily_variable": daily_variable,
        "completeness": "complete" if full_available else "partial" if known_subtotal is not None else "unavailable",
        "provenance": {
            "site_id": site_id,
            "timezone": timezone_name,
            "daily_source": "reconciled_grid_import",
            "fixed_source": "effective_dated_grid_tariff",
            "trade_source": "greenely_invoice" if trade_available else "greenely_invoice_required",
        },
        "source_status": {
            "grid": "actual" if grid_known is not None else "unavailable",
            "trade": "invoice" if trade_available else trade_actual_status,
            "full_total": "actual" if full_available else "unavailable",
        },
        "import_kwh_actual": import_kwh,
        "trade_actual_status": "invoice" if trade_available else trade_actual_status,
        "grid_variable_actual_sek": grid_variable,
        "grid_fixed_monthly_sek": fixed,
        "known_month_subtotal_sek": known_subtotal,
        "full_total": {
            "available": full_available,
            "sek": known_subtotal if full_available else None,
            "reason": None if full_available else "trade_invoice_missing",
        },
    }
