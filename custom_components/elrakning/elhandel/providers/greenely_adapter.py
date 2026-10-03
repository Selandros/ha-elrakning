"""Convert existing Greenely state into the provider-neutral data contract."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from ..models import ProviderData


def provider_data_from_greenely_state(state: Mapping[str, Any]) -> ProviderData:
    """Build ProviderData from the current in-memory Greenely state."""
    source = _mapping(state.get("source"))
    source_consumption = _mapping(source.get("consumption"))
    analysis = _mapping(state.get("analysis"))
    facility = _facility(state, source)
    invoices = _list_of_mappings(state.get("invoices"))
    consumption_state = _mapping(state.get("consumption"))
    samples = _list_of_mappings(source_consumption.get("samples"))
    summary = _mapping(state.get("summary"))
    latest_period = summary.get("latest_period") if isinstance(summary.get("latest_period"), Mapping) else {}
    summary_contract_id = summary.get("_contract_id")
    invoices = _list_of_mappings(state.get("invoices"))
    summary_attributed = (
        summary.get("_source_kind") == "invoice"
        and summary.get("_facility_id") == state.get("facility_id")
        and any(
            item.get("_invoice_key") == summary.get("_invoice_key")
            and item.get("_contract_id") == summary_contract_id
            for item in invoices
        )
    )
    current_contract = _current_contract(source.get("contracts"), summary_contract_id)

    active_data = {
        "configured": bool(state.get("configured")),
        "contracts": _list_of_mappings(source.get("contracts")),
        "source_invoices": _list_of_mappings(source.get("invoices")),
        "agreement_name": summary.get("agreement_name"),
        "latest_period": latest_period,
        "summary_present": isinstance(state.get("summary"), Mapping),
        "customer_price_eligible": summary_attributed and current_contract,
        "processing": _mapping(state.get("processing")),
        "last_update": state.get("last_update"),
    }

    consumption = None
    if consumption_state or samples:
        consumption = {
            "summary": consumption_state or None,
            "samples": samples,
        }

    return ProviderData(
        provider=_string_or_none(state.get("provider")),
        facility=facility,
        active_data=active_data,
        invoices=invoices,
        consumption=consumption,
        analysis=analysis,
        tariff=_mapping(summary.get("tariff")) or None,
        error=_error_state(state),
    )


def _facility(state: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any] | None:
    facility = deepcopy(source.get("facility")) if isinstance(source.get("facility"), Mapping) else {}
    facility_id = _string_or_none(state.get("facility_id"))
    facility_name = _string_or_none(state.get("facility_name"))
    if facility_id is not None:
        facility.setdefault("id", facility_id)
    if facility_name is not None:
        facility.setdefault("name", facility_name)
    return facility or None


def _error_state(state: Mapping[str, Any]) -> str | dict[str, Any] | None:
    errors: dict[str, Any] = {}
    if state.get("error") is not None:
        errors["state"] = deepcopy(state["error"])
    processing = _mapping(state.get("processing"))
    if processing.get("last_error") is not None:
        errors["processing"] = {
            "error": deepcopy(processing["last_error"]),
            "stage": deepcopy(processing.get("last_error_stage")),
            "at": deepcopy(processing.get("last_error_at")),
        }
    if state.get("consumption_error") is not None:
        errors["consumption"] = deepcopy(state["consumption_error"])
    if not errors:
        return None
    if set(errors) == {"state"}:
        return errors["state"]
    return errors


def _mapping(value: Any) -> dict[str, Any]:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [deepcopy(dict(item)) for item in value if isinstance(item, Mapping)]


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _current_contract(contracts: Any, contract_id: str | None) -> bool:
    """Return true only for an attributed contract effective now."""
    for contract in _list_of_mappings(contracts):
        if contract_id and str(contract.get("_contract_id")) != str(contract_id):
            continue
        status = str(contract.get("status") or "").upper()
        if status in {"FUTURE", "INACTIVE", "ENDED"}:
            continue
        start = contract.get("start_date")
        try:
            start_at = datetime.fromtimestamp(float(start), tz=timezone.utc) if start is not None else None
        except (TypeError, ValueError, OverflowError):
            start_at = None
        if start_at is not None and start_at > datetime.now(timezone.utc):
            continue
        return True
    return False
