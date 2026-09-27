"""Executable lifecycle, key, auth, and executor tests for C.4C.1."""

import asyncio
import hashlib
import importlib.util
import json
import sys
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)

install_homeassistant_stubs()
install_elrakning_package_stub()
install_optional_dependency_stubs()

from custom_components.elrakning.canonical_storage import HISTORY_FOUND, HISTORY_NONE, HISTORY_UNKNOWN
from custom_components.elrakning.elhandel.providers.greenely_invoice_economics import (
    SERVICE_PROVISION,
    GreenelyInvoiceEconomicsProducer,
    async_register_proof_service,
)
from custom_components.elrakning.elhandel.providers.greenely_client import GreenelyError
from custom_components.elrakning.pseudonymization import PseudonymizationDomain
from custom_components.elrakning.site_identity import SiteIdentityManager


class FakeHass:
    def __init__(self, history=HISTORY_NONE):
        self.history = history
        self.executor_calls = []
        self.data = {"elrakning": {}}
        self.auth = SimpleNamespace(async_get_user=self._get_user)
        self.user = None

    def async_create_task(self, coroutine):
        return asyncio.create_task(coroutine)

    async def async_add_executor_job(self, function, *args):
        self.executor_calls.append(function)
        return function(*args)

    async def _get_user(self, user_id):
        return self.user if user_id == "known" else None


class FakeServices:
    def __init__(self):
        self.handlers = {}

    def has_service(self, domain, service):
        return (domain, service) in self.handlers

    def async_register(self, domain, service, handler, **_kwargs):
        self.handlers[(domain, service)] = handler

    def async_remove(self, domain, service):
        self.handlers.pop((domain, service), None)


class FakeStorage:
    def __init__(self, status):
        self.status = status

    def external_history_status_for_identity_domain(self, dataset, domain):
        if isinstance(self.status, BaseException):
            raise self.status
        return self.status


class CaptureStorage:
    def __init__(self):
        self.frames = {}
        self.calls = []

    def ensure_source_generation(self, target, _now):
        return None

    def latest_external_frame_snapshot(self, semantic_key):
        return self.frames.get(semantic_key)

    def insert_external_frame(self, frame, points):
        self.calls.append((frame, points))
        self.frames[frame["semantic_key"]] = {"frame": frame, "points": [{"value": p["value"], "point_json": json.dumps(p["point"], sort_keys=True)} for p in points]}


class CaptureDomain:
    key_id = "key"

    @staticmethod
    def occurrence_identity(_contract, occurrence):
        return f"occ-{occurrence}"


class CaptureIdentity:
    def __init__(self):
        self.binding = {"provider": "greenely", "config_entry_id": "entry", "facility_id": "facility", "binding_fingerprint": "binding"}
        self.proof = {"proof_fingerprint": "proof", "proof_semantic_identity": "proof-semantic", "contract_identity_fingerprint": SiteIdentityManager.identity_fingerprint({"contract_id": "contract"}), "invoice_installation_identity_fingerprint": SiteIdentityManager.identity_fingerprint({"installation_id": "install"})}
        self.mutable = True
        self.timezone = "Europe/Stockholm"

    def collection_site_configs(self):
        return {"site": {"collection_enabled": self.mutable, "location": {"verification_state": "verified", "timezone": self.timezone}, "bindings": {"elhandel": dict(self.binding)}}}

    @staticmethod
    def identity_fingerprint(payload):
        return SiteIdentityManager.identity_fingerprint(payload)

    def validated_greenely_proof(self, _site_id, _binding):
        return dict(self.proof) if self.mutable else None


class CaptureClient:
    def __init__(self, _hass, pdf_event=None, pdf_release=None):
        self.pdf_event = pdf_event
        self.pdf_release = pdf_release

    async def async_login(self, *_args):
        return None

    async def async_get_electricity_contracts(self, _facility):
        return [{"id": "contract", "facility_id": "facility"}]

    async def async_get_invoices(self, _contract):
        return [{"invoice_date": "2026-08-01", "due_date": "2026-08-15", "month": "2026-07", "ocr_number": "ocr-1"}]

    async def async_get_invoice_pdf(self, _contract, _invoice):
        if self.pdf_event:
            self.pdf_event.set()
            await self.pdf_release.wait()
        return b"pdf"


