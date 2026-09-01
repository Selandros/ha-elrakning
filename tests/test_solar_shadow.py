import asyncio
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_module():
    homeassistant = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    storage = types.ModuleType("homeassistant.helpers.storage")
    util = types.ModuleType("homeassistant.util")
    dt_module = types.ModuleType("homeassistant.util.dt")
    core.Event = object
    fixed_now = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    dt_module.now = lambda: fixed_now
    dt_module.as_local = lambda value: value
    dt_module.parse_datetime = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else None

    class Store:
        def __init__(self, *args):
            self.data = None

        async def async_load(self):
            return self.data

        async def async_save(self, data):
            self.data = data

    storage.Store = Store
    helpers.storage = storage
    util.dt = dt_module
    homeassistant.core = core
    homeassistant.helpers = helpers
    homeassistant.util = util
    modules = {
        "homeassistant": homeassistant,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.storage": storage,
        "homeassistant.util": util,
        "homeassistant.util.dt": dt_module,
    }
    previous = {name: sys.modules.get(name) for name in modules}
    previous_package = sys.modules.get("custom_components.elrakning")
    sys.modules.update(modules)
    package = types.ModuleType("custom_components.elrakning")
    package.__path__ = [str(Path(__file__).parents[1] / "custom_components" / "elrakning")]
    sys.modules["custom_components.elrakning"] = package
    path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "solar_shadow.py"
    spec = spec_from_file_location("custom_components.elrakning.solar_shadow", path)
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


solar_shadow, FIXED_NOW = _load_module()


class _Bus:
    def async_listen(self, _event_type, _listener):
        return lambda: None

    def async_fire(self, _event_type, _data=None):
        pass


class _Hass:
    def __init__(self):
        self.bus = _Bus()
        self.states = types.SimpleNamespace(get=lambda _entity_id: None)


