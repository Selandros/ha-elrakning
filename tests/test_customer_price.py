"""Tests for generic customer-price calculation."""

from dataclasses import dataclass
from datetime import datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types
import unittest


@dataclass(frozen=True)
class _SpotPeriod:
    start: datetime
    end: datetime
    price: float


_MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "elrakning" / "customer_price.py"
_PACKAGE_ROOT = _MODULE_PATH.parent
for _name, _path in (
    ("custom_components", _PACKAGE_ROOT.parent),
    ("custom_components.elrakning", _PACKAGE_ROOT),
    ("custom_components.elrakning.elhandel", _PACKAGE_ROOT / "elhandel"),
    ("custom_components.elrakning.elhandel.providers", _PACKAGE_ROOT / "elhandel" / "providers"),
):
    if _name not in sys.modules:
        _package = types.ModuleType(_name)
        _package.__path__ = [str(_path)]
        sys.modules[_name] = _package
_SPEC = spec_from_file_location("custom_components.elrakning.customer_price", _MODULE_PATH)
_MODULE = module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
from custom_components.elrakning.elhandel.models import serialize_provider_state
from custom_components.elrakning.elhandel.providers.greenely_adapter import provider_data_from_greenely_state

build_customer_price_data = _MODULE.build_customer_price_data
grid_variable_cost_ex_vat = _MODULE.grid_variable_cost_ex_vat
grid_price_is_current = _MODULE.grid_price_is_current
ProviderData = _MODULE.ProviderData


def _periods() -> tuple[_SpotPeriod, ...]:
    return (
        _SpotPeriod(
            datetime.fromisoformat("2026-08-23T12:00:00+02:00"),
            datetime.fromisoformat("2026-08-23T12:15:00+02:00"),
            0.2993,
        ),
    )