class TestC4C1Async(unittest.IsolatedAsyncioTestCase):
    def _service_fixture(self, contract_batches):
        hass = FakeHass()
        hass.services = FakeServices()
        hass.user = SimpleNamespace(is_admin=True)
        binding = {"provider": "greenely", "config_entry_id": "entry", "facility_id": "facility"}
        binding["binding_fingerprint"] = SiteIdentityManager.binding_fingerprint(binding)
        semantic = {
            "relation": "greenely_meter_id_to_invoice_installation_id",
            "provider_config_entry_identity": SiteIdentityManager.identity_fingerprint({"config_entry_id": "entry"}),
            "site_binding_identity": binding["binding_fingerprint"],
            "facility_identity": SiteIdentityManager.identity_fingerprint({"facility_id": "facility"}),
            "contract_identity_scope": SiteIdentityManager.identity_fingerprint({"contract_id": "contract"}),
            "facility_meter_identity_state": "fm",
            "contract_meter_identity_state": "c" * 64,
            "invoice_installation_identity": "im",
            "verification_method": "provider_native_semantic_proof",
            "proof_schema_version": 1,
            "fingerprint_version": "sha256-v1",
            "parser_identity": "parser",
            "normalization_identity": "normalizer",
        }
        package = {
            "package_version": "c4c1a-evidence-package-v1",
            "procedure": "operator_compared_provider_and_invoice_sections",
            "relation": "greenely_meter_id_to_invoice_installation_id",
            "semantic_identity": SiteIdentityManager.identity_fingerprint(semantic),
            "recorded_at": "2026-09-13T10:00:00Z",
        }
        digest = hashlib.sha256(json.dumps(package, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        payload = {
            "site_id": "site", "expected_binding_fingerprint": binding["binding_fingerprint"], "contract_id": "contract",
            "facility_meter_id_fingerprint": "fm", "contract_meter_id_fingerprint_or_state": "c" * 64,
            "invoice_installation_identity_fingerprint": "im", "verification_method": "provider_native_semantic_proof",
            "parser_identity": "parser", "normalization_identity": "normalizer",
            "evidence_reference": "c4c1a-audit-ref-v1:test", "evidence_digest": digest,
            "evidence_package": package, "verification_actor": "forged",
        }

        identity = SiteIdentityManager.__new__(SiteIdentityManager)
        identity.state = {"site_configs": {"site": {"bindings": {"elhandel": dict(binding)}}}}
        identity.saved = []
        identity.authoritative_state = deepcopy(identity.state)

        async def save_identity(state):
            identity.saved.append(state)
            identity.authoritative_state = deepcopy(state)

        async def load_identity():
            return deepcopy(identity.authoritative_state)

        identity.store = SimpleNamespace(async_save=save_identity, async_load=load_identity)
        entry = SimpleNamespace(data={"electricity_provider_config": {"email": "e", "password": "p"}})
        hass.data["elrakning"]["config_entry"] = entry

        class Client:
            def __init__(self, _hass):
                self.index = 0

            async def async_login(self, *_args):
                return None

            async def async_get_facilities(self):
                return [{"id": "facility"}]

            async def async_get_electricity_contracts(self, _facility):
                batch = contract_batches[min(self.index, len(contract_batches) - 1)]
                self.index += 1
                if isinstance(batch, BaseException):
                    raise batch
                return batch

        return hass, identity, entry, payload, Client

    async def test_history_status_is_explicit_allow_list_and_executor_dispatched(self):
        for status in (HISTORY_FOUND, HISTORY_UNKNOWN, None, "unexpected", 7, object()):
            hass = FakeHass(status)
            domain = PseudonymizationDomain(hass, "entry", FakeStorage(status))
            with self.assertRaises(RuntimeError):
                await domain.async_initialize()
            self.assertEqual(domain.store.data, None)
            self.assertEqual(len(hass.executor_calls), 1)

        hass = FakeHass(HISTORY_NONE)
        domain = PseudonymizationDomain(hass, "entry", FakeStorage(HISTORY_NONE))
        key_id = await domain.async_initialize()
        self.assertEqual(domain.key_id, key_id)
        self.assertEqual(len(hass.executor_calls), 1)
        self.assertIsNotNone(domain.store.data)

    async def test_history_query_exception_is_fail_closed(self):
        hass = FakeHass()
        domain = PseudonymizationDomain(hass, "entry", FakeStorage(RuntimeError("sqlite")))
        with self.assertRaisesRegex(RuntimeError, "key_history_unknown"):
            await domain.async_initialize()
        self.assertIsNone(domain.store.data)

    async def test_key_store_load_save_failures_are_fail_closed_and_existing_key_reused(self):
        class FailingStore:
            def __init__(self, loaded=None, save_error=None, load_error=None):
                self.loaded = loaded
                self.save_error = save_error
                self.load_error = load_error
                self.save_calls = 0

            async def async_load(self):
                if self.load_error:
                    raise self.load_error
                return self.loaded

            async def async_save(self, _data):
                self.save_calls += 1
                if self.save_error:
                    raise self.save_error

        hass = FakeHass()
        domain = PseudonymizationDomain(hass, "entry", FakeStorage(HISTORY_NONE))
        failed_store = FailingStore(save_error=RuntimeError("store"))
        domain.store = failed_store
        with self.assertRaises(RuntimeError):
            await domain.async_initialize()
        self.assertIsNone(domain._key)
        self.assertIsNone(domain.key_id)
        self.assertEqual(failed_store.save_calls, 1)

        retry_store = FailingStore()
        domain.store = retry_store
        retry_key_id = await domain.async_initialize()
        self.assertEqual(domain.key_id, retry_key_id)
        self.assertIsNotNone(domain._key)
        self.assertEqual(retry_store.save_calls, 1)

        domain = PseudonymizationDomain(hass, "entry", FakeStorage(HISTORY_NONE))
        domain.store = FailingStore(loaded={"schema_version": 1, "key_material": "00" * 32, "key_id": "id", "identity_domain_id": "entry"})
        self.assertEqual(await domain.async_initialize(), "id")
        self.assertEqual(len(hass.executor_calls), 2)

        domain = PseudonymizationDomain(hass, "entry", FakeStorage(HISTORY_NONE))
        domain.store = FailingStore(load_error=RuntimeError("store"))
        with self.assertRaises(RuntimeError):
            await domain.async_initialize()

    async def test_new_key_is_not_published_until_store_save_completes(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        class BarrierStore:
            async def async_load(self):
                return None

            async def async_save(self, data):
                self.data = data
                entered.set()
                await release.wait()

        store = BarrierStore()
        domain = PseudonymizationDomain(FakeHass(), "entry", FakeStorage(HISTORY_NONE))
        domain.store = store
        task = asyncio.create_task(domain.async_initialize())
        await entered.wait()
        self.assertIsNone(domain._key)
        self.assertIsNone(domain.key_id)
        release.set()
        key_id = await task
        self.assertEqual(domain.key_id, key_id)
        self.assertIsNotNone(domain._key)
        self.assertEqual(store.data["key_id"], key_id)

    async def test_persistence_is_owned_until_shutdown_returns(self):
        started = asyncio.Event()
        release = asyncio.Event()
        inserted = []

        class Storage:
            def insert_external_frame(self, frame, points):
                inserted.append(frame)

        class Hass(FakeHass):
            async def async_add_executor_job(self, function, *args):
                self.executor_calls.append(function)
                started.set()
                await release.wait()
                return function(*args)

        hass = Hass()
        producer = GreenelyInvoiceEconomicsProducer(hass, SimpleNamespace(entry_id="entry"), None, Storage())
        persistence = asyncio.create_task(producer._persist_owned({"frame_id": "f"}, []))
        await started.wait()
        shutdown = asyncio.create_task(producer.async_shutdown())
        await asyncio.sleep(0)
        self.assertFalse(shutdown.done())
        release.set()
        await persistence
        await shutdown
        self.assertEqual(inserted, [{"frame_id": "f"}])
        self.assertFalse(producer._persistence_tasks)

    async def test_persistence_shutdown_before_dispatch_has_zero_writes(self):
        inserted = []

        class Storage:
            def insert_external_frame(self, frame, points):
                inserted.append((frame, points))

        hass = FakeHass()
        producer = GreenelyInvoiceEconomicsProducer(
            hass, SimpleNamespace(entry_id="entry"), None, Storage()
        )
        await producer.async_shutdown()
        self.assertTrue(producer._closed)
        self.assertEqual(inserted, [])
        self.assertEqual(hass.executor_calls, [])
        await producer.async_shutdown()
        self.assertEqual(inserted, [])
        self.assertEqual(hass.executor_calls, [])

    async def test_actual_integration_lifecycle_owns_startup_daily_and_unload(self):
        """Exercise setup/unload through the integration entry points."""
        import homeassistant.components as components
        import homeassistant.components.http as http

        components.frontend = SimpleNamespace(
            async_panel_exists=lambda _hass, _path: False,
            async_register_built_in_panel=lambda *_args, **_kwargs: None,
            async_remove_panel=lambda *_args, **_kwargs: None,
        )
        http.StaticPathConfig = lambda *args, **kwargs: (args, kwargs)

        spec = importlib.util.spec_from_file_location(
            "custom_components.elrakning",
            str(__import__("pathlib").Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"),
            submodule_search_locations=[str(__import__("pathlib").Path(__file__).parents[1] / "custom_components" / "elrakning")],
        )
        integration = importlib.util.module_from_spec(spec)
        sys.modules["custom_components.elrakning"] = integration
        spec.loader.exec_module(integration)

        class Bus:
            def __init__(self):
                self.listeners = []
                self.fired = []

            def async_listen(self, event, callback):
                record = {"event": event, "callback": callback, "active": True}
                self.listeners.append(record)

                def unsubscribe():
                    record["active"] = False

                return unsubscribe

            def async_fire(self, event):
                self.fired.append(event)

        class Http:
            def __init__(self):
                self.static_paths = []
                self.views = []

            async def async_register_static_paths(self, paths):
                self.static_paths.append(paths)

            def register_view(self, view):
                self.views.append(view)

        class Hass(FakeHass):
            def __init__(self):
                super().__init__()
                self.bus = Bus()
                self.http = Http()
                self.services = FakeServices()

        class Entry:
            entry_id = "entry"
            data = {"electricity_provider_config": {}}

        class Coordinator:
            def __init__(self, *_args):
                self.unsubscribed = False
                self.cancelled = False

            async def async_config_entry_first_refresh(self):
                return None

            def async_add_listener(self, _callback):
                return lambda: setattr(self, "unsubscribed", True)

            def async_schedule_midnight_recovery(self):
                return None

            def cancel_midnight_recovery(self):
                self.cancelled = True

        class Manager:
            def __init__(self, *_args):
                self.state = {"configured": False}
                self.configured = False
                self.shutdown = False

            async def async_load(self):
                return None

            async def async_shutdown(self):
                self.shutdown = True

            async def async_migrate_site_locations(self, *_args):
                return None

            async def async_capture_collection_baselines(self):
                return None

            def async_diagnostic(self, *_args, **_kwargs):
                return None

            def set_mapping_changed_callback(self, _callback):
                return None

        class Identity(Manager):
            def collection_site_configs(self):
                return {}

            def active_binding(self, _role):
                return None

            async def async_sync_from_current(self):
                return None

            async def async_prepare_runtime_bindings(self, *_args):
                return None

            async def async_prepare_solar_contexts(self, *_args):
                return None

            @property
            def forecast_collection_targets(self):
                return []

        class Collector(Manager):
            instances = []

            def __init__(self, *_args):
                super().__init__()
                self.storage = object()
                self.forecast_calls = 0
                Collector.instances.append(self)

            async def async_start(self):
                return None

            async def async_capture_forecast_solar(self, **_kwargs):
                self.forecast_calls += 1

            async def async_capture_open_meteo(self, **_kwargs):
                return None

            async def async_capture_weather(self, **_kwargs):
                return None

        class Greenely:
            instances = []

            def __init__(self, *_args):
                self.closed = False
                self.schedule_calls = 0
                Greenely.instances.append(self)

            def async_schedule_capture(self):
                if self.closed:
                    return
                self.schedule_calls += 1

            async def async_shutdown(self):
                self.closed = True

        class Evidence(Manager):
            async def async_startup_catch_up(self):
                return None

            async def async_backfill(self):
                return None

        def no_op(*_args, **_kwargs):
            return None

        hass = Hass()
        entry = Entry()
        tracked = []

        def track_time_change(_hass, callback, **kwargs):
            item = {"callback": callback, "kwargs": kwargs, "active": True}
            tracked.append(item)

            def unsubscribe():
                item["active"] = False

            return unsubscribe

        patches = [
            patch.object(integration, "ElrakningCoordinator", Coordinator),
            patch.object(integration, "ElhandelManager", Manager),
            patch.object(integration, "MeterManager", Manager),
            patch.object(integration, "PowerManager", Manager),
            patch.object(integration, "SiteIdentityManager", Identity),
            patch.object(integration, "CadenceAuditManager", Manager),
            patch.object(integration, "GridManager", Manager),
            patch.object(integration, "CanonicalCollector", Collector),
            patch.object(integration, "GreenelyInvoiceEconomicsProducer", Greenely),
            patch.object(integration, "SolarForecastManager", Manager),
            patch.object(integration, "SolarWeatherManager", Manager),
            patch.object(integration, "SolarPvgisManager", Manager),
            patch.object(integration, "SolarOpenMeteoManager", Manager),
            patch.object(integration, "SolarShadowManager", Manager),
            patch.object(integration, "SolarEvidenceManager", Evidence),
            patch.object(integration, "async_register_websocket_commands", no_op),
            patch.object(integration, "async_register_cadence_audit_websocket", no_op),
            patch.object(integration, "async_register_eon_handoff_views", no_op),
            patch.object(integration, "async_track_time_change", track_time_change),
        ]
        for item in patches:
            item.start()
        try:
            await integration.async_setup_entry(hass, entry)
            self.assertEqual(len(Greenely.instances), 1)
            self.assertEqual(len(Collector.instances), 1)
            self.assertEqual(Collector.instances[0].forecast_calls, 1)
            producer = Greenely.instances[0]
            self.assertEqual(producer.schedule_calls, 1)
            self.assertEqual(len(tracked), 4)
            cadence_keys = {
                (item["kwargs"]["hour"], tuple(item["kwargs"]["minute"])
                 if isinstance(item["kwargs"]["minute"], list) else item["kwargs"]["minute"],
                 item["kwargs"]["second"])
                for item in tracked
            }
            self.assertEqual(
                cadence_keys,
                {(0, 5, 0), (0, 0, 0), (None, (0, 15, 30, 45), 30), (None, 5, 0)},
            )
            economics_schedule = next(item for item in tracked if item["kwargs"]["hour"] == 0 and item["kwargs"]["minute"] == 5)
            economics_schedule["callback"](None)
            self.assertEqual(producer.schedule_calls, 2)
            first_handler = hass.services.handlers[("elrakning", SERVICE_PROVISION)]
            result = await integration.async_unload_entry(hass, entry)
            self.assertTrue(result)
            self.assertTrue(entry.runtime_data.cancelled)
            self.assertIsNot(entry.runtime_data, sys.modules["custom_components.elrakning.coordinator"])
            self.assertFalse(economics_schedule["active"])
            self.assertTrue(producer.closed)
            self.assertNotIn(("elrakning", SERVICE_PROVISION), hass.services.handlers)
            economics_schedule["callback"](None)
            self.assertEqual(producer.schedule_calls, 2)

            await integration.async_setup_entry(hass, entry)
            self.assertEqual(len(Greenely.instances), 2)
            self.assertEqual(len(Collector.instances), 2)
            current_producer = Greenely.instances[1]
            self.assertEqual(current_producer.schedule_calls, 1)
            self.assertNotEqual(first_handler, hass.services.handlers[("elrakning", SERVICE_PROVISION)])
            active_schedules = [item for item in tracked if item["active"]]
            self.assertEqual(len(active_schedules), 4)
            economics_schedule["callback"](None)
            self.assertEqual(producer.schedule_calls, 2)
            current_schedule = next(
                item for item in active_schedules
                if item["kwargs"]["hour"] == 0 and item["kwargs"]["minute"] == 5
            )
            current_schedule["callback"](None)
            self.assertEqual(current_producer.schedule_calls, 2)
            self.assertIsNot(entry.runtime_data, sys.modules["custom_components.elrakning.coordinator"])
            await integration.async_unload_entry(hass, entry)
            self.assertTrue(current_producer.closed)
        finally:
            for item in reversed(patches):
                item.stop()

    async def test_proof_service_rejects_missing_unknown_and_non_admin_users(self):
        hass = FakeHass()
        hass.services = FakeServices()

        class Identity:
            def collection_site_configs(self):
                return {}

        await async_register_proof_service(hass, Identity(), SimpleNamespace(data={}))
        handler = hass.services.handlers[("elrakning", SERVICE_PROVISION)]
        for user_id in (None, "unknown"):
            call = SimpleNamespace(context=SimpleNamespace(user_id=user_id), data={})
            with self.assertRaises(PermissionError):
                await handler(call)
        hass.user = SimpleNamespace(is_admin=False)
        with self.assertRaises(PermissionError):
            await handler(SimpleNamespace(context=SimpleNamespace(user_id="known"), data={}))

    async def test_proof_service_admin_uses_runtime_entry_and_actor_context(self):
        hass = FakeHass()
        hass.services = FakeServices()
        hass.user = SimpleNamespace(is_admin=True)

        class Identity:
            def collection_site_configs(self):
                return {"site": {"bindings": {"elhandel": {"provider": "other"}}}}

        await async_register_proof_service(hass, Identity(), SimpleNamespace(data={}))
        handler = hass.services.handlers[("elrakning", SERVICE_PROVISION)]
        call = SimpleNamespace(context=SimpleNamespace(user_id="known"), data={"site_id": "site", "verification_actor": "forged"})
        with self.assertRaisesRegex(ValueError, "greenely_binding_required"):
            await handler(call)

    async def test_registered_service_t1_and_t2_relation_validation(self):
        valid = {"id": "contract", "facility_id": "facility"}
        cases = [
            ([[valid], [valid]], None),
            ([[{"id": "contract", "facility_id": "other"}], [valid]], "contract_relation_not_unique"),
            ([[], [valid]], "contract_relation_not_unique"),
            ([[valid], [{"id": "contract", "facility_id": "other"}]], "provider_relation_changed"),
            ([[valid], []], "provider_relation_changed"),
            ([[valid], [valid, valid]], "provider_relation_changed"),
            ([[valid], RuntimeError("lookup")], "lookup"),
        ]
        for batches, expected in cases:
            hass, identity, entry, payload, client = self._service_fixture(batches)
            with patch("custom_components.elrakning.elhandel.providers.greenely_invoice_economics.GreenelyClient", client):
                await async_register_proof_service(hass, identity, entry)
                handler = hass.services.handlers[("elrakning", SERVICE_PROVISION)]
                if expected:
                    with self.assertRaisesRegex((ValueError, RuntimeError), expected):
                        await handler(SimpleNamespace(context=SimpleNamespace(user_id="known"), data=payload))
                    self.assertEqual(identity.saved, [])
                else:
                    await handler(SimpleNamespace(context=SimpleNamespace(user_id="known"), data=payload))
                    proof = identity.saved[0]["site_configs"]["site"]["greenely_meter_to_invoice_installation_proof"]
                    self.assertEqual(proof["verification_actor"], "known")
                    self.assertEqual(proof["verification_actor_source"], "authenticated_home_assistant_service_context")

    async def test_proof_provisioning_fails_when_authoritative_binding_changes_after_save(self):
        valid = {"id": "contract", "facility_id": "facility"}
        hass, identity, entry, payload, client = self._service_fixture([[valid], [valid]])
        original_save = identity.store.async_save

        async def save_then_replace(state):
            await original_save(state)
            identity.authoritative_state["site_configs"]["site"]["bindings"]["elhandel"] = {
                "provider": "greenely",
                "config_entry_id": "entry",
                "facility_id": "replacement",
            }

        identity.store.async_save = save_then_replace
        with patch("custom_components.elrakning.elhandel.providers.greenely_invoice_economics.GreenelyClient", client):
            await async_register_proof_service(hass, identity, entry)
            handler = hass.services.handlers[("elrakning", SERVICE_PROVISION)]
            with self.assertRaisesRegex(ValueError, "stale_binding"):
                await handler(SimpleNamespace(context=SimpleNamespace(user_id="known"), data=payload))

        self.assertEqual(len(identity.saved), 1)

    async def test_proof_provisioning_succeeds_when_authoritative_binding_is_unchanged(self):
        valid = {"id": "contract", "facility_id": "facility"}
        hass, identity, entry, payload, client = self._service_fixture([[valid], [valid]])
        with patch("custom_components.elrakning.elhandel.providers.greenely_invoice_economics.GreenelyClient", client):
            await async_register_proof_service(hass, identity, entry)
            handler = hass.services.handlers[("elrakning", SERVICE_PROVISION)]
            await handler(SimpleNamespace(context=SimpleNamespace(user_id="known"), data=payload))

        self.assertEqual(len(identity.saved), 1)
        self.assertEqual(
            identity.saved[0]["site_configs"]["site"]["greenely_meter_to_invoice_installation_proof"]["verification_state"],
            "EXPLICITLY_VERIFIED",
        )

    async def test_registered_service_rejects_digest_and_evidence_failures(self):
        valid = {"id": "contract", "facility_id": "facility"}
        hass, identity, entry, payload, client = self._service_fixture([[valid], [valid]])
        invalid_payloads = [
            (dict(payload, evidence_digest="0" * 64), "evidence_digest_mismatch"),
            (dict(payload, evidence_digest=""), "evidence_digest_invalid"),
            (dict(payload, evidence_digest="not-a-digest"), "evidence_digest_invalid"),
            (dict(payload, evidence_package={"contract_version": 2}), "evidence_package_invalid"),
            (dict(payload, evidence_reference="unsafe"), "evidence_reference_invalid"),
        ]
        with patch("custom_components.elrakning.elhandel.providers.greenely_invoice_economics.GreenelyClient", client):
            await async_register_proof_service(hass, identity, entry)
            handler = hass.services.handlers[("elrakning", SERVICE_PROVISION)]
            for value, error in invalid_payloads:
                with self.assertRaisesRegex(ValueError, error):
                    await handler(SimpleNamespace(context=SimpleNamespace(user_id="known"), data=value))
        self.assertEqual(identity.saved, [])

    async def test_registered_service_rejects_missing_digest_and_package_fields(self):
        valid = {"id": "contract", "facility_id": "facility"}
        hass, identity, entry, payload, client = self._service_fixture([[valid], [valid]])
        invalid_payloads = [
            (dict(payload, evidence_digest=None), "evidence_digest_invalid"),
            (dict(payload, evidence_digest=" " ), "evidence_digest_invalid"),
            (dict(payload, evidence_package={"contract_version": 1, "facility": "h"}), "evidence_package_invalid"),
            (dict(payload, evidence_reference="https://example.invalid/evidence"), "evidence_reference_invalid"),
        ]
        with patch("custom_components.elrakning.elhandel.providers.greenely_invoice_economics.GreenelyClient", client):
            await async_register_proof_service(hass, identity, entry)
            handler = hass.services.handlers[("elrakning", SERVICE_PROVISION)]
            for value, error in invalid_payloads:
                with self.assertRaisesRegex((KeyError, ValueError), error):
                    await handler(SimpleNamespace(context=SimpleNamespace(user_id="known"), data=value))
        self.assertEqual(identity.saved, [])

    async def test_registration_is_idempotent_and_unload_removes_service(self):
        hass = FakeHass()
        hass.services = FakeServices()
        identity = SimpleNamespace(collection_site_configs=lambda: {})
        entry = SimpleNamespace(data={})
        await async_register_proof_service(hass, identity, entry)
        first = hass.services.handlers[("elrakning", SERVICE_PROVISION)]
        await async_register_proof_service(hass, identity, entry)
        self.assertIs(hass.services.handlers[("elrakning", SERVICE_PROVISION)], first)
        hass.services.async_remove("elrakning", SERVICE_PROVISION)
        self.assertNotIn(("elrakning", SERVICE_PROVISION), hass.services.handlers)

    async def test_schedule_capture_has_one_owned_task_and_shutdown_invalidates_it(self):
        hass = FakeHass()
        producer = GreenelyInvoiceEconomicsProducer(hass, SimpleNamespace(entry_id="entry"), None, None)
        started = asyncio.Event()

        async def capture():
            started.set()
            await asyncio.Event().wait()

        producer.async_capture = capture
        producer.async_schedule_capture()
        producer.async_schedule_capture()
        await started.wait()
        task = producer._capture_task
        await producer.async_shutdown()
        self.assertTrue(producer._closed)
        self.assertTrue(task.done())
        producer.async_schedule_capture()
        self.assertIs(producer._capture_task, task)

    async def _capture_fixture(self, identity=None, storage=None, pdf_event=None, pdf_release=None):
        hass = FakeHass()
        identity = identity or CaptureIdentity()
        storage = storage or CaptureStorage()
        entry = SimpleNamespace(entry_id="entry", data={"electricity_provider_config": {"email": "e", "password": "p"}})
        producer = GreenelyInvoiceEconomicsProducer(hass, entry, identity, storage)
        producer._domains["entry"] = CaptureDomain()
        client = lambda _hass: CaptureClient(_hass, pdf_event, pdf_release)
        module = "custom_components.elrakning.elhandel.providers.greenely_invoice_economics"
        return hass, identity, storage, producer, client, module

    async def test_capture_path_dedups_revises_and_separates_variable_fixed(self):
        hass, identity, storage, producer, client, module = await self._capture_fixture()

        def parse(value):
            if value == "pdf text":
                return {"installation_sections": [{"installation_id": "install", "text": "section"}]}
            return {"period_start": "2026-07-01", "period_end": "2026-07-31", "variable_cost": {"rate_ore_per_kwh_ex_vat": 17}, "fixed_fee": {"rate_ex_vat_sek_per_month": 31.2}}

        def extract_pdf(_pdf):
            return ("pdf text", None)

        def parse_text(value):
            return parse(value)

        with patch(f"{module}.GreenelyClient", client), patch(f"{module}._parse_invoice_pdf", new=extract_pdf), patch(f"{module}.parse_greenely_invoice_text", new=parse_text):
            first = await producer.async_capture()
            second = await producer.async_capture()
        self.assertEqual(first["captured"], 2)
        self.assertEqual(second["deduplicated"], 2)
        self.assertEqual(len(storage.calls), 2)
        self.assertEqual({call[0]["logical_role"] for call in storage.calls}, {"greenely.invoice_economics.v1"})
        self.assertEqual({call[1][0]["point"]["component_role"] for call in storage.calls}, {"economic.provider.import.variable", "economic.provider.fixed.subscription"})
        self.assertGreaterEqual(len(hass.executor_calls), 8)
        storage_executor_names = {
            getattr(function, "__name__", None)
            for function in hass.executor_calls
            if getattr(function, "__self__", None) is storage
        }
        self.assertTrue({"ensure_source_generation", "latest_external_frame_snapshot", "insert_external_frame"}.issubset(storage_executor_names))
        executor_names = {getattr(function, "__name__", None) for function in hass.executor_calls}
        self.assertIn("extract_pdf", executor_names)
        self.assertIn("parse_text", executor_names)

    async def test_capture_path_occurrence_revision_and_generation_boundaries(self):
        hass, identity, storage, producer, _client, module = await self._capture_fixture()
        state = {"occurrence": "ocr-1", "variable": 17}

        class MutableClient:
            def __init__(self, _hass):
                pass

            async def async_login(self, *_args):
                return None

            async def async_get_electricity_contracts(self, _facility):
                return [{"id": "contract", "facility_id": "facility"}]

            async def async_get_invoices(self, _contract):
                return [{"invoice_date": "2026-08-01", "due_date": "2026-08-15", "month": "2026-07", "ocr_number": state["occurrence"]}]

            async def async_get_invoice_pdf(self, _contract, _invoice):
                return b"pdf"

        def parse(value):
            if value == "pdf text":
                return {"installation_sections": [{"installation_id": "install", "text": "section"}]}
            return {"period_start": "2026-07-01", "period_end": "2026-07-31", "variable_cost": {"rate_ore_per_kwh_ex_vat": state["variable"]}}

        with patch(f"{module}.GreenelyClient", MutableClient), patch(f"{module}._parse_invoice_pdf", return_value=("pdf text", None)), patch(f"{module}.parse_greenely_invoice_text", side_effect=parse):
            first = await producer.async_capture()
            same = await producer.async_capture()
            state["variable"] = 19
            revised = await producer.async_capture()
            state["occurrence"] = "ocr-2"
            new_occurrence = await producer.async_capture()
            identity.binding["binding_fingerprint"] = "binding-2"
            identity.proof.update(proof_fingerprint="proof-2", proof_semantic_identity="proof-semantic-2")
            new_generation = await producer.async_capture()

        self.assertEqual(first["captured"], 1)
        self.assertEqual(same["deduplicated"], 1)
        self.assertEqual(revised["captured"], 1)
        self.assertEqual(new_occurrence["captured"], 1)
        self.assertEqual(new_generation["captured"], 1)
        self.assertEqual(len(storage.calls), 4)
        frames = [frame for frame, _points in storage.calls]
        self.assertEqual(frames[1]["revision"], 2)
        self.assertEqual(frames[1]["supersedes_frame_id"], frames[0]["frame_id"])
        self.assertEqual(frames[2]["revision"], 1)
        self.assertIsNone(frames[2]["supersedes_frame_id"])
        self.assertEqual(frames[3]["revision"], 1)
        self.assertIsNone(frames[3]["supersedes_frame_id"])
        self.assertNotEqual(frames[2]["source_generation_id"], frames[3]["source_generation_id"])

    async def test_capture_path_discards_binding_change_before_persist(self):
        started = asyncio.Event()
        release = asyncio.Event()
        hass, identity, storage, producer, client, module = await self._capture_fixture(pdf_event=started, pdf_release=release)

        def parse(value):
            if value == "pdf text":
                return {"installation_sections": [{"installation_id": "install", "text": "section"}]}
            return {"period_start": "2026-07-01", "period_end": "2026-07-31", "variable_cost": {"rate_ore_per_kwh_ex_vat": 17}}

        task = None
        with patch(f"{module}.GreenelyClient", client), patch(f"{module}._parse_invoice_pdf", return_value=("pdf text", None)), patch(f"{module}.parse_greenely_invoice_text", side_effect=parse):
            task = asyncio.create_task(producer.async_capture())
            await started.wait()
            identity.binding["binding_fingerprint"] = "changed"
            release.set()
            result = await task
        self.assertEqual(result["captured"], 0)
        self.assertEqual(storage.calls, [])

    async def test_capture_path_discards_collection_disable_before_persist(self):
        started = asyncio.Event()
        release = asyncio.Event()
        hass, identity, storage, producer, client, module = await self._capture_fixture(pdf_event=started, pdf_release=release)

        def parse(value):
            if value == "pdf text":
                return {"installation_sections": [{"installation_id": "install", "text": "section"}]}
            return {"period_start": "2026-07-01", "period_end": "2026-07-31", "variable_cost": {"rate_ore_per_kwh_ex_vat": 17}}

        with patch(f"{module}.GreenelyClient", client), patch(f"{module}._parse_invoice_pdf", return_value=("pdf text", None)), patch(f"{module}.parse_greenely_invoice_text", side_effect=parse):
            task = asyncio.create_task(producer.async_capture())
            await started.wait()
            identity.mutable = False
            release.set()
            result = await task
        self.assertEqual(result["captured"], 0)
        self.assertEqual(storage.calls, [])

    async def test_capture_discards_provider_relation_change_before_persist(self):
        started = asyncio.Event()
        release = asyncio.Event()
        hass, identity, storage, producer, _client, module = await self._capture_fixture()

        class RelationClient(CaptureClient):
            def __init__(self, hass_instance):
                super().__init__(hass_instance, started, release)
                self.relation = {"id": "contract", "facility_id": "facility"}

            async def async_get_electricity_contracts(self, _facility):
                return [dict(self.relation)]

        client = RelationClient(hass)

        def parse(value):
            if value == "pdf text":
                return {"installation_sections": [{"installation_id": "install", "text": "section"}]}
            return {"period_start": "2026-07-01", "period_end": "2026-07-31", "variable_cost": {"rate_ore_per_kwh_ex_vat": 17}}

        with patch(f"{module}.GreenelyClient", lambda _hass: client), patch(f"{module}._parse_invoice_pdf", return_value=("pdf text", None)), patch(f"{module}.parse_greenely_invoice_text", side_effect=parse):
            task = asyncio.create_task(producer.async_capture())
            await started.wait()
            client.relation = {"id": "contract-replaced", "facility_id": "facility"}
            release.set()
            result = await task
        self.assertEqual(result["captured"], 0)
        self.assertEqual(storage.calls, [])

    async def _capture_with_provider_relation_batches(self, batches):
        hass, _identity, storage, producer, _client, module = await self._capture_fixture()

        class RelationClient:
            def __init__(self, _hass):
                self.index = 0

            async def async_login(self, *_args):
                return None

            async def async_get_electricity_contracts(self, _facility):
                batch = batches[min(self.index, len(batches) - 1)]
                self.index += 1
                if isinstance(batch, BaseException):
                    raise batch
                return batch

            async def async_get_invoices(self, _contract):
                return [{"invoice_date": "2026-08-01", "due_date": "2026-08-15", "month": "2026-07", "ocr_number": "ocr-1"}]

            async def async_get_invoice_pdf(self, _contract, _invoice):
                return b"pdf"

        def parse(value):
            if value == "pdf text":
                return {"installation_sections": [{"installation_id": "install", "text": "section"}]}
            return {"period_start": "2026-07-01", "period_end": "2026-07-31", "variable_cost": {"rate_ore_per_kwh_ex_vat": 17}}

        with patch(f"{module}.GreenelyClient", RelationClient), patch(f"{module}._parse_invoice_pdf", return_value=("pdf text", None)), patch(f"{module}.parse_greenely_invoice_text", side_effect=parse):
            result = await producer.async_capture()
        return result, storage

    async def test_capture_discards_missing_provider_relation_at_t2(self):
        result, storage = await self._capture_with_provider_relation_batches(
            [[{"id": "contract", "facility_id": "facility"}], []]
        )
        self.assertEqual(result["captured"], 0)
        self.assertEqual(storage.calls, [])

    async def test_capture_discards_wrong_facility_provider_relation_at_t2(self):
        result, storage = await self._capture_with_provider_relation_batches(
            [[{"id": "contract", "facility_id": "facility"}], [{"id": "contract", "facility_id": "other"}]]
        )
        self.assertEqual(result["captured"], 0)
        self.assertEqual(storage.calls, [])

    async def test_capture_discards_ambiguous_provider_relation_at_t2(self):
        result, storage = await self._capture_with_provider_relation_batches(
            [[{"id": "contract", "facility_id": "facility"}], [{"id": "contract", "facility_id": "facility"}, {"id": "contract", "facility_id": "facility"}]]
        )
        self.assertEqual(result["captured"], 0)
        self.assertEqual(storage.calls, [])

    async def test_capture_discards_provider_relation_lookup_failure_at_t2(self):
        result, storage = await self._capture_with_provider_relation_batches(
            [[{"id": "contract", "facility_id": "facility"}], GreenelyError("provider unavailable")]
        )
        self.assertEqual(result["captured"], 0)
        self.assertEqual(storage.calls, [])

    async def test_capture_discards_malformed_provider_relation_at_t2(self):
        result, storage = await self._capture_with_provider_relation_batches(
            [[{"id": "contract", "facility_id": "facility"}], [{"id": "contract"}]]
        )
        self.assertEqual(result["captured"], 0)
        self.assertEqual(storage.calls, [])

    async def test_capture_accepts_unchanged_provider_relation_at_t2(self):
        result, storage = await self._capture_with_provider_relation_batches(
            [[{"id": "contract", "facility_id": "facility"}], [{"id": "contract", "facility_id": "facility"}]]
        )
        self.assertEqual(result["captured"], 1)
        self.assertEqual(len(storage.calls), 1)

    async def _assert_stale_capture_discards(self, mutate):
        started = asyncio.Event()
        release = asyncio.Event()
        hass, identity, storage, producer, client, module = await self._capture_fixture(pdf_event=started, pdf_release=release)

        def parse(value):
            if value == "pdf text":
                return {"installation_sections": [{"installation_id": "install", "text": "section"}]}
            return {"period_start": "2026-07-01", "period_end": "2026-07-31", "variable_cost": {"rate_ore_per_kwh_ex_vat": 17}}

        with patch(f"{module}.GreenelyClient", client), patch(f"{module}._parse_invoice_pdf", return_value=("pdf text", None)), patch(f"{module}.parse_greenely_invoice_text", side_effect=parse):
            task = asyncio.create_task(producer.async_capture())
            await started.wait()
            mutate(identity, producer)
            release.set()
            result = await task
        self.assertEqual(result["captured"], 0)
        self.assertEqual(storage.calls, [])

    async def test_capture_discards_proof_identity_change(self):
        await self._assert_stale_capture_discards(lambda identity, _producer: identity.proof.update(proof_fingerprint="changed"))

    async def test_capture_discards_key_domain_change(self):
        await self._assert_stale_capture_discards(lambda _identity, producer: setattr(producer._domains["entry"], "key_id", "changed"))

    async def test_capture_discards_timezone_change(self):
        await self._assert_stale_capture_discards(lambda identity, _producer: setattr(identity, "timezone", "UTC"))

    async def test_capture_discards_lifecycle_close_before_persist(self):
        await self._assert_stale_capture_discards(lambda _identity, producer: setattr(producer, "_closed", True))


if __name__ == "__main__":
    unittest.main()
