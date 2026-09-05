import copy
import types
import unittest
from datetime import datetime, timezone

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)

install_homeassistant_stubs()
install_elrakning_package_stub()
install_optional_dependency_stubs()

from custom_components.elrakning.const import DOMAIN, GRID_CONFIG_KEY  # noqa: E402
from custom_components.elrakning.elnat import manager as manager_module  # noqa: E402
from custom_components.elrakning.site_economic_frames import (  # noqa: E402
    build_eon_grid_economic_frames,
)
from custom_components.elrakning.site_identity import SiteIdentityManager  # noqa: E402
from custom_components.elrakning import websocket as websocket_module  # noqa: E402


ACTIVE_GRID_STATE = {
    "configured": True,
    "provider": "eon",
    "provider_name": "E.ON",
    "auth_method": "app",
    "agreement": {
        "status": "active",
        "source_status": "ACTIVE",
        "type": "ELECTRICITY_CONS_GRID",
        "name": "16 A, upp till 8000 kWh/år. Elnätsområde Nord",
        "start_date": "2026-01-01",
        "end_date": None,
    },
    "facility": {
        "address": {
            "street": "Fiskvik 218",
            "city": "Bergsjö",
            "postal_code": "829 53",
        },
        "grid_area": "MEL",
        "price_area": "SE2",
        "fuse_ampere": 16,
    },
    "tariff": {"name": "16 A Nord"},
    "grid_price": {
        "source": "grouped_contracts",
        "source_subtitle": "Samtliga priser är inklusive moms.",
        "vat_included": True,
        "price_basis": "gross",
        "fixed_monthly_sek": 226.25,
        "transfer_ore_per_kwh_gross": 97.0,
        "energy_tax_ore_per_kwh_gross": 45.0,
        "variable_total_ore_per_kwh_gross": 142.0,
    },
    "updated_at": "2026-09-05T20:00:00+00:00",
    "reauth_required": False,
    "error": None,
}


class _Bus:
    def __init__(self):
        self.events = []

    def async_listen(self, *_args):
        return lambda: None

    def async_fire(self, event, *args, **kwargs):
        self.events.append(event)


class _ConfigEntries:
    def async_entries(self, _domain):
        return []

    def async_update_entry(self, entry, *, data):
        entry.data = dict(data)


class _Store:
    def __init__(self, data=None):
        self.data = copy.deepcopy(data)

    async def async_load(self):
        return copy.deepcopy(self.data)

    async def async_save(self, data):
        self.data = copy.deepcopy(data)


class _MappingManager:
    def __init__(self):
        self.mapping = {}

    async def async_restore_mapping(self, mapping):
        self.mapping = dict(mapping or {})


class _ElhandelManager:
    def __init__(self):
        self.entry = types.SimpleNamespace(entry_id="elhandel-entry")
        self.state = {}
        self.binding = None

    async def async_apply_site_binding(self, binding):
        self.binding = binding


class _Coordinator:
    def __init__(self):
        self.binding = None

    def set_site_binding(self, binding):
        self.binding = binding


class _Provider:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.state = self._empty_state()
        self.refresh_starts = 0
        self.remove_calls = 0
        self.cancelled = 0

    @property
    def configured(self):
        return isinstance(self.entry.data.get(GRID_CONFIG_KEY), dict)

    async def async_load(self):
        return None

    async def async_login(self, auth_method, account_id, password):
        if auth_method != "app" or not account_id or not password:
            return {"status": "invalid_input", "error": "invalid_input"}
        self.entry.data[GRID_CONFIG_KEY] = {
            "provider": "eon",
            "auth_method": "app",
            "provider_config": {"account_id": account_id, "password": password},
        }
        self.state = copy.deepcopy(ACTIVE_GRID_STATE)
        return self.public_state()

    async def async_remove(self):
        self.remove_calls += 1
        self.entry.data.pop(GRID_CONFIG_KEY, None)
        self.state = self._empty_state()
        return self.public_state()

    async def async_source_data(self):
        return {
            "provider": "eon",
            "facility": copy.deepcopy(self.state.get("facility")),
        }

    def async_start_refresh(self):
        self.refresh_starts += 1

    def _cancel_web_refresh(self):
        self.cancelled += 1

    def _empty_state(self):
        return {
            "configured": False,
            "facility": None,
            "agreement": None,
            "tariff": None,
            "grid_price": None,
            "updated_at": None,
        }

    def public_state(self):
        return {
            **copy.deepcopy(self.state),
            "configured": self.configured,
            "provider": "eon",
            "provider_name": "E.ON",
            "auth_method": "app" if self.configured else None,
        }


