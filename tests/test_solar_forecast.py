import asyncio
import sys
import types
import unittest
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_module():
    homeassistant = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    storage = types.ModuleType("homeassistant.helpers.storage")
    util = types.ModuleType("homeassistant.util")
    dt_module = types.ModuleType("homeassistant.util.dt")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    core.EVENT_STATE_CHANGED = "state_changed"
    core.Event = object
    fixed_now = datetime(2026, 8, 29, 12, tzinfo=timezone.utc)
    dt_module.now = lambda: fixed_now
    dt_module.as_local = lambda value: value

    class Store:
        def __init__(self, *args):
            self.data = None

        async def async_load(self):
            return self.data

        async def async_save(self, data):
            self.data = data

    storage.Store = Store
    helpers.storage = storage
    helpers.entity_registry = entity_registry
    util.dt = dt_module
    homeassistant.core = core
    homeassistant.helpers = helpers
    homeassistant.util = util
    modules = {
        "homeassistant": homeassistant,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.storage": storage,
        "homeassistant.helpers.entity_registry": entity_registry,
        "homeassistant.util": util,
        "homeassistant.util.dt": dt_module,
    }
    previous = {name: sys.modules.get(name) for name in modules}
    previous_package = sys.modules.get("custom_components.elrakning")
    sys.modules.update(modules)
    package = types.ModuleType("custom_components.elrakning")
    package.__path__ = [str(Path(__file__).parents[1] / "custom_components" / "elrakning")]
    sys.modules["custom_components.elrakning"] = package
    path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "solar_forecast.py"
    spec = spec_from_file_location("custom_components.elrakning.solar_forecast", path)
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    for name, original in previous.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original
    if previous_package is None:
        sys.modules.pop("custom_components.elrakning", None)
    else:
        sys.modules["custom_components.elrakning"] = previous_package
    return module, fixed_now


solar_forecast, FIXED_NOW = _load_module()


def _state(value, unit, name):
    return types.SimpleNamespace(
        state=str(value),
        attributes={"unit_of_measurement": unit, "friendly_name": name},
    )


class _Bus:
    def __init__(self):
        self.listener = None
        self.events = []

    def async_listen(self, event_type, listener):
        self.listener = listener
        return lambda: None

    def async_fire(self, event_type, data=None):
        self.events.append((event_type, data))


class _States:
    def __init__(self, states):
        self.states = states

    def get(self, entity_id):
        return self.states.get(entity_id)


class _ConfigEntries:
    def __init__(self, entries):
        self.entries = entries

    def async_entries(self, domain):
        return self.entries if domain == "forecast_solar" else []


class _Hass:
    def __init__(self, states, entries, registry):
        self.states = _States(states)
        self.config_entries = _ConfigEntries(entries)
        self.bus = _Bus()
        self.data = {}
        solar_forecast.er.async_get = lambda hass: registry


class ForecastSolarTests(unittest.TestCase):
    def _manager(self, states, registry_entries, entry_count=1):
        entries = [types.SimpleNamespace(entry_id=f"forecast-{index}") for index in range(entry_count)]
        hass = _Hass(states, entries, types.SimpleNamespace(entities={entry.entity_id: entry for entry in registry_entries}))
        return hass, solar_forecast.SolarForecastManager(hass)

    def test_units_normalize_energy_and_power(self):
        self.assertEqual(solar_forecast.normalize_forecast_value(_state(1200, "Wh", "energy production today"), "today_kwh"), 1.2)
        self.assertEqual(solar_forecast.normalize_forecast_value(_state(2, "MW", "power production now"), "power_now_kw"), 2000)
        self.assertEqual(solar_forecast._role("estimated power production next hour"), "power_next_hour_kw")
        self.assertEqual(solar_forecast.normalize_forecast_value(_state(1500, "W", "power production next hour"), "power_next_hour_kw"), 1.5)
        self.assertIsNone(solar_forecast.normalize_forecast_value(_state("unknown", "kWh", "energy production today"), "today_kwh"))

    def test_official_translation_keys_are_discovered(self):
        states = {
            "sensor.energy_current_hour": _state(1, "kWh", "Energy current hour"),
            "sensor.energy_next_hour": _state(2, "kWh", "Energy next hour"),
            "sensor.power_production_next_12hours": _state(1200, "W", "Power production next 12 hours"),
            "sensor.power_production_next_24hours": _state(2400, "W", "Power production next 24 hours"),
        }
        registry = [
            types.SimpleNamespace(
                entity_id=entity_id,
                config_entry_id="forecast-0",
                unique_id=entity_id,
                original_name=state.attributes["friendly_name"],
                translation_key=entity_id.removeprefix("sensor."),
            )
            for entity_id, state in states.items()
        ]
        hass, manager = self._manager(states, registry)
        asyncio.run(manager.async_load())
        public = manager.public_state()
        self.assertEqual(public["this_hour_kwh"], 1)
        self.assertEqual(public["next_hour_kwh"], 2)
        self.assertEqual(public["power_next_12_hours_kw"], 1.2)
        self.assertEqual(public["power_next_24_hours_kw"], 2.4)

    def test_single_source_discovers_facts_and_captures_baselines(self):
        states = {
            "sensor.energy_production_today": _state(5, "kWh", "Estimated energy production today"),
            "sensor.energy_production_tomorrow": _state(12, "kWh", "Estimated energy production tomorrow"),
        }
        registry = [
            types.SimpleNamespace(entity_id=entity_id, config_entry_id="forecast-0", unique_id=entity_id, original_name=state.attributes["friendly_name"], translation_key=None)
            for entity_id, state in states.items()
        ]
        hass, manager = self._manager(states, registry)
        asyncio.run(manager.async_load())
        public = manager.public_state()
        self.assertTrue(public["available"])
        self.assertEqual(public["today_kwh"], 5)
        self.assertEqual(public["tomorrow_kwh"], 12)
        self.assertEqual(public["baselines"], {"2026-08-29": 5, "2026-08-30": 12})
        self.assertTrue(any(event[0] == solar_forecast.UPDATE_EVENT for event in hass.bus.events))

    def test_tomorrow_updates_but_today_baseline_is_frozen(self):
        states = {
            "sensor.energy_production_today": _state(5, "kWh", "Estimated energy production today"),
            "sensor.energy_production_tomorrow": _state(12, "kWh", "Estimated energy production tomorrow"),
        }
        registry = [
            types.SimpleNamespace(entity_id=entity_id, config_entry_id="forecast-0", unique_id=entity_id, original_name=state.attributes["friendly_name"], translation_key=None)
            for entity_id, state in states.items()
        ]
        hass, manager = self._manager(states, registry)
        asyncio.run(manager.async_load())
        states["sensor.energy_production_tomorrow"] = _state(13, "kWh", "Estimated energy production tomorrow")
        asyncio.run(manager._async_state_changed(types.SimpleNamespace(data={"entity_id": "sensor.energy_production_tomorrow"})))
        states["sensor.energy_production_today"] = _state(6, "kWh", "Estimated energy production today")
        asyncio.run(manager._async_state_changed(types.SimpleNamespace(data={"entity_id": "sensor.energy_production_today"})))
        self.assertEqual(manager.public_state()["baselines"]["2026-08-30"], 13)
        self.assertEqual(manager.public_state()["baselines"]["2026-08-29"], 5)

    def test_multiple_sources_are_unavailable(self):
        hass, manager = self._manager({}, [], entry_count=2)
        asyncio.run(manager.async_load())
        self.assertFalse(manager.public_state()["available"])


if __name__ == "__main__":
    unittest.main()
