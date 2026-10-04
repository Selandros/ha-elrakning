import types
import asyncio
import unittest
from unittest import mock
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

from tests._elrakning_test_bootstrap import install_elrakning_package_stub, install_homeassistant_stubs
from tests._elrakning_test_bootstrap import install_optional_dependency_stubs


install_homeassistant_stubs()
install_elrakning_package_stub()
install_optional_dependency_stubs()
from custom_components.elrakning.coordinator import ElrakningCoordinator  # noqa: E402
import custom_components.elrakning.coordinator as coordinator_module  # noqa: E402
from custom_components.elrakning.site_identity import SiteIdentityManager  # noqa: E402
from custom_components.elrakning.websocket import websocket_ella_binding_set  # noqa: E402


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


class _HangingServices:
    def __init__(self):
        self.calls = []
        self.cancelled = False

    async def async_call(self, domain, service, data, **kwargs):
        self.calls.append((domain, service, data, kwargs))
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class _DelayedServices:
    def __init__(self, response, delay):
        self.response = response
        self.delay = delay
        self.calls = []

    async def async_call(self, domain, service, data, **kwargs):
        self.calls.append((domain, service, data, kwargs))
        await asyncio.sleep(self.delay)
        return self.response


class _DeferredServices:
    def __init__(self):
        self.calls = []
        self.future = asyncio.get_running_loop().create_future()

    async def async_call(self, domain, service, data, **kwargs):
        self.calls.append((domain, service, data, kwargs))
        return await self.future


class _Store:
    def __init__(self, data=None):
        self.data = data

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data


