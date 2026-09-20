"""Deterministic price-only ELLA planning from verified price periods."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from typing import Any, Iterable


DATASET = "ella.price_only_plan.v1"
CAPABILITY = "price"
PLAN_VERSION = "price-only-v1"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _stable_id(site_id: str, block: dict[str, Any]) -> str:
    digest = hashlib.sha256(_canonical({"dataset": DATASET, "site_id": site_id, **block}).encode()).hexdigest()
    return f"ella-price-{digest[:32]}"


def _valid_period(period: Any) -> bool:
    start = getattr(period, "start", None)
    end = getattr(period, "end", None)
    price = getattr(period, "price", None)
    return (
        isinstance(start, datetime)
        and isinstance(end, datetime)
        and start.tzinfo is not None
        and end.tzinfo is not None
        and end > start
        and isinstance(price, (int, float))
        and math.isfinite(float(price))
    )


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _group(periods: list[Any], labels: list[str]) -> list[tuple[int, int, str]]:
    groups: list[tuple[int, int, str]] = []
    start = 0
    current = labels[0]
    for index, label in enumerate(labels[1:], 1):
        if label != current:
            groups.append((start, index, current))
            start = index
            current = label
    groups.append((start, len(labels), current))
    return groups


def build_price_only_plan(
    site_id: str,
    periods: Iterable[Any],
    known_at: datetime,
    *,
    source_generation_id: str,
    source: str = "nord_pool.price_periods.v1",
) -> dict[str, Any]:
    """Build a truthful price-only plan, or an explicit unavailable result."""
    if not isinstance(site_id, str) or not site_id.strip() or known_at.tzinfo is None:
        return {"available": False, "reason": "invalid_price_capability", "capability": None, "plan_blocks": []}
    if not isinstance(source_generation_id, str) or not source_generation_id.strip():
        return {"available": False, "reason": "missing_price_provenance", "capability": None, "plan_blocks": []}
    normalized = list(periods or [])
    if not normalized or not all(_valid_period(period) for period in normalized):
        return {"available": False, "reason": "invalid_price_periods", "capability": None, "plan_blocks": []}
    normalized.sort(key=lambda item: item.start)
    if normalized[-1].end <= known_at:
        return {"available": False, "reason": "stale_price_periods", "capability": None, "plan_blocks": []}
    values = [float(period.price) for period in normalized]
    low_threshold = _percentile(values, 1 / 3)
    high_threshold = _percentile(values, 2 / 3)
    labels = [
        "cheap_period" if value <= low_threshold else
        "expensive_period" if value >= high_threshold else
        "price_change"
        for value in values
    ]
    capability = {
        "name": CAPABILITY,
        "verified": True,
        "dataset": "nord_pool.price_periods.v1",
        "source": source,
        "source_generation_id": source_generation_id,
        "known_at": known_at.isoformat(),
        "period_count": len(normalized),
        "valid_from": normalized[0].start.isoformat(),
        "valid_to": normalized[-1].end.isoformat(),
    }
    blocks: list[dict[str, Any]] = []
    for first, last, category in _group(normalized, labels):
        selected = normalized[first:last]
        start = selected[0].start
        end = selected[-1].end
        prices = [float(item.price) for item in selected]
        average = sum(prices) / len(prices)
        title = {
            "cheap_period": "Billig prisperiod",
            "expensive_period": "Dyr prisperiod",
            "price_change": "Prisförändring",
        }[category]
        reason = {
            "cheap_period": "Lägsta tredjedelen av verifierade prisperioder.",
            "expensive_period": "Högsta tredjedelen av verifierade prisperioder.",
            "price_change": "Mellanprisperiod mellan billiga och dyra fönster.",
        }[category]
        block = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "action": "flexible_consumption_window",
            "category": category,
            "title": title,
            "reason": reason,
            "verified_inputs": {"capabilities": [CAPABILITY], "source_generation_id": source_generation_id},
            "price": {"min_sek_per_kwh": min(prices), "max_sek_per_kwh": max(prices), "average_sek_per_kwh": average},
            "constraints": {},
            "execution_status": "not_executed_no_actuator",
            "plan_version": PLAN_VERSION,
        }
        block["plan_block_id"] = _stable_id(site_id, block)
        blocks.append(block)
    return {
        "available": True,
        "reason": None,
        "site_id": site_id,
        "dataset": DATASET,
        "plan_version": PLAN_VERSION,
        "capability": capability,
        "plan_blocks": blocks,
    }
