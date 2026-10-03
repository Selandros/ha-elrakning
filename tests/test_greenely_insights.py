import unittest
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "elhandel" / "providers" / "greenely_insights.py"
spec = spec_from_file_location("greenely_insights", path)
module = module_from_spec(spec)
spec.loader.exec_module(module)


class GreenelyInsightsTests(unittest.TestCase):
    def test_cost_distribution_preserves_provider_values_without_billing_semantics(self):
        payload = {
            "data": {
                "2026-10-01": {
                    "cheap": {"daily_rate": 43.0, "usage": 5827.0, "total_cost": 135799258.0},
                    "middle": {"daily_rate": 27.0, "usage": 3729.0, "total_cost": 135988021.0},
                    "expensive": {"daily_rate": 30.0, "usage": 3952.0, "total_cost": 164233352.0},
                    "energy_score": 56,
                }
            }
        }
        result = module.normalize_cost_distribution(payload, date(2026, 10, 1), date(2026, 10, 2))
        self.assertTrue(result["available"])
        self.assertEqual(result["unit_status"], "percentage_verified")
        self.assertEqual(result["unit"], "percent")
        self.assertEqual(result["days"][0]["categories"]["cheap"]["usage_provider"], 5827.0)
        self.assertEqual(result["days"][0]["categories"]["cheap"]["daily_rate_percent"], 43.0)
        self.assertEqual(result["days"][0]["energy_score"], 56)

    def test_spot_price_preserves_completion_and_provider_unit(self):
        payload = {"data": {"1790805600": {
            "localtime": "2026-10-01 00:00", "price": 55369,
            "is_complete": True, "min_resolution": "quarter_hourly",
        }}}
        result = module.normalize_spot_price(payload, date(2026, 10, 1), date(2026, 10, 1))
        self.assertTrue(result["available"])
        self.assertEqual(result["unit_status"], "unit_verified")
        self.assertEqual(result["unit"], "sek_per_kwh")
        self.assertEqual(result["observations"][0]["price_provider"], 55369)
        self.assertAlmostEqual(result["observations"][0]["price_sek_per_kwh"], 0.55369)
        self.assertTrue(result["observations"][0]["is_complete"])

    def test_currency_cost_normalizes_scale_and_average_without_billing_semantics(self):
        payload = {"data": {
            "1790805600": {"localtime": "2026-10-01 19:00", "usage": 1479, "cost": 84047},
            "1790809200": {"localtime": "2026-10-01 20:00", "usage": 1000, "cost": 56827},
        }}
        result = module.normalize_consumption_cost(
            payload, date(2026, 10, 1), date(2026, 10, 2), 2.479, "2026-10"
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["scale"], 100000)
        self.assertAlmostEqual(result["samples"][0]["cost_sek"], 0.84047)
        self.assertAlmostEqual(result["month_to_date_cost_sek"], 1.40874)
        self.assertAlmostEqual(result["average_price_ore_per_kwh"], 56.8269463)
        self.assertNotIn("total_cost_sek", result)

    def test_invalid_or_out_of_period_data_is_unavailable(self):
        self.assertFalse(module.normalize_spot_price(
            {"data": {"1": {"localtime": "2026-09-30 00:00", "price": 1}}},
            date(2026, 10, 1), date(2026, 10, 2),
        )["available"])
        self.assertFalse(module.normalize_cost_distribution(
            {"data": {"2026-10-01": None}}, date(2026, 10, 1), date(2026, 10, 2)
        )["available"])


if __name__ == "__main__":
    unittest.main()
