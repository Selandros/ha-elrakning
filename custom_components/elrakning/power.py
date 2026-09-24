"""Shared power-series configuration and Recorder access."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, time, timedelta, timezone
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
    "battery_power_entity",
    "soc_entity",
    "capacity_entity",
)
POWER_UPDATE_EVENT = "elrakning_power_update"
SOLAR_ARRAY_METADATA_KEY = "solar_array_metadata"


def _clean_entity(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _positive_power(state: State | Any) -> float | None:
    value = _power_kw(state)
    return abs(value) if value is not None else None


def _split_signed_power(value: float | None, invert: bool = False) -> tuple[float | None, float | None]:
    if value is None:
        return None, None
    signed = -value if invert else value
    return max(signed, 0), max(-signed, 0)


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


def _signed_power_history_point(state: State | Any, invert: bool = False) -> dict[str, Any] | None:
    value = _power_kw(state)
    timestamp = getattr(state, "last_updated", None)
    if value is None or timestamp is None:
        return None
    return {"timestamp": timestamp.isoformat(), "value_kw": -value if invert else value}


def _soc_history_point(state: State | Any) -> dict[str, Any] | None:
    value = _state_number(state, {"%", "percent"})
    timestamp = getattr(state, "last_updated", None)
    if value is None or timestamp is None:
        return None
    return {"timestamp": timestamp.isoformat(), "value_percent": value}


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _integrate_solar_points(points: list[dict[str, Any]], start, end) -> float | None:
    """Integrate known solar power samples without extrapolating beyond the last sample."""
    samples = []
    for point in points:
        timestamp = dt_util.parse_datetime(point.get("timestamp"))
        value = _finite_number(point.get("value_kw"))
        if timestamp is not None and value is not None:
            samples.append((dt_util.as_local(timestamp), value))
    samples.sort(key=lambda item: item[0])
    if len(samples) < 2:
        return 0.0 if samples else None
    total = 0.0
    for (left_time, left_value), (right_time, right_value) in zip(samples, samples[1:]):
        segment_start = max(left_time, start)
        segment_end = min(right_time, end)
        if segment_end <= segment_start:
            continue
        total += (left_value + right_value) / 2 * (segment_end - segment_start).total_seconds() / 3600
    return total


def _normalize_solar_array_metadata(metadata: Any, selected: list[str]) -> dict[str, dict[str, Any]]:
    """Keep optional PV metadata aligned with the selected solar entities."""
    if not isinstance(metadata, dict):
        return {}
    normalized = {}
    for entity_id in selected:
        item = metadata.get(entity_id)
        if not isinstance(item, dict):
            continue
        try:
            clean = _validate_solar_array_metadata(entity_id, item)
        except ValueError:
            continue
        if clean:
            normalized[entity_id] = clean
    return normalized


def _validate_solar_array_metadata(entity_id: str, metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise ValueError(f"invalid_solar_array_metadata:{entity_id}")
    clean = {}
    if "capacity_kwp" in metadata:
        capacity = _finite_number(metadata["capacity_kwp"])
        if capacity is None or capacity <= 0:
            raise ValueError(f"invalid_solar_capacity_kwp:{entity_id}")
        clean["capacity_kwp"] = capacity
    if "panel_count" in metadata and metadata["panel_count"] not in (None, ""):
        panel_count = _finite_number(metadata["panel_count"])
        if panel_count is None or panel_count <= 0 or panel_count != int(panel_count):
            raise ValueError(f"invalid_solar_panel_count:{entity_id}")
        clean["panel_count"] = int(panel_count)
    for key, low, high in (("tilt_deg", 0, 90), ("azimuth_deg", 0, 360)):
        if key in metadata:
            value = _finite_number(metadata[key])
            if value is None or value < low or value > high:
                raise ValueError(f"invalid_solar_{key}:{entity_id}")
            clean[key] = value
    return clean


def solar_incidence_factor(elevation_deg: float, sun_azimuth_deg: float, tilt_deg: float, panel_azimuth_deg: float) -> float:
    """Return the non-negative geometric incidence factor for one PV array."""
    import math

    if elevation_deg <= 0:
        return 0.0
    elevation = math.radians(elevation_deg)
    tilt = math.radians(tilt_deg)
    azimuth_delta = math.radians(sun_azimuth_deg - panel_azimuth_deg)
    return max(0.0, math.sin(elevation) * math.cos(tilt) + math.cos(elevation) * math.sin(tilt) * math.cos(azimuth_delta))


class PowerManager:
    """Persist selected power sensors and expose live/history series."""

    def __init__(self, hass, diagnostic_callback: Callable[..., Awaitable[None]] | None = None) -> None:
        self.hass = hass
        self._diagnostic_callback = diagnostic_callback
        self._mapping_changed_callback = None
        self.store = Store(hass, 1, STORE_KEY)
        self.mapping: dict[str, Any] = {"solar_entities": [], SOLAR_ARRAY_METADATA_KEY: {}, **{field: None for field in POWER_FIELDS}, "invert_battery_power": False}
        self._history_inflight: dict[tuple[str, str, int], asyncio.Task] = {}
        self._history_cache: dict[tuple[str, str, int], dict[str, Any]] = {}
        self._history_cache_epoch = 0
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
        entity_id = event.data.get("entity_id")
        selected = set(self.mapping.get("solar_entities", [])) | {
            value for field, value in self.mapping.items()
            if field not in {"solar_entities", SOLAR_ARRAY_METADATA_KEY} and isinstance(value, str) and value
        }
        if entity_id not in selected:
            return
        # Live points are merged by the frontend; keep the expensive Recorder
        # snapshot reusable until the mapping or period changes.
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
        if entity_id == self.mapping.get("battery_power_entity"):
            charging, discharging = _split_signed_power(
                _power_kw(new_state),
                bool(self.mapping.get("invert_battery_power")),
            )
            if timestamp and charging is not None and discharging is not None:
                points.extend([
                    {"series": "charging", "point": {"timestamp": timestamp.isoformat(), "value_kw": charging}},
                    {"series": "discharging", "point": {"timestamp": timestamp.isoformat(), "value_kw": discharging}},
                ])
        if entity_id == self.mapping.get("soc_entity"):
            value = state.get("soc_percent")
            if timestamp and value is not None:
                points.append({"series": "soc", "point": {"timestamp": timestamp.isoformat(), "value_percent": value}})
        self.hass.bus.async_fire(
            POWER_UPDATE_EVENT,
            {"entity_id": entity_id, "state": state, "points": points},
        )

    async def async_shutdown(self) -> None:
        for task in self._history_inflight.values():
            task.cancel()
        self._history_inflight.clear()
        self._history_cache.clear()
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
        self.mapping[SOLAR_ARRAY_METADATA_KEY] = _normalize_solar_array_metadata(
            cached.get(SOLAR_ARRAY_METADATA_KEY), self.mapping["solar_entities"]
        )
        for field in POWER_FIELDS:
            self.mapping[field] = _clean_entity(cached.get(field))
        self.mapping["invert_battery_power"] = cached.get("invert_battery_power") is True

    async def async_restore_mapping(self, mapping: dict[str, Any] | None) -> None:
        """Restore a previously validated site mapping without rediscovering sources."""
        for task in self._history_inflight.values():
            task.cancel()
        self._history_inflight.clear()
        self._history_cache_epoch += 1
        self._history_cache.clear()
        mapping = mapping if isinstance(mapping, dict) else {}
        solar = mapping.get("solar_entities", [])
        solar = solar if isinstance(solar, list) else []
        selected_solar = list(dict.fromkeys(_clean_entity(value) for value in solar))
        selected_solar = [value for value in selected_solar if value]
        selected = {
            "solar_entities": selected_solar,
            SOLAR_ARRAY_METADATA_KEY: _normalize_solar_array_metadata(
                mapping.get(SOLAR_ARRAY_METADATA_KEY), selected_solar
            ),
            **{field: _clean_entity(mapping.get(field)) for field in POWER_FIELDS},
            "invert_battery_power": mapping.get("invert_battery_power") is True,
        }
        if selected["battery_power_entity"]:
            selected["charging_entity"] = None
            selected["discharging_entity"] = None
        else:
            selected["battery_power_entity"] = None
        self.mapping = selected
        self._history_cache_epoch += 1
        self._history_cache.clear()
        await self.store.async_save(self.mapping)

    async def async_save_mapping(self, mapping: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(mapping, dict):
            raise ValueError("invalid_mapping")
        solar = mapping.get("solar_entities", [])
        if not isinstance(solar, list):
            raise ValueError("invalid_solar_entities")
        selected_solar = list(dict.fromkeys(_clean_entity(value) for value in solar))
        selected_solar = [value for value in selected_solar if value]
        selected_metadata = {}
        supplied_metadata = mapping.get(SOLAR_ARRAY_METADATA_KEY, {})
        if supplied_metadata is not None and not isinstance(supplied_metadata, dict):
            raise ValueError("invalid_solar_array_metadata")
        for entity_id in selected_solar:
            if isinstance(supplied_metadata, dict) and entity_id in supplied_metadata:
                selected_metadata[entity_id] = _validate_solar_array_metadata(entity_id, supplied_metadata[entity_id])
        selected = {"solar_entities": selected_solar, SOLAR_ARRAY_METADATA_KEY: selected_metadata}
        selected.update({field: _clean_entity(mapping.get(field)) for field in POWER_FIELDS})
        invert_battery_power = mapping.get("invert_battery_power", False)
        if not isinstance(invert_battery_power, bool):
            raise ValueError("invalid_invert_battery_power")
        selected["invert_battery_power"] = invert_battery_power
        if selected["battery_power_entity"]:
            selected["charging_entity"] = None
            selected["discharging_entity"] = None
        else:
            selected["battery_power_entity"] = None
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
            self._validate_unit(entity_id, state, field in {"consumption_entity", "charging_entity", "discharging_entity", "battery_power_entity"}, field)
        self.mapping = selected
        self._history_cache_epoch += 1
        self._history_cache.clear()
        await self.store.async_save(self.mapping)
        await self._notify_mapping_changed()
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
        metadata = self.mapping.get(SOLAR_ARRAY_METADATA_KEY, {})
        result["solar_total_capacity_kwp"] = sum(
            _finite_number(item.get("capacity_kwp")) or 0 for item in metadata.values() if isinstance(item, dict)
        ) or None
        result["solar_total_panel_count"] = sum(
            int(_finite_number(item.get("panel_count"))) for item in metadata.values()
            if isinstance(item, dict) and _finite_number(item.get("panel_count")) is not None
        ) or None
        result.update({
            "solar_kw": sum(solar_values) if solar_values else None,
            "consumption_kw": self._power_value("consumption_entity"),
            "charging_kw": self._battery_power_value("charging"),
            "discharging_kw": self._battery_power_value("discharging"),
            "soc_percent": self._attribute_value("soc_entity", {"%", "percent"}),
            "capacity_kwh": self._capacity_kwh(),
        })
        return result

    def _power_value(self, field: str) -> float | None:
        entity_id = self.mapping.get(field)
        return _positive_power(self.hass.states.get(entity_id)) if entity_id else None

    def _battery_power_value(self, direction: str) -> float | None:
        entity_id = self.mapping.get("battery_power_entity")
        if entity_id:
            charging, discharging = _split_signed_power(
                _power_kw(self.hass.states.get(entity_id)),
                bool(self.mapping.get("invert_battery_power")),
            )
            return charging if direction == "charging" else discharging
        return self._power_value(f"{direction}_entity")

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

    async def async_history(self, days: int = 1) -> dict[str, Any]:
        now = dt_util.now()
        days = max(1, min(7, int(days)))
        current_day_start = dt_util.start_of_local_day(now)
        start = dt_util.start_of_local_day(now - timedelta(days=days - 1))
        end = dt_util.start_of_local_day(current_day_start + timedelta(days=1))
        date = current_day_start.date().isoformat()
        mapping = {
            "solar_entities": list(self.mapping.get("solar_entities", [])),
            SOLAR_ARRAY_METADATA_KEY: dict(self.mapping.get(SOLAR_ARRAY_METADATA_KEY, {})),
            **{field: self.mapping.get(field) for field in POWER_FIELDS},
            "invert_battery_power": bool(self.mapping.get("invert_battery_power")),
        }
        power_entities = list(dict.fromkeys([
            *mapping["solar_entities"],
            *(mapping[field] for field in ("consumption_entity", "charging_entity", "discharging_entity", "battery_power_entity") if mapping.get(field)),
            *([mapping["soc_entity"]] if mapping.get("soc_entity") else []),
        ]))
        if not power_entities:
            return {
                "success": True,
                "date": date,
                "series": {key: {"points": []} for key in ("solar", "consumption", "charging", "discharging", "soc")},
            }
        mapping_key = "|".join(
            [f"solar={','.join(mapping['solar_entities'])}"]
            + [f"solar_array_metadata={mapping.get(SOLAR_ARRAY_METADATA_KEY) or {}}"]
            + [f"{field}={mapping.get(field) or ''}" for field in POWER_FIELDS]
            + [f"invert_battery_power={bool(mapping.get('invert_battery_power'))}"]
        )
        key = (mapping_key, date, days)
        cached = self._history_cache.get(key)
        if cached is not None:
            return cached
        task = self._history_inflight.get(key)
        if task is None:
            cache_epoch = self._history_cache_epoch
            task = asyncio.create_task(self._async_history_fetch(power_entities, mapping, start, end, date))
            self._history_inflight[key] = task
            def complete(completed, request_key=key, request_epoch=cache_epoch):
                if self._history_inflight.get(request_key) is completed:
                    self._history_inflight.pop(request_key, None)
                if not completed.cancelled() and completed.exception() is None and request_epoch == self._history_cache_epoch:
                    result = completed.result()
                    if isinstance(result, dict) and result.get("success") is True:
                        self._history_cache[request_key] = result
            task.add_done_callback(complete)
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
        battery_entity = mapping.get("battery_power_entity")
        soc_entity = mapping.get("soc_entity")
        invert_battery_power = bool(mapping.get("invert_battery_power"))
        for entity_id in entities:
            point_builder = _soc_history_point if entity_id == soc_entity else (_signed_power_history_point if entity_id == battery_entity else _power_history_point)
            raw[entity_id] = [
                point for state in history_by_entity.get(entity_id, [])
                if (point := point_builder(state, invert_battery_power) if entity_id == battery_entity else point_builder(state))
            ]
        solar_entities = mapping.get("solar_entities", [])
        series = {
            "solar": {"points": self._sum_solar_history(solar_entities, raw)},
            "consumption": {"points": self._points_for_entity(mapping.get("consumption_entity"), raw)},
            "charging": {"points": self._battery_history_points("charging", mapping, raw)},
            "discharging": {"points": self._battery_history_points("discharging", mapping, raw)},
            "soc": {"points": self._points_for_entity(soc_entity, raw)},
        }
        result = {"success": True, "date": date, "series": series}
        hass_data = getattr(self.hass, "data", {})
        forecast = hass_data.get("elrakning", {}).get("solar_forecast_manager") if isinstance(hass_data, dict) else None
        weather_manager = hass_data.get("elrakning", {}).get("solar_weather_manager") if isinstance(hass_data, dict) else None
        forecast_facts = forecast.public_state() if forecast else {"available": False}
        weather_context = weather_manager.public_state() if weather_manager else {"available": False, "hourly_forecast": []}
        result["solar_analysis"] = self._solar_analysis(
            series["solar"]["points"], start, now=dt_util.now(),
            forecast=forecast_facts, weather=weather_context,
        )
        return result

    def _solar_analysis(self, actual_points: list[dict[str, Any]], start, now, forecast=None, weather=None) -> dict[str, Any]:
        """Build daily clear-sky geometry facts from the shared solar history."""
        metadata = self.mapping.get(SOLAR_ARRAY_METADATA_KEY, {})
        entities = self.mapping.get("solar_entities", [])
        complete = bool(entities) and all(
            isinstance(metadata.get(entity_id), dict)
            and all(_finite_number(metadata[entity_id].get(key)) is not None for key in ("capacity_kwp", "tilt_deg", "azimuth_deg"))
            for entity_id in entities
        )
        sun_state = self.hass.states.get("sun.sun")
        if sun_state is None or not complete:
            return {"available": False, "sun_available": sun_state is not None, "days": []}
        try:
            from astral.sun import azimuth, elevation
            from homeassistant.helpers.sun import get_astral_observer
            observer = get_astral_observer(self.hass)
        except Exception:
            return {"available": False, "sun_available": True, "days": []}

        local_now = dt_util.as_local(now)
        today = local_now.date()
        points_by_day = {}
        for point in actual_points:
            timestamp = dt_util.parse_datetime(point.get("timestamp"))
            if timestamp is not None:
                points_by_day.setdefault(dt_util.as_local(timestamp).date(), []).append(point)
        days = []
        for offset in range(6, -1, -1):
            day = today - timedelta(days=offset)
            day_start = datetime.combine(day, time.min, tzinfo=local_now.tzinfo)
            day_end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=local_now.tzinfo)
            limit = day_end if day < today else min(day_end, local_now)
            if day == today and points_by_day.get(day):
                latest = max(dt_util.parse_datetime(point["timestamp"]) for point in points_by_day[day] if dt_util.parse_datetime(point["timestamp"]) is not None)
                limit = min(limit, latest)
            reference = 0.0
            if limit > day_start:
                previous = None
                cursor = day_start
                while cursor <= limit:
                    sun_elevation = elevation(observer, cursor)
                    sun_azimuth = azimuth(observer, cursor)
                    power = sum(
                        (_finite_number(metadata[entity_id]["capacity_kwp"]) or 0)
                        * solar_incidence_factor(
                            sun_elevation,
                            sun_azimuth,
                            _finite_number(metadata[entity_id]["tilt_deg"]) or 0,
                            _finite_number(metadata[entity_id]["azimuth_deg"]) or 0,
                        ) for entity_id in entities
                    )
                    if previous is not None:
                        reference += (previous + power) / 2 * (5 / 60)
                    previous = power
                    cursor = dt_util.as_local(cursor.astimezone(timezone.utc) + timedelta(minutes=5))
            days.append({"date": day.isoformat(), "reference_energy_kwh": reference})
        return {
            "available": True,
            "sun_available": True,
            "days": days,
            "intraday": self._solar_intraday_analysis(actual_points, local_now, forecast or {}, weather or {}, observer),
        }

    def _solar_intraday_analysis(self, actual_points, local_now, forecast, weather, observer):
        """Calculate observations and daylight-filtered weather context only."""
        day_start = datetime.combine(local_now.date(), time.min, tzinfo=local_now.tzinfo)
        today_points = [
            point for point in actual_points
            if (timestamp := dt_util.parse_datetime(point.get("timestamp"))) is not None
            and dt_util.as_local(timestamp).date() == local_now.date()
            and _finite_number(point.get("value_kw")) is not None
        ]
        actual_so_far = _integrate_solar_points(today_points, day_start, local_now)
        raw_day_forecast = _finite_number(forecast.get("today_kwh"))
        remaining = _finite_number(forecast.get("remaining_today_kwh"))
        expected_so_far = raw_day_forecast - remaining if raw_day_forecast is not None and remaining is not None else None
        performance_ratio = actual_so_far / expected_so_far if expected_so_far is not None and expected_so_far >= 1 and actual_so_far is not None else None
        power_now = _finite_number(forecast.get("power_now_kw"))
        actual_power_now = _finite_number(today_points[-1].get("value_kw")) if today_points else None
        power_ratio = actual_power_now / power_now if power_now is not None and power_now >= 0.1 and actual_power_now is not None else None
        sun_state = self.hass.states.get("sun.sun")
        sun_attributes = getattr(sun_state, "attributes", {}) if sun_state else {}
        elevation_now = _finite_number(sun_attributes.get("elevation"))
        hourly = weather.get("hourly_forecast") if isinstance(weather, dict) else []
        daylight_cloud = []
        next_three_hours = local_now + timedelta(hours=3)
        for item in hourly if isinstance(hourly, list) else []:
            timestamp = dt_util.parse_datetime(item.get("datetime")) if isinstance(item, dict) else None
            cloud = _finite_number(item.get("cloud_total", item.get("cloud_coverage"))) if isinstance(item, dict) else None
            if timestamp is None or cloud is None:
                continue
            timestamp = dt_util.as_local(timestamp)
            if timestamp <= local_now:
                continue
            try:
                sun_elevation = elevation(observer, timestamp)
            except Exception:
                continue
            if sun_elevation > 0:
                daylight_cloud.append({"timestamp": timestamp, "cloud": cloud, "weight": max(sun_elevation, 0.1)})

        def weighted_cloud(items):
            if not items:
                return None
            return sum(item["cloud"] * item["weight"] for item in items) / sum(item["weight"] for item in items)

        weighted_next = weighted_cloud([item for item in daylight_cloud if item["timestamp"] <= next_three_hours])
        weighted_remaining = weighted_cloud(daylight_cloud)
        return {
            "actual_so_far_kwh": actual_so_far,
            "raw_day_forecast_kwh": raw_day_forecast,
            "raw_expected_so_far_kwh": expected_so_far,
            "performance_ratio": performance_ratio,
            "performance_delta_percent": (performance_ratio - 1) * 100 if performance_ratio is not None else None,
            "actual_power_now_kw": actual_power_now,
            "forecast_power_now_kw": power_now,
            "power_performance_ratio": power_ratio,
            "sun_elevation_now": elevation_now,
            "cloud_now": _finite_number((weather.get("current") or {}).get("cloud_total", (weather.get("current") or {}).get("cloud_coverage"))),
            "production_weighted_cloud_next_3h": weighted_next,
            "production_weighted_cloud_remaining": weighted_remaining,
            "cloud_weighting_method": "solar_elevation" if weighted_remaining is not None else "unavailable",
            "daylight_hour_count": len(daylight_cloud),
        }

    @staticmethod
    def _battery_history_points(direction: str, mapping: dict[str, Any], raw: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        battery_entity = mapping.get("battery_power_entity")
        if battery_entity:
            points = raw.get(battery_entity, [])
            if direction == "charging":
                return [{**point, "value_kw": max(point["value_kw"], 0)} for point in points]
            return [{**point, "value_kw": max(-point["value_kw"], 0)} for point in points]
        return PowerManager._points_for_entity(mapping.get(f"{direction}_entity"), raw)

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
