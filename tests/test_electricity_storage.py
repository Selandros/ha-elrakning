from tests._elrakning_test_bootstrap import install_elrakning_package_stub, install_homeassistant_stubs

install_elrakning_package_stub()
install_homeassistant_stubs()

from custom_components.elrakning.elhandel.storage import (
    ELECTRICITY_STORAGE_VERSION,
    empty_electricity_store,
    history_metadata,
    record_from_state,
    state_from_record,
    migrate_electricity_store,
)


def _store_with(*records):
    store = empty_electricity_store()
    for facility_id, provider, record in records:
        store["facilities"].setdefault(facility_id, {"providers": {}})["providers"][provider] = record
    return store


def test_empty_store_is_current_canonical_shape():
    assert empty_electricity_store() == {
        "version": ELECTRICITY_STORAGE_VERSION,
        "facilities": {},
        "active_facility_id": None,
        "active_provider": None,
    }


def test_two_facilities_keep_same_provider_history_separate():
    record_a = {"active": {}, "history": {"invoices": [{"id": "a"}], "consumption": {"samples": []}}}
    record_b = {"active": {}, "history": {"invoices": [{"id": "b"}], "consumption": {"samples": []}}}
    store = _store_with(("facility-a", "greenely", record_a), ("facility-b", "greenely", record_b))

    assert store["facilities"]["facility-a"]["providers"]["greenely"]["history"]["invoices"] == [{"id": "a"}]
    assert store["facilities"]["facility-b"]["providers"]["greenely"]["history"]["invoices"] == [{"id": "b"}]


def test_one_facility_can_keep_provider_histories_separate():
    greenely = {"active": {}, "history": {"invoices": [{"id": "g"}], "consumption": {"samples": []}}}
    tibber = {"active": {}, "history": {"invoices": [{"id": "t"}], "consumption": {"samples": []}}}
    store = _store_with(("facility-a", "greenely", greenely), ("facility-a", "tibber", tibber))

    providers = store["facilities"]["facility-a"]["providers"]
    assert providers["greenely"]["history"]["invoices"] == [{"id": "g"}]
    assert providers["tibber"]["history"]["invoices"] == [{"id": "t"}]


def test_record_round_trip_keeps_history_separate_from_active_state():
    state = {
        "configured": True,
        "provider": "greenely",
        "facility_id": "facility-a",
        "summary": {"tariff": {"variable_cost": 17}},
        "invoices": [{"invoice_date": "2026-08-01"}],
        "source": {"facility": {"id": "facility-a"}, "consumption": {"samples": [{"value": 1}]}},
    }

    record = record_from_state(state)
    restored = state_from_record(record)

    assert record["active"]["source"]["consumption"]["samples"] == []
    assert record["history"]["invoices"] == state["invoices"]
    assert record["history"]["consumption"]["samples"] == [{"value": 1}]
    assert restored == state


def test_history_metadata_is_scoped_and_contains_only_counts():
    store = _store_with(
        ("facility-a", "greenely", {"active": {}, "history": {"invoices": [{"id": "a"}], "consumption": {"samples": [{"id": "a-1"}, {"id": "a-2"}]}}}),
        ("facility-b", "greenely", {"active": {}, "history": {"invoices": [{"id": "b"}, {"id": "b-2"}], "consumption": {"samples": []}}}),
    )

    assert history_metadata(store) == [
        {"facility_id": "facility-a", "provider": "greenely", "invoice_count": 1, "consumption_sample_count": 2},
        {"facility_id": "facility-b", "provider": "greenely", "invoice_count": 2, "consumption_sample_count": 0},
    ]
    assert "id" not in history_metadata(store)[0]


def test_empty_history_is_not_reported():
    store = _store_with(("facility-a", "greenely", {"active": {}, "history": {"invoices": [], "consumption": {"samples": []}}}))
    assert history_metadata(store) == []


def test_greenely_store_migration_sanitizes_active_and_history_idempotently():
    legacy = empty_electricity_store()
    legacy["facilities"] = {
        "facility-a": {
            "providers": {
                "greenely": {
                    "active": {
                        "provider": "greenely",
                        "facility_id": "facility-a",
                        "source": {
                            "facility": {
                                "id": "facility-a",
                                "email": "hidden",
                                "meter_id": "meter-hidden",
                            },
                            "contracts": [{"_contract_id": "contract-a", "customer_id": "hidden", "status": "OPERATIONAL"}],
                            "consumption": {"samples": [{"localtime": "2026-08-01T00:00:00", "usage_kwh": 1.2, "email": "hidden"}]},
                        },
                        "summary": {"tariff": {"variable_cost": 17}, "customer_id": "hidden"},
                    },
                    "history": {
                        "invoices": [{"invoice_date": "2026-08-01", "amount_due_sek": 12.0, "_contract_id": "contract-a", "_invoice_key": "invoice-a", "meter_id": "hidden"}],
                        "consumption": {"samples": [{"localtime": "2026-08-01T00:00:00", "usage_wh": 1200, "usage_kwh": 1.2, "email": "hidden"}]},
                    },
                },
                "other_provider": {"active": {"source": {"email": "keep"}}, "history": {"invoices": [{"id": "keep"}], "consumption": {"samples": [{"email": "keep"}]}}},
            }
        }
    }
    original_other = deepcopy(legacy["facilities"]["facility-a"]["providers"]["other_provider"])

    migrated = migrate_electricity_store(legacy)
    record = migrated["facilities"]["facility-a"]["providers"]["greenely"]
    assert record["active"]["facility_id"] == "facility-a"
    assert record["active"]["source"]["facility"]["id"] == "facility-a"
    assert record["active"]["source"]["contracts"] == [{"_contract_id": "contract-a", "status": "OPERATIONAL"}]
    assert record["active"]["summary"] == {"tariff": {"variable_cost": 17}}
    assert record["history"]["invoices"] == [{"invoice_date": "2026-08-01", "amount_due_sek": 12.0, "_contract_id": "contract-a", "_invoice_key": "invoice-a"}]
    assert record["history"]["consumption"]["samples"] == [{"localtime": "2026-08-01T00:00:00", "usage_wh": 1200, "usage_kwh": 1.2}]
    assert migrated["facilities"]["facility-a"]["providers"]["other_provider"] == original_other
    assert migrate_electricity_store(migrated) == migrated


def test_storage_manager_load_persists_greenely_migration_only():
    class _Store:
        def __init__(self, data):
            self.data = data

        async def async_load(self):
            return deepcopy(self.data)

        async def async_save(self, data):
            self.data = deepcopy(data)

    store = empty_electricity_store()
    store["facilities"] = {"facility-a": {"providers": {"greenely": {"active": {"source": {"email": "hidden"}}, "history": {"invoices": [], "consumption": {"samples": []}}}}}}
    manager = __import__("custom_components.elrakning.elhandel.storage", fromlist=["StorageManager"]).StorageManager.__new__(
        __import__("custom_components.elrakning.elhandel.storage", fromlist=["StorageManager"]).StorageManager
    )
    manager.store = _Store(store)
    asyncio.run(manager.async_load(facility_id="facility-a", provider="greenely", use_active_namespace=False))
    assert "email" not in manager.store.data["facilities"]["facility-a"]["providers"]["greenely"]["active"]["source"]
import asyncio
from copy import deepcopy
