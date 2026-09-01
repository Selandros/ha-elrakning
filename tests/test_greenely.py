import asyncio
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)

install_elrakning_package_stub()
install_homeassistant_stubs()
install_optional_dependency_stubs()

from custom_components.elrakning.const import DOMAIN, ELECTRICITY_PROVIDER_CONFIG_DATA_KEY, ELECTRICITY_PROVIDER_CONFIG_KEY
from custom_components.elrakning.elhandel.providers.greenely_client import (
    GreenelyClient as ProviderGreenelyClient,
    GreenelyError as ProviderGreenelyError,
    _sanitize_contract,
    _sanitize_invoice,
)
from custom_components.elrakning.elhandel import models as electricity_models
from custom_components.elrakning.elhandel.manager import ElhandelManager
from custom_components.elrakning.elhandel.lifecycle import LifecycleManager
from custom_components.elrakning.elhandel.providers.greenely import GreenelyProvider
from custom_components.elrakning.elhandel.providers.greenely_invoice import (
    GreenelyInvoiceError,
    GreenelyInvoiceProcessor,
)
from custom_components.elrakning.elhandel.storage import StorageManager
from custom_components.elrakning.elhandel.storage import _sanitize_storage_state, record_from_state
from custom_components.elrakning.websocket import (
    _electricity_provider_state,
    _safe_key_name,
    _summarize_consumption,
    websocket_electricity_provider_source_data,
)

GreenelyClient = ProviderGreenelyClient
GreenelyError = ProviderGreenelyError
_extract_facilities = __import__(
    "custom_components.elrakning.elhandel.providers.greenely_client", fromlist=["_extract_facilities"]
)._extract_facilities


def test_extract_facilities_from_data():
    facilities = [{"id": "one"}]
    assert _extract_facilities({"data": facilities}) == facilities


def test_extract_facilities_from_facilities_fallback():
    facilities = [{"id": "one"}]
    assert _extract_facilities({"facilities": facilities}) == facilities


def test_extract_facilities_from_raw_list():
    facilities = [{"id": "one"}]
    assert _extract_facilities(facilities) == facilities


def test_extract_facilities_rejects_invalid_format():
    assert _extract_facilities({"data": {"id": "one"}}) is None


class _Response:
    def __init__(self, status, payload=None):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def json(self, content_type=None):
        return self._payload


class _Session:
    def __init__(self, response):
        self.response = response

    def post(self, *args, **kwargs):
        return self.response


class GreenelyClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_rejects_401_and_403_as_invalid_auth(self):
        for status in (401, 403):
            client = object.__new__(GreenelyClient)
            client._session = _Session(_Response(status))
            with self.assertRaises(GreenelyError) as error:
                await client.async_login("user@example.test", "password")
            self.assertEqual(error.exception.code, "invalid_auth")


    async def test_consumption_http_200_and_empty_data(self):
        client = object.__new__(GreenelyClient)
        client._jwt = "jwt"
        client._session = _ConsumptionSession(_Response(200, {"data": []}))
        payload = await client.async_get_consumption(
            "facility", date(2026, 8, 20), date(2026, 8, 21)
        )
        self.assertEqual(payload, {"data": []})
        self.assertIsNone(_summarize_consumption(payload))

    async def test_consumption_rejects_401_and_403(self):
        for status in (401, 403):
            client = object.__new__(GreenelyClient)
            client._jwt = "jwt"
            client._session = _ConsumptionSession(_Response(status))
            with self.assertRaises(GreenelyError) as error:
                await client.async_get_consumption(
                    "facility", date(2026, 8, 20), date(2026, 8, 21)
                )
            self.assertEqual(error.exception.code, "invalid_auth")


class GreenelyProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_creates_config_for_selected_facility(self):
        client = SimpleNamespace(
            async_login=AsyncMock(),
            async_get_facilities=AsyncMock(return_value=[{"id": "facility-1", "name": "Home"}]),
        )

        with patch(
            "custom_components.elrakning.elhandel.providers.greenely.GreenelyClient",
            return_value=client,
        ):
            result = await GreenelyProvider(_Hass()).async_create_config(
                "user@example.test", "password", "facility-1"
            )

        self.assertEqual(
            result["config"],
            {"email": "user@example.test", "password": "password", "facility_id": "facility-1"},
        )
        self.assertEqual(result["facility"], {"id": "facility-1", "name": "Home"})

    async def test_provider_rejects_invalid_credentials_before_login(self):
        client = SimpleNamespace(async_login=AsyncMock())

        with patch(
            "custom_components.elrakning.elhandel.providers.greenely.GreenelyClient",
            return_value=client,
        ):
            with self.assertRaises(GreenelyError) as raised:
                await GreenelyProvider(_Hass()).async_create_config("", "password", "facility-1")

        self.assertEqual(raised.exception.code, "invalid_auth")
        client.async_login.assert_not_awaited()

    async def test_provider_rejects_unknown_facility(self):
        client = SimpleNamespace(
            async_login=AsyncMock(),
            async_get_facilities=AsyncMock(return_value=[{"id": "other-facility"}]),
        )

        with patch(
            "custom_components.elrakning.elhandel.providers.greenely.GreenelyClient",
            return_value=client,
        ):
            with self.assertRaises(GreenelyError) as raised:
                await GreenelyProvider(_Hass()).async_create_config(
                    "user@example.test", "password", "facility-1"
                )

        self.assertEqual(raised.exception.code, "unexpected_response")

    async def test_provider_forwards_facilities_contracts_invoices_and_consumption(self):
        facilities = [{"id": "facility-1"}]
        contracts = [{"id": "contract-1"}]
        invoices = [{"invoice_date": "2026-08-01"}]
        facility_invoices = {"contracts": contracts, "invoices": invoices, "failed_contracts": []}
        consumption = {"data": [{"value": 1.2}]}
        client = SimpleNamespace(
            async_login=AsyncMock(),
            async_get_facilities=AsyncMock(return_value=facilities),
            async_get_electricity_contracts=AsyncMock(return_value=contracts),
            async_get_invoices=AsyncMock(return_value=invoices),
            async_get_facility_invoices=AsyncMock(return_value=facility_invoices),
            async_get_consumption=AsyncMock(return_value=consumption),
            async_get_invoice_pdf=AsyncMock(return_value=b"%PDF-test"),
        )

        with patch(
            "custom_components.elrakning.elhandel.providers.greenely.GreenelyClient",
            return_value=client,
        ):
            provider = GreenelyProvider(_Hass())
            await provider.async_login("user@example.test", "password")
            self.assertEqual(await provider.async_get_facilities(), facilities)
            self.assertEqual(await provider.async_get_electricity_contracts("facility-1"), contracts)
            self.assertEqual(await provider.async_get_invoices("contract-1"), invoices)
            self.assertEqual(await provider.async_get_facility_invoices("facility-1"), facility_invoices)
            self.assertEqual(
                await provider.async_get_consumption(
                    "facility-1", date(2026, 8, 1), date(2026, 8, 2)
                ),
                consumption,
            )

        client.async_login.assert_awaited_once_with("user@example.test", "password")
        client.async_get_consumption.assert_awaited_once_with(
            "facility-1", date(2026, 8, 1), date(2026, 8, 2), "hourly"
        )

    async def test_provider_preserves_client_errors(self):
        error = GreenelyError("invalid_auth")
        client = SimpleNamespace(async_login=AsyncMock(side_effect=error))

        with patch(
            "custom_components.elrakning.elhandel.providers.greenely.GreenelyClient",
            return_value=client,
        ):
            provider = GreenelyProvider(_Hass())
            with self.assertRaises(GreenelyError) as raised:
                await provider.async_login("user@example.test", "password")

        self.assertIs(raised.exception, error)


class GreenelyInvoiceProcessorTests(unittest.IsolatedAsyncioTestCase):
    async def test_processor_preserves_summary_tariff_and_processing_inputs(self):
        parsed = {
            "agreement_name": "Kvartsprisavtal",
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "spot": {"rate_ore_per_kwh_ex_vat": 29.93},
            "variable_cost": {"rate_ore_per_kwh_ex_vat": 17.0},
            "fixed_fee": {
                "amount_ex_vat_sek": 100.0,
                "amount_incl_vat_sek": 125.0,
                "rate_ex_vat_sek_per_month": 100.0,
            },
            "credit": {"used_sek": None},
            "gross_charge_sek": None,
            "warnings": [],
        }
        provider = SimpleNamespace(async_get_invoice_pdf=AsyncMock(return_value=b"pdf"))
        with patch(
            "custom_components.elrakning.elhandel.providers.greenely_invoice.extract_pdf_text",
            return_value=("invoice text", 1),
        ), patch(
            "custom_components.elrakning.elhandel.providers.greenely_invoice.parse_greenely_invoice_diagnostics",
            return_value=(parsed, {"matched_fields": []}, "excerpt"),
        ):
            result = await GreenelyInvoiceProcessor(provider).async_process(
                "contract-1", "invoice-1", 12.0
            )

        self.assertEqual(result["parsed"], parsed)
        self.assertEqual(result["debug_text_excerpt"], "excerpt")
        self.assertEqual(result["diagnostics"]["pdf_pages"], 1)
        self.assertEqual(result["summary"]["agreement_name"], "Kvartsprisavtal")
        self.assertEqual(result["summary"]["tariff"]["variable_cost_ore_per_kwh_ex_vat"], 17.0)

    async def test_processor_preserves_parser_error_and_stage(self):
        provider = SimpleNamespace(async_get_invoice_pdf=AsyncMock(return_value=b"pdf"))
        with patch(
            "custom_components.elrakning.elhandel.providers.greenely_invoice.extract_pdf_text",
            side_effect=RuntimeError("invalid_pdf"),
        ):
            with self.assertRaises(GreenelyInvoiceError) as raised:
                await GreenelyInvoiceProcessor(provider).async_process(
                    "contract-1", "invoice-1", None
                )

        self.assertEqual(raised.exception.code, "invalid_pdf")
        self.assertEqual(raised.exception.stage, "pdf_extract")


