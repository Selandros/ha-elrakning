"""Canonical provider-neutral electricity manager."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.loader import async_get_integration

from ..const import (
    DOMAIN,
    ELECTRICITY_PROVIDER_CONFIG_KEY,
    ELECTRICITY_PROVIDER_CONFIG_DATA_KEY,
    GREENELY_PROVIDER,
    ELECTRICITY_PROVIDER_UPDATE_EVENT,
    SUPPORTED_ELECTRICITY_PROVIDERS,
)
from ..diagnostics import append_diagnostic
from .providers.greenely_source import merge_consumption_samples
from .providers.greenely_client import GreenelyError
from .models import ProviderData, _safe_facility_name, serialize_provider_state
from .provider_registry import provider_data_from_state, sanitize_provider_source
from .providers.greenely import GreenelyProvider
from .providers.greenely_invoice import GreenelyInvoiceError
from .storage import StorageManager
from .lifecycle import LifecycleManager

CHART_LAYER_DEFAULTS = {
    "spot": True,
    "average": True,
    "import": True,
    "export": True,
    "solar": True,
    "consumption": True,
    "charging": True,
    "discharging": True,
}
CONFIGURATION_CARDS_VISIBLE_DEFAULT = True
MAIN_CARD_DEFAULTS = {
    "elhandel": False,
    "elnet": False,
    "elmatare": False,
    "solar": False,
    "consumption": False,
    "battery": False,
}
PRICE_COMPARISON_DEFAULTS = {
    "electricity": True,
    "grid": False,
}
PHASE_HISTORY_VISIBLE_DEFAULTS = {
    "l1": True,
    "l2": True,
    "l3": True,
}


class ElhandelManager:
    """Orchestrate electricity provider lifecycle and persisted state."""

    def __init__(self, hass, entry) -> None:
        self.hass = hass
        self.entry = entry
        self.storage = StorageManager(hass)
        self.diagnostics_store = Store(hass, 1, "elrakning.diagnostics")
        self.preferences_store = Store(hass, 1, "elrakning.frontend_preferences")
        self.chart_preferences_store = Store(hass, 1, "elrakning.chart_preferences")
        self.frontend_preferences = {"debug_enabled": False}
        self.lifecycle = LifecycleManager(hass)
        self.diagnostics: list[dict[str, Any]] = []
        self.state: dict[str, Any] = {
            "configured": False,
            "provider": None,
            "source_type": "elhandel",
            "provider_name": None,
            "device_name": None,
            "facility_id": None,
            "invoice_count": 0,
            "invoices": [],
            "summary": None,
            "processing": {
                "_last_successful_invoice_key": None,
                "_last_successful_parse_at": None,
                "_failed_invoice_key": None,
                "last_error": None,
                "last_error_stage": None,
                "last_error_at": None,
            },
            "consumption": None,
            "consumption_error": None,
            "source": {"facility": None, "contracts": [], "invoices": [], "consumption": {"samples": []}},
            "last_update": None,
            "error": None,
        }

    async def async_load(self) -> None:
        config = self._config()
        configured = GreenelyProvider.is_configured(config)
        facility_id = GreenelyProvider.facility_id(config) if configured else None
        cached = await self.storage.async_load(
            facility_id=facility_id,
            provider=GREENELY_PROVIDER if configured else None,
            use_active_namespace=configured,
        )
        if isinstance(cached, dict):
            self.state.update(self.storage.sanitize(cached))
        if not isinstance(self.state.get("processing"), dict):
            self.state["processing"] = self._empty_processing()
        if not isinstance(self.state.get("source"), dict):
            self.state["source"] = {"facility": None, "contracts": [], "invoices": [], "consumption": {"samples": []}}
        preferences = await self.preferences_store.async_load()
        if isinstance(preferences, dict) and isinstance(preferences.get("debug_enabled"), bool):
            self.frontend_preferences["debug_enabled"] = preferences["debug_enabled"]
        integration = await async_get_integration(self.hass, DOMAIN)
        version = integration.manifest["version"]
        self.diagnostics = []
        await self.diagnostics_store.async_save(self.diagnostics)
        await self.async_diagnostic("INFO", "integration", "integration_start", f"Integration started · Version: {version}")
        self.state["configured"] = configured
        self.state["provider"] = GREENELY_PROVIDER if configured else None
        self.state["provider_name"] = SUPPORTED_ELECTRICITY_PROVIDERS[GREENELY_PROVIDER] if configured else None
        if configured and self.entry.data.get(ELECTRICITY_PROVIDER_CONFIG_KEY) != GREENELY_PROVIDER:
            entry_data = dict(self.entry.data)
            entry_data[ELECTRICITY_PROVIDER_CONFIG_KEY] = GREENELY_PROVIDER
            self.hass.config_entries.async_update_entry(self.entry, data=entry_data)

    def _config(self) -> dict[str, Any]:
        config = self.entry.data.get(ELECTRICITY_PROVIDER_CONFIG_DATA_KEY, {})
        return config if isinstance(config, dict) else {}

    async def async_diagnostic(self, level: str, component: str, event: str, message: str) -> None:
        append_diagnostic(self.diagnostics, level, component, event, message)
        await self.diagnostics_store.async_save(self.diagnostics)
        self.hass.bus.async_fire("elrakning_diagnostics_update")

    async def async_clear_diagnostics(self) -> None:
        self.diagnostics.clear()
        await self.diagnostics_store.async_save(self.diagnostics)
        self.hass.bus.async_fire("elrakning_diagnostics_update")

    async def async_get_frontend_preferences(self) -> dict[str, bool]:
        return dict(self.frontend_preferences)

    async def async_set_debug_enabled(self, enabled: bool) -> dict[str, bool]:
        self.frontend_preferences["debug_enabled"] = bool(enabled)
        await self.preferences_store.async_save(self.frontend_preferences)
        return await self.async_get_frontend_preferences()

    async def async_get_chart_layers(self, user_id: str) -> dict[str, bool]:
        stored = await self.chart_preferences_store.async_load()
        users = stored.get("users", {}) if isinstance(stored, dict) else {}
        user_state = users.get(user_id, {}) if isinstance(users, dict) else {}
        chart_layers = user_state.get("chart_layers", {}) if isinstance(user_state, dict) else {}
        result = {
            key: chart_layers[key] if isinstance(chart_layers, dict) and isinstance(chart_layers.get(key), bool) else default
            for key, default in CHART_LAYER_DEFAULTS.items()
        }
        if not isinstance(users, dict):
            users = {}
        if not isinstance(users.get(user_id), dict) or users[user_id].get("chart_layers") != result:
            users[user_id] = {**(users.get(user_id) if isinstance(users.get(user_id), dict) else {}), "chart_layers": result}
            await self.chart_preferences_store.async_save({"users": users})
        return result

    async def async_set_chart_layers(self, user_id: str, updates: dict[str, bool]) -> dict[str, bool]:
        current = await self.async_get_chart_layers(user_id)
        for key, value in updates.items():
            if key in CHART_LAYER_DEFAULTS and isinstance(value, bool):
                current[key] = value
        stored = await self.chart_preferences_store.async_load()
        users = stored.get("users", {}) if isinstance(stored, dict) and isinstance(stored.get("users"), dict) else {}
        users[user_id] = {**(users.get(user_id) if isinstance(users.get(user_id), dict) else {}), "chart_layers": current}
        await self.chart_preferences_store.async_save({"users": users})
        return current

    async def async_get_price_comparison(self, user_id: str) -> dict[str, bool]:
        stored = await self.chart_preferences_store.async_load()
        users = stored.get("users", {}) if isinstance(stored, dict) else {}
        user_state = users.get(user_id, {}) if isinstance(users, dict) else {}
        saved = user_state.get("price_comparison", {}) if isinstance(user_state, dict) else {}
        result = {
            key: saved[key] if isinstance(saved, dict) and isinstance(saved.get(key), bool) else default
            for key, default in PRICE_COMPARISON_DEFAULTS.items()
        }
        if not isinstance(users, dict):
            users = {}
        if not isinstance(users.get(user_id), dict) or users[user_id].get("price_comparison") != result:
            users[user_id] = {
                **(users.get(user_id) if isinstance(users.get(user_id), dict) else {}),
                "price_comparison": result,
            }
            await self.chart_preferences_store.async_save({"users": users})
        return result

    async def async_set_price_comparison(self, user_id: str, updates: dict[str, bool]) -> dict[str, bool]:
        current = await self.async_get_price_comparison(user_id)
        for key, value in updates.items():
            if key in PRICE_COMPARISON_DEFAULTS and isinstance(value, bool):
                current[key] = value
        stored = await self.chart_preferences_store.async_load()
        users = stored.get("users", {}) if isinstance(stored, dict) and isinstance(stored.get("users"), dict) else {}
        users[user_id] = {
            **(users.get(user_id) if isinstance(users.get(user_id), dict) else {}),
            "price_comparison": current,
        }
        await self.chart_preferences_store.async_save({"users": users})
        return current

    async def async_get_phase_history_visible(self, user_id: str) -> dict[str, bool]:
        stored = await self.chart_preferences_store.async_load()
        users = stored.get("users", {}) if isinstance(stored, dict) else {}
        user_state = users.get(user_id, {}) if isinstance(users, dict) else {}
        saved = user_state.get("phase_history_visible", {}) if isinstance(user_state, dict) else {}
        return {
            key: saved[key] if isinstance(saved, dict) and isinstance(saved.get(key), bool) else default
            for key, default in PHASE_HISTORY_VISIBLE_DEFAULTS.items()
        }

    async def async_set_phase_history_visible(self, user_id: str, updates: dict[str, bool]) -> dict[str, bool]:
        current = await self.async_get_phase_history_visible(user_id)
        for key, value in updates.items():
            if key in PHASE_HISTORY_VISIBLE_DEFAULTS and isinstance(value, bool):
                current[key] = value
        stored = await self.chart_preferences_store.async_load()
        users = stored.get("users", {}) if isinstance(stored, dict) and isinstance(stored.get("users"), dict) else {}
        users[user_id] = {**(users.get(user_id) if isinstance(users.get(user_id), dict) else {}), "phase_history_visible": current}
        await self.chart_preferences_store.async_save({"users": users})
        return current

    async def async_get_configuration_cards_visible(self, user_id: str) -> bool:
        stored = await self.chart_preferences_store.async_load()
        users = stored.get("users", {}) if isinstance(stored, dict) else {}
        user_state = users.get(user_id, {}) if isinstance(users, dict) else {}
        visible = user_state.get("configuration_cards_visible") if isinstance(user_state, dict) else None
        result = visible if isinstance(visible, bool) else CONFIGURATION_CARDS_VISIBLE_DEFAULT
        if not isinstance(users, dict):
            users = {}
        if not isinstance(users.get(user_id), dict) or users[user_id].get("configuration_cards_visible") != result:
            users[user_id] = {
                **(users.get(user_id) if isinstance(users.get(user_id), dict) else {}),
                "configuration_cards_visible": result,
            }
            await self.chart_preferences_store.async_save({"users": users})
        return result

    async def async_set_configuration_cards_visible(self, user_id: str, visible: bool) -> bool:
        result = bool(visible)
        stored = await self.chart_preferences_store.async_load()
        users = stored.get("users", {}) if isinstance(stored, dict) and isinstance(stored.get("users"), dict) else {}
        users[user_id] = {
            **(users.get(user_id) if isinstance(users.get(user_id), dict) else {}),
            "configuration_cards_visible": result,
        }
        await self.chart_preferences_store.async_save({"users": users})
        return result

    async def async_get_main_cards(self, user_id: str) -> dict[str, bool]:
        stored = await self.chart_preferences_store.async_load()
        users = stored.get("users", {}) if isinstance(stored, dict) else {}
        user_state = users.get(user_id, {}) if isinstance(users, dict) else {}
        main_cards = user_state.get("main_cards", {}) if isinstance(user_state, dict) else {}
        result = {
            key: main_cards[key] if isinstance(main_cards, dict) and isinstance(main_cards.get(key), bool) else default
            for key, default in MAIN_CARD_DEFAULTS.items()
        }
        if not isinstance(users, dict):
            users = {}
        if not isinstance(users.get(user_id), dict) or users[user_id].get("main_cards") != result:
            users[user_id] = {**(users.get(user_id) if isinstance(users.get(user_id), dict) else {}), "main_cards": result}
            await self.chart_preferences_store.async_save({"users": users})
        return result

    async def async_set_main_cards(self, user_id: str, updates: dict[str, bool]) -> dict[str, bool]:
        current = await self.async_get_main_cards(user_id)
        for key, value in updates.items():
            if key in MAIN_CARD_DEFAULTS and isinstance(value, bool):
                current[key] = value
        stored = await self.chart_preferences_store.async_load()
        users = stored.get("users", {}) if isinstance(stored, dict) and isinstance(stored.get("users"), dict) else {}
        users[user_id] = {**(users.get(user_id) if isinstance(users.get(user_id), dict) else {}), "main_cards": current}
        await self.chart_preferences_store.async_save({"users": users})
        return current

    def async_start_refresh(self, reason: str = "startup") -> None:
        if not self.lifecycle.has_refresh_unsubscribe():
            self.lifecycle.set_refresh_unsubscribe(async_track_time_interval(
                self.hass, lambda _: self.async_start_refresh("daily_refresh"), timedelta(days=1)
            ))
        self.lifecycle.start_refresh(
            lambda generation: self.async_refresh(reason, generation)
        )
        if not self.lifecycle.has_consumption_unsubscribe():
            self.lifecycle.set_consumption_unsubscribe(async_track_time_interval(self.hass, lambda _: self.async_start_consumption_refresh("hourly_refresh"), timedelta(hours=1)))
        self.async_start_consumption_refresh(reason)

    def async_start_consumption_refresh(self, reason: str = "manual_debug") -> None:
        self.lifecycle.start_consumption_refresh(
            lambda generation: self.async_refresh_consumption(reason, generation)
        )

    async def async_refresh_consumption(self, reason: str = "manual_debug", _generation: int | None = None) -> None:
        refresh_generation = self.lifecycle.generation if _generation is None else _generation
        config = self._config()
        if not GreenelyProvider.is_configured(config):
            return
        today = datetime.now().date()
        month_start = today.replace(day=1)
        month_end = today + timedelta(days=1)
        await self.async_diagnostic("INFO", "consumption", "consumption_refresh_start", f"Consumption refresh started · Provider: {GREENELY_PROVIDER} · Reason: {reason}")
        try:
            provider = GreenelyProvider(self.hass)
            consumption_data = await provider.async_get_consumption_data(
                config, month_start, month_end, today.strftime("%Y-%m")
            )
            samples = consumption_data["samples"]
            await self.async_diagnostic("INFO", "consumption", "consumption_response_received", "Consumption response received")
            await self.async_diagnostic("INFO", "consumption", "consumption_samples_received", f"Consumption samples received: {len(samples)}")
            summary = consumption_data["summary"]
            summary["last_update"] = datetime.now(timezone.utc).isoformat()
            if not self.lifecycle.is_current(refresh_generation):
                return
            self.state["consumption"] = summary
            source = self.state.setdefault("source", {"facility": None, "contracts": [], "invoices": [], "consumption": {"samples": []}})
            consumption_source = source.setdefault("consumption", {"samples": []})
            consumption_source["samples"] = merge_consumption_samples(consumption_source.get("samples", []), samples)
            self.state["consumption_error"] = None
            await self.async_diagnostic("INFO", "consumption", "consumption_refresh_success", "Consumption refresh completed")
            await self.storage.async_save(self.state)
            self.hass.bus.async_fire(ELECTRICITY_PROVIDER_UPDATE_EVENT)
        except GreenelyError as err:
            if not self.lifecycle.is_current(refresh_generation):
                return
            self.state["consumption_error"] = {"error": err.code, "at": datetime.now(timezone.utc).isoformat()}
            await self.async_diagnostic("ERROR", "consumption", "consumption_failed", "Consumption refresh failed")
            await self.storage.async_save(self.state)
            self.hass.bus.async_fire(ELECTRICITY_PROVIDER_UPDATE_EVENT)

    async def async_refresh(self, reason: str = "manual_debug", _generation: int | None = None) -> dict[str, Any]:
        refresh_generation = self.lifecycle.generation if _generation is None else _generation
        config = self._config()
        if not GreenelyProvider.is_configured(config):
            self.state["configured"] = False
            return self.public_state()
        await self.async_diagnostic("INFO", "provider", "provider_refresh_start", f"Provider refresh started · Provider: {GREENELY_PROVIDER} · Reason: {reason}")
        try:
            provider = GreenelyProvider(self.hass)
            refresh_data = await provider.async_get_refresh_data(config)
        except GreenelyError as err:
            if not self.lifecycle.is_current(refresh_generation):
                return self.public_state()
            self.state["configured"] = True
            self.state["error"] = err.code
            processing = self.state.setdefault("processing", self._empty_processing())
            processing.update({"last_error": err.code, "last_error_stage": "refresh", "last_error_at": datetime.now(timezone.utc).isoformat()})
            await self.storage.async_save(self.state)
            self.hass.bus.async_fire(ELECTRICITY_PROVIDER_UPDATE_EVENT)
            return self.public_state()
        if not self.lifecycle.is_current(refresh_generation):
            return self.public_state()
        previous_invoices = self.state.get("invoices", [])
        source = self.state.get("source") or {}
        facility_id = refresh_data["facility_id"]
        source["facility"] = refresh_data["facility"]
        source["contracts"] = refresh_data["contracts"]
        source["invoices"] = refresh_data["invoices"]
        await self.async_diagnostic("INFO", "source", "source_facility_loaded", "Facility loaded")
        await self.async_diagnostic("INFO", "source", "source_contracts_loaded", f"Contracts loaded: {len(refresh_data['contracts'])}")
        await self.async_diagnostic("INFO", "source", "source_invoices_loaded", f"Invoices loaded: {len(refresh_data['invoices'])}")
        invoices = self.storage.merge_invoice_history(previous_invoices, refresh_data["invoices"], {item["_contract_id"] for item in refresh_data["failed_contracts"]})
        self.state = {
            "configured": True,
            "provider": GREENELY_PROVIDER,
            "source_type": "elhandel",
            "provider_name": SUPPORTED_ELECTRICITY_PROVIDERS[GREENELY_PROVIDER],
            "device_name": None,
            "facility_id": facility_id,
            "facility_name": _safe_facility_name(refresh_data["facility"]),
            "invoice_count": len(invoices),
            "invoices": invoices,
            "summary": self.state.get("summary"),
            "processing": self.state.get("processing", self._empty_processing()),
            "consumption": self.state.get("consumption"),
            "consumption_error": self.state.get("consumption_error"),
            "source": source,
            "_new_invoice_keys": self.storage.new_invoice_keys(previous_invoices, refresh_data["invoices"]),
            "last_update": datetime.now(timezone.utc).isoformat(),
            "error": "partial_update" if refresh_data["failed_contracts"] else None,
        }
        await self.storage.async_save(self.state)
        self.hass.bus.async_fire(ELECTRICITY_PROVIDER_UPDATE_EVENT)
        await self.async_process_latest_invoice_if_needed()
        await self.async_refresh_consumption("invoice_update")
        return self.public_state()

    async def async_save_config(self, email: str, password: str, facility_id: str) -> dict[str, Any]:
        await self.async_diagnostic("INFO", "provider", "provider_auth_start", f"Provider configuration started · Provider: {GREENELY_PROVIDER}")
        provider = GreenelyProvider(self.hass)
        provider_config = await provider.async_create_config(email, password, facility_id)
        saved_config = provider_config["config"]
        selected = provider_config["facility"]
        self.lifecycle.invalidate_generation()
        # Configuration succeeds after auth, facility selection, and credential save; secondary sync is scheduled below.
        old_facility_id = GreenelyProvider.facility_id(self._config())
        facility_changed = old_facility_id is not None and old_facility_id != facility_id
        invoices = [] if facility_changed else self.state.get("invoices", [])
        restored_samples: list[dict[str, Any]] = []
        stored_state: dict[str, Any] | None = None
        if not facility_changed and not invoices:
            stored_state = await self.storage.async_load(
                facility_id=facility_id,
                provider=GREENELY_PROVIDER,
                use_active_namespace=True,
            )
            if isinstance(stored_state, dict):
                stored_invoices = stored_state.get("invoices")
                if isinstance(stored_invoices, list):
                    invoices = stored_invoices
                stored_source = stored_state.get("source")
                if isinstance(stored_source, dict):
                    stored_consumption = stored_source.get("consumption")
                    if isinstance(stored_consumption, dict) and isinstance(stored_consumption.get("samples"), list):
                        restored_samples = stored_consumption["samples"]
        source = self.state.get("source", {})
        if restored_samples and isinstance(source, dict):
            source = dict(source)
            source["consumption"] = {"samples": restored_samples}
        config = dict(self.entry.data)
        config[ELECTRICITY_PROVIDER_CONFIG_KEY] = GREENELY_PROVIDER
        config[ELECTRICITY_PROVIDER_CONFIG_DATA_KEY] = saved_config
        self.hass.config_entries.async_update_entry(self.entry, data=config)
        await self.async_diagnostic("INFO", "provider", "provider_auth_success", f"Provider authentication succeeded · Provider: {GREENELY_PROVIDER}")
        self.state = {
            "configured": True,
            "provider": GREENELY_PROVIDER,
            "source_type": "elhandel",
            "provider_name": SUPPORTED_ELECTRICITY_PROVIDERS[GREENELY_PROVIDER],
            "device_name": None,
            "facility_id": facility_id,
            "facility_name": _safe_facility_name(selected),
            "invoice_count": len(invoices),
            "invoices": invoices,
            "summary": None if facility_changed else self.state.get("summary"),
            "processing": self._empty_processing() if facility_changed else self.state.get("processing", self._empty_processing()),
            "consumption": None if facility_changed else self.state.get("consumption"),
            "consumption_error": None if facility_changed else self.state.get("consumption_error"),
            "source": {"facility": sanitize_provider_source(GREENELY_PROVIDER, selected), "contracts": [], "invoices": [], "consumption": {"samples": []}} if facility_changed else source,
            "_new_invoice_keys": [],
            "last_update": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }
        await self.storage.async_save(self.state)
        self.hass.bus.async_fire(ELECTRICITY_PROVIDER_UPDATE_EVENT)
        await self.async_diagnostic("INFO", "provider", "config_saved", f"Provider configuration saved · Provider: {GREENELY_PROVIDER}")
        self.async_start_refresh("manual_debug")
        return self.public_state()

    def _empty_processing(self) -> dict[str, Any]:
        return {"_last_successful_invoice_key": None, "_last_successful_parse_at": None, "_failed_invoice_key": None, "last_error": None, "last_error_stage": None, "last_error_at": None}

    async def async_process_latest_invoice_if_needed(self, force: bool = False) -> dict[str, Any] | None:
        """Process only the latest invoice when it is new or explicitly retried."""
        config = self._config()
        invoices = self.state.get("invoices", [])
        latest = max(invoices, key=lambda item: item.get("invoice_date") or "", default=None)
        if not latest or not latest.get("_contract_id") or not latest.get("_invoice_key"):
            return None
        processing = self.state.setdefault("processing", self._empty_processing())
        await self.async_diagnostic("INFO", "invoice", "invoice_parse_start", f"Invoice processing started · Provider: {GREENELY_PROVIDER}")
        invoice_key = latest["_invoice_key"]
        await self.async_diagnostic("INFO", "invoice", "latest_invoice_found", "Latest invoice found")
        if not force and processing.get("_last_successful_invoice_key") == invoice_key:
            return None
        if not GreenelyProvider.has_credentials(config):
            return await self._process_failure(invoice_key, "invalid_auth", "refresh")
        processing["last_error"] = None
        processing["last_error_stage"] = None
        processing["last_error_at"] = datetime.now(timezone.utc).isoformat()
        try:
            provider = GreenelyProvider(self.hass)
            result = await provider.async_process_invoice(
                config, latest["_contract_id"], invoice_key, latest.get("amount_due_sek")
            )
        except GreenelyError as err:
            return await self._process_failure(invoice_key, err.code, processing["last_error_stage"] or "refresh")
        except GreenelyInvoiceError as err:
            return await self._process_failure(invoice_key, err.code, err.stage)
        self.state["summary"] = result["summary"]
        await self.async_diagnostic("INFO", "invoice", "invoice_parse_success", "Invoice parsed successfully")
        await self.async_diagnostic("INFO", "invoice", "summary_updated", "Summary updated")
        self.state["error"] = None
        processing.update({"_last_successful_invoice_key": invoice_key, "_last_successful_parse_at": datetime.now(timezone.utc).isoformat(), "_failed_invoice_key": None, "last_error": None, "last_error_stage": None, "last_error_at": None})
        await self.storage.async_save(self.state)
        self.hass.bus.async_fire(ELECTRICITY_PROVIDER_UPDATE_EVENT)
        return {"invoice_date": latest.get("invoice_date"), "month": latest.get("month"), "amount_due_ore": latest.get("amount_due_ore"), "amount_due_sek": latest.get("amount_due_sek"), "parsed": result["parsed"], "diagnostics": result["diagnostics"], "debug_text_excerpt": result["debug_text_excerpt"], "summary": self.public_state().get("summary")}

    async def _process_failure(self, invoice_key: str, error: str, stage: str) -> None:
        processing = self.state.setdefault("processing", self._empty_processing())
        self.state["error"] = "processing_failed"
        await self.async_diagnostic("ERROR", "invoice", "invoice_parse_failed", "Invoice processing failed")
        processing.update({"_failed_invoice_key": invoice_key, "last_error": error, "last_error_stage": stage, "last_error_at": datetime.now(timezone.utc).isoformat()})
        await self.storage.async_save(self.state)
        self.hass.bus.async_fire(ELECTRICITY_PROVIDER_UPDATE_EVENT)
        return None

    async def async_parse_latest_invoice(self) -> dict[str, Any]:
        """Force a complete latest-invoice retry for the diagnostics action."""
        result = await self.async_process_latest_invoice_if_needed(force=True)
        if result is None:
            raise GreenelyError("invoice_parse_failed")
        return result

    async def async_disconnect(self, purge_history: bool = False) -> None:
        facility_id = self.state.get("facility_id")
        provider = self.state.get("provider") or GREENELY_PROVIDER
        if purge_history and (
            not isinstance(facility_id, str)
            or not facility_id
            or not isinstance(provider, str)
            or not provider
        ):
            raise GreenelyError("facility_not_identified")
        await self.async_diagnostic(
            "INFO",
            "electricity",
            "provider_remove_start",
            f"Provider removal started · Provider: {provider} · Facility: {facility_id} · Purge history: {purge_history}",
        )
        self.lifecycle.invalidate_generation()
        self.lifecycle.cancel_tasks()
        config = dict(self.entry.data)
        config.pop(ELECTRICITY_PROVIDER_CONFIG_DATA_KEY, None)
        config.pop(ELECTRICITY_PROVIDER_CONFIG_KEY, None)
        self.hass.config_entries.async_update_entry(self.entry, data=config)
        self.state.update({
            "configured": False,
            "provider": None,
            "provider_name": None,
            "device_name": None,
            "facility_id": None,
            "facility_name": None,
            "invoice_count": 0,
            "invoices": [],
            "summary": None,
            "processing": self._empty_processing(),
            "consumption": None,
            "consumption_error": None,
            "source": {"facility": None, "contracts": [], "invoices": [], "consumption": {"samples": []}},
            "last_update": None,
            "error": None,
            "_new_invoice_keys": [],
        })
        if isinstance(facility_id, str) and facility_id and isinstance(provider, str) and provider:
            if purge_history:
                await self.storage.async_remove_provider(facility_id, provider, purge_history=True)
            else:
                await self.storage.async_remove_provider(facility_id, provider, purge_history=False)
        self.hass.bus.async_fire(ELECTRICITY_PROVIDER_UPDATE_EVENT)
        await self.async_diagnostic(
            "INFO",
            "electricity",
            "provider_remove_success",
            f"Provider removal completed · Provider: {provider} · Facility: {facility_id} · Purge history: {purge_history}",
        )

    async def async_history_metadata(self) -> list[dict[str, Any]]:
        return await self.storage.async_history_metadata()

    async def async_purge_history(self, facility_id: str, provider: str) -> list[dict[str, Any]]:
        if not isinstance(facility_id, str) or not facility_id or not isinstance(provider, str) or not provider:
            raise GreenelyError("facility_not_identified")
        before = next(
            (item for item in await self.storage.async_history_metadata()
             if item["facility_id"] == facility_id and item["provider"] == provider),
            None,
        )
        if before is None:
            raise GreenelyError("history_not_found")
        await self.async_diagnostic(
            "INFO",
            "electricity",
            "history_purge_start",
            f"History purge started · Provider: {provider} · Facility: {facility_id} · "
            f"Invoices: {before['invoice_count']} · Consumption: {before['consumption_sample_count']}",
        )
        try:
            await self.storage.async_remove_provider(facility_id, provider, purge_history=True)
        except Exception:
            await self.async_diagnostic(
                "ERROR",
                "electricity",
                "history_purge_failed",
                f"History purge failed · Provider: {provider} · Facility: {facility_id}",
            )
            raise
        after = next(
            (item for item in await self.storage.async_history_metadata()
             if item["facility_id"] == facility_id and item["provider"] == provider),
            {"invoice_count": 0, "consumption_sample_count": 0},
        )
        await self.async_diagnostic(
            "INFO",
            "electricity",
            "history_purge_success",
            f"History purge completed · Provider: {provider} · Facility: {facility_id} · "
            f"Invoices: {after['invoice_count']} · Consumption: {after['consumption_sample_count']}",
        )
        self.hass.bus.async_fire(ELECTRICITY_PROVIDER_UPDATE_EVENT)
        return await self.storage.async_history_metadata()

    def public_state(self) -> dict[str, Any]:
        return serialize_provider_state(
            self._provider_data(),
            {
                "source_type": self.state.get("source_type"),
                "provider_name": self.state.get("provider_name"),
                "device_name": self.state.get("device_name"),
                "facility_name": self.state.get("facility_name"),
            },
        )

    def source_data(self) -> dict[str, Any]:
        """Return sanitized source data for the active provider."""
        return sanitize_provider_source(self.state.get("provider"), self.state.get("source") or {})

    def _provider_data(self) -> ProviderData:
        """Build an internal ProviderData snapshot without changing public state."""
        return provider_data_from_state(self.state.get("provider"), self.state)

    async def async_shutdown(self) -> None:
        await self.lifecycle.async_shutdown()
