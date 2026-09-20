"""Deterministic ELLA planning from verified price periods and optional load."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import math
from typing import Any, Iterable


DATASET = "ella.price_only_plan.v1"
CAPABILITY = "price"
PLAN_VERSION = "price-only-v1"
LOAD_PAYLOAD_SCHEMA = "load_forecast.v1"
LOAD_SLOT_SECONDS = 900


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


def _load_points_for_block(
    block: dict[str, Any],
    frames: Iterable[dict[str, Any]],
    site_id: str,
    decision_at: datetime,
    actual_rows: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]] | None:
    """Return complete site-scoped actual/forecast coverage for one block."""
    try:
        start = datetime.fromisoformat(block["start"])
        end = datetime.fromisoformat(block["end"])
    except (KeyError, TypeError, ValueError):
        return None
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        return None
    expected = int((end - start).total_seconds() / LOAD_SLOT_SECONDS)
    if expected <= 0:
        return None
    candidates: list[dict[str, Any]] = []
    for frame in frames or []:
        if not isinstance(frame, dict) or frame.get("site_id") != site_id:
            continue
        if frame.get("payload_schema") != LOAD_PAYLOAD_SCHEMA:
            continue
        if frame.get("quality_status") not in {"good", "partial"}:
            continue
        try:
            frame_known_at = datetime.fromisoformat(frame["known_at"])
        except (KeyError, TypeError, ValueError):
            continue
        if frame_known_at.tzinfo is None or frame_known_at > decision_at:
            continue
        for point in frame.get("points") or []:
            if not isinstance(point, dict) or point.get("unit") != "W":
                continue
            try:
                valid_at = datetime.fromisoformat(point["valid_at"])
                value = float(point["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if valid_at.tzinfo is None or not math.isfinite(value) or value < 0:
                continue
            if start <= valid_at < end and point.get("quality_status") == "good":
                candidates.append({"valid_at": valid_at, "value": value, "frame_id": frame.get("frame_id"),
                                   "quality": frame.get("quality") or {},
                                   "source_generation_id": frame.get("source_generation_id"),
                                   "source": "forecast"})
    by_time = {point["valid_at"]: point for point in candidates}
    actual_by_time: dict[datetime, dict[str, Any]] = {}
    for row in actual_rows or []:
        if row.get("site_id") not in {None, site_id}:
            continue
        if row.get("logical_role") != "house.consumption" or row.get("unit") != "W":
            continue
        if row.get("quality_status") not in {"good", "partial"} or row.get("value") is None:
            continue
        interval_start = row.get("interval_start")
        interval_end = row.get("interval_end")
        if not isinstance(interval_start, datetime) or not isinstance(interval_end, datetime):
            continue
        if interval_start.tzinfo is None or interval_end.tzinfo is None or interval_end <= interval_start:
            continue
        if int(row.get("resolution_seconds") or 0) != LOAD_SLOT_SECONDS or interval_end > decision_at:
            continue
        value = float(row["value"])
        if not math.isfinite(value) or value < 0 or not (start <= interval_start < end):
            continue
        actual_by_time[interval_start] = {
            "valid_at": interval_start, "value": value, "frame_id": None,
            "quality": {"status": row.get("quality_status"), "source": "canonical"},
            "source_generation_id": row.get("source_generation_id"), "source": "actual",
        }
    by_time.update(actual_by_time)
    expected_times = [start + timedelta(seconds=LOAD_SLOT_SECONDS * index) for index in range(expected)]
    selected = [by_time.get(value) for value in expected_times]
    return [point for point in selected if point is not None] if all(selected) and len(by_time) == expected else None


def enrich_plan_with_load(
    plan: dict[str, Any],
    frames: Iterable[dict[str, Any]] | None,
    *,
    actual_rows: Iterable[dict[str, Any]] | None = None,
    decision_at: datetime | None = None,
) -> dict[str, Any]:
    """Add complete canonical actual/forecast load values to price blocks."""
    frame_list = list(frames or [])
    if not isinstance(plan, dict) or plan.get("available") is not True or (not frame_list and not actual_rows):
        return plan
    site_id = plan.get("site_id")
    if not isinstance(site_id, str) or not site_id:
        return plan
    try:
        decision_at = decision_at or datetime.fromisoformat(plan["capability"]["known_at"])
    except (KeyError, TypeError, ValueError):
        return plan
    if decision_at.tzinfo is None:
        return plan
    usable_frames = []
    for frame in frame_list:
        if not isinstance(frame, dict) or frame.get("site_id") != site_id:
            continue
        if frame.get("payload_schema") != LOAD_PAYLOAD_SCHEMA or frame.get("quality_status") not in {"good", "partial"}:
            continue
        try:
            frame_known_at = datetime.fromisoformat(frame["known_at"])
        except (KeyError, TypeError, ValueError):
            continue
        if frame_known_at.tzinfo is not None and frame_known_at <= decision_at:
            usable_frames.append(frame)
    enriched = {**plan, "plan_blocks": []}
    for block in plan.get("plan_blocks") or []:
        updated = dict(block)
        points = _load_points_for_block(block, frame_list, site_id, decision_at, actual_rows)
        if points:
            watts = [point["value"] for point in points]
            duration_hours = LOAD_SLOT_SECONDS / 3600
            frame_ids = sorted({point["frame_id"] for point in points if point.get("frame_id")})
            source_generations = sorted({point["source_generation_id"] for point in points if point.get("source_generation_id")})
            sources = sorted({point["source"] for point in points})
            updated["load"] = {
                "energy_kwh": sum(watts) * duration_hours / 1000,
                "average_power_kw": sum(watts) / len(watts) / 1000,
                "peak_power_kw": max(watts) / 1000,
                "coverage": "complete",
                "dataset": LOAD_PAYLOAD_SCHEMA,
                "frame_ids": frame_ids,
                "source_generation_ids": source_generations,
                "quality": "low_confidence" if any(point["quality"].get("status") == "low_confidence" for point in points) else "good",
                "estimate_kind": "mixed" if len(sources) > 1 else sources[0],
                "actual_slots": sum(point["source"] == "actual" for point in points),
                "forecast_slots": sum(point["source"] == "forecast" for point in points),
            }
            updated["verified_inputs"] = {
                **block.get("verified_inputs", {}),
                "capabilities": ["price", "load"],
                "load_frames": frame_ids,
                "load_source_generations": source_generations,
            }
            if block.get("category") == "expensive_period":
                updated["reason"] = f"Dyr prisperiod med förväntad förbrukning {updated['load']['energy_kwh']:.1f} kWh."
            elif block.get("category") == "cheap_period":
                updated["reason"] = f"Billig prisperiod; förväntad förbrukning {updated['load']['energy_kwh']:.1f} kWh."
            else:
                updated["reason"] = f"Prisförändring med förväntad förbrukning {updated['load']['energy_kwh']:.1f} kWh."
        elif usable_frames:
            # Preserve fail-closed semantics explicitly for blocks without
            # complete forecast coverage; never fill a missing interval with 0.
            updated["load"] = {"coverage": "unavailable", "reason": "incomplete_forecast_coverage"}
        enriched["plan_blocks"].append(updated)
    return enriched