class _ConsumptionSession(_Session):
    def get(self, *args, **kwargs):
        return self.response


class _Store:
    def __init__(self, data=None):
        self.data = data

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data


class _Bus:
    def __init__(self):
        self.events = []

    def async_fire(self, event):
        self.events.append(event)


class _ConfigEntries:
    @staticmethod
    def async_update_entry(entry, data):
        entry.data = data


class _Hass:
    def __init__(self):
        self.bus = _Bus()
        self.config_entries = _ConfigEntries()
        self.data = {DOMAIN: {}}

    def async_create_task(self, coroutine):
        return asyncio.create_task(coroutine)


class ChartPreferencesTests(unittest.IsolatedAsyncioTestCase):
    async def test_ui_preference_get_is_pure_and_domain_updates_are_atomic(self):
        manager = object.__new__(ElhandelManager)
        manager.chart_preferences_store = _Store()

        self.assertEqual(await manager.async_get_price_comparison("user-a"), {"electricity": True, "grid": False})
        self.assertIsNone(manager.chart_preferences_store.data)

        await manager.async_update_ui_preferences("user-a", {"price_comparison": {"electricity": False, "grid": True}})
        await manager.async_update_ui_preferences("user-a", {"phase_history_visible": {"l2": False}})
        await manager.async_update_ui_preferences("user-a", {"chart_layers": {"average": False}})
        preferences = await manager.async_get_ui_preferences("user-a")
        self.assertEqual(preferences["price_comparison"], {"electricity": False, "grid": True})
        self.assertEqual(preferences["phase_history_visible"], {"l1": True, "l2": False, "l3": True})
        self.assertFalse(preferences["chart_layers"]["average"])

    async def test_price_comparison_defaults_and_persists_per_user(self):
        manager = object.__new__(ElhandelManager)
        manager.chart_preferences_store = _Store()

        first = await manager.async_get_price_comparison("user-a")
        self.assertEqual(first, {"electricity": True, "grid": False})
        for expected in (
            {"electricity": False, "grid": False},
            {"electricity": True, "grid": False},
            {"electricity": False, "grid": True},
            {"electricity": True, "grid": True},
        ):
            updated = await manager.async_set_price_comparison("user-a", expected)
            self.assertEqual(updated, expected)
            self.assertEqual(await manager.async_get_price_comparison("user-a"), expected)
        self.assertEqual(
            await manager.async_get_price_comparison("user-b"),
            {"electricity": True, "grid": False},
        )

    async def test_price_comparison_preserves_saved_grid_choice_when_data_is_unavailable(self):
        manager = object.__new__(ElhandelManager)
        manager.chart_preferences_store = _Store()

        await manager.async_set_price_comparison("user-a", {"grid": True})
        self.assertTrue((await manager.async_get_price_comparison("user-a"))["grid"])

    async def test_phase_visibility_defaults_and_persists_all_off_state(self):
        manager = object.__new__(ElhandelManager)
        manager.chart_preferences_store = _Store()

        self.assertEqual(
            await manager.async_get_phase_history_visible("user-a"),
            {"l1": True, "l2": True, "l3": True},
        )
        updated = await manager.async_set_phase_history_visible(
            "user-a", {"l1": False, "l2": False, "l3": False},
        )
        self.assertEqual(updated, {"l1": False, "l2": False, "l3": False})
        self.assertEqual(await manager.async_get_phase_history_visible("user-a"), updated)

    async def test_phase_visibility_partial_update_preserves_other_phases(self):
        manager = object.__new__(ElhandelManager)
        manager.chart_preferences_store = _Store()

        updated = await manager.async_set_phase_history_visible("user-a", {"l2": False})
        self.assertEqual(updated, {"l1": True, "l2": False, "l3": True})

    async def test_chart_layers_are_initialized_per_user_and_preserve_existing_values(self):
        manager = object.__new__(ElhandelManager)
        manager.chart_preferences_store = _Store()

        first = await manager.async_get_chart_layers("user-a")
        self.assertTrue(first["spot"])
        self.assertTrue(first["average"])
        self.assertEqual(set(first), {"spot", "average", "import", "export", "solar", "consumption", "charging", "discharging"})

        updated = await manager.async_set_chart_layers("user-a", {"average": False, "consumption": False})
        self.assertFalse(updated["average"])
        self.assertFalse(updated["consumption"])
        self.assertTrue(updated["spot"])

        restored = await manager.async_get_chart_layers("user-a")
        self.assertEqual(restored, updated)
        other_user = await manager.async_get_chart_layers("user-b")
        self.assertTrue(other_user["average"])
        self.assertTrue(other_user["consumption"])

    async def test_configuration_cards_visibility_is_persistent_per_user(self):
        manager = object.__new__(ElhandelManager)
        manager.chart_preferences_store = _Store()

        self.assertTrue(await manager.async_get_configuration_cards_visible("user-a"))
        self.assertFalse(await manager.async_set_configuration_cards_visible("user-a", False))
        self.assertFalse(await manager.async_get_configuration_cards_visible("user-a"))
        self.assertTrue(await manager.async_get_configuration_cards_visible("user-b"))

        stored = await manager.chart_preferences_store.async_load()
        self.assertFalse(stored["users"]["user-a"]["configuration_cards_visible"])

    async def test_main_cards_are_defaulted_per_user_and_partial_updates_are_preserved(self):
        manager = object.__new__(ElhandelManager)
        manager.chart_preferences_store = _Store()

        first = await manager.async_get_main_cards("user-a")
        self.assertEqual(set(first), {"elhandel", "elnet", "elmatare", "solar", "consumption", "battery"})
        self.assertFalse(any(first.values()))
        updated = await manager.async_set_main_cards("user-a", {"battery": True})
        self.assertTrue(updated["battery"])
        self.assertFalse(updated["solar"])
        updated = await manager.async_set_main_cards("user-a", {"solar": True})
        self.assertTrue(updated["battery"])
        self.assertTrue(updated["solar"])
        other_user = await manager.async_get_main_cards("user-b")
        self.assertFalse(any(other_user.values()))


