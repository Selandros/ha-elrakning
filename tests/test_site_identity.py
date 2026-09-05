import types
import unittest

from tests._elrakning_test_bootstrap import install_elrakning_package_stub, install_homeassistant_stubs


install_homeassistant_stubs()
install_elrakning_package_stub()
from custom_components.elrakning.site_identity import (  # noqa: E402
    SiteIdentityManager,
    classify_source,
    resolve_source_identity,
)


class _Bus:
    def async_listen(self, *_args):
        return lambda: None


class _Entity:
    def __init__(self, registry_id, unique_id, config_entry_id="entry", device_id="device", platform="test"):
        self.id = registry_id
        self.unique_id = unique_id
        self.config_entry_id = config_entry_id
        self.device_id = device_id
        self.platform = platform


class _Registry:
    def __init__(self, entries):
        self.entries = entries

    def async_get(self, entity_id):
        return self.entries.get(entity_id)


class _Store:
    def __init__(self, data=None):
        self.data = data

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data


def _hass(entries):
    hass = types.SimpleNamespace(
        config=types.SimpleNamespace(latitude=59.3, longitude=18.1),
        bus=_Bus(),
    )
    import homeassistant.helpers.entity_registry as entity_registry

    entity_registry.async_get = lambda _hass: _Registry(entries)
    return hass


def _managers(mapping, meter_mapping=None):
    class _Manager:
        def __init__(self, value):
            self.mapping = dict(value)

        async def async_restore_mapping(self, value):
            self.mapping = dict(value or {})

    return _Manager(mapping), _Manager(meter_mapping or {})


class SiteIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_migration_creates_persistent_site_and_unattributed_boundaries(self):
        entries = {"sensor.load": _Entity("registry-load", "load")}
        hass = _hass(entries)
        power, meter = _managers({"consumption_entity": "sensor.load"})
        manager = SiteIdentityManager(hass, power, meter)
        manager.store = _Store()

        await manager.async_load()
        await manager.async_sync_from_current()
        first_site_id = manager.state["site"]["site_id"]
        generations = manager.public_state()["logical_roles"]

        self.assertTrue(first_site_id)
        self.assertEqual(len(generations), 1)
        self.assertIsNone(generations[0]["effective_from"])
        self.assertEqual(generations[0]["provenance"]["migration_origin"], "existing_configuration")
        self.assertEqual(generations[0]["provenance"]["effective_from_status"], "unknown_unattributed")

        restarted = SiteIdentityManager(hass, power, meter)
        restarted.store = _Store(manager.store.data)
        await restarted.async_load()
        self.assertEqual(restarted.state["site"]["site_id"], first_site_id)

    async def test_existing_site_migration_persists_collection_enabled(self):
        hass = _hass({})
        power, meter = _managers({})
        data = {
            "site": {"site_id": "site-a", "name": "A", "current": True},
            "sites": [{"site_id": "site-a", "name": "A", "current": True}],
            "active_site_id": "site-a",
            "site_configs": {"site-a": {"power": {}, "meter": {}, "bindings": {}}},
            "ledger": [],
        }
        manager = SiteIdentityManager(hass, power, meter)
        manager.store = _Store(data)
        await manager.async_load()
        self.assertTrue(manager.state["site_configs"]["site-a"]["collection_enabled"])
        self.assertTrue(manager.store.data["site_configs"]["site-a"]["collection_enabled"])

    async def test_initial_migration_covers_power_meter_and_solar_roles(self):
        entries = {
            entity: _Entity(f"registry-{entity}", entity)
            for entity in ("sensor.load", "sensor.solar", "sensor.solar_2", "sensor.import", "sensor.soc")
        }
        hass = _hass(entries)
        power, meter = _managers(
            {"consumption_entity": "sensor.load", "solar_entities": ["sensor.solar", "sensor.solar_2"], "soc_entity": "sensor.soc"},
            {"power_entity": "sensor.import"},
        )
        manager = SiteIdentityManager(hass, power, meter)
        manager.store = _Store()
        await manager.async_load()
        await manager.async_sync_from_current()
        self.assertEqual(
            {item["logical_role"] for item in manager.public_state()["logical_roles"]},
            {"house.consumption", "solar.production", "battery.soc", "grid.power/import"},
        )
        self.assertEqual(
            len([item for item in manager.public_state()["logical_roles"] if item["logical_role"] == "solar.production"]),
            2,
        )

    async def test_rename_same_registry_identity_does_not_create_generation(self):
        entries = {
            "sensor.old_load": _Entity("registry-load", "load"),
            "sensor.new_load": _Entity("registry-load", "load"),
        }
        hass = _hass(entries)
        power, meter = _managers({"consumption_entity": "sensor.old_load"})
        manager = SiteIdentityManager(hass, power, meter)
        manager.store = _Store()
        await manager.async_load()
        await manager.async_sync_from_current()
        power.mapping["consumption_entity"] = "sensor.new_load"
        await manager.async_sync_from_current()
        ledger = manager.state["ledger"]
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["entity_id"], "sensor.new_load")
        self.assertEqual(ledger[0]["source_identity"]["identity_key"], resolve_source_identity(hass, "sensor.old_load")["identity_key"])
        self.assertEqual(len(ledger[0]["address_history"]), 1)

    async def test_replacement_closes_old_generation_and_starts_new_one(self):
        entries = {
            "sensor.old_load": _Entity("registry-old", "load-old"),
            "sensor.new_load": _Entity("registry-new", "load-new"),
        }
        hass = _hass(entries)
        power, meter = _managers({"consumption_entity": "sensor.old_load"})
        manager = SiteIdentityManager(hass, power, meter)
        manager.store = _Store()
        await manager.async_load()
        await manager.async_sync_from_current()
        power.mapping["consumption_entity"] = "sensor.new_load"
        await manager.async_sync_from_current()
        ledger = manager.state["ledger"]
        self.assertEqual(len(ledger), 2)
        self.assertIsNotNone(ledger[0]["effective_to"])
        self.assertIsNone(ledger[1]["effective_to"])
        self.assertEqual(ledger[1]["provenance"]["effective_from_status"], "verified_mapping_change")

    async def test_remove_keeps_history_and_readd_keeps_stable_identity(self):
        entries = {"sensor.load": _Entity("registry-load", "load")}
        hass = _hass(entries)
        power, meter = _managers({"consumption_entity": "sensor.load"})
        manager = SiteIdentityManager(hass, power, meter)
        manager.store = _Store()
        await manager.async_load()
        await manager.async_sync_from_current()
        power.mapping["consumption_entity"] = None
        await manager.async_sync_from_current()
        self.assertEqual(len(manager.state["ledger"]), 1)
        self.assertIsNotNone(manager.state["ledger"][0]["effective_to"])
        power.mapping["consumption_entity"] = "sensor.load"
        await manager.async_sync_from_current()
        self.assertEqual(len(manager.state["ledger"]), 2)
        self.assertEqual(
            manager.state["ledger"][0]["source_identity"]["identity_key"],
            manager.state["ledger"][1]["source_identity"]["identity_key"],
        )

    async def test_new_site_has_empty_site_scoped_mapping_and_preserves_site_a(self):
        hass = _hass({"sensor.load": _Entity("registry-load", "load")})
        power, meter = _managers({"consumption_entity": "sensor.load"}, {"power_entity": "sensor.import"})
        manager = SiteIdentityManager(hass, power, meter)
        manager.store = _Store()
        await manager.async_load()
        await manager.async_sync_from_current()
        site_a = manager.state["active_site_id"]
        await manager.async_create_site("Adress B")
        site_b = manager.state["sites"][-1]["site_id"]
        self.assertEqual(manager.state["site_configs"][site_a]["power"]["consumption_entity"], "sensor.load")
        self.assertEqual(
            manager.state["site_configs"][site_b],
            {"power": {}, "meter": {}, "bindings": {}, "collection_enabled": False},
        )
        await manager.async_activate_site(site_b)
        self.assertEqual(manager.public_state()["site_id"], site_b)
        self.assertEqual(manager.public_state()["logical_roles"], [])
        self.assertEqual(manager.state["site_configs"][site_a]["meter"]["power_entity"], "sensor.import")
        power.mapping["consumption_entity"] = "sensor.load_b"
        await manager.async_sync_from_current()
        await manager.async_activate_site(site_a)
        self.assertEqual(power.mapping["consumption_entity"], "sensor.load")
        self.assertEqual(meter.mapping["power_entity"], "sensor.import")
        await manager.async_activate_site(site_b)
        self.assertEqual(power.mapping["consumption_entity"], "sensor.load_b")
        self.assertEqual(meter.mapping, {})

    def test_identity_classification_does_not_guess_without_stable_identity(self):
        old = {"source_identity": {"identity_key": None}}
        self.assertEqual(classify_source(old, {"identity_key": None}), "IDENTITY_UNCERTAIN")
        self.assertEqual(classify_source(old, {"identity_key": "different"}), "IDENTITY_UNCERTAIN")