class _DiagnosticManager:
    def __init__(self):
        self.events = []

    async def async_diagnostic(self, level, component, event, message):
        self.events.append((level, component, event, message))


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

    def test_ella_requires_explicit_verified_versioned_binding(self):
        manager = object.__new__(SiteIdentityManager)
        manager.state = {
            "active_site_id": "site-b",
            "sites": [{"site_id": "site-b", "name": "B"}],
            "site_configs": {
                "site-b": {
                    "power": {"solar_entities": ["sensor.solar"]},
                    "meter": {},
                    "bindings": {},
                }
            },
        }

        self.assertIsNone(manager.active_ella_binding())
        self.assertFalse(manager.public_state()["ella_binding_verified"])

        manager.state["site_configs"]["site-b"]["bindings"]["ella"] = {
            "binding_version": 1,
            "capability": "ella_planner",
            "enabled": True,
            "verification_state": "verified",
            "actuator_write_enabled": False,
            "binding_fingerprint": SiteIdentityManager.binding_fingerprint({
                "binding_version": 1,
                "capability": "ella_planner",
                "enabled": True,
                "verification_state": "verified",
                "actuator_write_enabled": False,
            }),
        }

        self.assertEqual(manager.active_ella_binding()["binding_version"], 1)
        self.assertTrue(manager.public_state()["ella_binding_verified"])

    def test_ella_binding_does_not_follow_general_site_configuration(self):
        manager = object.__new__(SiteIdentityManager)
        manager.state = {
            "active_site_id": "fiskvik",
            "sites": [{"site_id": "fiskvik", "name": "Fiskvik"}],
            "site_configs": {
                "fiskvik": {
                    "power": {"solar_entities": ["sensor.solar"]},
                    "meter": {"import_power": "sensor.grid"},
                    "bindings": {"grid": {"provider": "generic-grid"}},
                }
            },
        }

        self.assertTrue(manager.public_state()["site_configured"])
        self.assertFalse(manager.public_state()["ella_binding_verified"])

    def test_ella_binding_validation_rejects_invalid_or_actuator_enabled_state(self):
        self.assertFalse(SiteIdentityManager.is_valid_ella_planner_binding({
            "binding_version": 1, "capability": "ella_planner", "enabled": True,
            "verification_state": "verified", "actuator_write_enabled": False,
            "binding_fingerprint": "foo",
        }))

    def test_ella_binding_rejects_stale_or_tampered_fingerprint(self):
        binding = {
            "binding_version": 1,
            "capability": "ella_planner",
            "enabled": True,
            "verification_state": "verified",
            "actuator_write_enabled": False,
        }
        binding["binding_fingerprint"] = SiteIdentityManager.binding_fingerprint(binding)
        self.assertTrue(SiteIdentityManager.is_valid_ella_planner_binding(binding, require_enabled=True))
        binding["binding_fingerprint"] = "0" * 64
        self.assertFalse(SiteIdentityManager.is_valid_ella_planner_binding(binding, require_enabled=True))

    def test_ella_mutation_websocket_requires_admin_and_accepts_intent_only(self):
        source = (Path(__file__).parents[1] / "custom_components" / "elrakning" / "websocket.py").read_text()
        start = source.index("async def websocket_ella_binding_set")
        body = source[start:source.index("\n\ndef _solar_forecast_manager", start)]
        self.assertIn('"admin_required"', body)
        self.assertIn('msg["site_id"]', body)
        self.assertIn('msg["enabled"]', body)
        for forbidden in ("verification_state", "binding_fingerprint", "binding_version", "actuator_write_enabled"):
            self.assertNotIn(f'msg["{forbidden}"]', body)

    def test_ella_mutation_websocket_enforces_admin_and_delegates_only_intent(self):
        class Connection:
            def __init__(self, is_admin):
                self.user = types.SimpleNamespace(is_admin=is_admin)
                self.results = []
            def send_result(self, msg_id, result):
                self.results.append((msg_id, result))

        class Manager:
            def __init__(self):
                self.calls = []
            async def async_set_ella_planner_binding(self, site_id, enabled):
                self.calls.append((site_id, enabled))
                return {"ella_binding_verified": enabled}

        manager = Manager()
        hass = types.SimpleNamespace(data={"elrakning": {"site_identity_manager": manager}})
        message = {"id": 1, "site_id": "site-a", "enabled": True}
        non_admin = Connection(False)
        asyncio.run(websocket_ella_binding_set(hass, non_admin, message))
        self.assertEqual(non_admin.results[-1], (1, {"success": False, "error": "admin_required"}))
        self.assertEqual(manager.calls, [])

        admin = Connection(True)
        asyncio.run(websocket_ella_binding_set(hass, admin, message))
        self.assertEqual(manager.calls, [("site-a", True)])
        self.assertEqual(admin.results[-1], (1, {"success": True, "ella_binding_verified": True}))
        self.assertFalse(SiteIdentityManager.is_valid_ella_planner_binding({
            "binding_version": 1, "capability": "ella_planner", "enabled": True,
            "verification_state": "verified", "actuator_write_enabled": True,
            "binding_fingerprint": "0" * 64,
        }))

    async def test_ella_binding_enable_disable_is_explicit_and_versioned(self):
        class _Store:
            async def async_save(self, _state):
                return None
        manager = object.__new__(SiteIdentityManager)
        manager.store = _Store()
        manager.state = {
            "active_site_id": "site-a",
            "sites": [{"site_id": "site-a", "name": "A"}],
            "site_configs": {"site-a": {"power": {}, "meter": {}, "bindings": {}}},
        }
        enabled = await manager.async_set_ella_planner_binding("site-a", True)
        self.assertTrue(enabled["ella_binding_verified"])
        binding = manager.state["site_configs"]["site-a"]["bindings"]["ella"]
        self.assertTrue(SiteIdentityManager.is_valid_ella_planner_binding(binding, require_enabled=True))
        disabled = await manager.async_set_ella_planner_binding("site-a", False)
        self.assertFalse(disabled["ella_binding_verified"])
        self.assertNotIn("ella", manager.state["site_configs"]["site-a"]["bindings"])

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

    async def test_global_price_binding_works_for_unconfigured_site(self):
        entry = _Entry("nord-entry", {"areas": ["SE2"], "currency": "SEK"})
        entry.domain = "nordpool"
        services = _Services({"SE2": [{
            "start": "2026-10-04T00:00:00+02:00",
            "end": "2026-10-04T00:15:00+02:00",
            "price": 264.2,
        }]})
        hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(
                async_entries=lambda _domain: [entry],
                async_entry_for_id=lambda entry_id: entry if entry_id == "nord-entry" else None,
            ),
            services=services,
        )
        coordinator = object.__new__(ElrakningCoordinator)
        coordinator.hass = hass
        coordinator._site_binding = {
            "config_entry_id": "nord-entry", "area": "SE2", "currency": "SEK",
        }
        coordinator._price_data_by_date = {}
        coordinator._active_price_date = None
        result = await coordinator._async_fetch_date(date(2026, 10, 4))
        self.assertIsNone(result.error)
        self.assertEqual(len(result.periods), 1)
        self.assertEqual(services.calls[-1][0], "nordpool")
        self.assertEqual(services.calls[-1][2]["resolution"], 15)

    async def test_future_price_fanout_is_blocked_without_tomorrow_sensor(self):
        entry = _Entry("nord-entry", {"areas": ["SE2"], "currency": "SEK"})
        services = _Services({"SE2": []})
        requested_entities = []
        states = types.SimpleNamespace(get=lambda entity_id: (requested_entities.append(entity_id), types.SimpleNamespace(state="off"))[1])
        hass = types.SimpleNamespace(
            states=states,
            config_entries=types.SimpleNamespace(
                async_entries=lambda _domain: [entry],
                async_entry_for_id=lambda entry_id: entry if entry_id == "nord-entry" else None,
            ),
            services=services,
        )
        coordinator = object.__new__(ElrakningCoordinator)
        coordinator.hass = hass
        coordinator._site_binding = {"config_entry_id": "nord-entry", "area": "SE2", "currency": "SEK"}
        coordinator._price_data_by_date = {}
        coordinator._active_price_date = None
        with mock.patch.object(coordinator_module.dt_util, "now", return_value=datetime(2026, 10, 4, tzinfo=timezone.utc)):
            result = await coordinator.async_get_price_data(date(2026, 10, 6))
        self.assertEqual(result.error, "future_price_unavailable")
        self.assertEqual(services.calls, [])
        self.assertEqual(requested_entities, [])

    async def test_tomorrow_price_requires_the_area_sensor_to_be_on(self):
        entry = _Entry("nord-entry", {"areas": ["SE2"], "currency": "SEK"})
        services = _Services({"SE2": [{
            "start": "2026-10-04T22:00:00+00:00",
            "end": "2026-10-04T22:15:00+00:00",
            "price": 194.64,
        }]})
        sensor = types.SimpleNamespace(state="off")
        requested_entities = []
        states = types.SimpleNamespace(get=lambda entity_id: (requested_entities.append(entity_id), sensor)[1])
        hass = types.SimpleNamespace(
            states=states,
            config_entries=types.SimpleNamespace(
                async_entries=lambda _domain: [entry],
                async_entry_for_id=lambda entry_id: entry if entry_id == "nord-entry" else None,
            ),
            services=services,
        )
        coordinator = object.__new__(ElrakningCoordinator)
        coordinator.hass = hass
        coordinator._site_binding = {"config_entry_id": "nord-entry", "area": "SE2", "currency": "SEK"}
        coordinator._price_data_by_date = {}
        coordinator._active_price_date = None
        with mock.patch.object(coordinator_module.dt_util, "now", return_value=datetime(2026, 10, 4, tzinfo=timezone.utc)):
            blocked = await coordinator.async_get_price_data(date(2026, 10, 5))
            sensor.state = "on"
            allowed = await coordinator.async_get_price_data(date(2026, 10, 5))
        self.assertEqual(blocked.error, "future_price_unavailable")
        self.assertIsNone(allowed.error)
        self.assertEqual(services.calls[0][2]["date"], "2026-10-05")
        self.assertEqual(requested_entities, ["binary_sensor.nord_pool_se2_morgondagens_pristillgangligt", "binary_sensor.nord_pool_se2_morgondagens_pristillgangligt"])

    async def test_price_failure_and_success_context_is_recorded_in_diagnostics(self):
        entry = _Entry("nord-entry", {"areas": ["SE2"], "currency": "SEK"})
        entry.domain = "nordpool"
        manager = _DiagnosticManager()
        hass = types.SimpleNamespace(
            data={"elrakning": {"elhandel_manager": manager}},
            config_entries=types.SimpleNamespace(
                async_entries=lambda _domain: [entry],
                async_entry_for_id=lambda entry_id: entry if entry_id == "nord-entry" else None,
            ),
            services=_Services({"SE2": [{
                "start": "2026-10-04T00:00:00+00:00",
                "end": "2026-10-04T00:15:00+00:00",
                "price": 194.64,
            }]}),
        )
        coordinator = object.__new__(ElrakningCoordinator)
        coordinator.hass = hass
        coordinator._site_binding = {"config_entry_id": "nord-entry", "area": "SE2", "currency": "SEK"}
        coordinator._price_data_by_date = {}
        result = await coordinator._async_fetch_date(date(2026, 10, 4))
        self.assertIsNone(result.error)
        self.assertEqual(
            [event[2] for event in manager.events],
            ["price_fetch_start", "price_service_call_start", "price_fetch_success"],
        )
        self.assertIn("period_count=1", manager.events[-1][3])

    async def test_missing_or_stale_global_price_binding_fails_closed(self):
        hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(
                async_entries=lambda _domain: [],
                async_entry_for_id=lambda _entry_id: None,
            ),
            services=_Services({}),
        )
        coordinator = object.__new__(ElrakningCoordinator)
        coordinator.hass = hass
        coordinator._site_binding = {
            "config_entry_id": "stale-entry", "area": "SE2", "currency": "SEK",
        }
        coordinator._price_data_by_date = {}
        coordinator._active_price_date = None
        result = await coordinator._async_fetch_date(date(2026, 10, 4))
        self.assertEqual(result.error, "missing_integration")
        self.assertEqual(hass.services.calls, [])

        other_entry = _Entry("other-entry", {"areas": ["SE2"], "currency": "SEK"})
        hass.config_entries.async_entries = lambda _domain: [other_entry]
        result = await coordinator._async_fetch_date(date(2026, 10, 4))
        self.assertEqual(result.error, "data_unavailable")

    async def test_hanging_price_service_fails_closed_and_is_cancelled(self):
        entry = _Entry("nord-entry", {"areas": ["SE2"], "currency": "SEK"})
        services = _HangingServices()
        hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(
                async_entries=lambda _domain: [entry],
                async_entry_for_id=lambda entry_id: entry if entry_id == "nord-entry" else None,
            ),
            services=services,
        )
        coordinator = object.__new__(ElrakningCoordinator)
        coordinator.hass = hass
        coordinator._site_binding = {
            "config_entry_id": "nord-entry", "area": "SE2", "currency": "SEK",
        }
        coordinator._price_data_by_date = {}
        coordinator._active_price_date = None
        previous_timeout = coordinator_module.PRICE_SERVICE_TIMEOUT_SECONDS
        coordinator_module.PRICE_SERVICE_TIMEOUT_SECONDS = 0.01
        try:
            result = await coordinator._async_fetch_date(date(2026, 10, 4))
        finally:
            coordinator_module.PRICE_SERVICE_TIMEOUT_SECONDS = previous_timeout
        self.assertEqual(result.error, "data_unavailable")
        self.assertTrue(services.cancelled)

    async def test_real_nord_pool_map_shape_normalizes_96_quarter_hours(self):
        entry = _Entry("nord-entry", {"areas": ["SE2"], "currency": "SEK"})
        first_start = datetime(2026, 10, 3, 22, tzinfo=timezone.utc)
        raw_periods = []
        for index in range(96):
            start = first_start + timedelta(minutes=15 * index)
            raw_periods.append({
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=15)).isoformat(),
                "price": 194.64 if index == 0 else 518.93 if index == 44 else 64.43 if index == 95 else 200.0,
            })
        services = _Services({"SE2": raw_periods})
        hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(
                async_entries=lambda _domain: [entry],
                async_entry_for_id=lambda entry_id: entry if entry_id == "nord-entry" else None,
            ),
            services=services,
        )
        coordinator = object.__new__(ElrakningCoordinator)
        coordinator.hass = hass
        coordinator._site_binding = {
            "config_entry_id": "nord-entry", "area": "SE2", "currency": "SEK",
        }
        coordinator._price_data_by_date = {}
        coordinator._active_price_date = None
        result = await coordinator._async_fetch_date(date(2026, 10, 4))
        self.assertIsNone(result.error)
        self.assertEqual(len(result.periods), 96)
        self.assertAlmostEqual(result.periods[0].price, 0.19464)
        self.assertAlmostEqual(result.periods[44].price, 0.51893)
        self.assertAlmostEqual(result.periods[95].price, 0.06443)

    async def test_slow_successful_price_service_is_not_discarded(self):
        entry = _Entry("nord-entry", {"areas": ["SE2"], "currency": "SEK"})
        services = _DelayedServices({"SE2": [{
            "start": "2026-10-03T22:00:00+00:00",
            "end": "2026-10-03T22:15:00+00:00",
            "price": 194.64,
        }]}, 0.02)
        hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(
                async_entries=lambda _domain: [entry],
                async_entry_for_id=lambda entry_id: entry if entry_id == "nord-entry" else None,
            ),
            services=services,
        )
        coordinator = object.__new__(ElrakningCoordinator)
        coordinator.hass = hass
        coordinator._site_binding = {
            "config_entry_id": "nord-entry", "area": "SE2", "currency": "SEK",
        }
        coordinator._price_data_by_date = {}
        coordinator._active_price_date = None
        previous_timeout = coordinator_module.PRICE_SERVICE_TIMEOUT_SECONDS
        coordinator_module.PRICE_SERVICE_TIMEOUT_SECONDS = 0.05
        try:
            result = await coordinator._async_fetch_date(date(2026, 10, 4))
        finally:
            coordinator_module.PRICE_SERVICE_TIMEOUT_SECONDS = previous_timeout
        self.assertIsNone(result.error)
        self.assertEqual(len(result.periods), 1)

    async def test_concurrent_same_date_fetches_share_one_service_call(self):
        entry = _Entry("nord-entry", {"areas": ["SE2"], "currency": "SEK"})
        services = _DelayedServices({"SE2": [{
            "start": "2026-10-03T22:00:00+00:00",
            "end": "2026-10-03T22:15:00+00:00",
            "price": 194.64,
        }]}, 0.02)
        hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(
                async_entries=lambda _domain: [entry],
                async_entry_for_id=lambda entry_id: entry if entry_id == "nord-entry" else None,
            ),
            services=services,
        )
        coordinator = object.__new__(ElrakningCoordinator)
        coordinator.hass = hass
        coordinator._site_binding = {
            "config_entry_id": "nord-entry", "area": "SE2", "currency": "SEK",
        }
        coordinator._price_data_by_date = {}
        coordinator._price_fetch_tasks = {}
        coordinator._active_price_date = None
        results = await asyncio.gather(
            coordinator.async_get_price_data(date(2026, 10, 4)),
            coordinator.async_get_price_data(date(2026, 10, 4)),
        )
        self.assertEqual(len(services.calls), 1)
        self.assertEqual([len(result.periods) for result in results], [1, 1])

    async def test_slow_fetch_continues_after_request_wait_and_updates_cache(self):
        entry = _Entry("nord-entry", {"areas": ["SE2"], "currency": "SEK"})
        services = _DeferredServices()
        hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(
                async_entries=lambda _domain: [entry],
                async_entry_for_id=lambda entry_id: entry if entry_id == "nord-entry" else None,
            ),
            services=services,
        )
        coordinator = object.__new__(ElrakningCoordinator)
        coordinator.hass = hass
        coordinator._site_binding = {
            "config_entry_id": "nord-entry", "area": "SE2", "currency": "SEK",
        }
        coordinator._price_data_by_date = {}
        coordinator._price_fetch_tasks = {}
        coordinator._active_price_date = None
        coordinator.async_set_updated_data = lambda _data: None
        previous_wait = coordinator_module.PRICE_REQUEST_WAIT_SECONDS
        previous_timeout = coordinator_module.PRICE_SERVICE_TIMEOUT_SECONDS
        coordinator_module.PRICE_REQUEST_WAIT_SECONDS = 0.01
        coordinator_module.PRICE_SERVICE_TIMEOUT_SECONDS = 1
        try:
            result = await coordinator.async_get_price_data(date(2026, 10, 4))
            self.assertEqual(result.error, "data_pending")
            self.assertEqual(len(services.calls), 1)
            services.future.set_result({"SE2": [{
                "start": "2026-10-03T22:00:00+00:00",
                "end": "2026-10-03T22:15:00+00:00",
                "price": 194.64,
            }]})
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            cached = await coordinator.async_get_price_data(date(2026, 10, 4))
        finally:
            coordinator_module.PRICE_REQUEST_WAIT_SECONDS = previous_wait
            coordinator_module.PRICE_SERVICE_TIMEOUT_SECONDS = previous_timeout
        self.assertIsNone(cached.error)
        self.assertEqual(len(cached.periods), 1)
        self.assertEqual(len(services.calls), 1)

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

    async def test_prepare_runtime_prefers_and_persists_newer_matching_grid_provider_state(self):
        power = _MappingManager({})
        meter = _MappingManager({})
        hass = types.SimpleNamespace(
            config=types.SimpleNamespace(latitude=59.3, longitude=18.1),
            config_entries=types.SimpleNamespace(async_entries=lambda _domain: []),
        )
        manager = SiteIdentityManager(hass, power, meter)
        facility = {"address": {"street": "Fiskvik 218"}, "grid_area": "MEL"}
        binding = {
            "config_entry_id": "grid-entry",
            "provider": "eon",
            "facility": facility,
        }
        cached = {
            "updated_at": "2026-09-05T21:23:38+00:00",
            "facility": facility,
            "agreement": {"status": "future"},
        }
        newer = {
            "updated_at": "2026-09-05T21:48:57+00:00",
            "facility": facility,
            "agreement": {"status": "active"},
        }
        manager.state = {
            "site": {"site_id": "site-a", "name": "A"},
            "sites": [
                {"site_id": "site-a", "name": "A"},
                {"site_id": "site-b", "name": "B"},
            ],
            "active_site_id": "site-a",
            "site_configs": {
                "site-a": {
                    "power": {},
                    "meter": {},
                    "bindings": {"grid": binding},
                    "runtime": {"grid_state": cached},
                    "collection_enabled": True,
                },
                "site-b": {"power": {}, "meter": {}, "bindings": {}, "collection_enabled": True},
            },
            "global_bindings": {},
            "ledger": [],
            "migration_complete": True,
        }
        manager.store = _Store()
        provider = _ProviderManager()
        grid = _GridManager()
        grid.provider.state = newer
        coordinator = _Coordinator()

        await manager.async_prepare_runtime_bindings(provider, grid, coordinator)

        self.assertEqual(grid.provider.state, newer)
        self.assertEqual(
            manager.state["site_configs"]["site-a"]["runtime"]["grid_state"],
            newer,
        )
        self.assertEqual(
            manager.store.data["site_configs"]["site-a"]["runtime"]["grid_state"],
            newer,
        )

    async def test_runtime_context_never_replaces_target_cache_with_older_or_other_facility_state(self):
        power = _MappingManager({})
        meter = _MappingManager({})
        manager = object.__new__(SiteIdentityManager)
        manager.power_manager = power
        manager.meter_manager = meter
        facility_b = {"address": {"street": "Site B"}, "grid_area": "B"}
        cached = {
            "updated_at": "2026-09-05T22:00:00+00:00",
            "facility": facility_b,
            "agreement": {"status": "active"},
        }
        binding = {"config_entry_id": "grid-entry", "provider": "eon", "facility": facility_b}
        manager.state = {
            "site": {"site_id": "site-b", "name": "B"},
            "sites": [{"site_id": "site-b", "name": "B"}],
            "active_site_id": "site-b",
            "site_configs": {
                "site-b": {"power": {}, "meter": {}, "bindings": {"grid": binding}, "runtime": {"grid_state": cached}}
            },
            "global_bindings": {},
            "ledger": [],
        }
        provider = _ProviderManager()
        grid = _GridManager()
        coordinator = _Coordinator()

        grid.provider.state = {
            "updated_at": "2026-09-05T23:00:00+00:00",
            "facility": {"address": {"street": "Other"}, "grid_area": "A"},
        }
        changed = await manager.async_apply_runtime_context(provider, grid, coordinator)
        self.assertFalse(changed)
        self.assertEqual(grid.provider.state, cached)

        grid.provider.state = {
            "updated_at": "2026-09-05T21:00:00+00:00",
            "facility": facility_b,
            "agreement": {"status": "future"},
        }
        changed = await manager.async_apply_runtime_context(provider, grid, coordinator)
        self.assertFalse(changed)
        self.assertEqual(grid.provider.state, cached)

    async def test_provider_bindings_unbind_only_active_site(self):
        power = _MappingManager({})
        meter = _MappingManager({})
        hass = types.SimpleNamespace(
            config=types.SimpleNamespace(latitude=59.3, longitude=18.1),
            config_entries=types.SimpleNamespace(async_entries=lambda _domain: []),
        )
        manager = SiteIdentityManager(hass, power, meter)
        manager.store = _Store({
            "site": {"site_id": "site-b", "name": "B"},
            "sites": [
                {"site_id": "site-a", "name": "A", "is_current": False},
                {"site_id": "site-b", "name": "B", "is_current": True},
            ],
            "active_site_id": "site-b",
            "site_configs": {
                "site-a": {"power": {}, "meter": {}, "bindings": {"elhandel": {"provider": "greenely", "facility_id": "164313"}}},
                "site-b": {"power": {}, "meter": {}, "bindings": {"elhandel": {"provider": "greenely", "facility_id": "624281"}}},
            },
            "global_bindings": {},
            "ledger": [],
            "migration_complete": True,
        })
        await manager.async_load()

        has_other_binding = await manager.async_unbind_provider_runtime()

        self.assertTrue(has_other_binding)
        self.assertNotIn("elhandel", manager.state["site_configs"]["site-b"]["bindings"])
        self.assertEqual(
            manager.state["site_configs"]["site-a"]["bindings"]["elhandel"]["facility_id"],
            "164313",
        )

    async def test_grid_bindings_can_share_external_source_and_unbind_only_active_site(self):
        power = _MappingManager({})
        meter = _MappingManager({})
        hass = types.SimpleNamespace(
            config=types.SimpleNamespace(latitude=59.3, longitude=18.1),
            config_entries=types.SimpleNamespace(async_entries=lambda _domain: []),
        )
        manager = SiteIdentityManager(hass, power, meter)
        manager.store = _Store({
            "site": {"site_id": "site-a", "name": "A"},
            "sites": [
                {"site_id": "site-a", "name": "A", "is_current": False},
                {"site_id": "site-b", "name": "B", "is_current": True},
            ],
            "active_site_id": "site-b",
            "site_configs": {
                "site-a": {"power": {}, "meter": {}, "bindings": {"grid": {"facility": {"id": "facility-x"}}}},
                "site-b": {"power": {}, "meter": {}, "bindings": {"grid": {"facility": {"id": "facility-x"}}}},
            },
            "global_bindings": {},
            "ledger": [],
            "migration_complete": True,
        })
        await manager.async_load()

        has_other_binding = await manager.async_unbind_grid_runtime()

        self.assertTrue(has_other_binding)
        self.assertNotIn("grid", manager.state["site_configs"]["site-b"]["bindings"])
        self.assertEqual(
            manager.state["site_configs"]["site-a"]["bindings"]["grid"]["facility"]["id"],
            "facility-x",
        )
