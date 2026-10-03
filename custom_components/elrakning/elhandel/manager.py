"""Canonical provider-neutral electricity manager."""

from __future__ import annotations

import asyncio
import json
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
from ..diagnostics import append_diagnostic, runtime_metadata
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
CONFIGURATION_CARDS_VISIBLE_DEFAULT = False
MAIN_CARD_DEFAULTS = {
    "elhandel": False,
    "elnet": False,
    "elmatare": False,
    "solar": False,
    "consumption": False,
    "battery": False,
}
DASHBOARD_CARD_VISIBILITY_VALUES = ("always", "config_only", "hidden")
DASHBOARD_CARD_VISIBILITY_DEFAULTS = {
    "house": "always",
    "solar": "config_only",
    "grid": "always",
    "battery": "config_only",
    "invoice": "always",
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
PHASE_HISTORY_METRIC_DEFAULT = "current"
PHASE_HISTORY_METRICS = {"current", "voltage", "active_power"}


class ElhandelManager:
    """Orchestrate electricity provider lifecycle and persisted state."""

    def __init__(self, hass, entry) -> None:
        self.hass = hass
        self.entry = entry
        self.storage = StorageManager(hass)
        self.diagnostics_store = Store(hass, 1, "elrakning.diagnostics")
        self.preferences_store = Store(hass, 1, "elrakning.frontend_preferences")
        self.chart_preferences_store = Store(hass, 1, "elrakning.chart_preferences")
        self._chart_preferences_lock = asyncio.Lock()
        self._site_binding: dict[str, Any] | None = None
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
            "analysis": {},
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
        await self.async_diagnostic(
            "INFO",
            "integration",
            "runtime_environment",
            json.dumps(runtime_metadata(version), sort_keys=True, separators=(",", ":")),
        )
        self.state["configured"] = configured
        self.state["provider"] = GREENELY_PROVIDER if configured else None
        self.state["provider_name"] = SUPPORTED_ELECTRICITY_PROVIDERS[GREENELY_PROVIDER] if configured else None
        if configured and self.entry.data.get(ELECTRICITY_PROVIDER_CONFIG_KEY) != GREENELY_PROVIDER:
            entry_data = dict(self.entry.data)
            entry_data[ELECTRICITY_PROVIDER_CONFIG_KEY] = GREENELY_PROVIDER
            self.hass.config_entries.async_update_entry(self.entry, data=entry_data)

    async def async_apply_site_binding(self, binding: dict[str, Any] | None) -> None:
        """Apply one explicit site facility without changing shared credentials."""
        self._site_binding = dict(binding) if isinstance(binding, dict) else None
        self.lifecycle.invalidate_generation()
        self.lifecycle.cancel_tasks()
        if not self._site_binding:
            self.state = {**self.state, **self._empty_site_runtime_state()}
            return
        facility_id = self._site_binding.get("facility_id")
        if not isinstance(facility_id, str) or not facility_id:
            self.state = {**self.state, **self._empty_site_runtime_state()}
            return
        cached = await self.storage.async_load(
            facility_id=facility_id,
            provider=self._site_binding.get("provider") or GREENELY_PROVIDER,
            use_active_namespace=False,
        )
        if isinstance(cached, dict):
            self.state = self.storage.sanitize(cached)
            self.state["configured"] = True
            self.state["provider"] = self._site_binding.get("provider") or GREENELY_PROVIDER
            if _has_untrusted_legacy_history(self.state):
                self.state["summary"] = None
                self.state["invoices"] = []
                self.state["invoice_count"] = 0
                self.state["consumption"] = None
                source = self.state.setdefault("source", {})
                consumption = source.setdefault("consumption", {})
                consumption["samples"] = []
                await self.storage.async_save(self.state)
            return
        self.state = {**self.state, **self._empty_site_runtime_state()}

    def _empty_site_runtime_state(self) -> dict[str, Any]:
        return {
            "configured": False,
            "provider": None,
            "provider_name": None,
            "facility_id": None,
            "facility_name": None,
            "invoice_count": 0,
            "invoices": [],
            "summary": None,
            "consumption": None,
            "analysis": {},
            "consumption_error": None,
            "source": {"facility": None, "contracts": [], "invoices": [], "consumption": {"samples": []}},
            "error": None,
        }

    def _config(self) -> dict[str, Any]:
        config = self.entry.data.get(ELECTRICITY_PROVIDER_CONFIG_DATA_KEY, {})
        return config if isinstance(config, dict) else {}

    def _runtime_config(self) -> dict[str, Any]:
        """Use shared credentials with the active site's explicit facility."""
        config = dict(self._config())
        binding_value = getattr(self, "_site_binding", None)
        binding = binding_value if isinstance(binding_value, dict) else None
        facility_id = binding.get("facility_id") if binding else None
        if isinstance(facility_id, str) and facility_id:
            config["facility_id"] = facility_id
        return config

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
        preferences = await self.async_get_ui_preferences(user_id)
        return preferences["chart_layers"]

    async def async_set_chart_layers(self, user_id: str, updates: dict[str, bool]) -> dict[str, bool]:
        return (await self.async_update_ui_preferences(user_id, {"chart_layers": updates}))["chart_layers"]

    async def async_get_price_comparison(self, user_id: str) -> dict[str, bool]:
        preferences = await self.async_get_ui_preferences(user_id)
        return preferences["price_comparison"]

    async def async_set_price_comparison(self, user_id: str, updates: dict[str, bool]) -> dict[str, bool]:
        return (await self.async_update_ui_preferences(user_id, {"price_comparison": updates}))["price_comparison"]

    def _ui_preferences_from_stored(self, stored: Any, user_id: str) -> dict[str, Any]:
        users = stored.get("users", {}) if isinstance(stored, dict) else {}
        user_state = users.get(user_id, {}) if isinstance(users, dict) else {}
        if not isinstance(user_state, dict):
            user_state = {}

        def merge(defaults: dict[str, bool], key: str) -> dict[str, bool]:
            saved = user_state.get(key, {})
            return {
                name: saved[name] if isinstance(saved, dict) and isinstance(saved.get(name), bool) else default
                for name, default in defaults.items()
            }

        saved_visibility = user_state.get("dashboard_card_visibility", {})
        dashboard_card_visibility = {
            name: saved_visibility[name]
            if isinstance(saved_visibility, dict) and saved_visibility.get(name) in DASHBOARD_CARD_VISIBILITY_VALUES
            else default
            for name, default in DASHBOARD_CARD_VISIBILITY_DEFAULTS.items()
        }

        main_cards = merge(MAIN_CARD_DEFAULTS, "main_cards")
        return {
            "chart_layers": merge(CHART_LAYER_DEFAULTS, "chart_layers"),
            "price_comparison": merge(PRICE_COMPARISON_DEFAULTS, "price_comparison"),
            "phase_history_visible": merge(PHASE_HISTORY_VISIBLE_DEFAULTS, "phase_history_visible"),
            "phase_history_metric": (
                user_state.get("phase_history_metric")
                if user_state.get("phase_history_metric") in PHASE_HISTORY_METRICS
                else PHASE_HISTORY_METRIC_DEFAULT
            ),
            "configuration_cards_visible": (
                user_state.get("configuration_cards_visible")
                if isinstance(user_state.get("configuration_cards_visible"), bool)
                else CONFIGURATION_CARDS_VISIBLE_DEFAULT
            ),
            "main_cards": main_cards,
            "dashboard_card_visibility": dashboard_card_visibility,
        }

    async def async_get_ui_preferences(self, user_id: str) -> dict[str, Any]:
        """Load preferences without mutating the store."""
        stored = await self.chart_preferences_store.async_load()
        return self._ui_preferences_from_stored(stored, user_id)

    def _get_chart_preferences_lock(self) -> asyncio.Lock:
        lock = getattr(self, "_chart_preferences_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._chart_preferences_lock = lock
        return lock

    async def async_update_ui_preferences(self, user_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Atomically merge one or more preference domains for one user."""
        async with self._get_chart_preferences_lock():
            stored = await self.chart_preferences_store.async_load()
            users = stored.get("users", {}) if isinstance(stored, dict) else {}
            if not isinstance(users, dict):
                users = {}
            existing = users.get(user_id) if isinstance(users.get(user_id), dict) else {}
            current = self._ui_preferences_from_stored(stored, user_id)

            for domain, value in updates.items():
                if domain in ("chart_layers", "price_comparison", "phase_history_visible", "main_cards"):
                    defaults = {
                        "chart_layers": CHART_LAYER_DEFAULTS,
                        "price_comparison": PRICE_COMPARISON_DEFAULTS,
                        "phase_history_visible": PHASE_HISTORY_VISIBLE_DEFAULTS,
                        "main_cards": MAIN_CARD_DEFAULTS,
                    }[domain]
                    if isinstance(value, dict):
                        current[domain] = {
                            key: value[key] if key in value and isinstance(value[key], bool) else current[domain][key]
                            for key in defaults
                        }
                elif domain == "dashboard_card_visibility" and isinstance(value, dict):
                    current[domain] = {
                        key: value[key] if value.get(key) in DASHBOARD_CARD_VISIBILITY_VALUES else current[domain][key]
                        for key in DASHBOARD_CARD_VISIBILITY_DEFAULTS
                    }
                elif domain == "configuration_cards_visible" and isinstance(value, bool):
                    current[domain] = value
                elif domain == "phase_history_metric" and value in PHASE_HISTORY_METRICS:
                    current[domain] = value

            users[user_id] = {
                **existing,
                "chart_layers": current["chart_layers"],
                "price_comparison": current["price_comparison"],
                "phase_history_visible": current["phase_history_visible"],
                "phase_history_metric": current["phase_history_metric"],
                "configuration_cards_visible": current["configuration_cards_visible"],
                "main_cards": current["main_cards"],
                "dashboard_card_visibility": current["dashboard_card_visibility"],
            }
            await self.chart_preferences_store.async_save({"users": users})
            saved = await self.chart_preferences_store.async_load()
            return self._ui_preferences_from_stored(saved, user_id)

    async def async_get_phase_history_visible(self, user_id: str) -> dict[str, bool]:
        return (await self.async_get_ui_preferences(user_id))["phase_history_visible"]

    async def async_set_phase_history_visible(self, user_id: str, updates: dict[str, bool]) -> dict[str, bool]:
        return (await self.async_update_ui_preferences(user_id, {"phase_history_visible": updates}))["phase_history_visible"]

    async def async_get_configuration_cards_visible(self, user_id: str) -> bool:
        return (await self.async_get_ui_preferences(user_id))["configuration_cards_visible"]

    async def async_set_configuration_cards_visible(self, user_id: str, visible: bool) -> bool:
        return (await self.async_update_ui_preferences(user_id, {"configuration_cards_visible": bool(visible)}))["configuration_cards_visible"]

    async def async_get_main_cards(self, user_id: str) -> dict[str, bool]:
        return (await self.async_get_ui_preferences(user_id))["main_cards"]

    async def async_set_main_cards(self, user_id: str, updates: dict[str, bool]) -> dict[str, bool]:
        return (await self.async_update_ui_preferences(user_id, {"main_cards": updates}))["main_cards"]

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
        if getattr(self, "_site_binding", True) is None:
            return
        refresh_generation = self.lifecycle.generation if _generation is None else _generation
        config = self._runtime_config()
        if not GreenelyProvider.is_configured(config):
            return
        today = datetime.now().date()
        month_start = today.replace(day=1)
        month_end = today
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
            self.state["analysis"] = consumption_data.get("analysis", {})
            source = self.state.setdefault("source", {"facility": None, "contracts": [], "invoices": [], "consumption": {"samples": []}})
            source["analysis"] = self.state["analysis"]
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
            diagnostic_message = "Consumption refresh failed"
            if isinstance(getattr(err, "diagnostics", None), dict):
                diagnostic_message += " · Response shape: " + json.dumps(
                    err.diagnostics, sort_keys=True, separators=(",", ":")
                )
            await self.async_diagnostic(
                "ERROR", "consumption", "consumption_failed", diagnostic_message
            )
            await self.storage.async_save(self.state)
            self.hass.bus.async_fire(ELECTRICITY_PROVIDER_UPDATE_EVENT)

    async def async_refresh(self, reason: str = "manual_debug", _generation: int | None = None) -> dict[str, Any]:
        if getattr(self, "_site_binding", True) is None:
            return self.public_state()
        refresh_generation = self.lifecycle.generation if _generation is None else _generation
        config = self._runtime_config()
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
            "summary": self.state.get("summary") if refresh_data["invoices"] and _summary_has_attribution(self.state) else None,
            "processing": self.state.get("processing", self._empty_processing()),
            "consumption": self.state.get("consumption"),
            "analysis": self.state.get("analysis", {}),
            "consumption_error": self.state.get("consumption_error"),
            "source": source,
            "_new_invoice_keys": self.storage.new_invoice_keys(previous_invoices, refresh_data["invoices"]),
            "last_update": datetime.now(timezone.utc).isoformat(),
            "error": "partial_update" if refresh_data["failed_contracts"] else None,
        }
        await self.storage.async_save(self.state)
        self.hass.bus.async_fire(ELECTRICITY_PROVIDER_UPDATE_EVENT)
        await self.async_process_latest_invoice_if_needed(
            force=not _summary_has_attribution(self.state)
        )
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
        binding = getattr(self, "_site_binding", None)
        bound_facility_id = binding.get("facility_id") if isinstance(binding, dict) else None
        current_facility_id = (
            bound_facility_id
            if isinstance(bound_facility_id, str) and bound_facility_id
            else self.state.get("facility_id")
        )
        facility_changed = (
            isinstance(current_facility_id, str)
            and bool(current_facility_id)
            and current_facility_id != facility_id
        )
        invoices = [] if facility_changed else self.state.get("invoices", [])
        source = self.state.get("source", {})
        if not invoices and isinstance(source, dict):
            source = dict(source)
            source["consumption"] = {"samples": []}
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
            "analysis": {} if facility_changed else self.state.get("analysis", {}),
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
            facility = self.state.get("source", {}).get("facility", {})
            installation_id = facility.get("meter_id") if isinstance(facility, dict) else None
            result = await provider.async_process_invoice(
                config,
                latest["_contract_id"],
                invoice_key,
                latest.get("amount_due_sek"),
                str(installation_id) if installation_id is not None else None,
            )
        except GreenelyError as err:
            return await self._process_failure(invoice_key, err.code, processing["last_error_stage"] or "refresh")
        except GreenelyInvoiceError as err:
            return await self._process_failure(invoice_key, err.code, err.stage)
        self.state["summary"] = result["summary"]
        self.state["summary"].update({
            "_facility_id": self.state.get("facility_id"),
            "_contract_id": latest.get("_contract_id"),
            "_invoice_key": invoice_key,
            "_source_kind": "invoice",
        })
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
            "analysis": {},
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

    def provider_data(self) -> ProviderData:
        """Return the internal provider snapshot for backend calculations."""
        return self._provider_data()

    async def async_shutdown(self) -> None:
        await self.lifecycle.async_shutdown()


def _summary_has_attribution(state: dict[str, Any]) -> bool:
    summary = state.get("summary")
    if not isinstance(summary, dict):
        return False
    if summary.get("_source_kind") != "invoice":
        return False
    if summary.get("_facility_id") != state.get("facility_id"):
        return False
    invoice_key = summary.get("_invoice_key")
    contract_id = summary.get("_contract_id")
    invoices = state.get("invoices") if isinstance(state.get("invoices"), list) else []
    return any(
        item.get("_invoice_key") == invoice_key and item.get("_contract_id") == contract_id
        for item in invoices
        if isinstance(item, dict)
    )


def _has_untrusted_legacy_history(state: dict[str, Any]) -> bool:
    """Reject legacy provider history that has no invoice/facility provenance."""
    invoices = state.get("invoices") if isinstance(state.get("invoices"), list) else []
    summary = state.get("summary")
    source = state.get("source") if isinstance(state.get("source"), dict) else {}
    consumption = source.get("consumption") if isinstance(source.get("consumption"), dict) else {}
    samples = consumption.get("samples") if isinstance(consumption.get("samples"), list) else []
    if invoices:
        return False
    if isinstance(summary, dict) and summary:
        return True
    if not samples:
        return False
    return any(
        not isinstance(sample, dict) or not isinstance(sample.get("facility_id"), str)
        for sample in samples
    )
