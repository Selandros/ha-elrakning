"""Public-state and small model helpers for electricity providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ProviderData:
    """Provider-neutral result returned by a future electricity provider."""

    provider: str | None = None
    facility: dict[str, Any] | None = None
    active_data: dict[str, Any] = field(default_factory=dict)
    invoices: list[dict[str, Any]] = field(default_factory=list)
    consumption: dict[str, Any] | None = None
    tariff: dict[str, Any] | None = None
    error: str | dict[str, Any] | None = None


def serialize_provider_state(
    provider_data: ProviderData,
    frontend_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize ProviderData to the existing public-state contract."""
    metadata = frontend_metadata if isinstance(frontend_metadata, Mapping) else {}
    active_data = provider_data.active_data
    configured = active_data.get("configured") is True
    if not configured:
        return {
            "configured": False,
            "provider": None,
            "source_type": None,
            "provider_name": None,
            "device_name": None,
            "facility_name": None,
            "invoice_count": 0,
            "invoice_history": [],
            "latest_invoice": None,
            "last_update": None,
            "error": None,
            "summary": None,
            "processing_status": {"error": False, "stage": None, "last_attempt": None},
            "consumption": None,
            "consumption_error": False,
        }

    invoices = [item for item in provider_data.invoices if isinstance(item, dict)]
    latest = max(invoices, key=lambda item: item.get("invoice_date") or "", default=None)
    facility = provider_data.facility if isinstance(provider_data.facility, Mapping) else {}
    processing = active_data.get("processing")
    error = provider_data.error
    if isinstance(error, dict):
        public_error = error.get("state") if "state" in error else (
            error if not ("processing" in error or "consumption" in error) else None
        )
    else:
        public_error = error if isinstance(error, str) else None
    return {
        "configured": True,
        "provider": provider_data.provider,
        "source_type": metadata.get("source_type"),
        "provider_name": metadata.get("provider_name"),
        "device_name": metadata.get("device_name"),
        "facility_name": metadata.get("facility_name") or facility.get("name") or facility.get("address"),
        "invoice_count": len(invoices),
        "invoice_history": [_public_invoice(invoice) for invoice in invoices],
        "latest_invoice": _public_invoice(latest) if latest else None,
        "last_update": active_data.get("last_update"),
        "error": public_error,
        "summary": _public_provider_summary(provider_data),
        "processing_status": _public_processing_status(processing),
        "consumption": _public_provider_consumption(provider_data),
        "consumption_error": bool(error.get("consumption")) if isinstance(error, dict) else False,
    }


def _public_provider_summary(provider_data: ProviderData) -> dict[str, Any] | None:
    active_data = provider_data.active_data
    if not active_data.get("summary_present"):
        return None
    tariff = provider_data.tariff if isinstance(provider_data.tariff, Mapping) else {}
    period = active_data.get("latest_period") if isinstance(active_data.get("latest_period"), Mapping) else {}
    return {
        "agreement_name": active_data.get("agreement_name"),
        "tariff": {key: tariff.get(key) for key in ("variable_cost_ore_per_kwh_incl_vat", "fixed_fee_incl_vat_per_month")},
        "latest_period": {key: period.get(key) for key in ("period_start", "period_end", "weighted_spot_average_ore_per_kwh", "credit_closing_sek", "amount_due_sek")},
    }


def _public_provider_consumption(provider_data: ProviderData) -> dict[str, Any] | None:
    consumption = provider_data.consumption
    if not isinstance(consumption, Mapping):
        return None
    return _public_consumption(consumption.get("summary"))


def _safe_facility_name(facility: dict[str, Any]) -> str | None:
    for key in ("name", "address"):
        value = facility.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _public_invoice(invoice: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "invoice_date", "month", "billing_period", "due_date", "state", "is_paid",
        "amount_due_ore", "amount_due_sek", "period_cost_sek",
        "period_cost_before_credits_sek", "credits_applied_sek", "source",
    )
    return {key: invoice[key] for key in allowed if key in invoice}


def _public_processing_status(processing: Any) -> dict[str, Any]:
    if not isinstance(processing, dict):
        return {"error": False, "stage": None, "last_attempt": None}
    return {
        "error": bool(processing.get("last_error")),
        "stage": processing.get("last_error_stage") if processing.get("last_error") else None,
        "last_attempt": processing.get("last_error_at") or processing.get("_last_successful_parse_at"),
    }


def _public_consumption(consumption: Any) -> dict[str, Any] | None:
    if not isinstance(consumption, dict):
        return None
    return {key: consumption.get(key) for key in ("month", "month_to_date_kwh", "latest_sample_at", "last_update")}