class CustomerPriceTests(unittest.TestCase):
    def test_customer_price_uses_valid_generic_variable_cost(self) -> None:
        data = build_customer_price_data(
            _periods(),
            {
                "configured": True,
                "provider": "greenely",
                "summary": {
                    "tariff": {"variable_cost_ore_per_kwh_incl_vat": 21.25},
                    "_source_kind": "invoice",
                    "_facility_id": "facility-a",
                    "_contract_id": "contract-a",
                    "_invoice_key": "invoice-a",
                },
                "facility_id": "facility-a",
                "invoices": [{"_contract_id": "contract-a", "_invoice_key": "invoice-a"}],
                "source": {"contracts": [{"_contract_id": "contract-a", "status": "OPERATIONAL"}]},
            },
        )

        self.assertEqual(data.mode, "customer_price")
        self.assertEqual(data.provider, "greenely")
        self.assertAlmostEqual(data.electricity_cost_ex_vat, 0.17)
        self.assertEqual(data.periods[0].spot_price_ex_vat, 0.2993)
        self.assertAlmostEqual(data.periods[0].electricity_cost_ex_vat, 0.17)
        self.assertEqual(data.periods[0].subtotal_ex_vat, 0.4693)
        self.assertAlmostEqual(data.periods[0].vat, 0.117325)
        self.assertAlmostEqual(data.periods[0].customer_price, 0.586625)

    def test_missing_variable_cost_keeps_vat_inclusive_spot_price(self) -> None:
        data = build_customer_price_data(_periods(), {"configured": True, "summary": None})

        self.assertEqual(data.mode, "spot_price")
        self.assertIsNone(data.electricity_cost_ex_vat)
        self.assertEqual(data.periods[0].spot_price_ex_vat, 0.2993)
        self.assertAlmostEqual(data.periods[0].customer_price, 0.374125)

    def test_future_or_unattributed_provider_data_cannot_adjust_current_price(self) -> None:
        data = build_customer_price_data(
            _periods(),
            {
                "configured": True,
                "provider": "greenely",
                "summary": {
                    "tariff": {"variable_cost_ore_per_kwh_incl_vat": 21.25},
                },
            },
        )
        self.assertEqual(data.mode, "spot_price")
        self.assertIsNone(data.electricity_cost_ex_vat)

    def test_provider_data_produces_the_same_result_as_current_public_state(self) -> None:
        provider_state = {
            "configured": True,
            "provider": "greenely",
            "summary": {
                "tariff": {"variable_cost_ore_per_kwh_incl_vat": 21.25},
                "_source_kind": "invoice",
                "_facility_id": "facility-a",
                "_contract_id": "contract-a",
                "_invoice_key": "invoice-a",
            },
            "facility_id": "facility-a",
            "invoices": [{"_contract_id": "contract-a", "_invoice_key": "invoice-a"}],
            "source": {"contracts": [{"_contract_id": "contract-a", "status": "OPERATIONAL"}]},
        }
        provider_data = ProviderData(
            provider="greenely",
            active_data={"configured": True, "customer_price_eligible": True},
            tariff={"variable_cost_ore_per_kwh_incl_vat": 21.25},
        )

        provider_result_from_state = build_customer_price_data(_periods(), provider_state)
        provider_result = build_customer_price_data(_periods(), provider_data)

        self.assertEqual(provider_result, provider_result_from_state)

    def test_backend_price_path_keeps_internal_attribution_out_of_public_state(self) -> None:
        state = {
            "configured": True,
            "provider": "greenely",
            "facility_id": "facility-a",
            "source": {
                "contracts": [{"_contract_id": "contract-a", "status": "OPERATIONAL"}],
            },
            "invoices": [{"_contract_id": "contract-a", "_invoice_key": "invoice-a"}],
            "summary": {
                "tariff": {"variable_cost_ore_per_kwh_incl_vat": 21.25},
                "_source_kind": "invoice",
                "_facility_id": "facility-a",
                "_contract_id": "contract-a",
                "_invoice_key": "invoice-a",
            },
        }
        internal = provider_data_from_greenely_state(state)
        public = serialize_provider_state(internal)

        internal_result = build_customer_price_data(_periods(), internal)
        public_result = build_customer_price_data(_periods(), public)

        self.assertTrue(internal.active_data["customer_price_eligible"])
        self.assertAlmostEqual(internal_result.electricity_cost_ex_vat, 0.17)
        self.assertEqual(public_result.mode, "spot_price")
        self.assertIsNone(public_result.electricity_cost_ex_vat)

    def test_provider_data_without_provider_tariff_keeps_spot_price(self) -> None:
        data = build_customer_price_data(
            _periods(),
            ProviderData(provider=None, active_data={"configured": False}),
        )

        self.assertEqual(data.mode, "spot_price")
        self.assertIsNone(data.provider)
        self.assertIsNone(data.electricity_cost_ex_vat)
        self.assertAlmostEqual(data.periods[0].customer_price, 0.374125)

    def test_greenely_contract_fee_is_not_an_actual_cost_without_invoice(self) -> None:
        state = {
            "configured": True,
            "provider": "greenely",
            "facility_id": "facility-a",
            "invoices": [],
            "summary": None,
            "source": {
                "contracts": [{"_contract_id": "contract-a", "price_group": {"name": "Monthly fee - 69 SEK/month", "fee_per_month": 69}, "promocode": "18månader"}],
            },
        }
        provider = provider_data_from_greenely_state(state)
        self.assertIsNone(provider.tariff)
        self.assertFalse(provider.active_data["customer_price_eligible"])
        self.assertEqual(build_customer_price_data(_periods(), provider).mode, "spot_price")

    def test_grid_rate_uses_gross_variable_components_only(self) -> None:
        self.assertAlmostEqual(grid_variable_cost_ex_vat({
            "vat_included": True,
            "variable_total_ore_per_kwh_gross": 142,
            "fixed_monthly_sek": 226.25,
            "yearly_estimated_sek": 6567,
        }), 1.136)
        self.assertIsNone(grid_variable_cost_ex_vat({
            "vat_included": False,
            "variable_total_ore_per_kwh_gross": 142,
        }))

    def test_future_grid_price_is_preview_only(self) -> None:
        self.assertFalse(grid_price_is_current({"contract_source_status": "FUTURE"}))
        self.assertTrue(grid_price_is_current({"contract_source_status": "ACTIVE"}))

    def test_provider_and_grid_contract_statuses_are_independent(self) -> None:
        current_provider = {
            "configured": True,
            "provider": "greenely",
            "facility_id": "facility-a",
            "summary": {
                "tariff": {"variable_cost_ore_per_kwh_incl_vat": 21.25},
                "_source_kind": "invoice",
                "_facility_id": "facility-a",
                "_contract_id": "provider-current",
                "_invoice_key": "invoice-a",
            },
            "invoices": [{"_contract_id": "provider-current", "_invoice_key": "invoice-a"}],
            "source": {"contracts": [{"_contract_id": "provider-current", "status": "OPERATIONAL"}]},
        }
        future_provider = {
            **current_provider,
            "summary": {**current_provider["summary"], "_contract_id": "provider-future"},
            "invoices": [{"_contract_id": "provider-future", "_invoice_key": "invoice-a"}],
            "source": {"contracts": [{"_contract_id": "provider-future", "status": "FUTURE", "start_date": "4102444800"}]},
        }
        future_grid = {"contract_source_status": "FUTURE"}
        current_grid = {
            "contract_source_status": "ACTIVE",
            "vat_included": True,
            "variable_total_ore_per_kwh_gross": 142,
        }

        self.assertAlmostEqual(
            build_customer_price_data(_periods(), current_provider).electricity_cost_ex_vat,
            0.17,
        )
        self.assertIsNone(grid_variable_cost_ex_vat(future_grid))
        self.assertEqual(build_customer_price_data(_periods(), future_provider).mode, "spot_price")
        self.assertAlmostEqual(grid_variable_cost_ex_vat(current_grid), 1.136)
