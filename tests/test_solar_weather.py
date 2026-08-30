import asyncio
import sys
import types
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_module():
    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    weather = types.ModuleType("homeassistant.components.weather")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    core.EVENT_STATE_CHANGED = "state_changed"
    core.Event = object
    weather.DOMAIN = "weather"
    weather.SERVICE_GET_FORECASTS = "get_forecasts"
    components.weather = weather
    helpers.entity_registry = entity_registry
    homeassistant.components = components
    homeassistant.core = core
    homeassistant.helpers = helpers
    modules = {
        "homeassistant": homeassistant,
        "homeassistant.components": components,
        "homeassistant.components.weather": weather,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.entity_registry": entity_registry,
    }
    previous = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    package = types.ModuleType("custom_components.elrakning")
    package.__path__ = [str(Path(__file__).parents[1] / "custom_components" / "elrakning")]
    sys.modules["custom_components.elrakning"] = package
    path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "solar_weather.py"
    spec = spec_from_file_location("custom_components.elrakning.solar_weather", path)
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    for name, original in previous.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original
    return module


solar_weather = _load_module()


class _Bus:
    def async_listen(self, _event_type, _listener):
        return lambda: None

    def async_fire(self, _event_type):
        pass


class _ConfigEntries:
    def __init__(self, entries):
        self.entries = entries

    def async_entries(self, domain):
        return self.entries if domain == "smhi" else []


class _Hass:
    def __init__(self, state, entries, registry_entries, response):
        self.states = types.SimpleNamespace(get=lambda _entity_id: state)
        self.config_entries = _ConfigEntries(entries)
        self.bus = _Bus()
        self.response = response

        async def async_call(*_args, **_kwargs):
            return self.response

        self.services = types.SimpleNamespace(async_call=async_call)
        solar_weather.er.async_get = lambda _hass: types.SimpleNamespace(entities={
            entry.entity_id: entry for entry in registry_entries
        })


def _hass(response, state=None, registry_entries=None, entries=None):
    state = state or types.SimpleNamespace(state="partlycloudy", attributes={
        "condition": "partlycloudy",
        "cloud_coverage": 42,
        "temperature": 18,
    })
    entries = entries if entries is not None else [types.SimpleNamespace(entry_id="smhi-1")]
    registry_entries = registry_entries if registry_entries is not None else [
        types.SimpleNamespace(entity_id="weather.home", config_entry_id="smhi-1")
    ]
    return _Hass(state, entries, registry_entries, response)


class SolarWeatherTests(unittest.TestCase):
    def test_single_smhi_entity_reads_current_and_hourly_forecast(self):
        hass = _hass({"weather.home": {"forecast": [{
            "datetime": "2026-08-30T12:00:00+00:00",
            "condition": "partlycloudy",
            "cloud_coverage": 42,
            "temperature": 18,
            "precipitation_probability": 20,
        }]}})
        manager = solar_weather.SolarWeatherManager(hass)
        asyncio.run(manager.async_load())
        state = manager.public_state()
        self.assertEqual(state["status"], "hourly_loaded")
        self.assertEqual(state["current"]["cloud_coverage"], 42)
        self.assertEqual(state["hourly_forecast"][0]["datetime"], "2026-08-30T12:00:00+00:00")
        self.assertEqual(state["hourly_forecast"][0]["precipitation_probability"], 20)

    def test_multiple_smhi_entities_are_unavailable(self):
        entries = [types.SimpleNamespace(entry_id="smhi-1"), types.SimpleNamespace(entry_id="smhi-2")]
        hass = _hass({}, entries=entries)
        manager = solar_weather.SolarWeatherManager(hass)
        asyncio.run(manager.async_load())
        self.assertEqual(manager.public_state()["status"], "ambiguous")

    def test_intraday_observation_is_bounded_and_does_not_change_expected_value(self):
        observation = solar_weather.build_intraday_observation(7.58, 5.98)
        self.assertEqual(observation["status"], "observation_only")
        self.assertAlmostEqual(observation["bias"], 7.58 / 5.98)
        self.assertEqual(solar_weather.build_intraday_observation(1, 0)["bias"], None)


if __name__ == "__main__":
    unittest.main()
