from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import unittest


_PATH = Path(__file__).parents[1] / "custom_components" / "elrakning" / "invoice.py"
_SPEC = spec_from_file_location("elrakning_invoice", _PATH)
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
build_today_variable_cost = _MODULE.build_today_variable_cost
build_daily_actual_cost = _MODULE.build_daily_actual_cost
build_bucketed_actual_cost = _MODULE.build_bucketed_actual_cost


class InvoiceTodayCostTests(unittest.TestCase):
    def test_daily_actual_cost_is_componentized_and_excludes_fixed_fee(self):
        day_start = datetime.fromisoformat("2026-08-02T00:00:00+02:00")
        day_end = datetime.fromisoformat("2026-08-02T01:00:00+02:00")
        points = [
            {"timestamp": "2026-08-02T00:00:00+02:00", "import_kw": 2},
            {"timestamp": "2026-08-02T00:30:00+02:00", "import_kw": 2},
            {"timestamp": "2026-08-02T01:00:00+02:00", "import_kw": 2},
        ]
        periods = [{
            "start": "2026-08-02T00:00:00+02:00",
            "end": "2026-08-02T01:00:00+02:00",
            "trade_customer_price_ore_per_kwh": 100,
            "grid_variable_ore_per_kwh": 200,
            "fixed_fee_sek": 999,
        }]
        result = build_daily_actual_cost(points, periods, day_start, day_end)
        self.assertEqual(result["import_kwh"], 2)
        self.assertEqual(result["elhandel_sek"], 2)
        self.assertEqual(result["elnat_variable_sek"], 4)
        self.assertEqual(result["total_variable_cost_sek"], 6)
        self.assertEqual(result["average_price_ore_per_kwh"], 300)
        self.assertNotIn("fixed_fee_sek", result)

    def test_daily_actual_cost_is_fail_closed_on_uncovered_gap(self):
        day_start = datetime.fromisoformat("2026-08-02T00:00:00+02:00")
        day_end = datetime.fromisoformat("2026-08-02T01:00:00+02:00")
        points = [
            {"timestamp": "2026-08-02T00:00:00+02:00", "import_kw": 2},
            {"timestamp": "2026-08-02T00:15:00+02:00", "import_kw": 2},
            {"timestamp": "2026-08-02T01:00:00+02:00", "import_kw": 2},
        ]
        periods = [{
            "start": "2026-08-02T00:00:00+02:00",
            "end": "2026-08-02T01:00:00+02:00",
            "trade_customer_price_ore_per_kwh": 100,
            "grid_variable_ore_per_kwh": 200,
        }]
        self.assertIsNone(build_daily_actual_cost(points, periods, day_start, day_end))

    def test_uses_only_observed_local_today_variable_costs(self):
        now = datetime.fromisoformat("2026-08-02T00:45:00+02:00")
        points = [
            {"timestamp": "2026-08-01T23:45:00+02:00", "import_kw": 2},
            {"timestamp": "2026-08-02T00:00:00+02:00", "import_kw": 2},
            {"timestamp": "2026-08-02T00:15:00+02:00", "import_kw": 2},
            {"timestamp": "2026-08-02T00:30:00+02:00", "import_kw": 2},
            {"timestamp": "2026-08-02T00:45:00+02:00", "import_kw": 2},
        ]
        periods = [
            {"start": "2026-08-01T23:45:00+02:00", "end": "2026-08-02T00:15:00+02:00", "trade_customer_price_ore_per_kwh": 100, "grid_variable_ore_per_kwh": 200},
            {"start": "2026-08-02T00:15:00+02:00", "end": "2026-08-02T00:30:00+02:00", "trade_customer_price_ore_per_kwh": 100, "grid_variable_ore_per_kwh": 200, "fixed_fee_sek": 999, "accrued_fixed_fee_sek": 999},
            {"start": "2026-08-02T00:30:00+02:00", "end": "2026-08-02T00:45:00+02:00", "trade_customer_price_ore_per_kwh": 100, "grid_variable_ore_per_kwh": 200, "forecast": True},
            {"start": "2026-08-02T00:45:00+02:00", "end": "2026-08-02T01:00:00+02:00", "trade_customer_price_ore_per_kwh": 100, "grid_variable_ore_per_kwh": 200},
        ]
        result = build_today_variable_cost(points, periods, now)
        self.assertEqual(result, {
            "variable_cost_sek": 3.0,
            "trade_cost_sek": 1.0,
            "grid_cost_sek": 2.0,
            "imported_kwh": 1.0,
        })

    def test_missing_or_invalid_rows_do_not_fabricate_a_value(self):
        now = datetime(2026, 8, 2, 1, tzinfo=timezone.utc)
        points = [
            {"timestamp": "2026-08-02T00:00:00+00:00", "import_kw": 2},
            {"timestamp": "2026-08-02T00:15:00+00:00", "import_kw": 2},
        ]
        self.assertIsNone(build_today_variable_cost(points, [{"start": "bad", "end": "2026-08-02T00:15:00+00:00"}], now))
        self.assertIsNone(build_today_variable_cost(points, [], now))

    def test_bucketed_kwh_is_priced_without_kwh_to_kw_conversion_or_fixed_fee(self):
        start = datetime.fromisoformat("2026-08-02T00:00:00+02:00")
        result = build_bucketed_actual_cost(
            [{"timestamp": start.isoformat(), "end": "2026-08-02T00:15:00+02:00", "import_kwh": 0.5}],
            [{"start": start.isoformat(), "end": "2026-08-02T00:15:00+02:00", "trade_customer_price_ore_per_kwh": 100, "grid_variable_ore_per_kwh": 200, "fixed_fee_sek": 999}],
            start, datetime.fromisoformat("2026-08-02T00:15:00+02:00"),
        )
        self.assertEqual(result["import_kwh"], 0.5)
        self.assertEqual(result["total_variable_cost_sek"], 1.5)
        self.assertNotIn("fixed_fee_sek", result)

    def test_bucketed_cost_fails_closed_when_price_does_not_cover_bucket(self):
        start = datetime.fromisoformat("2026-08-02T00:00:00+02:00")
        result = build_bucketed_actual_cost(
            [{"timestamp": start.isoformat(), "end": "2026-08-02T00:15:00+02:00", "import_kwh": 0.5}],
            [{"start": start.isoformat(), "end": "2026-08-02T00:10:00+02:00", "trade_customer_price_ore_per_kwh": 100, "grid_variable_ore_per_kwh": 200}],
            start, datetime.fromisoformat("2026-08-02T00:15:00+02:00"),
        )
        self.assertIsNone(result)
