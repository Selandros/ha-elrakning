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
build_canonical_cost_result = _MODULE.build_canonical_cost_result


class InvoiceTodayCostTests(unittest.TestCase):
    def test_provider_grid_cost_remains_available_without_greenely_tariff(self):
        start = datetime.fromisoformat("2026-10-01T00:00:00+02:00")
        end = datetime.fromisoformat("2026-10-01T00:15:00+02:00")
        result = build_bucketed_actual_cost(
            [{"timestamp": start.isoformat(), "end": end.isoformat(), "import_kwh": 1.0}],
            [{"start": start.isoformat(), "end": end.isoformat(), "trade_customer_price_ore_per_kwh": None, "grid_variable_ore_per_kwh": 100}],
            start, end,
        )
        self.assertEqual(result["elnat_variable_sek"], 1.0)
        self.assertIsNone(result["elhandel_sek"])
        self.assertEqual(result["quality"], "partial")
        self.assertEqual(result["trade_cost_status"], "unavailable")

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

    def test_canonical_cost_result_keeps_grid_partial_when_greenely_invoice_is_missing(self):
        result = build_canonical_cost_result(
            month="2026-10",
            daily_breakdown=[{"date": "2026-10-01", "actual": {
                "import_kwh": 28.611,
                "elnat_variable_sek": 40.626,
                "total_variable_cost_sek": 40.626,
            }}],
            grid_fixed_monthly_sek=241.25,
            trade_invoice_actual_sek=None,
            trade_actual_status="invoice_required",
            site_id="site-fiskvik",
        )
        self.assertEqual(result["grid_variable_actual_sek"], 40.626)
        self.assertEqual(result["grid_fixed_monthly_sek"], 241.25)
        self.assertEqual(result["known_month_subtotal_sek"], 281.876)
        self.assertEqual(result["completeness"], "partial")
        self.assertFalse(result["full_total"]["available"])
        self.assertEqual(result["trade_actual_status"], "invoice_required")

    def test_canonical_forecast_summary_excludes_legacy_actual_and_raw_snapshot_fields(self):
        result = build_canonical_cost_result(
            month="2026-10",
            daily_breakdown=[],
            grid_fixed_monthly_sek=241.25,
            trade_invoice_actual_sek=None,
            trade_actual_status="invoice_required",
            site_id="site-fiskvik",
            monthly_forecast={
                "available": False,
                "quality": "unavailable",
                "actual_cost_to_date_sek": 241.25,
                "actual_import_to_date_kwh": 0,
                "actual_priced_import_to_date_kwh": 0,
                "timezone": "UTC",
                "snapshot": {"actual_cost_to_date_sek": 241.25},
                "forecast_method": "legacy_explicit_fallback_required",
            },
        )
        forecast = result["forecast"]
        self.assertFalse(forecast["available"])
        self.assertNotIn("timezone", forecast)
        self.assertNotIn("snapshot", forecast)
        self.assertFalse(any(key.startswith("actual_") for key in forecast))
