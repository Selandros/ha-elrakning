"""Read-only, frozen evidence collection for solar forecast comparison."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from functools import partial
from typing import Any

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store

from .site_context import async_load_site_store
from .solar_provenance import (
    FORECAST_SOLAR_DATASET,
    OPEN_METEO_EVIDENCE_DATASET,
    append_immutable,
    build_provenance_record,
)
from homeassistant.util import dt as dt_util

from .solar_pvgis import build_installation


STORE_KEY = "elrakning.solar_evidence"
PROVENANCE_STORE_KEY = "elrakning.solar_evidence_provenance"
PROVENANCE_STORE_VERSION = 1
PROTOCOL_VERSION = "evidence-v1"
AUDIT_SEMANTICS_VERSION = "solar-evidence-audit-v3"
COMPARISON_EVIDENCE_VERSION = "solar-comparison-evidence-v1"
OPEN_METEO_ENDPOINT = "https://previous-runs-api.open-meteo.com/v1/forecast"
ACTIVE_THRESHOLD_KW = 0.05
MAX_INTERNAL_GAP_MINUTES = 30
# Keep quality recovery bounded to the recent evidence window; never scan all history at startup.
MAX_QUALITY_RECOVERY_DAYS = 60
CAPACITY_KWP = 9.45
PANEL_TILT = 30
OPEN_METEO_AZIMUTH = 45


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _state_point(state: Any) -> dict[str, Any] | None:
    value = _number(getattr(state, "state", None))
    timestamp = getattr(state, "last_updated", None)
    if value is None or timestamp is None:
        return None
    unit = str(getattr(state, "attributes", {}).get("unit_of_measurement", "")).lower()
    if unit == "w":
        value /= 1000
    elif unit != "kw":
        return None
    return {"timestamp": timestamp.isoformat(), "value_kw": abs(value)}


def merge_pv_points(history_by_entity: dict[str, list[Any]], entity_ids: list[str]) -> list[dict[str, Any]]:
    """Merge PV states using latest-known values at every recorded timestamp."""
    normalized = {
        entity: sorted((point for state in history_by_entity.get(entity, []) if (point := _state_point(state))), key=lambda item: item["timestamp"])
        for entity in entity_ids
    }
    timestamps = sorted({point["timestamp"] for points in normalized.values() for point in points})
    cursors = {entity: 0 for entity in entity_ids}
    result = []
    for timestamp in timestamps:
        total = 0.0
        known = False
        for entity in entity_ids:
            points = normalized[entity]
            while cursors[entity] < len(points) and points[cursors[entity]]["timestamp"] <= timestamp:
                cursors[entity] += 1
            if cursors[entity]:
                total += points[cursors[entity] - 1]["value_kw"]
                known = True
        if known:
            result.append({"timestamp": timestamp, "value_kw": total})
    return result


def integrate_actual(points: list[dict[str, Any]], start: datetime, end: datetime) -> tuple[float | None, int, int]:
    """Integrate finite segments, excluding segments longer than one hour."""
    total = 0.0
    boundary_long = 0
    interior_long = 0
    parsed = [(dt_util.parse_datetime(item.get("timestamp")), _number(item.get("value_kw"))) for item in points]
    parsed = [(timestamp, value) for timestamp, value in parsed if timestamp is not None and value is not None]
    active_times = [
        timestamp for timestamp, value in parsed
        if start <= timestamp < end and value > ACTIVE_THRESHOLD_KW
    ]
    first_active = min(active_times, default=None)
    last_active = max(active_times, default=None)
    for (left_time, left_value), (right_time, right_value) in zip(parsed, parsed[1:]):
        if left_time < start or left_time >= end:
            continue
        segment_end = min(right_time, end)
        duration = (segment_end - left_time).total_seconds() / 3600
        if 0 < duration <= 1:
            total += (left_value + right_value) / 2 * duration
        elif duration > 1:
            boundary_long += 1
            if (first_active is not None and first_active <= left_time
                    and right_time <= last_active
                    and (left_value > ACTIVE_THRESHOLD_KW or right_value > ACTIVE_THRESHOLD_KW)):
                interior_long += 1
    return total if parsed else None, boundary_long, interior_long


def assess_completeness(points: list[dict[str, Any]], entity_starts: list[bool], start: datetime, end: datetime) -> dict[str, Any]:
    day_points = sorted((point for point in points if start <= dt_util.parse_datetime(point["timestamp"]) < end), key=lambda point: point["timestamp"])
    active = [point for point in day_points if point["value_kw"] > ACTIVE_THRESHOLD_KW]
    max_gap = 0.0
    if len(active) > 1:
        first_active = dt_util.parse_datetime(active[0]["timestamp"])
        last_active = dt_util.parse_datetime(active[-1]["timestamp"])
        interior = [point for point in day_points if first_active <= dt_util.parse_datetime(point["timestamp"]) <= last_active]
        interior_times = [dt_util.parse_datetime(point["timestamp"]) for point in interior]
        max_gap = max((right - left).total_seconds() / 60 for left, right in zip(interior_times, interior_times[1:]))
    reasons = []
    if not all(entity_starts): reasons.append("start_state_missing")
    if len(day_points) < 20: reasons.append("merged_points_below_20")
    if len(active) < 2: reasons.append("active_points_below_2")
    if max_gap > MAX_INTERNAL_GAP_MINUTES: reasons.append("max_internal_gap_over_30_minutes")
    return {"audit_complete": not reasons, "exclusion_reasons": reasons, "merged_points": len(day_points), "active_points": len(active), "max_internal_gap_minutes": max_gap}


def count_invalid_states_in_target_day(
    history_by_entity: dict[str, list[Any]],
    entity_ids: list[str],
    start: datetime,
    end: datetime,
) -> tuple[int, int]:
    """Separate target-day invalid states from query-window padding states."""
    in_day = 0
    padding = 0
    invalid_states = {"unknown", "unavailable"}
    for entity in entity_ids:
        for state in history_by_entity.get(entity, []):
            if str(getattr(state, "state", "")).lower() not in invalid_states:
                continue
            timestamp = getattr(state, "last_updated", None)
            if timestamp is None or start <= timestamp < end:
                # Missing timestamps remain fail-closed rather than being treated as padding.
                in_day += 1
            else:
                padding += 1
    return in_day, padding


def assess_invalid_intervals(
    history_by_entity: dict[str, list[Any]],
    entity_ids: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Classify bounded in-day invalid runs without changing raw history."""
    raw_count = 0
    tolerated_intervals = 0
    untolerated_count = 0
    untolerated_duration = 0.0
    untolerated_duration_unknown = False
    intervals: list[tuple[datetime, datetime]] = []
    invalid_states = {"unknown", "unavailable"}

    for entity in entity_ids:
        states = sorted(history_by_entity.get(entity, []), key=lambda item: getattr(item, "last_updated", None) or start)
        for index, state in enumerate(states):
            timestamp = getattr(state, "last_updated", None)
            if str(getattr(state, "state", "")).strip().lower() not in invalid_states:
                continue
            if timestamp is None:
                raw_count += 1
                untolerated_count += 1
                untolerated_duration_unknown = True
                continue
            if not start <= timestamp < end:
                continue
            raw_count += 1
            previous_valid = index > 0 and _state_point(states[index - 1]) is not None
            next_index = index + 1
            while next_index < len(states) and str(getattr(states[next_index], "state", "")).strip().lower() in invalid_states:
                next_index += 1
            next_state = states[next_index] if next_index < len(states) else None
            next_timestamp = getattr(next_state, "last_updated", None) if next_state is not None else None
            bounded = previous_valid and next_state is not None and next_timestamp is not None and _state_point(next_state) is not None
            if not bounded:
                untolerated_count += 1
                untolerated_duration_unknown = True
                continue
            if index == 0 or str(getattr(states[index - 1], "state", "")).strip().lower() not in invalid_states:
                duration = max(0.0, (next_timestamp - timestamp).total_seconds())
                if duration <= MAX_INTERNAL_GAP_MINUTES * 60:
                    tolerated_intervals += 1
                    intervals.append((timestamp, next_timestamp))
                else:
                    untolerated_count += 1
                    untolerated_duration += duration

    merged_intervals: list[tuple[datetime, datetime]] = []
    for interval_start, interval_end in sorted(intervals):
        if merged_intervals and interval_start <= merged_intervals[-1][1]:
            merged_intervals[-1] = (merged_intervals[-1][0], max(merged_intervals[-1][1], interval_end))
        else:
            merged_intervals.append((interval_start, interval_end))
    union_duration = sum((right - left).total_seconds() for left, right in merged_intervals)
    if union_duration > MAX_INTERNAL_GAP_MINUTES * 60 and intervals:
        untolerated_count += 1
        untolerated_duration += union_duration - MAX_INTERNAL_GAP_MINUTES * 60
    return {
        "raw_in_day_invalid_count": raw_count,
        "tolerated_invalid_interval_count": tolerated_intervals,
        "tolerated_invalid_duration_seconds": union_duration,
        "untolerated_invalid_count": untolerated_count,
        "untolerated_invalid_duration_seconds": None if untolerated_duration_unknown else untolerated_duration,
    }


