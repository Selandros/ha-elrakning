import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from tests._elrakning_test_bootstrap import install_elrakning_package_stub, install_homeassistant_stubs


install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.ella_capabilities import build_capability_inventory  # noqa: E402
from custom_components.elrakning.ella_load_registry import EllaLoadRegistry, normalize_load  # noqa: E402


class _Store:
    def __init__(self):
        self.data = None

    async def async_load(self):
        return self.data

    async def async_save(self, value):
        self.data = value


def _registry():
    registry = EllaLoadRegistry.__new__(EllaLoadRegistry)
    registry.state = {"schema": "ella_load_registry.v1", "version": 1, "sites": {}}
    registry.store = _Store()
    registry.now_fn = lambda: "2026-09-20T12:00:00+00:00"
    return registry


def _manager():
    return SimpleNamespace(
        state={
            "active_site_id": "vik",
            "sites": [{"site_id": "vik", "name": "Vikarbodarna"}, {"site_id": "fisk", "name": "Fiskvik"}],
            "site_configs": {
                "vik": {"bindings": {"elhandel": {"provider": "eon"}, "grid": {"provider": "eon"}}},
                "fisk": {"bindings": {"elhandel": {"provider": "eon"}}},
            },
            "global_bindings": {"nord_pool": {"binding_fingerprint": "explicit"}},
            "ledger": [
                {"site_id": "vik", "logical_role": "house.consumption", "entity_id": "sensor.vik_load", "generation_id": "gen-vik", "resource_id": "res-vik", "effective_to": None},
                {"site_id": "vik", "logical_role": "solar.production", "entity_id": "sensor.vik_solar", "generation_id": "gen-solar", "resource_id": "res-solar", "effective_to": None},
                {"site_id": "fisk", "logical_role": "house.consumption", "entity_id": "sensor.fisk_load", "generation_id": "gen-fisk", "resource_id": "res-fisk", "effective_to": None},
            ],
        },
        global_binding=lambda service: {"binding_fingerprint": "explicit"} if service == "nord_pool" else None,
        ella_binding_for_site=lambda site_id: {"enabled": True} if site_id in {"vik", "fisk"} else None,
    )


class EllaStage1Tests(unittest.IsolatedAsyncioTestCase):
    async def test_load_crud_is_site_scoped_and_deterministic(self):
        registry = _registry()
        payload = {"load_id": "water_heater", "name": "Varmvatten", "measurement": "sensor.vik_water", "criticality": "normal", "flexibility": "shiftable", "control_mode": "recommend_only", "priority": 2}
        await registry.async_upsert("vik", payload)
        self.assertEqual([item["load_id"] for item in registry.list_for_site("vik")], ["water_heater"])
        self.assertEqual(registry.list_for_site("fisk"), [])
        self.assertFalse(await registry.async_remove("fisk", "water_heater"))
        self.assertTrue(await registry.async_remove("vik", "water_heater"))

    async def test_duplicate_upsert_is_update_not_second_load(self):
        registry = _registry()
        payload = {"load_id": "washer", "name": "Tvätt", "criticality": "low", "flexibility": "shiftable", "control_mode": "observe_only"}
        await registry.async_upsert("vik", payload)
        await registry.async_upsert("vik", {**payload, "name": "Tvättmaskin"})
        self.assertEqual(len(registry.list_for_site("vik")), 1)
        self.assertEqual(registry.list_for_site("vik")[0]["name"], "Tvättmaskin")

    def test_validation_rejects_malformed_entities_and_naive_dates(self):
        base = {"load_id": "heater", "name": "Heater"}
        with self.assertRaisesRegex(ValueError, "invalid_measurement"):
            normalize_load({**base, "measurement": "not-an-entity"}, "vik", now="2026-09-20T12:00:00+00:00")
        with self.assertRaisesRegex(ValueError, "invalid_deadline"):
            normalize_load({**base, "deadline": "2026-09-20T12:00:00"}, "vik", now="2026-09-20T12:00:00+00:00")

    def test_inventory_is_site_scoped_and_does_not_fabricate_missing_layers(self):
        registry = _registry()
        inventory = build_capability_inventory(_manager(), registry, "fisk", now=datetime(2026, 9, 20, tzinfo=timezone.utc))
        by_id = {item["capability_id"]: item for item in inventory["capabilities"]}
        self.assertEqual(inventory["site_id"], "fisk")
        self.assertTrue(by_id["load.house_total.actual"]["verified"])
        self.assertEqual(by_id["solar.actual"]["availability"], "unavailable")
        self.assertEqual(by_id["battery.soc"]["availability"], "unavailable")
        self.assertFalse(inventory["invariants"]["execution_eligible"])
        self.assertFalse(inventory["planner"]["solar_ess_used_by_current_plan"])

    def test_inventory_accepts_explicit_provider_binding_without_address_heuristic(self):
        inventory = build_capability_inventory(_manager(), _registry(), "fisk")
        by_id = {item["capability_id"]: item for item in inventory["capabilities"]}
        self.assertEqual(by_id["cost.electricity_retail"]["availability"], "available")
        self.assertEqual(by_id["cost.grid_tariff"]["availability"], "unavailable")


if __name__ == "__main__":
    unittest.main()
