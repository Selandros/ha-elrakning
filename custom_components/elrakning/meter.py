"""Generic Home Assistant meter discovery and state access."""

from __future__ import annotations

import json
from datetime import timedelta
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

from homeassistant.core import EVENT_STATE_CHANGED, Event, State, valid_entity_id
from homeassistant.util import dt as dt_util
from homeassistant.helpers.storage import Store


STORE_KEY = "elrakning.meter"
METER_FIELDS = (
    "power_entity",
    "energy_import_entity",
    "energy_export_entity",
)
METER_POWER_UPDATE_EVENT = "elrakning_meter_power_update"


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(state, divisor: float) -> float | None:
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    return value / divisor


def _power_kw(state: State | Any) -> float | None:
    """Normalize a signed power state to kW."""
    raw = getattr(state, "state", state)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not value == value or value in (float("inf"), float("-inf")):
        return None
    unit = str(getattr(state, "attributes", {}).get("unit_of_measurement", "")).lower()
    if unit == "w":
        value /= 1000
    elif unit == "mw":
        value *= 1000
    return value


def normalize_power_state(state: State | Any) -> dict[str, Any] | None:
    """Convert signed meter power into semantic import/export series."""
    power_kw = _power_kw(state)
    if power_kw is None:
        return None
    timestamp = getattr(state, "last_updated", None)
    if timestamp is None:
        return None
    return {
        "timestamp": timestamp.isoformat(),
        "import_kw": max(power_kw, 0),
        "export_kw": max(-power_kw, 0),
    }


class MeterManager:
    """Persist a user-selected generic meter mapping and read its states."""

    def __init__(self, hass, diagnostic_callback: Callable[..., Awaitable[None]] | None = None) -> None:
        self.hass = hass
        self._diagnostic_callback = diagnostic_callback
        self.store = Store(hass, 1, STORE_KEY)
        self.mapping: dict[str, Any] = {field: None for field in METER_FIELDS}
        self._state_unsub = hass.bus.async_listen(EVENT_STATE_CHANGED, self._async_state_changed)

    async def _async_state_changed(self, event: Event) -> None:
        """Publish normalized live power without polling."""
        entity_id = event.data.get("entity_id")
        if entity_id != self.mapping.get("power_entity"):
            return
        point = normalize_power_state(event.data.get("new_state"))
        if point is not None:
            self.hass.bus.async_fire(
                METER_POWER_UPDATE_EVENT,
                {"entity_id": entity_id, **point},
            )

    async def async_shutdown(self) -> None:
        """Unsubscribe from Home Assistant state changes."""
        if self._state_unsub:
            self._state_unsub()
            self._state_unsub = None

    async def _diagnostic(self, level: str, event: str, message: str) -> None:
        if self._diagnostic_callback is not None:
            await self._diagnostic_callback(level, "meter", event, message)

    async def async_load(self) -> None:
        cached = await self.store.async_load()
        if isinstance(cached, dict):
            for field in METER_FIELDS:
                value = cached.get(field)
                self.mapping[field] = value.strip() if isinstance(value, str) and value.strip() else None

    async def async_clear(self) -> dict[str, Any]:
        self.mapping = {field: None for field in METER_FIELDS}
        await self.store.async_remove()
        return await self.async_state()

    async def async_save_mapping(self, mapping: dict[str, Any]) -> dict[str, Any]:
        try:
            if not isinstance(mapping, dict):
                raise ValueError("invalid_mapping")
            await self._diagnostic("INFO", "meter_mapping_received", "Meter mapping received")
            selected = {field: _text(mapping.get(field)) or None for field in METER_FIELDS}
            for field, entity_id in selected.items():
                if entity_id is None:
                    continue
                if not valid_entity_id(entity_id):
                    raise ValueError(f"invalid_entity_id:{field}")
                if self.hass.states.get(entity_id) is None:
                    raise ValueError(f"entity_not_found:{field}")
            await self._diagnostic("INFO", "meter_validation_success", "Meter mapping validated")
            self.mapping = selected
            await self.store.async_save(self.mapping)
            await self._diagnostic("INFO", "meter_store_write_success", "Meter mapping stored")
            await self._diagnostic(
                "INFO",
                "meter_store_current_state",
                json.dumps(self.mapping, sort_keys=True),
            )
            return await self.async_state()
        except Exception:
            await self._diagnostic("ERROR", "meter_save_failed", "Meter mapping save failed")
            raise

    async def async_state(self) -> dict[str, Any]:
        result = {**self.mapping, "configured": any(self.mapping[field] for field in METER_FIELDS)}
        result.update({"power_kw": None, "energy_import_kwh": None, "energy_export_kwh": None})
        for field, output, divisor in (
            ("power_entity", "power_kw", 1000),
            ("energy_import_entity", "energy_import_kwh", 1),
            ("energy_export_entity", "energy_export_kwh", 1),
        ):
            entity_id = self.mapping[field]
            state = self.hass.states.get(entity_id) if entity_id else None
            if state is None:
                continue
            unit = _text(state.attributes.get("unit_of_measurement")).lower()
            if output == "power_kw":
                divisor = 1000 if unit == "w" else 1
            elif unit == "wh":
                divisor = 1000
            elif unit == "mwh":
                divisor = 0.001
            result[output] = _number(state, divisor)
        return result

    async def async_source(self) -> dict[str, Any]:
        return {"mapping": dict(self.mapping), "state": await self.async_state()}

    async def async_power_history(self) -> dict[str, Any]:
        """Return today's normalized history for the selected power entity."""
        entity_id = self.mapping.get("power_entity")
        now = dt_util.now()
        start = dt_util.start_of_local_day(now)
        end = dt_util.start_of_local_day(now + timedelta(days=1))
        if not entity_id:
            return {"success": True, "date": start.date().isoformat(), "points": []}
        try:
            from homeassistant.components.recorder import history

            history_by_entity = await self.hass.async_add_executor_job(
                partial(
                    history.get_significant_states,
                    self.hass,
                    start,
                    end,
                    entity_ids=[entity_id],
                    include_start_time_state=True,
                    significant_changes_only=False,
                    minimal_response=False,
                    no_attributes=False,
                )
            )
        except Exception:
            return {
                "success": False,
                "date": start.date().isoformat(),
                "points": [],
                "error": "history_unavailable",
            }
        points = []
        for state in history_by_entity.get(entity_id, []):
            point = normalize_power_state(state)
            if point is not None:
                points.append(point)
        points.sort(key=lambda point: point["timestamp"])
        return {"success": True, "date": start.date().isoformat(), "points": points}
