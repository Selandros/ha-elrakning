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


def test_normalize_user_profiles_keeps_all_web_grid_contracts_for_matching():
    payload = {
        "customerIdentifier": "customer-id",
        "privateContractAccounts": [{
            "deliveryContracts": [
                {"installation": {"installationIdentifier": "installation-a", "pointOfDeliveryNumber": "pod-a"},
                 "engagements": [{"engagementType": "ELECTRICITY_GRID", "engagementStatus": "ACTIVE"}]},
                {"installation": {"installationIdentifier": "installation-b", "pointOfDeliveryNumber": "pod-b"},
                 "engagements": [{"engagementType": "ELECTRICITY_GRID", "engagementStatus": "FUTURE"}]},
            ],
        }],
    }
    result = models.normalize_user_profiles(payload, "customer-id")
    assert [item["facility"]["point_of_delivery_number"] for item in result] == ["pod-a", "pod-b"]


def test_native_facility_identity_prefers_installation_then_pod():
    assert models.facility_identity({"installation_identifier": "installation-a", "point_of_delivery_number": "pod-a"}) == "installation:installation-a"
    assert models.facility_identity({"point_of_delivery_number": "pod-a"}) == "pod:pod-a"
    assert models.facility_identity({"address": {"street": "Street 1"}}) is None


def test_grouped_contracts_preserve_native_contract_identity():
    result = models.normalize_grouped_contracts([{
        "contractsByType": [{
            "type": "ELECTRICITY_CONS_GRID",
            "installationId": "installation-a",
            "premiseInformation": {"gridArea": "Grid", "priceArea": "SE2"},
            "contracts": [{"id": "contract-a", "status": "ACTIVE", "prices": {"entries": []}}],
        }],
    }], {"installation-a"})
    assert result[0]["contract_identity"] == "contract-a"


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


def test_normalize_grouped_contracts_reads_verified_contracts_by_type_shape():
    result = models.normalize_grouped_contracts([{
        "contractsByType": [{
            "type": "ELECTRICITY_CONS_GRID",
            "installationId": "installation-1",
            "premiseInformation": {"gridArea": "Elnätsområde Nord", "priceArea": "SE_2"},
            "contracts": [{
                "name": "16 A, upp till 8000 kWh/år. Elnätsområde Nord",
                "startDate": "2999-10-01",
                "endDate": None,
                "status": "FUTURE",
                "fuseSize": "16 A",
                "prices": {
                    "title": "Ditt pris",
                    "subtitle": "Samtliga priser är inklusive moms.",
                    "entries": [
                        {"name": "Abonnemangsavgift", "price": {"value": 226.25, "numberUnit": "KR", "divisorUnit": "MONTH"}},
                        {"name": "Elöverföringsavgift", "price": {"value": 97, "numberUnit": "ORE", "divisorUnit": "KWH"}},
                        {"name": "Energiskatt", "price": {"value": 45, "numberUnit": "ORE", "divisorUnit": "KWH"}},
                        {"name": "Beräknad årskostnad", "price": {"value": 6567, "numberUnit": "KR", "divisorUnit": "NONE"}},
                        {"name": "Extra rad", "price": {"value": 1, "numberUnit": "KR", "divisorUnit": "NONE"}},
                    ],
                },
            }],
        }],
    }], {"installation-1"})
    contract = result[0]
    assert contract["agreement"]["status"] == "future"
    assert contract["agreement"]["source_status"] == "FUTURE"
    assert contract["agreement"]["type"] == "ELECTRICITY_CONS_GRID"
    assert contract["facility"] == {"fuse_ampere": 16.0, "price_area": "SE 2", "grid_area": "Elnätsområde Nord"}
    assert contract["tariff"]["subscription_fee_sek_per_month"] == 226.25
    assert contract["tariff"]["transfer_fee_ore_per_kwh"] == 97.0
    assert contract["tariff"]["energy_tax_ore_per_kwh"] == 45.0
    assert contract["tariff"]["estimated_yearly_cost_sek"] == 6567.0
    assert contract["tariff"]["grid_price"] == {
        "vat_included": True,
        "price_basis": "gross",
        "source": "grouped_contracts",
        "source_subtitle": "Samtliga priser är inklusive moms.",
        "fixed_monthly_sek": 226.25,
        "transfer_ore_per_kwh_gross": 97.0,
        "energy_tax_ore_per_kwh_gross": 45.0,
        "variable_total_ore_per_kwh_gross": 142.0,
        "yearly_estimated_sek": 6567.0,
        "contract_source_status": "FUTURE",
        "preview_applied": True,
    }
    assert len(contract["tariff"]["entries"]) == 5


def test_future_tariff_can_be_selected_for_pricing_without_changing_status():
    tariff = {"grid_price": {"variable_total_ore_per_kwh_gross": 142}}
    assert models.pricing_tariff_for_agreement(tariff, "future") == tariff


def test_normalize_grouped_contracts_ignores_other_types_and_installations():
    payload = [{"contractsByType": [
        {"type": "ELECTRICITY_SUPPLY", "installationId": "installation-1", "contracts": [{}]},
        {"type": "ELECTRICITY_CONS_GRID", "installationId": "other", "contracts": [{}]},
    ]}]
    assert models.normalize_grouped_contracts(payload, {"installation-1"}) == []


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
        "price_area": "SE 2",
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


