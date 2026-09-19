"""Forecast.Solar discovery, live facts, and daily forecast baselines."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta
import re
from typing import Any

from homeassistant.core import EVENT_STATE_CHANGED, Event
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .site_context import async_load_site_store


FORECAST_SOLAR_DOMAIN = "forecast_solar"
STORE_KEY = "elrakning.solar_forecast"
UPDATE_EVENT = "elrakning_solar_forecast_update"
BASELINE_DAYS = 14
ENERGY_FACTORS = {"wh": 0.001, "kwh": 1.0, "mwh": 1000.0}
POWER_FACTORS = {"w": 0.001, "kw": 1.0, "mw": 1000.0}


def source_generation_id(site_id: str, binding: dict[str, Any]) -> str:
    """Derive a stable source generation from source-defining binding fields."""
    identity = {
        "site_id": site_id,
        "source": "forecast_solar",
        "config_entry_id": binding.get("config_entry_id"),
        "binding_fingerprint": binding.get("binding_fingerprint"),
        "entities": sorted((binding.get("entities") or {}).items()),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:32]
    return f"fs-{digest}"


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _tokens(entity_id: str, registry_entry: Any, state: Any) -> str:
    values = [
        entity_id,
        getattr(registry_entry, "unique_id", ""),
        getattr(registry_entry, "original_name", ""),
        getattr(registry_entry, "translation_key", ""),
        getattr(state, "attributes", {}).get("friendly_name", "") if state else "",
    ]
    return re.sub(r"[^a-z0-9]+", " ", " ".join(str(value).lower() for value in values))


def _role(tokens: str) -> str | None:
    if "peak time tomorrow" in tokens or "power peak time tomorrow" in tokens:
        return "peak_time_tomorrow"
    if "peak time today" in tokens or "power peak time today" in tokens:
        return "peak_time_today"
    if "energy production today remaining" in tokens or "energy production remaining today" in tokens or "energy production today left" in tokens:
        return "remaining_today_kwh"
    if "energy production tomorrow" in tokens:
        return "tomorrow_kwh"
    if "energy current hour" in tokens or "energy production this hour" in tokens:
        return "this_hour_kwh"
    if "energy next hour" in tokens or "energy production next hour" in tokens:
        return "next_hour_kwh"
    if "power production next 12 hours" in tokens or "power production next 12hours" in tokens:
        return "power_next_12_hours_kw"
    if "power production next 24 hours" in tokens or "power production next 24hours" in tokens:
        return "power_next_24_hours_kw"
    if "power production now" in tokens or "power production current" in tokens:
        return "power_now_kw"
    if "power production next hour" in tokens:
        return "power_next_hour_kw"
    if "energy production today" in tokens and "remaining" not in tokens and "left" not in tokens:
        return "today_kwh"
    return None


def normalize_forecast_value(state: Any, role: str) -> float | str | None:
    """Normalize an official Forecast.Solar entity state to neutral facts."""
    if state is None or str(getattr(state, "state", "")).lower() in {"unknown", "unavailable", "none", ""}:
        return None
    if role.startswith("peak_time"):
        return str(state.state)
    value = _number(state.state)
    if value is None:
        return None
    unit = str(getattr(state, "attributes", {}).get("unit_of_measurement", "")).lower().replace(" ", "")
    factors = ENERGY_FACTORS if role.endswith("_kwh") else POWER_FACTORS
    factor = factors.get(unit)
    return value * factor if factor is not None else None


class SolarForecastManager:
    """Consume one unambiguous Forecast.Solar installation."""

    def __init__(self, hass, diagnostic_callback=None, collection_targets_getter=None) -> None:
        self.hass = hass
        self._diagnostic_callback = diagnostic_callback
        self._collection_targets_getter = collection_targets_getter
        self._baseline_lock = asyncio.Lock()
        self.store = Store(hass, 1, STORE_KEY)
        self._baselines: dict[str, dict[str, Any]] = {}
        self._entities: dict[str, str] = {}
        self._facts: dict[str, Any] = self._unavailable_facts()
        self._site_id: str | None = None
        self._site_context_enabled = False
        self._context_generation = 0
        self._state_unsub = hass.bus.async_listen(EVENT_STATE_CHANGED, self._async_state_changed)

    @staticmethod
    def _unavailable_facts() -> dict[str, Any]:
        return {
            "available": False,
            "source": None,
            "today_kwh": None,
            "remaining_today_kwh": None,
            "tomorrow_kwh": None,
            "this_hour_kwh": None,
            "next_hour_kwh": None,
            "power_now_kw": None,
            "power_next_hour_kw": None,
            "power_next_12_hours_kw": None,
            "power_next_24_hours_kw": None,
            "peak_time_today": None,
            "peak_time_tomorrow": None,
        }

    async def async_load(self) -> None:
        cached = await self.store.async_load()
        if isinstance(cached, dict):
            stored_days = cached.get("days", cached)
            if isinstance(stored_days, dict):
                self._baselines = {
                    date: value for date, value in stored_days.items()
                    if isinstance(date, str) and isinstance(value, dict) and _number(value.get("forecast_kwh")) is not None
                }
        self._trim_baselines(dt_util.as_local(dt_util.now()).date())
        self._discover()
        await self._refresh(capture=True)

    def discovered_binding(self) -> dict[str, Any] | None:
        """Return the explicit Forecast.Solar resource selected by discovery."""
        if not self._entities:
            return None
        entries = self.hass.config_entries.async_entries(FORECAST_SOLAR_DOMAIN)
        if len(entries) != 1:
            return None
        return {
            "config_entry_id": entries[0].entry_id,
            "entities": dict(self._entities),
            "source": "forecast_solar",
        }

    async def async_apply_site_context(self, site_id: str, binding: dict[str, Any] | None) -> None:
        """Switch baselines and live discovery to one explicit site."""
        async with self._baseline_lock:
            self._context_generation += 1
            self._site_id = site_id if isinstance(binding, dict) else None
            self._site_context_enabled = True
            self._baselines = {}
            self._entities = {}
            self._facts = self._unavailable_facts()
            if self._site_id is None:
                return
            self.store, cached = await async_load_site_store(
                self.hass, STORE_KEY, 1, self._site_id
            )
            if cached and isinstance(cached.get("days", cached), dict):
                self._baselines = {
                    key: value for key, value in cached.get("days", cached).items()
                    if isinstance(key, str) and isinstance(value, dict)
                }
            self._entities = dict(binding.get("entities", {}))
            self._facts = self._read_facts()
            self._facts["site_id"] = self._site_id

    async def async_shutdown(self) -> None:
        if self._state_unsub:
            self._state_unsub()
            self._state_unsub = None

    async def async_capture_collection_baselines(self, entity_id: str | None = None) -> dict[str, Any]:
        """Capture baseline stores for every explicitly enabled Forecast.Solar site."""
        getter = self._collection_targets_getter
        targets = getter() if callable(getter) else []
        if entity_id is not None:
            targets = [
                target for target in targets
                if entity_id in ((target.get("binding") or {}).get("entities") or {}).values()
            ]
        result = {"target_count": len(targets), "written": 0, "site_ids": []}
        async with self._baseline_lock:
            for target in targets:
                site_id = target.get("site_id")
                binding = target.get("binding")
                entities = binding.get("entities") if isinstance(binding, dict) else None
                if not isinstance(site_id, str) or not site_id or not isinstance(entities, dict):
                    continue
                result["site_ids"].append(site_id)
                store, cached = await async_load_site_store(self.hass, STORE_KEY, 1, site_id)
                days = {
                    key: dict(value)
                    for key, value in ((cached or {}).get("days", {}) or {}).items()
                    if isinstance(key, str) and isinstance(value, dict)
                }
                today = dt_util.as_local(dt_util.now()).date()
                changed = self._trim_baseline_days(days, today)
                facts = self._read_facts(entities)
                captured_at = dt_util.now()
                generation_id = source_generation_id(site_id, binding)
                tomorrow = facts.get("tomorrow_kwh")
                if isinstance(tomorrow, (int, float)) and tomorrow >= 0:
                    changed |= self._capture_into(
                        days, site_id, today + timedelta(days=1), tomorrow, "day_ahead", captured_at,
                        generation_id,
                    )
                current = facts.get("today_kwh")
                if isinstance(current, (int, float)) and current >= 0:
                    changed |= self._capture_into(
                        days, site_id, today, current, "first_today", captured_at, generation_id
                    )
                if changed:
                    await store.async_save({"days": days})
                    result["written"] += 1
                if site_id == self._site_id and entities == self._entities:
                    self._baselines = {key: dict(value) for key, value in days.items()}
        return result

    async def async_site_baseline_record(self, site_id: str, key: str) -> dict[str, Any] | None:
        """Read one site's frozen baseline without changing active UI context."""
        if not isinstance(site_id, str) or not site_id or not isinstance(key, str) or not key:
            return None
        async with self._baseline_lock:
            _store, cached = await async_load_site_store(self.hass, STORE_KEY, 1, site_id)
            days = (cached or {}).get("days", {}) if isinstance(cached, dict) else {}
            item = days.get(key) if isinstance(days, dict) else None
            return dict(item) if isinstance(item, dict) else None

    def _discover(self) -> None:
        entries = self.hass.config_entries.async_entries(FORECAST_SOLAR_DOMAIN)
        if len(entries) != 1:
            self._entities = {}
            self._facts = self._unavailable_facts()
            return
        entry_id = entries[0].entry_id
        try:
            registry = er.async_get(self.hass)
        except Exception:
            self._entities = {}
            self._facts = self._unavailable_facts()
            return
        candidates: dict[str, list[str]] = {}
        for registry_entry in registry.entities.values():
            if getattr(registry_entry, "config_entry_id", None) != entry_id:
                continue
            entity_id = getattr(registry_entry, "entity_id", None)
            if not isinstance(entity_id, str):
                continue
            role = _role(_tokens(entity_id, registry_entry, self.hass.states.get(entity_id)))
            if role:
                candidates.setdefault(role, []).append(entity_id)
        self._entities = {
            role: entity_ids[0]
            for role, entity_ids in candidates.items()
            if len(entity_ids) == 1
        }
        if any(len(entity_ids) > 1 for entity_ids in candidates.values()):
            self._entities = {}

    def _read_facts(self, entities: dict[str, str] | None = None) -> dict[str, Any]:
        facts = self._unavailable_facts()
        selected_entities = self._entities if entities is None else entities
        if not selected_entities:
            return facts
        facts.update({
            "source": "forecast_solar",
            **{
                role: normalize_forecast_value(self.hass.states.get(entity_id), role)
                for role, entity_id in selected_entities.items()
            },
        })
        facts["available"] = any(value is not None for key, value in facts.items() if key not in {"available", "source"})
        return facts

    @staticmethod
    def _trim_baseline_days(days: dict[str, dict[str, Any]], today) -> bool:
        minimum = today - timedelta(days=BASELINE_DAYS - 1)
        retained = {
            date: value for date, value in days.items()
            if _date_in_window(date, minimum, today + timedelta(days=1))
        }
        changed = len(retained) != len(days)
        if changed:
            days.clear()
            days.update(retained)
        return changed

    def _trim_baselines(self, today) -> bool:
        return self._trim_baseline_days(self._baselines, today)

    async def _refresh(self, *, capture: bool) -> bool:
        async with self._baseline_lock:
            context_generation = self._context_generation
            context_site_id = self._site_id
            context_entities = dict(self._entities)
            context_store = self.store
            previous_facts = self._facts
            self._facts = self._read_facts(context_entities)
            changed = self._facts != previous_facts
            today = dt_util.as_local(dt_util.now()).date()
            baselines_changed = self._trim_baselines(today)
            if capture:
                tomorrow = self._facts.get("tomorrow_kwh")
                if isinstance(tomorrow, (int, float)) and tomorrow >= 0:
                    baselines_changed |= self._capture(today + timedelta(days=1), tomorrow, "day_ahead")
                current = self._facts.get("today_kwh")
                if today.isoformat() not in self._baselines and isinstance(current, (int, float)) and current >= 0:
                    baselines_changed |= self._capture(today, current, "first_today")
            if baselines_changed:
                if context_generation != self._context_generation or context_site_id != self._site_id:
                    return False
                await context_store.async_save({"days": self._baselines})
            if (changed or baselines_changed) and context_generation == self._context_generation and context_site_id == self._site_id:
                self.hass.bus.async_fire(UPDATE_EVENT)
            return changed or baselines_changed

    @staticmethod
    def _capture_into(
        days: dict[str, dict[str, Any]],
        site_id: str | None,
        target_date,
        forecast_kwh: float,
        capture_type: str,
        captured_at: datetime,
        source_generation_id: str | None = None,
    ) -> bool:
        key = target_date.isoformat()
        existing = days.get(key)
        if capture_type == "first_today" and existing is not None:
            return False
        next_value = {
            "forecast_kwh": float(forecast_kwh),
            "captured_at": captured_at.isoformat(),
            "source": "forecast_solar",
            "capture_type": capture_type,
            "site_id": site_id,
            "source_generation_id": source_generation_id,
        }
        if (
            existing
            and existing.get("forecast_kwh") == next_value["forecast_kwh"]
            and existing.get("capture_type") == capture_type
            and existing.get("source_generation_id") == source_generation_id
        ):
            return False
        days[key] = next_value
        return True

    def _capture(self, target_date, forecast_kwh: float, capture_type: str) -> bool:
        return self._capture_into(
            self._baselines, self._site_id, target_date, forecast_kwh, capture_type, dt_util.now()
        )

    async def _async_state_changed(self, event: Event) -> None:
        entity_id = event.data.get("entity_id")
        if callable(self._collection_targets_getter):
            await self.async_capture_collection_baselines(entity_id=entity_id)
            context_entities = dict(self._entities)
            if entity_id in context_entities.values():
                await self._refresh(capture=False)
            return
        if getattr(self, "_site_context_enabled", False) and getattr(self, "_site_id", None) is None:
            return
        context_entities = dict(self._entities)
        if entity_id not in context_entities.values():
            return
        await self._refresh(capture=True)

    def public_state(self) -> dict[str, Any]:
        return {
            **self._facts,
            "baselines": {
                date: value.get("forecast_kwh")
                for date, value in self._baselines.items()
                if isinstance(value, dict) and _number(value.get("forecast_kwh")) is not None
            },
        }


def _date_in_window(value: str, minimum, maximum) -> bool:
    try:
        parsed = datetime.fromisoformat(value).date()
    except (TypeError, ValueError):
        return False
    return minimum <= parsed <= maximum