class _Connection:
    def __init__(self):
        self.results = []

    def send_result(self, msg_id, payload):
        self.results.append((msg_id, payload))

    @property
    def last(self):
        return self.results[-1][1]


class GridMultiSiteControlPlaneTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.definition = types.SimpleNamespace(
            provider_id="eon",
            manager_factory=lambda hass, entry: _Provider(hass, entry),
        )
        self.original_configured = manager_module.configured_grid_provider
        self.original_get = manager_module.get_grid_provider
        manager_module.configured_grid_provider = lambda _entry: self.definition
        manager_module.get_grid_provider = lambda provider_id: (
            self.definition if provider_id == "eon" else None
        )

    async def asyncTearDown(self):
        manager_module.configured_grid_provider = self.original_configured
        manager_module.get_grid_provider = self.original_get

    def _hass(self):
        return types.SimpleNamespace(
            config=types.SimpleNamespace(latitude=61.98, longitude=17.06),
            config_entries=_ConfigEntries(),
            data={DOMAIN: {}},
            bus=_Bus(),
        )

    async def _runtime(self, *, persisted=None, entry=None):
        hass = self._hass()
        power = _MappingManager()
        meter = _MappingManager()
        site_manager = SiteIdentityManager(hass, power, meter)
        site_manager.store = _Store(persisted)
        await site_manager.async_load()
        if persisted is None:
            site_a = site_manager.state["active_site_id"]
            await site_manager.async_rename_site(site_a, "A")
            await site_manager.async_create_site("B")
        else:
            site_a = next(
                item["site_id"]
                for item in site_manager.state["sites"]
                if item["name"] == "A"
            )
        site_b = next(
            item["site_id"]
            for item in site_manager.state["sites"]
            if item["name"] == "B"
        )
        entry = entry or types.SimpleNamespace(entry_id="grid-entry", data={})
        grid_manager = manager_module.GridManager(hass, entry)
        await grid_manager.async_load()
        hass.data[DOMAIN]["site_identity_manager"] = site_manager
        hass.data[DOMAIN]["grid_manager"] = grid_manager
        elhandel = _ElhandelManager()
        coordinator = _Coordinator()
        await site_manager.async_prepare_runtime_bindings(
            elhandel, grid_manager, coordinator
        )
        return hass, site_manager, grid_manager, entry, site_a, site_b

    async def _login(self, hass, account="account", password="secret"):
        connection = _Connection()
        await websocket_module.websocket_grid_login(
            hass,
            connection,
            {
                "id": 1,
                "type": websocket_module.GRID_LOGIN_COMMAND,
                "provider": "eon",
                "auth_method": "app",
                "account_id": account,
                "password": password,
            },
        )
        self.assertTrue(connection.last["success"])
        return connection.last

    async def _remove(self, hass):
        connection = _Connection()
        await websocket_module.websocket_grid_remove(
            hass,
            connection,
            {"id": 2, "type": websocket_module.GRID_REMOVE_COMMAND},
        )
        self.assertTrue(connection.last["success"])
        return connection.last

    async def test_same_facility_a_to_b_to_a_remove_b_leaves_a(self):
        hass, sites, grid, entry, site_a, site_b = await self._runtime()

        result_a = await self._login(hass)
        self.assertTrue(result_a["configured"])
        binding_a = copy.deepcopy(sites.active_binding("grid"))
        self.assertIsNotNone(binding_a)
        self.assertEqual(
            binding_a["facility"]["address"]["street"], "Fiskvik 218"
        )
        self.assertEqual(grid._site_binding, binding_a)
        self.assertEqual(grid.provider.refresh_starts, 1)

        await sites.async_activate_site(site_b)
        self.assertIsNone(sites.active_binding("grid"))
        self.assertTrue(grid.configured)
        self.assertIsNone(grid.provider.state["facility"])

        result_b = await self._login(hass)
        self.assertTrue(result_b["configured"])
        binding_b = copy.deepcopy(sites.active_binding("grid"))
        self.assertIsNotNone(binding_b)
        self.assertEqual(binding_b["facility"], binding_a["facility"])
        self.assertEqual(entry.data[GRID_CONFIG_KEY]["provider"], "eon")

        captured = datetime(2026, 9, 5, 20, 1, tzinfo=timezone.utc)
        frames_a = build_eon_grid_economic_frames(
            site_a, binding_a, ACTIVE_GRID_STATE, captured
        )
        frames_b = build_eon_grid_economic_frames(
            site_b, binding_b, ACTIVE_GRID_STATE, captured
        )
        transfer_a = next(
            item["frame"]
            for item in frames_a
            if item["frame"]["logical_role"] == "economic.grid.import.transfer"
        )
        transfer_b = next(
            item["frame"]
            for item in frames_b
            if item["frame"]["logical_role"] == "economic.grid.import.transfer"
        )
        self.assertNotEqual(
            transfer_a["source_generation_id"],
            transfer_b["source_generation_id"],
        )
        self.assertEqual(
            transfer_a["provenance"]["facility_context_sha256"],
            transfer_b["provenance"]["facility_context_sha256"],
        )
        self.assertEqual(
            transfer_a["provenance"]["config_entry_id"],
            transfer_b["provenance"]["config_entry_id"],
        )

        await sites.async_activate_site(site_a)
        self.assertEqual(sites.active_binding("grid"), binding_a)
        self.assertEqual(
            grid.provider.state["facility"], ACTIVE_GRID_STATE["facility"]
        )

        await sites.async_activate_site(site_b)
        removed = await self._remove(hass)
        self.assertEqual(removed["configured"], False)
        self.assertEqual(removed["site_status"], "unconfigured")
        self.assertIsNone(sites.active_binding("grid"))
        self.assertIn(GRID_CONFIG_KEY, entry.data)
        self.assertEqual(grid.provider.remove_calls, 0)

        await sites.async_activate_site(site_a)
        self.assertEqual(sites.active_binding("grid"), binding_a)
        self.assertTrue(grid.configured)
        self.assertEqual(
            grid.provider.state["facility"], ACTIVE_GRID_STATE["facility"]
        )
        self.assertIn("elrakning_eon_grid_update", hass.bus.events)

    async def test_restart_reload_keeps_a_after_b_is_removed(self):
        hass, sites, grid, entry, site_a, site_b = await self._runtime()
        await self._login(hass)
        binding_a = copy.deepcopy(sites.active_binding("grid"))
        await sites.async_activate_site(site_b)
        await self._login(hass)
        await self._remove(hass)
        await sites.async_activate_site(site_a)
        persisted = copy.deepcopy(sites.store.data)

        (
            _,
            reloaded_sites,
            reloaded_grid,
            reloaded_entry,
            reloaded_a,
            reloaded_b,
        ) = await self._runtime(persisted=persisted, entry=entry)

        self.assertEqual(reloaded_a, site_a)
        self.assertEqual(reloaded_b, site_b)
        self.assertEqual(reloaded_sites.state["active_site_id"], site_a)
        self.assertEqual(reloaded_sites.active_binding("grid"), binding_a)
        self.assertIsNone(
            reloaded_sites.state["site_configs"][site_b]["bindings"].get("grid")
        )
        self.assertIn(GRID_CONFIG_KEY, reloaded_entry.data)
        self.assertTrue(reloaded_grid.configured)
        self.assertEqual(reloaded_grid._site_binding, binding_a)
        self.assertEqual(
            reloaded_grid.provider.state["facility"], ACTIVE_GRID_STATE["facility"]
        )

    async def test_grid_source_data_uses_grid_binding_not_physical_site_mapping(self):
        hass, sites, _grid, _entry, _site_a, site_b = await self._runtime()
        self.assertFalse(sites.active_site_is_configured())

        await self._login(hass)
        self.assertIsNotNone(sites.active_binding("grid"))
        connection = _Connection()
        await websocket_module.websocket_grid_source_data(
            hass,
            connection,
            {"id": 3, "type": websocket_module.GRID_SOURCE_DATA_COMMAND},
        )
        self.assertTrue(connection.last["success"])
        self.assertEqual(
            connection.last["facility"]["address"]["street"], "Fiskvik 218"
        )

        await sites.async_activate_site(site_b)
        self.assertFalse(sites.active_site_is_configured())
        self.assertIsNone(sites.active_binding("grid"))
        connection = _Connection()
        await websocket_module.websocket_grid_source_data(
            hass,
            connection,
            {"id": 4, "type": websocket_module.GRID_SOURCE_DATA_COMMAND},
        )
        self.assertEqual(
            connection.last,
            {"success": False, "error": "site_unconfigured"},
        )
