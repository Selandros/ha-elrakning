"""Read-only SMHI weather context for solar intraday analysis."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components import weather
from homeassistant.core import EVENT_STATE_CHANGED, Event
from homeassistant.helpers import entity_registry as er


SMHI_DOMAIN = "smhi"
WEATHER_UPDATE_EVENT = "elrakning_solar_weather_update"
WEATHER_ATTRIBUTES = (
    "condition",
    "cloud_coverage",
    "temperature",
    "precipitation",
    "precipitation_probability",
)
FORECAST_ATTRIBUTES = (
    "datetime",
    "condition",
    "cloud_coverage",
    "temperature",
    "precipitation",
    "precipitation_probability",
)
SMHI_SENSOR_ROLES = {
    "total_cloud": "cloud_total",
    "low_cloud": "cloud_low",
    "medium_cloud": "cloud_medium",
    "high_cloud": "cloud_high",
    "thunder": "thunder_probability",
}
SMHI_CURRENT_DATASET = "smhi.current_weather.v1"
SMHI_HOURLY_DATASET = "smhi.hourly_forecast.v1"
SUN_CONTEXT_ATTRIBUTES = (
    "elevation",
    "azimuth",
    "rising",
    "next_rising",
    "next_setting",
    "next_dawn",
    "next_dusk",
    "next_noon",
    "next_midnight",
)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _copy_known(source: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    result: dict[str, Any] = {}
    for key in keys:
        value = source.get(key)
        if key == "datetime":
            if isinstance(value, str) and value:
                result[key] = value
        elif key == "condition":
            if isinstance(value, str) and value:
                result[key] = value
        elif (number := _number(value)) is not None:
            result[key] = number
    return result


def build_weather_targets(site_configs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Build site-explicit SMHI targets without changing legacy manager state."""
    targets: list[dict[str, Any]] = []
    for site_id in sorted(site_configs):
        config = site_configs[site_id]
        if not isinstance(config, dict) or config.get("collection_enabled", True) is not True:
            continue
        bindings = config.get("bindings")
        binding = bindings.get("weather") if isinstance(bindings, dict) else None
        if not isinstance(binding, dict) or binding.get("source") != "smhi":
            continue
        config_entry_id = binding.get("config_entry_id")
        if not isinstance(config_entry_id, str) or not config_entry_id.strip():
            continue
        entity_id = binding.get("weather_entity")
        if not isinstance(entity_id, str) or not entity_id:
            continue
        sensor_entities = binding.get("sensor_entities", {})
        if not isinstance(sensor_entities, dict):
            sensor_entities = {}
        targets.append({
            "site_id": site_id,
            "config_entry_id": config_entry_id,
            "weather_entity": entity_id,
            "sensor_entities": {str(role): str(entity) for role, entity in sensor_entities.items() if isinstance(role, str) and isinstance(entity, str)},
            "source": binding.get("source", "smhi"),
        })
    return targets


