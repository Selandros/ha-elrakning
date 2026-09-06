"""Read-only site energy history for the price chart."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)

_POWER_ROLES = {
    "house.consumption",
    "solar.production",
    "grid.power/import",
    "battery.power",
}
_ENERGY_COUNTER_ROLES = {"grid.energy_import", "grid.energy_export"}
_SUPPORTED_ROLES = _POWER_ROLES | _ENERGY_COUNTER_ROLES


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _midpoint(start: datetime, end: datetime) -> datetime:
    return start + (end - start) / 2


def _active_for_interval(item: dict[str, Any], start: datetime, end: datetime) -> bool:
    point = _midpoint(start, end)
    effective_from = _parse_time(item.get("effective_from"))
    effective_to = _parse_time(item.get("effective_to"))
    return not ((effective_from and point < effective_from) or (effective_to and point >= effective_to))


def history_targets(site_manager: Any, site_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Return ledger sources whose verified/known lifetime intersects the requested period."""
    targets = []
    for item in site_manager.state.get("ledger", []):
        if not isinstance(item, dict) or item.get("site_id") != site_id:
            continue
        if item.get("logical_role") not in _SUPPORTED_ROLES or not item.get("entity_id"):
            continue
        effective_from = _parse_time(item.get("effective_from"))
        effective_to = _parse_time(item.get("effective_to"))
        if effective_from and effective_from >= end:
            continue
        if effective_to and effective_to <= start:
            continue
        targets.append(dict(item))
    return targets