def parse_previous_runs(payload: dict[str, Any], target_date: str) -> dict[str, Any]:
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    values = hourly.get("global_tilted_irradiance_previous_day1") if isinstance(hourly, dict) else None
    times = hourly.get("time") if isinstance(hourly, dict) else None
    selected = [value for timestamp, value in zip(times or [], values or []) if str(timestamp).startswith(target_date)]
    numeric = [_number(value) for value in selected]
    if len(selected) != 24 or any(value is None for value in numeric):
        return {"status": "invalid", "values": len(selected), "missing": sum(value is None for value in numeric)}
    gti = sum(numeric) / 1000
    return {"status": "complete", "values": 24, "missing": 0, "gti_kwh_m2": gti, "nominal_kwh": gti * CAPACITY_KWP}


def build_evidence_collection_targets(site_configs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return enabled, explicitly bound Evidence-v1 site targets."""
    targets: list[dict[str, Any]] = []
    if not isinstance(site_configs, dict):
        return targets
    for site_id in sorted(site_configs):
        config = site_configs.get(site_id)
        if not isinstance(config, dict) or config.get("collection_enabled", True) is not True:
            continue
        bindings = config.get("bindings")
        binding = bindings.get("evidence") if isinstance(bindings, dict) else None
        if (
            not isinstance(binding, dict)
            or binding.get("source") != "solar_evidence"
            or binding.get("protocol_version") != PROTOCOL_VERSION
        ):
            continue
        power = config.get("power") if isinstance(config.get("power"), dict) else {}
        solar_entities = power.get("solar_entities")
        if (
            not isinstance(solar_entities, list)
            or not solar_entities
            or any(not isinstance(entity_id, str) or not entity_id for entity_id in solar_entities)
        ):
            continue
        targets.append({
            "site_id": site_id,
            "binding": deepcopy(binding),
            "power": deepcopy(power),
        })
    return targets


def should_reprocess_existing_day(existing: dict[str, Any] | None) -> bool:
    """Re-evaluate only records not produced with the current audit semantics."""
    return not (
        isinstance(existing, dict)
        and existing.get("audit_semantics_version") == AUDIT_SEMANTICS_VERSION
    )


def should_recover_stale_quality(existing: dict[str, Any] | None) -> bool:
    """Select persisted evidence whose current audit fields are visibly incomplete."""
    if not isinstance(existing, dict) or existing.get("audit_complete") is True:
        return False
    comparison = existing.get("historical_comparison_evidence")
    if not isinstance(comparison, dict):
        return False
    if not (comparison.get("open_meteo_eligible") or comparison.get("forecast_solar_common_eligible")):
        return False
    if existing.get("audit_semantics_version") != AUDIT_SEMANTICS_VERSION:
        return True
    return (
        existing.get("merged_points") == 0
        or existing.get("active_points") == 0
        or existing.get("start_state_available") is False
        or "actual_unavailable" in (existing.get("exclusion_reasons") or [])
    )


def build_historical_comparison_evidence(
    record: dict[str, Any] | None,
    *,
    site_id: str | None = None,
    target_date: str | None = None,
) -> dict[str, Any]:
    """Derive comparison eligibility only from captured, persisted fields."""
    item = record if isinstance(record, dict) else {}
    actual_site = item.get("site_id")
    actual_date = item.get("date")
    site_match = isinstance(site_id, str) and actual_site == site_id if site_id is not None else isinstance(actual_site, str)
    date_match = isinstance(target_date, str) and actual_date == target_date if target_date is not None else isinstance(actual_date, str)
    captured_at = item.get("first_collected_at") or item.get("collected_at")
    actual_valid = _number(item.get("actual_kwh")) is not None
    open_meteo_valid = (
        actual_valid
        and item.get("open_meteo_status") == "complete"
        and item.get("open_meteo_values") == 24
        and item.get("open_meteo_missing") == 0
        and _number(item.get("open_meteo_nominal_kwh")) is not None
        and isinstance(captured_at, str)
        and site_match
        and date_match
    )
    forecast_solar_valid = open_meteo_valid and _number(item.get("forecast_solar_frozen_kwh")) is not None
    reasons = []
    if not site_match:
        reasons.append("site_mismatch")
    if not date_match:
        reasons.append("date_mismatch")
    if not captured_at:
        reasons.append("capture_timestamp_missing")
    if not actual_valid:
        reasons.append("actual_missing")
    if not open_meteo_valid:
        reasons.append("open_meteo_evidence_incomplete")
    if open_meteo_valid and not forecast_solar_valid:
        reasons.append("forecast_solar_evidence_missing")
    return {
        "version": COMPARISON_EVIDENCE_VERSION,
        "site_id": actual_site,
        "date": actual_date,
        "captured_at": captured_at,
        "open_meteo_eligible": bool(open_meteo_valid),
        "forecast_solar_common_eligible": bool(forecast_solar_valid),
        "reasons": reasons,
    }


def _collection_failures(result: dict[str, dict[str, Any]]) -> set[str]:
    """Return failed site ids without retaining unbounded per-target diagnostics."""
    return {
        site_id
        for site_id, record in result.items()
        if isinstance(record, dict)
        and "collection_failed" in (record.get("exclusion_reasons") or [])
    }


class SolarEvidenceManager:
    """Collect frozen evidence without feeding any candidate/model path."""

    def __init__(self, hass, power_manager, forecast_manager, collection_site_configs_getter=None) -> None:
        self.hass = hass
        self.power_manager = power_manager
        self.forecast_manager = forecast_manager
        self._collection_site_configs_getter = collection_site_configs_getter
        self._collection_lock = asyncio.Lock()
        self.store = Store(hass, 1, STORE_KEY)
        self.provenance_store = Store(hass, PROVENANCE_STORE_VERSION, PROVENANCE_STORE_KEY)
        self._provenance: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self._days: dict[str, dict[str, Any]] = {}
        self._task = None
        self._unsub = None
        self._site_id: str | None = None
        self._site_context_enabled = False
        self._capture_tasks: dict[str, dict[str, Any]] = {}
        self._quality_recovery_status: dict[str, Any] = {
            "outcome": "not_run",
            "target_count": 0,
            "candidate_count": 0,
            "attempted": [],
            "recovered": [],
        }

    def mark_capture_scheduled(self, source: str, target_date: date | None = None) -> None:
        """Record only the latest bounded capture-task lifecycle marker."""
        self._capture_tasks[source] = {
            "source": source,
            "scheduled_at": dt_util.now().isoformat(),
            "started_at": None,
            "finished_at": None,
            "target_date": target_date.isoformat() if target_date else None,
            "target_site_ids": [],
            "outcome": "scheduled",
        }

    def _capture_started(self, source: str, target_date: date | None = None) -> None:
        status = self._capture_tasks.get(source)
        if not status:
            self.mark_capture_scheduled(source, target_date)
            status = self._capture_tasks[source]
        status.update({
            "started_at": dt_util.now().isoformat(),
            "outcome": "running",
        })

    def _capture_finished(self, source: str, outcome: str, target_site_ids: list[str] | None = None, error: BaseException | None = None) -> None:
        status = self._capture_tasks.setdefault(source, {"source": source})
        status.update({
            "finished_at": dt_util.now().isoformat(),
            "outcome": outcome,
            "target_site_ids": sorted({site_id for site_id in (target_site_ids or []) if isinstance(site_id, str)}),
        })
        if error is not None:
            status["error_type"] = type(error).__name__
            status["error"] = str(error)[:160]
        else:
            status.pop("error_type", None)
            status.pop("error", None)

    async def async_load(self) -> None:
        try:
            cached = await self.store.async_load()
        except Exception:
            cached = None
        if isinstance(cached, dict) and isinstance(cached.get("days"), dict):
            self._days = {key: value for key, value in cached["days"].items() if isinstance(key, str) and isinstance(value, dict)}
        try:
            self._unsub = async_track_time_change(self.hass, self._daily_update, hour=0, minute=5, second=0)
        except Exception:
            self._unsub = None

    def discovered_binding(self) -> dict[str, Any]:
        """Return the site-local evidence context marker."""
        return {"source": "solar_evidence", "protocol_version": PROTOCOL_VERSION}

    async def async_apply_site_context(self, site_id: str, binding: dict[str, Any] | None) -> None:
        """Switch evidence days to one site namespace."""
        async with self._collection_lock:
            self._site_id = site_id if isinstance(binding, dict) else None
            self._site_context_enabled = True
            if self._site_id is None:
                self._days = {}
                self._provenance = {}
                return
            self.store, cached = await async_load_site_store(self.hass, STORE_KEY, 1, self._site_id)
            self.provenance_store, provenance = await async_load_site_store(
                self.hass, PROVENANCE_STORE_KEY, PROVENANCE_STORE_VERSION, self._site_id
            )
            self._provenance = {}
            if isinstance(provenance, dict) and isinstance(provenance.get("observations"), dict):
                self._provenance = {
                    str(target): dict(sources)
                    for target, sources in provenance["observations"].items()
                    if isinstance(sources, dict)
                }
            self._days = {}
            if cached and isinstance(cached.get("days"), dict):
                self._days = {
                    key: value for key, value in cached["days"].items()
                    if isinstance(key, str) and isinstance(value, dict)
                }
                for day in self._days.values():
                    day.setdefault("site_id", self._site_id)
            await self._migrate_historical_comparison_evidence()

    async def _migrate_historical_comparison_evidence(self) -> None:
        """Persist comparison eligibility once from existing captured fields only."""
        changed = False
        for key, day in self._days.items():
            stored = day.get("historical_comparison_evidence")
            if isinstance(stored, dict) and stored.get("version") == COMPARISON_EVIDENCE_VERSION:
                continue
            day["historical_comparison_evidence"] = build_historical_comparison_evidence(
                day,
                site_id=self._site_id,
                target_date=key,
            )
            changed = True
        if changed:
            await self.store.async_save({"protocol_version": PROTOCOL_VERSION, "days": self._days})

    async def async_shutdown(self) -> None:
        if self._unsub:
            self._unsub()
        if self._task:
            self._task.cancel()

    def _collection_targets(self) -> list[dict[str, Any]]:
        getter = self._collection_site_configs_getter
        configs = getter() if callable(getter) else {}
        return build_evidence_collection_targets(configs)

    async def _daily_update(self, _now) -> None:
        target_date = dt_util.as_local(dt_util.now()).date() - timedelta(days=1)
        self.mark_capture_scheduled("daily", target_date)
        self._capture_started("daily", target_date)
        try:
            result = await self.async_collect_completed_day_for_targets(target_date)
            failures = _collection_failures(result)
            self._capture_finished(
                "daily",
                "error" if failures else "success",
                list(result),
                RuntimeError("collection_failed") if failures else None,
            )
        except asyncio.CancelledError:
            self._capture_finished("daily", "cancelled")
            raise
        except Exception as error:
            self._capture_finished("daily", "error", error=error)
            return

    async def async_backfill(self, days: int = 30) -> None:
        self.mark_capture_scheduled("backfill")
        self._capture_started("backfill")
        target_site_ids: set[str] = set()
        failed_site_ids: set[str] = set()
        try:
            today = dt_util.as_local(dt_util.now()).date()
            for offset in range(1, days + 1):
                try:
                    result = await self.async_collect_completed_day_for_targets(today - timedelta(days=offset))
                    target_site_ids.update(result)
                    failed_site_ids.update(_collection_failures(result))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    continue
            self._capture_finished(
                "backfill",
                "error" if failed_site_ids else "success",
                list(target_site_ids),
                RuntimeError("collection_failed") if failed_site_ids else None,
            )
        except asyncio.CancelledError:
            self._capture_finished("backfill", "cancelled", list(target_site_ids))
            raise
        except Exception as error:
            self._capture_finished("backfill", "error", list(target_site_ids), error)
            return

    async def async_startup_catch_up(self) -> None:
        """Finalize yesterday through the same site-explicit evidence path as 00:05."""
        yesterday = dt_util.as_local(dt_util.now()).date() - timedelta(days=1)
        self._capture_started("startup", yesterday)
        try:
            result = await self.async_collect_completed_day_for_targets(yesterday)
            await self.async_recover_stale_quality_for_targets()
            failures = _collection_failures(result)
            self._capture_finished(
                "startup",
                "error" if failures else "success",
                list(result),
                RuntimeError("collection_failed") if failures else None,
            )
        except asyncio.CancelledError:
            self._capture_finished("startup", "cancelled")
            raise
        except Exception as error:
            self._capture_finished("startup", "error", error=error)
            return

    async def async_recover_stale_quality_for_targets(self) -> dict[str, list[str]]:
        """Rebuild only current audit fields from Recorder for bounded stale records."""
        recovered: dict[str, list[str]] = {}
        status = {
            "outcome": "running",
            "target_count": 0,
            "candidate_count": 0,
            "attempted": [],
            "recovered": [],
        }
        self._quality_recovery_status = status
        if not callable(self._collection_site_configs_getter):
            status["outcome"] = "skipped_no_site_config_getter"
            return recovered
        targets = self._collection_targets()
        status["target_count"] = len(targets)
        for target in targets:
            site_id = target["site_id"]
            store, cached = await async_load_site_store(self.hass, STORE_KEY, 1, site_id)
            days = {
                key: dict(value)
                for key, value in ((cached or {}).get("days", {}) or {}).items()
                if isinstance(key, str) and isinstance(value, dict)
            }
            candidates = []
            for key, existing in days.items():
                try:
                    target_date = date.fromisoformat(key)
                except (TypeError, ValueError):
                    continue
                if should_recover_stale_quality(existing):
                    candidates.append((target_date, key))
            candidates = sorted(candidates)[-MAX_QUALITY_RECOVERY_DAYS:]
            status["candidate_count"] += len(candidates)
            for target_date, key in candidates:
                status["attempted"].append(f"{site_id}:{key}")
                if await self._async_recover_target_day_quality(target, target_date, store, days):
                    recovered.setdefault(site_id, []).append(key)
                    status["recovered"].append(f"{site_id}:{key}")
        status["outcome"] = "success"
        return recovered

    async def _async_recover_target_day_quality(
        self,
        target: dict[str, Any],
        target_date: date,
        store,
        days: dict[str, dict[str, Any]],
    ) -> bool:
        """Persist only Recorder-derived audit fields; captured provider facts stay immutable."""
        site_id = target["site_id"]
        entities = list((target.get("power") or {}).get("solar_entities", []))
        if not entities:
            return False
        local_now = dt_util.as_local(dt_util.now())
        start = dt_util.start_of_local_day(datetime.combine(target_date, datetime.min.time(), tzinfo=local_now.tzinfo))
        end = dt_util.start_of_local_day(start + timedelta(days=1))
        query_end = end + timedelta(hours=12)
        try:
            from homeassistant.components.recorder import get_instance, history
            recorder = get_instance(self.hass)
            history_by_entity = await recorder.async_add_executor_job(
                partial(
                    history.get_significant_states,
                    self.hass,
                    start,
                    query_end,
                    entity_ids=entities,
                    include_start_time_state=True,
                    significant_changes_only=False,
                    minimal_response=False,
                    no_attributes=False,
                )
            )
        except Exception:
            return False
        merged = merge_pv_points(history_by_entity, entities)
        unavailable, padding_unavailable = count_invalid_states_in_target_day(
            history_by_entity, entities, start, end
        )
        invalid_quality = assess_invalid_intervals(history_by_entity, entities, start, end)
        entity_starts = []
        for entity in entities:
            points = [point for state in history_by_entity.get(entity, []) if (point := _state_point(state))]
            entity_starts.append(bool(points and abs((dt_util.parse_datetime(points[0]["timestamp"]) - start).total_seconds()) <= 2))
        actual, boundary_long, interior_long = integrate_actual(merged, start, end)
        quality = assess_completeness(merged, entity_starts, start, end)
        if invalid_quality["untolerated_invalid_count"]:
            quality["exclusion_reasons"].append("unavailable_or_unknown")
        if actual is None:
            quality["exclusion_reasons"].append("actual_unavailable")
        record = {
            "site_id": site_id,
            "date": target_date.isoformat(),
            "protocol_version": PROTOCOL_VERSION,
            "audit_semantics_version": AUDIT_SEMANTICS_VERSION,
            "collected_at": dt_util.now().isoformat(),
            "merged_points": quality["merged_points"],
            "active_points": quality["active_points"],
            "max_internal_gap_minutes": quality["max_internal_gap_minutes"],
            "interior_long_gap_count": interior_long,
            "boundary_long_gap_count": boundary_long,
            "unavailable_or_unknown": unavailable,
            "in_day_unavailable_or_unknown": unavailable,
            "padding_unavailable_or_unknown": padding_unavailable,
            **invalid_quality,
            "start_state_available": all(entity_starts),
            "audit_complete": quality["audit_complete"] and interior_long == 0 and invalid_quality["untolerated_invalid_count"] == 0 and actual is not None,
            "exclusion_reasons": quality["exclusion_reasons"] + (["interior_long_gap"] if interior_long else []),
            "_quality_recovery": True,
        }
        await self._save_target_day(site_id, store, days, target_date.isoformat(), record)
        return True

    async def async_collect_completed_day_for_targets(self, target_date: date) -> dict[str, dict[str, Any]]:
        """Collect one completed day for every eligible site, independent of active UI context."""
        if not callable(self._collection_site_configs_getter):
            return {"legacy": await self.async_collect_completed_day(target_date)}
        results: dict[str, dict[str, Any]] = {}
        for target in self._collection_targets():
            site_id = target["site_id"]
            try:
                results[site_id] = await self._async_collect_target_day(target, target_date)
            except asyncio.CancelledError:
                raise
            except Exception:
                results[site_id] = {
                    "site_id": site_id,
                    "date": target_date.isoformat(),
                    "audit_complete": False,
                    "exclusion_reasons": ["collection_failed"],
                }
        return results

    async def async_collect_completed_day(self, target_date: date) -> dict[str, Any]:
        """Collect the active site's target; retained for explicit/manual compatibility."""
        if callable(self._collection_site_configs_getter):
            target = next(
                (item for item in self._collection_targets() if item.get("site_id") == self._site_id),
                None,
            )
            if target is None:
                return {
                    "date": target_date.isoformat(),
                    "audit_complete": False,
                    "exclusion_reasons": ["site_unconfigured"],
                }
            return await self._async_collect_target_day(target, target_date)
        if getattr(self, "_site_context_enabled", False) and getattr(self, "_site_id", None) is None:
            return {"date": target_date.isoformat(), "audit_complete": False, "exclusion_reasons": ["site_unconfigured"]}
        power_state = await self.power_manager.async_state()
        return await self._async_collect_target_day(
            {"site_id": self._site_id, "binding": {}, "power": power_state}, target_date
        )

    async def _async_collect_target_day(self, target: dict[str, Any], target_date: date) -> dict[str, Any]:
        site_id = target["site_id"]
        power_state = target.get("power") if isinstance(target.get("power"), dict) else {}
        async with self._collection_lock:
            store, cached = await async_load_site_store(self.hass, STORE_KEY, 1, site_id)
            provenance_store, provenance_cached = await async_load_site_store(
                self.hass, PROVENANCE_STORE_KEY, PROVENANCE_STORE_VERSION, site_id
            )
            days = {
                key: dict(value)
                for key, value in ((cached or {}).get("days", {}) or {}).items()
                if isinstance(key, str) and isinstance(value, dict)
            }
            key = target_date.isoformat()
            existing = days.get(key)
            if not should_reprocess_existing_day(existing):
                if site_id == self._site_id:
                    self._days = {day: dict(value) for day, value in days.items()}
                    self.store = store
                return existing
            entities = list(power_state.get("solar_entities", []))
            start = dt_util.start_of_local_day(datetime.combine(target_date, datetime.min.time(), tzinfo=dt_util.now().tzinfo))
            end = dt_util.start_of_local_day(start + timedelta(days=1))
            query_end = end + timedelta(hours=12)
            record: dict[str, Any] = {
                "site_id": site_id, "date": key, "protocol_version": PROTOCOL_VERSION,
                "audit_semantics_version": AUDIT_SEMANTICS_VERSION,
                "collected_at": dt_util.now().isoformat(), "pv_entity_count": len(entities), "actual_kwh": None,
            }
            if not entities:
                record["exclusion_reasons"] = ["no_solar_entities"]
                record["audit_complete"] = False
                return await self._save_target_day(site_id, store, days, key, record)
            try:
                from homeassistant.components.recorder import get_instance, history
                recorder = get_instance(self.hass)
                history_by_entity = await recorder.async_add_executor_job(partial(history.get_significant_states, self.hass, start, query_end, entity_ids=entities, include_start_time_state=True, significant_changes_only=False, minimal_response=False, no_attributes=False))
            except Exception:
                record.update({"audit_complete": False, "exclusion_reasons": ["recorder_unavailable"]})
                return await self._save_target_day(site_id, store, days, key, record)
            merged = merge_pv_points(history_by_entity, entities)
            entity_starts = []
            unavailable, padding_unavailable = count_invalid_states_in_target_day(
                history_by_entity, entities, start, end
            )
            invalid_quality = assess_invalid_intervals(history_by_entity, entities, start, end)
            for entity in entities:
                points = [point for state in history_by_entity.get(entity, []) if (point := _state_point(state))]
                entity_starts.append(bool(points and abs((dt_util.parse_datetime(points[0]["timestamp"]) - start).total_seconds()) <= 2))
            actual, boundary_long, interior_long = integrate_actual(merged, start, end)
            quality = assess_completeness(merged, entity_starts, start, end)
            if invalid_quality["untolerated_invalid_count"]:
                quality["exclusion_reasons"].append("unavailable_or_unknown")
            if actual is None:
                quality["exclusion_reasons"].append("actual_unavailable")
            record.update({"actual_kwh": actual, "merged_points": quality["merged_points"], "active_points": quality["active_points"], "max_internal_gap_minutes": quality["max_internal_gap_minutes"], "interior_long_gap_count": interior_long, "boundary_long_gap_count": boundary_long, "unavailable_or_unknown": unavailable, "in_day_unavailable_or_unknown": unavailable, "padding_unavailable_or_unknown": padding_unavailable, **invalid_quality, "start_state_available": all(entity_starts), "audit_complete": quality["audit_complete"] and interior_long == 0 and invalid_quality["untolerated_invalid_count"] == 0 and actual is not None, "exclusion_reasons": quality["exclusion_reasons"] + (["interior_long_gap"] if interior_long else [])})
            om = await self._fetch_open_meteo(target_date, power_state)
            record.update({
                f"open_meteo_{key_name}": value
                for key_name, value in om.items()
                if key_name != "fetched_at"
            })
            forecast_item = await self._forecast_baseline_record(site_id, key)
            baseline = self._usable_forecast_baseline(forecast_item, start)
            record["forecast_solar_frozen_kwh"] = baseline
            if baseline is not None and actual is not None:
                record["common_forecast_solar_day"] = True
            fs_fingerprint = await self._persist_forecast_provenance(
                site_id, key, provenance_store, provenance_cached, forecast_item, baseline, start
            )
            om_fingerprint = await self._persist_open_meteo_provenance(
                site_id, key, provenance_store, provenance_cached, om, start
            )
            await self._persist_provenance_link(site_id, key, fs_fingerprint, om_fingerprint, start)
            return await self._save_target_day(site_id, store, days, key, record)

    async def _fetch_open_meteo(self, target_date: date, power_state: dict[str, Any]) -> dict[str, Any]:
        installation = build_installation(self.hass, power_state)
        if not installation:
            return {"status": "installation_inputs_missing", "values": 0, "missing": 24, "fetched_at": None}
        params = {"latitude": str(installation["latitude"]), "longitude": str(installation["longitude"]), "start_date": target_date.isoformat(), "end_date": target_date.isoformat(), "hourly": "global_tilted_irradiance_previous_day1", "models": "metno_seamless", "tilt": str(PANEL_TILT), "azimuth": str(OPEN_METEO_AZIMUTH), "timezone": "Europe/Stockholm"}
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(OPEN_METEO_ENDPOINT, params=params, timeout=30) as response:
                if response.status != 200:
                    return {"status": f"http_{response.status}", "values": 0, "missing": 24, "fetched_at": None}
                fetched_at = dt_util.now().astimezone(timezone.utc)
                result = parse_previous_runs(await response.json(), target_date.isoformat())
                result["fetched_at"] = fetched_at.isoformat()
                return result
        except Exception:
            return {"status": "request_failed", "values": 0, "missing": 24, "fetched_at": None}

    async def _forecast_baseline_record(self, site_id: str, key: str) -> dict[str, Any] | None:
        reader = getattr(self.forecast_manager, "async_site_baseline_record", None)
        if callable(reader):
            item = await reader(site_id, key)
        else:
            baselines = getattr(self.forecast_manager, "_baselines", {})
            item = baselines.get(key) if isinstance(baselines, dict) else None
        return dict(item) if isinstance(item, dict) else None

    @staticmethod
    def _usable_forecast_baseline(item: dict[str, Any] | None, start: datetime) -> float | None:
        if not isinstance(item, dict) or item.get("capture_type") != "day_ahead":
            return None
        captured = dt_util.parse_datetime(item.get("captured_at"))
        value = _number(item.get("forecast_kwh"))
        return value if captured and captured < start and value is not None else None

    async def _persist_forecast_provenance(
        self, site_id, key, store, cached, item, baseline, decision_at
    ) -> str | None:
        if baseline is None or not isinstance(item, dict):
            return None
        captured = dt_util.parse_datetime(item.get("captured_at"))
        if captured is None:
            return None
        _latest_store, latest = await async_load_site_store(
            self.hass, PROVENANCE_STORE_KEY, PROVENANCE_STORE_VERSION, site_id
        )
        observations = {
            str(target): dict(sources)
            for target, sources in ((latest or {}).get("observations", {}) or {}).items()
            if isinstance(sources, dict)
        }
        source_records = list(observations.get(key, {}).get("forecast_solar", []))
        source_record = build_provenance_record(
                site_id=site_id,
                source="forecast_solar",
                dataset=FORECAST_SOLAR_DATASET,
                target=f"local_day:{key}",
                value=baseline,
                unit="kWh",
                captured_at=captured,
                known_at=captured,
                source_generation_id=item.get("source_generation_id"),
                valid_from=decision_at.isoformat(),
                valid_to=None,
                payload={"capture_type": item.get("capture_type"), "source": item.get("source")},
            )
        append_immutable(source_records, source_record)
        source_records = source_records[-32:]
        observations.setdefault(key, {})["forecast_solar"] = source_records
        await store.async_save({"schema": "solar_evidence.provenance.v1", "observations": observations})
        return source_record["frame_fingerprint"]

    async def _persist_open_meteo_provenance(
        self, site_id, key, store, cached, result, decision_at
    ) -> str | None:
        if not isinstance(result, dict) or result.get("status") != "complete":
            return None
        fetched_raw = result.get("fetched_at")
        fetched_at = dt_util.parse_datetime(fetched_raw)
        value = _number(result.get("nominal_kwh"))
        if fetched_at is None or value is None:
            return None
        _latest_store, latest = await async_load_site_store(
            self.hass, PROVENANCE_STORE_KEY, PROVENANCE_STORE_VERSION, site_id
        )
        observations = {
            str(target): dict(sources)
            for target, sources in ((latest or {}).get("observations", {}) or {}).items()
            if isinstance(sources, dict)
        }
        source_records = list(observations.get(key, {}).get("open_meteo", []))
        source_record = build_provenance_record(
                site_id=site_id,
                source="open_meteo",
                dataset=OPEN_METEO_EVIDENCE_DATASET,
                target=f"local_day:{key}",
                value=value,
                unit="kWh",
                captured_at=fetched_at,
                known_at=fetched_at,
                fetched_at=fetched_at,
                source_generation_id=None,
                valid_from=decision_at.isoformat(),
                valid_to=None,
                payload={"previous_day1": True, "status": result.get("status")},
            )
        append_immutable(source_records, source_record)
        observations.setdefault(key, {})["open_meteo"] = source_records[-32:]
        await store.async_save({"schema": "solar_evidence.provenance.v1", "observations": observations})
        return source_record["frame_fingerprint"]

    async def _persist_provenance_link(self, site_id, key, fs_fingerprint, om_fingerprint, decision_at) -> None:
        if not fs_fingerprint and not om_fingerprint:
            return
        store, cached = await async_load_site_store(
            self.hass, PROVENANCE_STORE_KEY, PROVENANCE_STORE_VERSION, site_id
        )
        links = dict((cached or {}).get("links", {}) or {})
        links[key] = {
            "forecast_solar_frame_fingerprint": fs_fingerprint,
            "open_meteo_frame_fingerprint": om_fingerprint,
            "decision_at": decision_at.isoformat(),
        }
        observations = dict((cached or {}).get("observations", {}) or {})
        await store.async_save({"schema": "solar_evidence.provenance.v1", "observations": observations, "links": links})

    async def _frozen_forecast_baseline(self, site_id: str, key: str, start: datetime) -> float | None:
        return self._usable_forecast_baseline(await self._forecast_baseline_record(site_id, key), start)

    async def _save_target_day(
        self,
        site_id: str | None,
        store,
        days: dict[str, dict[str, Any]],
        key: str,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        old = days.get(key, {})
        quality_recovery = bool(record.pop("_quality_recovery", False))
        merged = {**old, **record}
        re_evaluated = (
            record.get("audit_semantics_version") == AUDIT_SEMANTICS_VERSION
            and (old.get("audit_semantics_version") != AUDIT_SEMANTICS_VERSION or quality_recovery)
        )
        if re_evaluated and old.get("collected_at") is not None:
            merged.setdefault("first_collected_at", old["collected_at"])
        for field in ("actual_kwh", "forecast_solar_frozen_kwh", "collected_at"):
            if old.get(field) is not None and not (field == "collected_at" and re_evaluated):
                merged[field] = old[field]
        old_comparison = old.get("historical_comparison_evidence")
        if isinstance(old_comparison, dict) and old_comparison.get("version") == COMPARISON_EVIDENCE_VERSION:
            merged["historical_comparison_evidence"] = deepcopy(old_comparison)
        else:
            merged["historical_comparison_evidence"] = build_historical_comparison_evidence(
                merged,
                site_id=site_id,
                target_date=key,
            )
        days[key] = merged
        await store.async_save({"protocol_version": PROTOCOL_VERSION, "days": days})
        if site_id == self._site_id:
            self._days = {day: dict(value) for day, value in days.items()}
            self.store = store
            self.hass.bus.async_fire("elrakning_solar_evidence_update")
        return merged


    async def _save_day(self, key: str, record: dict[str, Any]) -> dict[str, Any]:
        return await self._save_target_day(self._site_id, self.store, self._days, key, record)

    def public_state(self) -> dict[str, Any]:
        days = []
        for key in sorted(self._days):
            day = dict(self._days[key])
            comparison = day.get("historical_comparison_evidence")
            if not isinstance(comparison, dict) or comparison.get("version") != COMPARISON_EVIDENCE_VERSION:
                comparison = build_historical_comparison_evidence(day, site_id=self._site_id, target_date=key)
            day["historical_comparison_evidence"] = comparison
            day["common_forecast_solar_day"] = (
                comparison.get("forecast_solar_common_eligible") is True
            )
            days.append(day)
        dated_days = []
        for item in days:
            try:
                dated_days.append((date.fromisoformat(str(item.get("date"))), item))
            except (TypeError, ValueError):
                continue
        comparison_end = max((item_date for item_date, _item in dated_days), default=None)
        open_meteo_start = comparison_end - timedelta(days=20) if comparison_end else None
        forecast_solar_start = comparison_end - timedelta(days=13) if comparison_end else None
        om_complete = sum(
            1 for item_date, item in dated_days
            if open_meteo_start is not None
            and open_meteo_start <= item_date <= comparison_end
            and item.get("historical_comparison_evidence", {}).get("open_meteo_eligible") is True
        )
        common = sum(
            1 for item_date, item in dated_days
            if forecast_solar_start is not None
            and forecast_solar_start <= item_date <= comparison_end
            if item.get("historical_comparison_evidence", {}).get("forecast_solar_common_eligible") is True
        )
        return {"available": True, "protocol_version": PROTOCOL_VERSION, "days": days, "progress": {"open_meteo_complete": om_complete, "forecast_solar_common": common, "open_meteo_target": 21, "forecast_solar_target": 14, "open_meteo_window_start": open_meteo_start.isoformat() if open_meteo_start else None, "forecast_solar_window_start": forecast_solar_start.isoformat() if forecast_solar_start else None, "comparison_window_end": comparison_end.isoformat() if comparison_end else None}, "capture_tasks": {source: dict(status) for source, status in self._capture_tasks.items()}, "quality_recovery": deepcopy(self._quality_recovery_status), "status": "SUFFICIENT FOR BOUNDED MODEL EXPERIMENT" if om_complete >= 21 and common >= 14 else "INSUFFICIENT – KEEP COLLECTING"}