def normalize_current_weather(state: Any, sensor_states: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one current SMHI state without timestamps or provider defaults."""
    if state is None or str(getattr(state, "state", "")).lower() in {"unknown", "unavailable", ""}:
        return None
    current = _copy_known(getattr(state, "attributes", {}), WEATHER_ATTRIBUTES)
    condition = getattr(state, "state", None)
    if isinstance(condition, str) and condition and condition.lower() not in {"unknown", "unavailable"}:
        current["condition"] = condition
    if "cloud_coverage" in current:
        current["cloud_total"] = current["cloud_coverage"]
    for role, sensor in sensor_states.items():
        value = _number(getattr(sensor, "state", None)) if sensor is not None else None
        if value is not None:
            current[role] = value
    return current or None


def normalize_hourly_forecast(response: Any, timezone_name: str | None = None) -> dict[str, Any] | None:
    """Normalize a weather service response and reject ambiguous timestamps."""
    entity_response = response if isinstance(response, dict) else {}
    forecast = entity_response.get("forecast", []) if isinstance(entity_response, dict) else []
    if not isinstance(forecast, list) or not forecast:
        return None
    points: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    rejected_points = 0
    for index, raw in enumerate(forecast):
        item = _copy_known(raw, FORECAST_ATTRIBUTES)
        value = item.get("datetime")
        if not isinstance(value, str):
            gaps.append({"index": index, "reason": "malformed_timestamp"})
            rejected_points += 1
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            gaps.append({"index": index, "source_timestamp": value, "reason": "malformed_timestamp"})
            rejected_points += 1
            continue
        if parsed.tzinfo is None:
            gaps.append({"index": index, "source_timestamp": value, "reason": "naive_timestamp"})
            rejected_points += 1
            continue
        item["valid_at"] = parsed.astimezone(timezone.utc)
        item["source_timestamp"] = value
        item.pop("datetime", None)
        points.append(item)
    duplicate_targets = {
        valid_at for valid_at in {point["valid_at"] for point in points}
        if sum(point["valid_at"] == valid_at for point in points) > 1
    }
    if duplicate_targets:
        for valid_at in sorted(duplicate_targets):
            rejected_points += sum(point["valid_at"] == valid_at for point in points)
            gaps.append({"valid_at": valid_at.isoformat(), "reason": "duplicate_utc_target"})
        points = [point for point in points if point["valid_at"] not in duplicate_targets]
    if not points:
        return None
    return {"points": points, "quality_status": "good" if not gaps else "partial", "quality": {"status": "good" if not gaps else "partial", "gaps": gaps}, "rejected_points": rejected_points}


class SolarWeatherManager:
    """Consume one unambiguous Home Assistant SMHI weather entity."""

    def __init__(self, hass) -> None:
        self.hass = hass
        self._entity_id: str | None = None
        self._sensor_entities: dict[str, str] = {}
        self._watched_entity_ids: set[str] = set()
        self._state: dict[str, Any] = self._unavailable_state("unavailable")
        self._site_id: str | None = None
        self._site_context_enabled = False
        self._state_unsub = hass.bus.async_listen(EVENT_STATE_CHANGED, self._async_state_changed)
        self._sun_unsub = hass.bus.async_listen(EVENT_STATE_CHANGED, self._async_sun_changed)

    @staticmethod
    def _unavailable_state(status: str) -> dict[str, Any]:
        return {
            "available": False,
            "source": "smhi",
            "status": status,
            "current": {},
            "hourly_forecast": [],
            "discovery": {"config_entry_count": 0, "weather_entity": None, "sensor_roles": {}},
        }

    async def async_load(self) -> None:
        self._discover()
        await self._refresh()

    def discovered_binding(self) -> dict[str, Any] | None:
        """Return the explicit weather resource selected by discovery."""
        if not self._entity_id:
            return None
        entries = self.hass.config_entries.async_entries(SMHI_DOMAIN)
        if len(entries) != 1:
            return None
        return {
            "config_entry_id": entries[0].entry_id,
            "weather_entity": self._entity_id,
            "sensor_entities": dict(self._sensor_entities),
            "source": "smhi",
        }

    async def async_apply_site_context(self, site_id: str, binding: dict[str, Any] | None) -> None:
        """Switch live weather reads to one explicit site resource."""
        self._site_id = site_id if isinstance(binding, dict) else None
        self._site_context_enabled = True
        if self._site_id is None:
            self._entity_id = None
            self._sensor_entities = {}
            self._watched_entity_ids = set()
            self._state = self._unavailable_state("site_unconfigured")
            return
        self._entity_id = binding.get("weather_entity")
        self._sensor_entities = dict(binding.get("sensor_entities", {}))
        self._watched_entity_ids = {self._entity_id, *self._sensor_entities.values()}
        await self._refresh()
        self._state["site_id"] = self._site_id

    async def async_shutdown(self) -> None:
        if self._state_unsub:
            self._state_unsub()
            self._state_unsub = None
        if self._sun_unsub:
            self._sun_unsub()
            self._sun_unsub = None

    def _discover(self) -> None:
        entries = self.hass.config_entries.async_entries(SMHI_DOMAIN)
        if len(entries) != 1:
            self._entity_id = None
            self._sensor_entities = {}
            self._watched_entity_ids = set()
            self._state = self._unavailable_state("ambiguous" if len(entries) > 1 else "unavailable")
            return
        entry_id = entries[0].entry_id
        try:
            registry = er.async_get(self.hass)
        except Exception:
            self._entity_id = None
            self._sensor_entities = {}
            self._watched_entity_ids = set()
            self._state = self._unavailable_state("unavailable")
            return
        candidates = [
            entity.entity_id
            for entity in registry.entities.values()
            if getattr(entity, "config_entry_id", None) == entry_id
            and isinstance(getattr(entity, "entity_id", None), str)
            and entity.entity_id.startswith("weather.")
        ]
        if len(candidates) != 1:
            self._entity_id = None
            self._sensor_entities = {}
            self._watched_entity_ids = set()
            self._state = self._unavailable_state("ambiguous" if len(candidates) > 1 else "unavailable")
            return
        self._entity_id = candidates[0]
        sensor_entities: dict[str, str] = {}
        for entity in registry.entities.values():
            if getattr(entity, "config_entry_id", None) != entry_id:
                continue
            if getattr(entity, "domain", None) != "sensor":
                continue
            role = SMHI_SENSOR_ROLES.get(getattr(entity, "translation_key", None))
            entity_id = getattr(entity, "entity_id", None)
            if role and isinstance(entity_id, str) and role not in sensor_entities:
                sensor_entities[role] = entity_id
        self._sensor_entities = sensor_entities
        self._watched_entity_ids = {self._entity_id, *sensor_entities.values()}

    async def _refresh(self) -> None:
        if not self._entity_id:
            return
        state = self.hass.states.get(self._entity_id)
        if state is None or str(getattr(state, "state", "")).lower() in {"unknown", "unavailable", ""}:
            next_state = self._unavailable_state("current_unavailable")
        else:
            attributes = getattr(state, "attributes", {})
            current = _copy_known(attributes, WEATHER_ATTRIBUTES)
            if "cloud_coverage" in current:
                current["cloud_total"] = current["cloud_coverage"]
            for role, entity_id in self._sensor_entities.items():
                sensor = self.hass.states.get(entity_id)
                value = _number(getattr(sensor, "state", None)) if sensor is not None else None
                if value is not None:
                    current[role] = value
            next_state = {
                "available": bool(current),
                "source": "smhi",
                "status": "current_loaded" if current else "current_unavailable",
                "current": current,
                "hourly_forecast": [],
                "discovery": {
                    "config_entry_count": 1,
                    "weather_entity": self._entity_id,
                    "sensor_roles": dict(self._sensor_entities),
                },
            }
            try:
                response = await self.hass.services.async_call(
                    weather.DOMAIN,
                    weather.SERVICE_GET_FORECASTS,
                    {"entity_id": self._entity_id, "type": "hourly"},
                    blocking=True,
                    return_response=True,
                )
                entity_response = response.get(self._entity_id, {}) if isinstance(response, dict) else {}
                forecast = entity_response.get("forecast", []) if isinstance(entity_response, dict) else []
                if isinstance(forecast, list):
                    next_state["hourly_forecast"] = [
                        item for raw in forecast
                        if (item := _copy_known(raw, FORECAST_ATTRIBUTES))
                    ]
                    if next_state["hourly_forecast"]:
                        next_state["status"] = "hourly_loaded"
            except Exception:
                pass
        if next_state != self._state:
            self._state = next_state
            self.hass.bus.async_fire(WEATHER_UPDATE_EVENT)

    async def _async_state_changed(self, event: Event) -> None:
        if getattr(self, "_site_context_enabled", False) and getattr(self, "_site_id", None) is None:
            return
        if event.data.get("entity_id") in self._watched_entity_ids:
            await self._refresh()

    async def _async_sun_changed(self, event: Event) -> None:
        if getattr(self, "_site_context_enabled", False) and getattr(self, "_site_id", None) is None:
            return
        if event.data.get("entity_id") == "sun.sun":
            self.hass.bus.async_fire(WEATHER_UPDATE_EVENT)

    def public_state(self) -> dict[str, Any]:
        return {
            "available": self._state["available"],
            "source": self._state["source"],
            "status": self._state["status"],
            "current": dict(self._state["current"]),
            "hourly_forecast": [dict(item) for item in self._state["hourly_forecast"]],
            "discovery": dict(self._state.get("discovery", {})),
        }


def build_intraday_observation(actual_so_far_kwh: float | None, expected_so_far_kwh: float | None) -> dict[str, float | str | None]:
    """Expose a bounded observation without modifying Forecast.Solar expectations."""
    actual = _number(actual_so_far_kwh)
    expected = _number(expected_so_far_kwh)
    if actual is None or expected is None or expected <= 0:
        return {"status": "unavailable", "bias": None}
    return {"status": "observation_only", "bias": max(0.5, min(actual / expected, 1.5))}


def build_sun_context(hass) -> dict[str, Any]:
    """Read only the attributes exposed by Home Assistant's normal sun entity."""
    state = hass.states.get("sun.sun")
    if state is None or str(getattr(state, "state", "")).lower() in {"unknown", "unavailable", ""}:
        return {"available": False, "entity_id": "sun.sun"}
    context: dict[str, Any] = {"available": True, "entity_id": "sun.sun", "state": str(state.state)}
    attributes = getattr(state, "attributes", {})
    for key in SUN_CONTEXT_ATTRIBUTES:
        value = attributes.get(key)
        if key in {"elevation", "azimuth"}:
            value = _number(value)
        elif key == "rising":
            value = value if isinstance(value, bool) else None
        elif isinstance(value, str):
            value = value or None
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        else:
            value = None
        if value is not None:
            context[key] = value
    return context
