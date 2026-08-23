import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "elhandel" / "providers" / "greenely_consumption.py"
spec = spec_from_file_location("greenely_consumption", path)
module = module_from_spec(spec)
spec.loader.exec_module(module)
normalize = module.normalize_greenely_consumption
summarize = module.summarize_greenely_consumption


class GreenelyConsumptionTests(unittest.TestCase):
    def test_timestamp_map_is_sorted_and_converted(self):
        payload = {"data": {"2": {"usage": 32, "localtime": "2026-08-01T02:00:00"}, "1": {"usage": 63, "localtime": "2026-08-01T01:00:00"}}}
        result = normalize(payload)
        self.assertEqual([item["usage_kwh"] for item in result], [0.063, 0.032])
        self.assertEqual(result[0]["localtime"], "2026-08-01T01:00:00")

    def test_month_to_date_uses_localtime(self):
        payload = {"data": {"1": {"usage": 63, "localtime": "2026-08-01T01:00:00"}, "2": {"usage": 32, "localtime": "2026-08-02T01:00:00"}, "3": {"usage": 100, "localtime": "2026-09-01T01:00:00"}}}
        result = summarize(payload, "2026-08")
        self.assertEqual(result["month_to_date_kwh"], 0.095)
        self.assertEqual(result["latest_sample_at"], "2026-08-02T01:00:00")

    def test_invalid_points_are_ignored(self):
        self.assertEqual(normalize({"data": {"1": {"usage": "bad", "localtime": "2026-08-01"}}}), [])

    def test_missing_month_is_none(self):
        self.assertIsNone(summarize({"data": {"1": {"usage": 1, "localtime": "2026-08-01"}}}, "2026-09"))


if __name__ == "__main__":
    unittest.main()
