"""Generic Home Assistant meter discovery and state access."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.core import valid_entity_id
from homeassistant.helpers.storage import Store


STORE_KEY = "elrakning.meter"
METER_FIELDS = (
    "power_entity",
    "energy_import_entity",
    "energy_export_entity",
)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(state, divisor: float) -> float | None:
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    return value / divisor


class MeterManager:
    """Persist a user-selected generic meter mapping and read its states."""

    def __init__(self, hass, diagnostic_callback: Callable[..., Awaitable[None]] | None = None) -> None:
        self.hass = hass
        self._diagnostic_callback = diagnostic_callback
        self.store = Store(hass, 1, STORE_KEY)
        self.mapping: dict[str, Any] = {field: None for field in METER_FIELDS}

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
