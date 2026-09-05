"""Event-driven site-independent collector for the P0 canonical dataset."""

from __future__ import annotations

import asyncio
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from homeassistant.core import EVENT_STATE_CHANGED, Event, callback
try:
    from homeassistant.core import EVENT_STATE_REPORTED
except ImportError:
    EVENT_STATE_REPORTED = "state_reported"
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .canonical_storage import CanonicalStorage, quarter_start
from .meter import _power_kw


POWER_ROLES = {
    "house.consumption": ("W", "positive_consumption"),
    "solar.production": ("W", "positive_production"),
    "grid.power/import": ("W", "positive_import_negative_export"),
    "battery.power": ("W", "positive_discharge_negative_charge"),
}


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
            lambda: {"samples": [], "invalid": False}
        )
        self._recent_reported: dict[str, tuple[tuple[str, str, str], datetime]] = {}
        self._finalized_intervals: set[datetime] = set()
        self._flush_lock = asyncio.Lock()
        self._started = False

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
        self._quarter_unsub = async_track_time_change(
            self.hass,
            self._async_close_previous_quarter,
            minute=[0, 15, 30, 45],
            second=5,
        )
        self._started = True

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
        self._buffers.clear()
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
            buffer = self._buffers[(target["site_id"], role, target["generation_id"], interval)]
            buffer.setdefault("target", target)
            if value is None:
                buffer["invalid"] = True
                continue
            buffer["samples"].append((observed_at, value))

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
            and semantics.get("unit") in {"W", "%"}
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
                value, coverage, observed_at = self._aggregate(
                    semantics["aggregation"], samples, interval,
                    semantics.get("max_hold_seconds"),
                )
                if value is None:
                    quality_status = "invalid" if buffer["invalid"] else "unknown"
                    gap_status = "unavailable" if buffer["invalid"] else "gap"
                elif semantics["aggregation"] == "last_valid" and coverage < 1:
                    quality_status, gap_status = "stale", "stale"
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
    def _aggregate(
        aggregation: str,
        samples: list[tuple[datetime, float]],
        interval: datetime,
        max_hold_seconds: float | None = None,
    ):
        if not samples:
            return None, 0.0, None
        if aggregation == "last_valid":
            observed_at, value = samples[-1]
            interval_end = interval + timedelta(seconds=900)
            age = (interval_end - observed_at).total_seconds()
            return value, 1.0 if max_hold_seconds is not None and age <= max_hold_seconds else 0.0, observed_at
        start = interval
        end = interval + timedelta(seconds=900)
        total = 0.0
        covered = 0.0
        for (left_time, left_value), (right_time, _right_value) in zip(samples, samples[1:]):
            segment_start = max(left_time, start)
            segment_end = min(right_time, end)
            if segment_end > segment_start:
                total += left_value * (segment_end - segment_start).total_seconds()
                covered += (segment_end - segment_start).total_seconds()
        if covered <= 0:
            return None, 0.0, samples[-1][0]
        return total / covered, covered / 900, samples[-1][0]

    def _build_observation(self, target, interval, value, coverage, observed_at, captured_at, quality_status, gap_status):
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
            "quality": {"coverage_ratio": coverage, "invalid_event": quality_status == "invalid"},
            "provenance": {
                "origin_type": "ha_state_event",
                "entity_id": target["entity_id"],
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
