import asyncio
import inspect
import tempfile
import threading
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub


install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.canonical_collector import CanonicalCollector  # noqa: E402
from custom_components.elrakning import canonical_collector as collector_module  # noqa: E402
from custom_components.elrakning.canonical_storage import CanonicalStorage, SCHEMA_PATH, quarter_start  # noqa: E402
from custom_components.elrakning.site_identity import SiteIdentityManager  # noqa: E402
from custom_components.elrakning.solar_open_meteo import _location_fingerprint  # noqa: E402


UTC = timezone.utc


class _State:
    def __init__(self, value, unit, when):
        self.state = value
        self.last_updated = when
        self.attributes = {"unit_of_measurement": unit}


class _Identity:
    def __init__(self, targets):
        self.targets = targets

    def collection_targets(self):
        return self.targets

    def forecast_collection_targets(self):
        return [target for target in self.targets if "binding" in target]

    def collection_site_configs(self):
        return getattr(self, "site_configs", {})


class _Hass:
    async def async_add_executor_job(self, callback, *args):
        return callback(*args)


class _ThreadedHass(_Hass):
    async def async_add_executor_job(self, callback, *args):
        return await asyncio.to_thread(callback, *args)


class _Bus:
    def __init__(self):
        self.listeners = []

    def async_listen(self, event_type, action, **kwargs):
        self.listeners.append((event_type, action, kwargs))
        return lambda: None


class _StartHass(_Hass):
    def __init__(self):
        self.bus = _Bus()


class _WeatherHass(_Hass):
    def __init__(self, weather_state, response):
        self.calls = []
        self.states = types.SimpleNamespace(get=lambda entity_id: weather_state.get(entity_id))

        async def async_call(*args, **kwargs):
            self.calls.append((args, kwargs))
            return response

        self.services = types.SimpleNamespace(async_call=async_call)


def _target(site, role, entity, generation, mapping=None):
    power_semantics = {
        "house.consumption": ("W", "positive_consumption", "time_weighted_mean"),
        "solar.production": ("W", "positive_production", "time_weighted_mean"),
        "grid.power/import": ("W", "positive_import_negative_export", "time_weighted_mean"),
        "battery.power": ("W", "positive_discharge_negative_charge", "time_weighted_mean"),
        "battery.charge": ("W", "positive_charge", "time_weighted_mean"),
        "battery.discharge": ("W", "positive_discharge", "time_weighted_mean"),
        "battery.soc": ("%", "unsigned_0_100", "last_valid"),
        "grid.energy_import": ("kWh", "positive_import_energy", "last_valid"),
        "grid.energy_export": ("kWh", "positive_export_energy", "last_valid"),
        "battery.capacity": ("kWh", "positive_usable_or_nominal_capacity", "last_valid"),
    }
    unit, sign, aggregation = power_semantics[role]
    return {
        "site_id": site,
        "logical_role": role,
        "entity_id": entity,
        "generation_id": generation,
        "source_identity": {"identity_key": f"{site}:{generation}", "identity_strength": "strong"},
        "mapping": mapping or {},
        "classification": "measured",
        "canonicalization": {
            "unit": unit,
            "sign_convention": sign,
            "aggregation": aggregation,
            "classification": "measured",
            "max_hold_seconds": 60 if aggregation == "last_valid" else None,
            "invert_power": bool((mapping or {}).get("invert_power")),
            "invert_battery_power": bool((mapping or {}).get("invert_battery_power")),
            "absolute_value": role in {"house.consumption", "solar.production"},
        },
    }


def _forecast_target(site, entity):
    return {
        "site_id": site,
        "binding": {
            "config_entry_id": "forecast-entry",
            "binding_fingerprint": f"binding-{site}",
            "entities": {"today_kwh": entity},
        },
    }


class CanonicalCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_meteo_capture_status_is_empty_then_returns_deep_read_only_snapshot(self):
        collector = CanonicalCollector(_Hass(), _Identity([]), ":memory:")
        self.addCleanup(collector.storage.close)

        self.assertIsNone(collector.open_meteo_capture_status())
        collector._open_meteo_capture_status = {
            "trigger": "hourly",
            "sections": {"site-a:request": {"status": "fetched"}},
        }

        snapshot = collector.open_meteo_capture_status()
        snapshot["sections"]["site-a:request"]["status"] = "mutated"

        self.assertEqual(
            collector.open_meteo_capture_status(),
            {
                "trigger": "hourly",
                "sections": {"site-a:request": {"status": "fetched"}},
            },
        )

    async def test_open_meteo_hourly_callback_is_a_coroutine_function(self):
        collector = CanonicalCollector(_Hass(), _Identity([]), ":memory:")
        self.addCleanup(collector.storage.close)
        self.assertTrue(inspect.iscoroutinefunction(collector._async_open_meteo_cadence))

    async def test_open_meteo_capture_is_site_independent_and_fiskvik_empty(self):
        identity = _Identity([])
        identity.site_configs = {
            "site-a": {
                "collection_enabled": True,
                "location": {
                    "latitude": 62.2,
                    "longitude": 17.4,
                    "timezone": "Europe/Stockholm",
                    "verification_state": "verified",
                    "provenance": "test",
                    "location_fingerprint": _location_fingerprint(62.2, 17.4, "Europe/Stockholm"),
                },
                "bindings": {"open_meteo": {"source": "open_meteo_global_tilted_irradiance", "binding_fingerprint": "a"}},
                "power": {
                    "solar_entities": ["sensor.pv-a"],
                    "solar_array_metadata": {
                        "sensor.pv-a": {"capacity_kwp": 1, "tilt_deg": 30, "azimuth_deg": 225}
                    },
                },
            },
            "site-b": {
                "collection_enabled": True,
                "location": {
                    "latitude": 59.3,
                    "longitude": 18.1,
                    "timezone": "Europe/Stockholm",
                    "verification_state": "unverified",
                },
                "bindings": {},
                "power": {"solar_entities": [], "solar_array_metadata": {}},
            },
        }
        collector = CanonicalCollector(_Hass(), identity, ":memory:")
        self.addCleanup(collector.storage.close)
        async def fetch(_hass, target):
            return {
                "timezone": "Europe/Stockholm",
                "hourly": {
                    "time": ["2026-09-12T12:00"],
                    "global_tilted_irradiance": [-1.5],
                },
            }, datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
        with patch.object(collector_module, "async_fetch_open_meteo_target", side_effect=fetch), \
             patch.object(collector_module, "persist_open_meteo_frames", return_value={"written": 1, "unchanged": 0, "revised": 0, "frames": {}}):
            result = await collector.async_capture_open_meteo()
        self.assertEqual(result["target_site_ids"], ["site-a"])
        self.assertEqual(result["target_count"], 1)
        self.assertEqual(result["status"], "success")

    async def test_open_meteo_capture_discards_stale_target_before_persist(self):
        identity = _Identity([])
        identity.site_configs = {
            "site-a": {
                "collection_enabled": True,
                "location": {
                    "latitude": 62.2,
                    "longitude": 17.4,
                    "timezone": "Europe/Stockholm",
                    "verification_state": "verified",
                    "provenance": "test",
                    "location_fingerprint": _location_fingerprint(62.2, 17.4, "Europe/Stockholm"),
                },
                "bindings": {"open_meteo": {"source": "open_meteo_global_tilted_irradiance", "binding_fingerprint": "a"}},
                "power": {
                    "solar_entities": ["sensor.pv-a"],
                    "solar_array_metadata": {
                        "sensor.pv-a": {"capacity_kwp": 1, "tilt_deg": 30, "azimuth_deg": 225}
                    },
                },
            }
        }
        collector = CanonicalCollector(_Hass(), identity, ":memory:")
        self.addCleanup(collector.storage.close)
        async def fetch(_hass, target):
            identity.site_configs["site-a"]["location"]["latitude"] = 63.0
            return {"timezone": "Europe/Stockholm", "hourly": {"time": ["2026-09-12T12:00"], "global_tilted_irradiance": [1]}}, datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
        with patch.object(collector_module, "async_fetch_open_meteo_target", side_effect=fetch), \
             patch.object(collector_module, "persist_open_meteo_frames") as persist:
            result = await collector.async_capture_open_meteo()
        persist.assert_not_called()
        self.assertEqual(next(iter(result["sections"].values()))["status"], "stale_target")

    async def test_forecast_capture_status_starts_empty_and_is_read_only(self):
        collector = CanonicalCollector(_Hass(), _Identity([]), ":memory:")
        self.addCleanup(collector.storage.close)
        self.assertIsNone(collector.forecast_capture_status())

    async def test_forecast_capture_without_targets_is_explicitly_reported(self):
        collector = CanonicalCollector(_Hass(), _Identity([]), ":memory:")
        self.addCleanup(collector.storage.close)
        result = await collector.async_capture_forecast_solar()
        self.assertEqual(result["status"], "no_targets")
        self.assertEqual(result["target_count"], 0)

    async def test_weather_capture_is_site_explicit_and_empty_sites_make_no_service_calls(self):
        identity = _Identity([])
        identity.site_configs = {
            "site-a": {"collection_enabled": True, "bindings": {}},
            "site-b": {"collection_enabled": True, "bindings": {}},
        }
        hass = _WeatherHass({}, {})
        collector = CanonicalCollector(hass, identity, ":memory:")
        self.addCleanup(collector.storage.close)
        result = await collector.async_capture_weather()
        self.assertEqual(result["target_count"], 0)
        self.assertEqual(result["target_site_ids"], [])
        self.assertEqual(hass.calls, [])
        self.assertEqual(result["status"], "no_targets")

    async def test_weather_capture_partial_hourly_failure_does_not_block_current_path(self):
        identity = _Identity([])
        identity.site_configs = {"site-a": {"collection_enabled": True, "bindings": {"weather": {
            "source": "smhi", "config_entry_id": "smhi-1", "weather_entity": "weather.home",
        }}}}
        state = types.SimpleNamespace(state="partlycloudy", attributes={"temperature": 18})
        hass = _WeatherHass({"weather.home": state}, {})
        collector = CanonicalCollector(hass, identity, ":memory:")
        self.addCleanup(collector.storage.close)
        with patch.object(collector_module, "persist_smhi_frames", side_effect=[
            {"written": 1, "unchanged": 0, "revised": 0},
        ]):
            result = await collector.async_capture_weather()
        self.assertEqual(result["target_site_ids"], ["site-a"])
        self.assertEqual(result["current"]["written"], 1)
        self.assertEqual(result["hourly"]["failed"], 1)
        self.assertEqual(len(hass.calls), 1)

    async def test_weather_capture_uses_partial_rejected_count_and_separate_hourly_persist(self):
        identity = _Identity([])
        identity.site_configs = {"site-a": {"collection_enabled": True, "bindings": {"weather": {
            "source": "smhi", "config_entry_id": "smhi-1", "weather_entity": "weather.home",
        }}}}
        state = types.SimpleNamespace(state="partlycloudy", attributes={"temperature": 18})
        response = {"weather.home": {"forecast": [
            {"datetime": "2026-09-13T12:00:00+00:00", "temperature": 14},
            {"datetime": "2026-09-13T14:00:00+02:00", "temperature": 15},
            {"datetime": "2026-09-13T13:00:00+00:00", "temperature": 16},
        ]}}
        hass = _WeatherHass({"weather.home": state}, response)
        collector = CanonicalCollector(hass, identity, ":memory:")
        self.addCleanup(collector.storage.close)
        with patch.object(collector_module, "persist_smhi_frames", side_effect=[
            {"written": 1, "unchanged": 0, "revised": 0},
            {"written": 1, "unchanged": 0, "revised": 0},
        ]) as persist:
            result = await collector.async_capture_weather()
        self.assertEqual(result["hourly"]["rejected_points"], 2)
        self.assertEqual(result["current"]["written"], 1)
        self.assertEqual(result["hourly"]["written"], 1)
        self.assertEqual(persist.call_count, 2)

    async def test_forecast_capture_with_no_candidates_is_explicitly_reported(self):
        target = _forecast_target("site-a", "sensor.forecast")
        collector = CanonicalCollector(_Hass(), _Identity([target]), ":memory:")
        self.addCleanup(collector.storage.close)
        with patch.object(collector_module, "build_forecast_solar_frames", return_value=[]):
            result = await collector.async_capture_forecast_solar()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["sites"]["site-a"]["status"], "no_candidates")

    async def test_forecast_capture_persistence_failure_is_explicitly_reported(self):
        target = _forecast_target("site-a", "sensor.forecast")
        collector = CanonicalCollector(_Hass(), _Identity([target]), ":memory:")
        self.addCleanup(collector.storage.close)
        frames = [({"site_id": "site-a"}, [])]
        with patch.object(collector_module, "build_forecast_solar_frames", return_value=frames), \
             patch.object(collector_module, "persist_forecast_solar_frames", side_effect=RuntimeError("db failed")):
            result = await collector.async_capture_forecast_solar()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["sites"]["site-a"]["error_type"], "RuntimeError")

    async def test_forecast_capture_stale_binding_is_fail_closed(self):
        target = _forecast_target("site-a", "sensor.forecast")
        identity = _Identity([target])
        collector = CanonicalCollector(_Hass(), identity, ":memory:")
        self.addCleanup(collector.storage.close)
        frames = [({"site_id": "site-a"}, [])]
        def build_and_replace(*_args):
            identity.targets = [_forecast_target("site-a", "sensor.forecast-new")]
            return frames

        with patch.object(collector_module, "build_forecast_solar_frames", side_effect=build_and_replace):
            result = await collector.async_capture_forecast_solar()
        self.assertEqual(result["sites"]["site-a"]["status"], "stale_binding")
        self.assertEqual(result["sites"]["site-a"]["written"], 0)

    async def test_forecast_capture_success_and_deduplication_are_observable(self):
        target = _forecast_target("site-a", "sensor.forecast")
        collector = CanonicalCollector(_Hass(), _Identity([target]), ":memory:")
        self.addCleanup(collector.storage.close)
        frames = [({"site_id": "site-a"}, [])]
        with patch.object(collector_module, "build_forecast_solar_frames", return_value=frames), \
             patch.object(
                 collector_module,
                 "persist_forecast_solar_frames",
                 side_effect=[
                     {"written": 1, "unchanged": 0, "revised": 0},
                     {"written": 0, "unchanged": 1, "revised": 0},
                 ],
             ):
            first = await collector.async_capture_forecast_solar(trigger="startup")
            second = await collector.async_capture_forecast_solar(
                trigger="forecast_solar_state_changed", entity_id="sensor.forecast"
            )
        self.assertEqual(first["status"], "success")
        self.assertEqual(first["trigger"], "startup")
        self.assertEqual(first["sites"]["site-a"]["status"], "success")
        self.assertEqual(first["sites"]["site-a"]["written"], 1)
        self.assertEqual(second["trigger"], "forecast_solar_state_changed")
        self.assertEqual(second["entity_id"], "sensor.forecast")
        self.assertEqual(second["sites"]["site-a"]["status"], "deduplicated")
        self.assertEqual(second["sites"]["site-a"]["deduplicated"], 1)
        snapshot = collector.forecast_capture_status()
        self.assertEqual(snapshot, second)
        snapshot["sites"]["site-a"]["written"] = 999
        self.assertEqual(collector.forecast_capture_status()["sites"]["site-a"]["written"], 0)

    async def test_forecast_captures_serialize_shared_storage_writes(self):
        target = _forecast_target("site-a", "sensor.forecast")
        collector = CanonicalCollector(_ThreadedHass(), _Identity([target]), ":memory:")
        self.addCleanup(collector.storage.close)
        frames = [({"site_id": "site-a"}, [])]
        entered = threading.Event()
        release = threading.Event()
        calls = 0

        def persist(*_args):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                release.wait(timeout=2)
            return {"written": 1, "unchanged": 0, "revised": 0}

        with patch.object(collector_module, "build_forecast_solar_frames", return_value=frames), \
             patch.object(collector, "_persist_forecast_target", side_effect=persist):
            first = asyncio.create_task(collector.async_capture_forecast_solar())
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            second = asyncio.create_task(collector.async_capture_forecast_solar())
            await asyncio.sleep(0)
            self.assertEqual(calls, 1)
            release.set()
            await asyncio.gather(first, second)

        self.assertEqual(calls, 2)

    async def test_forecast_capture_typeerror_and_valueerror_are_recorded(self):
        target = _forecast_target("site-a", "sensor.forecast")
        collector = CanonicalCollector(_Hass(), _Identity([target]), ":memory:")
        for error in (TypeError("bad type"), ValueError("bad value")):
            with patch.object(collector_module, "build_forecast_solar_frames", side_effect=error):
                result = await collector.async_capture_forecast_solar()
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["sites"]["site-a"]["error_type"], type(error).__name__)
            self.assertEqual(result["last_error"]["error_message"], str(error))

    async def test_forecast_capture_one_site_failure_does_not_abort_next_site(self):
        targets = [_forecast_target("site-a", "sensor.a"), _forecast_target("site-b", "sensor.b")]
        collector = CanonicalCollector(_Hass(), _Identity(targets), ":memory:")
        self.addCleanup(collector.storage.close)
        frames = [({"site_id": "site-b"}, [])]
        with patch.object(
            collector_module,
            "build_forecast_solar_frames",
            side_effect=[ValueError("site-a failed"), frames],
        ), patch.object(
            collector_module,
            "persist_forecast_solar_frames",
            return_value={"written": 1, "unchanged": 0, "revised": 0},
        ):
            result = await collector.async_capture_forecast_solar()
        self.assertEqual(result["sites"]["site-a"]["status"], "error")
        self.assertEqual(result["sites"]["site-b"]["status"], "success")
        self.assertEqual(result["status"], "partial_failure")

    async def test_forecast_capture_event_keeps_entity_trigger_identity(self):
        target = _forecast_target("site-a", "sensor.forecast")
        collector = CanonicalCollector(_Hass(), _Identity([target]), ":memory:")
        self.addCleanup(collector.storage.close)
        collector._started = True
        collector.async_capture_forecast_solar = AsyncMock()
        await collector._async_forecast_state_changed(types.SimpleNamespace(data={"entity_id": "sensor.forecast"}))
        collector.async_capture_forecast_solar.assert_awaited_once_with(
            trigger="forecast_solar_state_changed", entity_id="sensor.forecast"
        )

    async def test_forecast_capture_new_collector_has_no_persisted_status(self):
        first = CanonicalCollector(_Hass(), _Identity([]), ":memory:")
        self.addCleanup(first.storage.close)
        await first.async_capture_forecast_solar()
        second = CanonicalCollector(_Hass(), _Identity([]), ":memory:")
        self.addCleanup(second.storage.close)
        self.assertIsNone(second.forecast_capture_status())

    async def test_start_finalizes_previous_quarter_before_scheduling_next(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = CanonicalCollector(
                _StartHass(), _Identity([]), Path(directory) / "canonical.sqlite"
            )
            collector._async_close_previous_quarter = AsyncMock()
            await collector.async_start()
            collector._async_close_previous_quarter.assert_awaited_once()
            await collector.async_shutdown()

    async def test_state_reported_subscription_is_filtered_to_ready_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            hass = _StartHass()
            collector = CanonicalCollector(
                hass, _Identity([target]), Path(directory) / "canonical.sqlite"
            )
            await collector.async_start()
            reported = hass.bus.listeners[1]
            self.assertIn("event_filter", reported[2])
            event_filter = reported[2]["event_filter"]
            self.assertTrue(event_filter({"entity_id": "sensor.load"}))
            self.assertFalse(event_filter({"entity_id": "sensor.other"}))
            await collector.async_shutdown()

    async def test_event_stream_is_site_explicit_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            target_a = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            target_b = _target("site-b", "house.consumption", "sensor.load", "gen-b")
            collector = CanonicalCollector(
                _Hass(), _Identity([target_a, target_b]), Path(directory) / "canonical.sqlite"
            )
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            collector._buffers[("site-a", "house.consumption", "gen-a", start)]["target"] = target_a
            collector._buffers[("site-a", "house.consumption", "gen-a", start)]["samples"] = [
                (start, 100.0),
                (start + timedelta(seconds=300), 100.0),
                (start + timedelta(seconds=600), 100.0),
            ]
            collector._buffers[("site-b", "house.consumption", "gen-b", start)]["target"] = target_b
            collector._buffers[("site-b", "house.consumption", "gen-b", start)]["samples"] = [
                (start, 200.0),
                (start + timedelta(seconds=300), 200.0),
                (start + timedelta(seconds=600), 200.0),
            ]
            self.assertEqual(await collector.async_flush(start, start + timedelta(seconds=900)), 2)
            self.assertEqual(collector.storage.count_observations(), 2)
            collector._buffers[("site-a", "house.consumption", "gen-a", start)]["target"] = target_a
            collector._buffers[("site-a", "house.consumption", "gen-a", start)]["samples"] = [
                (start, 100.0),
                (start + timedelta(seconds=300), 100.0),
                (start + timedelta(seconds=600), 100.0),
            ]
            self.assertEqual(await collector.async_flush(start, start + timedelta(seconds=901)), 0)
            self.assertEqual(collector.storage.integrity_check(), "ok")
            rows = collector.storage._connection().execute(
                "SELECT site_id, value, quality_status FROM energy_observations ORDER BY site_id"
            ).fetchall()
            self.assertEqual(rows, [("site-a", 100.0, "good"), ("site-b", 200.0, "good")])
            collector.storage.close()

    async def test_missing_edges_are_partial_and_never_zero_filled(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            collector = CanonicalCollector(_Hass(), _Identity([target]), Path(directory) / "canonical.sqlite")
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            collector._buffers[("site-a", "house.consumption", "gen-a", start)]["target"] = target
            collector._buffers[("site-a", "house.consumption", "gen-a", start)]["samples"] = [
                (start + timedelta(seconds=300), 100.0),
                (start + timedelta(seconds=600), 100.0),
            ]
            await collector.async_flush(start, start + timedelta(seconds=900))
            row = collector.storage._connection().execute(
                "SELECT value, quality_status, gap_status, coverage_ratio FROM energy_observations"
            ).fetchone()
            self.assertEqual(row[0], 100.0)
            self.assertEqual(row[1:], ("partial", "gap", 600 / 900))
            collector.storage.close()

    async def test_time_weighted_mean_uses_fresh_predecessor_and_bounded_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            collector = CanonicalCollector(_Hass(), _Identity([target]), Path(directory) / "canonical.sqlite")
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            key = ("site-a", "house.consumption", "gen-a")
            collector._carry_samples[key] = (start - timedelta(seconds=5), 100.0)
            collector._buffers[(*key, start)]["target"] = target
            collector._buffers[(*key, start)]["samples"] = [
                (start + timedelta(seconds=300), 100.0),
                (start + timedelta(seconds=600), 100.0),
                (start + timedelta(seconds=895), 100.0),
            ]
            await collector.async_flush(start, start + timedelta(seconds=900))
            row = collector.storage._connection().execute(
                "SELECT value, coverage_ratio, quality_status, quality_json FROM energy_observations"
            ).fetchone()
            self.assertEqual(row[0:3], (100.0, 1.0, "good"))
            self.assertIn('"boundary_carry_used": true', row[3])
            collector.storage.close()

    async def test_time_weighted_mean_does_not_hold_stale_predecessor_or_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            collector = CanonicalCollector(_Hass(), _Identity([target]), Path(directory) / "canonical.sqlite")
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            key = ("site-a", "house.consumption", "gen-a")
            collector._carry_samples[key] = (start - timedelta(seconds=361), 100.0)
            collector._buffers[(*key, start)]["target"] = target
            collector._buffers[(*key, start)]["samples"] = [(start + timedelta(seconds=300), 100.0)]
            await collector.async_flush(start, start + timedelta(seconds=900))
            row = collector.storage._connection().execute(
                "SELECT coverage_ratio, quality_status FROM energy_observations"
            ).fetchone()
            self.assertEqual(row, (360 / 900, "partial"))
            collector.storage.close()

    async def test_single_stale_sample_never_creates_full_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            collector = CanonicalCollector(_Hass(), _Identity([target]), Path(directory) / "canonical.sqlite")
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            key = ("site-a", "house.consumption", "gen-a", start)
            collector._buffers[key]["target"] = target
            collector._buffers[key]["samples"] = [(start, 100.0)]
            await collector.async_flush(start, start + timedelta(seconds=900))
            row = collector.storage._connection().execute(
                "SELECT coverage_ratio, quality_status, gap_status FROM energy_observations"
            ).fetchone()
            self.assertEqual(row, (360 / 900, "partial", "gap"))
            collector.storage.close()

    async def test_generation_switch_never_carries_old_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            old = _target("site-a", "house.consumption", "sensor.old", "gen-old")
            new = _target("site-a", "house.consumption", "sensor.new", "gen-new")
            identity = _Identity([new])
            collector = CanonicalCollector(_Hass(), identity, Path(directory) / "canonical.sqlite")
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            collector._carry_samples[("site-a", "house.consumption", "gen-old")] = (
                start - timedelta(seconds=5), 100.0
            )
            key = ("site-a", "house.consumption", "gen-new", start)
            collector._buffers[key]["target"] = new
            collector._buffers[key]["samples"] = [(start + timedelta(seconds=300), 200.0)]
            await collector.async_flush(start, start + timedelta(seconds=900))
            row = collector.storage._connection().execute(
                "SELECT value, coverage_ratio FROM energy_observations"
            ).fetchone()
            self.assertEqual(row, (200.0, 360 / 900))
            collector.storage.close()

    async def test_restart_without_cache_does_not_invent_predecessor(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            collector = CanonicalCollector(_Hass(), _Identity([target]), Path(directory) / "canonical.sqlite")
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            key = ("site-a", "house.consumption", "gen-a", start)
            collector._buffers[key]["target"] = target
            collector._buffers[key]["samples"] = [(start + timedelta(seconds=300), 100.0)]
            await collector.async_flush(start, start + timedelta(seconds=900))
            row = collector.storage._connection().execute(
                "SELECT coverage_ratio FROM energy_observations"
            ).fetchone()
            self.assertEqual(row[0], 360 / 900)
            collector.storage.close()

    async def test_invalid_event_breaks_boundary_carry(self):
        target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
        collector = CanonicalCollector(_Hass(), _Identity([target]), ":memory:")
        collector._started = True
        start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        key = ("site-a", "house.consumption", "gen-a")
        collector._carry_samples[key] = (start - timedelta(seconds=5), 100.0)
        await collector._async_state_changed(types.SimpleNamespace(
            data={"entity_id": "sensor.load", "new_state": _State("unavailable", "W", start + timedelta(seconds=10))},
            time_fired=start + timedelta(seconds=10),
        ))
        self.assertNotIn(key, collector._carry_samples)

    async def test_exact_boundary_sample_belongs_to_new_interval_without_double_count(self):
        target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
        collector = CanonicalCollector(_Hass(), _Identity([target]), ":memory:")
        start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        predecessor = (start - timedelta(seconds=5), 100.0)
        value, coverage, _observed_at, metadata = collector._aggregate(
            "time_weighted_mean",
            [(start, 200.0), (start + timedelta(seconds=300), 200.0), (start + timedelta(seconds=600), 200.0)],
            start,
            360,
            predecessor,
        )
        self.assertEqual(value, 200.0)
        self.assertEqual(coverage, 1.0)
        self.assertTrue(metadata["boundary_carry_used"])

    async def test_predecessor_is_frozen_before_later_current_events_advance_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            collector = CanonicalCollector(_Hass(), _Identity([target]), Path(directory) / "canonical.sqlite")
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 21, 30, tzinfo=UTC)
            for when in (
                start - timedelta(seconds=2),
                start + timedelta(seconds=299),
                start + timedelta(seconds=599),
                start + timedelta(seconds=899),
            ):
                await collector._async_state_changed(types.SimpleNamespace(
                    data={"entity_id": "sensor.load", "new_state": _State("100", "W", when)},
                    time_fired=when,
                ))
            buffer = collector._buffers[("site-a", "house.consumption", "gen-a", start)]
            self.assertEqual(buffer["predecessor"][0], start - timedelta(seconds=2))
            await collector.async_flush(start, start + timedelta(seconds=905))
            row = collector.storage._connection().execute(
                "SELECT coverage_ratio, quality_status FROM energy_observations WHERE interval_start_us = ?",
                (int(start.timestamp() * 1_000_000),),
            ).fetchone()
            self.assertEqual(row, (1.0, "good"))
            collector.storage.close()

    async def test_next_quarter_event_before_previous_flush_cannot_contaminate_previous_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            collector = CanonicalCollector(_Hass(), _Identity([target]), Path(directory) / "canonical.sqlite")
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 21, 30, tzinfo=UTC)
            for when in (
                start - timedelta(seconds=2),
                start + timedelta(seconds=299),
                start + timedelta(seconds=599),
                start + timedelta(seconds=899),
                start + timedelta(seconds=902),
            ):
                await collector._async_state_changed(types.SimpleNamespace(
                    data={"entity_id": "sensor.load", "new_state": _State("100", "W", when)},
                    time_fired=when,
                ))
            await collector.async_flush(start, start + timedelta(seconds=905))
            row = collector.storage._connection().execute(
                "SELECT value, coverage_ratio, quality_status FROM energy_observations WHERE interval_start_us = ?",
                (int(start.timestamp() * 1_000_000),),
            ).fetchone()
            self.assertEqual(row, (100.0, 1.0, "good"))
            collector.storage.close()

    def test_hold_boundary_and_invalid_boundary_do_not_create_coverage(self):
        start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        value, coverage, _observed_at, _metadata = CanonicalCollector._aggregate(
            "time_weighted_mean", [(start + timedelta(seconds=300), 100.0)], start, 360,
            (start - timedelta(seconds=360), 100.0),
        )
        self.assertEqual(value, 100.0)
        self.assertEqual(coverage, 360 / 900)
        _value, invalid_coverage, _observed_at, metadata = CanonicalCollector._aggregate(
            "time_weighted_mean",
            [(start + timedelta(seconds=100), 100.0), (start + timedelta(seconds=800), 200.0)],
            start, 360, (start - timedelta(seconds=5), 100.0),
            [start + timedelta(seconds=500)],
        )
        self.assertEqual(invalid_coverage, 560 / 900)
        self.assertEqual(metadata["invalid_boundary_count"], 1)

    def test_silent_slot_uses_bounded_carry_only(self):
        start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        value, coverage, _observed_at, metadata = CanonicalCollector._aggregate(
            "time_weighted_mean", [], start, 360, (start - timedelta(seconds=5), 100.0)
        )
        self.assertEqual(value, 100.0)
        self.assertEqual(coverage, 355 / 900)
        self.assertTrue(metadata["boundary_carry_used"])

    def test_time_weighted_coverage_is_clamped_to_storage_contract(self):
        start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        _value, coverage, _observed_at, _metadata = CanonicalCollector._aggregate(
            "time_weighted_mean",
            [(start, 100.0), (start + timedelta(seconds=300), 100.0), (start + timedelta(seconds=600), 100.0)],
            start,
            360,
        )
        self.assertGreaterEqual(coverage, 0.0)
        self.assertLessEqual(coverage, 1.0)

    async def test_source_replacement_mid_quarter_keeps_both_generations(self):
        with tempfile.TemporaryDirectory() as directory:
            old = _target("site-a", "solar.production", "sensor.solar_old", "gen-old")
            new = _target("site-a", "solar.production", "sensor.solar_new", "gen-new")
            identity = _Identity([old])
            collector = CanonicalCollector(_Hass(), identity, Path(directory) / "canonical.sqlite")
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            old_key = ("site-a", "solar.production", "gen-old", start)
            collector._buffers[old_key]["target"] = old
            collector._buffers[old_key]["samples"] = [
                (start + timedelta(seconds=60), 100.0),
                (start + timedelta(seconds=420), 100.0),
            ]
            identity.targets = [new]
            new_key = ("site-a", "solar.production", "gen-new", start)
            collector._buffers[new_key]["target"] = new
            collector._buffers[new_key]["samples"] = [
                (start + timedelta(seconds=480), 200.0),
                (start + timedelta(seconds=840), 200.0),
            ]
            await collector.async_flush(start, start + timedelta(seconds=900))
            rows = collector.storage._connection().execute(
                "SELECT source_generation_id, value, quality_status FROM energy_observations ORDER BY source_generation_id"
            ).fetchall()
            self.assertEqual(rows, [("gen-new", 200.0, "partial"), ("gen-old", 100.0, "partial")])
            collector.storage.close()

    async def test_reported_events_preserve_constant_value_freshness(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            collector = CanonicalCollector(_Hass(), _Identity([target]), Path(directory) / "canonical.sqlite")
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            event_type = types.SimpleNamespace
            for seconds in (60, 120, 180):
                await collector._async_state_reported(event_type(
                    data={"entity_id": "sensor.load", "state": _State("100", "W", start)},
                    time_fired=start + timedelta(seconds=seconds),
                ))
            buffer = collector._buffers[("site-a", "house.consumption", "gen-a", start)]
            self.assertEqual([item[0] for item in buffer["samples"]], [
                start + timedelta(seconds=60), start + timedelta(seconds=120), start + timedelta(seconds=180)
            ])

    async def test_reported_and_changed_pair_is_one_canonical_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "grid.power/import", "sensor.grid", "gen-a")
            collector = CanonicalCollector(
                _Hass(), _Identity([target]), Path(directory) / "canonical.sqlite"
            )
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            state = _State("1", "kW", start)
            event = types.SimpleNamespace(
                data={"entity_id": "sensor.grid", "new_state": state},
                time_fired=start + timedelta(seconds=60),
            )
            await collector._async_state_reported(event)
            await collector._async_state_changed(event)
            buffer = collector._buffers[("site-a", "grid.power/import", "gen-a", start)]
            self.assertEqual(len(buffer["samples"]), 1)

    async def test_silent_source_finalizes_as_gap_without_fabricated_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            collector = CanonicalCollector(
                _Hass(), _Identity([target]), Path(directory) / "canonical.sqlite"
            )
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            await collector.async_flush(start, start + timedelta(seconds=900))
            row = collector.storage._connection().execute(
                "SELECT value, quality_status, gap_status FROM energy_observations"
            ).fetchone()
            self.assertEqual(row, (None, "unknown", "gap"))

    async def test_stale_last_valid_source_uses_schema_valid_quality_state(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "battery.soc", "sensor.soc", "gen-s")
            collector = CanonicalCollector(
                _Hass(), _Identity([target]), Path(directory) / "canonical.sqlite"
            )
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            key = ("site-a", "battery.soc", "gen-s", start)
            collector._buffers[key]["target"] = target
            collector._buffers[key]["samples"] = [(start, 57.0)]
            await collector.async_flush(start, start + timedelta(seconds=900))
            row = collector.storage._connection().execute(
                "SELECT value, quality_status, gap_status FROM energy_observations"
            ).fetchone()
            self.assertEqual(row, (57.0, "partial", "stale"))
            collector.storage.close()

    async def test_target_without_source_semantics_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            target["canonicalization"] = None
            collector = CanonicalCollector(
                _Hass(), _Identity([target]), Path(directory) / "canonical.sqlite"
            )
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            await collector._async_state_changed(types.SimpleNamespace(
                data={"entity_id": "sensor.load", "new_state": _State("1", "kW", start)},
                time_fired=start,
            ))
            self.assertEqual(collector._buffers, {})

    def test_signs_and_soc_follow_contract(self):
        battery = _target("site-a", "battery.power", "sensor.battery", "gen-b", {"invert_battery_power": True})
        grid = _target("site-a", "grid.power/import", "sensor.grid", "gen-g", {"invert_power": True})
        when = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        self.assertEqual(CanonicalCollector._value_for_target(battery, _State("-2", "kW", when)), 2000.0)
        self.assertEqual(CanonicalCollector._value_for_target(grid, _State("-1", "kW", when)), 1000.0)
        soc = _target("site-a", "battery.soc", "sensor.soc", "gen-s")
        self.assertEqual(CanonicalCollector._value_for_target(soc, _State("57", "%", when)), 57.0)
        self.assertIsNone(CanonicalCollector._value_for_target(soc, _State("unknown", "%", when)))

    def test_energy_and_capacity_roles_normalize_native_units(self):
        when = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        imported = _target("site-a", "grid.energy_import", "sensor.import", "gen-import")
        capacity = _target("site-a", "battery.capacity", "sensor.capacity", "gen-capacity")
        self.assertEqual(CanonicalCollector._value_for_target(imported, _State("2500", "Wh", when)), 2.5)
        self.assertEqual(CanonicalCollector._value_for_target(capacity, _State("10", "kWh", when)), 10.0)
        self.assertIsNone(CanonicalCollector._value_for_target(imported, _State("10", "W", when)))

    def test_capture_provenance_is_generic_and_resource_scoped(self):
        when = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        target = _target("site-a", "battery.capacity", "sensor.capacity", "gen-capacity")
        target["resource_id"] = "resource-a"
        observation = CanonicalCollector(_Hass(), _Identity([]), ":memory:")._build_observation(
            target, when, 10.0, 1.0, when, when, "good", "none"
        )
        self.assertEqual(observation["provenance"]["capture_contract"], "ess_telemetry.v1")
        self.assertEqual(observation["provenance"]["resource_id"], "resource-a")

    def test_explicit_target_canonicalization_controls_source_transform(self):
        when = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        target = _target(
            "site-a", "grid.power/import", "sensor.grid", "gen-g",
            {"invert_power": False},
        )
        target["canonicalization"] = {
            "unit": "W",
            "sign_convention": "positive_import_negative_export",
            "aggregation": "time_weighted_mean",
            "classification": "derived",
            "max_hold_seconds": None,
            "invert_power": True,
            "invert_battery_power": False,
            "absolute_value": False,
        }
        self.assertEqual(CanonicalCollector._value_for_target(target, _State("-1", "kW", when)), 1000.0)

    def test_duplicate_revision_payload_mismatch_is_explicit_error(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = CanonicalStorage(Path(directory) / "canonical.sqlite")
            storage.open()
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            storage.ensure_source_generation(target, start)
            observation = {
                "semantic_key": "site-a|house.consumption|gen-a|2026-01-01T12:00:00+00:00",
                "site_id": "site-a", "logical_role": "house.consumption", "source_generation_id": "gen-a",
                "interval_start": start, "observed_at": start, "captured_at": start + timedelta(seconds=900),
                "known_at": start + timedelta(seconds=900), "value": 100.0, "unit": "W",
                "sign_convention": "positive_consumption", "quality_status": "good", "coverage_ratio": 1.0,
                "gap_status": "none", "quality": {"coverage_ratio": 1.0}, "provenance": {"origin": "a"},
            }
            self.assertTrue(storage.insert_observation(observation))
            changed = dict(observation, provenance={"origin": "b"})
            with self.assertRaises(ValueError):
                storage.insert_observation(changed)
            storage.close()

    def test_provider_native_resolution_observation_is_immutable_and_site_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = CanonicalStorage(Path(directory) / "canonical.sqlite")
            storage.open()
            start = datetime(2026, 10, 1, 18, 0, tzinfo=UTC)
            captured = start + timedelta(hours=2)
            target = _target("site-a", "grid.energy_import", "eon:40093679", "eon-q")
            target.update({
                "source_resolution_kind": "native_bucket",
                "source_resolution_seconds": 900,
                "timezone_state": "verified",
            })
            storage.ensure_source_generation(target, captured)
            observation = {
                "semantic_key": "site-a|grid.energy_import|eon-q|2026-10-01T18:00:00+00:00",
                "site_id": "site-a", "logical_role": "grid.energy_import", "source_generation_id": "eon-q",
                "interval_start": start, "interval_end": start + timedelta(minutes=15),
                "resolution_seconds": 900, "source_resolution_kind": "native_bucket",
                "source_resolution_seconds": 900, "observed_at": start, "captured_at": captured,
                "fetched_at": captured, "known_at": captured, "value": 0.734, "unit": "kWh",
                "sign_convention": "positive_import_energy", "quality_status": "good", "coverage_ratio": 1.0,
                "gap_status": "none", "quality": {"padded": False}, "provenance": {"provider": "eon"},
            }
            self.assertEqual(storage.insert_historical_observations_atomic([observation]), 1)
            self.assertEqual(storage.insert_historical_observations_atomic([observation]), 0)
            rows = storage.read_site_energy_history("site-a", start, start + timedelta(minutes=15))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["value"], 0.734)
            self.assertEqual(rows[0]["provenance"]["provider"], "eon")
            self.assertEqual(storage.read_site_energy_history("site-b", start, start + timedelta(minutes=15)), [])
            storage.close()

    def test_recanonicalization_is_append_only_idempotent_and_site_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = CanonicalStorage(Path(directory) / "canonical.sqlite")
            storage.open()
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            for site, generation, value in (("site-a", "old-a", -500.0), ("site-b", "old-b", -700.0)):
                target = _target(site, "battery.power", "sensor.battery", generation)
                storage.ensure_source_generation(target, start)
                storage.insert_observation({
                    "semantic_key": f"{site}|battery.power|{generation}|{start.isoformat()}",
                    "site_id": site, "logical_role": "battery.power", "source_generation_id": generation,
                    "interval_start": start, "observed_at": start, "captured_at": start + timedelta(seconds=900),
                    "known_at": start + timedelta(seconds=900), "value": value, "unit": "W",
                    "sign_convention": "positive_discharge_negative_charge", "quality_status": "good",
                    "coverage_ratio": 1.0, "gap_status": "none", "quality": {"coverage_ratio": 1.0},
                    "provenance": {"entity_id": "sensor.battery"},
                })
            migrated = storage.recanonicalize_source_generation(
                "site-a", "battery.power", "old-a", "new-a", "migration-a",
                start + timedelta(days=1), lambda value: -float(value),
            )
            self.assertEqual(migrated, 1)
            self.assertEqual(
                storage.recanonicalize_source_generation(
                    "site-a", "battery.power", "old-a", "new-a", "migration-a",
                    start + timedelta(days=2), lambda value: -float(value),
                ),
                0,
            )
            rows_a = storage.read_site_energy_history("site-a", start, start + timedelta(hours=1))
            rows_b = storage.read_site_energy_history("site-b", start, start + timedelta(hours=1))
            corrected = next(row for row in rows_a if row["source_generation_id"] == "new-a")
            original = next(row for row in rows_a if row["source_generation_id"] == "old-a")
            self.assertEqual(corrected["value"], 500.0)
            self.assertEqual(corrected["sign_convention"], "positive_discharge_negative_charge")
            self.assertEqual(corrected["provenance"]["canonicalization_migration"], "migration-a")
            self.assertEqual(corrected["provenance"]["source_generation_id"], "new-a")
            self.assertTrue(corrected["provenance"]["source_mapping_invert_battery_power"])
            self.assertEqual(original["value"], -500.0)
            self.assertEqual(len(rows_b), 1)
            self.assertEqual(rows_b[0]["value"], -700.0)
            storage.close()

    def test_storage_reopen_verifies_schema_without_recreating_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canonical.sqlite"
            first = CanonicalStorage(path)
            first.open()
            first.close()
            second = CanonicalStorage(path)
            second.open()
            self.assertEqual(second.integrity_check(), "ok")
            second.close()

    def test_storage_fails_closed_on_schema_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canonical.sqlite"
            schema = Path(directory) / "schema.sql"
            schema.write_text(SCHEMA_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            storage = CanonicalStorage(path, schema)
            storage.open()
            storage.close()
            schema.write_text(schema.read_text(encoding="utf-8") + "\n-- tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "canonical_schema_mismatch"):
                CanonicalStorage(path, schema).open()

    def test_fresh_storage_fails_closed_when_initialization_marker_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canonical.sqlite"
            (Path(directory) / "canonical.sqlite.initializing").touch()
            with self.assertRaisesRegex(RuntimeError, "canonical_initialization_incomplete"):
                CanonicalStorage(path).open()

    def test_existing_empty_storage_fails_closed_without_auto_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canonical.sqlite"
            path.touch()
            with self.assertRaisesRegex(RuntimeError, "canonical_initialization_incomplete"):
                CanonicalStorage(path).open()

    def test_quarter_mapping_is_utc_aligned(self):
        value = datetime(2026, 3, 29, 1, 7, 4, tzinfo=UTC)
        self.assertEqual(quarter_start(value), datetime(2026, 3, 29, 1, 0, tzinfo=UTC))

    async def test_active_empty_site_does_not_stop_background_collection_for_other_site(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = SiteIdentityManager.__new__(SiteIdentityManager)
            manager.state = {
                "active_site_id": "site-b",
                "sites": [{"site_id": "site-a"}, {"site_id": "site-b"}],
                "site_configs": {
                    "site-a": {"collection_enabled": True, "power": {}, "meter": {}},
                    "site-b": {"collection_enabled": True, "power": {}, "meter": {}},
                },
                "ledger": [{
                    "site_id": "site-a", "logical_role": "house.consumption",
                    "entity_id": "sensor.load_a", "generation_id": "gen-a",
                    "source_identity": {"identity_key": "site-a-load", "identity_strength": "strong"},
                    "classification": "measured", "effective_from": None, "effective_to": None,
                    "canonicalization": {
                        "unit": "W", "sign_convention": "positive_consumption",
                        "aggregation": "time_weighted_mean", "classification": "measured",
                        "max_hold_seconds": None, "absolute_value": True,
                    },
                }],
            }
            collector = CanonicalCollector(_Hass(), manager, Path(directory) / "canonical.sqlite")
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)
            first = _State("1.0", "kW", start)
            second = _State("1.0", "kW", start + timedelta(minutes=14, seconds=59))
            await collector._async_state_changed(types.SimpleNamespace(data={
                "entity_id": "sensor.load_a", "new_state": first,
            }))
            await collector._async_state_changed(types.SimpleNamespace(data={
                "entity_id": "sensor.load_a", "new_state": second,
            }))
            await collector.async_flush(start, start + timedelta(minutes=15, seconds=5))
            rows = collector.storage.read_site_energy_history("site-a", start, start + timedelta(minutes=15))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source_generation_id"], "gen-a")
            self.assertEqual(rows[0]["site_id"], "site-a")
            self.assertAlmostEqual(rows[0]["value"], 1000.0)
            self.assertEqual(collector.storage.read_site_energy_history("site-b", start, start + timedelta(minutes=15)), [])
            collector.storage.close()

    def test_collection_enabled_is_independent_of_active_site(self):
        manager = SiteIdentityManager.__new__(SiteIdentityManager)
        manager.state = {
            "active_site_id": "site-b",
            "sites": [{"site_id": "site-a"}, {"site_id": "site-b"}],
            "site_configs": {
                "site-a": {"collection_enabled": True},
                "site-b": {"collection_enabled": False},
            },
            "ledger": [{
                "site_id": "site-a", "logical_role": "house.consumption",
                "entity_id": "sensor.load", "generation_id": "gen-a",
                "classification": "measured",
                "canonicalization": {
                    "unit": "W", "sign_convention": "positive_consumption",
                "aggregation": "time_weighted_mean", "classification": "measured",
                    "max_hold_seconds": None,
                },
            }, {
                "site_id": "site-b", "logical_role": "house.consumption",
                "entity_id": "sensor.load", "generation_id": "gen-b",
                "classification": "measured",
                "canonicalization": {
                    "unit": "W", "sign_convention": "positive_consumption",
                    "aggregation": "time_weighted_mean", "classification": "measured",
                },
            }],
        }
        targets = manager.collection_targets()
        self.assertEqual([(item["site_id"], item["generation_id"]) for item in targets], [("site-a", "gen-a")])
