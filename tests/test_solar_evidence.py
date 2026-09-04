import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)

install_elrakning_package_stub()
install_homeassistant_stubs()
install_optional_dependency_stubs()

from custom_components.elrakning.solar_evidence import (
    SolarEvidenceManager,
    assess_completeness,
    integrate_actual,
    merge_pv_points,
    parse_previous_runs,
)


def _state(value, timestamp, unit="W"):
    return SimpleNamespace(
        state=str(value),
        last_updated=datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
        attributes={"unit_of_measurement": unit},
    )


class SolarEvidenceTests(unittest.TestCase):
    def test_startup_catch_up_uses_yesterday_through_normal_audit(self):
        manager = SolarEvidenceManager(SimpleNamespace(), SimpleNamespace(), SimpleNamespace())
        calls = []

        async def collect(target_date):
            calls.append(target_date)

        manager.async_collect_completed_day = collect
        import asyncio
        asyncio.run(manager.async_startup_catch_up())

        self.assertEqual(len(calls), 1)

    def test_async_load_schedules_daily_finalization_after_local_midnight(self):
        manager = SolarEvidenceManager(SimpleNamespace(), SimpleNamespace(), SimpleNamespace())
        calls = []

        def track_time_change(*args, **kwargs):
            calls.append(kwargs)
            return lambda: None

        import custom_components.elrakning.solar_evidence as solar_evidence
        original = solar_evidence.async_track_time_change
        solar_evidence.async_track_time_change = track_time_change
        try:
            import asyncio
            asyncio.run(manager.async_load())
        finally:
            solar_evidence.async_track_time_change = original

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["hour"], 0)
        self.assertEqual(calls[0]["minute"], 5)
        self.assertEqual(calls[0]["second"], 0)

    def test_common_progress_requires_open_meteo_eligibility(self):
        manager = SolarEvidenceManager(SimpleNamespace(), SimpleNamespace(), SimpleNamespace())
        manager._days = {
            "2026-09-01": {"audit_complete": False, "open_meteo_status": "complete", "forecast_solar_frozen_kwh": 10},
            "2026-09-02": {"audit_complete": True, "open_meteo_status": "invalid", "forecast_solar_frozen_kwh": 10},
            "2026-09-03": {"audit_complete": True, "open_meteo_status": "complete", "forecast_solar_frozen_kwh": 10},
        }
        state = manager.public_state()
        self.assertEqual(state["progress"]["open_meteo_complete"], 1)
        self.assertEqual(state["progress"]["forecast_solar_common"], 1)
        self.assertFalse(state["days"][0]["common_forecast_solar_day"])
        self.assertFalse(state["days"][1]["common_forecast_solar_day"])
        self.assertTrue(state["days"][2]["common_forecast_solar_day"])

    def test_store_failure_does_not_escape_async_load(self):
        manager = SolarEvidenceManager(SimpleNamespace(), SimpleNamespace(), SimpleNamespace())

        async def fail_load():
            raise RuntimeError("store unavailable")

        manager.store.async_load = fail_load
        import asyncio
        asyncio.run(manager.async_load())
        self.assertEqual(manager._days, {})

    def test_backfill_failure_isolated_and_continues(self):
        manager = SolarEvidenceManager(SimpleNamespace(), SimpleNamespace(), SimpleNamespace())
        calls = []

        async def collect(target_date):
            calls.append(target_date)
            if len(calls) == 1:
                raise RuntimeError("optional source unavailable")

        manager.async_collect_completed_day = collect
        import asyncio
        asyncio.run(manager.async_backfill(days=2))
        self.assertEqual(len(calls), 2)

    def test_merge_preserves_latest_known_values_for_multiple_pv_entities(self):
        history = {
            "pv.one": [_state(1000, "2026-09-02T00:00:00Z"), _state(2000, "2026-09-02T01:00:00Z")],
            "pv.two": [_state(500, "2026-09-02T00:00:00Z"), _state(1000, "2026-09-02T02:00:00Z")],
        }
        result = merge_pv_points(history, ["pv.one", "pv.two"])
        self.assertEqual([point["value_kw"] for point in result], [1.5, 2.5, 3.0])

    def test_actual_excludes_segments_longer_than_one_hour(self):
        points = [
            {"timestamp": "2026-09-02T00:00:00+00:00", "value_kw": 0},
            {"timestamp": "2026-09-02T01:00:00+00:00", "value_kw": 2},
            {"timestamp": "2026-09-02T03:30:00+00:00", "value_kw": 2},
        ]
        total, boundary_long, interior_long = integrate_actual(
            points,
            datetime(2026, 9, 2, tzinfo=timezone.utc),
            datetime(2026, 9, 3, tzinfo=timezone.utc),
        )
        self.assertEqual(total, 1)
        self.assertEqual(boundary_long, 1)
        self.assertEqual(interior_long, 1)

    def test_long_boundary_gaps_do_not_become_interior_gaps(self):
        points = [
            {"timestamp": "2026-09-02T00:00:00+00:00", "value_kw": 0},
            {"timestamp": "2026-09-02T06:00:00+00:00", "value_kw": 1},
            {"timestamp": "2026-09-02T18:00:00+00:00", "value_kw": 1},
            {"timestamp": "2026-09-03T00:00:00+00:00", "value_kw": 0},
        ]
        total, boundary_long, interior_long = integrate_actual(
            points,
            datetime(2026, 9, 2, tzinfo=timezone.utc),
            datetime(2026, 9, 3, tzinfo=timezone.utc),
        )
        self.assertEqual(total, 0)
        self.assertEqual(boundary_long, 3)
        self.assertEqual(interior_long, 1)

    def test_long_gap_between_active_points_is_interior(self):
        points = [
            {"timestamp": "2026-09-02T06:00:00+00:00", "value_kw": 1},
            {"timestamp": "2026-09-02T08:30:00+00:00", "value_kw": 1},
        ]
        _, _, interior_long = integrate_actual(
            points,
            datetime(2026, 9, 2, tzinfo=timezone.utc),
            datetime(2026, 9, 3, tzinfo=timezone.utc),
        )
        self.assertEqual(interior_long, 1)

    def test_completeness_uses_frozen_thresholds(self):
        points = [
            {"timestamp": f"2026-09-02T00:{hour * 3:02d}:00+00:00", "value_kw": 1}
            for hour in range(20)
        ]
        start = datetime(2026, 9, 2, tzinfo=timezone.utc)
        result = assess_completeness(points, [True, True], start, datetime(2026, 9, 3, tzinfo=timezone.utc))
        self.assertTrue(result["audit_complete"])
        points[5]["timestamp"] = "2026-09-02T06:31:00+00:00"
        self.assertFalse(assess_completeness(points, [True, True], start, datetime(2026, 9, 3, tzinfo=timezone.utc))["audit_complete"])

    def test_open_meteo_requires_exactly_24_numeric_values(self):
        values = list(range(24))
        payload = {"hourly": {"time": [f"2026-09-02T{hour:02d}:00" for hour in range(24)], "global_tilted_irradiance_previous_day1": values}}
        result = parse_previous_runs(payload, "2026-09-02")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["values"], 24)
        self.assertAlmostEqual(result["nominal_kwh"], sum(values) / 1000 * 9.45)
        values.pop()
        payload["hourly"]["global_tilted_irradiance_previous_day1"] = values
        self.assertEqual(parse_previous_runs(payload, "2026-09-02")["status"], "invalid")


if __name__ == "__main__":
    unittest.main()
