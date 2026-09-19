import asyncio
import unittest
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)

install_elrakning_package_stub()
install_homeassistant_stubs()
install_optional_dependency_stubs()

from custom_components.elrakning.solar_single_run import (
    DATASET,
    MODEL,
    build_single_run_request,
    candidate_run_times,
    decision_at_for_target,
    normalize_single_run_payload,
    select_for_decision,
    source_generation_id,
    target_day_bounds,
)
from custom_components.elrakning.external_input_frames import build_open_meteo_frame
from custom_components.elrakning.canonical_storage import CanonicalStorage
from custom_components.elrakning.external_input_frames import persist_open_meteo_frames
from custom_components.elrakning.canonical_collector import CanonicalCollector
from custom_components.elrakning import canonical_collector as collector_module
from custom_components.elrakning.solar_open_meteo import _location_fingerprint


def _target():
    return {
        "site_id": "site-vik",
        "timezone": "Europe/Stockholm",
        "latitude": 62.2,
        "longitude": 17.49,
        "tilt_deg": 30.0,
        "open_meteo_azimuth_deg": 45.0,
        "peak_power_kwp": 9.45,
    }


def _payload(target_date, timezone_name="Europe/Stockholm", hours=24):
    return {
        "model": MODEL,
        "timezone": timezone_name,
        "hourly": {
            "time": [f"{target_date}T{hour:02d}:00" for hour in range(hours)],
            "global_tilted_irradiance": [100.0] * hours,
        },
        "hourly_units": {"global_tilted_irradiance": "W/m²"},
    }


def _selector_frame(*, known_at=None, run="2026-09-13T06:00:00Z", fingerprint="fp",
                    site_id="site-vik", dataset=DATASET, target_date="2026-09-14",
                    logical_role="solar.irradiance.day_ahead_pv_forecast",
                    generation="om-generation", valid_provenance=True):
    frame = {
        "frame_id": fingerprint,
        "site_id": site_id,
        "source_generation_id": generation,
        "payload_schema": dataset,
        "logical_role": logical_role,
        "valid_from": datetime(2026, 9, 13, 22, tzinfo=timezone.utc),
        "valid_to": datetime(2026, 9, 14, 22, tzinfo=timezone.utc),
        "known_at": known_at,
        "provenance": {
            "provider": "open-meteo",
            "model": MODEL,
            "target_date": target_date,
            "run_initialization_at": run,
            "provider_response_received_at": known_at.isoformat() if known_at else None,
            "knowledge_fingerprint": fingerprint,
        },
    }
    if not valid_provenance:
        frame["provenance"].pop("provider_response_received_at")
        frame["provenance"].pop("knowledge_fingerprint")
    return frame


