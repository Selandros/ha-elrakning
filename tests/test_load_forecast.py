import unittest
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.canonical_storage import CanonicalStorage
from custom_components.elrakning.load_forecast import _intraday_calibration, _qualified_actual, build_forecast_evaluation, build_historical_model_points, build_load_forecast_frame, build_load_forecast_shadow_evaluation, persist_load_forecast


UTC = timezone.utc


class LoadForecastTests(unittest.TestCase):
    def test_insufficient_history_is_unavailable(self):
        now = datetime(2026, 9, 19, 12, tzinfo=UTC)
        history = [{
            "logical_role": "house.consumption", "interval_start": now - timedelta(days=2),
            "source_generation_id": "source-a", "value": 500, "quality_status": "good",
        }]
        frame, points = build_load_forecast_frame("site-a", "Europe/Stockholm", history, now)
        self.assertIsNone(frame)
        self.assertEqual(points, [])

    def test_time_shaped_forecast_keeps_provenance_and_no_unknown_zero(self):
        now = datetime(2026, 9, 19, 12, tzinfo=UTC)
        history = []
        for day in range(7):
            start = now - timedelta(days=day + 1) + timedelta(minutes=15)
            history.append({
                "logical_role": "house.consumption", "interval_start": start,
                "source_generation_id": "source-a", "value": 750, "quality_status": "good",
            })
        frame, points = build_load_forecast_frame("site-a", "Europe/Stockholm", history, now, horizon_hours=1)
        self.assertIsNotNone(frame)
        self.assertEqual(frame["payload_schema"], "load_forecast.v1")
        self.assertEqual(frame["classification"], "forecast")
        self.assertTrue(frame["known_at"] <= now)
        self.assertTrue(points)
        self.assertTrue(all(point["value"] == 750 for point in points))
        self.assertTrue(all(point["value"] != 0 for point in points))
        self.assertEqual(points[0]["point"]["model_version"], "load-profile-v2")

    def test_global_prior_bootstraps_new_site_without_site_calibration(self):
        now = datetime(2026, 9, 19, 12, tzinfo=UTC)
        history = self._adaptive_history(now, [1000, 1000, 1000])
        frame, points = build_load_forecast_frame(
            "fiskvik", "Europe/Stockholm", history, now, horizon_hours=1,
            persistent_calibration={"by_slot": {}},
            global_prior_calibration={
                "version": "load-profile-v2-global-prior-v1",
                "by_slot": {"slot:57": {"factor": 0.6, "evidence_count": 12}},
                "provenance": {"fingerprint": "global-prior-fingerprint"},
            },
        )
        self.assertIsNotNone(frame)
        self.assertTrue(points)
        self.assertEqual(points[0]["point"]["calibration_scope"], "global_prior")
        self.assertEqual(points[0]["point"]["global_prior_fingerprint"], "global-prior-fingerprint")
        self.assertAlmostEqual(points[0]["point"]["persistent_factor"], 0.6)
        self.assertEqual(frame["site_id"], "fiskvik")
        self.assertNotIn("foreign-generation", str(frame))

    def test_forecast_frame_has_deterministic_training_and_calibration_provenance(self):
        now = datetime(2026, 9, 19, 12, tzinfo=UTC)
        history = self._adaptive_history(now)
        global_prior = {
            "version": "load-profile-v2-global-prior-v1",
            "by_slot": {},
            "provenance": {"fingerprint": "global-prior-fingerprint"},
        }
        first, _ = build_load_forecast_frame(
            "site-a", "Europe/Stockholm", history, now, horizon_hours=1,
            persistent_calibration={"version": "site-calibration-v1", "by_slot": {}},
            global_prior_calibration=global_prior,
        )
        second, _ = build_load_forecast_frame(
            "site-a", "Europe/Stockholm", history, now, horizon_hours=1,
            persistent_calibration={"version": "site-calibration-v1", "by_slot": {}},
            global_prior_calibration=global_prior,
        )
        self.assertEqual(first["provenance"], second["provenance"])
        for payload in (first["quality"], first["provenance"]):
            self.assertEqual(payload["training_dataset_version"], "canonical-house-consumption-60d-v1")
            self.assertEqual(payload["parameter_config_version"], "load-forecast-parameters-v1")
            self.assertEqual(payload["site_calibration_version"], "site-calibration-v1")
            self.assertEqual(payload["global_model_fingerprint"], "global-prior-fingerprint")
            self.assertTrue(payload["parameter_config_hash"])

    def test_site_calibration_overrides_global_prior(self):
        now = datetime(2026, 9, 19, 12, tzinfo=UTC)
        frame, points = build_load_forecast_frame(
            "fiskvik", "Europe/Stockholm", self._adaptive_history(now), now, horizon_hours=1,
            persistent_calibration={"by_slot": {"5:57": {"factor": 1.1, "evidence_count": 3}}},
            global_prior_calibration={
                "by_slot": {"slot:57": {"factor": 0.6, "evidence_count": 12}},
                "provenance": {"fingerprint": "global-prior-fingerprint"},
            },
        )
        self.assertIsNotNone(frame)
        self.assertTrue(points)
        self.assertEqual(points[0]["point"]["calibration_scope"], "site")
        self.assertAlmostEqual(points[0]["point"]["persistent_factor"], 1.1)
        self.assertIsNone(points[0]["point"]["global_prior_fingerprint"])

    def test_segmented_evaluation_weekend_is_local_and_provenance_versioned(self):
        decision_at = datetime(2026, 9, 28, 12, tzinfo=UTC)
        weekday = datetime(2026, 9, 25, 10, tzinfo=UTC)
        weekend = datetime(2026, 9, 26, 22, tzinfo=UTC)
        frames = [{
            "site_id": "site-a", "payload_schema": "load_forecast.v1", "frame_id": "frame-a",
            "revision": 1, "known_at": datetime(2026, 9, 24, tzinfo=UTC),
            "points": [
                {"valid_at": weekday, "value": 100, "point": {"corrected_forecast_w": 100}},
                {"valid_at": weekend, "value": 100, "point": {"corrected_forecast_w": 100}},
            ],
        }]
        actuals = [{
            "site_id": "site-a", "logical_role": "house.consumption", "unit": "W",
            "interval_start": timestamp, "interval_end": timestamp + timedelta(minutes=15),
            "value": value, "quality_status": "good", "coverage_ratio": 1.0,
        } for timestamp, value in ((weekday, 110), (weekend, 130))]
        provenance = {
            "model_version": "model-v2", "training_dataset_version": "dataset-v3",
            "parameter_config_version": "params-v4", "parameter_config_hash": "hash-v4",
            "site_calibration_version": "site-cal-v5",
        }
        evaluation = build_forecast_evaluation(
            frames, actuals, decision_at, "site-a", timezone_name="Europe/Stockholm", provenance=provenance,
        )
        weekend_metric = evaluation["segments"]["weekend"]
        self.assertEqual(weekend_metric["support_count"], 1)
        self.assertEqual(weekend_metric["eligible_count"], 1)
        self.assertAlmostEqual(weekend_metric["bias_w"], 30)
        self.assertAlmostEqual(weekend_metric["mae_w"], 30)
        self.assertEqual(weekend_metric["model_version"], "model-v2")
        self.assertEqual(weekend_metric["parameter_config_hash"], "hash-v4")
        self.assertEqual(evaluation["segment_contract"]["schema"], "ella_forecast_segment_metrics.v1")
        self.assertEqual(evaluation["segments"]["cold"]["unavailable_reason"], "temperature_input_missing")
        self.assertEqual(evaluation["segments"]["anomaly"]["unavailable_reason"], "explicit_anomaly_classification_missing")
        self.assertEqual(evaluation["segments"]["normal"]["unavailable_reason"], "normal_classifier_contract_missing")

    def test_segmented_evaluation_is_causal_site_scoped_and_deterministic(self):
        decision_at = datetime(2026, 9, 28, 12, tzinfo=UTC)
        valid_at = datetime(2026, 9, 26, 22, tzinfo=UTC)
        frames = [{
            "site_id": "site-a", "payload_schema": "load_forecast.v1", "frame_id": "frame-a",
            "known_at": datetime(2026, 9, 24, tzinfo=UTC),
            "points": [{"valid_at": valid_at, "value": 100, "point": {"corrected_forecast_w": 100}}],
        }, {
            "site_id": "site-b", "payload_schema": "load_forecast.v1", "frame_id": "foreign",
            "known_at": datetime(2026, 9, 24, tzinfo=UTC),
            "points": [{"valid_at": valid_at, "value": 1, "point": {"corrected_forecast_w": 1}}],
        }, {
            "site_id": "site-a", "payload_schema": "load_forecast.v1", "frame_id": "future",
            "known_at": decision_at, "points": [{"valid_at": decision_at - timedelta(minutes=15), "value": 1, "point": {"corrected_forecast_w": 1}}],
        }]
        actuals = [{
            "site_id": "site-a", "logical_role": "house.consumption", "unit": "W",
            "interval_start": valid_at, "interval_end": valid_at + timedelta(minutes=15),
            "value": 100, "quality_status": "good", "coverage_ratio": 1.0,
        }, {
            "site_id": "site-b", "logical_role": "house.consumption", "unit": "W",
            "interval_start": valid_at, "interval_end": valid_at + timedelta(minutes=15),
            "value": 900, "quality_status": "good", "coverage_ratio": 1.0,
        }]
        first = build_forecast_evaluation(frames, actuals, decision_at, "site-a", timezone_name="Europe/Stockholm")
        second = build_forecast_evaluation(frames, actuals, decision_at, "site-a", timezone_name="Europe/Stockholm")
        self.assertEqual(first, second)
        self.assertEqual(first["summary"]["count"], 1)
        self.assertEqual(first["segments"]["weekend"]["support_count"], 1)
        self.assertEqual(first["summary"]["hindsight_excluded_count"], 1)
        self.assertNotIn("site-b", json.dumps(first, sort_keys=True))

    def test_segmented_evaluation_wape_is_unavailable_for_near_zero_actuals(self):
        decision_at = datetime(2026, 9, 28, 12, tzinfo=UTC)
        valid_at = datetime(2026, 9, 26, 22, tzinfo=UTC)
        frame = [{
            "site_id": "site-a", "payload_schema": "load_forecast.v1", "frame_id": "frame-a",
            "known_at": datetime(2026, 9, 24, tzinfo=UTC),
            "points": [{"valid_at": valid_at, "value": 0.5, "point": {"corrected_forecast_w": 0.5}}],
        }]
        actual = [{
            "site_id": "site-a", "logical_role": "house.consumption", "unit": "W",
            "interval_start": valid_at, "interval_end": valid_at + timedelta(minutes=15),
            "value": 0.5, "quality_status": "good", "coverage_ratio": 1.0,
        }]
        metric = build_forecast_evaluation(frame, actual, decision_at, "site-a", timezone_name="Europe/Stockholm")["segments"]["weekend"]
        self.assertIsNone(metric["wape"])
        self.assertEqual(metric["unavailable_reason"], "zero_or_near_zero_actual_denominator")

    def test_load_forecast_shadow_requires_two_real_candidates(self):
        result = build_load_forecast_shadow_evaluation([], [], "site-a", datetime(2026, 9, 28, tzinfo=UTC))
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "single_candidate_only")
        self.assertFalse(result["auto_promotion"])

    def test_load_forecast_shadow_compares_candidates_on_same_frame(self):
        decision_at = datetime(2026, 9, 28, tzinfo=UTC)
        records = [{"site_id": "site-a", "valid_at": "2026-09-26T22:00:00+00:00", "actual_w": 110}]
        candidates = [{
            "site_id": "site-a", "candidate_id": "candidate-a", "model_version": "model-a",
            "parameter_config_hash": "hash-a", "site_calibration_version": "cal-a",
            "global_prior_fingerprint": "prior-a", "input_frame_id": "frame-1",
            "predictions": {"2026-09-26T22:00:00+00:00": 100},
        }, {
            "site_id": "site-a", "candidate_id": "candidate-b", "model_version": "model-b",
            "parameter_config_hash": "hash-b", "site_calibration_version": "cal-b",
            "global_prior_fingerprint": "prior-a", "input_frame_id": "frame-1",
            "predictions": {"2026-09-26T22:00:00+00:00": 90},
        }]
        result = build_load_forecast_shadow_evaluation(records, candidates, "site-a", decision_at)
        self.assertTrue(result["available"])
        self.assertEqual(result["input_frame_id"], "frame-1")
        self.assertEqual([item["bias_w"] for item in result["candidates"]], [10, 20])
        self.assertFalse(result["auto_promotion"])

    def test_evaluation_builds_causal_recency_candidate_on_same_frame(self):
        decision_at = datetime(2026, 9, 10, 12, tzinfo=UTC)
        frame_known_at = datetime(2026, 9, 9, 12, tzinfo=UTC)
        valid_at = datetime(2026, 9, 9, 13, tzinfo=UTC)
        actual = []
        for day in range(1, 8):
            start = frame_known_at - timedelta(days=day) + timedelta(hours=1)
            actual.append({
                "site_id": "site-a", "logical_role": "house.consumption", "unit": "W",
                "interval_start": start, "interval_end": start + timedelta(minutes=15),
                "value": 900 + day * 10, "quality_status": "good", "coverage_ratio": 1.0,
            })
        actual.append({
            "site_id": "site-a", "logical_role": "house.consumption", "unit": "W",
            "interval_start": valid_at, "interval_end": valid_at + timedelta(minutes=15),
            "value": 980, "quality_status": "good", "coverage_ratio": 1.0,
        })
        frames = [{
            "site_id": "site-a", "payload_schema": "load_forecast.v1", "frame_id": "frame-a",
            "known_at": frame_known_at, "revision": 1,
            "quality": {"model_version": "load-profile-v2", "training_dataset_version": "canonical-house-consumption-60d-v1", "parameter_config_version": "load-forecast-parameters-v1", "parameter_config_hash": "champion-hash", "site_calibration_version": "site-cal-v1"},
            "provenance": {"global_model_fingerprint": "global-none"},
            "points": [{"valid_at": valid_at, "value": 1000, "point": {"corrected_forecast_w": 1000}}],
        }]
        result = build_forecast_evaluation(frames, actual, decision_at, "site-a", timezone_name="UTC")
        self.assertTrue(result["shadow"]["available"])
        self.assertEqual(result["shadow"]["input_frame_id"], "frame-a")
        candidates = {item["candidate_id"]: item for item in result["shadow"]["candidates"]}
        self.assertEqual(set(candidates), {"champion", "load-profile-recency-v1"})
        self.assertEqual(candidates["load-profile-recency-v1"]["training_cutoff"], frame_known_at.isoformat())
        self.assertFalse(result["shadow"]["auto_promotion"])

    def test_load_forecast_shadow_rejects_foreign_or_different_frame_candidate(self):
        base = {
            "candidate_id": "candidate-a", "model_version": "model-a", "parameter_config_hash": "hash-a",
            "site_calibration_version": "cal-a", "global_prior_fingerprint": "prior-a", "input_frame_id": "frame-1",
        }
        foreign = {**base, "site_id": "site-b"}
        local = {**base, "site_id": "site-a", "candidate_id": "candidate-b", "input_frame_id": "frame-2"}
        result = build_load_forecast_shadow_evaluation([], [foreign, local], "site-a", datetime(2026, 9, 28, tzinfo=UTC))
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "candidate_site_scope_invalid")

    def _adaptive_history(self, now, current_values=(), current_coverage=1.0):
        history = []
        for day in range(7):
            for offset in (15, -60, -45, -30):
                history.append({
                    "logical_role": "house.consumption", "interval_start": now - timedelta(days=day + 1) + timedelta(minutes=offset),
                    "interval_end": now - timedelta(days=day + 1) + timedelta(minutes=offset + 15),
                    "source_generation_id": "source-a", "value": 1000, "unit": "W", "quality_status": "good",
                    "coverage_ratio": 1.0,
                })
        for index, value in enumerate(current_values):
            start = now - timedelta(minutes=60 - index * 15)
            history.append({
                "logical_role": "house.consumption", "interval_start": start,
                "interval_end": start + timedelta(minutes=15), "source_generation_id": "source-a",
                "value": value, "unit": "W", "quality_status": "good", "coverage_ratio": current_coverage,
            })
        return history

    def test_intraday_correction_moves_future_forecast_down_with_qualified_evidence(self):
        now = datetime(2026, 9, 20, 12, tzinfo=UTC)
        frame, points = build_load_forecast_frame("site-a", "Europe/Stockholm", self._adaptive_history(now, [600, 600, 600]), now, horizon_hours=12)
        self.assertIsNotNone(frame)
        self.assertEqual(frame["quality"]["model_version"], "load-profile-v2")
        self.assertEqual(frame["quality"]["intraday_evidence_count"], 3)
        self.assertLess(frame["quality"]["intraday_factor"], 1.0)
        self.assertLess(points[0]["point"]["corrected_forecast_w"], points[0]["point"]["baseline_w"])

    def test_isolated_spike_does_not_drive_median_correction(self):
        now = datetime(2026, 9, 20, 12, tzinfo=UTC)
        frame, _points = build_load_forecast_frame("site-a", "Europe/Stockholm", self._adaptive_history(now, [600, 600, 2500, 600, 600]), now, horizon_hours=12)
        self.assertIsNotNone(frame)
        self.assertLess(frame["quality"]["intraday_factor"], 1.0)

    def test_low_coverage_and_open_slot_do_not_enter_correction(self):
        now = datetime(2026, 9, 20, 12, tzinfo=UTC)
        history = self._adaptive_history(now, [600, 600], current_coverage=0.001)
        history.append({
            "logical_role": "house.consumption", "interval_start": now - timedelta(minutes=5),
            "interval_end": now + timedelta(minutes=10), "source_generation_id": "source-a",
            "value": 100, "unit": "W", "quality_status": "good", "coverage_ratio": 1.0,
        })
        frame, _points = build_load_forecast_frame("site-a", "Europe/Stockholm", history, now, horizon_hours=12)
        self.assertIsNotNone(frame)
        self.assertEqual(frame["quality"]["intraday_evidence_count"], 0)
        self.assertEqual(frame["quality"]["intraday_factor"], 1.0)

    def test_partial_high_coverage_actual_is_learning_eligible(self):
        now = datetime(2026, 9, 20, 12, tzinfo=UTC)
        base = {
            "logical_role": "house.consumption", "interval_start": now - timedelta(minutes=15),
            "interval_end": now, "unit": "W", "value": 600, "coverage_ratio": 0.99,
        }
        self.assertTrue(_qualified_actual({**base, "quality_status": "partial"}, now))
        self.assertTrue(_qualified_actual({**base, "quality_status": "good"}, now))
        self.assertFalse(_qualified_actual({**base, "quality_status": "partial", "coverage_ratio": 0.89}, now))
        self.assertFalse(_qualified_actual({**base, "quality_status": "bad"}, now))
        self.assertFalse(_qualified_actual({**base, "quality_status": "unknown"}, now))

    def test_partial_high_coverage_slots_drive_intraday_correction_with_provenance(self):
        now = datetime(2026, 9, 20, 12, tzinfo=UTC)
        history = self._adaptive_history(now, [600, 600, 600])
        for row in history[-3:]:
            row["quality_status"] = "partial"
        frame, _points = build_load_forecast_frame("site-a", "Europe/Stockholm", history, now, horizon_hours=12)
        self.assertEqual(frame["quality"]["intraday_evidence_count"], 3)
        self.assertLess(frame["quality"]["intraday_factor"], 1.0)
        self.assertTrue(all(item["quality_status"] == "partial" for item in frame["quality"]["intraday_evidence"]))
        self.assertTrue(all(item["qualification_reason"] == "partial_high_coverage" for item in frame["quality"]["intraday_evidence"]))

    def test_correction_returns_toward_neutral_after_recent_alignment(self):
        now = datetime(2026, 9, 20, 12, tzinfo=UTC)
        frame, _points = build_load_forecast_frame("site-a", "Europe/Stockholm", self._adaptive_history(now, [1000] * 8), now, horizon_hours=12)
        self.assertIsNotNone(frame)
        self.assertEqual(frame["quality"]["intraday_factor"], 1.0)

    def test_correction_is_site_and_local_day_scoped_and_replay_deterministic(self):
        now = datetime(2026, 9, 20, 12, tzinfo=UTC)
        history = self._adaptive_history(now, [600, 600, 600])
        first, _ = build_load_forecast_frame("site-a", "Europe/Stockholm", history, now, horizon_hours=1)
        replay, _ = build_load_forecast_frame("site-a", "Europe/Stockholm", history, now, horizon_hours=1)
        other, _ = build_load_forecast_frame("site-b", "Europe/Stockholm", history, now, horizon_hours=1)
        next_day, _ = build_load_forecast_frame("site-a", "Europe/Stockholm", history, now + timedelta(days=1), horizon_hours=1)
        self.assertEqual(first["frame_id"], replay["frame_id"])
        self.assertNotEqual(first["source_generation_id"], other["source_generation_id"])
        self.assertEqual(next_day["quality"]["intraday_factor"], 1.0)

    def test_unknown_slot_is_omitted_instead_of_zero(self):
        now = datetime(2026, 9, 19, 12, tzinfo=UTC)
        history = []
        for day in range(7):
            history.append({
                "logical_role": "house.consumption", "interval_start": now - timedelta(days=day + 1),
                "source_generation_id": "source-a", "value": 600, "quality_status": "good",
            })
        frame, points = build_load_forecast_frame("site-a", "Europe/Stockholm", history, now, horizon_hours=36)
        self.assertIsNotNone(frame)
        self.assertTrue(points)
        self.assertLess(len(points), 36 * 4)

    def test_partial_canonical_15_minute_history_persists_forecast_generation(self):
        now = datetime(2026, 9, 20, 12, tzinfo=UTC)
        history = []
        for day in range(7):
            history.append({
                "logical_role": "house.consumption",
                "interval_start": now - timedelta(days=day + 1) + timedelta(minutes=15),
                "source_generation_id": "canonical-house-generation",
                "value": 750,
                "quality_status": "partial",
            })

        frame, points = build_load_forecast_frame("site-a", "Europe/Stockholm", history, now, horizon_hours=1)
        self.assertIsNotNone(frame)
        self.assertTrue(points)

        with tempfile.TemporaryDirectory() as directory:
            storage = CanonicalStorage(Path(directory) / "canonical.sqlite")
            storage.open()
            try:
                self.assertEqual(frame["quality_status"], "partial")
                self.assertEqual(frame["quality"]["status"], "low_confidence")
                self.assertTrue(persist_load_forecast(storage, frame, points, now))
                generation = storage.connection.execute(
                    "SELECT source_resolution_kind, source_resolution_seconds "
                    "FROM source_generations WHERE source_generation_id = ?",
                    (frame["source_generation_id"],),
                ).fetchone()
                self.assertEqual(generation, ("native_bucket", 900))
                self.assertIsNotNone(storage.latest_external_frame(frame["semantic_key"]))
            finally:
                storage.close()

    def test_historical_model_points_reuse_weekday_slot_profile(self):
        now = datetime(2026, 9, 20, 12, tzinfo=UTC)
        history = []
        for day in range(7):
            history.append({
                "logical_role": "house.consumption",
                "interval_start": datetime(2026, 9, 14 + day, 10, 0, tzinfo=UTC),
                "source_generation_id": "canonical-house-generation",
                "value": 900 + day,
                "quality_status": "partial",
            })
        points = build_historical_model_points(
            history, "Europe/Stockholm", datetime(2026, 9, 21, 10, 0, tzinfo=UTC),
            datetime(2026, 9, 21, 10, 15, tzinfo=UTC),
        )
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["source"], "model")
        self.assertEqual(points[0]["quality"]["support_method"], "weekday_slot")
        self.assertGreater(points[0]["value"], 0)

    def test_forecast_evaluation_requires_matured_qualified_actual(self):
        now = datetime(2026, 9, 20, 12, tzinfo=UTC)
        valid_at = now - timedelta(minutes=30)
        frame = {
            "site_id": "site-a", "frame_id": "frame-a", "revision": 1,
            "payload_schema": "load_forecast.v1", "known_at": now - timedelta(hours=1),
            "points": [{"valid_at": valid_at, "value": 1000, "point": {"baseline_w": 1000, "corrected_forecast_w": 1000, "model_version": "load-profile-v2"}}],
        }
        actual = [{"site_id": "site-a", "logical_role": "house.consumption", "interval_start": valid_at,
                   "interval_end": valid_at + timedelta(minutes=15), "unit": "W", "value": 600,
                   "quality_status": "good", "coverage_ratio": 1.0}]
        result = build_forecast_evaluation([frame], actual, now, "site-a")
        self.assertEqual(result["summary"]["count"], 1)
        self.assertEqual(result["records"][0]["actual_w"], 600)
        self.assertEqual(result["records"][0]["predicted_w"], 1000)
        self.assertEqual(result["records"][0]["actual_energy_kwh"], 0.15)
        self.assertTrue(result["records"][0]["learning_eligible"])
        self.assertEqual(build_forecast_evaluation([frame], [], now, "site-a")["summary"]["count"], 0)

    def test_forecast_evaluation_keeps_consumption_when_other_role_shares_slot(self):
        now = datetime(2026, 9, 20, 12, tzinfo=UTC)
        valid_at = now - timedelta(minutes=30)
        frame = {
            "site_id": "site-a", "frame_id": "frame-a", "revision": 1,
            "payload_schema": "load_forecast.v1", "known_at": now - timedelta(hours=1),
            "points": [{"valid_at": valid_at, "value": 1000, "point": {"baseline_w": 1000}}],
        }
        actual = [
            {"site_id": "site-a", "logical_role": "house.consumption", "interval_start": valid_at,
             "interval_end": valid_at + timedelta(minutes=15), "unit": "W", "value": 600,
             "quality_status": "good", "coverage_ratio": 1.0},
            {"site_id": "site-a", "logical_role": "battery.power", "interval_start": valid_at,
             "interval_end": valid_at + timedelta(minutes=15), "unit": "W", "value": -300,
             "quality_status": "good", "coverage_ratio": 1.0},
        ]
        result = build_forecast_evaluation([frame], actual, now, "site-a")
        self.assertEqual(result["summary"]["count"], 1)
        self.assertEqual(result["records"][0]["actual_w"], 600)

    def test_forecast_evaluation_marks_poor_actual_as_ineligible(self):
        now = datetime(2026, 9, 20, 12, tzinfo=UTC)
        valid_at = now - timedelta(minutes=30)
        frame = {"site_id": "site-a", "frame_id": "frame-a", "revision": 1, "payload_schema": "load_forecast.v1",
                 "known_at": now - timedelta(hours=1), "points": [{"valid_at": valid_at, "value": 1000, "point": {}}]}
        actual = [{"site_id": "site-a", "logical_role": "house.consumption", "interval_start": valid_at,
                   "interval_end": valid_at + timedelta(minutes=15), "unit": "W", "value": 600,
                   "quality_status": "partial", "coverage_ratio": 0.001}]
        result = build_forecast_evaluation([frame], actual, now, "site-a")
        assert result["summary"]["ineligible_actual_count"] == 1
        assert result["learning_eligibility"]["forecast"] is False

    def test_forecast_evaluation_rejects_hindsight_frame_and_exposes_scorecards(self):
        now = datetime(2026, 9, 20, 12, tzinfo=UTC)
        valid_at = now - timedelta(minutes=30)
        frame = {"site_id": "site-a", "frame_id": "frame-a", "revision": 1, "payload_schema": "load_forecast.v1",
                 "known_at": valid_at + timedelta(minutes=1),
                 "points": [{"valid_at": valid_at, "value": 900, "point": {"baseline_w": 1000, "corrected_forecast_w": 900}}]}
        actual = [{"site_id": "site-a", "logical_role": "house.consumption", "interval_start": valid_at,
                   "interval_end": valid_at + timedelta(minutes=15), "unit": "W", "value": 600,
                   "quality_status": "good", "coverage_ratio": 1.0}]
        result = build_forecast_evaluation([frame], actual, now, "site-a")
        self.assertEqual(result["summary"]["count"], 0)
        self.assertEqual(result["summary"]["hindsight_excluded_count"], 1)
        self.assertIn("counterfactual", result)
        self.assertEqual(result["counterfactual"]["status"], "counterfactual_unavailable")

        frame["known_at"] = valid_at - timedelta(minutes=30)
        result = build_forecast_evaluation([frame], actual, now, "site-a")
        self.assertEqual(result["baseline_scorecard"]["mae_w"], 400)
        self.assertEqual(result["corrected_scorecard"]["mae_w"], 300)

    def test_intraday_materiality_gate_suppresses_tiny_change(self):
        now = datetime(2026, 9, 20, 12, tzinfo=UTC)
        history = self._adaptive_history(now, [950, 950, 950])
        calibration = _intraday_calibration(history, "Europe/Stockholm", now)
        self.assertEqual(calibration["factor"], 1.0)
        self.assertEqual(calibration["reason"], "below_materiality_threshold")


if __name__ == "__main__":
    unittest.main()
