"""Effective-dated, site-scoped grid tariff facts.

The timeline never infers historical validity. A record is usable only when
the provider supplied an effective start and the decision-time evidence is
causal for the requested slot.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo


SCHEMA = "elrakning.grid_tariff_timeline.v1"


def _moment(value: Any, timezone_name: str = "Europe/Stockholm") -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min, ZoneInfo(timezone_name))
    else:
        return None
    if parsed.tzinfo is None:
        if isinstance(value, str) and len(value) == 10:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
        else:
            return None
    return parsed.astimezone(timezone.utc)


def _date_boundary(value: Any, timezone_name: str = "Europe/Stockholm") -> str | None:
    parsed = _moment(value, timezone_name)
    return parsed.isoformat() if parsed else None


def build_grid_tariff_record(
    *,
    site_id: str | None,
    binding: dict[str, Any] | None,
    state: dict[str, Any] | None,
    captured_at: datetime,
) -> dict[str, Any] | None:
    """Project one provider state into an immutable timeline fact."""
    if not isinstance(state, dict) or not isinstance(binding, dict):
        return None
    agreement = state.get("agreement")
    grid_price = state.get("grid_price")
    facility = state.get("facility")
    if not isinstance(agreement, dict) or not isinstance(grid_price, dict):
        return None
    if not isinstance(site_id, str) or not site_id or not isinstance(facility, dict):
        return None
    valid_from = _date_boundary(agreement.get("start_date"))
    valid_to = _date_boundary(agreement.get("end_date"))
    known_at = _moment(state.get("updated_at")) or _moment(captured_at)
    captured = _moment(captured_at)
    if not valid_from or not known_at or not captured:
        return None
    payload = {
        "site_id": site_id,
        "provider": "eon",
        "config_entry_id": binding.get("config_entry_id"),
        "facility": facility,
        "agreement": agreement,
        "grid_price": grid_price,
        "valid_from": valid_from,
        "valid_to": valid_to,
    }
    source_generation_id = "eon-tariff-" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()[:32]
    return {
        "schema": SCHEMA,
        "site_id": site_id,
        "provider": "eon",
        "source_generation_id": source_generation_id,
        "known_at": known_at.isoformat(),
        "captured_at": captured.isoformat(),
        "valid_from": valid_from,
        "valid_to": valid_to,
        "source_status": agreement.get("source_status") or agreement.get("status"),
        "agreement": deepcopy(agreement),
        "grid_price": deepcopy(grid_price),
        "provenance": {
            "provider": "eon",
            "config_entry_id": binding.get("config_entry_id"),
            "facility": deepcopy(facility),
            "identity_strength": "strong" if binding.get("config_entry_id") and facility else "weak",
            "origin": "eon_grid_state",
        },
    }


def build_user_confirmed_grid_tariff_record(
    *,
    site_id: str | None,
    binding: dict[str, Any] | None,
    state: dict[str, Any] | None,
    fact: dict[str, Any] | None,
    captured_at: datetime,
) -> dict[str, Any] | None:
    """Project one explicitly verified tariff fact into the same timeline contract."""
    if not isinstance(fact, dict) or not isinstance(binding, dict):
        return None
    expected_site_id = fact.get("site_id")
    if not isinstance(site_id, str) or site_id != expected_site_id:
        return None
    if fact.get("provider") != "eon" or fact.get("source_status") != "MANUALLY_VERIFIED":
        return None
    facility = fact.get("facility")
    agreement = fact.get("agreement")
    grid_price = fact.get("grid_price")
    binding_facility = binding.get("facility")
    runtime_agreement = state.get("agreement") if isinstance(state, dict) else None
    runtime_facility = state.get("facility") if isinstance(state, dict) else None
    if not isinstance(facility, dict) or not isinstance(agreement, dict) or not isinstance(grid_price, dict):
        return None
    if not isinstance(binding_facility, dict) or not isinstance(runtime_agreement, dict) or not isinstance(runtime_facility, dict):
        return None
    identity_fields = ("installation_identifier", "price_area", "grid_area", "fuse_ampere")
    if any(
        binding_facility.get(key) != facility.get(key)
        or runtime_facility.get(key) != facility.get(key)
        for key in identity_fields
    ):
        return None
    if runtime_agreement.get("name") != fact.get("product_name"):
        return None
    valid_from = _date_boundary(agreement.get("start_date"))
    valid_to = _date_boundary(agreement.get("end_date"))
    captured = _moment(captured_at)
    if not valid_from or not valid_to or not captured:
        return None
    payload = {
        "site_id": site_id,
        "provider": "eon",
        "config_entry_id": binding.get("config_entry_id"),
        "facility": facility,
        "agreement": agreement,
        "grid_price": grid_price,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "source_status": "MANUALLY_VERIFIED",
        "provenance": fact.get("provenance"),
    }
    source_generation_id = "eon-manual-tariff-" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()[:32]
    return {
        "schema": SCHEMA,
        "site_id": site_id,
        "provider": "eon",
        "source_generation_id": source_generation_id,
        "known_at": captured.isoformat(),
        "captured_at": captured.isoformat(),
        "valid_from": valid_from,
        "valid_to": valid_to,
        "source_status": "MANUALLY_VERIFIED",
        "agreement": deepcopy(agreement),
        "grid_price": deepcopy(grid_price),
        "provenance": {
            **deepcopy(fact.get("provenance") or {}),
            "provider": "eon",
            "config_entry_id": binding.get("config_entry_id"),
            "facility": deepcopy(facility),
            "identity_strength": "strong",
            "origin": "user_confirmed",
            "provider_api_verified": False,
        },
    }


def merge_grid_tariff_record(records: list[dict[str, Any]] | None, record: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Append a changed fact while keeping identical generations idempotent."""
    existing = [item for item in records or [] if isinstance(item, dict)]
    if not isinstance(record, dict):
        return existing
    key = (record.get("site_id"), record.get("source_generation_id"))
    if any((item.get("site_id"), item.get("source_generation_id")) == key for item in existing):
        return existing
    return [*existing, deepcopy(record)]


def resolve_grid_tariff(
    records: list[dict[str, Any]] | None,
    *,
    site_id: str,
    at: datetime,
    decision_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Resolve one tariff without using future knowledge or inferred validity."""
    target = _moment(at)
    decision = _moment(decision_at) if decision_at is not None else target
    if target is None or decision is None:
        return None
    candidates = []
    for record in records or []:
        if not isinstance(record, dict) or record.get("site_id") != site_id:
            continue
        known = _moment(record.get("known_at"))
        start = _moment(record.get("valid_from"))
        end = _moment(record.get("valid_to")) if record.get("valid_to") else None
        if not known or not start or known > decision or start > target or (end and target >= end):
            continue
        price = record.get("grid_price")
        if not isinstance(price, dict):
            continue
        candidates.append((start, known, str(record.get("source_generation_id") or ""), record))
    if not candidates:
        return None
    # Resolve the latest causally known revision for the applicable interval.
    # Input order must never decide which historical revision wins.
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    chosen = candidates[-1][3]
    return deepcopy(chosen)
