"""Provider-neutral persistent storage for electricity data."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from homeassistant.helpers.storage import Store

from .provider_registry import sanitize_provider_source

ELECTRICITY_STORAGE_VERSION = 2
ELECTRICITY_STORE_KEY = "elrakning.elhandel"


def empty_electricity_store() -> dict[str, Any]:
    """Return an empty canonical store without touching Home Assistant storage."""
    return {
        "version": ELECTRICITY_STORAGE_VERSION,
        "facilities": {},
        "active_facility_id": None,
        "active_provider": None,
    }


def record_from_state(state: dict[str, Any]) -> dict[str, Any]:
    """Split runtime state into active data and durable history."""
    active = deepcopy(state)
    invoices = active.pop("invoices", [])
    source = active.get("source")
    samples: list[dict[str, Any]] = []
    if isinstance(source, dict):
        consumption = source.get("consumption")
        if isinstance(consumption, dict) and isinstance(consumption.get("samples"), list):
            samples = deepcopy(consumption["samples"])
            source.setdefault("consumption", {})["samples"] = []
    active["source"] = source if isinstance(source, dict) else _empty_source()
    return {
        "active": active,
        "history": {
            "invoices": deepcopy(invoices) if isinstance(invoices, list) else [],
            "consumption": {"samples": samples},
        },
    }


def state_from_record(record: dict[str, Any] | None) -> dict[str, Any] | None:
    """Rebuild the runtime state shape from one canonical provider record."""
    if not isinstance(record, dict) or not isinstance(record.get("active"), dict):
        return None
    state = deepcopy(record["active"])
    history = record.get("history") if isinstance(record.get("history"), dict) else {}
    invoices = history.get("invoices", [])
    state["invoices"] = deepcopy(invoices) if isinstance(invoices, list) else []
    source = state.get("source")
    if not isinstance(source, dict):
        source = _empty_source()
        state["source"] = source
    consumption_history = history.get("consumption")
    samples = (
        consumption_history.get("samples", [])
        if isinstance(consumption_history, dict)
        else consumption_history
    )
    source["consumption"] = {"samples": deepcopy(samples)} if isinstance(samples, list) else {"samples": []}
    return state


def history_metadata(store: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return provider-scoped history counts without exposing history contents."""
    if not _is_current_store(store):
        return []
    metadata: list[dict[str, Any]] = []
    for facility_id, facility in sorted(store["facilities"].items()):
        providers = facility.get("providers", {}) if isinstance(facility, dict) else {}
        if not isinstance(providers, dict):
            continue
        for provider, record in sorted(providers.items()):
            history = record.get("history", {}) if isinstance(record, dict) else {}
            invoices = history.get("invoices", []) if isinstance(history, dict) else []
            consumption = history.get("consumption", {}) if isinstance(history, dict) else {}
            samples = consumption.get("samples", []) if isinstance(consumption, dict) else []
            if isinstance(invoices, list) and isinstance(samples, list) and (invoices or samples):
                metadata.append({
                    "facility_id": str(facility_id),
                    "provider": str(provider),
                    "invoice_count": len(invoices),
                    "consumption_sample_count": len(samples),
                })
    return metadata


def _empty_source() -> dict[str, Any]:
    return {
        "facility": None,
        "contracts": [],
        "invoices": [],
        "consumption": {"samples": []},
    }


class StorageManager:
    """Persist active provider data and facility/provider-scoped history."""

    def __init__(self, hass) -> None:
        self.store = Store(hass, ELECTRICITY_STORAGE_VERSION, ELECTRICITY_STORE_KEY)

    async def async_load(
        self,
        facility_id: str | None = None,
        provider: str | None = None,
        use_active_namespace: bool = True,
    ) -> dict[str, Any] | None:
        """Load one active namespace from the canonical store."""
        stored = await self.store.async_load()
        if _is_current_store(stored):
            return state_from_record(_select_record(stored, facility_id, provider, use_active_namespace))
        return None

    async def async_save(
        self,
        state: dict[str, Any],
        facility_id: str | None = None,
        provider: str | None = None,
    ) -> None:
        """Save only the selected facility/provider namespace."""
        normalized = _sanitize_storage_state(state)
        namespace_facility = facility_id or normalized.get("facility_id")
        namespace_provider = provider or normalized.get("provider")
        if not _valid_namespace(namespace_facility, namespace_provider):
            raise ValueError("facility_id and provider are required for electricity storage")

        stored = await self.store.async_load()
        root = _canonical_root(stored) if _is_current_store(stored) else empty_electricity_store()
        facility = root.setdefault("facilities", {}).setdefault(
            str(namespace_facility), {"providers": {}}
        )
        facility.setdefault("providers", {})[str(namespace_provider)] = record_from_state(normalized)
        root["active_facility_id"] = str(namespace_facility)
        root["active_provider"] = str(namespace_provider)
        await self.store.async_save(root)

    async def async_remove_provider(
        self,
        facility_id: str,
        provider: str,
        purge_history: bool = False,
    ) -> None:
        """Clear active data, optionally purging only one namespace's history."""
        stored = await self.store.async_load()
        if not _is_current_store(stored):
            return
        root = deepcopy(stored)
        facility = root.get("facilities", {}).get(str(facility_id))
        providers = facility.get("providers", {}) if isinstance(facility, dict) else {}
        record = providers.get(str(provider))
        if not isinstance(record, dict):
            return
        if purge_history:
            providers.pop(str(provider), None)
            if not providers:
                root["facilities"].pop(str(facility_id), None)
            if (
                root.get("active_facility_id") == str(facility_id)
                and root.get("active_provider") == str(provider)
            ):
                root["active_facility_id"] = None
                root["active_provider"] = None
        else:
            record["active"] = _empty_active_state()
            if (
                root.get("active_facility_id") == str(facility_id)
                and root.get("active_provider") == str(provider)
            ):
                root["active_facility_id"] = None
                root["active_provider"] = None
        await self.store.async_save(root)

    async def async_history_metadata(self) -> list[dict[str, Any]]:
        """Return counts for provider-scoped history without exposing its contents."""
        stored = await self.store.async_load()
        return history_metadata(stored) if _is_current_store(stored) else []

    @staticmethod
    def sanitize(state: dict[str, Any]) -> dict[str, Any]:
        return _sanitize_storage_state(state)

    @staticmethod
    def merge_invoice_history(
        previous: list[dict[str, Any]],
        refreshed: list[dict[str, Any]],
        failed_contract_ids: set[str],
    ) -> list[dict[str, Any]]:
        return _merge_invoice_history(previous, refreshed, failed_contract_ids)

    @staticmethod
    def new_invoice_keys(
        previous: list[dict[str, Any]], refreshed: list[dict[str, Any]]
    ) -> list[str]:
        return _new_invoice_keys(previous, refreshed)


