"""Site-scoped economic external input frame producers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from copy import deepcopy
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .canonical_storage import DATASET_VERSION, SCHEMA_VERSION, CanonicalStorage
from .const import DOMAIN
from .elnat.eon_models import facility_identity

UTC = timezone.utc

_EON_COMPONENTS = (
    ("economic.grid.import.transfer", "transfer_ore_per_kwh_gross", 0.01, "SEK/kWh", "positive_import_cost"),
    ("economic.grid.import.energy_tax", "energy_tax_ore_per_kwh_gross", 0.01, "SEK/kWh", "positive_import_cost"),
    ("economic.grid.fixed.subscription", "fixed_monthly_sek", 1.0, "SEK/month", "positive_fixed_cost"),
)


def _as_aware_utc(value: datetime, error_code: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(error_code)
    return value.astimezone(UTC)


def _parse_aware_utc(value: Any, error_code: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(error_code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise ValueError(error_code) from err
    return _as_aware_utc(parsed, error_code)


def _normalized_facility_context(facility: Any) -> dict[str, Any] | None:
    if not isinstance(facility, dict):
        return None
    address = facility.get("address")
    if not isinstance(address, dict):
        return None
    normalized_address = {
        key: str(address.get(key)).strip()
        for key in ("street", "city", "postal_code")
        if address.get(key) is not None and str(address.get(key)).strip()
    }
    if not normalized_address:
        return None
    context = {
        "address": normalized_address,
        "grid_area": str(facility.get("grid_area")).strip() if facility.get("grid_area") else None,
        "price_area": str(facility.get("price_area")).strip() if facility.get("price_area") else None,
    }
    if not context["grid_area"] and not context["price_area"]:
        return None
    return context


def _facility_context_hash(context: dict[str, Any]) -> str:
    payload = json.dumps(context, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def matching_grid_binding_targets(
    site_identity_state: Any,
    runtime_state: Any,
    config_entry_id: str,
) -> list[tuple[str, dict[str, Any]]]:
    """Return all collection-enabled sites bound to the exact runtime E.ON source."""
    if (
        not isinstance(site_identity_state, dict)
        or not isinstance(runtime_state, dict)
        or not isinstance(config_entry_id, str)
        or not config_entry_id
    ):
        return []
    runtime_context = _normalized_facility_context(runtime_state.get("facility"))
    runtime_identity = facility_identity(runtime_state.get("facility"))
    configs = site_identity_state.get("site_configs")
    if runtime_context is None or not isinstance(configs, dict):
        return []
    targets: list[tuple[str, dict[str, Any]]] = []
    for site_id, config in configs.items():
        if not isinstance(config, dict) or config.get("collection_enabled") is not True:
            continue
        bindings = config.get("bindings")
        binding = bindings.get("grid") if isinstance(bindings, dict) else None
        if (
            not isinstance(binding, dict)
            or binding.get("provider") != "eon"
            or binding.get("config_entry_id") != config_entry_id
            or (
                facility_identity(binding.get("facility")) != runtime_identity
                if runtime_identity and facility_identity(binding.get("facility"))
                else _normalized_facility_context(binding.get("facility")) != runtime_context
            )
        ):
            continue
        targets.append((str(site_id), deepcopy(binding)))
    return sorted(targets, key=lambda item: item[0])


def resolve_grid_binding_site_id(site_identity_state: Any, binding: Any) -> str | None:
    """Resolve one explicit grid binding to exactly one site without active-site context."""
    if not isinstance(site_identity_state, dict) or not isinstance(binding, dict):
        return None
    fingerprint = binding.get("binding_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        return None
    matches: list[str] = []
    configs = site_identity_state.get("site_configs")
    if not isinstance(configs, dict):
        return None
    for site_id, config in configs.items():
        bindings = config.get("bindings") if isinstance(config, dict) else None
        candidate = bindings.get("grid") if isinstance(bindings, dict) else None
        if isinstance(candidate, dict) and candidate.get("binding_fingerprint") == fingerprint:
            matches.append(str(site_id))
    return matches[0] if len(matches) == 1 else None


def build_eon_grid_economic_frames(
    site_id: str,
    binding: dict[str, Any],
    state: dict[str, Any],
    captured_at: datetime,
) -> list[dict[str, Any]]:
    """Build truthful E.ON active-tariff snapshots without inferring local validity."""
    if not isinstance(site_id, str) or not site_id:
        raise ValueError("economic_site_id_missing")
    if not isinstance(binding, dict) or binding.get("provider") != "eon":
        return []
    if not isinstance(state, dict):
        return []

    agreement = state.get("agreement")
    grid_price = state.get("grid_price")
    if not isinstance(agreement, dict) or agreement.get("status") != "active":
        return []
    if not isinstance(grid_price, dict):
        return []
    if (
        grid_price.get("source") != "grouped_contracts"
        or grid_price.get("vat_included") is not True
        or grid_price.get("price_basis") != "gross"
    ):
        return []

    config_entry_id = binding.get("config_entry_id")
    if not isinstance(config_entry_id, str) or not config_entry_id:
        return []

    bound_context = _normalized_facility_context(binding.get("facility"))
    runtime_context = _normalized_facility_context(state.get("facility"))
    if bound_context is None or runtime_context is None or bound_context != runtime_context:
        return []

    captured_utc = _as_aware_utc(captured_at, "economic_capture_time_invalid")
    fetched_utc = _parse_aware_utc(state.get("updated_at"), "economic_fetched_time_invalid")
    if fetched_utc > captured_utc:
        raise ValueError("economic_snapshot_fetched_after_capture")

    context_hash = _facility_context_hash(bound_context)
    native_identity = facility_identity(binding.get("facility"))
    identity_strength = "strong" if native_identity else "medium"
    identity_payload = {
        "provider": "eon",
        "config_entry_id": config_entry_id,
        "facility_context_sha256": context_hash,
        "facility_identity": native_identity,
    }
    identity_key = json.dumps(identity_payload, sort_keys=True, separators=(",", ":"))
    snapshot_key = fetched_utc.isoformat()
    source_start_date = agreement.get("start_date")
    source_end_date = agreement.get("end_date")

    frames: list[dict[str, Any]] = []
    for logical_role, field, multiplier, unit, sign_convention in _EON_COMPONENTS:
        raw_value = grid_price.get(field)
        if raw_value is None:
            continue
        try:
            numeric = float(raw_value)
        except (TypeError, ValueError) as err:
            raise ValueError("economic_component_invalid") from err
        if not math.isfinite(numeric) or numeric < 0:
            raise ValueError("economic_component_invalid")
        value = numeric * multiplier
        generation_seed = f"{site_id}|{logical_role}|{identity_key}"
        generation_id = "econ-" + hashlib.sha256(generation_seed.encode()).hexdigest()[:32]
        semantic_key = f"{site_id}|{logical_role}|{generation_id}|{snapshot_key}"
        content_seed = f"{semantic_key}|{value:.12g}|{unit}|{sign_convention}"
        frame_id = "frame-" + hashlib.sha256(content_seed.encode()).hexdigest()[:32]
        point_id = "point-" + hashlib.sha256(content_seed.encode()).hexdigest()[:32]
        provenance = {
            "origin_type": "eon_grouped_contracts_runtime",
            "provider": "eon",
            "config_entry_id": config_entry_id,
            "facility_context_sha256": context_hash,
            "facility_identity": native_identity,
            "identity_strength": identity_strength,
            "identity_provenance": "native_facility_binding" if native_identity else "normalized_facility_context",
            "binding_fingerprint": binding.get("binding_fingerprint"),
            "vat_included": True,
            "price_basis": "gross",
            "source_subtitle": grid_price.get("source_subtitle"),
            "agreement": {
                "status": "active",
                "type": agreement.get("type"),
                "name": agreement.get("name"),
                "source_status": agreement.get("source_status"),
            },
            "effective_validity": {
                "mode": "active_snapshot_at_fetched_at",
                "source_start_date": source_start_date,
                "source_end_date": source_end_date,
                "utc_boundaries_resolved": False,
                "reason": "provider_validity_is_calendar_date_only",
            },
        }
        frame = {
            "frame_id": frame_id,
            "schema_version": SCHEMA_VERSION,
            "dataset_version": DATASET_VERSION,
            "semantic_key": semantic_key,
            "revision": 1,
            "source_generation_id": generation_id,
            "source_scope": "site",
            "site_id": site_id,
            "logical_role": logical_role,
            "classification": "published",
            "published_at": None,
            "fetched_at": fetched_utc,
            "known_at": captured_utc,
            "captured_at": captured_utc,
            "valid_from": None,
            "valid_to": None,
            "quality_status": "good",
            "quality": {
                "status": "good",
                "validity_mode": "active_snapshot_at_fetched_at",
                "utc_period_boundaries_resolved": False,
            },
            "provenance": provenance,
            "payload_schema": "eon.grid_economic_active_snapshot.v1",
        }
        point = {
            "point_id": point_id,
            "point_key": snapshot_key,
            "valid_at": fetched_utc,
            "value": value,
            "unit": unit,
            "quality_status": "good",
            "point": {
                "source_field": field,
                "source_value": numeric,
                "source_unit": "ore/kWh" if multiplier == 0.01 else "SEK/month",
                "sign_convention": sign_convention,
                "vat_included": True,
                "price_basis": "gross",
            },
        }
        source_target = {
            "site_id": site_id,
            "logical_role": logical_role,
            "generation_id": generation_id,
            "source_identity": {
                "identity_key": identity_key,
                "identity_strength": "medium",
                "identity_provenance": "eon_config_entry_and_normalized_facility_context",
            },
        }
        frames.append({"frame": frame, "points": [point], "source_target": source_target})
    return frames


def _insert_with_revision(
    storage: CanonicalStorage,
    frame: dict[str, Any],
    points: list[dict[str, Any]],
) -> bool:
    latest = storage.latest_external_frame(frame["semantic_key"])
    if latest:
        frame["revision"] = latest[1]
        frame["frame_id"] = latest[0]
        frame["supersedes_frame_id"] = latest[2]
        try:
            return storage.insert_external_frame(frame, points)
        except ValueError as error:
            if str(error) != "canonical_frame_revision_conflict":
                raise
            frame["revision"] = latest[1] + 1
            frame["supersedes_frame_id"] = latest[0]
            frame["frame_id"] = "frame-" + hashlib.sha256(
                (
                    f"{frame['semantic_key']}|{frame['revision']}|"
                    + "|".join(
                        point["point_key"] + f"={point['value']:.12g}:{point['unit']}"
                        for point in points
                    )
                ).encode()
            ).hexdigest()[:32]
    return storage.insert_external_frame(frame, points)


def persist_eon_grid_economic_snapshot(
    storage: CanonicalStorage,
    site_id: str,
    binding: dict[str, Any],
    state: dict[str, Any],
    captured_at: datetime,
) -> int:
    """Persist all available active E.ON economic components as site frames."""
    built = build_eon_grid_economic_frames(site_id, binding, state, captured_at)
    inserted = 0
    for item in built:
        storage.ensure_source_generation(item["source_target"], captured_at)
        inserted += int(_insert_with_revision(storage, item["frame"], item["points"]))
    return inserted


def persist_eon_grid_economic_snapshot_path(
    storage_path: str | Path,
    site_id: str,
    binding: dict[str, Any],
    state: dict[str, Any],
    captured_at: datetime,
) -> int:
    """Use a dedicated SQLite connection so collector writes never share a connection."""
    storage = CanonicalStorage(storage_path)
    storage.open()
    try:
        return persist_eon_grid_economic_snapshot(storage, site_id, binding, state, captured_at)
    finally:
        storage.close()


def _persist_eon_grid_economic_snapshot_with_retry(
    storage_path: str | Path,
    site_id: str,
    binding: dict[str, Any],
    state: dict[str, Any],
    captured_at: datetime,
) -> int:
    """Retry only the idempotent snapshot write on transient SQLite contention."""
    for attempt in range(2):
        try:
            return persist_eon_grid_economic_snapshot_path(
                storage_path, site_id, binding, state, captured_at
            )
        except sqlite3.OperationalError as err:
            if "locked" not in str(err).lower() or attempt:
                raise
            time.sleep(0.1)
    raise RuntimeError("eon_grid_snapshot_retry_exhausted")


async def _async_capture_eon_grid_economic_snapshot(hass: Any, captured_at: datetime) -> None:
    domain_data = getattr(hass, "data", {}).get(DOMAIN, {})
    site_identity = domain_data.get("site_identity_manager")
    grid_manager = domain_data.get("grid_manager")
    collector = domain_data.get("canonical_collector")
    if site_identity is None or grid_manager is None or collector is None:
        return
    provider = getattr(grid_manager, "provider", None)
    state = getattr(provider, "state", None)
    entry = getattr(grid_manager, "entry", None)
    config_entry_id = getattr(entry, "entry_id", None)
    if not isinstance(state, dict) or not isinstance(config_entry_id, str):
        return
    state_snapshot = deepcopy(state)
    site_state = getattr(site_identity, "state", None)
    has_explicit_facility_states = hasattr(
        getattr(grid_manager, "provider", None), "state_for_binding"
    )
    if has_explicit_facility_states and isinstance(site_state, dict):
        targets = []
        configs = site_state.get("site_configs")
        for site_id, config in configs.items() if isinstance(configs, dict) else ():
            binding = config.get("bindings", {}).get("grid") if isinstance(config, dict) else None
            if (
                isinstance(config, dict)
                and config.get("collection_enabled") is True
                and isinstance(binding, dict)
                and binding.get("provider") == "eon"
                and binding.get("config_entry_id") == config_entry_id
            ):
                targets.append((str(site_id), deepcopy(binding)))
        targets.sort(key=lambda item: item[0])
    else:
        targets = matching_grid_binding_targets(site_state, state_snapshot, config_entry_id)
    if not targets:
        return
    storage_path = getattr(getattr(collector, "storage", None), "path", None)
    if storage_path is None:
        return
    for site_id, binding in targets:
        explicit_state = None
        if has_explicit_facility_states:
            explicit_state = grid_manager.state_for_binding(binding)
            if not isinstance(explicit_state, dict):
                continue
        if isinstance(explicit_state, dict):
            state_snapshot = deepcopy(explicit_state)
        try:
            await hass.async_add_executor_job(
                _persist_eon_grid_economic_snapshot_with_retry,
                storage_path,
                site_id,
                binding,
                state_snapshot,
                captured_at,
            )
        except Exception as err:
            diagnostic = getattr(domain_data.get("manager"), "async_diagnostic", None)
            if callable(diagnostic):
                try:
                    result = diagnostic(
                        "ERROR",
                        "canonical_storage",
                        "eon_grid_capture_failed",
                        json.dumps(
                            {"site_id": site_id, "error_type": type(err).__name__, "error": str(err)[:200]},
                            separators=(",", ":"),
                        ),
                    )
                    if hasattr(result, "__await__"):
                        await result
                except Exception:
                    pass


def schedule_eon_grid_economic_capture(hass: Any) -> None:
    """Schedule one provider-update snapshot on Home Assistant's event-loop thread."""
    captured_at = datetime.now(UTC)

    def _schedule() -> None:
        hass.async_create_task(
            _async_capture_eon_grid_economic_snapshot(hass, captured_at)
        )

    hass.loop.call_soon_threadsafe(_schedule)
