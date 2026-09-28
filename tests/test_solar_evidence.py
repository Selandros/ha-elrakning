import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)

install_elrakning_package_stub()
install_homeassistant_stubs()
install_optional_dependency_stubs()

import custom_components.elrakning.solar_evidence as solar_evidence

from custom_components.elrakning.solar_evidence import (
    AUDIT_SEMANTICS_VERSION,
    SolarEvidenceManager,
    assess_completeness,
    build_evidence_collection_targets,
    count_invalid_states_in_target_day,
    assess_invalid_intervals,
    integrate_actual,
    merge_pv_points,
    parse_previous_runs,
    should_reprocess_existing_day,
)


def _state(value, timestamp, unit="W"):
    return SimpleNamespace(
        state=str(value),
        last_updated=datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
        attributes={"unit_of_measurement": unit},
    )


class SolarEvidenceTests(unittest.TestCase):
    def test_bounded_simultaneous_transient_is_tolerated_without_interpolation(self):
        from zoneinfo import ZoneInfo

        zone = ZoneInfo("Europe/Stockholm")
        start = datetime(2026, 9, 27, tzinfo=zone)
        end = datetime(2026, 9, 28, tzinfo=zone)
        history = {
            "pv.one": [_state(1000, "2026-09-27T23:00:00+02:00"), _state("unavailable", "2026-09-27T23:02:53.907000+02:00"), _state(0, "2026-09-27T23:14:47.046000+02:00")],
            "pv.two": [_state(1000, "2026-09-27T23:00:00+02:00"), _state("unavailable", "2026-09-27T23:02:53.907000+02:00"), _state(0, "2026-09-27T23:14:47.059000+02:00")],
        }
        result = assess_invalid_intervals(history, ["pv.one", "pv.two"], start, end)
        self.assertEqual(result["raw_in_day_invalid_count"], 2)
        self.assertEqual(result["tolerated_invalid_interval_count"], 2)
        self.assertAlmostEqual(result["tolerated_invalid_duration_seconds"], 713.152, places=3)
        self.assertEqual(result["untolerated_invalid_count"], 0)

    def test_invalid_interval_over_limit_is_fail_closed(self):
        from zoneinfo import ZoneInfo

        zone = ZoneInfo("Europe/Stockholm")
        start = datetime(2026, 9, 27, tzinfo=zone)
        end = datetime(2026, 9, 28, tzinfo=zone)
        history = {"pv.one": [_state(1000, "2026-09-27T12:00:00+02:00"), _state("unknown", "2026-09-27T12:01:00+02:00"), _state(0, "2026-09-27T12:31:01+02:00")]}
        result = assess_invalid_intervals(history, ["pv.one"], start, end)
        self.assertEqual(result["untolerated_invalid_count"], 1)

    def test_invalid_interval_requires_valid_bracketing(self):
        from zoneinfo import ZoneInfo

        zone = ZoneInfo("Europe/Stockholm")
        start = datetime(2026, 9, 27, tzinfo=zone)
        end = datetime(2026, 9, 28, tzinfo=zone)
        histories = (
            {"pv.one": [_state("unavailable", "2026-09-27T12:00:00+02:00"), _state(0, "2026-09-27T12:01:00+02:00")]},
            {"pv.one": [_state(0, "2026-09-27T11:59:00+02:00"), _state("unavailable", "2026-09-27T12:00:00+02:00")]},
        )
        for history in histories:
            self.assertEqual(assess_invalid_intervals(history, ["pv.one"], start, end)["untolerated_invalid_count"], 1)

    def test_invalid_without_timestamp_remains_fail_closed(self):
        from zoneinfo import ZoneInfo

        zone = ZoneInfo("Europe/Stockholm")
        start = datetime(2026, 9, 27, tzinfo=zone)
        end = datetime(2026, 9, 28, tzinfo=zone)
        state = SimpleNamespace(state="unavailable", last_updated=None, attributes={"unit_of_measurement": "W"})
        result = assess_invalid_intervals({"pv.one": [state]}, ["pv.one"], start, end)
        self.assertEqual(result["raw_in_day_invalid_count"], 1)
        self.assertEqual(result["untolerated_invalid_count"], 1)
        self.assertIsNone(result["untolerated_invalid_duration_seconds"])

    def test_multiple_short_transients_are_bounded_by_union_duration(self):
        from zoneinfo import ZoneInfo

        zone = ZoneInfo("Europe/Stockholm")
        start = datetime(2026, 9, 27, tzinfo=zone)
        end = datetime(2026, 9, 28, tzinfo=zone)
        history = {"pv.one": [
            _state(0, "2026-09-27T10:00:00+02:00"), _state("unknown", "2026-09-27T10:01:00+02:00"), _state(0, "2026-09-27T10:11:00+02:00"),
            _state("unavailable", "2026-09-27T10:12:00+02:00"), _state(0, "2026-09-27T10:32:01+02:00"),
        ]}
        result = assess_invalid_intervals(history, ["pv.one"], start, end)
        self.assertEqual(result["tolerated_invalid_interval_count"], 2)
        self.assertGreater(result["tolerated_invalid_duration_seconds"], 30 * 60)
        self.assertEqual(result["untolerated_invalid_count"], 1)
    def test_invalid_padding_states_do_not_exclude_target_day(self):
        from zoneinfo import ZoneInfo

        zone = ZoneInfo("Europe/Stockholm")
        start = datetime(2026, 9, 27, tzinfo=zone)
        end = datetime(2026, 9, 28, tzinfo=zone)
        history = {"pv.one": [
            _state("unavailable", "2026-09-26T23:59:00+02:00"),
            _state(1000, "2026-09-27T00:00:00+02:00"),
            _state("unknown", "2026-09-28T00:01:00+02:00"),
        ]}

        self.assertEqual(count_invalid_states_in_target_day(history, ["pv.one"], start, end), (0, 2))

    def test_invalid_state_inside_local_target_day_excludes_target_day(self):
        from zoneinfo import ZoneInfo

        zone = ZoneInfo("Europe/Stockholm")
        start = datetime(2026, 9, 27, tzinfo=zone)
        end = datetime(2026, 9, 28, tzinfo=zone)
        history = {"pv.one": [_state("unknown", "2026-09-27T12:00:00+02:00")]}

        self.assertEqual(count_invalid_states_in_target_day(history, ["pv.one"], start, end), (1, 0))

    def test_next_local_midnight_belongs_to_next_day(self):
        from zoneinfo import ZoneInfo

        zone = ZoneInfo("Europe/Stockholm")
        start = datetime(2026, 9, 27, tzinfo=zone)
        end = datetime(2026, 9, 28, tzinfo=zone)
        history = {"pv.one": [_state("unavailable", "2026-09-28T00:00:00+02:00")]}

        self.assertEqual(count_invalid_states_in_target_day(history, ["pv.one"], start, end), (0, 1))

    def test_startup_catch_up_uses_yesterday_through_normal_audit(self):
        manager = SolarEvidenceManager(SimpleNamespace(), SimpleNamespace(), SimpleNamespace())
        calls = []

        async def collect(target_date):
            calls.append(target_date)

        manager.async_collect_completed_day = collect
        import asyncio
        asyncio.run(manager.async_startup_catch_up())

        self.assertEqual(len(calls), 1)
        self.assertEqual(manager.public_state()["capture_tasks"]["startup"]["outcome"], "success")

    def test_startup_capture_exception_is_observable_without_changing_result_handling(self):
        manager = SolarEvidenceManager(SimpleNamespace(), SimpleNamespace(), SimpleNamespace())

        async def fail(_target_date):
            raise RuntimeError("recorder unavailable")

        manager.async_collect_completed_day_for_targets = fail
        import asyncio
        asyncio.run(manager.async_startup_catch_up())

        status = manager.public_state()["capture_tasks"]["startup"]
        self.assertEqual(status["outcome"], "error")
        self.assertEqual(status["error_type"], "RuntimeError")
        self.assertEqual(status["error"], "recorder unavailable")

    def test_startup_capture_cancelled_is_observable_and_reraised(self):
        manager = SolarEvidenceManager(SimpleNamespace(), SimpleNamespace(), SimpleNamespace())

        async def cancel(_target_date):
            raise asyncio.CancelledError

        manager.async_collect_completed_day_for_targets = cancel
        import asyncio
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(manager.async_startup_catch_up())

        self.assertEqual(manager.public_state()["capture_tasks"]["startup"]["outcome"], "cancelled")

    def test_stale_incomplete_record_is_reprocessed_once_for_current_semantics(self):
        self.assertTrue(should_reprocess_existing_day({
            "date": "2026-09-27",
            "audit_complete": False,
            "exclusion_reasons": ["unavailable_or_unknown"],
        }))

    def test_current_complete_or_fail_closed_record_is_idempotent(self):
        complete = {"audit_semantics_version": AUDIT_SEMANTICS_VERSION, "audit_complete": True}
        failed = {"audit_semantics_version": AUDIT_SEMANTICS_VERSION, "audit_complete": False}
        self.assertFalse(should_reprocess_existing_day(complete))
        self.assertFalse(should_reprocess_existing_day(failed))

    def test_semantic_re_evaluation_updates_collection_time_once(self):
        class Store:
            async def async_save(self, _data):
                return None

        manager = SolarEvidenceManager(SimpleNamespace(bus=SimpleNamespace(async_fire=lambda _event: None)), SimpleNamespace(), SimpleNamespace())
        old = {
            "collected_at": "2026-09-28T00:02:50+02:00",
            "audit_complete": False,
            "audit_semantics_version": "solar-evidence-audit-v1",
        }
        record = {
            "collected_at": "2026-09-28T19:59:00+02:00",
            "audit_complete": True,
            "audit_semantics_version": AUDIT_SEMANTICS_VERSION,
        }
        import asyncio
        result = asyncio.run(manager._save_target_day("site-vik", Store(), {"2026-09-27": old}, "2026-09-27", record))
        self.assertEqual(result["collected_at"], "2026-09-28T19:59:00+02:00")
        self.assertEqual(result["first_collected_at"], "2026-09-28T00:02:50+02:00")

    def test_startup_reports_per_site_collection_failure_instead_of_success(self):
        configs = {
            "site-vik": {
                "collection_enabled": True,
                "bindings": {"evidence": {"source": "solar_evidence", "protocol_version": "evidence-v1"}},
                "power": {"solar_entities": ["sensor.vik_pv"]},
            }
        }
        manager = SolarEvidenceManager(SimpleNamespace(), SimpleNamespace(), SimpleNamespace(), lambda: configs)

        async def fail(_target, _target_date):
            raise RuntimeError("recorder unavailable")

        manager._async_collect_target_day = fail
        import asyncio
        asyncio.run(manager.async_startup_catch_up())

        status = manager.public_state()["capture_tasks"]["startup"]
        self.assertEqual(status["outcome"], "error")
        self.assertEqual(status["error"], "collection_failed")

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


    def test_collection_targets_require_enabled_explicit_evidence_v1_binding(self):
        configs = {
            "site-vik": {
                "collection_enabled": True,
                "bindings": {"evidence": {"source": "solar_evidence", "protocol_version": "evidence-v1"}},
                "power": {"solar_entities": ["sensor.vik_pv"]},
            },
            "site-disabled": {
                "collection_enabled": False,
                "bindings": {"evidence": {"source": "solar_evidence", "protocol_version": "evidence-v1"}},
                "power": {"solar_entities": ["sensor.disabled_pv"]},
            },
            "site-fisk": {"collection_enabled": True, "bindings": {}, "power": {}},
            "site-wrong": {
                "collection_enabled": True,
                "bindings": {"evidence": {"source": "other", "protocol_version": "evidence-v1"}},
                "power": {"solar_entities": ["sensor.other"]},
            },
        }
        targets = build_evidence_collection_targets(configs)
        self.assertEqual([item["site_id"] for item in targets], ["site-vik"])
        self.assertEqual(targets[0]["power"]["solar_entities"], ["sensor.vik_pv"])

    def test_collection_targets_require_legitimate_pv_mapping(self):
        configs = {
            "missing": {
                "collection_enabled": True,
                "bindings": {"evidence": {"source": "solar_evidence", "protocol_version": "evidence-v1"}},
                "power": {},
            },
            "empty": {
                "collection_enabled": True,
                "bindings": {"evidence": {"source": "solar_evidence", "protocol_version": "evidence-v1"}},
                "power": {"solar_entities": []},
            },
            "invalid": {
                "collection_enabled": True,
                "bindings": {"evidence": {"source": "solar_evidence", "protocol_version": "evidence-v1"}},
                "power": {"solar_entities": [""]},
            },
        }
        self.assertEqual(build_evidence_collection_targets(configs), [])

    def test_inactive_vik_target_collects_without_using_active_power_manager(self):
        class FailingPowerManager:
            async def async_state(self):
                raise AssertionError("active-site PowerManager must not drive background Evidence")

        configs = {
            "site-vik": {
                "collection_enabled": True,
                "bindings": {"evidence": {"source": "solar_evidence", "protocol_version": "evidence-v1"}},
                "power": {"solar_entities": ["sensor.vik_pv"]},
            },
            "site-fisk": {"collection_enabled": True, "bindings": {}, "power": {}},
        }
        manager = SolarEvidenceManager(
            SimpleNamespace(), FailingPowerManager(), SimpleNamespace(), lambda: configs
        )
        manager._site_id = "site-fisk"
        calls = []

        async def collect(target, target_date):
            calls.append((target, target_date))
            return {"site_id": target["site_id"], "date": target_date.isoformat(), "audit_complete": True}

        manager._async_collect_target_day = collect
        import asyncio
        result = asyncio.run(manager.async_collect_completed_day_for_targets(datetime(2026, 9, 12).date()))
        self.assertEqual(list(result), ["site-vik"])
        self.assertEqual([item[0]["site_id"] for item in calls], ["site-vik"])
        self.assertEqual(calls[0][0]["power"]["solar_entities"], ["sensor.vik_pv"])
        self.assertEqual(manager._site_id, "site-fisk")

    def test_site_without_evidence_binding_has_no_target_and_no_collection_side_effect(self):
        configs = {"site-fisk": {"collection_enabled": True, "bindings": {}, "power": {}}}
        manager = SolarEvidenceManager(
            SimpleNamespace(), SimpleNamespace(), SimpleNamespace(), lambda: configs
        )
        calls = []

        async def collect(*_args):
            calls.append(True)
            raise AssertionError("no target must not collect or fabricate Evidence")

        manager._async_collect_target_day = collect
        import asyncio
        result = asyncio.run(manager.async_collect_completed_day_for_targets(datetime(2026, 9, 12).date()))
        self.assertEqual(result, {})
        self.assertEqual(calls, [])

    def test_daily_startup_and_backfill_share_site_explicit_collection_path(self):
        manager = SolarEvidenceManager(SimpleNamespace(), SimpleNamespace(), SimpleNamespace(), lambda: {})
        calls = []

        async def collect(target_date):
            calls.append(target_date)
            return {}

        manager.async_collect_completed_day_for_targets = collect
        import asyncio
        asyncio.run(manager._daily_update(None))
        asyncio.run(manager.async_startup_catch_up())
        asyncio.run(manager.async_backfill(days=2))
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0], calls[1])

    def test_frozen_forecast_baseline_reads_site_store_and_rejects_first_today_or_late_capture(self):
        class ForecastManager:
            def __init__(self, item):
                self.item = item
                self.calls = []

            async def async_site_baseline_record(self, site_id, key):
                self.calls.append((site_id, key))
                return self.item

        start = datetime(2026, 9, 12, tzinfo=timezone.utc)
        import asyncio

        forecast = ForecastManager({
            "forecast_kwh": 28.5,
            "capture_type": "day_ahead",
            "captured_at": "2026-09-11T20:00:00+00:00",
        })
        manager = SolarEvidenceManager(SimpleNamespace(), SimpleNamespace(), forecast)
        self.assertEqual(
            asyncio.run(manager._frozen_forecast_baseline("site-vik", "2026-09-12", start)), 28.5
        )
        self.assertEqual(forecast.calls, [("site-vik", "2026-09-12")])

        forecast.item = {
            "forecast_kwh": 28.5,
            "capture_type": "first_today",
            "captured_at": "2026-09-11T20:00:00+00:00",
        }
        self.assertIsNone(asyncio.run(manager._frozen_forecast_baseline("site-vik", "2026-09-12", start)))

        forecast.item = {
            "forecast_kwh": 28.5,
            "capture_type": "day_ahead",
            "captured_at": "2026-09-12T00:00:00+00:00",
        }
        self.assertIsNone(asyncio.run(manager._frozen_forecast_baseline("site-vik", "2026-09-12", start)))

    def test_inactive_site_save_preserves_frozen_values_without_ui_event(self):
        class Bus:
            def __init__(self):
                self.events = []

            def async_fire(self, event):
                self.events.append(event)

        class Store:
            def __init__(self):
                self.saved = None

            async def async_save(self, data):
                self.saved = data

        hass = SimpleNamespace(bus=Bus())
        manager = SolarEvidenceManager(hass, SimpleNamespace(), SimpleNamespace())
        manager._site_id = "site-fisk"
        store = Store()
        days = {
            "2026-09-12": {
                "actual_kwh": 10.0,
                "forecast_solar_frozen_kwh": 20.0,
                "collected_at": "2026-09-13T00:05:00+02:00",
                "open_meteo_status": "partial",
            }
        }
        record = {
            "site_id": "site-vik",
            "actual_kwh": 99.0,
            "forecast_solar_frozen_kwh": 88.0,
            "collected_at": "2026-09-14T00:05:00+02:00",
            "open_meteo_status": "complete",
        }
        import asyncio
        result = asyncio.run(
            manager._save_target_day("site-vik", store, days, "2026-09-12", record)
        )
        self.assertEqual(result["actual_kwh"], 10.0)
        self.assertEqual(result["forecast_solar_frozen_kwh"], 20.0)
        self.assertEqual(result["collected_at"], "2026-09-13T00:05:00+02:00")
        self.assertEqual(result["open_meteo_status"], "complete")
        self.assertEqual(hass.bus.events, [])
        self.assertEqual(manager._site_id, "site-fisk")

    def test_site_context_load_does_not_migrate_previous_active_days_into_new_site(self):
        class Store:
            async def async_load(self):
                return None

            async def async_save(self, _data):
                raise AssertionError("missing site store must not receive previous site's days")

        manager = SolarEvidenceManager(SimpleNamespace(), SimpleNamespace(), SimpleNamespace())
        manager.store = Store()
        manager._days = {"2026-09-12": {"site_id": "site-vik", "actual_kwh": 1}}

        import asyncio
        original = solar_evidence.async_load_site_store

        async def load_site_store(*_args, **_kwargs):
            return Store(), None

        solar_evidence.async_load_site_store = load_site_store
        try:
            asyncio.run(manager.async_apply_site_context("site-fisk", {"source": "solar_evidence"}))
        finally:
            solar_evidence.async_load_site_store = original

        self.assertEqual(manager._days, {})

    def test_previous_day1_contract_remains_frozen(self):
        source = Path(__file__).parents[1].joinpath("custom_components/elrakning/solar_evidence.py").read_text(encoding="utf-8")
        self.assertIn('"hourly": "global_tilted_irradiance_previous_day1"', source)
        self.assertIn('OPEN_METEO_ENDPOINT = "https://previous-runs-api.open-meteo.com/v1/forecast"', source)

    def test_context_switch_waits_for_evidence_collection_store_io(self):
        import asyncio

        class Bus:
            def __init__(self):
                self.events = []

            def async_fire(self, event):
                self.events.append(event)

        class SiteStore:
            def __init__(self, site_id):
                self.site_id = site_id
                self.saved = None

            async def async_save(self, data):
                self.saved = data
                stores[self.site_id] = data

        stores = {}
        entered = asyncio.Event()
        release = asyncio.Event()
        manager = SolarEvidenceManager(SimpleNamespace(bus=Bus()), SimpleNamespace(), SimpleNamespace())
        manager._site_id = "site-vik"

        async def load_site_store(_hass, _key, _version, site_id, *_args):
            if site_id == "site-vik" and not entered.is_set():
                entered.set()
                await release.wait()
            return SiteStore(site_id), None

        original = solar_evidence.async_load_site_store

        async def scenario():
            solar_evidence.async_load_site_store = load_site_store
            try:
                collect = asyncio.create_task(manager._async_collect_target_day(
                    {"site_id": "site-vik", "power": {"solar_entities": []}},
                    datetime(2026, 9, 12).date(),
                ))
                await entered.wait()
                switch = asyncio.create_task(manager.async_apply_site_context("site-fisk", None))
                await asyncio.sleep(0)
                self.assertFalse(switch.done())
                release.set()
                await asyncio.gather(collect, switch)
            finally:
                solar_evidence.async_load_site_store = original

        asyncio.run(scenario())
        self.assertEqual(manager._site_id, None)
        self.assertEqual(manager._days, {})
        self.assertIn("site-vik", stores)
        self.assertEqual(len(manager.hass.bus.events), 1)

    def test_evidence_collection_waits_for_context_restore_lock(self):
        import asyncio

        class SiteStore:
            async def async_save(self, _data):
                return None

        entered = asyncio.Event()
        release = asyncio.Event()
        manager = SolarEvidenceManager(SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *_args: None)), SimpleNamespace(), SimpleNamespace())

        async def load_site_store(_hass, _key, _version, site_id, *_args):
            if site_id == "site-fisk" and not entered.is_set():
                entered.set()
                await release.wait()
            return SiteStore(), None

        original = solar_evidence.async_load_site_store

        async def scenario():
            solar_evidence.async_load_site_store = load_site_store
            try:
                restore = asyncio.create_task(manager.async_apply_site_context("site-fisk", {"source": "solar_evidence"}))
                await entered.wait()
                collect = asyncio.create_task(manager._async_collect_target_day(
                    {"site_id": "site-vik", "power": {"solar_entities": []}},
                    datetime(2026, 9, 12).date(),
                ))
                await asyncio.sleep(0)
                self.assertFalse(collect.done())
                release.set()
                await restore
                # The collection is allowed to finish only after restore; this
                # test is concerned with lock ordering, not source availability.
                await collect
            finally:
                solar_evidence.async_load_site_store = original

        asyncio.run(scenario())
        self.assertEqual(manager._site_id, "site-fisk")
        self.assertEqual(manager._days, {})


if __name__ == "__main__":
    unittest.main()
