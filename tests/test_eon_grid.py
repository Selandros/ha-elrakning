import importlib.util
from datetime import date
from pathlib import Path


_ROOT = Path(__file__).parents[1] / "custom_components" / "elrakning" / "elnat"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


models = _load("eon_models")


def test_normalize_user_profile_reads_grid_agreement_and_tariff_fields():
    result = models.normalize_user_profile({
        "customerIdentifier": "customer-id",
        "privateContractAccounts": [{
            "deliveryContracts": [{
                "installation": {
                    "installationIdentifier": "installation-id",
                    "pointOfDeliveryNumber": "pod-id",
                    "gridArea": {"priceArea": "SE2"},
                    "fuse": {"size": 16},
                },
                "engagements": [{
                    "engagementType": "ELECTRICITY_GRID",
                    "engagementStatus": "FUTURE",
                    "startDate": "2026-10-01",
                    "endDate": "Tillsvidare",
                    "description": "Elnät",
                    "prices": {
                        "transferFee": {"grossAmount": 97.0},
                        "energyTax": {"grossAmount": 45.0},
                        "subscriptionFee": {"grossAmount": 226.25},
                    },
                    "estimatedYearlyCost": {"costInclVAT": 1234.5},
                }],
            }],
        }],
        "smeContractAccounts": [],
    }, "customer-id")
    assert result["agreement"]["status"] == "future"
    assert result["facility"]["price_area"] == "SE2"
    assert result["facility"]["fuse_ampere"] == 16
    assert result["tariff"]["transfer_fee_ore_per_kwh"] == 97.0
    assert result["tariff"]["energy_tax_ore_per_kwh"] == 45.0
    assert result["tariff"]["subscription_fee_sek_per_month"] == 226.25


def test_monthly_parser_reads_energy_block_and_selected_month():
    payload = {
        "hasNoValues": False,
        "energyData": {
            "subType": "energy",
            "resolution": "Monthly",
            "lowestAvailableResolution": "Monthly",
            "2026": {"months": [None, 12.5, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]},
        },
    }
    result = models.parse_monthly_consumption(payload, 2026, 2)
    assert result == {"status": "ok", "resolution": "Monthly", "year": 2026, "month": 2, "consumption_kwh": 12.5}


def test_monthly_parser_keeps_missing_values_distinct_from_zero():
    assert models.parse_monthly_consumption({"hasNoValues": True}, 2026, 8)["reason"] == "no_values"
    result = models.parse_monthly_consumption({"energy": {"subType": "energy", "resolution": "Monthly", "2026": {"months": [None] * 12}}}, 2026, 8)
    assert result["status"] == "missing"
    assert result["reason"] == "month_missing"


def test_unknown_monthly_shape_is_unsupported():
    result = models.parse_monthly_consumption({"energy": {"subType": "energy", "resolution": "Daily"}}, 2026, 8)
    assert result == {"status": "unsupported", "resolution": "Monthly"}


def test_cost_uses_gross_ore_rates_and_monthly_fee():
    result = models.calculate_eon_cost(10, {
        "subscription_fee_sek_per_month": 226.25,
        "transfer_fee_ore_per_kwh": 97.0,
        "energy_tax_ore_per_kwh": 45.0,
    })
    assert result == {
        "subscription_fee_sek": 226.25,
        "transfer_cost_sek": 9.7,
        "energy_tax_sek": 4.5,
        "total_sek": 240.45,
    }


def test_future_status_does_not_depend_on_current_date():
    assert models.agreement_status("ACTIVE", "2999-01-01", "Tillsvidare") == "future"


def test_normalize_locations_selects_only_electricity_grid_installations():
    result = models.normalize_locations([{
        "installations": [
            {"id": "grid-1", "podId": "pod-1", "productType": "ELECTRICITY", "serviceType": "GRID",
             "priceArea": "SE_2", "production": False, "isFuture": True,
             "address": {"fullStreet": "Example 1", "city": "Town", "postalCode": "123 45"}},
            {"id": "other", "podId": "pod-2", "productType": "ELECTRICITY", "serviceType": "SUPPLY",
             "address": {"fullStreet": "Example 2", "city": "Town", "postalCode": "123 45"}},
        ],
    }])
    assert result == [{
        "installation_identifier": "grid-1",
        "point_of_delivery_number": "pod-1",
        "street": "Example 1",
        "city": "Town",
        "postal_code": "123 45",
        "price_area": "SE_2",
        "production": False,
        "is_future": True,
        "elna_service_status": None,
    }]


def test_monthly_transfer_uses_timestamp_and_rejects_padded_values():
    payload = {
        "productType": "ELECTRICITY",
        "aggregation": "MONTH",
        "transfer": [
            {"timestamp": "2026-08-01T00:00:00Z", "consumption": {"total": 12.5, "padded": False}},
            {"timestamp": "2026-09-01T00:00:00Z", "consumption": {"total": 0, "padded": True}},
        ],
        "total": {"consumption": {"total": 999, "padded": False}},
    }
    assert models.parse_monthly_transfer(payload, 2026, 8)["consumption_kwh"] == 12.5
    assert models.parse_monthly_transfer(payload, 2026, 9)["reason"] == "padded"


def test_normalize_outage_treats_no_info_as_no_known_outage():
    assert models.normalize_outage({"outageType": "NO_INFO", "affected": 0}) == {
        "status": "no_known_outage", "outages": []
    }
    result = models.normalize_outage({"outageType": "UNVERIFIED", "affected": 1, "messageShort": "Status"})
    assert result["status"] == "outage"
    assert result["outages"][0]["message"] == "Status"
