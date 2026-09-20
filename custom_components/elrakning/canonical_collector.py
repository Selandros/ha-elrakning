"""Event-driven site-independent collector for the P0 canonical dataset."""

from __future__ import annotations

import asyncio
import copy
import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from homeassistant.core import EVENT_STATE_CHANGED, Event, callback
from homeassistant.components import weather
try:
    from homeassistant.core import EVENT_STATE_REPORTED
except ImportError:
    EVENT_STATE_REPORTED = "state_reported"
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .canonical_storage import CanonicalStorage, quarter_start
from .external_input_frames import (
    build_forecast_solar_frames,
    build_open_meteo_frame,
    persist_forecast_solar_frames,
    persist_open_meteo_frames,
    persist_nord_pool_frame,
    build_smhi_current_frame,
    build_smhi_hourly_frame,
    persist_smhi_frames,
)
from .meter import _power_kw
from .solar_open_meteo import (
    async_fetch_open_meteo_target,
    build_open_meteo_targets,
    normalize_open_meteo_payload,
)
from .solar_single_run import (
    DATASET as SINGLE_RUN_DATASET,
    async_fetch_single_run_target,
    build_single_run_targets,
    candidate_run_times,
    decision_at_for_target,
)
from .solar_weather import build_weather_targets, normalize_current_weather, normalize_hourly_forecast


POWER_ROLES = {
    "house.consumption": ("W", "positive_consumption"),
    "solar.production": ("W", "positive_production"),
    "grid.power/import": ("W", "positive_import_negative_export"),
    "battery.power": ("W", "positive_discharge_negative_charge"),
    "battery.charge": ("W", "positive_charge"),
    "battery.discharge": ("W", "positive_discharge"),
}
ENERGY_ROLES = {"grid.energy_import", "grid.energy_export", "battery.capacity"}
# A bounded hold covers the observed five-minute reporting cadence without
# allowing a silent source to appear healthy indefinitely.
DEFAULT_TIME_WEIGHTED_HOLD_SECONDS = 360.0
_LOGGER = logging.getLogger(__name__)