def test_hourly_transfer_keeps_actual_points_and_excludes_padded_points():
    payload = {
        "productType": "ELECTRICITY",
        "aggregation": "HOUR",
        "from": "2026-10-01T00:00:00.000+02:00",
        "to": "2026-10-01T23:59:59.999+02:00",
        "transfer": [
            {"timestamp": "2026-10-01T18:00:00.000+02:00", "hasHigherResolutionData": True,
             "consumption": {"total": 2.105, "padded": False, "hasHigherResolutionData": True}},
            {"timestamp": "2026-10-01T19:00:00.000+02:00", "hasHigherResolutionData": False,
             "consumption": {"total": 0, "padded": True, "hasHigherResolutionData": False}},
        ],
    }
    result = models.parse_transfer_points(payload, "HOUR", date(2026, 10, 1))
    assert result["status"] == "ok"
    assert result["actual_count"] == 1
    assert result["padded_count"] == 1
    assert result["actual_total_kwh"] == 2.105
    assert result["actual_points"][0]["timestamp"].endswith("+02:00")


def test_quarter_hour_transfer_sums_verified_hour_and_excludes_future_padded_points():
    quarter_values = [0.734, 0.450, 0.491, 0.430]
    transfer = [
        {
            "timestamp": f"2026-10-01T18:{minute:02d}:00.000+02:00",
            "consumption": {"total": value, "padded": False},
        }
        for minute, value in zip((0, 15, 30, 45), quarter_values)
    ]
    transfer.extend(
        {
            "timestamp": f"2026-10-01T{hour:02d}:{minute:02d}:00.000+02:00",
            "consumption": {"total": 0, "padded": True},
        }
        for hour in range(19, 20)
        for minute in (0, 15, 30, 45)
    )
    result = models.parse_transfer_points(
        {"productType": "ELECTRICITY", "aggregation": "QUARTER_HOUR", "transfer": transfer},
        "QUARTER_HOUR",
        date(2026, 10, 1),
    )
    assert result["resolution"] == "QUARTER_HOUR"
    assert result["actual_count"] == 4
    assert result["padded_count"] == 4
    assert result["actual_total_kwh"] == 2.105
    assert sum(quarter_values) == 2.105
    assert result["padded_excluded"] is True


def test_quarter_hour_points_are_not_accepted_as_hourly_data():
    payload = {"productType": "ELECTRICITY", "aggregation": "QUARTER_HOUR", "transfer": []}
    assert models.parse_transfer_points(payload, "HOUR", date(2026, 10, 1))["status"] == "unsupported"


def test_day_transfer_excludes_padded_points():
    payload = {
        "productType": "ELECTRICITY",
        "aggregation": "DAY",
        "transfer": [
            {"timestamp": "2026-10-01T00:00:00.000+02:00", "consumption": {"total": 6.926, "padded": False}},
            {"timestamp": "2026-10-02T00:00:00.000+02:00", "consumption": {"total": 0, "padded": True}},
        ],
    }
    result = models.parse_transfer_points(payload, "DAY", date(2026, 10, 1))
    assert result["status"] == "ok"
    assert result["actual_count"] == 1
    assert result["padded_count"] == 0
    assert result["actual_total_kwh"] == 6.926


def test_provider_trend_is_separate_and_never_actual_or_forecast_input():
    result = models.parse_provider_trend(
        [{"productType": "ELECTRICITY", "consumption": {
            "value": 6.926,
            "text": "Trend",
            "timestamp": "2026-10-01T00:00:00.000+02:00",
            "comparePercentage": None,
        }, "dialogCopy": None}],
        "2026-10-01T22:00:00+00:00",
        "2026-10-01T22:00:00+00:00",
        "installation-1",
        {"method": "GET", "path": "/energy/trend"},
    )
    assert result["status"] == "ok"
    assert result["value"] == 6.926
    assert result["provenance"]["installation_identifier"] == "installation-1"
    assert result["provenance"]["request"]["path"] == "/energy/trend"
    assert result["usable_as_actual"] is False
    assert result["usable_as_forecast_input"] is False


def test_transfer_points_reject_wrong_aggregation_and_future_date():
    payload = {"productType": "ELECTRICITY", "aggregation": "HOUR", "transfer": []}
    assert models.parse_transfer_points(payload, "DAY", date(2026, 10, 1))["status"] == "unsupported"
    assert models.parse_transfer_points(payload, "HOUR", date(2026, 10, 1))["reason"] == "date_missing"


def test_hourly_transfer_matches_verified_october_first_total():
    values = [0, 0, 0, 0.127, 0.129, 0.012, 0.139, 0.156, 0.173, 0.133, 0, 0.104, 0, 0, 0, 0, 0.909, 2.939, 2.105]
    transfer = [
        {
            "timestamp": f"2026-10-01T{hour:02d}:00:00.000+02:00",
            "hasHigherResolutionData": True,
            "consumption": {"total": value, "padded": False, "hasHigherResolutionData": True},
        }
        for hour, value in enumerate(values)
    ]
    transfer.extend(
        {
            "timestamp": f"2026-10-01T{hour:02d}:00:00.000+02:00",
            "hasHigherResolutionData": False,
            "consumption": {"total": 0, "padded": True, "hasHigherResolutionData": False},
        }
        for hour in range(19, 24)
    )
    result = models.parse_transfer_points(
        {"productType": "ELECTRICITY", "aggregation": "HOUR", "transfer": transfer},
        "HOUR",
        date(2026, 10, 1),
    )
    assert result["actual_count"] == 19
    assert result["padded_count"] == 5
    assert result["actual_total_kwh"] == 6.926


def test_normalize_outage_treats_no_info_as_no_known_outage():
    assert models.normalize_outage({"outageType": "NO_INFO", "affected": 0}) == {
        "status": "no_known_outage", "outages": []
    }
    result = models.normalize_outage({"outageType": "UNVERIFIED", "affected": 1, "messageShort": "Status"})
    assert result["status"] == "outage"
    assert result["outages"][0]["message"] == "Status"
