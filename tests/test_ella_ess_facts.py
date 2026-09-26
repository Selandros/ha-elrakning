"""Tests for the generic auditable ESS-facts store contract."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ella_ess_facts", ROOT / "custom_components/elrakning/ella_ess_facts.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeStore:
    def __init__(self):
        self.saved = []

    async def async_save(self, value):
        self.saved.append(value)

    async def async_load(self):
        return None


def _fact(site="site-a", resource="ess-a", key="capacity_kwh", value=25.0, source="manufacturer_rated_specification"):
    return {
        "site_id": site,
        "resource_id": resource,
        "key": key,
        "value": value,
        "unit": "kWh" if key == "capacity_kwh" else "%",
        "source_type": source,
        "verified_at": "2026-09-26T10:00:00+00:00",
        "evidence_note": "verified external evidence",
    }


def _store():
    store = MODULE.EllaEssFactsStore(object())
    store.store = FakeStore()
    return store


def test_import_is_idempotent_and_site_resource_scoped():
    store = _store()
    import asyncio
    asyncio.run(store.async_upsert([_fact()]))
    asyncio.run(store.async_upsert([_fact()]))
    assert len(store.list_site("site-a")) == 1
    assert store.list_site("site-b") == []
    assert store.store.saved[-1]["sites"]["site-a"]["facts"][0]["value"] == 25.0


def test_higher_priority_runtime_fact_wins_without_cross_site_leakage():
    store = _store()
    import asyncio
    asyncio.run(store.async_upsert([
        _fact(value=25.0),
        _fact(value=24.0, source="runtime_device_config"),
        _fact(site="site-b", value=99.0),
    ]))
    assert store.resolve("site-a", "ess-a")["capacity_kwh"]["value"] == 24.0
    assert store.resolve("site-b", "ess-a")["capacity_kwh"]["value"] == 99.0


def test_optimizer_overlay_only_fills_missing_exact_resource_facts():
    store = _store()
    import asyncio
    asyncio.run(store.async_upsert([
        _fact(key="capacity_kwh", value=25.0),
        _fact(key="reserve_soc_fraction", value=0.05),
        _fact(key="max_charge_kw", value=10.0, source="manufacturer_rated_specification"),
        _fact(key="max_discharge_kw", value=10.0, source="manufacturer_rated_specification"),
    ]))
    result = store.apply_to_optimizer_inputs({
        "site_id": "site-a",
        "ess": {"resource_identity": {
            "available": True,
            "site_id": "site-a",
            "resource_id": "ess-a",
            "method": "strong_registry_config_entry_and_device_identity",
        }},
    })
    assert result["ess"]["capacity_kwh"] == 25.0
    assert result["ess"]["reserve_soc_fraction"] == 0.05
    assert result["ess"]["verified_fact_provenance"]["max_charge_kw"]["source_type"] == "manufacturer_rated_specification"


def test_invalid_fact_is_rejected():
    assert MODULE.normalize_fact({"site_id": "a", "resource_id": "b"}) is None


def test_planning_efficiency_overlay_remains_explicitly_non_physical():
    store = _store()
    import asyncio
    asyncio.run(store.async_upsert([
        _fact(key="planning_charge_efficiency", value=0.85, source="conservative_calibration_planning_assumption"),
        _fact(key="planning_discharge_efficiency", value=0.85, source="conservative_calibration_planning_assumption"),
    ]))
    result = store.apply_to_optimizer_inputs({
        "site_id": "site-a",
        "ess": {"resource_identity": {
            "available": True,
            "site_id": "site-a",
            "resource_id": "ess-a",
            "method": "strong_registry_config_entry_and_device_identity",
        }},
    })
    assert result["ess"]["planning_efficiency"]["source_type"] == "conservative_calibration_planning_assumption"
