"""Forecast.Solar discovery, live facts, and daily forecast baselines."""

from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any

from homeassistant.core import EVENT_STATE_CHANGED, Event
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util


FORECAST_SOLAR_DOMAIN = "forecast_solar"
STORE_KEY = "elrakning.solar_forecast"
UPDATE_EVENT = "elrakning_solar_forecast_update"
BASELINE_DAYS = 14
ENERGY_FACTORS = {"wh": 0.001, "kwh": 1.0, "mwh": 1000.0}
POWER_FACTORS = {"w": 0.001, "kw": 1.0, "mw": 1000.0}


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

    def __init__(self, hass, diagnostic_callback=None) -> None:
        self.hass = hass
        self._diagnostic_callback = diagnostic_callback
        self.store = Store(hass, 1, STORE_KEY)
        self._baselines: dict[str, dict[str, Any]] = {}
        self._entities: dict[str, str] = {}
        self._facts: dict[str, Any] = self._unavailable_facts()
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

    async def async_shutdown(self) -> None:
        if self._state_unsub:
            self._state_unsub()
            self._state_unsub = None

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

    def _read_facts(self) -> dict[str, Any]:
        facts = self._unavailable_facts()
        if not self._entities:
            return facts
        facts.update({
            "source": "forecast_solar",
            **{
                role: normalize_forecast_value(self.hass.states.get(entity_id), role)
                for role, entity_id in self._entities.items()
            },
        })
        facts["available"] = any(value is not None for key, value in facts.items() if key not in {"available", "source"})
        return facts

    def _trim_baselines(self, today) -> bool:
        minimum = today - timedelta(days=BASELINE_DAYS - 1)
        original = len(self._baselines)
        self._baselines = {
            date: value for date, value in self._baselines.items()
            if _date_in_window(date, minimum, today + timedelta(days=1))
        }
        return len(self._baselines) != original

    async def _refresh(self, *, capture: bool) -> bool:
        previous_facts = self._facts
        self._facts = self._read_facts()
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
            await self.store.async_save({"days": self._baselines})
        if changed or baselines_changed:
            self.hass.bus.async_fire(UPDATE_EVENT)
        return changed or baselines_changed

    def _capture(self, target_date, forecast_kwh: float, capture_type: str) -> bool:
        key = target_date.isoformat()
        existing = self._baselines.get(key)
        if capture_type == "first_today" and existing is not None:
            return False
        next_value = {
            "forecast_kwh": float(forecast_kwh),
            "captured_at": dt_util.now().isoformat(),
            "source": "forecast_solar",
            "capture_type": capture_type,
        }
        if existing and existing.get("forecast_kwh") == next_value["forecast_kwh"] and existing.get("capture_type") == capture_type:
            return False
        self._baselines[key] = next_value
        return True

    async def _async_state_changed(self, event: Event) -> None:
        if event.data.get("entity_id") not in self._entities.values():
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
