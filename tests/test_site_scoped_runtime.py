import types
import unittest
from datetime import date

from tests._elrakning_test_bootstrap import install_elrakning_package_stub, install_homeassistant_stubs


install_homeassistant_stubs()
install_elrakning_package_stub()
from custom_components.elrakning.coordinator import ElrakningCoordinator  # noqa: E402
from custom_components.elrakning.site_identity import SiteIdentityManager  # noqa: E402


class _Entry:
    def __init__(self, entry_id, data):
        self.entry_id = entry_id
        self.data = data
        self.options = {}


class _Services:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def async_call(self, domain, service, data, **kwargs):
        self.calls.append((domain, service, data, kwargs))
        return self.response


class _Store:
    def __init__(self, data=None):
        self.data = data

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data


class _MappingManager:
    def __init__(self, mapping):
        self.mapping = dict(mapping)

    async def async_restore_mapping(self, mapping):
        self.mapping = dict(mapping or {})


class _ProviderManager:
    def __init__(self):
        self.entry = types.SimpleNamespace(entry_id="elhandel-entry")
        self.state = {"facility_id": "facility-a", "provider": "greenely"}
        self.applied = None

    async def async_apply_site_binding(self, binding):
        self.applied = binding


class _GridProvider:
    def __init__(self):
        self.state = {"facility": {"point_of_delivery_number": "pod-a"}}


class _GridManager:
    def __init__(self):
        self.entry = types.SimpleNamespace(entry_id="grid-entry")
        self.definition = types.SimpleNamespace(provider_id="eon")
        self.provider = _GridProvider()
        self.applied = None

    @property
    def configured(self):
        return True

    async def async_apply_site_binding(self, binding, state=None):
        self.applied = binding
        self.provider.state = state or {}


class _Coordinator:
    def __init__(self):
        self.binding = None

    def discovered_binding(self):
        return {"config_entry_id": "nord-entry", "area": "SE2", "currency": "SEK"}

    def set_site_binding(self, binding):
        self.binding = binding


class SiteScopedRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_site_identity_filters_ledger_to_active_site(self):
        power = _MappingManager({})
        meter = _MappingManager({})
        manager = object.__new__(SiteIdentityManager)
        manager.power_manager = power
        manager.meter_manager = meter
        manager.state = {
            "active_site_id": "site-b",
            "site": {"site_id": "site-b", "name": "B"},
            "sites": [
                {"site_id": "site-a", "name": "A"},
                {"site_id": "site-b", "name": "B"},
            ],
            "site_configs": {"site-b": {"power": {}, "meter": {}, "bindings": {}}},
            "ledger": [
                {"site_id": "site-a", "generation_id": "generation-a"},
                {"site_id": "site-b", "generation_id": "generation-b"},
            ],
        }

        state = manager.public_state()

        self.assertEqual([item["generation_id"] for item in state["source_ledger"]], ["generation-b"])
        self.assertEqual([item["generation_id"] for item in state["logical_roles"]], ["generation-b"])

    async def test_price_fetch_requires_explicit_site_binding(self):
        entry = _Entry("nord-entry", {"areas": ["SE2"], "currency": "SEK"})
        services = _Services({"SE2": [{
            "start": "2026-09-03T00:00:00+02:00",
            "end": "2026-09-03T00:15:00+02:00",
            "price": 100,
        }]})
        hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(async_entries=lambda _domain: [entry]),
            services=services,
        )
        coordinator = object.__new__(ElrakningCoordinator)
        coordinator.hass = hass
        coordinator._site_binding = None
        coordinator._price_data_by_date = {}
        coordinator._active_price_date = None
        result = await coordinator._async_fetch_date(date(2026, 9, 3))
        self.assertEqual(result.error, "site_unconfigured")
        self.assertEqual(services.calls, [])

        coordinator.set_site_binding({
            "config_entry_id": "nord-entry",
            "area": "SE2",
            "currency": "SEK",
            "binding_fingerprint": "binding-a",
        })
        result = await coordinator._async_fetch_date(date(2026, 9, 3))
        self.assertIsNone(result.error)
        self.assertEqual(services.calls[-1][2]["config_entry"], "nord-entry")
        self.assertEqual(services.calls[-1][2]["date"], "2026-09-03")

    def test_binding_fingerprint_excludes_only_derived_fingerprint(self):
        binding = {"config_entry_id": "entry", "area": "SE2", "currency": "SEK"}
        fingerprint = SiteIdentityManager.binding_fingerprint(binding)
        self.assertEqual(
            fingerprint,
            SiteIdentityManager.binding_fingerprint({**binding, "binding_fingerprint": "old"}),
        )

    async def test_switching_to_empty_site_clears_site_adjustments_but_keeps_global_price(self):
        power = _MappingManager({"consumption_entity": "sensor.load_a"})
        meter = _MappingManager({"power_entity": "sensor.import_a"})
        hass = types.SimpleNamespace(
            config=types.SimpleNamespace(latitude=59.3, longitude=18.1),
            config_entries=types.SimpleNamespace(async_entries=lambda _domain: []),
        )
        manager = SiteIdentityManager(hass, power, meter)
        manager.store = _Store()
        await manager.async_load()
        await manager.async_sync_from_current()
        provider = _ProviderManager()
        grid = _GridManager()
        coordinator = _Coordinator()
        await manager.async_prepare_runtime_bindings(provider, grid, coordinator)
        site_a = manager.state["active_site_id"]
        await manager.async_create_site("B")
        site_b = manager.state["sites"][-1]["site_id"]

        await manager.async_activate_site(site_b)
        self.assertIsNone(provider.applied)
        self.assertEqual(coordinator.binding, manager.global_binding("nord_pool"))
        self.assertEqual(grid.provider.state, {})
        self.assertEqual(power.mapping, {})
        self.assertEqual(meter.mapping, {})
        self.assertEqual(manager.state["site_configs"][site_b]["bindings"], {})
        self.assertEqual(manager.global_binding("nord_pool"), {
            "config_entry_id": "nord-entry",
            "area": "SE2",
            "currency": "SEK",
            "binding_fingerprint": SiteIdentityManager.binding_fingerprint({
                "config_entry_id": "nord-entry", "area": "SE2", "currency": "SEK"
            }),
        })
        self.assertEqual(coordinator.binding, manager.global_binding("nord_pool"))
