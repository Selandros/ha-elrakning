from custom_components.elrakning.elhandel.models import ProviderData
from custom_components.elrakning.elhandel.providers.greenely_adapter import provider_data_from_greenely_state


def test_complete_greenely_state_maps_to_provider_data():
    data = provider_data_from_greenely_state(
        {
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
    )

    assert isinstance(data, ProviderData)
    assert data.provider == "greenely"
    assert data.facility == {
        "id": "facility-a",
        "address": "Fiskvik 218",
        "name": "Fiskvik 218",
    }
    assert data.active_data == {
        "configured": True,
        "contracts": [{"id": "contract-a"}],
        "source_invoices": [{"invoice_date": "2026-08-01"}],
        "agreement_name": "Kvartsprisavtal",
        "latest_period": {},
        "summary_present": True,
        "processing": {"last_error": None},
        "last_update": "2026-08-23T10:00:00+00:00",
    }
    assert data.invoices == [{"invoice_date": "2026-08-01", "amount_due_sek": 12.0}]
    assert data.consumption == {
        "summary": {"month": "2026-08", "month_to_date_kwh": 10.0},
        "samples": [{"value": 1.2}],
    }
    assert data.tariff == {"variable_cost_ore_per_kwh_incl_vat": 21.25}
    assert data.error is None


def test_missing_facility_maps_to_none():
    data = provider_data_from_greenely_state({"provider": "greenely", "source": {}})

    assert data.facility is None


def test_empty_history_maps_to_empty_invoices_and_no_consumption():
    data = provider_data_from_greenely_state(
        {
            "provider": "greenely",
            "source": {"invoices": [], "consumption": {"samples": []}},
            "invoices": [],
        }
    )

    assert data.invoices == []
    assert data.consumption is None


def test_error_state_is_preserved_and_processing_error_is_structured():
    data = provider_data_from_greenely_state(
        {
            "provider": "greenely",
            "error": "processing_failed",
            "processing": {
                "last_error": "validation_failed",
                "last_error_stage": "validation",
                "last_error_at": "2026-08-23T10:00:00+00:00",
            },
            "consumption_error": {"error": "no_consumption"},
        }
    )

    assert data.error == {
        "state": "processing_failed",
        "processing": {
            "error": "validation_failed",
            "stage": "validation",
            "at": "2026-08-23T10:00:00+00:00",
        },
        "consumption": {"error": "no_consumption"},
    }


def test_missing_tariff_maps_to_none():
    data = provider_data_from_greenely_state({"provider": "greenely", "summary": None})

    assert data.tariff is None
