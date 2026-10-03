from dataclasses import fields

from custom_components.elrakning.elhandel.models import ProviderData


def test_provider_data_defines_only_the_provider_neutral_contract():
    assert [field.name for field in fields(ProviderData)] == [
        "provider",
        "facility",
        "active_data",
        "invoices",
        "consumption",
        "analysis",
        "tariff",
        "error",
    ]


def test_provider_data_has_empty_optional_sections_by_default():
    data = ProviderData()

    assert data.provider is None
    assert data.facility is None
    assert data.active_data == {}
    assert data.invoices == []
    assert data.consumption is None
    assert data.tariff is None
    assert data.error is None


def test_greenely_state_can_be_mapped_without_changing_the_contract():
    greenely_state = {
        "provider": "greenely",
        "configured": True,
        "facility_id": "facility-a",
        "facility_name": "Fiskvik 218",
        "source": {
            "facility": {"id": "facility-a", "address": "Fiskvik 218"},
            "contracts": [{"id": "contract-a"}],
            "invoices": [{"invoice_date": "2026-08-01"}],
            "consumption": {"samples": [{"value": 1.2}]},
        },
        "invoices": [{"invoice_date": "2026-08-01", "amount_due_sek": 12.0}],
        "summary": {
            "agreement_name": "Kvartsprisavtal",
            "tariff": {"variable_cost_ore_per_kwh_incl_vat": 21.25},
        },
        "last_update": "2026-08-23T10:00:00+00:00",
        "consumption": {"month": "2026-08", "month_to_date_kwh": 10.0},
        "processing": {"last_error": None},
        "error": None,
    }
    source = greenely_state["source"]

    data = ProviderData(
        provider=greenely_state["provider"],
        facility={
            "id": greenely_state["facility_id"],
            "name": greenely_state["facility_name"],
            "source": source["facility"],
        },
        active_data={
            "configured": greenely_state["configured"],
            "contracts": source["contracts"],
            "source_invoices": source["invoices"],
            "agreement_name": "Kvartsprisavtal",
            "latest_period": {},
            "summary_present": True,
            "processing": greenely_state["processing"],
            "last_update": "2026-08-23T10:00:00+00:00",
        },
        invoices=greenely_state["invoices"],
        consumption={
            "summary": greenely_state["consumption"],
            "samples": source["consumption"]["samples"],
        },
        tariff=greenely_state["summary"]["tariff"],
        error=greenely_state["error"],
    )

    assert data.provider == "greenely"
    assert data.facility == {
        "id": "facility-a",
        "name": "Fiskvik 218",
        "source": {"id": "facility-a", "address": "Fiskvik 218"},
    }
    assert data.active_data["contracts"] == [{"id": "contract-a"}]
    assert data.invoices == [{"invoice_date": "2026-08-01", "amount_due_sek": 12.0}]
    assert data.consumption == {
        "summary": {"month": "2026-08", "month_to_date_kwh": 10.0},
        "samples": [{"value": 1.2}],
    }
    assert data.tariff == {"variable_cost_ore_per_kwh_incl_vat": 21.25}
    assert data.error is None


def test_greenely_processing_and_errors_have_explicit_generic_destinations():
    data = ProviderData(
        provider="greenely",
        active_data={"processing": {"last_error_stage": "parse"}},
        error={"code": "invoice_parse_failed", "stage": "parse"},
    )

    assert data.active_data["processing"]["last_error_stage"] == "parse"
    assert data.error == {"code": "invoice_parse_failed", "stage": "parse"}
