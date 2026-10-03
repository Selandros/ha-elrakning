"""Safe normalization for non-billing Greenely provider data."""

from __future__ import annotations

from datetime import date
from typing import Any


def normalize_cost_distribution(payload: Any, start_date: date, end_date: date) -> dict[str, Any]:
    """Normalize verified provider percentage analysis without billing semantics."""
    data = payload.get("data") if isinstance(payload, dict) else None
    days: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for day, value in data.items():
            if not isinstance(day, str) or not _date_in_range(day, start_date, end_date):
                continue
            if not isinstance(value, dict):
                continue
            categories = {}
            for name in ("cheap", "middle", "expensive"):
                item = value.get(name)
                if not isinstance(item, dict):
                    continue
                categories[name] = {
                    "daily_rate_provider": _number_or_none(item.get("daily_rate")),
                    "daily_rate_percent": _number_or_none(item.get("daily_rate")),
                    "usage_provider": _number_or_none(item.get("usage")),
                    "total_cost_provider": _number_or_none(item.get("total_cost")),
                }
            days.append({"date": day, "categories": categories, "energy_score": _number_or_none(value.get("energy_score"))})
    days.sort(key=lambda item: item["date"])
    return {
        "schema": "greenely.cost_distribution.v1",
        "available": bool(days),
        "status": "available" if days else "unavailable",
        "period": {"from": start_date.isoformat(), "to": end_date.isoformat(), "resolution": "daily"},
        "unit": "percent",
        "unit_status": "percentage_verified",
        "days": days,
    }


def normalize_spot_price(payload: Any, start_date: date, end_date: date) -> dict[str, Any]:
    """Normalize verified provider spot prices while retaining raw values for provenance."""
    data = payload.get("data") if isinstance(payload, dict) else None
    observations: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if not isinstance(value, dict):
                continue
            localtime = value.get("localtime")
            if not isinstance(localtime, str) or not _date_in_range(localtime[:10], start_date, end_date):
                continue
            observations.append({
                "source_timestamp": str(key),
                "localtime": localtime,
                "price_provider": _number_or_none(value.get("price")),
                "price_sek_per_kwh": _scaled(value.get("price")),
                "is_complete": value.get("is_complete") if isinstance(value.get("is_complete"), bool) else None,
                "min_resolution": value.get("min_resolution") if isinstance(value.get("min_resolution"), str) else None,
            })
    observations.sort(key=lambda item: item["localtime"])
    return {
        "schema": "greenely.spot_price.v1",
        "available": bool(observations),
        "status": "available" if observations else "unavailable",
        "period": {"from": start_date.isoformat(), "to": end_date.isoformat(), "resolution": "daily"},
        "unit": "sek_per_kwh",
        "scale": 100000,
        "unit_status": "unit_verified",
        "observations": observations,
    }


def normalize_consumption_cost(
    payload: Any,
    start_date: date,
    end_date: date,
    month_to_date_kwh: float | None = None,
    month: str | None = None,
) -> dict[str, Any]:
    """Normalize verified hourly currency samples without creating billing actuals."""
    data = payload.get("data") if isinstance(payload, dict) else None
    samples: list[dict[str, Any]] = []
    if isinstance(data, dict):
        items = ((str(key), value) for key, value in data.items())
    elif isinstance(data, list):
        items = ((str(index), value) for index, value in enumerate(data))
    else:
        items = ()
    for source_timestamp, value in items:
        if not isinstance(value, dict):
            continue
        localtime = value.get("localtime")
        cost_sek = _scaled(value.get("cost"))
        if not isinstance(localtime, str) or not localtime or cost_sek is None:
            continue
        if not _date_in_range(localtime[:10], start_date, end_date):
            continue
        if month is not None and localtime[:7] != month:
            continue
        sample = {
            "source_timestamp": source_timestamp,
            "localtime": localtime,
            "cost_raw": value.get("cost"),
            "cost_sek": cost_sek,
        }
        usage = _number_or_none(value.get("usage"))
        if usage is not None and usage >= 0:
            sample["usage_wh"] = usage
            sample["usage_kwh"] = usage / 1000
        if isinstance(value.get("is_complete"), bool):
            sample["is_complete"] = value["is_complete"]
        if isinstance(value.get("min_resolution"), str):
            sample["min_resolution"] = value["min_resolution"]
        samples.append(sample)
    samples.sort(key=lambda item: item["localtime"])
    total_sek = sum(item["cost_sek"] for item in samples) if samples else None
    usage_kwh = month_to_date_kwh
    if usage_kwh is None:
        usage_values = [item["usage_kwh"] for item in samples if "usage_kwh" in item]
        usage_kwh = sum(usage_values) if usage_values else None
    average_ore = None
    if total_sek is not None and isinstance(usage_kwh, (int, float)) and usage_kwh > 0:
        average_ore = total_sek / usage_kwh * 100
    return {
        "schema": "greenely.consumption_cost.v1",
        "available": bool(samples),
        "status": "available" if samples else "unavailable",
        "source": "greenely_consumption_currency",
        "period": {"from": start_date.isoformat(), "to": end_date.isoformat(), "resolution": "hourly"},
        "unit": "sek",
        "scale": 100000,
        "samples": samples,
        "month_to_date_cost_sek": total_sek,
        "month_to_date_import_kwh": usage_kwh,
        "average_price_ore_per_kwh": average_ore,
    }


def _date_in_range(value: str, start_date: date, end_date: date) -> bool:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return start_date <= parsed <= end_date


def _number_or_none(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _scaled(value: Any) -> float | None:
    number = _number_or_none(value)
    return number / 100000 if number is not None and number >= 0 else None
