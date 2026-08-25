"""Shared power-series configuration and Recorder access."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from functools import partial
from typing import Any

from homeassistant.core import EVENT_STATE_CHANGED, Event, State, valid_entity_id
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .meter import _power_kw


STORE_KEY = "elrakning.power"
POWER_FIELDS = (
    "consumption_entity",
    "charging_entity",
    "discharging_entity",
    "soc_entity",
    "capacity_entity",
)
POWER_UPDATE_EVENT = "elrakning_power_update"


def _clean_entity(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _positive_power(state: State | Any) -> float | None:
    value = _power_kw(state)
    return abs(value) if value is not None else None


def _state_number(state: State | Any, units: set[str], divisor: float = 1) -> float | None:
    if state is None:
        return None
    unit = str(getattr(state, "attributes", {}).get("unit_of_measurement", "")).lower()
    if unit not in units:
        return None
    try:
        value = float(state.state) / divisor
    except (TypeError, ValueError):
        return None
    return value if value == value and value not in (float("inf"), float("-inf")) else None


def _power_history_point(state: State | Any) -> dict[str, Any] | None:
    value = _positive_power(state)
    timestamp = getattr(state, "last_updated", None)
    if value is None or timestamp is None:
        return None
    return {"timestamp": timestamp.isoformat(), "value_kw": value}


class PowerManager:
    """Persist selected power sensors and expose live/history series."""

    def __init__(self, hass, diagnostic_callback: Callable[..., Awaitable[None]] | None = None) -> None:
        self.hass = hass
        self._diagnostic_callback = diagnostic_callback
        self.store = Store(hass, 1, STORE_KEY)
        self.mapping: dict[str, Any] = {"solar_entities": [], **{field: None for field in POWER_FIELDS}}
        self._history_inflight: dict[tuple[str, str], asyncio.Task] = {}
        self._state_unsub = hass.bus.async_listen(EVENT_STATE_CHANGED, self._async_state_changed)

    async def _async_state_changed(self, event: Event) -> None:
        entity_id = event.data.get("entity_id")
        selected = set(self.mapping.get("solar_entities", [])) | {
            value for field, value in self.mapping.items() if field != "solar_entities" and value
        }
        if entity_id not in selected:
            return
        state = await self.async_state()
        new_state = event.data.get("new_state")
        timestamp = getattr(new_state, "last_updated", None)
        points = []
        if entity_id in self.mapping.get("solar_entities", []):
            point = {"timestamp": timestamp.isoformat(), "value_kw": state["solar_kw"]} if timestamp and state.get("solar_kw") is not None else None
            if point:
                points.append({"series": "solar", "point": point})
        for field, series in (
            ("consumption_entity", "consumption"),
            ("charging_entity", "charging"),
            ("discharging_entity", "discharging"),
        ):
            if entity_id == self.mapping.get(field):
                value = state.get(f"{series}_kw")
                if timestamp and value is not None:
                    points.append({"series": series, "point": {"timestamp": timestamp.isoformat(), "value_kw": value}})
        self.hass.bus.async_fire(
            POWER_UPDATE_EVENT,
            {"entity_id": entity_id, "state": state, "points": points},
        )

    async def async_shutdown(self) -> None:
        for task in self._history_inflight.values():
            task.cancel()
        self._history_inflight.clear()
        if self._state_unsub:
            self._state_unsub()
            self._state_unsub = None

    async def async_load(self) -> None:
        cached = await self.store.async_load()
        if not isinstance(cached, dict):
            return
        solar = cached.get("solar_entities", [])
        self.mapping["solar_entities"] = list(dict.fromkeys(
            value for value in solar if isinstance(value, str) and value.strip()
        )) if isinstance(solar, list) else []
        for field in POWER_FIELDS:
            self.mapping[field] = _clean_entity(cached.get(field))

    async def async_save_mapping(self, mapping: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(mapping, dict):
            raise ValueError("invalid_mapping")
        solar = mapping.get("solar_entities", [])
        if not isinstance(solar, list):
            raise ValueError("invalid_solar_entities")
        selected_solar = list(dict.fromkeys(_clean_entity(value) for value in solar))
        selected_solar = [value for value in selected_solar if value]
        selected = {"solar_entities": selected_solar}
        selected.update({field: _clean_entity(mapping.get(field)) for field in POWER_FIELDS})
        for entity_id in selected_solar:
            if not valid_entity_id(entity_id):
                raise ValueError(f"invalid_entity_id:{entity_id}")
            state = self.hass.states.get(entity_id)
            if state is None:
                raise ValueError(f"entity_not_found:{entity_id}")
            self._validate_unit(entity_id, state, True, "solar_entities")
        for field in POWER_FIELDS:
            entity_id = selected[field]
            if not entity_id:
                continue
            if not valid_entity_id(entity_id):
                raise ValueError(f"invalid_entity_id:{field}")
            state = self.hass.states.get(entity_id)
            if state is None:
                raise ValueError(f"entity_not_found:{field}")
            self._validate_unit(entity_id, state, field in {"consumption_entity", "charging_entity", "discharging_entity"}, field)
        self.mapping = selected
        await self.store.async_save(self.mapping)
        return await self.async_state()

    @staticmethod
    def _validate_unit(entity_id: str, state: State | Any, power: bool, field: str | None) -> None:
        unit = str(getattr(state, "attributes", {}).get("unit_of_measurement", "")).lower()
        if power and unit not in {"w", "kw", "mw"}:
            raise ValueError(f"invalid_power_unit:{entity_id}")
        if field == "soc_entity":
            if unit not in {"%", "percent"}:
                raise ValueError(f"invalid_soc_unit:{entity_id}")
        if field == "capacity_entity" and unit not in {"wh", "kwh", "mwh"}:
            raise ValueError(f"invalid_capacity_unit:{entity_id}")

    async def async_state(self) -> dict[str, Any]:
        solar_values = [_positive_power(self.hass.states.get(entity_id)) for entity_id in self.mapping["solar_entities"]]
        solar_values = [value for value in solar_values if value is not None]
        result = {**self.mapping, "configured": any(self.mapping["solar_entities"]) or any(self.mapping[field] for field in POWER_FIELDS)}
        result.update({
            "solar_kw": sum(solar_values) if solar_values else None,
            "consumption_kw": self._power_value("consumption_entity"),
            "charging_kw": self._power_value("charging_entity"),
            "discharging_kw": self._power_value("discharging_entity"),
            "soc_percent": self._attribute_value("soc_entity", {"%", "percent"}),
            "capacity_kwh": self._capacity_kwh(),
        })
        return result

    def _power_value(self, field: str) -> float | None:
        entity_id = self.mapping.get(field)
        return _positive_power(self.hass.states.get(entity_id)) if entity_id else None

    def _attribute_value(self, field: str, units: set[str]) -> float | None:
        entity_id = self.mapping.get(field)
        return _state_number(self.hass.states.get(entity_id), units) if entity_id else None

    def _capacity_kwh(self) -> float | None:
        entity_id = self.mapping.get("capacity_entity")
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None:
            return None
        unit = str(getattr(state, "attributes", {}).get("unit_of_measurement", "")).lower()
        divisor = 1000 if unit == "wh" else 1 if unit == "kwh" else 0.001 if unit == "mwh" else None
        return _state_number(state, {"wh", "kwh", "mwh"}, divisor) if divisor else None

    async def async_history(self) -> dict[str, Any]:
        now = dt_util.now()
        start = dt_util.start_of_local_day(now)
        end = dt_util.start_of_local_day(now + timedelta(days=1))
        date = start.date().isoformat()
        mapping = {
            "solar_entities": list(self.mapping.get("solar_entities", [])),
            **{field: self.mapping.get(field) for field in POWER_FIELDS},
        }
        power_entities = list(dict.fromkeys([
            *mapping["solar_entities"],
            *(mapping[field] for field in ("consumption_entity", "charging_entity", "discharging_entity") if mapping.get(field)),
        ]))
        if not power_entities:
            return {
                "success": True,
                "date": date,
                "series": {key: {"points": []} for key in ("solar", "consumption", "charging", "discharging")},
            }
        mapping_key = "|".join(
            [f"solar={','.join(mapping['solar_entities'])}"]
            + [f"{field}={mapping.get(field) or ''}" for field in POWER_FIELDS]
        )
        key = (mapping_key, date)
        task = self._history_inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._async_history_fetch(power_entities, mapping, start, end, date))
            self._history_inflight[key] = task
            task.add_done_callback(lambda completed, request_key=key: self._history_inflight.pop(request_key, None) if self._history_inflight.get(request_key) is completed else None)
        return await asyncio.shield(task)

    async def _async_history_fetch(self, entities: list[str], mapping: dict[str, Any], start, end, date: str) -> dict[str, Any]:
        try:
            from homeassistant.components.recorder import get_instance, history

            recorder = get_instance(self.hass)
            history_by_entity = await recorder.async_add_executor_job(partial(
                history.get_significant_states,
                self.hass,
                start,
                end,
                entity_ids=entities,
                include_start_time_state=True,
                significant_changes_only=False,
                minimal_response=False,
                no_attributes=False,
            ))
        except Exception:
            return {"success": False, "date": date, "series": {}, "error": "history_unavailable"}
        raw = {}
        for entity_id in entities:
            raw[entity_id] = [point for state in history_by_entity.get(entity_id, []) if (point := _power_history_point(state))]
        solar_entities = mapping.get("solar_entities", [])
        series = {
            "solar": {"points": self._sum_solar_history(solar_entities, raw)},
            "consumption": {"points": self._points_for_entity(mapping.get("consumption_entity"), raw)},
            "charging": {"points": self._points_for_entity(mapping.get("charging_entity"), raw)},
            "discharging": {"points": self._points_for_entity(mapping.get("discharging_entity"), raw)},
        }
        return {"success": True, "date": date, "series": series}

    @staticmethod
    def _points_for_entity(entity_id: str | None, raw: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        return raw.get(entity_id, []) if entity_id else []

    @staticmethod
    def _sum_solar_history(entity_ids: list[str], raw: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        cursors = {entity_id: 0 for entity_id in entity_ids}
        timelines = {entity_id: raw.get(entity_id, []) for entity_id in entity_ids}
        timestamps = sorted({point["timestamp"] for points in timelines.values() for point in points})
        result = []
        for timestamp in timestamps:
            total = 0.0
            known = False
            for entity_id, points in timelines.items():
                while cursors[entity_id] < len(points) and points[cursors[entity_id]]["timestamp"] <= timestamp:
                    cursors[entity_id] += 1
                if cursors[entity_id]:
                    total += points[cursors[entity_id] - 1]["value_kw"]
                    known = True
            if known:
                result.append({"timestamp": timestamp, "value_kw": total})
        return result
