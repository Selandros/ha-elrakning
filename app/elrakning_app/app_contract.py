"""Versioned, fail-closed Core-to-App shadow contract."""

from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any


CONTRACT_VERSION = 1
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


class AppContractError(ValueError):
    """Raised when a Core/App payload is not safe to consume."""


def _require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AppContractError(f"{field}_must_be_object")
    return value


def _require_text(value: Any, field: str, *, max_length: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise AppContractError(f"{field}_must_be_nonempty_text")
    return value


def parse_contract_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise AppContractError(f"{field}_must_be_iso_datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AppContractError(f"{field}_must_be_iso_datetime") from error
    if parsed.tzinfo is None:
        raise AppContractError(f"{field}_must_have_timezone")
    return parsed.astimezone(timezone.utc)


def _contract_version(payload: dict[str, Any]) -> None:
    if payload.get("contract_version") != CONTRACT_VERSION:
        raise AppContractError("unsupported_contract_version")


def validate_state_snapshot(payload: Any) -> dict[str, Any]:
    """Validate and return a bounded Core state snapshot."""
    value = _require_mapping(payload, "snapshot")
    _contract_version(value)
    _require_text(value.get("site_id"), "site_id", max_length=128)
    _require_text(value.get("source_generation_id"), "source_generation_id")
    _require_text(value.get("unit"), "unit", max_length=64)
    _require_text(value.get("sign_convention"), "sign_convention", max_length=128)
    _require_text(value.get("status"), "status", max_length=32)
    _require_mapping(value.get("entity_source_identity"), "entity_source_identity")
    quality = _require_mapping(value.get("quality"), "quality")
    if len(quality) > 32:
        raise AppContractError("quality_too_large")

    captured_at = parse_contract_datetime(value.get("captured_at"), "captured_at")
    observed_at = parse_contract_datetime(value.get("observed_at"), "observed_at")
    known_at = parse_contract_datetime(value.get("known_at"), "known_at")
    decision_context = _require_mapping(value.get("decision_context"), "decision_context")
    decision_at = parse_contract_datetime(
        decision_context.get("decision_at"), "decision_at"
    )
    if known_at > decision_at:
        raise AppContractError("known_at_after_decision_at")
    if captured_at < known_at:
        raise AppContractError("captured_at_before_known_at")

    snapshot_value = value.get("value")
    if snapshot_value is not None:
        if isinstance(snapshot_value, bool) or not isinstance(snapshot_value, (int, float)):
            raise AppContractError("value_must_be_numeric_or_null")
        if not math.isfinite(float(snapshot_value)):
            raise AppContractError("value_must_be_finite")
    elif value.get("status") in {"available", "valid"}:
        raise AppContractError("available_value_must_not_be_null")

    return dict(value)


def validate_app_result(
    payload: Any,
    *,
    expected_site_id: str,
    expected_source_generation_id: str,
    decision_at: datetime,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate an App result against the exact Core request context."""
    value = _require_mapping(payload, "result")
    _contract_version(value)
    if value.get("site_id") != expected_site_id:
        raise AppContractError("site_id_mismatch")
    if value.get("source_generation_id") != expected_source_generation_id:
        raise AppContractError("source_generation_id_mismatch")
    _require_text(value.get("status"), "status", max_length=32)
    if not isinstance(value.get("revision"), int) or isinstance(value.get("revision"), bool) or value["revision"] < 1:
        raise AppContractError("revision_must_be_positive_integer")
    fingerprint = value.get("fingerprint")
    if not isinstance(fingerprint, str) or not _FINGERPRINT_RE.fullmatch(fingerprint):
        raise AppContractError("fingerprint_must_be_sha256")
    provenance = _require_mapping(value.get("provenance"), "provenance")
    _require_text(provenance.get("source"), "provenance_source")
    validity = _require_mapping(value.get("validity_interval"), "validity_interval")
    valid_from = parse_contract_datetime(validity.get("from"), "validity_interval.from")
    valid_to = validity.get("to")
    if valid_to is not None:
        valid_to = parse_contract_datetime(valid_to, "validity_interval.to")
        if valid_to <= valid_from:
            raise AppContractError("invalidity_interval")
    known_at = parse_contract_datetime(value.get("known_at"), "known_at")
    decision_at = decision_at.astimezone(timezone.utc)
    if known_at > decision_at:
        raise AppContractError("known_at_after_decision_at")
    if now is not None and valid_to is not None and valid_to <= now.astimezone(timezone.utc):
        raise AppContractError("stale_result")
    if not isinstance(value.get("fail_closed"), bool):
        raise AppContractError("fail_closed_must_be_boolean")
    diagnostics = _require_mapping(value.get("diagnostics"), "diagnostics")
    if len(diagnostics) > 32:
        raise AppContractError("diagnostics_too_large")
    return dict(value)
