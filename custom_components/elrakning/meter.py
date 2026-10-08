"""Generic Home Assistant meter discovery and state access."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

from homeassistant.core import EVENT_STATE_CHANGED, Event, State, valid_entity_id
from homeassistant.util import dt as dt_util
from homeassistant.helpers.storage import Store
from homeassistant.helpers import entity_registry as er


STORE_KEY = "elrakning.meter"
METER_FIELDS = (
    "power_entity",
    "energy_import_entity",
    "energy_export_entity",
)
METER_INVERT_FIELD = "invert_power"
METER_POWER_UPDATE_EVENT = "elrakning_meter_power_update"
ENERGY_UNIT_FACTORS = {"wh": 0.001, "kwh": 1, "mwh": 1000}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(state, divisor: float) -> float | None:
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    return value / divisor if value == value and value not in (float("inf"), float("-inf")) else None


def _energy_kwh(state: State | Any) -> float | None:
    """Normalize a genuine energy sensor state to kWh."""
    attributes = getattr(state, "attributes", {})
    if str(attributes.get("device_class", "")).lower() != "energy":
        return None
    factor = ENERGY_UNIT_FACTORS.get(_text(attributes.get("unit_of_measurement")).lower())
    if factor is None:
        return None
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    return value * factor if value == value and value not in (float("inf"), float("-inf")) else None


def _is_energy_sensor(state: State | Any) -> bool:
    attributes = getattr(state, "attributes", {})
    return (
        str(attributes.get("device_class", "")).lower() == "energy"
        and _text(attributes.get("unit_of_measurement")).lower() in ENERGY_UNIT_FACTORS
    )


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


def _normalized_power_kw(state: State | Any, invert_power: bool = False) -> float | None:
    power_kw = _power_kw(state)
    if power_kw is not None and invert_power:
        power_kw = -power_kw
    return power_kw


def normalize_power_state(state: State | Any, invert_power: bool = False) -> dict[str, Any] | None:
    """Convert signed meter power into semantic import/export series."""
    power_kw = _normalized_power_kw(state, invert_power)
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


def _phase_from_metadata(values: list[Any]) -> str | None:
    """Find a phase marker in entity metadata without relying on display names."""
    for value in values:
        text = str(value or "").lower()
        match = re.search(r"(?:^|[^a-z0-9])l([123])(?:$|[^a-z0-9])", text)
        if match:
            return f"l{match.group(1)}"
        match = re.search(r"phase[_ -]?([123abc])(?:$|[^a-z0-9])", text)
        if match:
            token = match.group(1)
            return f"l{({'a': '1', 'b': '2', 'c': '3'}.get(token, token))}"
    return None


def _current_ampere(state: State | Any) -> float | None:
    attributes = getattr(state, "attributes", {})
    if str(attributes.get("device_class", "")).lower() != "current":
        return None
    if _text(attributes.get("unit_of_measurement")).lower() != "a":
        return None
    try:
        value = float(getattr(state, "state", state))
    except (TypeError, ValueError):
        return None
    return value if value == value and value not in (float("inf"), float("-inf")) else None


def _finite_state_value(state: State | Any) -> float | None:
    try:
        value = float(getattr(state, "state", state))
    except (TypeError, ValueError):
        return None
    return value if value == value and value not in (float("inf"), float("-inf")) else None


def _phase_voltage(state: State | Any) -> float | None:
    attributes = getattr(state, "attributes", {})
    if str(attributes.get("device_class", "")).lower() != "voltage":
        return None
    if _text(attributes.get("unit_of_measurement")).lower() != "v":
        return None
    return _finite_state_value(state)


def _phase_active_power_kw(state: State | Any, invert_power: bool = False) -> float | None:
    attributes = getattr(state, "attributes", {})
    if str(attributes.get("device_class", "")).lower() != "power":
        return None
    unit = _text(attributes.get("unit_of_measurement")).lower()
    if unit not in {"w", "kw", "mw"}:
        return None
    value = _finite_state_value(state)
    if value is None:
        return None
    normalized = value / 1000 if unit == "w" else value * 1000 if unit == "mw" else value
    return -normalized if invert_power else normalized


class MeterManager:
    """Persist a user-selected generic meter mapping and read its states."""

    def __init__(self, hass, diagnostic_callback: Callable[..., Awaitable[None]] | None = None) -> None:
        self.hass = hass
        self._diagnostic_callback = diagnostic_callback
        self._mapping_changed_callback = None
        self.store = Store(hass, 1, STORE_KEY)
        self.mapping: dict[str, Any] = {field: None for field in METER_FIELDS}
        self.mapping[METER_INVERT_FIELD] = False
        self._history_summary: dict[str, Any] | None = None
        self._history_inflight: dict[tuple[str, str, bool, tuple[tuple[str, str, str], ...]], asyncio.Task] = {}
        self._history_cache: dict[tuple[str, str, bool, tuple[tuple[str, str, str], ...]], dict[str, Any]] = {}
        self._history_cache_epoch = 0
        self._phase_current_entities: dict[str, str] = {}
        self._phase_source_entities: dict[str, dict[str, str]] = {"current": {}, "voltage": {}, "active_power": {}}
        self._phase_current_discovery_method = "device_registry_and_phase_metadata"
        self._state_unsub = hass.bus.async_listen(EVENT_STATE_CHANGED, self._async_state_changed)

    def set_mapping_changed_callback(self, callback) -> None:
        """Register the metadata-only source ledger callback."""
        self._mapping_changed_callback = callback

    async def _notify_mapping_changed(self) -> None:
        if self._mapping_changed_callback is None:
            return
        try:
            await self._mapping_changed_callback()
        except Exception:
            return

    async def _async_state_changed(self, event: Event) -> None:
        """Publish normalized live power without polling."""
        entity_id = event.data.get("entity_id")
        phase_entity = entity_id in self._phase_current_entities.values()
        phase_kind = next((kind for kind, entities in self._phase_source_entities.items() if entity_id in entities.values()), None)
        if entity_id != self.mapping.get("power_entity") and phase_kind is None and not phase_entity:
            return
        # Live points are merged by the frontend; keep the expensive Recorder
        # snapshot reusable until the mapping or period changes.
        if phase_entity or phase_kind is not None:
            invert_power = bool(self.mapping.get(METER_INVERT_FIELD))
            phase_values = {
                kind: {
                    phase: validator(self.hass.states.get(phase_entity_id))
                    for phase, phase_entity_id in entities.items()
                }
                for kind, entities, validator in (
                    ("current", self._phase_source_entities["current"], _current_ampere),
                    ("voltage", self._phase_source_entities["voltage"], _phase_voltage),
                    ("active_power", self._phase_source_entities["active_power"], lambda state: _phase_active_power_kw(state, invert_power)),
                )
            }
            self.hass.bus.async_fire(
                METER_POWER_UPDATE_EVENT,
                {
                    "entity_id": entity_id,
                    "timestamp": getattr(event.data.get("new_state"), "last_updated", None).isoformat() if getattr(event.data.get("new_state"), "last_updated", None) else None,
                    "phase_current_a": phase_values["current"],
                    "phase_voltage_v": phase_values["voltage"],
                    "phase_active_power_kw": phase_values["active_power"],
                    METER_INVERT_FIELD: invert_power,
                },
            )
            return
        point = normalize_power_state(event.data.get("new_state"), bool(self.mapping.get(METER_INVERT_FIELD)))
        if point is not None:
            self.hass.bus.async_fire(
                METER_POWER_UPDATE_EVENT,
                {"entity_id": entity_id, **point},
            )

    async def async_shutdown(self) -> None:
        """Unsubscribe from Home Assistant state changes."""
        for task in self._history_inflight.values():
            task.cancel()
        self._history_inflight.clear()
        self._history_cache.clear()
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
            self.mapping[METER_INVERT_FIELD] = cached.get(METER_INVERT_FIELD) is True

    async def async_restore_mapping(self, mapping: dict[str, Any] | None) -> None:
        """Restore a previously validated site mapping without validating live states."""
        for task in self._history_inflight.values():
            task.cancel()
        self._history_inflight.clear()
        self._history_cache_epoch += 1
        self._history_cache.clear()
        mapping = mapping if isinstance(mapping, dict) else {}
        selected = {
            field: _text(mapping.get(field)) or None for field in METER_FIELDS
        }
        selected[METER_INVERT_FIELD] = mapping.get(METER_INVERT_FIELD) is True
        self.mapping = selected
        self._history_cache_epoch += 1
        self._history_cache.clear()
        self._history_summary = None
        self._clear_phase_context()
        await self.store.async_save(self.mapping)

    def _clear_phase_context(self) -> None:
        """Drop phase discovery and live context when the active site has no meter."""
        self._phase_current_entities = {}
        self._phase_source_entities = {"current": {}, "voltage": {}, "active_power": {}}
        self._phase_current_discovery_method = None

    async def async_clear(self) -> dict[str, Any]:
        self.mapping = {field: None for field in METER_FIELDS}
        self.mapping[METER_INVERT_FIELD] = False
        self._history_cache_epoch += 1
        self._history_cache.clear()
        self._history_summary = None
        self._clear_phase_context()
        await self.store.async_remove()
        await self._notify_mapping_changed()
        return await self.async_state()

    async def async_save_mapping(self, mapping: dict[str, Any]) -> dict[str, Any]:
        try:
            if not isinstance(mapping, dict):
                raise ValueError("invalid_mapping")
            await self._diagnostic("INFO", "meter_mapping_received", "Meter mapping received")
            selected = {field: _text(mapping.get(field)) or None for field in METER_FIELDS}
            invert_power = mapping.get(METER_INVERT_FIELD, False)
            if not isinstance(invert_power, bool):
                raise ValueError("invalid_invert_power")
            selected[METER_INVERT_FIELD] = invert_power
            for field in METER_FIELDS:
                entity_id = selected[field]
                if entity_id is None:
                    continue
                if not valid_entity_id(entity_id):
                    raise ValueError(f"invalid_entity_id:{field}")
                if self.hass.states.get(entity_id) is None:
                    raise ValueError(f"entity_not_found:{field}")
                if field in ("energy_import_entity", "energy_export_entity"):
                    state = self.hass.states.get(entity_id)
                    if str(state.attributes.get("device_class", "")).lower() != "energy":
                        raise ValueError(f"invalid_energy_device_class:{field}")
                    if _text(state.attributes.get("unit_of_measurement")).lower() not in ENERGY_UNIT_FACTORS:
                        raise ValueError(f"invalid_energy_unit:{field}")
            await self._diagnostic("INFO", "meter_validation_success", "Meter mapping validated")
            self.mapping = selected
            self._history_cache_epoch += 1
            self._history_cache.clear()
            self._history_summary = None
            await self.store.async_save(self.mapping)
            await self._notify_mapping_changed()
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
        result.update({
            "power_kw": None,
            "energy_import_kwh": None,
            "energy_export_kwh": None,
            "energy_import_valid": None,
            "energy_export_valid": None,
        })
        if not result["configured"]:
            self._clear_phase_context()
            result.update({
                "phase_current_a": {},
                "phase_voltage_v": {},
                "phase_active_power_kw": {},
                "phase_current_entities": {},
                "phase_current_source_entities": {},
                "phase_current_discovery_method": None,
                "phase_current_available": False,
                "phase_source_entities": {"current": {}, "voltage": {}, "active_power": {}},
                "phase_discovery_method": None,
            })
            return result
        self._phase_current_discovery_method = "device_registry_and_phase_metadata"
        phase_sources = self._discover_phase_entities()
        self._phase_source_entities = phase_sources
        phase_entities = phase_sources["current"]
        self._phase_current_entities = phase_entities
        phase_values = {
            phase: _current_ampere(self.hass.states.get(entity_id))
            for phase, entity_id in phase_entities.items()
        }
        phase_voltage_values = {
            phase: _phase_voltage(self.hass.states.get(entity_id))
            for phase, entity_id in phase_sources["voltage"].items()
        }
        phase_power_values = {
            phase: _phase_active_power_kw(
                self.hass.states.get(entity_id),
                bool(self.mapping.get(METER_INVERT_FIELD)),
            )
            for phase, entity_id in phase_sources["active_power"].items()
        }
        result.update({
            "phase_current_a": {phase: phase_values.get(phase) for phase in ("l1", "l2", "l3")},
            "phase_voltage_v": {phase: phase_voltage_values.get(phase) for phase in ("l1", "l2", "l3")},
            "phase_active_power_kw": {phase: phase_power_values.get(phase) for phase in ("l1", "l2", "l3")},
            "phase_current_entities": dict(phase_entities),
            "phase_current_source_entities": dict(phase_entities),
            "phase_current_discovery_method": self._phase_current_discovery_method,
            "phase_current_available": any(value is not None for value in phase_values.values()),
            "phase_source_entities": {kind: dict(entities) for kind, entities in phase_sources.items()},
            "phase_discovery_method": self._phase_current_discovery_method,
        })
        for field, output, divisor in (
            ("power_entity", "power_kw", 1000),
            ("energy_import_entity", "energy_import_kwh", 1),
            ("energy_export_entity", "energy_export_kwh", 1),
        ):
            entity_id = self.mapping[field]
            state = self.hass.states.get(entity_id) if entity_id else None
            if state is None:
                if output == "energy_import_kwh":
                    result["energy_import_valid"] = False if entity_id else None
                elif output == "energy_export_kwh":
                    result["energy_export_valid"] = False if entity_id else None
                continue
            unit = _text(state.attributes.get("unit_of_measurement")).lower()
            if output == "power_kw":
                divisor = 1000 if unit == "w" else 1
            else:
                valid = _is_energy_sensor(state)
                result["energy_import_valid" if output == "energy_import_kwh" else "energy_export_valid"] = valid
                result[output] = _energy_kwh(state) if valid else None
                continue
            result[output] = _normalized_power_kw(state, bool(self.mapping.get(METER_INVERT_FIELD)))
        return result

    def _discover_phase_current_entities(self) -> dict[str, str]:
        """Discover phase-current sensors associated with the selected meter device."""
        return self._discover_phase_entities()["current"]

    def _discover_phase_entities(self) -> dict[str, dict[str, str]]:
        """Discover phase sensors associated with the selected meter device."""
        if not hasattr(self.hass.states, "async_all"):
            return {"current": {}, "voltage": {}, "active_power": {}}
        try:
            states = self.hass.states.async_all()
        except TypeError:
            states = self.hass.states.async_all(None)
        state_by_entity = {state.entity_id: state for state in states if getattr(state, "entity_id", None)}
        registry = er.async_get(self.hass)
        power_entity = self.mapping.get("power_entity")
        power_entry = registry.async_get(power_entity) if registry is not None and power_entity else None
        device_id = getattr(power_entry, "device_id", None)
        candidates: dict[str, list[tuple[str, str, Any]]] = {"current": [], "voltage": [], "active_power": []}
        validators = {"current": _current_ampere, "voltage": _phase_voltage, "active_power": _phase_active_power_kw}
        for entity_id, state in state_by_entity.items():
            entry = registry.async_get(entity_id) if registry is not None else None
            if device_id and getattr(entry, "device_id", None) != device_id:
                continue
            phase = _phase_from_metadata([
                entity_id,
                getattr(entry, "unique_id", None),
                getattr(entry, "original_name", None),
                getattr(state, "attributes", {}).get("phase"),
                getattr(state, "attributes", {}).get("phase_name"),
                getattr(state, "attributes", {}).get("channel"),
            ])
            if not phase:
                continue
            for kind, validator in validators.items():
                if validator(state) is not None:
                    candidates[kind].append((phase, entity_id, entry))
        result = {kind: {} for kind in candidates}
        for kind, items in candidates.items():
            for phase, entity_id, _entry in items:
                result[kind].setdefault(phase, entity_id)
        return result

    async def async_source(self) -> dict[str, Any]:
        return {
            "mapping": dict(self.mapping),
            "state": await self.async_state(),
            "history": self._history_summary,
        }

    async def async_power_history(self, requested_entity_id: str | None = None) -> dict[str, Any]:
        """Return today's normalized Recorder history for the selected power entity."""
        entity_id = self.mapping.get("power_entity")
        now = dt_util.now()
        start = dt_util.start_of_local_day(now)
        end = dt_util.start_of_local_day(now + timedelta(days=1))
        date = start.date().isoformat()
        if requested_entity_id is not None and requested_entity_id != entity_id:
            return {
                "success": False,
                "entity_id": requested_entity_id,
                "date": date,
                "points": [],
                "error": "meter_mapping_changed",
            }
        if not entity_id:
            summary = {
                "entity_id": None,
                "success": True,
                "date": date,
                "point_count": 0,
                "first_timestamp": None,
                "last_timestamp": None,
                "max_abs_kw": None,
                METER_INVERT_FIELD: bool(self.mapping.get(METER_INVERT_FIELD)),
            }
            self._history_summary = summary
            return {"success": True, "entity_id": None, "date": date, "points": [], "history": summary}
        invert_power = bool(self.mapping.get(METER_INVERT_FIELD))
        phase_entities = self._discover_phase_entities()
        self._phase_source_entities = phase_entities
        self._phase_current_entities = phase_entities["current"]
        phase_key = tuple(sorted((kind, phase, entity_id) for kind, entities in phase_entities.items() for phase, entity_id in entities.items()))
        key = (entity_id, date, invert_power, phase_key)
        current_date = date == dt_util.now().date().isoformat()
        cached = None if current_date else self._history_cache.get(key)
        if cached is not None:
            return cached
        task = self._history_inflight.get(key)
        if task is None:
            cache_epoch = self._history_cache_epoch
            task = asyncio.create_task(self._async_power_history_fetch(entity_id, start, end, date, invert_power, phase_entities))
            self._history_inflight[key] = task
            def clear_inflight(
                completed: asyncio.Task,
                *,
                request_key: tuple[str, str, bool, tuple[tuple[str, str, str], ...]] = key,
                request_epoch: int = cache_epoch,
                cache_result: bool = not current_date,
            ) -> None:
                if self._history_inflight.get(request_key) is completed:
                    self._history_inflight.pop(request_key, None)
                if cache_result and not completed.cancelled() and completed.exception() is None and request_epoch == self._history_cache_epoch:
                    result = completed.result()
                    if isinstance(result, dict) and result.get("success") is True:
                        self._history_cache[request_key] = result

            task.add_done_callback(clear_inflight)
        return await asyncio.shield(task)

    async def async_billing_history(self, target_month: str | None = None) -> dict[str, Any]:
        """Return imported power history for one local month plus a bounded baseline."""
        entity_id = self.mapping.get("power_entity")
        now = dt_util.now()
        if target_month:
            try:
                year, month = (int(value) for value in target_month.split("-", 1))
                start = now.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
            except (AttributeError, TypeError, ValueError):
                start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = min(now, next_month)
        if not entity_id:
            return {
                "success": True,
                "entity_id": None,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "points": [],
                "baseline_points": [],
                "coverage": {"energy_start": None, "energy_end": None, "point_count": 0, "baseline_start": None, "baseline_end": None, "baseline_point_count": 0},
                "baseline_coverage": {"energy_start": None, "energy_end": None, "point_count": 0},
            }
        return await self._async_billing_history_fetch(entity_id, start, end, bool(self.mapping.get(METER_INVERT_FIELD)))

    async def _async_billing_history_fetch(self, entity_id: str, start, end, invert_power: bool) -> dict[str, Any]:
        """Read the billing month and a bounded trailing baseline window."""
        baseline_start = start - timedelta(days=28)
        try:
            from homeassistant.components.recorder import get_instance, history

            recorder = get_instance(self.hass)
            history_by_entity = await recorder.async_add_executor_job(
                partial(
                    history.get_significant_states,
                    self.hass,
                    baseline_start,
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
                "entity_id": entity_id,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "points": [],
                "error": "history_unavailable",
            }
        points = sorted(
            (
                point
                for state in history_by_entity.get(entity_id, [])
                if (point := normalize_power_state(state, invert_power)) is not None
            ),
            key=lambda point: point["timestamp"],
        )
        current_points = []
        baseline_points = []
        for point in points:
            try:
                point_time = datetime.fromisoformat(point["timestamp"])
            except (TypeError, ValueError):
                continue
            if point_time >= start:
                current_points.append(point)
            else:
                baseline_points.append(point)
        return {
            "success": True,
            "entity_id": entity_id,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "points": current_points,
            "baseline_points": baseline_points,
            "coverage": {
                "energy_start": current_points[0]["timestamp"] if current_points else None,
                "energy_end": current_points[-1]["timestamp"] if current_points else None,
                "point_count": len(current_points),
                "baseline_start": baseline_points[0]["timestamp"] if baseline_points else None,
                "baseline_end": baseline_points[-1]["timestamp"] if baseline_points else None,
                "baseline_point_count": len(baseline_points),
            },
            "baseline_coverage": {
                "energy_start": baseline_points[0]["timestamp"] if baseline_points else None,
                "energy_end": baseline_points[-1]["timestamp"] if baseline_points else None,
                "point_count": len(baseline_points),
            },
        }

    async def _async_power_history_fetch(
        self,
        entity_id: str,
        start,
        end,
        date: str,
        invert_power: bool = False,
        phase_entities: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Run one Recorder history operation shared by identical callers."""
        try:
            from homeassistant.components.recorder import get_instance, history

            recorder = get_instance(self.hass)
            sources = phase_entities or {"current": {}, "voltage": {}, "active_power": {}}
            requested_entities = list(dict.fromkeys([entity_id, *(entity for entities in sources.values() for entity in entities.values())]))
            history_by_entity = await recorder.async_add_executor_job(
                partial(
                    history.get_significant_states,
                    self.hass,
                    start,
                    end,
                    entity_ids=requested_entities,
                    include_start_time_state=True,
                    significant_changes_only=False,
                    minimal_response=False,
                    no_attributes=False,
                )
            )
        except Exception as err:
            await self._diagnostic(
                "ERROR",
                "meter_history_request_failed",
                f"Meter history failed · Entity: {entity_id} · Error: {type(err).__name__}: {str(err) or 'empty_exception_message'}",
            )
            return {
                "success": False,
                "entity_id": entity_id,
                "date": date,
                "points": [],
                "error": "history_unavailable",
            }
        points = []
        for state in history_by_entity.get(entity_id, []):
            point = normalize_power_state(state, invert_power)
            if point is not None:
                points.append(point)
        points.sort(key=lambda point: point["timestamp"])
        max_abs_kw = max(
            (max(point["import_kw"], point["export_kw"]) for point in points),
            default=None,
        )
        phase_current_history = {}
        phase_history = {"current": {}, "voltage": {}, "active_power": {}}
        validators = {"current": _current_ampere, "voltage": _phase_voltage, "active_power": _phase_active_power_kw}
        for kind, entities in (phase_entities or {}).items():
            validator = validators[kind]
            for phase, phase_entity_id in entities.items():
                history_points = []
                for state in history_by_entity.get(phase_entity_id, []):
                    timestamp = getattr(state, "last_updated", None)
                    raw_value = _finite_state_value(state)
                    value = (
                        _phase_active_power_kw(state, invert_power)
                        if kind == "active_power"
                        else validator(state)
                    )
                    if value is None or timestamp is None:
                        continue
                    history_points.append({
                        "timestamp": timestamp.isoformat(),
                        "value": abs(value) if kind == "current" else value,
                        "raw_value": raw_value,
                        **({"inverted": invert_power} if kind == "active_power" else {}),
                    })
                phase_history[kind][phase] = {"entity_id": phase_entity_id, "points": history_points}
        for phase, phase_entity_id in (phase_entities or {}).get("current", {}).items():
            phase_values = []
            for state in history_by_entity.get(phase_entity_id, []):
                value = _current_ampere(state)
                timestamp = getattr(state, "last_updated", None)
                if value is not None and timestamp is not None:
                    phase_values.append((abs(value), value, timestamp))
            max_entry = max(phase_values, key=lambda entry: entry[0], default=None)
            phase_current_history[phase] = {
                "entity_id": phase_entity_id,
                "max_a": max_entry[0] if max_entry else None,
                "max_raw_value": max_entry[1] if max_entry else None,
                "max_timestamp": max_entry[2].isoformat() if max_entry else None,
                "point_count": len(phase_values),
            }
        daily_max_phase_current_a = max(
            (abs(item["max_a"]) for item in phase_current_history.values() if item["max_a"] is not None),
            default=None,
        )
        daily_phase_max = {
            phase: {
                "ampere": item["max_a"],
                "raw_value": item["max_raw_value"],
                "timestamp": item["max_timestamp"],
            }
            for phase, item in phase_current_history.items()
        }
        daily_max_phase = next(
            (
                {
                    "phase": phase,
                    "ampere": item["ampere"],
                    "raw_value": item.get("raw_value"),
                    "timestamp": item["timestamp"],
                }
                for phase, item in daily_phase_max.items()
                if item["ampere"] is not None
            ),
            None,
        )
        for phase, item in daily_phase_max.items():
            if item["ampere"] is not None and (daily_max_phase is None or item["ampere"] > daily_max_phase["ampere"]):
                daily_max_phase = {
                    "phase": phase,
                    "ampere": item["ampere"],
                    "raw_value": item.get("raw_value"),
                    "timestamp": item["timestamp"],
                }
        summary = {
            "entity_id": entity_id,
            "success": True,
            "date": date,
            "point_count": len(points),
            "first_timestamp": points[0]["timestamp"] if points else None,
            "last_timestamp": points[-1]["timestamp"] if points else None,
            "max_abs_kw": round(max_abs_kw, 3) if max_abs_kw is not None else None,
            METER_INVERT_FIELD: invert_power,
            "phase_current_source_entities": dict((phase_entities or {}).get("current", {})),
            "phase_source_entities": {kind: dict(entities) for kind, entities in (phase_entities or {}).items()},
            "phase_discovery_method": self._phase_current_discovery_method,
            "phase_current_discovery_method": self._phase_current_discovery_method,
            "daily_max_phase_current_a": daily_max_phase_current_a,
            "daily_phase_max": daily_phase_max,
            "daily_max_phase": daily_max_phase,
        }
        self._history_summary = summary
        return {
            "success": True,
            "entity_id": entity_id,
            "date": date,
            "points": points,
            "history": summary,
            "phase_current_history": phase_current_history,
            "phase_history": phase_history,
            "daily_max_phase_current_a": daily_max_phase_current_a,
            "daily_phase_max": daily_phase_max,
            "daily_max_phase": daily_max_phase,
            "phase_current_source_entities": dict((phase_entities or {}).get("current", {})),
            "phase_source_entities": {kind: dict(entities) for kind, entities in (phase_entities or {}).items()},
            "phase_discovery_method": self._phase_current_discovery_method,
            "phase_current_discovery_method": self._phase_current_discovery_method,
        }
