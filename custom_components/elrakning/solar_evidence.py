"""Read-only, frozen evidence collection for solar forecast comparison."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store

from .site_context import async_load_site_store
from homeassistant.util import dt as dt_util

from .solar_pvgis import build_installation


STORE_KEY = "elrakning.solar_evidence"
PROTOCOL_VERSION = "evidence-v1"
OPEN_METEO_ENDPOINT = "https://previous-runs-api.open-meteo.com/v1/forecast"
ACTIVE_THRESHOLD_KW = 0.05
MAX_INTERNAL_GAP_MINUTES = 30
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


class SolarEvidenceManager:
    """Collect frozen evidence without feeding any candidate/model path."""

    def __init__(self, hass, power_manager, forecast_manager, collection_site_configs_getter=None) -> None:
        self.hass = hass
        self.power_manager = power_manager
        self.forecast_manager = forecast_manager
        self._collection_site_configs_getter = collection_site_configs_getter
        self._collection_lock = asyncio.Lock()
        self.store = Store(hass, 1, STORE_KEY)
        self._days: dict[str, dict[str, Any]] = {}
        self._task = None
        self._unsub = None
        self._site_id: str | None = None
        self._site_context_enabled = False

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
                return
            self.store, cached = await async_load_site_store(self.hass, STORE_KEY, 1, self._site_id)
            self._days = {}
            if cached and isinstance(cached.get("days"), dict):
                self._days = {
                    key: value for key, value in cached["days"].items()
                    if isinstance(key, str) and isinstance(value, dict)
                }
                for day in self._days.values():
                    day.setdefault("site_id", self._site_id)

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
        try:
            await self.async_collect_completed_day_for_targets(
                dt_util.as_local(dt_util.now()).date() - timedelta(days=1)
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def async_backfill(self, days: int = 30) -> None:
        try:
            today = dt_util.as_local(dt_util.now()).date()
            for offset in range(1, days + 1):
                try:
                    await self.async_collect_completed_day_for_targets(today - timedelta(days=offset))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    continue
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def async_startup_catch_up(self) -> None:
        """Finalize yesterday through the same site-explicit evidence path as 00:05."""
        yesterday = dt_util.as_local(dt_util.now()).date() - timedelta(days=1)
        try:
            await self.async_collect_completed_day_for_targets(yesterday)
        except asyncio.CancelledError:
            raise
        except Exception:
            return

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
            days = {
                key: dict(value)
                for key, value in ((cached or {}).get("days", {}) or {}).items()
                if isinstance(key, str) and isinstance(value, dict)
            }
            key = target_date.isoformat()
            existing = days.get(key)
            if (isinstance(existing, dict) and existing.get("audit_complete") is True
                    and existing.get("open_meteo_status") == "complete"
                    and "forecast_solar_frozen_kwh" in existing):
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
            unavailable = 0
            for entity in entities:
                unavailable += sum(1 for state in history_by_entity.get(entity, []) if str(getattr(state, "state", "")).lower() in {"unknown", "unavailable"})
                points = [point for state in history_by_entity.get(entity, []) if (point := _state_point(state))]
                entity_starts.append(bool(points and abs((dt_util.parse_datetime(points[0]["timestamp"]) - start).total_seconds()) <= 2))
            actual, boundary_long, interior_long = integrate_actual(merged, start, end)
            quality = assess_completeness(merged, entity_starts, start, end)
            if unavailable:
                quality["exclusion_reasons"].append("unavailable_or_unknown")
            if actual is None:
                quality["exclusion_reasons"].append("actual_unavailable")
            record.update({"actual_kwh": actual, "merged_points": quality["merged_points"], "active_points": quality["active_points"], "max_internal_gap_minutes": quality["max_internal_gap_minutes"], "interior_long_gap_count": interior_long, "boundary_long_gap_count": boundary_long, "unavailable_or_unknown": unavailable, "start_state_available": all(entity_starts), "audit_complete": quality["audit_complete"] and interior_long == 0 and unavailable == 0 and actual is not None, "exclusion_reasons": quality["exclusion_reasons"] + (["interior_long_gap"] if interior_long else [])})
            om = await self._fetch_open_meteo(target_date, power_state)
            record.update({f"open_meteo_{key_name}": value for key_name, value in om.items()})
            baseline = await self._frozen_forecast_baseline(site_id, key, start)
            record["forecast_solar_frozen_kwh"] = baseline
            if baseline is not None and actual is not None:
                record["common_forecast_solar_day"] = True
            return await self._save_target_day(site_id, store, days, key, record)

    async def _fetch_open_meteo(self, target_date: date, power_state: dict[str, Any]) -> dict[str, Any]:
        installation = build_installation(self.hass, power_state)
        if not installation:
            return {"status": "installation_inputs_missing", "values": 0, "missing": 24}
        params = {"latitude": str(installation["latitude"]), "longitude": str(installation["longitude"]), "start_date": target_date.isoformat(), "end_date": target_date.isoformat(), "hourly": "global_tilted_irradiance_previous_day1", "models": "metno_seamless", "tilt": str(PANEL_TILT), "azimuth": str(OPEN_METEO_AZIMUTH), "timezone": "Europe/Stockholm"}
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(OPEN_METEO_ENDPOINT, params=params, timeout=30) as response:
                if response.status != 200:
                    return {"status": f"http_{response.status}", "values": 0, "missing": 24}
                return parse_previous_runs(await response.json(), target_date.isoformat())
        except Exception:
            return {"status": "request_failed", "values": 0, "missing": 24}

    async def _frozen_forecast_baseline(self, site_id: str, key: str, start: datetime) -> float | None:
        reader = getattr(self.forecast_manager, "async_site_baseline_record", None)
        if callable(reader):
            item = await reader(site_id, key)
        else:
            baselines = getattr(self.forecast_manager, "_baselines", {})
            item = baselines.get(key) if isinstance(baselines, dict) else None
        if not isinstance(item, dict) or item.get("capture_type") != "day_ahead":
            return None
        captured = dt_util.parse_datetime(item.get("captured_at"))
        return _number(item.get("forecast_kwh")) if captured and captured < start else None

    async def _save_target_day(
        self,
        site_id: str | None,
        store,
        days: dict[str, dict[str, Any]],
        key: str,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        old = days.get(key, {})
        merged = {**old, **record}
        for field in ("actual_kwh", "forecast_solar_frozen_kwh"):
            if old.get(field) is not None:
                merged[field] = old[field]
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
            day["common_forecast_solar_day"] = (
                day.get("audit_complete") is True
                and day.get("open_meteo_status") == "complete"
                and day.get("forecast_solar_frozen_kwh") is not None
            )
            days.append(day)
        om_complete = sum(1 for item in days if item.get("audit_complete") and item.get("open_meteo_status") == "complete")
        common = sum(
            1 for item in days
            if item.get("audit_complete") is True
            and item.get("open_meteo_status") == "complete"
            and item.get("forecast_solar_frozen_kwh") is not None
        )
        return {"available": True, "protocol_version": PROTOCOL_VERSION, "days": days, "progress": {"open_meteo_complete": om_complete, "forecast_solar_common": common, "open_meteo_target": 21, "forecast_solar_target": 14}, "status": "SUFFICIENT FOR BOUNDED MODEL EXPERIMENT" if om_complete >= 21 and common >= 14 else "INSUFFICIENT – KEEP COLLECTING"}