class CanonicalCollector:
    """Collect future source events without using active UI site context."""

    def __init__(self, hass, site_identity_manager, storage_path: str | Path | None = None) -> None:
        self.hass = hass
        self.site_identity_manager = site_identity_manager
        path = storage_path or hass.config.path("elrakning", "canonical.sqlite")
        self.storage = CanonicalStorage(path)
        self._state_unsub = None
        self._reported_unsub = None
        self._quarter_unsub = None
        self._buffers: dict[tuple[str, str, str, datetime], dict[str, Any]] = defaultdict(
            lambda: {"samples": [], "invalid": False, "invalid_boundaries": []}
        )
        self._carry_samples: dict[tuple[str, str, str], tuple[datetime, float]] = {}
        self._recent_reported: dict[str, tuple[tuple[str, str, str], datetime]] = {}
        self._finalized_intervals: set[datetime] = set()
        self._flush_lock = asyncio.Lock()
        self._started = False
        self._forecast_capture_status: dict[str, Any] | None = None
        self._open_meteo_capture_status: dict[str, Any] | None = None
        self._open_meteo_lock = asyncio.Lock()
        self._open_meteo_unsub = None
        self._single_run_lock = asyncio.Lock()
        self._single_run_capture_status: dict[str, Any] | None = None
        self._weather_unsub = None
        self._weather_capture_lock = asyncio.Lock()
        self._weather_capture_status: dict[str, Any] | None = None

    async def async_persist_nord_pool_frame(self, data, binding, captured_at) -> bool:
        """Persist one global price frame without changing collection context."""
        async with self._flush_lock:
            return await self.hass.async_add_executor_job(
                persist_nord_pool_frame, self.storage, data, binding, captured_at
            )

    def forecast_capture_status(self) -> dict[str, Any] | None:
        """Return the latest in-memory Forecast.Solar capture diagnostics."""
        return copy.deepcopy(self._forecast_capture_status)

    def open_meteo_capture_status(self) -> dict[str, Any] | None:
        """Return the latest in-memory Open-Meteo capture diagnostics."""
        return copy.deepcopy(self._open_meteo_capture_status)

    def single_run_capture_status(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._single_run_capture_status)

    def _single_run_targets(self) -> list[dict[str, Any]]:
        getter = getattr(self.site_identity_manager, "collection_site_configs", None)
        return build_single_run_targets(getter() if getter else {})

    async def async_capture_single_run_day_ahead(self, *, trigger: str = "startup") -> dict[str, Any]:
        """Capture available causal Open-Meteo run vintages site-independently."""
        async with self._single_run_lock:
            now = dt_util.now().astimezone(timezone.utc)
            targets = self._single_run_targets()
            result = {"trigger": trigger, "target_count": len(targets), "target_site_ids": sorted({item["site_id"] for item in targets}), "sections": {}, "last_error": None}
            frames = []
            for target in targets:
                target_date = dt_util.as_local(now).date() + timedelta(days=1)
                decision_at = decision_at_for_target(target_date, target["timezone"])
                key = f"{target['site_id']}:{target['single_run_request_fingerprint']}:{target_date.isoformat()}"
                section = {"status": "missing", "written": 0, "revised": 0, "deduplicated": 0}
                result["sections"][key] = section
                if now >= decision_at:
                    section["status"] = "post_decision_window"
                    continue
                for run_time in candidate_run_times(now, decision_at):
                    try:
                        normalized, received_at = await async_fetch_single_run_target(self.hass, target, target_date, run_time)
                        capture_target = dict(target)
                        capture_target.update({
                            "dataset": SINGLE_RUN_DATASET,
                            "decision_at": decision_at,
                            "semantic_run_identity": normalized["run_initialization_at"],
                            "section_request_fingerprint": target["single_run_request_fingerprint"],
                            "payload_schema": "open_meteo.single_run_day_ahead_pv.v1",
                        })
                        frame_pair = build_open_meteo_frame(capture_target, normalized, received_at, received_at, received_at)
                        frames.append((key, frame_pair))
                        section["status"] = "fetched"
                        break
                    except Exception as error:
                        section["last_error"] = type(error).__name__
                if section["status"] == "missing":
                    result["last_error"] = section.get("last_error", "run_unavailable")
            if frames:
                try:
                    async with self._flush_lock:
                        persisted = await self.hass.async_add_executor_job(
                            persist_open_meteo_frames, self.storage, [pair for _key, pair in frames], now
                        )
                    for key, (frame, _points) in frames:
                        item = result["sections"][key]
                        frame_result = persisted.get("frames", {}).get(frame["semantic_key"], persisted)
                        item["written"] = int(frame_result.get("written", 0))
                        item["revised"] = int(frame_result.get("revised", 0))
                        item["deduplicated"] = int(frame_result.get("unchanged", 0))
                        item["status"] = "success" if item["written"] or item["revised"] else "deduplicated"
                except Exception as error:
                    result["last_error"] = str(error)
                    for key, _pair in frames:
                        result["sections"][key]["status"] = "error"
            result["status"] = "success" if frames and not result["last_error"] else "partial_failure" if frames else "no_eligible_run"
            self._single_run_capture_status = copy.deepcopy(result)
            return result

    def weather_capture_status(self) -> dict[str, Any] | None:
        """Return the latest in-memory SMHI canonical capture diagnostics."""
        return copy.deepcopy(self._weather_capture_status)

    def _weather_targets(self) -> list[dict[str, Any]]:
        getter = getattr(self.site_identity_manager, "collection_site_configs", None)
        return build_weather_targets(getter() if getter else {})

    async def async_capture_weather(self, *, trigger: str = "startup") -> dict[str, Any]:
        """Capture site-explicit SMHI current and hourly frames."""
        async with self._weather_capture_lock:
            started_at = dt_util.now().astimezone(timezone.utc)
            targets = self._weather_targets()
            result = {
                "started_at": started_at.isoformat(), "finished_at": None, "trigger": trigger,
                "target_count": len(targets), "target_site_ids": [target["site_id"] for target in targets],
                "current": {"attempted": 0, "written": 0, "deduplicated": 0, "revised": 0, "failed": 0},
                "hourly": {"attempted": 0, "service_calls": 0, "written": 0, "deduplicated": 0, "revised": 0, "failed": 0, "valid_points": 0, "rejected_points": 0},
                "sites": {}, "last_error": None,
            }
            frames = []
            for target in targets:
                site_id = target["site_id"]
                site_result = {"current": "unattempted", "hourly": "unattempted", "service_calls": 0, "valid_points": 0, "rejected_points": 0}
                result["sites"][site_id] = site_result
                result["current"]["attempted"] += 1
                state = self.hass.states.get(target["weather_entity"])
                sensors = {role: self.hass.states.get(entity_id) for role, entity_id in target["sensor_entities"].items()}
                current = normalize_current_weather(state, sensors)
                if current is None:
                    site_result["current"] = "failed"
                    result["current"]["failed"] += 1
                else:
                    current_captured_at = dt_util.now().astimezone(timezone.utc)
                    frames.append(build_smhi_current_frame(target, current, current_captured_at))
                    site_result["current"] = "ready"
                result["hourly"]["attempted"] += 1
                result["hourly"]["service_calls"] += 1
                site_result["service_calls"] = 1
                try:
                    response = await self.hass.services.async_call(
                        weather.DOMAIN, weather.SERVICE_GET_FORECASTS,
                        {"entity_id": target["weather_entity"], "type": "hourly"},
                        blocking=True, return_response=True,
                    )
                    fetched_at = dt_util.now().astimezone(timezone.utc)
                    entity_response = response.get(target["weather_entity"], response) if isinstance(response, dict) else {}
                    normalized = normalize_hourly_forecast(entity_response)
                    if normalized is None:
                        raise ValueError("invalid_response")
                    captured_at = dt_util.now().astimezone(timezone.utc)
                    hourly_frame = build_smhi_hourly_frame(target, normalized, fetched_at, captured_at, captured_at)
                    frames.append(hourly_frame)
                    valid_points = len(normalized["points"])
                    rejected = int(normalized.get("rejected_points", 0))
                    result["hourly"]["valid_points"] += valid_points
                    result["hourly"]["rejected_points"] += rejected
                    site_result.update({"hourly": "ready", "valid_points": valid_points, "rejected_points": rejected})
                except Exception as error:
                    result["hourly"]["failed"] += 1
                    site_result["hourly"] = "failed"
                    result["last_error"] = str(error)
            current_frames = [frame for frame in frames if frame[0]["logical_role"] == "weather.current_conditions"]
            hourly_frames = [frame for frame in frames if frame[0]["logical_role"] == "weather.forecast.hourly"]
            for key, frame_group in (("current", current_frames), ("hourly", hourly_frames)):
                if not frame_group:
                    continue
                try:
                    async with self._flush_lock:
                        persisted = await self.hass.async_add_executor_job(
                            persist_smhi_frames, self.storage, frame_group, started_at
                        )
                    result[key]["written"] = int(persisted.get("written", 0))
                    result[key]["revised"] = int(persisted.get("revised", 0))
                    result[key]["deduplicated"] = int(persisted.get("unchanged", 0))
                except Exception as error:
                    result["last_error"] = str(error)
                    result[key]["failed"] += 1
            result["finished_at"] = dt_util.now().astimezone(timezone.utc).isoformat()
            result["status"] = "no_targets" if not targets else "error" if result["last_error"] else "success"
            self._weather_capture_status = result
            return copy.deepcopy(result)

    async def _async_weather_cadence(self, _now) -> None:
        """Run the hourly canonical weather capture."""
        await self.async_capture_weather(trigger="hourly_cadence")

    def _open_meteo_targets(self) -> list[dict[str, Any]]:
        getter = getattr(self.site_identity_manager, "collection_site_configs", None)
        return build_open_meteo_targets(getter() if getter else {})

    async def async_capture_open_meteo(self, *, trigger: str = "startup") -> dict[str, Any]:
        """Capture immutable Open-Meteo frames without active-site context."""
        async with self._open_meteo_lock:
            started_at = dt_util.now().astimezone(timezone.utc)
            targets = self._open_meteo_targets()
            result = {
                "started_at": started_at.isoformat(),
                "finished_at": None,
                "trigger": trigger,
                "target_count": len(targets),
                "target_site_ids": sorted({target["site_id"] for target in targets}),
                "sections": {},
                "last_error": None,
            }
            candidates = []
            for target in targets:
                key = f"{target['site_id']}:{target['section_request_fingerprint']}"
                try:
                    payload, fetched_at = await async_fetch_open_meteo_target(self.hass, target)
                    normalized = normalize_open_meteo_payload(payload, target)
                    if normalized is None:
                        raise ValueError("invalid_response")
                    normalized_at = dt_util.now().astimezone(timezone.utc)
                    candidates.append((target, normalized, fetched_at, normalized_at))
                    result["sections"][key] = {"status": "fetched", "written": 0, "revised": 0, "deduplicated": 0}
                except Exception as error:
                    result["sections"][key] = {
                        "status": "error",
                        "written": 0,
                        "revised": 0,
                        "deduplicated": 0,
                        "error_type": type(error).__name__,
                        "error_message": str(error),
                    }
                    result["last_error"] = str(error)
            current = {
                (target["site_id"], target["section_request_fingerprint"]): target
                for target in self._open_meteo_targets()
            }
            frames = []
            for target, normalized, fetched_at, normalized_at in candidates:
                if current.get((target["site_id"], target["section_request_fingerprint"])) != target:
                    key = f"{target['site_id']}:{target['section_request_fingerprint']}"
                    result["sections"][key]["status"] = "stale_target"
                    continue
                frames.append(build_open_meteo_frame(target, normalized, fetched_at, normalized_at, normalized_at))
            if frames:
                try:
                    async with self._flush_lock:
                        persisted = await self.hass.async_add_executor_job(
                            persist_open_meteo_frames, self.storage, frames, started_at
                        )
                    for frame, _points in frames:
                        key = f"{frame['site_id']}:{frame['provenance']['section_request_fingerprint']}"
                        item = result["sections"][key]
                        frame_result = persisted.get("frames", {}).get(frame["semantic_key"], persisted)
                        item["written"] = int(frame_result.get("written", 0))
                        item["revised"] = int(frame_result.get("revised", 0))
                        item["deduplicated"] = int(frame_result.get("unchanged", 0))
                        item["status"] = "success" if item["written"] or item["revised"] else "deduplicated"
                except Exception as error:
                    result["last_error"] = str(error)
                    for frame, _points in frames:
                        key = f"{frame['site_id']}:{frame['provenance']['section_request_fingerprint']}"
                        result["sections"][key].update({
                            "status": "error",
                            "error_type": type(error).__name__,
                            "error_message": str(error),
                        })
            result["finished_at"] = dt_util.now().astimezone(timezone.utc).isoformat()
            successful = any(
                section.get("status") in {"success", "deduplicated"}
                for section in result["sections"].values()
            )
            result["status"] = (
                "no_targets" if not targets
                else "error" if result["last_error"] and not successful
                else "partial_failure" if result["last_error"]
                else "success"
            )
            self._open_meteo_capture_status = result
            return copy.deepcopy(result)

    async def _async_open_meteo_cadence(self, _now) -> None:
        """Run the hourly capture as a real Home Assistant coroutine job."""
        await self.async_capture_open_meteo(trigger="hourly_cadence")
        await self.async_capture_single_run_day_ahead(trigger="hourly_cadence")

    async def async_capture_forecast_solar(
        self,
        captured_at: datetime | None = None,
        *,
        trigger: str = "startup",
        entity_id: str | None = None,
    ) -> dict[str, Any]:
        """Serialize Forecast.Solar capture with all canonical storage writes."""
        async with self._flush_lock:
            return await self._async_capture_forecast_solar(
                captured_at,
                trigger=trigger,
                entity_id=entity_id,
            )

    async def _async_capture_forecast_solar(
        self,
        captured_at: datetime | None = None,
        *,
        trigger: str = "startup",
        entity_id: str | None = None,
    ) -> dict[str, Any]:
        """Capture all enabled Forecast.Solar site bindings without UI context."""
        started_at = dt_util.now().astimezone(timezone.utc)
        captured_at = (captured_at or dt_util.now()).astimezone(timezone.utc)
        target_getter = getattr(self.site_identity_manager, "forecast_collection_targets", None)
        targets = target_getter() if target_getter else []
        result: dict[str, Any] = {
            "started_at": started_at.isoformat(),
            "finished_at": None,
            "last_attempt_at": started_at.isoformat(),
            "last_success_at": None,
            "trigger": trigger,
            "entity_id": entity_id,
            "target_count": len(targets),
            "target_site_ids": [target.get("site_id") for target in targets],
            "sites": {},
            "last_error": None,
        }
        for target in targets:
            site_id = target.get("site_id")
            site_result = {
                "status": "no_candidates",
                "candidates": 0,
                "written": 0,
                "deduplicated": 0,
                "revised": 0,
                "rejected": 0,
                "error_type": None,
                "error_message": None,
            }
            result["sites"][site_id] = site_result
            try:
                frames = build_forecast_solar_frames(
                    self.hass, site_id, target["binding"], captured_at
                )
            except (TypeError, ValueError) as error:
                # Unsupported or malformed source context must fail closed.
                site_result.update({
                    "status": "error",
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                })
                result["last_error"] = {
                    "site_id": site_id,
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                }
                _LOGGER.warning("Forecast.Solar capture failed for site %s: %s", site_id, error)
                continue
            if not frames:
                continue
            site_result["candidates"] = len(frames)
            try:
                persisted = await self.hass.async_add_executor_job(
                    self._persist_forecast_target,
                    site_id,
                    target["binding"],
                    frames,
                    captured_at,
                )
            except Exception as error:
                site_result.update({
                    "status": "error",
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                })
                result["last_error"] = {
                    "site_id": site_id,
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                }
                _LOGGER.warning("Forecast.Solar persistence failed for site %s: %s", site_id, error)
                continue
            site_result.update({
                "written": int(persisted.get("written", 0)),
                "deduplicated": int(persisted.get("unchanged", 0)),
                "revised": int(persisted.get("revised", 0)),
            })
            if persisted.get("status") == "stale_binding":
                site_result["status"] = "stale_binding"
            elif site_result["written"] or site_result["revised"]:
                site_result["status"] = "success"
            else:
                site_result["status"] = "deduplicated"
        result["finished_at"] = dt_util.now().astimezone(timezone.utc).isoformat()
        previous_success = (
            self._forecast_capture_status or {}
        ).get("last_success_at")
        result["last_success_at"] = (
            result["finished_at"] if not result["last_error"] else previous_success
        )
        result["status"] = (
            "no_targets" if not targets else "error" if result["last_error"] and not any(
                site.get("status") in {"success", "deduplicated", "stale_binding"}
                for site in result["sites"].values()
            ) else "partial_failure" if result["last_error"] else "success"
        )
        self._forecast_capture_status = result
        return copy.deepcopy(result)

    def _persist_forecast_target(self, site_id, binding, frames, captured_at):
        current = {
            item["site_id"]: item["binding"]
            for item in getattr(self.site_identity_manager, "forecast_collection_targets", lambda: [])()
        }.get(site_id)
        if current != binding:
            return {"status": "stale_binding", "written": 0, "unchanged": 0, "revised": 0}
        persisted = persist_forecast_solar_frames(self.storage, frames, captured_at)
        persisted["status"] = "persisted"
        return persisted

    async def _async_forecast_state_changed(self, event: Event) -> None:
        if not self._started:
            return
        entity_id = event.data.get("entity_id")
        target_getter = getattr(self.site_identity_manager, "forecast_collection_targets", None)
        targets = target_getter() if target_getter else []
        if not any(
            entity_id in (target["binding"].get("entities") or {}).values()
            for target in targets
        ):
            return
        await self.async_capture_forecast_solar(
            trigger="forecast_solar_state_changed",
            entity_id=entity_id,
        )

    async def async_start(self) -> None:
        if self._started:
            return
        await self.hass.async_add_executor_job(self.storage.open)
        self._state_unsub = self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._async_state_changed)
        self._reported_unsub = self.hass.bus.async_listen(
            EVENT_STATE_REPORTED,
            self._async_state_reported,
            event_filter=self._state_reported_filter,
        )
        self._started = True
        await self._async_close_previous_quarter(dt_util.now())
        self._quarter_unsub = async_track_time_change(
            self.hass,
            self._async_close_previous_quarter,
            minute=[0, 15, 30, 45],
            second=5,
        )
        self._open_meteo_unsub = async_track_time_change(
            self.hass,
            self._async_open_meteo_cadence,
            minute=0,
            second=12,
        )
        self._weather_unsub = async_track_time_change(
            self.hass, self._async_weather_cadence, minute=0, second=22,
        )

    async def async_shutdown(self) -> None:
        if self._state_unsub:
            self._state_unsub()
            self._state_unsub = None
        if self._reported_unsub:
            self._reported_unsub()
            self._reported_unsub = None
        if self._quarter_unsub:
            self._quarter_unsub()
            self._quarter_unsub = None
        if self._open_meteo_unsub:
            self._open_meteo_unsub()
            self._open_meteo_unsub = None
        if self._weather_unsub:
            self._weather_unsub()
            self._weather_unsub = None
        self._buffers.clear()
        self._carry_samples.clear()
        self._recent_reported.clear()
        self._finalized_intervals.clear()
        if self._started:
            await self.hass.async_add_executor_job(self.storage.close)
        self._started = False

    @callback
    def _state_reported_filter(self, event_data: dict[str, Any]) -> bool:
        """Accept reported events only for currently bound collection sources."""
        entity_id = event_data.get("entity_id")
        return any(
            target.get("entity_id") == entity_id
            and self._canonicalization_ready(target)
            for target in self.site_identity_manager.collection_targets()
        )

    async def _async_state_changed(self, event: Event) -> None:
        await self._async_observation_event(event, reported=False)
        await self._async_forecast_state_changed(event)

    async def _async_state_reported(self, event: Event) -> None:
        await self._async_observation_event(event, reported=True)

    async def _async_observation_event(self, event: Event, reported: bool) -> None:
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state") or event.data.get("state")
        if new_state is None:
            new_state = self.hass.states.get(entity_id)
        observed_at = getattr(new_state, "last_reported", None)
        if observed_at is None:
            observed_at = getattr(new_state, "last_updated", None)
        if reported:
            observed_at = getattr(event, "time_fired", None) or observed_at
        if not entity_id or observed_at is None or not self._started:
            return
        if observed_at.tzinfo is None:
            return
        observed_at = observed_at.astimezone(timezone.utc)
        signature = self._state_signature(new_state)
        if reported:
            self._recent_reported[entity_id] = (signature, observed_at)
        else:
            previous = self._recent_reported.get(entity_id)
            if previous and previous[0] == signature and quarter_start(observed_at) == quarter_start(previous[1]):
                return
        for target in self.site_identity_manager.collection_targets():
            if target.get("entity_id") != entity_id:
                continue
            if not self._canonicalization_ready(target):
                continue
            role = target["logical_role"]
            interval = quarter_start(observed_at)
            if interval in self._finalized_intervals:
                continue
            value = self._value_for_target(target, new_state)
            carry_key = (target["site_id"], role, target["generation_id"])
            buffer = self._buffers[(target["site_id"], role, target["generation_id"], interval)]
            buffer.setdefault("target", target)
            if value is None:
                buffer["invalid"] = True
                buffer.setdefault("invalid_boundaries", []).append(observed_at)
                self._carry_samples.pop(carry_key, None)
                continue
            if "predecessor" not in buffer:
                previous = self._carry_samples.get(carry_key)
                buffer["predecessor"] = previous if previous and previous[0] < interval else None
            buffer["samples"].append((observed_at, value))
            for cached_key in tuple(self._carry_samples):
                if cached_key[:2] == carry_key[:2] and cached_key[2] != carry_key[2]:
                    self._carry_samples.pop(cached_key, None)
            self._carry_samples[carry_key] = (observed_at, value)

    @staticmethod
    def _state_signature(state: Any) -> tuple[str, str, str]:
        attributes = getattr(state, "attributes", {}) or {}
        return (
            str(getattr(state, "state", "")),
            str(attributes.get("unit_of_measurement", "")),
            str(attributes.get("device_class", "")),
        )

    @staticmethod
    def _canonicalization_ready(target: dict[str, Any]) -> bool:
        semantics = target.get("canonicalization")
        return (
            isinstance(semantics, dict)
            and semantics.get("unit") in {"W", "%", "kWh"}
            and isinstance(semantics.get("sign_convention"), str)
            and semantics.get("aggregation") in {"time_weighted_mean", "last_valid"}
            and semantics.get("classification") in {"measured", "derived"}
            and (
                semantics.get("aggregation") != "last_valid"
                or isinstance(semantics.get("max_hold_seconds"), (int, float))
                and semantics["max_hold_seconds"] > 0
            )
        )

    def _interval_targets(self, interval: datetime) -> list[dict[str, Any]]:
        targets = []
        for target in self.site_identity_manager.collection_targets():
            if not self._canonicalization_ready(target):
                continue
            effective_from = target.get("effective_from")
            if isinstance(effective_from, str):
                try:
                    effective_from_dt = datetime.fromisoformat(effective_from.replace("Z", "+00:00"))
                except ValueError:
                    effective_from_dt = None
                if effective_from_dt and effective_from_dt.astimezone(timezone.utc) > interval:
                    continue
            targets.append(target)
        return targets

    def _ensure_interval_buffers(self, interval: datetime, existing_keys: set[str]) -> None:
        """Materialize explicit gap rows for eligible silent sources."""
        for target in self._interval_targets(interval):
            key = (target["site_id"], target["logical_role"], target["generation_id"], interval)
            semantic_key = f"{target['site_id']}|{target['logical_role']}|{target['generation_id']}|{interval.isoformat()}"
            if semantic_key in existing_keys:
                continue
            self._buffers[key].setdefault("target", target)

    @staticmethod
    def _value_for_target(target: dict[str, Any], state: Any) -> float | None:
        role = target.get("logical_role")
        canonicalization = target.get("canonicalization") or {}
        if role == "battery.soc":
            unit = str(getattr(state, "attributes", {}).get("unit_of_measurement", "")).lower()
            if unit not in {"%", "percent"}:
                return None
            try:
                value = float(state.state)
            except (TypeError, ValueError):
                return None
            return value if math.isfinite(value) and 0 <= value <= 100 else None
        if role in ENERGY_ROLES:
            unit = str(getattr(state, "attributes", {}).get("unit_of_measurement", "")).lower()
            try:
                value = float(state.state)
            except (TypeError, ValueError):
                return None
            if unit in {"wh", "watt-hour", "watt hours"}:
                value /= 1000
            elif unit in {"mwh", "megawatt-hour", "megawatt hours"}:
                value *= 1000
            elif unit not in {"kwh", "kilowatt-hour", "kilowatt hours"}:
                return None
            return value if math.isfinite(value) and value >= 0 else None
        if role not in POWER_ROLES:
            return None
        value = _power_kw(state)
        if value is None:
            return None
        if canonicalization.get("unit") == "W":
            value *= 1000
        mapping = target.get("mapping", {})
        invert_power = canonicalization.get("invert_power")
        if invert_power is None:
            invert_power = role == "grid.power/import" and mapping.get("invert_power") is True
        invert_battery_power = canonicalization.get("invert_battery_power")
        if invert_battery_power is None:
            invert_battery_power = role == "battery.power" and mapping.get("invert_battery_power") is True
        if invert_power:
            value = -value
        if invert_battery_power:
            value = -value
        if canonicalization.get("absolute_value", role in {"house.consumption", "solar.production"}):
            value = abs(value)
        return value if math.isfinite(value) else None

    async def _async_close_previous_quarter(self, now: datetime) -> None:
        interval = quarter_start(now.astimezone(timezone.utc)) - timedelta(seconds=900)
        await self.async_flush(interval, now.astimezone(timezone.utc))

    async def async_flush(self, interval: datetime, captured_at: datetime | None = None) -> int:
        """Persist one closed interval and remove only successfully handled buffers."""
        async with self._flush_lock:
            captured_at = captured_at or datetime.now(timezone.utc)
            interval_targets = self._interval_targets(interval)
            semantic_keys = [
                f"{target['site_id']}|{target['logical_role']}|{target['generation_id']}|{interval.isoformat()}"
                for target in interval_targets
            ]
            existing_keys = await self.hass.async_add_executor_job(
                self.storage.existing_observation_keys, semantic_keys
            )
            self._ensure_interval_buffers(interval, existing_keys)
            matching = [key for key in self._buffers if key[3] == interval]
            observations = []
            for key in matching:
                site_id, role, generation_id, _ = key
                buffer = self._buffers[key]
                samples = sorted(set(buffer["samples"]), key=lambda item: item[0])
                target = buffer.get("target")
                if target is None:
                    self._buffers.pop(key, None)
                    continue
                semantics = target["canonicalization"]
                if "predecessor" in buffer:
                    predecessor = buffer.get("predecessor")
                else:
                    # A materialized silent buffer may use the last valid sample,
                    # but an active buffer must use its frozen predecessor.
                    predecessor = self._carry_samples.get((site_id, role, generation_id))
                value, coverage, observed_at, aggregation_metadata = self._aggregate(
                    semantics["aggregation"], samples, interval,
                    self._effective_max_hold_seconds(semantics), predecessor,
                    buffer.get("invalid_boundaries", []),
                )
                if value is None:
                    quality_status = "invalid" if buffer["invalid"] else "unknown"
                    gap_status = "unavailable" if buffer["invalid"] else "gap"
                elif semantics["aggregation"] == "last_valid" and coverage < 1:
                    quality_status, gap_status = "partial", "stale"
                elif semantics["aggregation"] == "last_valid":
                    quality_status, gap_status = "good", "none"
                else:
                    quality_status = "good" if coverage >= 1 else "partial"
                    gap_status = "none" if coverage >= 1 else "gap"
                observations.append(self._build_observation(
                    target,
                    interval,
                    value,
                    coverage,
                    observed_at,
                    captured_at,
                    quality_status,
                    gap_status,
                    aggregation_metadata,
                ))
            written = await self.hass.async_add_executor_job(
                self._write_batch,
                observations,
                captured_at,
            ) if observations else 0
            for key in matching:
                self._buffers.pop(key, None)
            self._finalized_intervals.add(interval)
            return written

    @staticmethod
    def _effective_max_hold_seconds(semantics: dict[str, Any]) -> float | None:
        if semantics.get("aggregation") != "time_weighted_mean":
            return semantics.get("max_hold_seconds")
        configured = semantics.get("max_hold_seconds")
        if isinstance(configured, (int, float)) and configured > 0:
            return float(configured)
        return DEFAULT_TIME_WEIGHTED_HOLD_SECONDS

    @staticmethod
    def _aggregate(
        aggregation: str,
        samples: list[tuple[datetime, float]],
        interval: datetime,
        max_hold_seconds: float | None = None,
        predecessor: tuple[datetime, float] | None = None,
        invalid_boundaries: list[datetime] | None = None,
    ):
        if not samples and (aggregation != "time_weighted_mean" or predecessor is None):
            return None, 0.0, None, {}
        if aggregation == "last_valid":
            observed_at, value = samples[-1]
            interval_end = interval + timedelta(seconds=900)
            age = (interval_end - observed_at).total_seconds()
            return value, 1.0 if max_hold_seconds is not None and age <= max_hold_seconds else 0.0, observed_at, {}
        start = interval
        end = interval + timedelta(seconds=900)
        hold_seconds = max_hold_seconds or DEFAULT_TIME_WEIGHTED_HOLD_SECONDS
        effective_samples = list(samples)
        predecessor_used = False
        if predecessor is not None and predecessor[0] < start:
            effective_samples.insert(0, predecessor)
            predecessor_used = True
        total = 0.0
        covered = 0.0
        invalid_boundaries = sorted(invalid_boundaries or [])
        for index, (left_time, left_value) in enumerate(effective_samples):
            right_time = effective_samples[index + 1][0] if index + 1 < len(effective_samples) else end
            segment_start = max(left_time, start)
            segment_end = min(right_time, end, left_time + timedelta(seconds=hold_seconds))
            invalid_boundary = next(
                (boundary for boundary in invalid_boundaries if boundary > segment_start),
                None,
            )
            if invalid_boundary is not None:
                segment_end = min(segment_end, invalid_boundary)
            if segment_end > segment_start:
                total += left_value * (segment_end - segment_start).total_seconds()
                covered += (segment_end - segment_start).total_seconds()
        if covered <= 0:
            observed_at = samples[-1][0] if samples else predecessor[0]
            return None, 0.0, observed_at, {"boundary_carry_used": predecessor_used}
        observed_at = samples[-1][0] if samples else predecessor[0]
        coverage = min(1.0, max(0.0, covered / 900))
        return total / covered, coverage, observed_at, {
            "boundary_carry_used": predecessor_used,
            "hold_seconds": hold_seconds,
            "invalid_boundary_count": len(invalid_boundaries),
        }

    def _build_observation(self, target, interval, value, coverage, observed_at, captured_at, quality_status, gap_status, aggregation_metadata=None):
        role = target["logical_role"]
        canonicalization = target.get("canonicalization") or {}
        unit = canonicalization["unit"]
        sign = canonicalization["sign_convention"]
        semantic_key = f"{target['site_id']}|{role}|{target['generation_id']}|{interval.isoformat()}"
        return {
            "semantic_key": semantic_key,
            "site_id": target["site_id"],
            "logical_role": role,
            "source_generation_id": target["generation_id"],
            "interval_start": interval,
            "observed_at": observed_at,
            "captured_at": captured_at,
            "known_at": captured_at,
            "classification": canonicalization["classification"],
            "value": value,
            "unit": unit,
            "sign_convention": sign,
            "quality_status": quality_status,
            "coverage_ratio": coverage,
            "gap_status": gap_status,
            "quality": {
                "coverage_ratio": coverage,
                "invalid_event": quality_status == "invalid",
                **(aggregation_metadata or {}),
            },
            "provenance": {
                "origin_type": "ha_state_event",
                "entity_id": target["entity_id"],
                "resource_id": target.get("resource_id") or target["generation_id"],
                "capture_contract": (
                    "ess_telemetry.v1"
                    if role.startswith("battery.")
                    else "energy_telemetry.v1"
                ),
                "source_generation_id": target["generation_id"],
                "source_identity": target.get("source_identity", {}),
            },
        }

    def _write_batch(self, observations, captured_at):
        for observation in observations:
            self.storage.ensure_source_generation(
                {
                    "site_id": observation["site_id"],
                    "logical_role": observation["logical_role"],
                    "generation_id": observation["source_generation_id"],
                    "source_identity": observation["provenance"].get("source_identity", {}),
                },
                captured_at,
            )
        return self.storage.insert_observations_atomic(observations)
