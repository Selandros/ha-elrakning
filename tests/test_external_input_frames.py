import tempfile
import unittest
import sqlite3
import hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.canonical_storage import CanonicalStorage
from custom_components.elrakning.external_input_frames import (
    build_nord_pool_frame,
    build_forecast_solar_frames,
    build_open_meteo_frame,
    persist_open_meteo_frames,
    persist_forecast_solar_frames,
    persist_nord_pool_frame,
    build_smhi_current_frame,
    build_smhi_hourly_frame,
    persist_smhi_frames,
)


UTC = timezone.utc


def ha_state(value, attributes, observed_at):
    return SimpleNamespace(state=value, attributes=attributes, last_updated=observed_at)


def price_data(values):
    start = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    periods = tuple(
        SimpleNamespace(start=start + timedelta(minutes=15 * index), end=start + timedelta(minutes=15 * (index + 1)), price=value)
        for index, value in enumerate(values)
    )
    return SimpleNamespace(area="SE2", currency="SEK", date=date(2026, 9, 5), periods=periods)


class ExternalInputFrameTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.storage = CanonicalStorage(Path(self.directory.name) / "canonical.sqlite")
        self.storage.open()
        self.binding = {"config_entry_id": "np-entry", "area": "SE2", "currency": "SEK"}

    def test_smhi_current_and_hourly_use_separate_revision_streams(self):
        target = {
            "site_id": "site-a", "config_entry_id": "smhi-1",
            "weather_entity": "weather.home", "sensor_entities": {}, "source": "smhi",
        }
        captured = datetime(2026, 9, 13, 10, tzinfo=UTC)
        current, current_points = build_smhi_current_frame(target, {"temperature": 18}, captured)
        hourly, hourly_points = build_smhi_hourly_frame(
            target,
            {"points": [{"valid_at": datetime(2026, 9, 13, 12, tzinfo=UTC), "temperature": 14}], "quality_status": "good", "quality": {"status": "good", "gaps": []}},
            captured, captured, captured,
        )
        self.assertNotEqual(current["semantic_key"], hourly["semantic_key"])
        self.assertEqual(current["valid_from"], None)
        self.assertEqual(current_points, [])
        self.assertEqual(hourly_points[0]["valid_at"], datetime(2026, 9, 13, 12, tzinfo=UTC))
        result = persist_smhi_frames(self.storage, [(current, current_points), (hourly, hourly_points)], captured)
        self.assertEqual(result["written"], 2)
        self.assertEqual(self.storage.count_external_frames(), 2)

    def test_smhi_generations_are_site_owned_and_hourly_ignores_current_sensor_mapping(self):
        base = {"site_id": "site-a", "config_entry_id": "smhi-1", "weather_entity": "weather.home", "source": "smhi"}
        current_a, _ = build_smhi_current_frame({**base, "sensor_entities": {"cloud_total": "sensor.a"}}, {"temperature": 18}, datetime(2026, 9, 13, 10, tzinfo=UTC))
        current_b, _ = build_smhi_current_frame({**base, "site_id": "site-b", "sensor_entities": {"cloud_total": "sensor.a"}}, {"temperature": 18}, datetime(2026, 9, 13, 10, tzinfo=UTC))
        hourly_a, _ = build_smhi_hourly_frame({**base, "sensor_entities": {"cloud_total": "sensor.a"}}, {"points": [{"valid_at": datetime(2026, 9, 13, 12, tzinfo=UTC), "temperature": 14}], "quality_status": "good", "quality": {}}, datetime(2026, 9, 13, 10, tzinfo=UTC), datetime(2026, 9, 13, 10, tzinfo=UTC), datetime(2026, 9, 13, 10, tzinfo=UTC))
        hourly_b, _ = build_smhi_hourly_frame({**base, "sensor_entities": {"cloud_total": "sensor.b"}}, {"points": [{"valid_at": datetime(2026, 9, 13, 12, tzinfo=UTC), "temperature": 14}], "quality_status": "good", "quality": {}}, datetime(2026, 9, 13, 10, tzinfo=UTC), datetime(2026, 9, 13, 10, tzinfo=UTC), datetime(2026, 9, 13, 10, tzinfo=UTC))
        self.assertNotEqual(current_a["source_generation_id"], current_b["source_generation_id"])
        self.assertEqual(hourly_a["source_generation_id"], hourly_b["source_generation_id"])

    def test_smhi_hourly_rejected_points_are_immutable_frame_knowledge(self):
        target = {
            "site_id": "site-a", "config_entry_id": "smhi-1",
            "weather_entity": "weather.home", "sensor_entities": {}, "source": "smhi",
        }
        captured = datetime(2026, 9, 13, 10, tzinfo=UTC)
        normalized_a = {
            "points": [{"valid_at": datetime(2026, 9, 13, 12, tzinfo=UTC), "temperature": 14}],
            "quality_status": "partial", "quality": {"status": "partial", "gaps": [{"reason": "duplicate_utc_target"}]},
            "rejected_points": 2,
        }
        normalized_b = {**normalized_a, "quality": {**normalized_a["quality"], "gaps": [{"reason": "duplicate_utc_target"}, {"reason": "malformed_timestamp"}]}, "rejected_points": 3}
        frame_a, _ = build_smhi_hourly_frame(target, normalized_a, captured, captured, captured)
        frame_b, _ = build_smhi_hourly_frame(target, normalized_b, captured, captured, captured)
        self.assertEqual(frame_a["quality"]["rejected_points"], 2)
        self.assertEqual(frame_b["quality"]["rejected_points"], 3)
        self.assertNotEqual(frame_a["frame_id"], frame_b["frame_id"])

    def test_smhi_revisions_are_replayable_by_known_at_and_generation(self):
        target = {
            "site_id": "site-a", "config_entry_id": "smhi-1",
            "weather_entity": "weather.home", "sensor_entities": {}, "source": "smhi",
        }
        first_at = datetime(2026, 9, 13, 10, tzinfo=UTC)
        second_at = datetime(2026, 9, 13, 11, tzinfo=UTC)
        current_a, _ = build_smhi_current_frame(target, {"condition": "sunny", "temperature": 18}, first_at)
        current_b, _ = build_smhi_current_frame(target, {"condition": "cloudy", "temperature": 16}, second_at)
        self.assertEqual(persist_smhi_frames(self.storage, [(current_a, [])], first_at)["written"], 1)
        self.assertEqual(persist_smhi_frames(self.storage, [(current_a, [])], second_at)["unchanged"], 1)
        self.assertEqual(persist_smhi_frames(self.storage, [(current_b, [])], second_at)["revised"], 1)
        generation = current_a["source_generation_id"]
        before = self.storage.read_external_input_frames(
            first_at + timedelta(minutes=30), source_scope="site", site_id="site-a",
            source_generation_id=generation, logical_role="weather.current_conditions",
        )
        after = self.storage.read_external_input_frames(
            second_at + timedelta(minutes=30), source_scope="site", site_id="site-a",
            source_generation_id=generation, logical_role="weather.current_conditions",
        )
        self.assertEqual(before[0]["revision"], 1)
        self.assertEqual(before[0]["quality"]["knowledge"]["current"]["temperature"], 18)
        self.assertEqual(after[0]["revision"], 2)
        self.assertEqual(after[0]["quality"]["knowledge"]["current"]["temperature"], 16)

    def test_smhi_hourly_same_payload_deduplicates_and_changed_payload_revises(self):
        target = {
            "site_id": "site-a", "config_entry_id": "smhi-1",
            "weather_entity": "weather.home", "sensor_entities": {}, "source": "smhi",
        }
        captured = datetime(2026, 9, 13, 10, tzinfo=UTC)
        def hourly(temperature):
            return build_smhi_hourly_frame(target, {
                "points": [{"valid_at": datetime(2026, 9, 13, 12, tzinfo=UTC), "temperature": temperature}],
                "quality_status": "good", "quality": {}, "rejected_points": 0,
            }, captured, captured, captured)
        first, first_points = hourly(14)
        same, same_points = hourly(14)
        changed, changed_points = hourly(15)
        self.assertEqual(persist_smhi_frames(self.storage, [(first, first_points)], captured)["written"], 1)
        self.assertEqual(persist_smhi_frames(self.storage, [(same, same_points)], captured + timedelta(hours=1))["unchanged"], 1)
        self.assertEqual(persist_smhi_frames(self.storage, [(changed, changed_points)], captured + timedelta(hours=2))["revised"], 1)
        self.assertEqual(self.storage.count_external_frames(), 2)

    def test_smhi_new_generation_does_not_supersede_previous_generation(self):
        captured = datetime(2026, 9, 13, 10, tzinfo=UTC)
        target_a = {"site_id": "site-a", "config_entry_id": "smhi-1", "weather_entity": "weather.a", "sensor_entities": {}, "source": "smhi"}
        target_b = {**target_a, "weather_entity": "weather.b"}
        frame_a, _ = build_smhi_current_frame(target_a, {"condition": "sunny"}, captured)
        frame_b, _ = build_smhi_current_frame(target_b, {"condition": "sunny"}, captured)
        persist_smhi_frames(self.storage, [(frame_a, [])], captured)
        persist_smhi_frames(self.storage, [(frame_b, [])], captured + timedelta(hours=1))
        rows = self.storage.connection.execute(
            "SELECT source_generation_id, supersedes_frame_id FROM external_input_frames ORDER BY frame_id"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row[1] is None for row in rows))
    def tearDown(self):
        self.storage.close()
        self.directory.cleanup()

    def test_global_nord_pool_frame_round_trips_and_is_idempotent(self):
        data = price_data([0.42, 0.43])
        captured = datetime(2026, 9, 5, 1, 0, tzinfo=UTC)
        self.assertTrue(persist_nord_pool_frame(self.storage, data, self.binding, captured))
        self.assertFalse(persist_nord_pool_frame(self.storage, data, self.binding, captured + timedelta(minutes=15)))
        self.assertEqual(self.storage.count_external_frames(), 1)
        row = self.storage.connection.execute(
            "SELECT source_scope, site_id, logical_role, known_at_us, valid_from_us, valid_to_us FROM external_input_frames"
        ).fetchone()
        self.assertEqual(row[:3], ("global", None, "market.price.energy"))
        self.assertEqual(row[3], int(captured.timestamp() * 1_000_000))
        self.assertEqual(self.storage.connection.execute("SELECT COUNT(*) FROM external_input_points").fetchone()[0], 2)

    def test_open_meteo_frame_is_site_scoped_and_revision_safe(self):
        target = {
            "site_id": "site-a",
            "latitude": 62.2,
            "longitude": 17.4,
            "timezone": "Europe/Stockholm",
            "tilt_deg": 30.0,
            "open_meteo_azimuth_deg": 45.0,
            "section_request_fingerprint": "request-a",
            "generation_id": "om-generation-a",
            "source_strings": ["sensor.pv"],
            "peak_power_kwp": 9.45,
            "binding": {"binding_fingerprint": "binding-a"},
        }
        fetched = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
        normalized = {
            "quality_status": "good",
            "quality": {"status": "good", "gaps": []},
            "api_metadata": {"timezone": "Europe/Stockholm"},
            "points": [
                {
                    "source_timestamp": "2026-09-05T12:00",
                    "valid_at": datetime(2026, 9, 5, 10, 0, tzinfo=UTC),
                    "value": -2.5,
                    "unit": "W/m²",
                    "quality_status": "good",
                }
            ],
        }
        frame = build_open_meteo_frame(target, normalized, fetched)
        self.assertEqual(frame[0]["source_scope"], "site")
        self.assertEqual(frame[0]["site_id"], "site-a")
        self.assertIsNone(frame[0]["published_at"])
        self.assertEqual(persist_open_meteo_frames(self.storage, [frame], fetched)["written"], 1)
        self.assertEqual(persist_open_meteo_frames(self.storage, [frame], fetched)["unchanged"], 1)
        metadata_only = dict(normalized)
        metadata_only["api_metadata"] = {"timezone": "Europe/Stockholm", "generationtime_ms": 0.2}
        unchanged = build_open_meteo_frame(target, metadata_only, fetched + timedelta(hours=1))
        self.assertEqual(persist_open_meteo_frames(self.storage, [unchanged], fetched + timedelta(hours=1))["unchanged"], 1)
        generation = self.storage.connection.execute(
            "SELECT source_resolution_kind, source_resolution_seconds, timezone_state FROM source_generations WHERE source_generation_id = ?",
            ("om-generation-a",),
        ).fetchone()
        self.assertEqual(generation, ("native_bucket", 3600, "verified"))
        normalized["points"][0]["value"] = 4.0
        changed = build_open_meteo_frame(target, normalized, fetched + timedelta(hours=1))
        result = persist_open_meteo_frames(self.storage, [changed], fetched + timedelta(hours=1))
        self.assertEqual(result["revised"], 1)
        rows = self.storage.connection.execute(
            "SELECT site_id, logical_role, revision FROM external_input_frames ORDER BY revision"
        ).fetchall()
        self.assertEqual(rows, [("site-a", "solar.irradiance.forecast", 1), ("site-a", "solar.irradiance.forecast", 2)])

    def test_forecast_solar_supported_roles_write_site_scoped_frames(self):
        observed_at = datetime(2026, 9, 5, 9, 59, tzinfo=UTC)
        states = {
            "sensor.today": ha_state("18.4", {"unit_of_measurement": "kWh"}, observed_at),
            "sensor.tomorrow": ha_state("17.9", {"unit_of_measurement": "kWh"}, observed_at),
            "sensor.remaining": ha_state("12.1", {"unit_of_measurement": "kWh"}, observed_at),
            "sensor.power": ha_state("2.5", {"unit_of_measurement": "kW"}, observed_at),
            "sensor.peak_today": ha_state("2026-09-05T13:30:00+02:00", {"unit_of_measurement": None}, observed_at),
            "sensor.peak_tomorrow": ha_state("2026-09-06T12:00:00+02:00", {"unit_of_measurement": None}, observed_at),
        }
        hass = SimpleNamespace(
            states=SimpleNamespace(get=states.get),
            config=SimpleNamespace(time_zone="Europe/Stockholm"),
        )
        binding = {
            "config_entry_id": "fs-entry",
            "binding_fingerprint": "binding-a",
            "entities": {
                "today_kwh": "sensor.today",
                "tomorrow_kwh": "sensor.tomorrow",
                "remaining_today_kwh": "sensor.remaining",
                "power_now_kw": "sensor.power",
                "peak_time_today": "sensor.peak_today",
                "peak_time_tomorrow": "sensor.peak_tomorrow",
                "power_next_12_hours_kw": "sensor.aggregate",
            },
        }
        captured = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
        frames = build_forecast_solar_frames(hass, "site-a", binding, captured)
        self.assertEqual(len(frames), 6)
        self.assertTrue(all(frame["source_scope"] == "site" for frame, _ in frames))
        self.assertTrue(all(frame["site_id"] == "site-a" for frame, _ in frames))
        self.assertTrue(all(frame["published_at"] is None for frame, _ in frames))
        self.assertTrue(all(frame["fetched_at"] is None for frame, _ in frames))
        self.assertEqual({frame["logical_role"] for frame, _ in frames}, {
            "forecast_solar.today_kwh", "forecast_solar.tomorrow_kwh",
            "forecast_solar.remaining_today_kwh", "forecast_solar.power_now_kw",
            "forecast_solar.peak_time_today", "forecast_solar.peak_time_tomorrow",
        })
        targets = {frame["logical_role"]: frame["provenance"]["target"] for frame, _ in frames}
        self.assertEqual(targets["forecast_solar.today_kwh"], "local_day:2026-09-05")
        self.assertEqual(targets["forecast_solar.tomorrow_kwh"], "local_day:2026-09-06")
        self.assertEqual(targets["forecast_solar.remaining_today_kwh"], "local_day_remainder:2026-09-05")
        self.assertEqual(targets["forecast_solar.peak_time_today"], "local_day:2026-09-05")
        self.assertEqual(targets["forecast_solar.peak_time_tomorrow"], "local_day:2026-09-06")
        result = persist_forecast_solar_frames(self.storage, frames, captured)
        self.assertEqual(result["written"], 6)
        self.assertEqual(self.storage.count_external_frames(), 6)
        self.assertEqual(persist_forecast_solar_frames(self.storage, frames, captured + timedelta(minutes=15))["unchanged"], 6)

    def test_forecast_solar_changed_target_is_revision_and_replay_is_decision_time_safe(self):
        state = ha_state("18.4", {"unit_of_measurement": "kWh"}, datetime(2026, 9, 5, 9, tzinfo=UTC))
        hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda _entity: state),
            config=SimpleNamespace(time_zone="Europe/Stockholm"),
        )
        binding = {"config_entry_id": "fs-entry", "binding_fingerprint": "binding-a", "entities": {"today_kwh": "sensor.today"}}
        first_at = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
        first = build_forecast_solar_frames(hass, "site-a", binding, first_at)
        persist_forecast_solar_frames(self.storage, first, first_at)
        state.state = "17.9"
        state.last_updated = datetime(2026, 9, 5, 14, tzinfo=UTC)
        second_at = datetime(2026, 9, 5, 15, 0, tzinfo=UTC)
        second = build_forecast_solar_frames(hass, "site-a", binding, second_at)
        persist_forecast_solar_frames(self.storage, second, second_at)
        rows = self.storage.connection.execute(
            "SELECT revision, supersedes_frame_id FROM external_input_frames"
        ).fetchall()
        self.assertEqual(rows[0][0], 1)
        self.assertEqual(rows[1][0], 2)
        first_frame_id = self.storage.connection.execute(
            "SELECT frame_id FROM external_input_frames WHERE revision=1"
        ).fetchone()[0]
        self.assertEqual(rows[1][1], first_frame_id)
        old = self.storage.read_external_input_frames(first_at + timedelta(minutes=30), source_scope="site", site_id="site-a")
        new = self.storage.read_external_input_frames(second_at + timedelta(minutes=1), source_scope="site", site_id="site-a")
        self.assertEqual(old[0]["revision"], 1)
        self.assertEqual(new[0]["revision"], 2)
        self.assertEqual(old[0]["points"][0]["value"], 18.4)
        self.assertEqual(new[0]["points"][0]["value"], 17.9)

    def test_forecast_solar_revisions_rekey_points_when_content_returns(self):
        state = ha_state("2026-09-05T13:30:00+02:00", {"unit_of_measurement": None}, datetime(2026, 9, 5, 9, tzinfo=UTC))
        hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda _entity: state),
            config=SimpleNamespace(time_zone="Europe/Stockholm"),
        )
        binding = {"config_entry_id": "fs-entry", "binding_fingerprint": "binding-a", "entities": {"peak_time_today": "sensor.peak"}}
        captures = []
        for value, captured_at in (("2026-09-05T13:30:00+02:00", datetime(2026, 9, 5, 10, tzinfo=UTC)),
                                   ("2026-09-05T14:00:00+02:00", datetime(2026, 9, 5, 15, tzinfo=UTC)),
                                   ("2026-09-05T13:30:00+02:00", datetime(2026, 9, 5, 20, tzinfo=UTC))):
            state.state = value
            state.last_updated = captured_at - timedelta(minutes=1)
            captures.append((build_forecast_solar_frames(hass, "site-a", binding, captured_at), captured_at))
        for frames, captured_at in captures:
            persist_forecast_solar_frames(self.storage, frames, captured_at)
        rows = self.storage.connection.execute(
            "SELECT revision, frame_id, supersedes_frame_id FROM external_input_frames ORDER BY revision"
        ).fetchall()
        points = self.storage.connection.execute(
            "SELECT point_id FROM external_input_points ORDER BY frame_id"
        ).fetchall()
        self.assertEqual([row[0] for row in rows], [1, 2, 3])
        self.assertEqual(rows[1][2], rows[0][1])
        self.assertEqual(rows[2][2], rows[1][1])
        self.assertEqual(len({row[1] for row in rows}), 3)
        self.assertEqual(len({row[0] for row in points}), 3)
        replay = self.storage.read_external_input_frames(
            datetime(2026, 9, 5, 21, tzinfo=UTC), source_scope="site", site_id="site-a"
        )
        self.assertEqual([frame["points"][0]["point"]["predicted_peak_at"] for frame in replay], ["2026-09-05T11:30:00+00:00"])

    def test_forecast_solar_repeated_content_is_deduplicated_after_revision(self):
        state = ha_state("2026-09-05T13:30:00+02:00", {"unit_of_measurement": None}, datetime(2026, 9, 5, 9, tzinfo=UTC))
        hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda _entity: state),
            config=SimpleNamespace(time_zone="Europe/Stockholm"),
        )
        binding = {"config_entry_id": "fs-entry", "binding_fingerprint": "binding-a", "entities": {"peak_time_today": "sensor.peak"}}
        first_at = datetime(2026, 9, 5, 10, tzinfo=UTC)
        persist_forecast_solar_frames(self.storage, build_forecast_solar_frames(hass, "site-a", binding, first_at), first_at)
        state.state = "2026-09-05T14:00:00+02:00"
        second_at = datetime(2026, 9, 5, 15, tzinfo=UTC)
        state.last_updated = datetime(2026, 9, 5, 14, tzinfo=UTC)
        persist_forecast_solar_frames(self.storage, build_forecast_solar_frames(hass, "site-a", binding, second_at), second_at)
        third_at = datetime(2026, 9, 5, 20, tzinfo=UTC)
        result = persist_forecast_solar_frames(self.storage, build_forecast_solar_frames(hass, "site-a", binding, third_at), third_at)
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(self.storage.connection.execute("SELECT COUNT(*) FROM external_input_frames").fetchone()[0], 2)

    def test_forecast_solar_unchanged_numeric_observation_is_not_revised_by_new_capture(self):
        observed_at = datetime(2026, 9, 5, 9, 59, tzinfo=UTC)
        state = ha_state("18.4", {"unit_of_measurement": "kWh"}, observed_at)
        hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda _entity: state),
            config=SimpleNamespace(time_zone="Europe/Stockholm"),
        )
        binding = {"config_entry_id": "fs-entry", "binding_fingerprint": "binding-a", "entities": {"today_kwh": "sensor.today"}}
        first_at = datetime(2026, 9, 5, 10, tzinfo=UTC)
        second_at = datetime(2026, 9, 5, 10, 15, tzinfo=UTC)
        persist_forecast_solar_frames(self.storage, build_forecast_solar_frames(hass, "site-a", binding, first_at), first_at)
        result = persist_forecast_solar_frames(self.storage, build_forecast_solar_frames(hass, "site-a", binding, second_at), second_at)
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(self.storage.count_external_frames(), 1)

    def test_forecast_solar_capture_relative_roles_use_observation_time(self):
        observed_at = datetime(2026, 9, 5, 9, 59, tzinfo=UTC)
        states = {
            "sensor.remaining": ha_state("9.108", {"unit_of_measurement": "kWh"}, observed_at),
            "sensor.power": ha_state("4.13", {"unit_of_measurement": "kW"}, observed_at),
        }
        hass = SimpleNamespace(
            states=SimpleNamespace(get=states.get),
            config=SimpleNamespace(time_zone="Europe/Stockholm"),
        )
        binding = {
            "config_entry_id": "fs-entry",
            "binding_fingerprint": "binding-a",
            "entities": {"remaining_today_kwh": "sensor.remaining", "power_now_kw": "sensor.power"},
        }
        first_at = datetime(2026, 9, 5, 10, tzinfo=UTC)
        second_at = datetime(2026, 9, 5, 10, 15, tzinfo=UTC)
        first = build_forecast_solar_frames(hass, "site-a", binding, first_at)
        second = build_forecast_solar_frames(hass, "site-a", binding, second_at)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 2)
        for frame, points in first + second:
            self.assertEqual(points[0]["point"]["observed_at"], observed_at.isoformat())
            self.assertEqual(points[0]["point"]["target_point"], observed_at.isoformat())
            if frame["logical_role"].endswith("remaining_today_kwh"):
                self.assertEqual(frame["valid_from"], observed_at)
        persist_forecast_solar_frames(self.storage, first, first_at)
        result = persist_forecast_solar_frames(self.storage, second, second_at)
        self.assertEqual(result["unchanged"], 2)
        self.assertEqual(self.storage.count_external_frames(), 2)

    def test_forecast_solar_changed_observation_timestamp_creates_revision(self):
        state = ha_state("18.4", {"unit_of_measurement": "kWh"}, datetime(2026, 9, 5, 9, 59, tzinfo=UTC))
        hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda _entity: state),
            config=SimpleNamespace(time_zone="Europe/Stockholm"),
        )
        binding = {"config_entry_id": "fs-entry", "binding_fingerprint": "binding-a", "entities": {"today_kwh": "sensor.today"}}
        first_at = datetime(2026, 9, 5, 10, tzinfo=UTC)
        second_at = datetime(2026, 9, 5, 10, 15, tzinfo=UTC)
        persist_forecast_solar_frames(self.storage, build_forecast_solar_frames(hass, "site-a", binding, first_at), first_at)
        state.last_updated = datetime(2026, 9, 5, 10, 14, tzinfo=UTC)
        result = persist_forecast_solar_frames(self.storage, build_forecast_solar_frames(hass, "site-a", binding, second_at), second_at)
        self.assertEqual(result["revised"], 1)
        self.assertEqual(self.storage.count_external_frames(), 2)

    def test_forecast_solar_missing_observation_timestamp_fails_closed(self):
        state = SimpleNamespace(state="18.4", attributes={"unit_of_measurement": "kWh"})
        hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda _entity: state),
            config=SimpleNamespace(time_zone="Europe/Stockholm"),
        )
        binding = {"config_entry_id": "fs-entry", "binding_fingerprint": "binding-a", "entities": {"today_kwh": "sensor.today"}}
        self.assertEqual(
            build_forecast_solar_frames(hass, "site-a", binding, datetime(2026, 9, 5, 10, tzinfo=UTC)),
            [],
        )

    def test_forecast_solar_exact_recapture_matches_legacy_point_id(self):
        state = ha_state("2026-09-05T13:30:00+02:00", {"unit_of_measurement": None}, datetime(2026, 9, 5, 9, tzinfo=UTC))
        hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda _entity: state),
            config=SimpleNamespace(time_zone="Europe/Stockholm"),
        )
        binding = {"config_entry_id": "fs-entry", "binding_fingerprint": "binding-a", "entities": {"peak_time_today": "sensor.peak"}}
        captured = datetime(2026, 9, 5, 10, tzinfo=UTC)
        legacy_frames = build_forecast_solar_frames(hass, "site-a", binding, captured)
        legacy_frame, legacy_points = legacy_frames[0]
        legacy_points[0]["point_id"] = "legacy-revision-1-point"
        persist_forecast_solar_frames(self.storage, [(legacy_frame, legacy_points)], captured)
        result = persist_forecast_solar_frames(
            self.storage, build_forecast_solar_frames(hass, "site-a", binding, captured + timedelta(minutes=15)), captured + timedelta(minutes=15)
        )
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(self.storage.connection.execute("SELECT COUNT(*) FROM external_input_frames").fetchone()[0], 1)
        self.assertEqual(
            self.storage.connection.execute("SELECT point_id FROM external_input_points").fetchone()[0],
            "legacy-revision-1-point",
        )

    def test_forecast_solar_exact_recapture_matches_legacy_revision_above_one(self):
        state = ha_state("2026-09-05T13:30:00+02:00", {"unit_of_measurement": None}, datetime(2026, 9, 5, 9, tzinfo=UTC))
        hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda _entity: state),
            config=SimpleNamespace(time_zone="Europe/Stockholm"),
        )
        binding = {"config_entry_id": "fs-entry", "binding_fingerprint": "binding-a", "entities": {"peak_time_today": "sensor.peak"}}
        first_at = datetime(2026, 9, 5, 10, tzinfo=UTC)
        first_frame, first_points = build_forecast_solar_frames(hass, "site-a", binding, first_at)[0]
        first_points[0]["point_id"] = "legacy-revision-1-point"
        persist_forecast_solar_frames(self.storage, [(first_frame, first_points)], first_at)

        state.state = "2026-09-05T14:00:00+02:00"
        state.last_updated = datetime(2026, 9, 5, 14, tzinfo=UTC)
        second_at = datetime(2026, 9, 5, 15, tzinfo=UTC)
        second_frame, second_points = build_forecast_solar_frames(hass, "site-a", binding, second_at)[0]
        second_frame["revision"] = 2
        second_frame["frame_id"] = "legacy-revision-2-frame"
        second_frame["supersedes_frame_id"] = first_frame["frame_id"]
        second_points[0]["point_id"] = "legacy-revision-2-point"
        self.storage.insert_external_frame(second_frame, second_points)

        exact = persist_forecast_solar_frames(
            self.storage, build_forecast_solar_frames(hass, "site-a", binding, second_at + timedelta(minutes=15)), second_at + timedelta(minutes=15)
        )
        self.assertEqual(exact["unchanged"], 1)
        self.assertEqual(self.storage.connection.execute("SELECT COUNT(*) FROM external_input_frames").fetchone()[0], 2)

        state.state = "2026-09-05T15:00:00+02:00"
        state.last_updated = datetime(2026, 9, 5, 15, tzinfo=UTC)
        third_at = datetime(2026, 9, 5, 20, tzinfo=UTC)
        revised = persist_forecast_solar_frames(
            self.storage, build_forecast_solar_frames(hass, "site-a", binding, third_at), third_at
        )
        self.assertEqual(revised["revised"], 1)
        rows = self.storage.connection.execute(
            "SELECT revision, frame_id, supersedes_frame_id FROM external_input_frames ORDER BY revision"
        ).fetchall()
        self.assertEqual([row[0] for row in rows], [1, 2, 3])
        self.assertEqual(rows[2][2], "legacy-revision-2-frame")
        self.assertEqual(
            self.storage.connection.execute(
                "SELECT point_id FROM external_input_points WHERE frame_id = ?", (rows[2][1],)
            ).fetchone()[0],
            f"{rows[2][1]}-p001",
        )

    def test_forecast_solar_generation_is_stable_for_values_and_separate_for_sites(self):
        state = ha_state("18.4", {"unit_of_measurement": "kWh"}, datetime(2026, 9, 5, 9, tzinfo=UTC))
        hass = SimpleNamespace(states=SimpleNamespace(get=lambda _entity: state), config=SimpleNamespace(time_zone="Europe/Stockholm"))
        binding = {"config_entry_id": "fs-entry", "binding_fingerprint": "binding-a", "entities": {"today_kwh": "sensor.today"}}
        first = build_forecast_solar_frames(hass, "site-a", binding, datetime(2026, 9, 5, 10, tzinfo=UTC))[0][0]
        state.state = "19.1"
        state.last_updated = datetime(2026, 9, 5, 14, tzinfo=UTC)
        second = build_forecast_solar_frames(hass, "site-a", binding, datetime(2026, 9, 5, 15, tzinfo=UTC))[0][0]
        other = build_forecast_solar_frames(hass, "site-b", binding, datetime(2026, 9, 5, 15, tzinfo=UTC))[0][0]
        self.assertEqual(first["source_generation_id"], second["source_generation_id"])
        self.assertNotEqual(first["source_generation_id"], other["source_generation_id"])
        self.assertNotEqual(first["semantic_key"], other["semantic_key"])

    def test_forecast_solar_unavailable_and_invalid_peak_fail_closed(self):
        observed_at = datetime(2026, 9, 5, 9, tzinfo=UTC)
        states = {
            "sensor.today": ha_state("unavailable", {"unit_of_measurement": "kWh"}, observed_at),
            "sensor.peak": ha_state("not-a-timestamp", {"unit_of_measurement": None}, observed_at),
        }
        hass = SimpleNamespace(states=SimpleNamespace(get=states.get), config=SimpleNamespace(time_zone="Europe/Stockholm"))
        binding = {"config_entry_id": "fs-entry", "binding_fingerprint": "binding-a", "entities": {"today_kwh": "sensor.today", "peak_time_today": "sensor.peak"}}
        self.assertEqual(build_forecast_solar_frames(hass, "site-a", binding, datetime(2026, 9, 5, 10, tzinfo=UTC)), [])

    def test_forecast_solar_local_day_uses_23_and_25_hour_utc_intervals(self):
        state = ha_state("18.4", {"unit_of_measurement": "kWh"}, datetime(2026, 3, 29, 9, tzinfo=UTC))
        hass = SimpleNamespace(states=SimpleNamespace(get=lambda _entity: state), config=SimpleNamespace(time_zone="Europe/Stockholm"))
        binding = {"config_entry_id": "fs-entry", "binding_fingerprint": "binding-a", "entities": {"today_kwh": "sensor.today"}}
        for captured, expected_hours in ((datetime(2026, 3, 29, 10, tzinfo=UTC), 23), (datetime(2026, 10, 25, 10, tzinfo=UTC), 25)):
            frame = build_forecast_solar_frames(hass, "site-a", binding, captured)[0][0]
            self.assertEqual((frame["valid_to"] - frame["valid_from"]).total_seconds(), expected_hours * 3600)

    def test_changed_real_periods_create_revision_without_destroying_old_frame(self):
        data = price_data([0.42, 0.43])
        captured = datetime(2026, 9, 5, 1, 0, tzinfo=UTC)
        persist_nord_pool_frame(self.storage, data, self.binding, captured)
        changed = price_data([0.99, 0.43])
        persist_nord_pool_frame(self.storage, changed, self.binding, captured + timedelta(minutes=20))
        self.assertFalse(persist_nord_pool_frame(self.storage, changed, self.binding, captured + timedelta(minutes=30)))
        rows = self.storage.connection.execute(
            "SELECT revision, supersedes_frame_id FROM external_input_frames ORDER BY revision"
        ).fetchall()
        self.assertEqual([row[0] for row in rows], [1, 2])
        self.assertIsNotNone(rows[1][1])

    def test_source_scope_mismatch_is_rejected(self):
        data = price_data([0.42])
        frame, points = build_nord_pool_frame(data, self.binding, datetime.now(UTC))
        frame["source_scope"] = "site"
        frame["site_id"] = "site-a"
        with self.assertRaises(ValueError):
            self.storage.insert_external_frame(frame, points)

    def test_unknown_or_nonfinite_point_is_rejected(self):
        data = price_data([0.42])
        frame, points = build_nord_pool_frame(data, self.binding, datetime.now(UTC))
        points[0]["value"] = float("nan")
        self.storage.ensure_global_source_generation(
            {
                "generation_id": frame["source_generation_id"],
                "logical_role": frame["logical_role"],
                "source_identity": {"identity_key": "np-entry|SE2|SEK", "identity_strength": "strong"},
            },
            datetime.now(UTC),
        )
        with self.assertRaises(ValueError):
            self.storage.insert_external_frame(frame, points)

    def test_points_are_immutable(self):
        persist_nord_pool_frame(
            self.storage, price_data([0.42, 0.43]), self.binding,
            datetime(2026, 9, 5, 1, 0, tzinfo=UTC),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.storage.connection.execute(
                "UPDATE external_input_points SET value = 99 WHERE point_key LIKE '2026-%'"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.storage.connection.execute(
                "DELETE FROM external_input_points WHERE point_key LIKE '2026-%'"
            )

    def test_external_frame_write_rolls_back_frame_and_points_on_point_failure(self):
        frame, points = build_nord_pool_frame(
            price_data([0.42, 0.43]), self.binding,
            datetime(2026, 9, 5, 1, 0, tzinfo=UTC),
        )
        self.storage.ensure_global_source_generation(
            {
                "generation_id": frame["source_generation_id"],
                "logical_role": frame["logical_role"],
                "source_identity": {"identity_key": "np-entry|SE2|SEK", "identity_strength": "strong"},
            },
            datetime(2026, 9, 5, 1, 0, tzinfo=UTC),
        )
        points[1]["valid_at"] = datetime(2026, 9, 6, 0, 0, tzinfo=UTC)
        with self.assertRaises(ValueError):
            self.storage.insert_external_frame(frame, points)
        self.assertEqual(self.storage.count_external_frames(), 0)
        self.assertEqual(
            self.storage.connection.execute("SELECT COUNT(*) FROM external_input_points").fetchone()[0],
            0,
        )

    def test_decision_time_reader_selects_known_revision_and_target_point(self):
        first_capture = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
        second_capture = datetime(2026, 9, 5, 14, 0, tzinfo=UTC)
        persist_nord_pool_frame(self.storage, price_data([0.42, 0.43]), self.binding, first_capture)
        persist_nord_pool_frame(self.storage, price_data([0.99, 0.43]), self.binding, second_capture)
        target = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
        before_correction = self.storage.read_external_input_frames(
            datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
            source_scope="global", logical_role="market.price.energy", valid_at=target,
        )
        after_correction = self.storage.read_external_input_frames(
            datetime(2026, 9, 5, 15, 0, tzinfo=UTC),
            source_scope="global", logical_role="market.price.energy", valid_at=target,
        )
        self.assertEqual(len(before_correction), 1)
        self.assertEqual(before_correction[0]["revision"], 1)
        self.assertEqual(before_correction[0]["points"][0]["value"], 0.42)
        self.assertEqual(len(after_correction), 1)
        self.assertEqual(after_correction[0]["revision"], 2)
        self.assertEqual(after_correction[0]["points"][0]["value"], 0.99)

    def test_future_frames_are_invisible_and_source_generation_is_explicit(self):
        first_capture = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
        second_capture = datetime(2026, 9, 5, 14, 0, tzinfo=UTC)
        first_binding = self.binding
        second_binding = {**self.binding, "config_entry_id": "np-entry-2"}
        persist_nord_pool_frame(self.storage, price_data([0.42]), first_binding, first_capture)
        persist_nord_pool_frame(self.storage, price_data([0.52]), second_binding, second_capture)
        target = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
        before = self.storage.read_external_input_frames(
            datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
            source_scope="global", logical_role="market.price.energy", valid_at=target,
        )
        self.assertEqual(len(before), 1)
        expected_generation = "np-" + hashlib.sha256(
            "nord_pool|np-entry|SE2|SEK".encode()
        ).hexdigest()[:32]
        self.assertEqual(before[0]["source_generation_id"], expected_generation)
        after = self.storage.read_external_input_frames(
            datetime(2026, 9, 5, 15, 0, tzinfo=UTC),
            source_scope="global", logical_role="market.price.energy", valid_at=target,
            source_generation_id=before[0]["source_generation_id"],
        )
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]["points"][0]["value"], 0.42)

    def test_invalid_reader_scope_and_decision_timestamps_fail_closed(self):
        with self.assertRaises(ValueError):
            self.storage.read_external_input_frames(
                datetime(2026, 9, 5, 12, 0, tzinfo=UTC), source_scope="site"
            )
        with self.assertRaises(ValueError):
            self.storage.read_external_input_frames(
                datetime(2026, 9, 5, 12, 0), source_scope="global"
            )

    def test_integrity_migration_is_idempotent_across_reopen(self):
        migration = self.storage.connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version = 2"
        ).fetchone()
        self.assertIsNotNone(migration)
        self.storage.close()
        self.storage.open()
        self.assertEqual(
            self.storage.connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' "
                "AND name IN ('point_immutable_update', 'point_immutable_delete')"
            ).fetchone()[0],
            2,
        )


if __name__ == "__main__":
    unittest.main()
