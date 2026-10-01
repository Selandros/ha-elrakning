import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.canonical_storage import CanonicalStorage
from custom_components.elrakning.load_forecast import _intraday_calibration, _qualified_actual, build_forecast_evaluation, build_historical_model_points, build_load_forecast_frame, persist_load_forecast


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
