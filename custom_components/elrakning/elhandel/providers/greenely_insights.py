"""Safe normalization for non-billing Greenely provider data."""

from __future__ import annotations

from datetime import date
from typing import Any


def normalize_cost_distribution(payload: Any, start_date: date, end_date: date) -> dict[str, Any]:
    """Normalize provider analysis without assigning billing units or semantics."""
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
        "unit_status": "provider_units_unverified",
        "days": days,
    }


def normalize_spot_price(payload: Any, start_date: date, end_date: date) -> dict[str, Any]:
    """Normalize provider spot observations while preserving their raw unit status."""
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
                "is_complete": value.get("is_complete") if isinstance(value.get("is_complete"), bool) else None,
                "min_resolution": value.get("min_resolution") if isinstance(value.get("min_resolution"), str) else None,
            })
    observations.sort(key=lambda item: item["localtime"])
    return {
        "schema": "greenely.spot_price.v1",
        "available": bool(observations),
        "status": "available" if observations else "unavailable",
        "period": {"from": start_date.isoformat(), "to": end_date.isoformat(), "resolution": "daily"},
        "unit_status": "provider_unit_unverified",
        "observations": observations,
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
