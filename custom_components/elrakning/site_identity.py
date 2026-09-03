"""Persistent site identity and configured source mapping history."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util


STORE_KEY = "elrakning.site_identity"
STORE_VERSION = 1

ROLE_MAP = {
    "consumption_entity": "house.consumption",
    "power_entity": "grid.power/import",
    "energy_import_entity": "grid.energy_import",
    "energy_export_entity": "grid.energy_export",
    "battery_power_entity": "battery.power",
    "charging_entity": "battery.charge",
    "discharging_entity": "battery.discharge",
    "soc_entity": "battery.soc",
    "capacity_entity": "battery.capacity",
}


def _now() -> str:
    return dt_util.now().isoformat()


def _location_fingerprint(hass) -> str | None:
    config = getattr(hass, "config", None)
    latitude = getattr(config, "latitude", None)
    longitude = getattr(config, "longitude", None)
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        return None
    value = json.dumps({"latitude": latitude, "longitude": longitude}, sort_keys=True)
    return hashlib.sha256(value.encode()).hexdigest()


def resolve_source_identity(hass, entity_id: str | None) -> dict[str, Any]:
    """Resolve an entity using registry identity without guessing continuity."""
    domain = entity_id.split(".", 1)[0] if isinstance(entity_id, str) and "." in entity_id else None
    registry_entry = None
    if isinstance(entity_id, str) and entity_id:
        registry = er.async_get(hass)
        getter = getattr(registry, "async_get", None) or getattr(registry, "get", None)
        if getter:
            registry_entry = getter(entity_id)
        elif hasattr(registry, "entities"):
            registry_entry = registry.entities.get(entity_id)

    registry_id = getattr(registry_entry, "id", None)
    unique_id = getattr(registry_entry, "unique_id", None)
    config_entry_id = getattr(registry_entry, "config_entry_id", None)
    device_id = getattr(registry_entry, "device_id", None)
    platform = getattr(registry_entry, "platform", None)
    stable_fields = {
        "registry_id": registry_id,
        "unique_id": unique_id,
        "config_entry_id": config_entry_id,
        "device_id": device_id,
        "domain": domain,
        "platform": platform,
    }
    stable_fields = {key: value for key, value in stable_fields.items() if value is not None}
    if not any(stable_fields.get(key) for key in ("registry_id", "unique_id", "config_entry_id", "device_id")) and entity_id:
        stable_fields = {"entity_id": entity_id, "domain": domain}
    if registry_id and unique_id:
        strength = "strong"
        provenance = "ha_entity_registry"
    elif registry_id or unique_id or config_entry_id or device_id:
        strength = "medium"
        provenance = "ha_entity_registry_partial"
    elif entity_id:
        strength = "weak"
        provenance = "entity_id_only"
    else:
        strength = "uncertain"
        provenance = "missing_entity"
    return {
        "entity_id": entity_id,
        "registry_id": registry_id,
        "unique_id": unique_id,
        "config_entry_id": config_entry_id,
        "device_id": device_id,
        "domain": domain,
        "platform": platform,
        "identity_strength": strength,
        "identity_provenance": provenance,
        "identity_key": json.dumps(stable_fields, sort_keys=True) if stable_fields else None,
    }


def classify_source(old: dict[str, Any] | None, new: dict[str, Any]) -> str:
    """Classify source continuity only when the stable identity proves it."""
    old_key = old.get("source_identity", {}).get("identity_key") if old else None
    new_key = new.get("identity_key")
    old_strength = old.get("source_identity", {}).get("identity_strength") if old else None
    new_strength = new.get("identity_strength")
    if old_strength in {"weak", "uncertain"} or new_strength in {"weak", "uncertain"}:
        return "IDENTITY_UNCERTAIN"
    if old_key and new_key:
        return "SAME_SOURCE" if old_key == new_key else "NEW_SOURCE"
    return "IDENTITY_UNCERTAIN"


class SiteIdentityManager:
    """Own persistent site metadata and an append-only generation ledger."""

    def __init__(self, hass, power_manager, meter_manager) -> None:
        self.hass = hass
        self.power_manager = power_manager
        self.meter_manager = meter_manager
        self.store = Store(hass, STORE_VERSION, STORE_KEY)
        self.state: dict[str, Any] = {}

    async def async_load(self) -> None:
        cached = await self.store.async_load()
        if isinstance(cached, dict) and isinstance(cached.get("site"), dict):
            self.state = {
                "site": dict(cached["site"]),
                "ledger": list(cached.get("ledger", [])) if isinstance(cached.get("ledger", []), list) else [],
                "migration_complete": cached.get("migration_complete", bool(cached.get("ledger"))),
            }
            self.state["site"].setdefault("current", True)
            self.state["site"].setdefault("location_fingerprint", _location_fingerprint(self.hass))
            return
        self.state = {
            "site": {
                "site_id": str(uuid.uuid4()),
                "created_at": _now(),
                "current": True,
                "location_fingerprint": _location_fingerprint(self.hass),
            },
            "ledger": [],
            "migration_complete": False,
        }
        await self.store.async_save(self.state)

    def _current_sources(self) -> dict[str, list[str]]:
        sources: dict[str, list[str]] = {}
        for field, role in ROLE_MAP.items():
            entity_id = self.meter_manager.mapping.get(field) if field in {
                "power_entity", "energy_import_entity", "energy_export_entity"
            } else self.power_manager.mapping.get(field)
            if entity_id:
                sources.setdefault(role, []).append(entity_id)
        for entity_id in self.power_manager.mapping.get("solar_entities", []):
            if entity_id:
                sources.setdefault("solar.production", []).append(entity_id)
        return sources

    async def async_sync_from_current(self) -> None:
        """Snapshot current mappings while leaving functional managers authoritative."""
        current = self._current_sources()
        ledger = self.state.setdefault("ledger", [])
        site_id = self.state["site"]["site_id"]
        initial_migration = self.state.get("migration_complete") is not True
        for role, entity_ids in current.items():
            active = [
                item for item in ledger
                if item.get("logical_role") == role and item.get("effective_to") is None
            ]
            matched: set[int] = set()
            for entity_id in entity_ids:
                identity = resolve_source_identity(self.hass, entity_id)
                match = next(
                    (
                        item for index, item in enumerate(active)
                        if index not in matched
                        and item.get("source_identity", {}).get("identity_key") == identity.get("identity_key")
                        and identity.get("identity_key")
                    ),
                    None,
                )
                if match:
                    matched.add(active.index(match))
                    if match.get("entity_id") != entity_id:
                        match.setdefault("address_history", []).append({"entity_id": entity_id, "updated_at": _now()})
                        match["entity_id"] = entity_id
                    match["source_identity"] = identity
                    continue
                ledger.append({
                    "generation_id": str(uuid.uuid4()),
                    "site_id": site_id,
                    "logical_role": role,
                    "source_identity": identity,
                    "entity_id": entity_id,
                    "effective_from": None if initial_migration else _now(),
                    "effective_to": None,
                    "provenance": {
                        "migration_origin": "existing_configuration" if initial_migration else "mapping_change",
                        "effective_from_status": "unknown_unattributed" if initial_migration else "verified_mapping_change",
                    },
                    "created_at": _now(),
                })
            for index, old in enumerate(active):
                if index not in matched and old.get("effective_to") is None:
                    old["effective_to"] = _now()
                    old.setdefault("provenance", {})["end_reason"] = "mapping_changed_or_removed"
        current_roles = set(current)
        for item in ledger:
            if item.get("effective_to") is None and item.get("logical_role") not in current_roles:
                item["effective_to"] = _now()
                item.setdefault("provenance", {})["end_reason"] = "mapping_removed"
        self.state["migration_complete"] = True
        await self.store.async_save(self.state)

    def public_state(self) -> dict[str, Any]:
        ledger = self.state.get("ledger", [])
        return {
            "site": dict(self.state.get("site", {})),
            "site_id": self.state.get("site", {}).get("site_id"),
            "logical_roles": [item for item in ledger if item.get("effective_to") is None],
            "source_ledger": ledger,
        }