class _Connection:
    def __init__(self):
        self.result = None

    def send_result(self, message_id, result):
        self.result = (message_id, result)


def _manager() -> ElhandelManager:
    manager = object.__new__(ElhandelManager)
    manager.hass = _Hass()
    manager.entry = SimpleNamespace(
        data={
            ELECTRICITY_PROVIDER_CONFIG_KEY: "greenely",
            ELECTRICITY_PROVIDER_CONFIG_DATA_KEY: {
                "email": "user@example.test",
                "password": "password",
                "facility_id": "facility-1",
            },
        }
    )
    manager.storage = StorageManager.__new__(StorageManager)
    manager.storage.store = _Store()
    manager.diagnostics_store = _Store()
    manager.diagnostics = []
    manager.state = {
        "configured": True,
        "provider": "greenely",
        "source_type": "elhandel",
        "provider_name": "Greenely",
        "device_name": None,
        "facility_id": "facility-1",
        "facility_name": "Home",
        "invoices": [{"invoice_date": "2026-08-01", "amount_due_sek": 12.0}],
        "summary": {"agreement_name": "Kvartsprisavtal"},
        "processing": manager._empty_processing(),
        "consumption": {"month": "2026-08", "month_to_date_kwh": 10.0},
        "consumption_error": None,
        "source": {
            "facility": {"id": "facility-1"},
            "contracts": [{"_contract_id": "contract-1"}],
            "invoices": [{"invoice_date": "2026-08-01"}],
            "consumption": {"samples": [{"localtime": "2026-08-01T00:00:00+02:00"}]},
        },
        "last_update": "2026-08-01T00:00:00+00:00",
        "error": None,
        "_new_invoice_keys": [],
    }
    manager.lifecycle = LifecycleManager(manager.hass)
    return manager


def _seed_persisted_manager(manager: ElhandelManager) -> None:
    manager.storage.store.data = {
        "version": 2,
        "facilities": {
            "facility-1": {
                "providers": {
                    "greenely": record_from_state(manager.state),
                },
            },
        },
        "active_facility_id": "facility-1",
        "active_provider": "greenely",
    }


class _BlockingRefreshClient:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def async_login(self, email, password):
        return None

    async def async_get_facilities(self):
        return [{"id": "facility-1", "name": "Home"}]

    @staticmethod
    def select_facility(facilities, facility_id):
        return next(item for item in facilities if str(item.get("id")) == facility_id)

    async def async_get_refresh_data(self, config):
        self.started.set()
        await self.release.wait()
        return {
            "facility_id": "facility-1",
            "facility": {"id": "facility-1", "name": "Home"},
            "contracts": [],
            "invoices": [],
            "failed_contracts": [],
        }

    async def async_get_facility_invoices(self, facility_id):
        self.started.set()
        await self.release.wait()
        return {"contracts": [], "invoices": [], "failed_contracts": []}


class _RefreshClient:
    async def async_login(self, email, password):
        return None

    async def async_get_facilities(self):
        return [{"id": "facility-1", "name": "Home"}]

    @staticmethod
    def select_facility(facilities, facility_id):
        return next(item for item in facilities if str(item.get("id")) == facility_id)

    async def async_get_refresh_data(self, config):
        return {
            "facility_id": "facility-1",
            "facility": {"id": "facility-1", "name": "Home"},
            "contracts": [],
            "invoices": [{"_invoice_key": "invoice-1", "_contract_id": "contract-1", "invoice_date": "2026-08-02", "amount_due_sek": 13.0}],
            "failed_contracts": [],
        }

    async def async_get_facility_invoices(self, facility_id):
        return {
            "contracts": [],
            "invoices": [{"_invoice_key": "invoice-1", "_contract_id": "contract-1", "invoice_date": "2026-08-02", "amount_due_sek": 13.0}],
            "failed_contracts": [],
        }


