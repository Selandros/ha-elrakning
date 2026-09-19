import unittest
from datetime import datetime, timedelta, timezone

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.load_forecast import build_load_forecast_frame


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
        self.assertEqual(points[0]["point"]["model_version"], "load-profile-v1")

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


if __name__ == "__main__":
    unittest.main()
