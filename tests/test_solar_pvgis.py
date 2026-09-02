import asyncio
import sys
import types
import unittest
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_module():
    homeassistant = types.ModuleType("homeassistant")
    helpers = types.ModuleType("homeassistant.helpers")
    storage = types.ModuleType("homeassistant.helpers.storage")
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    util = types.ModuleType("homeassistant.util")
    dt_module = types.ModuleType("homeassistant.util.dt")

    class Store:
        def __init__(self, *args):
            pass

    storage.Store = Store
    aiohttp_client.async_get_clientsession = lambda _hass: None
    dt_module.now = lambda: __import__("datetime").datetime(2026, 9, 2)
    helpers.storage = storage
    helpers.aiohttp_client = aiohttp_client
    util.dt = dt_module
    modules = {
        "homeassistant": homeassistant,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.storage": storage,
        "homeassistant.helpers.aiohttp_client": aiohttp_client,
        "homeassistant.util": util,
        "homeassistant.util.dt": dt_module,
    }
    previous = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "solar_pvgis.py"
    spec = spec_from_file_location("test_solar_pvgis_module", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, original in previous.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original
    return module


pvgis = _load_module()


class _Config:
    latitude = 62.2
    longitude = 17.5


class _Hass:
    config = _Config()


class PvgisTests(unittest.TestCase):
    def test_installation_groups_equal_physical_sections(self):
        state = {
            "solar_entities": ["a", "b", "c"],
            "solar_array_metadata": {
                "a": {"capacity_kwp": 5.4, "panel_count": 12, "tilt_deg": 30, "azimuth_deg": 225},
                "b": {"capacity_kwp": 4.05, "panel_count": 9, "tilt_deg": 30, "azimuth_deg": 225},
                "c": {"capacity_kwp": 2, "panel_count": 4, "tilt_deg": 40, "azimuth_deg": 180},
            },
        }
        installation = pvgis.build_installation(_Hass(), state)
        self.assertEqual(installation["total_peak_power_kwp"], 11.45)
        self.assertEqual(len(installation["sections"]), 2)
        self.assertEqual(installation["sections"][0]["source_strings"], ["a", "b"])
        self.assertEqual(installation["sections"][1]["source_strings"], ["c"])

    def test_normalize_snake_case_hourly_power_and_profile(self):
        timestamps = [f"2024-{month:02d}-15T{hour:02d}:00:00+00:00" for month in range(1, 13) for hour in range(24)]
        payload = {"timestamps": timestamps, "power": [float(month * 100 + hour) for month in range(1, 13) for hour in range(24)]}
        profile = pvgis.normalize_response(payload)
        self.assertEqual(profile["unit"], "kW")
        day = pvgis.profile_for_date(profile, date(2026, 9, 2))
        self.assertEqual(day["hourly_profile"][12], 0.912)
        self.assertAlmostEqual(day["potential_kwh"], sum((900 + hour) / 1000 for hour in range(24)))

    def test_malformed_response_is_unavailable(self):
        self.assertIsNone(pvgis.normalize_response({"timestamps": ["2024-01-01T00:00:00Z"], "power": []}))

    def test_cache_hit_does_not_fetch(self):
        manager = pvgis.SolarPvgisManager.__new__(pvgis.SolarPvgisManager)
        manager.hass = _Hass()
        manager.power_manager = types.SimpleNamespace(async_state=lambda: asyncio.sleep(0, result={
            "solar_entities": ["a"],
            "solar_array_metadata": {"a": {"capacity_kwp": 1, "tilt_deg": 30, "azimuth_deg": 225}},
        }))
        manager.store = types.SimpleNamespace(async_load=lambda: asyncio.sleep(0, result={
            "cache_version": 1,
            "installation": {"fingerprint": pvgis.build_installation(_Hass(), {"solar_entities": ["a"], "solar_array_metadata": {"a": {"capacity_kwp": 1, "tilt_deg": 30, "azimuth_deg": 225}}})["fingerprint"]},
            "profile": {"reference_year": 2024, "hourly_profile": {str(month): {str(hour): 0 for hour in range(24)} for month in range(1, 13)}},
            "state": {"source": "jrc_pvgis"},
        }))
        manager._async_fetch = lambda _installation: (_ for _ in ()).throw(AssertionError("cache miss"))
        asyncio.run(manager.async_load())
        self.assertTrue(manager._state["available"])


if __name__ == "__main__":
    unittest.main()