class _SaveClient:
    async def async_login(self, email, password):
        return None

    async def async_get_facilities(self):
        return [{"id": "facility-1", "name": "Home"}]

    async def async_create_config(self, email, password, facility_id):
        return {
            "config": {"email": email, "password": password, "facility_id": facility_id},
            "facility": {"id": facility_id, "name": "Home"},
        }


class _UnknownFacilityClient(_SaveClient):
    async def async_get_facilities(self):
        return [{"id": "other-facility", "name": "Other"}]

    async def async_create_config(self, email, password, facility_id):
        raise GreenelyError("unexpected_response")


class _FailingSaveClient:
    async def async_login(self, email, password):
        raise GreenelyError("invalid_auth")

    async def async_create_config(self, email, password, facility_id):
        raise GreenelyError("invalid_auth")


def test_consumption_summary_sanitizes_samples_and_rejects_schema():
    summary = _summarize_consumption(
        {"data": [{"timestamp": "2026-08-20T00:00:00Z", "value": 1.2, "email": "hidden"}]}
    )
    assert summary["sample_items"] == [{"timestamp": "2026-08-20T00:00:00Z", "value": 1.2}]
    assert _summarize_consumption({"data": {"value": 1.2}}) is None


def test_safe_key_name_blocks_personal_fields():
    for key in ("personal_number", "cell_phone", "first_name", "last_name"):
        assert not _safe_key_name(key)


def test_invoice_sanitization_removes_sensitive_fields_and_normalizes_cost():
    contract = {
        "id": "contract-1",
        "facility_id": 123,
        "status": "OPERATIONAL",
        "electricity_type": "consumption",
        "customer_id": "private",
        "bankid_order_ref": "private",
        "meter_id": "private",
    }
    invoice = _sanitize_invoice(
        {
            "invoice_date": "2026-08-11",
            "pdf_url": "https://example.invalid/signed.pdf",
            "ocr_number": "private",
            "cost": 7800,
            "state": "Betalt",
            "is_paid": True,
        },
        "contract-1",
        contract,
    )
    assert invoice["amount_due_ore"] == 7800
    assert invoice["amount_due_sek"] == 78.0
    assert "pdf_url" not in invoice
    assert "ocr_number" not in invoice
    assert "jwt" not in invoice
    assert _sanitize_contract(contract)["status"] == "OPERATIONAL"
    assert "customer_id" not in _sanitize_contract(contract)


def test_cached_state_contains_no_credentials_or_raw_invoice_fields():
    state = _sanitize_storage_state(
        {
            "configured": True,
            "provider": "greenely",
            "facility_id": "facility-1",
            "greenely_password": "secret",
            "jwt": "token",
            "invoices": [{"amount_due_ore": 0, "pdf_url": "signed", "ocr_number": "hidden"}],
        }
    )
    assert state["provider"] == "greenely"
    assert state["invoices"] == [{"amount_due_ore": 0}]
    assert "greenely_password" not in state
    assert "jwt" not in state


class GreenelyLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def test_provider_state_endpoint_preserves_full_public_state(self):
        manager = _manager()

        result = _electricity_provider_state(manager)

        self.assertEqual(result["provider_name"], "Greenely")
        self.assertEqual(result["summary"]["agreement_name"], "Kvartsprisavtal")
        self.assertEqual(result["invoice_count"], 1)
        self.assertIn("processing_status", result)
        self.assertEqual(result["consumption"]["month_to_date_kwh"], 10.0)
        self.assertEqual(result["providers"], [{"provider": "greenely", "name": "Greenely"}])

    def test_provider_state_endpoint_preserves_empty_public_state(self):
        result = _electricity_provider_state(None)

        self.assertFalse(result["configured"])
        self.assertIsNone(result["provider_name"])
        self.assertIsNone(result["summary"])
        self.assertEqual(result["invoice_count"], 0)
        self.assertIn("processing_status", result)
        self.assertEqual(result["providers"], [{"provider": "greenely", "name": "Greenely"}])

    async def test_storage_manager_load_and_save_preserve_existing_payload(self):
        storage = StorageManager.__new__(StorageManager)
        existing = {"configured": True, "provider": "greenely", "facility_id": "facility-1", "invoices": []}
        storage.store = _Store({
            "version": 2,
            "facilities": {"facility-1": {"providers": {"greenely": record_from_state(existing)}}},
            "active_facility_id": "facility-1",
            "active_provider": "greenely",
        })

        loaded = await storage.async_load()
        state = {
            "configured": True,
            "provider": "greenely",
            "facility_id": "facility-1",
            "invoices": [{"invoice_date": "2026-08-01", "private": "removed"}],
            "source": {"facility": {"id": "facility-1"}},
        }
        await storage.async_save(state)

        self.assertEqual(loaded["configured"], True)
        saved = storage.store.data["facilities"]["facility-1"]["providers"]["greenely"]
        self.assertEqual(saved["active"]["provider"], "greenely")
        self.assertEqual(saved["history"]["invoices"], [{"invoice_date": "2026-08-01"}])

    def test_storage_manager_history_helpers_are_consistent(self):
        previous = [{"_invoice_key": "old", "_contract_id": "failed", "invoice_date": "2026-07-01"}]
        refreshed = [{"_invoice_key": "new", "_contract_id": "ok", "invoice_date": "2026-08-01"}]
        failed = {"failed"}
        storage = StorageManager.__new__(StorageManager)

        self.assertEqual(
            storage.merge_invoice_history(previous, refreshed, failed),
            [{"_invoice_key": "new", "_contract_id": "ok", "invoice_date": "2026-08-01"},
             {"_invoice_key": "old", "_contract_id": "failed", "invoice_date": "2026-07-01"}],
        )
        self.assertEqual(storage.new_invoice_keys(previous, refreshed), ["new"])

    async def test_async_load_restores_configured_provider(self):
        hass = _Hass()
        entry = SimpleNamespace(
            data={
                ELECTRICITY_PROVIDER_CONFIG_KEY: "greenely",
                ELECTRICITY_PROVIDER_CONFIG_DATA_KEY: {
                    "email": "user@example.test",
                    "password": "password",
                    "facility_id": "facility-1",
                },
            }
        )
        state = {"configured": True, "provider": "greenely", "facility_id": "facility-1", "invoices": []}
        state_store = _Store({
            "version": 2,
            "facilities": {"facility-1": {"providers": {"greenely": record_from_state(state)}}},
            "active_facility_id": "facility-1",
            "active_provider": "greenely",
        })
        diagnostics_store = _Store([])
        preferences_store = _Store({"debug_enabled": True})
        integration = SimpleNamespace(manifest={"version": "0.0.124"})

        with patch(
            "custom_components.elrakning.elhandel.storage.Store",
            return_value=state_store,
        ), patch(
            "custom_components.elrakning.elhandel.manager.Store",
            side_effect=[diagnostics_store, preferences_store, _Store()],
        ), patch(
            "custom_components.elrakning.elhandel.manager.async_get_integration",
            new=AsyncMock(return_value=integration),
        ):
            manager = ElhandelManager(hass, entry)
            await manager.async_load()

        self.assertTrue(manager.state["configured"])
        self.assertEqual(manager.state["provider"], "greenely")
        self.assertEqual(manager.state["provider_name"], "Greenely")
        self.assertTrue(manager.frontend_preferences["debug_enabled"])
        self.assertEqual(diagnostics_store.data[0]["event"], "integration_start")
        self.assertIn("Version: 0.0.124", diagnostics_store.data[0]["message"])

    async def test_async_load_without_provider_clears_active_provider_state(self):
        hass = _Hass()
        entry = SimpleNamespace(data={})
        integration = SimpleNamespace(manifest={"version": "0.0.124"})

        with patch(
            "custom_components.elrakning.elhandel.storage.Store",
            return_value=_Store({"configured": True, "provider": "greenely"}),
        ), patch(
            "custom_components.elrakning.elhandel.manager.Store",
            side_effect=[_Store([]), _Store(), _Store()],
        ), patch(
            "custom_components.elrakning.elhandel.manager.async_get_integration",
            new=AsyncMock(return_value=integration),
        ):
            manager = ElhandelManager(hass, entry)
            await manager.async_load()

        self.assertFalse(manager.state["configured"])
        self.assertIsNone(manager.state["provider"])
        self.assertIsNone(manager.state["provider_name"])

    async def test_async_save_config_persists_provider_and_starts_refresh(self):
        manager = _manager()
        manager.entry.data = {}

        with patch(
            "custom_components.elrakning.elhandel.manager.GreenelyProvider",
            return_value=_SaveClient(),
        ), patch.object(manager, "async_start_refresh") as start_refresh:
            result = await manager.async_save_config("user@example.test", "password", "facility-1")

        self.assertTrue(result["configured"])
        self.assertEqual(manager.entry.data[ELECTRICITY_PROVIDER_CONFIG_KEY], "greenely")
        self.assertEqual(manager.entry.data[ELECTRICITY_PROVIDER_CONFIG_DATA_KEY]["facility_id"], "facility-1")
        self.assertEqual(manager.state["provider"], "greenely")
        start_refresh.assert_called_once_with("manual_debug")

    async def test_async_save_config_failure_does_not_activate_provider(self):
        manager = _manager()
        manager.entry.data = {}

        with patch(
            "custom_components.elrakning.elhandel.manager.GreenelyProvider",
            return_value=_FailingSaveClient(),
        ):
            with self.assertRaises(GreenelyError) as error:
                await manager.async_save_config("user@example.test", "password", "facility-1")

        self.assertEqual(error.exception.code, "invalid_auth")
        self.assertNotIn(ELECTRICITY_PROVIDER_CONFIG_DATA_KEY, manager.entry.data)
        self.assertNotIn(ELECTRICITY_PROVIDER_CONFIG_KEY, manager.entry.data)

    async def test_async_save_config_rejects_unknown_facility(self):
        manager = _manager()
        manager.entry.data = {}

        with patch(
            "custom_components.elrakning.elhandel.manager.GreenelyProvider",
            return_value=_UnknownFacilityClient(),
        ):
            with self.assertRaises(GreenelyError) as error:
                await manager.async_save_config("user@example.test", "password", "facility-1")

        self.assertEqual(error.exception.code, "unexpected_response")
        self.assertNotIn(ELECTRICITY_PROVIDER_CONFIG_DATA_KEY, manager.entry.data)

    async def test_disconnect_removes_configuration_but_preserves_history(self):
        manager = _manager()
        _seed_persisted_manager(manager)

        await manager.async_disconnect()

        self.assertNotIn(ELECTRICITY_PROVIDER_CONFIG_KEY, manager.entry.data)
        self.assertNotIn(ELECTRICITY_PROVIDER_CONFIG_DATA_KEY, manager.entry.data)
        self.assertFalse(manager.state["configured"])
        self.assertEqual(manager.state["invoices"], [])
        self.assertEqual(manager.state["source"]["consumption"]["samples"], [])
        stored = manager.storage.store.data
        self.assertEqual(stored["version"], 2)
        self.assertIsNone(stored["active_facility_id"])
        self.assertIsNone(stored["active_provider"])
        record = stored["facilities"]["facility-1"]["providers"]["greenely"]
        self.assertFalse(record["active"]["configured"])
        self.assertEqual(len(record["history"]["invoices"]), 1)

    async def test_disconnect_persists_cleared_active_fields_and_retains_history(self):
        manager = _manager()
        _seed_persisted_manager(manager)

        await manager.async_disconnect()

        stored = manager.storage.store.data
        record = stored["facilities"]["facility-1"]["providers"]["greenely"]
        self.assertFalse(record["active"]["configured"])
        self.assertIsNone(record["active"]["provider"])
        self.assertIsNone(record["active"]["facility_id"])
        self.assertIsNone(record["active"]["source"]["facility"])
        self.assertEqual(len(record["history"]["invoices"]), 1)

    async def test_disconnect_with_purge_uses_captured_facility_and_provider(self):
        manager = _manager()
        manager.storage.async_remove_provider = AsyncMock()

        await manager.async_disconnect(purge_history=True)

        manager.storage.async_remove_provider.assert_awaited_once_with(
            "facility-1", "greenely", purge_history=True
        )
        self.assertFalse(manager.state["configured"])
        self.assertIsNone(manager.state["facility_id"])

    async def test_disconnect_with_purge_rejects_unknown_facility(self):
        manager = _manager()
        manager.state["facility_id"] = None

        with self.assertRaises(GreenelyError) as raised:
            await manager.async_disconnect(purge_history=True)

        self.assertEqual(raised.exception.code, "facility_not_identified")
        manager.storage.store.data = None

    async def test_retained_history_can_be_purged_without_provider_config(self):
        manager = _manager()
        manager.storage.async_history_metadata = AsyncMock(side_effect=[
            [{"facility_id": "facility-1", "provider": "greenely", "invoice_count": 2, "consumption_sample_count": 3}],
            [],
            [],
        ])
        manager.storage.async_remove_provider = AsyncMock()
        manager.state["configured"] = False
        manager.state["provider"] = None

        result = await manager.async_purge_history("facility-1", "greenely")

        manager.storage.async_remove_provider.assert_awaited_once_with(
            "facility-1", "greenely", purge_history=True
        )
        self.assertEqual(result, [])
        self.assertIn("history_purge_start", [item["event"] for item in manager.diagnostics])
        self.assertIn("history_purge_success", [item["event"] for item in manager.diagnostics])

    async def test_source_data_is_rejected_after_disconnect(self):
        manager = _manager()
        manager.hass.data[DOMAIN]["elhandel_manager"] = manager
        await manager.async_disconnect()
        connection = _Connection()

        await websocket_electricity_provider_source_data(manager.hass, connection, {"id": 1, "type": "elrakning/electricity_provider_source_data"})

        self.assertEqual(connection.result, (1, {"success": False, "error": "not_configured"}))

    async def test_stale_refresh_does_not_restore_removed_provider_state(self):
        manager = _manager()
        client = _BlockingRefreshClient()

        with patch("custom_components.elrakning.elhandel.manager.GreenelyProvider", return_value=client):
            refresh_task = asyncio.create_task(manager.async_refresh("test"))
            await client.started.wait()
            await manager.async_disconnect()
            client.release.set()
            await refresh_task

        self.assertFalse(manager.state["configured"])
        self.assertIsNone(manager.state["provider"])
        self.assertEqual(manager.state["source"]["facility"], None)

    async def test_public_state_hides_cached_values_after_disconnect(self):
        manager = _manager()
        await manager.async_disconnect()

        state = manager.public_state()

        self.assertEqual(state["configured"], False)
        self.assertIsNone(state["provider"])
        self.assertIsNone(state["summary"])
        self.assertIsNone(state["consumption"])
        self.assertEqual(state["invoice_count"], 0)
        self.assertIsNone(state["latest_invoice"])

    async def test_refresh_success_updates_state_and_fires_update_event(self):
        manager = _manager()
        manager.async_process_latest_invoice_if_needed = AsyncMock()
        manager.async_refresh_consumption = AsyncMock()

        with patch(
            "custom_components.elrakning.elhandel.manager.GreenelyProvider",
            return_value=_RefreshClient(),
        ):
            state = await manager.async_refresh("test")

        self.assertEqual(state["invoice_count"], 1)
        self.assertEqual(manager.state["invoices"][0]["_invoice_key"], "invoice-1")
        self.assertIn("elrakning_electricity_provider_update", manager.hass.bus.events)

    async def test_public_state_has_exact_empty_shape_without_provider(self):
        manager = _manager()
        manager.state["configured"] = False

        state = manager.public_state()

        self.assertEqual(
            set(state),
            {
                "configured", "provider", "source_type", "provider_name", "device_name",
                "facility_name", "invoice_count", "invoice_history", "latest_invoice", "last_update", "error",
                "summary", "processing_status", "consumption", "consumption_error",
            },
        )
        self.assertEqual(state["configured"], False)
        self.assertIsNone(state["provider"])
        self.assertIsNone(state["summary"])
        self.assertEqual(state["invoice_count"], 0)

    async def test_internal_provider_data_snapshot_preserves_existing_public_state(self):
        manager = _manager()
        public_before = manager.public_state()

        provider_data = manager._provider_data()

        self.assertEqual(manager.public_state(), public_before)
        self.assertEqual(provider_data.provider, "greenely")
        self.assertEqual(provider_data.facility["id"], "facility-1")
        self.assertEqual(provider_data.active_data["contracts"], [{"_contract_id": "contract-1"}])
        self.assertEqual(provider_data.invoices, manager.state["invoices"])
        self.assertEqual(provider_data.consumption["summary"], manager.state["consumption"])
        self.assertEqual(provider_data.consumption["samples"], manager.state["source"]["consumption"]["samples"])
        self.assertIsNone(provider_data.tariff)
        self.assertIsNone(provider_data.error)

    async def test_internal_provider_data_snapshot_exposes_error_without_changing_public_state(self):
        manager = _manager()
        manager.state["error"] = "processing_failed"
        manager.state["processing"]["last_error"] = "validation_failed"
        manager.state["processing"]["last_error_stage"] = "validation"

        public_before = manager.public_state()
        provider_data = manager._provider_data()

        self.assertEqual(manager.public_state(), public_before)
        self.assertEqual(provider_data.error["state"], "processing_failed")
        self.assertEqual(provider_data.error["processing"]["error"], "validation_failed")

    async def test_provider_neutral_serializer_matches_public_state_for_configured_provider(self):
        manager = _manager()
        provider_data = manager._provider_data()
        expected = manager.public_state()

        serialized = electricity_models.serialize_provider_state(
            provider_data,
            {
                "source_type": manager.state["source_type"],
                "provider_name": manager.state["provider_name"],
                "device_name": manager.state["device_name"],
                "facility_name": manager.state["facility_name"],
            },
        )

        self.assertEqual(serialized, expected)
        self.assertEqual(manager.public_state(), expected)

    async def test_provider_neutral_serializer_matches_empty_public_state(self):
        manager = _manager()
        manager.state["configured"] = False
        provider_data = manager._provider_data()
        expected = manager.public_state()

        serialized = electricity_models.serialize_provider_state(provider_data)

        self.assertEqual(serialized, expected)
        self.assertEqual(manager.public_state(), expected)

    async def test_provider_neutral_serializer_preserves_tariff_missing_and_error_processing_states(self):
        manager = _manager()
        manager.state["summary"] = None
        manager.state["error"] = "processing_failed"
        manager.state["processing"].update(
            {"last_error": "validation_failed", "last_error_stage": "validation"}
        )
        provider_data = manager._provider_data()
        expected = manager.public_state()

        serialized = electricity_models.serialize_provider_state(
            provider_data,
            {
                "source_type": manager.state["source_type"],
                "provider_name": manager.state["provider_name"],
                "device_name": manager.state["device_name"],
                "facility_name": manager.state["facility_name"],
            },
        )

        self.assertEqual(serialized, expected)
        self.assertEqual(manager.public_state(), expected)
        self.assertIsNone(serialized["summary"])
        self.assertEqual(serialized["error"], "processing_failed")
        self.assertTrue(serialized["processing_status"]["error"])

    async def test_diagnostic_event_preserves_level_component_event_and_payload_shape(self):
        manager = _manager()

        await manager.async_diagnostic("INFO", "price", "chart_debug_copy_success", "Copied debug tooltip")

        diagnostic = manager.diagnostics[-1]
        self.assertEqual(set(diagnostic), {"timestamp", "level", "component", "event", "message"})
        self.assertEqual(diagnostic["level"], "INFO")
        self.assertEqual(diagnostic["component"], "price")
        self.assertEqual(diagnostic["event"], "chart_debug_copy_success")
        self.assertEqual(diagnostic["message"], "Copied debug tooltip")
        self.assertIn("elrakning_diagnostics_update", manager.hass.bus.events)