class SolarSingleRunTests(unittest.TestCase):
    def test_request_has_explicit_single_run_contract(self):
        request = build_single_run_request(_target(), datetime(2026, 9, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(request["run"], "2026-09-12T00:00")
        self.assertEqual(request["models"], MODEL)
        self.assertEqual(request["hourly"], "global_tilted_irradiance")
        self.assertNotIn("previous_day1", request["hourly"])

    def test_run_initialization_is_not_known_at(self):
        target = _target()
        normalized = normalize_single_run_payload(
            _payload("2026-09-13"), target, date(2026, 9, 13), datetime(2026, 9, 12, tzinfo=timezone.utc)
        )
        self.assertEqual(normalized["run_initialization_at"], "2026-09-12T00:00:00+00:00")
        self.assertNotIn("known_at", normalized)

    def test_normal_day_requires_complete_coverage_and_transforms_capacity(self):
        normalized = normalize_single_run_payload(
            _payload("2026-09-13"), _target(), date(2026, 9, 13), datetime(2026, 9, 12, tzinfo=timezone.utc)
        )
        self.assertIsNotNone(normalized)
        self.assertAlmostEqual(normalized["derived_target_day_pv_kwh"], 22.68)
        self.assertEqual(normalized["source_valid_to"], decision_at_for_target(date(2026, 9, 14), "Europe/Stockholm"))

    def test_partial_day_fails_closed(self):
        self.assertIsNone(normalize_single_run_payload(
            _payload("2026-09-13", hours=23), _target(), date(2026, 9, 13), datetime(2026, 9, 12, tzinfo=timezone.utc)
        ))

    def test_dst_days_use_local_timezone_bounds(self):
        spring_start, spring_end = target_day_bounds(date(2026, 3, 29), "Europe/Stockholm")
        autumn_start, autumn_end = target_day_bounds(date(2026, 10, 25), "Europe/Stockholm")
        self.assertEqual(int((spring_end - spring_start).total_seconds() / 3600), 23)
        self.assertEqual(int((autumn_end - autumn_start).total_seconds() / 3600), 25)

    def test_dst_payloads_are_normalized_through_production_path(self):
        target = _target()
        zone = ZoneInfo("Europe/Stockholm")

        def payload_for(local_day, start_utc, hours):
            times = [
                (start_utc + timedelta(hours=index)).astimezone(zone).strftime("%Y-%m-%dT%H:%M")
                for index in range(hours)
            ]
            return {
                "model": MODEL,
                "timezone": "Europe/Stockholm",
                "hourly": {"time": times, "global_tilted_irradiance": [100.0] * hours},
                "hourly_units": {"global_tilted_irradiance": "W/m²"},
            }

        spring = normalize_single_run_payload(
            payload_for(date(2026, 3, 29), datetime(2026, 3, 28, 23, tzinfo=timezone.utc), 23),
            target, date(2026, 3, 29), datetime(2026, 3, 28, tzinfo=timezone.utc),
        )
        autumn = normalize_single_run_payload(
            payload_for(date(2026, 10, 25), datetime(2026, 10, 24, 22, tzinfo=timezone.utc), 25),
            target, date(2026, 10, 25), datetime(2026, 10, 24, tzinfo=timezone.utc),
        )
        self.assertIsNotNone(spring)
        self.assertIsNotNone(autumn)
        self.assertEqual(len({point["valid_at"] for point in spring["points"]}), 23)
        self.assertEqual(len({point["valid_at"] for point in autumn["points"]}), 25)
        self.assertAlmostEqual(spring["derived_target_day_pv_kwh"], 23 * 0.1 * 9.45)
        self.assertAlmostEqual(autumn["derived_target_day_pv_kwh"], 25 * 0.1 * 9.45)

    def test_canonical_sqlite_replay_preserves_earliest_knowledge_and_run_vintages(self):
        target = {
            **_target(),
            "dataset": DATASET,
            "logical_role": "solar.irradiance.day_ahead_pv_forecast",
            "generation_id": source_generation_id(_target()),
            "section_request_fingerprint": "request",
            "endpoint": "https://single-runs-api.open-meteo.com/v1/forecast",
            "model": MODEL,
            "payload_schema": DATASET,
            "normalization_version": "open_meteo_single_run_hourly.v1",
            "transformation_version": "gti_to_pv_kwh.v1",
            "decision_at": datetime(2026, 9, 14, 22, tzinfo=timezone.utc),
        }
        target_date = date(2026, 9, 14)

        def make_frame(run, received, value=100.0):
            payload = _payload(target_date.isoformat())
            payload["hourly"]["global_tilted_irradiance"] = [value] * 24
            normalized = normalize_single_run_payload(
                payload, target, target_date, datetime.fromisoformat(run.replace("Z", "+00:00"))
            )
            self.assertIsNotNone(normalized)
            return build_open_meteo_frame(
                {**target, "semantic_run_identity": normalized["run_initialization_at"]},
                normalized, received, received, received,
            )

        with tempfile.TemporaryDirectory() as directory:
            storage = CanonicalStorage(Path(directory) / "canonical.sqlite")
            storage.open()
            try:
                early = make_frame("2026-09-13T00:00:00Z", datetime(2026, 9, 13, 5, tzinfo=timezone.utc))
                self.assertEqual(persist_open_meteo_frames(storage, [early], early[0]["known_at"])["written"], 1)
                duplicate = make_frame("2026-09-13T00:00:00Z", datetime(2026, 9, 13, 21, tzinfo=timezone.utc))
                self.assertEqual(persist_open_meteo_frames(storage, [duplicate], duplicate[0]["known_at"])["unchanged"], 1)
                newer = make_frame("2026-09-13T06:00:00Z", datetime(2026, 9, 13, 11, tzinfo=timezone.utc))
                self.assertEqual(persist_open_meteo_frames(storage, [newer], newer[0]["known_at"])["written"], 1)
                post = make_frame("2026-09-13T12:00:00Z", datetime(2026, 9, 13, 23, tzinfo=timezone.utc))
                self.assertEqual(persist_open_meteo_frames(storage, [post], post[0]["known_at"])["written"], 1)
                changed = make_frame("2026-09-13T06:00:00Z", datetime(2026, 9, 13, 12, tzinfo=timezone.utc), 101.0)
                self.assertEqual(persist_open_meteo_frames(storage, [changed], changed[0]["known_at"])["revised"], 1)

                visible = storage.read_external_input_frames(
                    datetime(2026, 9, 13, 22, tzinfo=timezone.utc), source_scope="site",
                    site_id="site-vik", source_generation_id=target["generation_id"],
                    logical_role=target["logical_role"],
                )
                status, selected = select_for_decision(
                    visible, site_id="site-vik", target_date=target_date,
                    timezone_name=target["timezone"], source_generation_id=target["generation_id"],
                    decision_at=target["decision_at"],
                )
                self.assertEqual(status, "VERIFIED_PRE_DECISION")
                self.assertEqual(selected["provenance"]["run_initialization_at"], "2026-09-13T06:00:00+00:00")
                self.assertEqual(selected["revision"], 2)
                self.assertEqual(len({frame["semantic_key"] for frame in visible}), 2)
                self.assertTrue(all(frame["known_at"] <= target["decision_at"] for frame in visible))
            finally:
                storage.close()

    def test_generation_stable_across_runs_and_changes_with_site_semantics(self):
        first = source_generation_id(_target())
        same = source_generation_id(_target())
        changed = _target()
        changed["tilt_deg"] = 31.0
        self.assertEqual(first, same)
        self.assertNotEqual(first, source_generation_id(changed))

    def test_candidate_runs_never_cross_decision_boundary(self):
        now = datetime(2026, 9, 13, 21, 30, tzinfo=timezone.utc)
        cutoff = datetime(2026, 9, 13, 22, tzinfo=timezone.utc)
        self.assertTrue(all(item < cutoff for item in candidate_run_times(now, cutoff)))

    def test_dataset_is_distinct_from_existing_paths(self):
        self.assertEqual(DATASET, "open_meteo.single_run_day_ahead_pv.v1")
        self.assertNotEqual(DATASET, "open_meteo.manager_forecast.v1")
        self.assertNotEqual(DATASET, "open_meteo.evidence_previous_day1.v1")

    def test_timezone_and_gti_unit_must_match_contract(self):
        target = _target()
        self.assertIsNotNone(normalize_single_run_payload(
            _payload("2026-09-13"), target, date(2026, 9, 13), datetime(2026, 9, 12, tzinfo=timezone.utc)
        ))
        for payload in (
            {**_payload("2026-09-13"), "timezone": "UTC"},
            {key: value for key, value in _payload("2026-09-13").items() if key != "timezone"},
            {**_payload("2026-09-13"), "hourly_units": {}},
            {**_payload("2026-09-13"), "hourly_units": {"global_tilted_irradiance": "kWh/m²"}},
        ):
            self.assertIsNone(normalize_single_run_payload(
                payload, target, date(2026, 9, 13), datetime(2026, 9, 12, tzinfo=timezone.utc)
            ))

    def test_invalid_gti_unit_cannot_reach_canonical_storage(self):
        target = _target()
        payload = _payload("2026-09-13")
        payload["hourly_units"] = {"global_tilted_irradiance": "kWh/m²"}
        self.assertIsNone(normalize_single_run_payload(
            payload, target, date(2026, 9, 13), datetime(2026, 9, 12, tzinfo=timezone.utc)
        ))
        with tempfile.TemporaryDirectory() as directory:
            storage = CanonicalStorage(Path(directory) / "canonical.sqlite")
            storage.open()
            try:
                self.assertEqual(storage.count_external_frames(), 0)
            finally:
                storage.close()

    def test_site_independent_collector_persists_only_enabled_vikarbodarna_target(self):
        site_id = "site-vik"
        location = {
            "verification_state": "verified",
            "latitude": 62.2,
            "longitude": 17.49,
            "timezone": "Europe/Stockholm",
            "provenance": "test-fixture",
        }
        location["location_fingerprint"] = _location_fingerprint(
            location["latitude"], location["longitude"], location["timezone"]
        )
        vik_config = {
            "collection_enabled": True,
            "location": location,
            "bindings": {"open_meteo": {"source": "open_meteo_global_tilted_irradiance"}},
            "power": {
                "solar_entities": ["sensor.pv"],
                "solar_array_metadata": {
                    "sensor.pv": {"capacity_kwp": 9.45, "tilt_deg": 30, "azimuth_deg": 45},
                },
            },
        }
        fiskvik_config = {"collection_enabled": False}

        class Identity:
            active_site_id = "site-fiskvik"

            def collection_site_configs(self):
                return {site_id: vik_config, "site-fiskvik": fiskvik_config}

        class Hass:
            async def async_add_executor_job(self, callback, *args):
                return callback(*args)

        fixed_now = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)

        async def fake_fetch(_hass, target, target_date, run_initialization_at):
            normalized = normalize_single_run_payload(
                _payload(target_date.isoformat()), target, target_date, run_initialization_at
            )
            self.assertIsNotNone(normalized)
            return normalized, datetime(2026, 9, 19, 12, 5, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as directory:
            collector = CanonicalCollector(
                Hass(), Identity(), Path(directory) / "canonical.sqlite"
            )
            try:
                collector.storage.open()
                with patch.object(collector_module.dt_util, "now", return_value=fixed_now), \
                     patch.object(collector_module, "candidate_run_times", return_value=[datetime(2026, 9, 19, 6, tzinfo=timezone.utc)]), \
                     patch.object(collector_module, "async_fetch_single_run_target", side_effect=fake_fetch):
                    result = asyncio.run(
                        collector.async_capture_single_run_day_ahead(trigger="hourly_cadence")
                    )
                self.assertEqual(result["status"], "success")
                self.assertEqual(result["target_count"], 1)
                self.assertEqual(result["target_site_ids"], [site_id])
                frames = collector.storage.read_external_input_frames(
                    datetime(2026, 9, 19, 21, tzinfo=timezone.utc),
                    source_scope="site", site_id=site_id,
                )
                self.assertTrue(frames)
                self.assertTrue(all(frame["site_id"] == site_id for frame in frames))
                fiskvik = collector.storage.read_external_input_frames(
                    datetime(2026, 9, 19, 21, tzinfo=timezone.utc),
                    source_scope="site", site_id="site-fiskvik",
                )
                self.assertEqual(fiskvik, [])
            finally:
                collector.storage.close()

    def test_replay_selector_keeps_latest_causal_run_and_excludes_post_cutoff(self):
        generation = source_generation_id(_target())
        decision = datetime(2026, 9, 13, 22, tzinfo=timezone.utc)

        def frame(run, known, fingerprint):
            return {
                "frame_id": fingerprint,
                "site_id": "site-vik",
                "source_generation_id": generation,
                "payload_schema": DATASET,
                "logical_role": "solar.irradiance.day_ahead_pv_forecast",
                "valid_from": datetime(2026, 9, 13, 22, tzinfo=timezone.utc),
                "valid_to": datetime(2026, 9, 14, 22, tzinfo=timezone.utc),
                "known_at": known,
                "provenance": {
                    "provider": "open-meteo",
                    "model": MODEL,
                    "target_date": "2026-09-14",
                    "run_initialization_at": run,
                    "provider_response_received_at": known.isoformat(),
                    "knowledge_fingerprint": fingerprint,
                },
            }

        frames = [
            frame("2026-09-13T00:00:00Z", datetime(2026, 9, 13, 5, tzinfo=timezone.utc), "old"),
            frame("2026-09-13T06:00:00Z", datetime(2026, 9, 13, 11, tzinfo=timezone.utc), "new"),
            frame("2026-09-13T12:00:00Z", datetime(2026, 9, 13, 23, tzinfo=timezone.utc), "late"),
        ]
        status, selected = select_for_decision(
            frames, site_id="site-vik", target_date=date(2026, 9, 14),
            timezone_name="Europe/Stockholm", source_generation_id=generation, decision_at=decision,
        )
        self.assertEqual(status, "VERIFIED_PRE_DECISION")
        self.assertEqual(selected["frame_id"], "new")

    def test_replay_selector_fails_closed_on_same_boundary_fingerprints(self):
        generation = source_generation_id(_target())
        known = datetime(2026, 9, 13, 11, tzinfo=timezone.utc)
        frames = [
            {
                "frame_id": fingerprint,
                "site_id": "site-vik",
                "source_generation_id": generation,
                "payload_schema": DATASET,
                "logical_role": "solar.irradiance.day_ahead_pv_forecast",
                "valid_from": datetime(2026, 9, 13, 22, tzinfo=timezone.utc),
                "valid_to": datetime(2026, 9, 14, 22, tzinfo=timezone.utc),
                "known_at": known,
                "provenance": {
                    "provider": "open-meteo",
                    "model": MODEL,
                    "target_date": "2026-09-14",
                    "run_initialization_at": "2026-09-13T06:00:00Z",
                    "provider_response_received_at": known.isoformat(),
                    "knowledge_fingerprint": fingerprint,
                },
            }
            for fingerprint in ("x", "y")
        ]
        status, selected = select_for_decision(
            frames, site_id="site-vik", target_date=date(2026, 9, 14),
            timezone_name="Europe/Stockholm", source_generation_id=generation,
            decision_at=datetime(2026, 9, 13, 22, tzinfo=timezone.utc),
        )
        self.assertEqual(status, "AMBIGUOUS")
        self.assertIsNone(selected)

    def test_replay_status_precedence_and_model_eligibility(self):
        decision = datetime(2026, 9, 13, 22, tzinfo=timezone.utc)
        kwargs = {
            "site_id": "site-vik", "target_date": date(2026, 9, 14),
            "timezone_name": "Europe/Stockholm", "source_generation_id": "om-generation",
            "decision_at": decision,
        }
        cases = (
            ([], "MISSING"),
            ([_selector_frame(known_at=None, valid_provenance=False)], "INSUFFICIENT_PROVENANCE"),
            ([_selector_frame(known_at=datetime(2026, 9, 13, 23, tzinfo=timezone.utc))], "VERIFIED_POST_DECISION"),
            ([_selector_frame(known_at=datetime(2026, 9, 13, 21, tzinfo=timezone.utc)), _selector_frame(known_at=datetime(2026, 9, 13, 23, tzinfo=timezone.utc), fingerprint="post")], "VERIFIED_PRE_DECISION"),
            ([_selector_frame(known_at=datetime(2026, 9, 13, 21, tzinfo=timezone.utc), valid_provenance=False), _selector_frame(known_at=datetime(2026, 9, 13, 23, tzinfo=timezone.utc), fingerprint="post")], "INSUFFICIENT_PROVENANCE"),
            ([_selector_frame(known_at=datetime(2026, 9, 13, 21, tzinfo=timezone.utc), valid_provenance=False), _selector_frame(known_at=datetime(2026, 9, 13, 21, tzinfo=timezone.utc), fingerprint="x"), _selector_frame(known_at=datetime(2026, 9, 13, 21, tzinfo=timezone.utc), fingerprint="y")], "INSUFFICIENT_PROVENANCE"),
        )
        for frames, expected in cases:
            with self.subTest(expected=expected):
                status, selected = select_for_decision(frames, **kwargs)
                self.assertEqual(status, expected)
                if expected != "VERIFIED_PRE_DECISION":
                    self.assertIsNone(selected)

        out_of_scope = [
            _selector_frame(known_at=None, valid_provenance=False, site_id="other-site"),
            _selector_frame(known_at=None, valid_provenance=False, dataset="open_meteo.manager_forecast.v1"),
            _selector_frame(known_at=None, valid_provenance=False, target_date="2026-09-13"),
            _selector_frame(known_at=datetime(2026, 9, 13, 21, tzinfo=timezone.utc)),
        ]
        status, selected = select_for_decision(out_of_scope, **kwargs)
        self.assertEqual(status, "VERIFIED_PRE_DECISION")
        self.assertIsNotNone(selected)

    def test_scope_matching_frame_without_provenance_is_insufficient(self):
        frame = _selector_frame(known_at=datetime(2026, 9, 13, 21, tzinfo=timezone.utc))
        frame.pop("provenance")
        status, selected = select_for_decision(
            [frame], site_id="site-vik", target_date=date(2026, 9, 14),
            timezone_name="Europe/Stockholm", source_generation_id="om-generation",
            decision_at=datetime(2026, 9, 13, 22, tzinfo=timezone.utc),
        )
        self.assertEqual(status, "INSUFFICIENT_PROVENANCE")
        self.assertIsNone(selected)

    def test_persisted_post_decision_frame_is_classified_post_decision(self):
        target = {
            **_target(),
            "dataset": DATASET,
            "logical_role": "solar.irradiance.day_ahead_pv_forecast",
            "generation_id": source_generation_id(_target()),
            "section_request_fingerprint": "request-post",
            "endpoint": "https://single-runs-api.open-meteo.com/v1/forecast",
            "model": MODEL,
            "payload_schema": DATASET,
            "normalization_version": "open_meteo_single_run_hourly.v1",
            "transformation_version": "gti_to_pv_kwh.v1",
            "decision_at": datetime(2026, 9, 13, 22, tzinfo=timezone.utc),
        }
        target_date = date(2026, 9, 14)
        run = datetime(2026, 9, 13, 6, tzinfo=timezone.utc)
        received = datetime(2026, 9, 13, 23, tzinfo=timezone.utc)
        normalized = normalize_single_run_payload(_payload(target_date.isoformat()), target, target_date, run)
        self.assertIsNotNone(normalized)
        pair = build_open_meteo_frame(
            {**target, "semantic_run_identity": normalized["run_initialization_at"]},
            normalized, received, received, received,
        )
        with tempfile.TemporaryDirectory() as directory:
            storage = CanonicalStorage(Path(directory) / "canonical.sqlite")
            storage.open()
            try:
                self.assertEqual(persist_open_meteo_frames(storage, [pair], received)["written"], 1)
                frames = storage.read_external_input_frames(
                    datetime(2026, 9, 14, 1, tzinfo=timezone.utc),
                    source_scope="site", site_id="site-vik",
                    source_generation_id=target["generation_id"],
                    logical_role=target["logical_role"],
                )
                status, selected = select_for_decision(
                    frames, site_id="site-vik", target_date=target_date,
                    timezone_name=target["timezone"], source_generation_id=target["generation_id"],
                    decision_at=target["decision_at"],
                )
                self.assertEqual(status, "VERIFIED_POST_DECISION")
                self.assertIsNone(selected)
            finally:
                storage.close()

    def test_run_vintages_have_separate_semantic_frames(self):
        target = {
            **_target(),
            "dataset": DATASET,
            "logical_role": "solar.irradiance.day_ahead_pv_forecast",
            "generation_id": source_generation_id(_target()),
            "section_request_fingerprint": "request",
            "endpoint": "https://single-runs-api.open-meteo.com/v1/forecast",
            "model": MODEL,
            "payload_schema": DATASET,
            "normalization_version": "open_meteo_single_run_hourly.v1",
            "transformation_version": "gti_to_pv_kwh.v1",
        }
        received = datetime(2026, 9, 12, 5, tzinfo=timezone.utc)

        def frame(run):
            normalized = {
                "quality_status": "good",
                "quality": {"status": "good", "gaps": []},
                "points": [{
                    "source_timestamp": "2026-09-13T00:00",
                    "valid_at": datetime(2026, 9, 12, 22, tzinfo=timezone.utc),
                    "value": 100.0,
                    "unit": "W/m²",
                    "quality_status": "good",
                }],
                "run_initialization_at": run,
                "target_date": "2026-09-13",
                "derived_target_day_pv_kwh": 1.0,
                "api_metadata": {"timezone": "Europe/Stockholm"},
            }
            return build_open_meteo_frame(
                {**target, "semantic_run_identity": run}, normalized, received, received, received
            )[0]

        first = frame("2026-09-12T00:00:00+00:00")
        same = frame("2026-09-12T00:00:00+00:00")
        other = frame("2026-09-12T06:00:00+00:00")
        self.assertEqual(first["semantic_key"], same["semantic_key"])
        self.assertNotEqual(first["semantic_key"], other["semantic_key"])
        self.assertEqual(first["frame_id"], same["frame_id"])
        self.assertNotEqual(first["frame_id"], other["frame_id"])
        self.assertEqual(first["provenance"]["provider_response_received_at"], received.isoformat())
        self.assertEqual(first["provenance"]["run_initialization_at"], "2026-09-12T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
