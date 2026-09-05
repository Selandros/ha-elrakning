"""Pure Greenely consumption normalization helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def normalize_greenely_consumption(payload: Any) -> list[dict[str, Any]]:
    """Normalize Greenely hourly Wh samples into sorted kWh samples."""
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        items = [{"timestamp": key, **value} for key, value in data.items() if isinstance(value, dict)]
    elif isinstance(data, list):
        items = [item for item in data if isinstance(item, dict)]
    else:
        return []
    result = []
    for item in items:
        usage = item.get("usage")
        localtime = item.get("localtime")
        if not isinstance(usage, (int, float)) or isinstance(usage, bool) or usage < 0:
            continue
        if not isinstance(localtime, str) or not localtime:
            continue
        sample = {"source_timestamp": str(item.get("timestamp") or ""), "localtime": localtime, "usage_wh": usage, "usage_kwh": usage / 1000}
        for key, value in item.items():
            if key not in {"timestamp", "usage", "localtime"} and isinstance(value, (str, int, float, bool)):
                sample[key] = value
        result.append(sample)
    result.sort(key=lambda item: item["localtime"])
    return result


def summarize_greenely_consumption(payload: Any, month: str) -> dict[str, Any] | None:
    """Summarize normalized samples for one local calendar month."""
    samples = normalize_greenely_consumption(payload)
    selected = [item for item in samples if item["localtime"][:7] == month]
    if not selected:
        return None
    return {
        "month": month,
        "month_to_date_kwh": sum(item["usage_kwh"] for item in selected),
        "latest_sample_at": selected[-1]["localtime"],
    }

def greenely_consumption_payload_shape(payload: Any, month: str) -> dict[str, Any]:
    """Return non-sensitive structural diagnostics for one consumption response."""
    top_level_keys = sorted(payload) if isinstance(payload, dict) else []
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        raw_items = [value for value in data.values() if isinstance(value, dict)]
    elif isinstance(data, list):
        raw_items = [value for value in data if isinstance(value, dict)]
    else:
        raw_items = []
    item_keys = sorted({key for item in raw_items[:10] for key in item if isinstance(key, str)})
    normalized = normalize_greenely_consumption(payload)
    month_matches = [
        item for item in normalized
        if isinstance(item.get("localtime"), str) and item["localtime"][:7] == month
    ]
    return {
        "payload_type": type(payload).__name__,
        "top_level_keys": top_level_keys,
        "data_type": type(data).__name__,
        "raw_item_count": len(raw_items),
        "item_keys": item_keys,
        "normalized_count": len(normalized),
        "month_match_count": len(month_matches),
    }
