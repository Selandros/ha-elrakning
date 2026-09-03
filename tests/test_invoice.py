from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import unittest


_PATH = Path(__file__).parents[1] / "custom_components" / "elrakning" / "invoice.py"
_SPEC = spec_from_file_location("elrakning_invoice", _PATH)
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
build_today_variable_cost = _MODULE.build_today_variable_cost


class InvoiceTodayCostTests(unittest.TestCase):
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
