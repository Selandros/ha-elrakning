import unittest
from types import SimpleNamespace

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)

install_elrakning_package_stub()
install_homeassistant_stubs()
install_optional_dependency_stubs()

from custom_components.elrakning.solar_open_meteo import (
    SolarOpenMeteoManager,
    _parse_fetched_at,
    _parse_hourly,
    compass_to_open_meteo_azimuth,
)


async def _raising_load():
    raise RuntimeError("store failure")


async def _empty_state():
    return {}


class SolarOpenMeteoTests(unittest.TestCase):
    def test_manager_accepts_missing_or_invalid_fetched_at_as_cache_miss(self):
        for value in (None, "not-a-timestamp"):
            self.assertIsNone(_parse_fetched_at(value))

    def test_manager_startup_survives_store_failure(self):
        manager = SolarOpenMeteoManager.__new__(SolarOpenMeteoManager)
        manager.hass = SimpleNamespace(config=SimpleNamespace(latitude=None, longitude=None))
        manager.power_manager = SimpleNamespace(async_state=lambda: _empty_state())
        manager.store = SimpleNamespace(async_load=_raising_load)
        manager._state = {"available": False}
        manager._installation = None
        manager._frame = None
        manager._frame_id = None
        import asyncio
        asyncio.run(manager.async_load())
        self.assertFalse(manager._state["available"])


    def test_compass_azimuth_conversion(self):
        self.assertEqual(compass_to_open_meteo_azimuth(180), 0)
        self.assertEqual(compass_to_open_meteo_azimuth(90), -90)
        self.assertEqual(compass_to_open_meteo_azimuth(270), 90)
        self.assertEqual(compass_to_open_meteo_azimuth(0), 180)
        self.assertEqual(compass_to_open_meteo_azimuth(225), 45)

    def test_gti_is_integrated_from_watts_per_square_meter_to_kwh_per_square_meter(self):
        result = _parse_hourly(
            {"hourly": {"time": ["2026-09-02T12:00", "2026-09-02T13:00"], "global_tilted_irradiance": [500, 250]}},
            {"source_strings": ["PV1"], "peak_power_kwp": 9.45, "tilt_deg": 30, "azimuth_deg": 225},
        )
        self.assertEqual(result["irradiance_kwh_m2"], 0.75)
        self.assertAlmostEqual(result["potential_dc_kwh"], 7.0875)
        self.assertEqual(result["open_meteo_azimuth_deg"], 45)

    def test_invalid_or_empty_response_is_unavailable(self):
        self.assertIsNone(_parse_hourly({}, {"source_strings": [], "peak_power_kwp": 1, "tilt_deg": 30, "azimuth_deg": 180}))


if __name__ == "__main__":
    unittest.main()