def _power_to_kw(value: Any, unit: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    normalized = str(unit or "").strip().lower()
    if normalized in {"w", "watt", "watts"}:
        return number / 1000
    if normalized in {"kw", "kilowatt", "kilowatts"}:
        return number
    if normalized in {"mw", "megawatt", "megawatts"}:
        return number * 1000
    return None


def _energy_to_kwh(value: Any, unit: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    normalized = str(unit or "").strip().lower()
    if normalized in {"wh", "watt-hour", "watt-hours"}:
        return number / 1000
    if normalized in {"kwh", "kilowatt-hour", "kilowatt-hours"}:
        return number
    if normalized in {"mwh", "megawatt-hour", "megawatt-hours"}:
        return number * 1000
    return None


def _role_values(role: str, value_kw: float) -> dict[str, float]:
    if role == "house.consumption":
        return {"consumption": abs(value_kw)}
    if role == "solar.production":
        return {"solar": abs(value_kw)}
    if role == "grid.power/import":
        return {"import": max(0.0, value_kw), "export": max(0.0, -value_kw)}
    if role == "battery.power":
        return {"discharging": max(0.0, value_kw), "charging": max(0.0, -value_kw)}
    return {}


def _contribution(series: str, start: datetime, end: datetime, value_kw: float, *,
                  priority: int, source: str, generation_id: str, quality: str = "good",
                  coverage: float | None = None,
                  source_resolution_seconds: int | None = None) -> dict[str, Any]:
    return {
        "series": series,
        "start": start.astimezone(timezone.utc),
        "end": end.astimezone(timezone.utc),
        "value_kw": value_kw,
        "priority": priority,
        "source": source,
        "generation_id": generation_id,
        "quality_status": quality,
        "coverage_ratio": coverage,
        "source_resolution_seconds": source_resolution_seconds or int((end - start).total_seconds()),
    }


def canonical_contributions(rows: list[dict[str, Any]], ledger_by_generation: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert stored canonical/historical rows into graph-series contributions."""
    result: list[dict[str, Any]] = []
    for row in rows:
        role = str(row.get("logical_role") or "")
        if role not in _POWER_ROLES or row.get("quality_status") not in {"good", "partial"}:
            continue
        start = row.get("interval_start")
        end = row.get("interval_end")
        generation_id = str(row.get("source_generation_id") or "")
        if not isinstance(start, datetime) or not isinstance(end, datetime) or not generation_id:
            continue
        target = ledger_by_generation.get(generation_id)
        if target is not None and not _active_for_interval(target, start, end):
            continue
        value_kw = _power_to_kw(row.get("value"), row.get("unit"))
        if value_kw is None:
            continue
        source = "canonical" if row.get("storage_class") == "canonical" else "historical_canonical"
        priority = 30 if source == "canonical" else 25
        for series, value in _role_values(role, value_kw).items():
            result.append(_contribution(
                series, start, end, value, priority=priority, source=source,
                generation_id=generation_id, quality=str(row.get("quality_status")),
                coverage=row.get("coverage_ratio"),
                source_resolution_seconds=row.get("source_resolution_seconds"),
            ))
    return result


def _metadata_unit(metadata: dict[str, Any], statistic_id: str) -> Any:
    item = metadata.get(statistic_id)
    if not item or len(item) < 2:
        return None
    meta = item[1]
    return meta.get("unit_of_measurement") if isinstance(meta, dict) else getattr(meta, "unit_of_measurement", None)


def _statistics_start(row: dict[str, Any]) -> datetime | None:
    value = row.get("start")
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _target_canonicalization(target: dict[str, Any], field: str) -> bool:
    canonicalization = target.get("canonicalization") or {}
    value = canonicalization.get(field)
    if value is None:
        value = (target.get("mapping") or {}).get(field)
    return value is True


def _statistics_request_units(targets: list[dict[str, Any]]) -> dict[str, str]:
    unit_classes = set()
    for target in targets:
        entity_id = str(target.get("entity_id") or "")
        role = str(target.get("logical_role") or "")
        if not entity_id:
            continue
        if role in _POWER_ROLES:
            unit_classes.add("power")
        elif role in _ENERGY_COUNTER_ROLES:
            unit_classes.add("energy")
    return {unit_class: ("W" if unit_class == "power" else "kWh") for unit_class in unit_classes}


def long_term_contributions(targets: list[dict[str, Any]], metadata: dict[str, Any],
                            statistics: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Convert Home Assistant hourly long-term statistics without inventing finer resolution."""
    result: list[dict[str, Any]] = []
    for target in targets:
        role = str(target.get("logical_role") or "")
        entity_id = str(target.get("entity_id") or "")
        generation_id = str(target.get("generation_id") or "")
        if role not in _SUPPORTED_ROLES or not entity_id or not generation_id:
            continue
        unit = _metadata_unit(metadata, entity_id)
        for row in statistics.get(entity_id, []):
            start = _statistics_start(row)
            if start is None:
                continue
            end = start + timedelta(hours=1)
            if not _active_for_interval(target, start, end):
                continue
            if role in _POWER_ROLES:
                value_kw = _power_to_kw(row.get("mean"), unit)
                if value_kw is None:
                    continue
                if role in {"grid.power/import", "battery.power"}:
                    if _target_canonicalization(
                        target,
                        "invert_power" if role == "grid.power/import" else "invert_battery_power",
                    ):
                        value_kw = -value_kw
                for series, value in _role_values(role, value_kw).items():
                    result.append(_contribution(
                        series, start, end, value, priority=20,
                        source="home_assistant_long_term_statistics",
                        generation_id=generation_id,
                    ))
                continue
            energy_kwh = _energy_to_kwh(row.get("change"), unit)
            if energy_kwh is None:
                continue
            duration_hours = (end - start).total_seconds() / 3600
            if duration_hours <= 0:
                continue
            series = "import" if role == "grid.energy_import" else "export"
            result.append(_contribution(
                series, start, end, energy_kwh / duration_hours, priority=40,
                source="home_assistant_long_term_statistics_energy",
                generation_id=generation_id,
            ))
    return result


def merge_contributions(contributions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Prefer higher-fidelity intervals without inventing finer source resolution."""
    def resolution_seconds(item: dict[str, Any]) -> int:
        return int(item.get("source_resolution_seconds") or (item["end"] - item["start"]).total_seconds())

    grouped: dict[tuple[str, datetime, datetime, int, str], list[dict[str, Any]]] = {}
    for item in contributions:
        key = (item["series"], item["start"], item["end"], item["priority"], item["source"])
        grouped.setdefault(key, []).append(item)

    candidates: list[dict[str, Any]] = []
    for (series, start, end, priority, source), items in grouped.items():
        candidates.append({
            "series": series,
            "start": start,
            "end": end,
            "value_kw": sum(float(item["value_kw"]) for item in items),
            "priority": priority,
            "source": source,
            "quality_status": "partial" if any(item.get("quality_status") == "partial" for item in items) else "good",
            "coverage_ratio": min(
                (float(item["coverage_ratio"]) for item in items if item.get("coverage_ratio") is not None),
                default=None,
            ),
            "source_count": len({item["generation_id"] for item in items}),
            "source_resolution_seconds": max(resolution_seconds(item) for item in items),
            "source_interval_start": start,
            "source_interval_end": end,
        })

    accepted: dict[str, list[dict[str, Any]]] = {}
    for candidate in sorted(candidates, key=lambda item: (-item["priority"], item["start"], item["end"])):
        existing = accepted.setdefault(candidate["series"], [])
        segments = [(candidate["start"], candidate["end"])]
        for blocker in existing:
            if blocker["priority"] < candidate["priority"]:
                continue
            remaining = []
            for segment_start, segment_end in segments:
                if blocker["start"] >= segment_end or blocker["end"] <= segment_start:
                    remaining.append((segment_start, segment_end))
                    continue
                if segment_start < blocker["start"]:
                    remaining.append((segment_start, blocker["start"]))
                if blocker["end"] < segment_end:
                    remaining.append((blocker["end"], segment_end))
            segments = remaining
            if not segments:
                break
        for segment_start, segment_end in segments:
            if segment_start >= segment_end:
                continue
            existing.append({
                **candidate,
                "start": segment_start,
                "end": segment_end,
            })

    result: dict[str, list[dict[str, Any]]] = {}
    for series in ("import", "export", "solar", "consumption", "charging", "discharging"):
        intervals = sorted(accepted.get(series, []), key=lambda item: item["start"])
        result[series] = [
            {
                "start": item["start"].isoformat(),
                "end": item["end"].isoformat(),
                "value_kw": item["value_kw"],
                "resolution_seconds": int(item["source_resolution_seconds"]),
                "source_interval_start": item["source_interval_start"].isoformat(),
                "source_interval_end": item["source_interval_end"].isoformat(),
                "source": item["source"],
                "quality_status": item["quality_status"],
                "coverage_ratio": item["coverage_ratio"],
                "source_count": item["source_count"],
            }
            for item in intervals
        ]
    return result


def _load_long_term_statistics(hass: Any, statistic_ids: set[str], units: dict[str, str],
                               start: datetime, end: datetime):
    from homeassistant.components.recorder.statistics import get_metadata, statistics_during_period

    metadata = get_metadata(hass, statistic_ids=statistic_ids)
    statistics = statistics_during_period(
        hass, start, end, statistic_ids, "hour", units, {"mean", "change"}
    )
    return metadata, statistics


async def async_build_energy_history(hass: Any, site_manager: Any, collector: Any,
                                     start: datetime, end: datetime) -> dict[str, Any]:
    """Build one site's read-only energy history for a price period range."""
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    site_id = site_manager.state.get("active_site_id") if site_manager else None
    empty_series = {name: [] for name in ("import", "export", "solar", "consumption", "charging", "discharging")}
    if not site_id or collector is None:
        return {"site_id": site_id, "start": start.isoformat(), "end": end.isoformat(), "series": empty_series}

    rows = await hass.async_add_executor_job(
        collector.storage.read_site_energy_history, str(site_id), start, end
    )
    targets = history_targets(site_manager, str(site_id), start, end)
    ledger_by_generation = {
        str(item.get("generation_id")): item for item in targets if item.get("generation_id")
    }
    contributions = canonical_contributions(rows, ledger_by_generation)

    statistic_ids = {str(item["entity_id"]) for item in targets if item.get("entity_id")}
    if statistic_ids:
        try:
            from homeassistant.components.recorder import get_instance

            recorder = get_instance(hass)
            metadata, statistics = await recorder.async_add_executor_job(
                _load_long_term_statistics, hass, statistic_ids, _statistics_request_units(targets), start, end
            )
            contributions.extend(long_term_contributions(targets, metadata, statistics))
        except Exception:  # Long-term fallback must never break price data.
            _LOGGER.debug("Unable to load long-term energy statistics", exc_info=True)

    series = merge_contributions(contributions)
    sources = sorted({item["source"] for values in series.values() for item in values})
    return {
        "site_id": str(site_id),
        "start": start.astimezone(timezone.utc).isoformat(),
        "end": end.astimezone(timezone.utc).isoformat(),
        "series": series,
        "sources": sources,
        "interval_count": sum(len(values) for values in series.values()),
    }