class SolarShadowTests(unittest.TestCase):
    def test_candidate_is_deterministic_and_missing_weather_falls_back_to_raw(self):
        first = solar_shadow.build_candidate_forecast(20, {})
        second = solar_shadow.build_candidate_forecast(20, {})
        self.assertEqual(first, second)
        self.assertEqual(first["candidate_forecast_kwh"], 20)
        self.assertIn("weather_unavailable", first["reasons"])

    def test_weather_layers_are_distinguished_and_bounded(self):
        low = solar_shadow.build_candidate_forecast(20, {"available": True, "hourly_forecast": [{"cloud_low": 10, "cloud_medium": 20, "cloud_high": 30}]})
        high = solar_shadow.build_candidate_forecast(20, {"available": True, "hourly_forecast": [{"cloud_low": 90, "cloud_medium": 95, "cloud_high": 100}]})
        self.assertGreater(low["candidate_forecast_kwh"], high["candidate_forecast_kwh"])
        self.assertGreaterEqual(high["candidate_forecast_kwh"], 0)
        self.assertLessEqual(low["candidate_forecast_kwh"], 20)

    def test_precipitation_is_a_separate_conservative_component(self):
        clear = solar_shadow.build_candidate_forecast(20, {"available": True, "current": {"cloud_total": 10, "precipitation_probability": 0}})
        wet = solar_shadow.build_candidate_forecast(20, {"available": True, "current": {"cloud_total": 10, "precipitation_probability": 100}})
        self.assertGreater(clear["candidate_forecast_kwh"], wet["candidate_forecast_kwh"])
        self.assertLessEqual(clear["candidate_forecast_kwh"] - wet["candidate_forecast_kwh"], 2)

    def test_site_calibration_uses_only_previous_valid_days(self):
        calibration = [
            {"target_date": "2026-08-30", "raw_forecast_kwh": 10, "actual_final_kwh": 20, "quality": "valid"},
            {"target_date": "2026-08-31", "raw_forecast_kwh": 10, "actual_final_kwh": 10, "quality": "possible_curtailment"},
        ]
        candidate = solar_shadow.build_candidate_forecast(20, {}, calibration)
        self.assertEqual(candidate["site_bias"], 1.003125)
        self.assertNotIn("possible_curtailment", candidate["reasons"])

    def test_intraday_uses_only_actual_so_far_and_is_bounded(self):
        normal = solar_shadow.build_candidate_forecast(20, {}, actual_so_far_kwh=5, expected_so_far_kwh=4, remaining_forecast_kwh=16)
        extreme = solar_shadow.build_candidate_forecast(20, {}, actual_so_far_kwh=100, expected_so_far_kwh=1, remaining_forecast_kwh=19)
        self.assertIn("bounded_actual_so_far", normal["reasons"])
        self.assertLessEqual(extreme["intraday_bias"], 1.25)
        self.assertGreaterEqual(extreme["intraday_bias"], 0.75)

    def test_no_lookahead_future_inputs_do_not_change_candidate_at_snapshot(self):
        snapshot_inputs = {"available": True, "current": {"cloud_total": 40}}
        before = solar_shadow.build_candidate_forecast(20, snapshot_inputs, actual_so_far_kwh=4, expected_so_far_kwh=5, remaining_forecast_kwh=15)
        future_actual = 999
        future_weather = {"cloud_total": 100}
        after = solar_shadow.build_candidate_forecast(20, snapshot_inputs, actual_so_far_kwh=4, expected_so_far_kwh=5, remaining_forecast_kwh=15)
        self.assertEqual(before, after)
        self.assertNotEqual(future_actual, 4)
        self.assertNotEqual(future_weather, snapshot_inputs["current"])

    def test_snapshot_helpers_preserve_raw_and_hourly_inputs(self):
        weather = {"available": True, "current": {"cloud_low": 12}, "hourly_forecast": [{"datetime": "2026-09-01T12:00:00+00:00", "cloud_high": 80}]}
        copied = solar_shadow._copy_weather(weather)
        weather["hourly_forecast"][0]["cloud_high"] = 0
        self.assertEqual(copied["hourly_forecast"][0]["cloud_high"], 80)
        self.assertEqual(copied["current"]["cloud_low"], 12)

    def test_day_ahead_never_uses_today_intraday_context(self):
        day_ahead = solar_shadow.build_candidate_forecast(
            20, {}, actual_so_far_kwh=None, expected_so_far_kwh=None, remaining_forecast_kwh=None,
        )
        intraday = solar_shadow.build_candidate_forecast(
            20, {}, actual_so_far_kwh=8, expected_so_far_kwh=4, remaining_forecast_kwh=12,
        )
        self.assertEqual(day_ahead["intraday_bias"], 1.0)
        self.assertNotEqual(intraday["intraday_bias"], day_ahead["intraday_bias"])

    def test_frames_deduplicate_large_weather_payload(self):
        manager = solar_shadow.SolarShadowManager.__new__(solar_shadow.SolarShadowManager)
        manager._frames = {"forecast": {}, "weather": {}, "sun": {}}
        payload = {"hourly_forecast": [{"datetime": f"2026-09-01T{hour:02d}:00:00+00:00", "cloud_total": 40} for hour in range(24)]}
        first = manager._store_frame("weather", payload)
        second = manager._store_frame("weather", dict(payload))
        self.assertEqual(first, second)
        self.assertEqual(len(manager._frames["weather"]), 1)

    def test_capture_persists_today_and_tomorrow_without_duplicate_write(self):
        manager = solar_shadow.SolarShadowManager.__new__(solar_shadow.SolarShadowManager)
        manager.hass = _Hass()
        manager.forecast_manager = types.SimpleNamespace(public_state=lambda: {
            "today_kwh": 20, "tomorrow_kwh": 21, "available": True,
        })
        manager.weather_manager = types.SimpleNamespace(public_state=lambda: {
            "available": True, "status": "hourly_loaded", "current": {"cloud_total": 20},
            "hourly_forecast": [{"datetime": "2026-09-01T12:00:00+00:00", "cloud_total": 20}],
        })
        class _Power:
            async def async_history(self, _days):
                return {"solar_analysis": {"intraday": {
                    "actual_so_far_kwh": 4, "raw_expected_so_far_kwh": 5, "raw_day_forecast_kwh": 20,
                }}}
        manager.power_manager = _Power()
        manager.store = types.SimpleNamespace(data=None, async_load=lambda: None)
        saves = []
        async def save(data):
            manager.store.data = data
            saves.append(data)
        manager.store.async_save = save
        manager._snapshots = []
        manager._frames = {"forecast": {}, "weather": {}, "sun": {}}
        manager._last_capture_at = None
        manager._last_input_signature = None
        manager._capture_lock = None
        manager._last_enrichment_date = None
        asyncio.run(manager._capture("startup"))
        self.assertEqual(len(manager._snapshots), 2)
        self.assertEqual(manager._snapshots[0]["capture_type"], "intraday")
        self.assertEqual(manager._snapshots[1]["capture_type"], "day_ahead")
        self.assertIsNone(manager._snapshots[1]["pv"]["actual_so_far_kwh"])
        self.assertEqual(len(manager._frames["weather"]), 1)
        manager.forecast_manager.public_state = lambda: {
            "today_kwh": 19, "tomorrow_kwh": 21, "available": True,
        }
        asyncio.run(manager._capture("event"))
        self.assertEqual(len(manager._snapshots), 2)
        self.assertEqual(len(saves), 1)

    def test_completed_day_enrichment_changes_outcome_only(self):
        manager = solar_shadow.SolarShadowManager.__new__(solar_shadow.SolarShadowManager)
        manager._frames = {"forecast": {}, "weather": {}, "sun": {}}
        manager._snapshots = [{
            "target_date": "2026-08-31",
            "forecast_solar": {"today_kwh": 16.602},
            "smhi": {"hourly_forecast": [{"cloud_total": 20}]},
            "model": {"candidate_forecast_kwh": 17.1},
            "actual_final_kwh": None,
            "raw_error_kwh": None,
            "candidate_error_kwh": None,
            "quality": "unknown_quality",
        }]
        class _Store:
            async def async_save(self, _data):
                pass
        manager.store = _Store()
        manager.hass = types.SimpleNamespace(bus=_Bus())
        before = dict(manager._snapshots[0]["forecast_solar"])
        changed = asyncio.run(manager.async_enrich_completed_day("2026-08-31", 23.439536, "valid"))
        self.assertEqual(changed, 1)
        self.assertEqual(manager._snapshots[0]["forecast_solar"], before)
        self.assertEqual(manager._snapshots[0]["actual_final_kwh"], 23.439536)
        self.assertAlmostEqual(manager._snapshots[0]["raw_error_kwh"], 6.837536)
        self.assertEqual(manager._snapshots[0]["quality"], "valid")

    def test_completed_day_enrichment_runs_from_next_day_history(self):
        manager = solar_shadow.SolarShadowManager.__new__(solar_shadow.SolarShadowManager)
        manager._frames = {"forecast": {}, "weather": {}, "sun": {}}
        manager._snapshots = [{
            "target_date": "2026-08-31",
            "forecast_solar": {"today_kwh": 16.602},
            "model": {"candidate_forecast_kwh": 17.1},
            "actual_final_kwh": None,
            "quality": "unknown_quality",
        }]
        class _Store:
            async def async_save(self, _data):
                pass
        class _Power:
            async def async_history(self, _days):
                return {"series": {"solar": {"points": [
                    *({"timestamp": f"2026-08-31T{hour:02d}:00:00+00:00", "value_kw": 1} for hour in range(24)),
                    {"timestamp": "2026-09-01T00:00:00+00:00", "value_kw": 1},
                ]}}}
        manager.store = _Store()
        manager.hass = types.SimpleNamespace(bus=_Bus())
        manager.power_manager = _Power()
        asyncio.run(manager._enrich_completed_days(datetime(2026, 9, 1).date()))
        self.assertEqual(manager._snapshots[0]["quality"], "valid")
        self.assertEqual(manager._snapshots[0]["actual_final_kwh"], 24)

    def test_incomplete_completed_day_is_not_valid_for_learning(self):
        self.assertFalse(solar_shadow._day_has_complete_history([
            (datetime(2026, 8, 31, 12, tzinfo=timezone.utc), 1),
            (datetime(2026, 8, 31, 13, tzinfo=timezone.utc), 1),
        ], datetime(2026, 8, 31).date()))

    def test_retention_is_bounded_and_old_forecast_baselines_are_not_rewritten(self):
        manager = solar_shadow.SolarShadowManager.__new__(solar_shadow.SolarShadowManager)
        manager._frames = {"forecast": {}, "weather": {}, "sun": {}}
        manager._snapshots = [{"target_date": "2026-07-01", "forecast_solar": {"today_kwh": 18.829}, "actual_final_kwh": None}]
        manager._trim(FIXED_NOW.date())
        self.assertEqual(manager._snapshots, [])
        old_baseline = {"date": "2026-08-29", "forecast_kwh": 18.829, "capture_type": "first_today"}
        self.assertEqual(old_baseline, {"date": "2026-08-29", "forecast_kwh": 18.829, "capture_type": "first_today"})

    def test_duplicate_identity_is_deterministic(self):
        manager = solar_shadow.SolarShadowManager.__new__(solar_shadow.SolarShadowManager)
        manager._snapshots = []
        snapshot = {"timestamp": "2026-09-01T12:00:00+00:00", "target_date": "2026-09-01", "forecast_solar": {"today_kwh": 20}, "smhi": {}, "sun": {}, "pv": {}}
        self.assertFalse(manager._is_duplicate(snapshot))
        manager._snapshots.append(snapshot)
        self.assertTrue(manager._is_duplicate(dict(snapshot)))


if __name__ == "__main__":
    unittest.main()