def _is_current_store(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("version") == ELECTRICITY_STORAGE_VERSION
        and isinstance(value.get("facilities"), dict)
    )


def _canonical_root(value: dict[str, Any]) -> dict[str, Any]:
    """Keep only current canonical fields when writing the store."""
    return {
        "version": ELECTRICITY_STORAGE_VERSION,
        "facilities": deepcopy(value.get("facilities", {})),
        "active_facility_id": value.get("active_facility_id"),
        "active_provider": value.get("active_provider"),
    }


def _select_record(
    store: dict[str, Any],
    facility_id: str | None,
    provider: str | None,
    use_active_namespace: bool = True,
) -> dict[str, Any] | None:
    selected_facility = facility_id or (store.get("active_facility_id") if use_active_namespace else None)
    selected_provider = provider or (store.get("active_provider") if use_active_namespace else None)
    if not selected_facility or not selected_provider:
        return None
    facility = store.get("facilities", {}).get(str(selected_facility), {})
    providers = facility.get("providers", {}) if isinstance(facility, dict) else {}
    return providers.get(str(selected_provider)) if isinstance(providers, dict) else None


def _empty_active_state() -> dict[str, Any]:
    return {
        "configured": False,
        "provider": None,
        "provider_name": None,
        "device_name": None,
        "facility_id": None,
        "facility_name": None,
        "source_type": "elhandel",
        "summary": None,
        "processing": {},
        "consumption": None,
        "consumption_error": None,
        "source": _empty_source(),
        "last_update": None,
        "error": None,
        "_new_invoice_keys": [],
    }


def _valid_namespace(facility_id: Any, provider: Any) -> bool:
    return isinstance(facility_id, str) and bool(facility_id) and isinstance(provider, str) and bool(provider)


def _sanitize_storage_state(state: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "configured", "provider", "source_type", "provider_name", "device_name", "facility_id",
        "facility_name", "invoices", "summary", "processing", "consumption", "consumption_error",
        "source", "last_update", "error", "_new_invoice_keys",
    )
    result = {key: state.get(key) for key in allowed}
    result["invoices"] = [
        _storage_invoice(item) for item in result.get("invoices", []) if isinstance(item, dict)
    ]
    result["invoice_count"] = len(result["invoices"])
    result["source"] = sanitize_provider_source(
        result.get("provider"), result.get("source") or _empty_source()
    )
    return result


def _storage_invoice(invoice: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "invoice_date", "month", "due_date", "state", "is_paid",
        "amount_due_ore", "amount_due_sek", "_invoice_key", "_contract_id", "_contract_status",
    )
    return {key: invoice[key] for key in allowed if key in invoice}


def _merge_invoice_history(
    previous: list[dict[str, Any]],
    refreshed: list[dict[str, Any]],
    failed_contract_ids: set[str],
) -> list[dict[str, Any]]:
    retained = [
        invoice for invoice in previous
        if invoice.get("_contract_id") in failed_contract_ids
    ]
    combined = {_invoice.get("_invoice_key"): _invoice for _invoice in retained + refreshed}
    return sorted(combined.values(), key=lambda item: item.get("invoice_date") or "", reverse=True)


def _new_invoice_keys(previous: list[dict[str, Any]], refreshed: list[dict[str, Any]]) -> list[str]:
    previous_keys = {item.get("_invoice_key") for item in previous}
    return [
        item["_invoice_key"] for item in refreshed
        if item.get("_invoice_key") not in previous_keys
    ]
