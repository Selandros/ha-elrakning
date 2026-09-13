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
    previous_package = sys.modules.get("custom_components.elrakning")
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
    if previous_package is None:
        sys.modules.pop("custom_components.elrakning", None)
    else:
        sys.modules["custom_components.elrakning"] = previous_package
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
    def test_weather_targets_are_site_explicit_and_fail_closed_without_binding(self):
        targets = solar_weather.build_weather_targets({
            "site-a": {"collection_enabled": True, "bindings": {"weather": {
                "config_entry_id": "smhi-1", "weather_entity": "weather.home",
                "sensor_entities": {"cloud_total": "sensor.cloud"},
                "source": "smhi",
            }}},
            "site-b": {"collection_enabled": True, "bindings": {}},
        })
        self.assertEqual([target["site_id"] for target in targets], ["site-a"])
        self.assertEqual(targets[0]["weather_entity"], "weather.home")

    def test_weather_targets_reject_non_smhi_source_and_missing_config_entry(self):
        targets = solar_weather.build_weather_targets({
            "wrong-provider": {"collection_enabled": True, "bindings": {"weather": {
                "source": "other", "config_entry_id": "other-1", "weather_entity": "weather.home",
            }}},
            "missing-entry": {"collection_enabled": True, "bindings": {"weather": {
                "source": "smhi", "config_entry_id": "", "weather_entity": "weather.home",
            }}},
        })
        self.assertEqual(targets, [])

    def test_hourly_normalizer_rejects_naive_points_and_keeps_valid_points(self):
        normalized = solar_weather.normalize_hourly_forecast({"forecast": [
            {"datetime": "2026-09-13T12:00:00+00:00", "temperature": 14},
            {"datetime": "2026-09-13T13:00:00", "temperature": 15},
        ]})
        self.assertEqual(normalized["quality_status"], "partial")
        self.assertEqual(len(normalized["points"]), 1)
        self.assertEqual(len(normalized["quality"]["gaps"]), 1)
        self.assertEqual(normalized["rejected_points"], 1)

    def test_current_normalizer_does_not_fabricate_missing_values(self):
        state = types.SimpleNamespace(state="partlycloudy", attributes={"temperature": 18})
        current = solar_weather.normalize_current_weather(state, {"cloud_total": None})
        self.assertEqual(current, {"temperature": 18, "condition": "partlycloudy"})

    def test_hourly_normalizer_rejects_duplicate_utc_targets(self):
        normalized = solar_weather.normalize_hourly_forecast({"forecast": [
            {"datetime": "2026-09-13T12:00:00+00:00", "temperature": 14},
            {"datetime": "2026-09-13T14:00:00+02:00", "temperature": 15},
            {"datetime": "2026-09-13T13:00:00+00:00", "temperature": 16},
        ]})
        self.assertEqual(normalized["quality_status"], "partial")
        self.assertEqual(len(normalized["points"]), 1)
        self.assertEqual(normalized["points"][0]["temperature"], 16)
        self.assertEqual(normalized["quality"]["gaps"][0]["reason"], "duplicate_utc_target")
        self.assertEqual(normalized["rejected_points"], 2)

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

    def test_sensor_roles_use_translation_key_and_are_exposed_separately(self):
        hass = _hass({}, registry_entries=[
            types.SimpleNamespace(entity_id="weather.smhi_home", config_entry_id="smhi-1"),
            types.SimpleNamespace(entity_id="sensor.cloud_total", domain="sensor", config_entry_id="smhi-1", translation_key="total_cloud"),
            types.SimpleNamespace(entity_id="sensor.cloud_low", domain="sensor", config_entry_id="smhi-1", translation_key="low_cloud"),
        ])
        manager = solar_weather.SolarWeatherManager(hass)
        asyncio.run(manager.async_load())
        roles = manager.public_state()["discovery"]["sensor_roles"]
        self.assertEqual(roles["cloud_total"], "sensor.cloud_total")
        self.assertEqual(roles["cloud_low"], "sensor.cloud_low")

    def test_sun_context_reads_available_attributes_without_requiring_sun(self):
        hass = types.SimpleNamespace(states=types.SimpleNamespace(get=lambda entity_id: (
            types.SimpleNamespace(state="above_horizon", attributes={"elevation": 36.7, "azimuth": 180, "rising": False})
            if entity_id == "sun.sun" else None
        )))
        context = solar_weather.build_sun_context(hass)
        self.assertTrue(context["available"])
        self.assertEqual(context["elevation"], 36.7)
        self.assertEqual(context["azimuth"], 180)
        self.assertFalse(context["rising"])


if __name__ == "__main__":
    unittest.main()
