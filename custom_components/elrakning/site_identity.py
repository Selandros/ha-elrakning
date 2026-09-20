"""Persistent site identity and configured source mapping history."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from copy import deepcopy
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .meter import METER_FIELDS
from .power import POWER_FIELDS


STORE_KEY = "elrakning.site_identity"
STORE_VERSION = 1
SITE_BINDING_SERVICES = ("elhandel", "grid")
GREENELY_PROOF_SCHEMA_VERSION = 1
GREENELY_PROOF_FINGERPRINT_VERSION = "sha256-v1"
GREENELY_PROOF_RELATION = "greenely_meter_id_to_invoice_installation_id"
GREENELY_ALLOWED_VERIFICATION_METHODS = {
    "provider_native_semantic_proof",
    "explicit_out_of_band_invoice_verification",
}
GREENELY_FACILITY_METER_IDENTITY_UNAVAILABLE = "provider_meter_identity_unavailable_v1"
GREENELY_CONTRACT_METER_IDENTITY_UNAVAILABLE = "provider_contract_meter_identity_unavailable_v1"
GREENELY_EVIDENCE_PACKAGE_VERSION = "c4c1a-evidence-package-v1"
GREENELY_EVIDENCE_PACKAGE_PROCEDURE = "operator_compared_provider_and_invoice_sections"
GREENELY_EVIDENCE_PACKAGE_KEYS = frozenset({
    "package_version", "procedure", "relation", "semantic_identity", "recorded_at",
})
GREENELY_EVIDENCE_FORBIDDEN_KEYS = frozenset({
    "facility_id", "contract_id", "user_id", "email", "address", "street",
    "meter_id", "installation_id", "anl.id", "ocr_number", "credential", "jwt",
    "signed_url",
})


def normalize_greenely_facility_meter_identity(payload: dict[str, Any]) -> str | None:
    """Return one bounded facility-meter identity or an allowed absence state."""
    fingerprint = payload.get("facility_meter_id_fingerprint")
    state = payload.get("facility_meter_identity_state")
    if bool(fingerprint) == bool(state):
        return None
    if state is not None:
        return state if state == GREENELY_FACILITY_METER_IDENTITY_UNAVAILABLE else None
    return fingerprint if isinstance(fingerprint, str) and fingerprint.strip() else None


def normalize_greenely_contract_meter_identity(value: Any) -> str | None:
    """Return one canonical contract-meter fingerprint or bounded absence state."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if value == GREENELY_CONTRACT_METER_IDENTITY_UNAVAILABLE:
        return value
    if len(value) == 64 and all(char in "0123456789abcdef" for char in value):
        return value
    return None


def validate_greenely_evidence_package(
    package: Any, expected_semantic_identity: str,
) -> str | None:
    """Validate and digest the exact bounded C4C1A evidence package."""
    if not isinstance(package, dict) or set(package) != GREENELY_EVIDENCE_PACKAGE_KEYS:
        return None
    if package.get("package_version") != GREENELY_EVIDENCE_PACKAGE_VERSION:
        return None
    if package.get("procedure") != GREENELY_EVIDENCE_PACKAGE_PROCEDURE:
        return None
    if package.get("relation") != GREENELY_PROOF_RELATION:
        return None
    semantic_identity = package.get("semantic_identity")
    if semantic_identity != expected_semantic_identity:
        return None
    if (
        not isinstance(semantic_identity, str)
        or len(semantic_identity) != 64
        or any(char not in "0123456789abcdef" for char in semantic_identity)
    ):
        return None
    recorded_at = package.get("recorded_at")
    if not isinstance(recorded_at, str) or not recorded_at.strip():
        return None
    try:
        parsed_recorded_at = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed_recorded_at.tzinfo is None:
        return None

    def contains_forbidden_key(value: Any) -> bool:
        if isinstance(value, dict):
            if any(str(key).lower() in GREENELY_EVIDENCE_FORBIDDEN_KEYS for key in value):
                return True
            return any(contains_forbidden_key(item) for item in value.values())
        if isinstance(value, list):
            return any(contains_forbidden_key(item) for item in value)
        return False

    if contains_forbidden_key(package):
        return None
    return hashlib.sha256(
        json.dumps(package, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

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

ROLE_CANONICALIZATION = {
    "house.consumption": {
        "unit": "W",
        "sign_convention": "positive_consumption",
        "aggregation": "time_weighted_mean",
        "classification": "measured",
        "max_hold_seconds": None,
        "absolute_value": True,
    },
    "solar.production": {
        "unit": "W",
        "sign_convention": "positive_production",
        "aggregation": "time_weighted_mean",
        "classification": "measured",
        "max_hold_seconds": None,
        "absolute_value": True,
    },
    "grid.power/import": {
        "unit": "W",
        "sign_convention": "positive_import_negative_export",
        "aggregation": "time_weighted_mean",
        "classification": "measured",
        "max_hold_seconds": None,
        "absolute_value": False,
    },
    "battery.power": {
        "unit": "W",
        "sign_convention": "positive_discharge_negative_charge",
        "aggregation": "time_weighted_mean",
        "classification": "measured",
        "max_hold_seconds": None,
        "absolute_value": False,
    },
    "battery.soc": {
        "unit": "%",
        "sign_convention": "unsigned_0_100",
        "aggregation": "last_valid",
        "classification": "measured",
        "max_hold_seconds": 900,
        "absolute_value": False,
    },
    "grid.energy_import": {
        "unit": "kWh",
        "sign_convention": "positive_import_energy",
        "aggregation": "last_valid",
        "classification": "measured",
        "max_hold_seconds": 3600,
        "absolute_value": False,
    },
    "grid.energy_export": {
        "unit": "kWh",
        "sign_convention": "positive_export_energy",
        "aggregation": "last_valid",
        "classification": "measured",
        "max_hold_seconds": 3600,
        "absolute_value": False,
    },
    "battery.charge": {
        "unit": "W",
        "sign_convention": "positive_charge",
        "aggregation": "time_weighted_mean",
        "classification": "measured",
        "max_hold_seconds": None,
        "absolute_value": True,
    },
    "battery.discharge": {
        "unit": "W",
        "sign_convention": "positive_discharge",
        "aggregation": "time_weighted_mean",
        "classification": "measured",
        "max_hold_seconds": None,
        "absolute_value": True,
    },
    "battery.capacity": {
        "unit": "kWh",
        "sign_convention": "positive_usable_or_nominal_capacity",
        "aggregation": "last_valid",
        "classification": "measured",
        "max_hold_seconds": 3600,
        "absolute_value": False,
    },
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
        self._provider_manager = None
        self._grid_manager = None
        self._coordinator = None
        self._solar_managers: dict[str, Any] = {}

    async def async_load(self) -> None:
        cached = await self.store.async_load()
        if isinstance(cached, dict) and isinstance(cached.get("site"), dict):
            site = dict(cached["site"])
            site.setdefault("name", "Nuvarande installation")
            site.setdefault("is_current", site.get("current", True) is True)
            sites = cached.get("sites")
            if not isinstance(sites, list) or not sites:
                sites = [site]
            self.state = {
                "site": site,
                "sites": [dict(item) for item in sites if isinstance(item, dict)],
                "active_site_id": cached.get("active_site_id") or site.get("site_id"),
                "site_configs": deepcopy(cached.get("site_configs", {})) if isinstance(cached.get("site_configs"), dict) else {},
                "global_bindings": deepcopy(cached.get("global_bindings", {})) if isinstance(cached.get("global_bindings"), dict) else {},
                "ledger": list(cached.get("ledger", [])) if isinstance(cached.get("ledger", []), list) else [],
                "migration_complete": cached.get("migration_complete", bool(cached.get("ledger"))),
            }
            resource_ids_added = False
            for item in self.state["ledger"]:
                if isinstance(item, dict) and not item.get("resource_id"):
                    item["resource_id"] = str(uuid.uuid4())
                    resource_ids_added = True
            self.state["site"].setdefault("current", True)
            self.state["site"].setdefault("location_fingerprint", _location_fingerprint(self.hass))
            self._normalize_sites()
            if not self.state["site_configs"]:
                self.state["site_configs"] = {
                    self.state["active_site_id"]: {
                        **self._current_mapping_config(),
                        "bindings": {},
                    }
                }
            for item in self.state["sites"]:
                self.state["site_configs"].setdefault(item["site_id"], self._empty_site_config())
            collection_enabled_migrated = False
            for config in self.state["site_configs"].values():
                if isinstance(config, dict):
                    config.setdefault("bindings", {})
                    if "collection_enabled" not in config:
                        config["collection_enabled"] = True
                        collection_enabled_migrated = True
            migrated_global_price = False
            for config in self.state["site_configs"].values():
                bindings = config.get("bindings", {}) if isinstance(config, dict) else {}
                legacy_binding = bindings.pop("nord_pool", None) if isinstance(bindings, dict) else None
                if not self.state["global_bindings"].get("nord_pool") and isinstance(legacy_binding, dict):
                    self.state["global_bindings"]["nord_pool"] = legacy_binding
                    migrated_global_price = True
            if migrated_global_price or resource_ids_added:
                await self.store.async_save(self.state)
            elif collection_enabled_migrated:
                await self.store.async_save(self.state)
            await self._restore_active_config()
            return
        site = {
            "site_id": str(uuid.uuid4()),
            "name": "Nuvarande installation",
            "created_at": _now(),
            "current": True,
            "is_current": True,
            "location_fingerprint": _location_fingerprint(self.hass),
        }
        self.state = {
            "site": site,
            "sites": [site],
            "active_site_id": site["site_id"],
            "site_configs": {
                site["site_id"]: {
                    **self._current_mapping_config(),
                    "bindings": {},
                    "collection_enabled": True,
                }
            },
            "global_bindings": {},
            "ledger": [],
            "migration_complete": False,
        }
        await self.store.async_save(self.state)

    def _normalize_sites(self) -> None:
        sites = self.state.get("sites")
        if not isinstance(sites, list) or not sites:
            sites = [self.state["site"]]
        normalized = []
        for site in sites:
            if not isinstance(site, dict) or not site.get("site_id"):
                continue
            item = dict(site)
            item.setdefault("name", "Installation / bostad")
            item.setdefault("is_current", item.get("site_id") == self.state.get("active_site_id"))
            item.setdefault("current", item["is_current"])
            normalized.append(item)
        if not normalized:
            normalized = [self.state["site"]]
        active_id = self.state.get("active_site_id") or self.state["site"].get("site_id")
        if not any(site.get("site_id") == active_id for site in normalized):
            active_id = normalized[0]["site_id"]
        for site in normalized:
            site["is_current"] = site.get("site_id") == active_id
            site["current"] = site["is_current"]
        self.state["sites"] = normalized
        self.state["active_site_id"] = active_id
        self.state["site"] = next(site for site in normalized if site["site_id"] == active_id)

    async def async_rename_site(self, site_id: str, name: str) -> dict[str, Any]:
        self._normalize_sites()
        clean_name = name.strip() if isinstance(name, str) else ""
        if not clean_name:
            raise ValueError("invalid_site_name")
        site = next((item for item in self.state["sites"] if item.get("site_id") == site_id), None)
        if site is None:
            raise ValueError("site_not_found")
        site["name"] = clean_name
        self._normalize_sites()
        await self.store.async_save(self.state)
        return self.public_state()

    async def async_create_site(self, name: str) -> dict[str, Any]:
        clean_name = name.strip() if isinstance(name, str) else ""
        if not clean_name:
            raise ValueError("invalid_site_name")
        self._normalize_sites()
        site = {
            "site_id": str(uuid.uuid4()),
            "name": clean_name,
            "created_at": _now(),
            "current": False,
            "is_current": False,
            "location_fingerprint": _location_fingerprint(self.hass),
        }
        self.state["sites"].append(site)
        self.state.setdefault("site_configs", {})[site["site_id"]] = self._empty_site_config()
        await self.store.async_save(self.state)
        return self.public_state()

    async def async_activate_site(self, site_id: str) -> dict[str, Any]:
        self._normalize_sites()
        if not any(item.get("site_id") == site_id for item in self.state["sites"]):
            raise ValueError("site_not_found")
        await self.async_sync_from_current()
        self._snapshot_runtime_state()
        self.state["active_site_id"] = site_id
        self._normalize_sites()
        await self._restore_active_config()
        if self._provider_manager and self._coordinator:
            await self.async_apply_runtime_context(
                self._provider_manager, self._grid_manager, self._coordinator
            )
            await self.async_prepare_solar_contexts(self._solar_managers)
            if self._provider_manager.state.get("configured") and self.active_binding("elhandel"):
                self._provider_manager.async_start_refresh("site_switch")
            if self._grid_manager and self._grid_manager.configured and self.active_binding("grid"):
                self._grid_manager.async_start_refresh()
        await self.async_sync_from_current()
        await self.store.async_save(self.state)
        return self.public_state()

    @staticmethod
    def _empty_site_config() -> dict[str, Any]:
        return {"power": {}, "meter": {}, "bindings": {}, "collection_enabled": False}

    def collection_targets(self) -> list[dict[str, Any]]:
        """Return explicit site/source targets for background collection."""
        targets = []
        ledger = self.state.get("ledger", [])
        configs = self.state.get("site_configs", {})
        for site in self.state.get("sites", []):
            site_id = site.get("site_id") if isinstance(site, dict) else None
            if not site_id:
                continue
            config = configs.get(site_id, {})
            if not isinstance(config, dict) or config.get("collection_enabled", True) is not True:
                continue
            for item in ledger:
                if (
                    isinstance(item, dict)
                    and item.get("site_id") == site_id
                    and item.get("effective_to") is None
                    and item.get("entity_id")
                    and item.get("logical_role")
                    and item.get("generation_id")
                ):
                    targets.append({
                        "site_id": site_id,
                        "logical_role": item["logical_role"],
                        "entity_id": item["entity_id"],
                        "generation_id": item["generation_id"],
                        "resource_id": item.get("resource_id") or item["generation_id"],
                        "source_identity": deepcopy(item.get("source_identity", {})),
                        "provenance": deepcopy(item.get("provenance", {})),
                        "site": deepcopy(site),
                        "effective_from": item.get("effective_from"),
                        "classification": item.get("classification"),
                        "mapping": deepcopy(config.get("power", {})) | deepcopy(config.get("meter", {})),
                        "canonicalization": deepcopy(item.get("canonicalization")),
                    })
        return targets

    def forecast_collection_targets(self) -> list[dict[str, Any]]:
        """Return explicit Forecast.Solar bindings for enabled sites."""
        targets = []
        configs = self.state.get("site_configs", {})
        for site in self.state.get("sites", []):
            site_id = site.get("site_id") if isinstance(site, dict) else None
            if not site_id:
                continue
            config = configs.get(site_id, {})
            if not isinstance(config, dict) or config.get("collection_enabled", True) is not True:
                continue
            bindings = config.get("bindings")
            binding = bindings.get("forecast") if isinstance(bindings, dict) else None
            if not isinstance(binding, dict) or not isinstance(binding.get("entities"), dict):
                continue
            targets.append({"site_id": site_id, "binding": deepcopy(binding)})
        return targets

    def collection_site_configs(self) -> dict[str, dict[str, Any]]:
        """Return a deep snapshot of site configuration for background producers."""
        configs = self.state.get("site_configs", {})
        return {
            str(site_id): deepcopy(config)
            for site_id, config in configs.items()
            if isinstance(site_id, str) and isinstance(config, dict)
        }

    async def async_set_site_location(self, site_id: str, location: dict[str, Any]) -> bool:
        """Persist an explicitly verified site location without changing active context."""
        if not isinstance(site_id, str) or not site_id or not isinstance(location, dict):
            raise ValueError("site_location_invalid")
        if site_id not in {
            item.get("site_id")
            for item in self.state.get("sites", [])
            if isinstance(item, dict)
        }:
            raise ValueError("site_not_found")
        required = {"latitude", "longitude", "timezone", "provenance", "verification_state", "location_fingerprint"}
        if set(location) != required or location.get("verification_state") != "verified":
            raise ValueError("site_location_invalid")
        try:
            latitude = float(location["latitude"])
            longitude = float(location["longitude"])
            timezone_name = str(location["timezone"])
            ZoneInfo(timezone_name)
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            raise ValueError("site_location_invalid") from None
        if not math.isfinite(latitude) or not math.isfinite(longitude) or not str(location["provenance"]).strip():
            raise ValueError("site_location_invalid")
        if location.get("location_fingerprint") != self.site_location_fingerprint(latitude, longitude, timezone_name):
            raise ValueError("site_location_invalid")
        config = self.state.setdefault("site_configs", {}).setdefault(
            site_id, self._empty_site_config()
        )
        current = config.get("location")
        if current == location:
            return False
        if current is not None:
            raise ValueError("site_location_conflict")
        config["location"] = deepcopy(location)
        await self.store.async_save(self.state)
        return True

    @staticmethod
    def site_location_fingerprint(latitude: float, longitude: float, timezone_name: str) -> str:
        payload = {"latitude": latitude, "longitude": longitude, "timezone": timezone_name}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _current_mapping_config(self) -> dict[str, Any]:
        return {
            "power": deepcopy(self.power_manager.mapping),
            "meter": deepcopy(self.meter_manager.mapping),
        }

    @staticmethod
    def binding_fingerprint(binding: dict[str, Any] | None) -> str | None:
        """Return a deterministic fingerprint for non-secret site binding data."""
        if not isinstance(binding, dict):
            return None
        payload = {key: value for key, value in binding.items() if key != "binding_fingerprint"}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def identity_fingerprint(payload: dict[str, Any]) -> str:
        """Fingerprint operator-verified identity evidence without retaining raw values."""
        value = {"fingerprint_version": GREENELY_PROOF_FINGERPRINT_VERSION, **payload}
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def current_greenely_proof(self, site_id: str) -> dict[str, Any] | None:
        config = self.state.get("site_configs", {}).get(site_id, {})
        proof = config.get("greenely_meter_to_invoice_installation_proof") if isinstance(config, dict) else None
        return deepcopy(proof) if isinstance(proof, dict) else None

    def validated_greenely_proof(self, site_id: str, binding: dict[str, Any]) -> dict[str, Any] | None:
        proof = self.current_greenely_proof(site_id)
        if not proof or proof.get("verification_state") != "EXPLICITLY_VERIFIED":
            return None
        if proof.get("provider") != "greenely" or proof.get("site_id") != site_id:
            return None
        if proof.get("site_binding_fingerprint") != self.binding_fingerprint(binding):
            return None
        if proof.get("proof_schema_version") != GREENELY_PROOF_SCHEMA_VERSION:
            return None
        if proof.get("fingerprint_version") != GREENELY_PROOF_FINGERPRINT_VERSION:
            return None
        if proof.get("relation") != GREENELY_PROOF_RELATION:
            return None
        if proof.get("verification_method") not in GREENELY_ALLOWED_VERIFICATION_METHODS:
            return None
        if proof.get("verification_actor_source") != "authenticated_home_assistant_service_context":
            return None
        if not isinstance(proof.get("evidence_reference"), str) or not proof["evidence_reference"].startswith("c4c1a-audit-ref-v1:"):
            return None
        if not isinstance(proof.get("evidence_digest"), str) or len(proof["evidence_digest"]) != 64:
            return None
        facility_meter_identity = normalize_greenely_facility_meter_identity(proof)
        if facility_meter_identity is None:
            return None
        contract_meter_identity = normalize_greenely_contract_meter_identity(
            proof.get("contract_meter_id_fingerprint_or_state")
        )
        if contract_meter_identity is None:
            return None
        required = (
            "relation", "config_entry_identity", "facility_identity_fingerprint",
            "contract_identity_fingerprint",
            "contract_meter_id_fingerprint_or_state", "invoice_installation_identity_fingerprint",
            "verification_method", "verified_at", "parser_identity", "normalization_identity",
            "verification_actor", "verification_actor_source", "evidence_reference", "evidence_digest",
            "proof_semantic_identity", "proof_audit_identity",
        )
        if any(not proof.get(key) for key in required):
            return None
        if proof.get("config_entry_identity") != self.identity_fingerprint({"config_entry_id": binding.get("config_entry_id")}):
            return None
        if proof.get("facility_identity_fingerprint") != self.identity_fingerprint({"facility_id": binding.get("facility_id")}):
            return None
        semantic = {
            "relation": proof["relation"],
            "provider_config_entry_identity": proof["config_entry_identity"],
            "site_binding_identity": proof["site_binding_fingerprint"],
            "facility_identity": proof["facility_identity_fingerprint"],
            "contract_identity_scope": proof["contract_identity_fingerprint"],
            "facility_meter_identity_state": facility_meter_identity,
            "contract_meter_identity_state": contract_meter_identity,
            "invoice_installation_identity": proof["invoice_installation_identity_fingerprint"],
            "verification_method": proof["verification_method"],
            "proof_schema_version": proof["proof_schema_version"],
            "fingerprint_version": proof["fingerprint_version"],
            "parser_identity": proof["parser_identity"],
            "normalization_identity": proof["normalization_identity"],
        }
        audit = {
            "verification_actor": proof["verification_actor"],
            "verified_at": proof["verified_at"],
            "evidence_reference": proof["evidence_reference"],
            "evidence_digest": proof["evidence_digest"],
        }
        expected = self.identity_fingerprint(semantic)
        expected_audit = self.identity_fingerprint(audit)
        if proof.get("proof_semantic_identity") != expected or proof.get("proof_audit_identity") != expected_audit:
            return None
        return deepcopy(proof) if proof.get("proof_fingerprint") == expected else None

    async def async_provision_greenely_proof(self, payload: dict[str, Any], *, provider_relation: dict[str, Any]) -> dict[str, Any]:
        """Persist an explicitly operator-verified Greenely attribution proof."""
        site_id = payload.get("site_id")
        if not isinstance(site_id, str) or not site_id:
            raise ValueError("site_id_required")
        config = self.state.get("site_configs", {}).get(site_id, {})
        binding = config.get("bindings", {}).get("elhandel") if isinstance(config, dict) else None
        if not isinstance(binding, dict) or binding.get("provider") != "greenely":
            raise ValueError("greenely_binding_required")
        if payload.get("expected_binding_fingerprint") != self.binding_fingerprint(binding):
            raise ValueError("stale_binding")
        verification_method = payload.get("verification_method")
        if verification_method not in GREENELY_ALLOWED_VERIFICATION_METHODS:
            raise ValueError("verification_method_invalid")
        contract = provider_relation
        if str(contract.get("facility_id")) != str(binding.get("facility_id")):
            raise ValueError("contract_facility_mismatch")
        contract_id = contract.get("id")
        if not isinstance(contract_id, (str, int)) or isinstance(contract_id, bool):
            raise ValueError("contract_identity_required")
        if payload.get("contract_id") != str(contract_id):
            raise ValueError("contract_not_provider_verified")
        actor = payload.get("verification_actor")
        actor_source = payload.get("verification_actor_source")
        if not isinstance(actor, str) or not actor.strip() or actor_source != "authenticated_home_assistant_service_context":
            raise ValueError("verification_actor_required")
        evidence_reference = payload.get("evidence_reference")
        evidence_digest = payload.get("evidence_digest")
        evidence_package = payload.get("evidence_package")
        if not isinstance(evidence_reference, str) or not evidence_reference.startswith("c4c1a-audit-ref-v1:") or len(evidence_reference) > 256:
            raise ValueError("evidence_reference_invalid")
        if not isinstance(evidence_digest, str) or len(evidence_digest) != 64 or any(c not in "0123456789abcdef" for c in evidence_digest.lower()):
            raise ValueError("evidence_digest_invalid")
        fields = {
            "site_id": site_id,
            "provider": "greenely",
            "relation": GREENELY_PROOF_RELATION,
            "site_binding_fingerprint": self.binding_fingerprint(binding),
            "config_entry_identity": self.identity_fingerprint({"config_entry_id": binding.get("config_entry_id")}),
            "facility_identity_fingerprint": self.identity_fingerprint({"facility_id": binding.get("facility_id")}),
            "contract_identity_fingerprint": self.identity_fingerprint({"contract_id": str(contract_id)}),
            "facility_meter_id_fingerprint": payload.get("facility_meter_id_fingerprint"),
            "facility_meter_identity_state": payload.get("facility_meter_identity_state"),
            "contract_meter_id_fingerprint_or_state": normalize_greenely_contract_meter_identity(
                payload.get("contract_meter_id_fingerprint_or_state")
            ),
            "invoice_installation_identity_fingerprint": payload.get("invoice_installation_identity_fingerprint"),
            "verification_method": verification_method,
            "verification_state": "EXPLICITLY_VERIFIED",
            "verified_at": _now(),
            "proof_schema_version": GREENELY_PROOF_SCHEMA_VERSION,
            "fingerprint_version": GREENELY_PROOF_FINGERPRINT_VERSION,
            "parser_identity": payload.get("parser_identity"),
            "normalization_identity": payload.get("normalization_identity"),
            "verification_actor": actor,
            "verification_actor_source": actor_source,
            "evidence_reference": evidence_reference,
            "evidence_digest": evidence_digest,
        }
        if normalize_greenely_facility_meter_identity(fields) is None:
            raise ValueError("facility_meter_identity_invalid")
        if fields["contract_meter_id_fingerprint_or_state"] is None:
            raise ValueError("contract_meter_identity_invalid")
        if any(not fields.get(key) for key in (
            "contract_identity_fingerprint",
            "contract_meter_id_fingerprint_or_state", "invoice_installation_identity_fingerprint",
            "parser_identity", "normalization_identity",
        )):
            raise ValueError("proof_fields_required")
        semantic = {
            "relation": fields["relation"],
            "provider_config_entry_identity": fields["config_entry_identity"],
            "site_binding_identity": fields["site_binding_fingerprint"],
            "facility_identity": fields["facility_identity_fingerprint"],
            "contract_identity_scope": fields["contract_identity_fingerprint"],
            "facility_meter_identity_state": normalize_greenely_facility_meter_identity(fields),
            "contract_meter_identity_state": fields["contract_meter_id_fingerprint_or_state"],
            "invoice_installation_identity": fields["invoice_installation_identity_fingerprint"],
            "verification_method": fields["verification_method"],
            "proof_schema_version": fields["proof_schema_version"],
            "fingerprint_version": fields["fingerprint_version"],
            "parser_identity": fields["parser_identity"],
            "normalization_identity": fields["normalization_identity"],
        }
        package_digest = validate_greenely_evidence_package(
            evidence_package, self.identity_fingerprint(semantic)
        )
        if package_digest is None:
            raise ValueError("evidence_package_invalid")
        if package_digest != evidence_digest:
            raise ValueError("evidence_digest_mismatch")
        audit = {key: fields[key] for key in ("verification_actor", "verified_at", "evidence_reference", "evidence_digest")}
        fields["proof_semantic_identity"] = self.identity_fingerprint(semantic)
        fields["proof_audit_identity"] = self.identity_fingerprint(audit)
        fields["proof_fingerprint"] = fields["proof_semantic_identity"]
        before = self.binding_fingerprint(binding)
        if before != self.binding_fingerprint(config.get("bindings", {}).get("elhandel")):
            raise ValueError("stale_binding")
        config["greenely_meter_to_invoice_installation_proof"] = fields
        await self.store.async_save(self.state)
        authoritative_state = await self.store.async_load()
        authoritative_configs = (
            authoritative_state.get("site_configs", {})
            if isinstance(authoritative_state, dict)
            else {}
        )
        authoritative_config = authoritative_configs.get(site_id, {})
        authoritative_bindings = (
            authoritative_config.get("bindings", {})
            if isinstance(authoritative_config, dict)
            else {}
        )
        authoritative_binding = (
            authoritative_bindings.get("elhandel")
            if isinstance(authoritative_bindings, dict)
            else None
        )
        if self.binding_fingerprint(authoritative_binding) != before:
            raise ValueError("stale_binding")
        return {"site_id": site_id, "verification_state": fields["verification_state"], "proof_fingerprint": fields["proof_fingerprint"]}

    def active_binding(self, service: str) -> dict[str, Any] | None:
        """Return only the active site's explicit binding for one service."""
        self._normalize_sites()
        config = self.state.get("site_configs", {}).get(self.state.get("active_site_id"), {})
        bindings = config.get("bindings", {}) if isinstance(config, dict) else {}
        binding = bindings.get(service) if isinstance(bindings, dict) else None
        return dict(binding) if isinstance(binding, dict) else None

    def active_ella_binding(self) -> dict[str, Any] | None:
        """Return ELLA only for an explicitly verified versioned site binding."""
        binding = self.active_binding("ella")
        return binding if self.is_valid_ella_planner_binding(binding, require_enabled=True) else None

    @staticmethod
    def is_valid_ella_planner_binding(binding: dict[str, Any] | None, *, require_enabled: bool = False) -> bool:
        """Validate the explicit planner-only capability without inferring hardware access."""
        if not isinstance(binding, dict):
            return False
        if binding.get("binding_version") != 1:
            return False
        if binding.get("capability") != "ella_planner":
            return False
        if binding.get("actuator_write_enabled") is not False:
            return False
        if binding.get("verification_state") not in {"verified", "disabled"}:
            return False
        if not isinstance(binding.get("enabled"), bool):
            return False
        if require_enabled and (binding.get("enabled") is not True or binding.get("verification_state") != "verified"):
            return False
        fingerprint = binding.get("binding_fingerprint")
        return isinstance(fingerprint, str) and len(fingerprint) == 64 and all(
            char in "0123456789abcdef" for char in fingerprint
        )

    async def async_set_ella_planner_binding(self, site_id: str, enabled: bool) -> dict[str, Any]:
        """Persist an explicit site-scoped planner capability; never grants actuator access."""
        self._normalize_sites()
        if not isinstance(site_id, str) or not any(item.get("site_id") == site_id for item in self.state["sites"]):
            raise ValueError("site_not_found")
        if not isinstance(enabled, bool):
            raise ValueError("invalid_ella_binding")
        config = self.state.setdefault("site_configs", {}).setdefault(site_id, self._empty_site_config())
        bindings = config.setdefault("bindings", {})
        if enabled:
            binding = {
                "binding_version": 1,
                "capability": "ella_planner",
                "enabled": True,
                "verification_state": "verified",
                "actuator_write_enabled": False,
                "configured_at": _now(),
            }
            binding["binding_fingerprint"] = self.binding_fingerprint(binding)
            if not self.is_valid_ella_planner_binding(binding, require_enabled=True):
                raise ValueError("invalid_ella_binding")
            bindings["ella"] = binding
        else:
            binding = dict(bindings.get("ella", {}))
            binding.update({
                "binding_version": 1,
                "capability": "ella_planner",
                "enabled": False,
                "verification_state": "disabled",
                "actuator_write_enabled": False,
            })
            binding["binding_fingerprint"] = self.binding_fingerprint(binding)
            if not self.is_valid_ella_planner_binding(binding):
                raise ValueError("invalid_ella_binding")
            bindings["ella"] = binding
        await self.store.async_save(self.state)
        if site_id == self.state.get("active_site_id"):
            return self.public_state()
        return self.public_state()

    def global_binding(self, service: str) -> dict[str, Any] | None:
        """Return a global binding shared by all sites."""
        binding = self.state.get("global_bindings", {}).get(service)
        return dict(binding) if isinstance(binding, dict) else None

    def _set_binding(self, service: str, binding: dict[str, Any]) -> None:
        config = self.state.setdefault("site_configs", {}).setdefault(
            self.state["active_site_id"], self._empty_site_config()
        )
        bindings = config.setdefault("bindings", {})
        normalized = deepcopy(binding)
        normalized["binding_fingerprint"] = self.binding_fingerprint(normalized)
        bindings[service] = normalized

    async def async_prepare_runtime_bindings(self, provider_manager, grid_manager, coordinator) -> None:
        """Migrate verified current resources into Site A and apply active context."""
        self._normalize_sites()
        self._provider_manager = provider_manager
        self._grid_manager = grid_manager
        self._coordinator = coordinator
        config = self.state.setdefault("site_configs", {}).setdefault(
            self.state["active_site_id"], self._empty_site_config()
        )
        config.setdefault("bindings", {})
        legacy_site_migration = len(self.state.get("sites", [])) == 1
        if legacy_site_migration and not config["bindings"].get("elhandel") and provider_manager.state.get("facility_id"):
            self._set_binding("elhandel", {
                "config_entry_id": provider_manager.entry.entry_id,
                "provider": provider_manager.state.get("provider"),
                "facility_id": provider_manager.state.get("facility_id"),
                "configured_at": _now(),
            })
        if legacy_site_migration and not config["bindings"].get("grid") and grid_manager and grid_manager.provider:
            grid_state = grid_manager.provider.state
            if grid_manager.configured and isinstance(grid_state.get("facility"), dict):
                self._set_binding("grid", {
                    "config_entry_id": grid_manager.entry.entry_id,
                    "provider": getattr(grid_manager.definition, "provider_id", None),
                    "facility": deepcopy(grid_state.get("facility")),
                    "tariff": deepcopy(grid_state.get("tariff")),
                    "grid_price": deepcopy(grid_state.get("grid_price")),
                    "configured_at": _now(),
                })
                config.setdefault("runtime", {})["grid_state"] = deepcopy(grid_state)
        global_bindings = self.state.setdefault("global_bindings", {})
        if not global_bindings.get("nord_pool") and legacy_site_migration:
            discover = getattr(coordinator, "discovered_binding", None)
            binding = discover() if discover else None
            if binding:
                global_bindings["nord_pool"] = {
                    **deepcopy(binding),
                    "binding_fingerprint": self.binding_fingerprint(binding),
                }
        await self.store.async_save(self.state)
        if await self.async_apply_runtime_context(provider_manager, grid_manager, coordinator):
            await self.store.async_save(self.state)

    @staticmethod
    def _runtime_updated_at(state: Any) -> datetime | None:
        if not isinstance(state, dict):
            return None
        value = state.get("updated_at")
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else None

    @classmethod
    def _preferred_grid_runtime_state(
        cls,
        binding: dict[str, Any] | None,
        cached_state: Any,
        grid_manager: Any,
    ) -> dict[str, Any] | None:
        cached = deepcopy(cached_state) if isinstance(cached_state, dict) else None
        if not isinstance(binding, dict) or grid_manager is None:
            return cached
        provider = getattr(grid_manager, "provider", None)
        provider_state = getattr(provider, "state", None)
        entry = getattr(grid_manager, "entry", None)
        definition = getattr(grid_manager, "definition", None)
        if (
            not isinstance(provider_state, dict)
            or binding.get("config_entry_id") != getattr(entry, "entry_id", None)
            or binding.get("provider") != getattr(definition, "provider_id", None)
            or binding.get("facility") != provider_state.get("facility")
        ):
            return cached
        provider_updated = cls._runtime_updated_at(provider_state)
        cached_updated = cls._runtime_updated_at(cached)
        if provider_updated is None:
            return cached
        if cached_updated is not None and provider_updated < cached_updated:
            return cached
        return deepcopy(provider_state)

    async def async_apply_runtime_context(self, provider_manager, grid_manager, coordinator) -> bool:
        """Apply the active site's explicit provider, grid and price context."""
        provider_binding = self.active_binding("elhandel")
        grid_binding = self.active_binding("grid")
        price_binding = self.global_binding("nord_pool")
        if grid_manager and grid_binding:
            provider = getattr(grid_manager, "provider", None)
            reconcile = getattr(provider, "binding_reconciliation", None)
            if reconcile:
                result = reconcile(grid_binding)
                enriched = result.get("binding") if isinstance(result, dict) else None
                if result.get("status") == "legacy_unique" and isinstance(enriched, dict):
                    self._set_binding("grid", enriched)
                    await self.store.async_save(self.state)
                    grid_binding = self.active_binding("grid")
        config = self.state.get("site_configs", {}).get(self.state.get("active_site_id"), {})
        runtime = config.get("runtime", {}) if isinstance(config, dict) else {}
        cached_grid_state = runtime.get("grid_state") if isinstance(runtime, dict) else None
        runtime_cleared = False
        grid_state = self._preferred_grid_runtime_state(
            grid_binding, cached_grid_state, grid_manager
        )
        if (
            grid_manager
            and grid_binding
            and hasattr(getattr(grid_manager, "provider", None), "state_for_binding")
        ):
            explicit_state = grid_manager.state_for_binding(grid_binding)
            grid_state = explicit_state if isinstance(explicit_state, dict) else None
            if not isinstance(explicit_state, dict) and isinstance(runtime, dict):
                runtime_cleared = "grid_state" in runtime
                runtime.pop("grid_state", None)
        runtime_changed = (
            runtime_cleared
            or
            isinstance(config, dict)
            and isinstance(grid_state, dict)
            and grid_state != cached_grid_state
        )
        if runtime_changed:
            config.setdefault("runtime", {})["grid_state"] = deepcopy(grid_state)
        if hasattr(provider_manager, "async_apply_site_binding"):
            await provider_manager.async_apply_site_binding(provider_binding)
        if grid_manager and hasattr(grid_manager, "async_apply_site_binding"):
            await grid_manager.async_apply_site_binding(grid_binding, grid_state)
        if hasattr(coordinator, "set_site_binding"):
            coordinator.set_site_binding(price_binding)
        return runtime_changed

    async def async_reconcile_grid_bindings(self, grid_manager) -> int:
        """Backfill native E.ON identity only for a unique provider match."""
        provider = getattr(grid_manager, "provider", None)
        reconcile = getattr(provider, "binding_reconciliation", None)
        if reconcile is None:
            return 0
        changed = 0
        for config in self.state.get("site_configs", {}).values():
            if not isinstance(config, dict):
                continue
            binding = config.get("bindings", {}).get("grid")
            if not isinstance(binding, dict) or binding.get("provider") != "eon":
                continue
            result = reconcile(binding)
            enriched = result.get("binding") if isinstance(result, dict) else None
            if result.get("status") == "legacy_unique" and isinstance(enriched, dict) and enriched != binding:
                config.setdefault("bindings", {})["grid"] = enriched
                changed += 1
        if changed:
            await self.store.async_save(self.state)
        return changed

    async def async_bind_provider_runtime(self, provider_manager) -> None:
        """Record an explicit provider facility selection for the active site."""
        state = provider_manager.state
        facility_id = state.get("facility_id")
        if not facility_id:
            raise ValueError("facility_not_identified")
        self._set_binding("elhandel", {
            "config_entry_id": provider_manager.entry.entry_id,
            "provider": state.get("provider"),
            "facility_id": facility_id,
            "configured_at": _now(),
        })
        await self.store.async_save(self.state)
        await provider_manager.async_apply_site_binding(self.active_binding("elhandel"))

    async def async_unbind_provider_runtime(self) -> bool:
        """Remove only the active site's provider binding and report other users."""
        active_site_id = self.state.get("active_site_id")
        config = self.state.setdefault("site_configs", {}).setdefault(
            active_site_id, self._empty_site_config()
        )
        config.setdefault("bindings", {}).pop("elhandel", None)
        await self.store.async_save(self.state)
        return any(
            isinstance(site_config, dict)
            and isinstance(site_config.get("bindings"), dict)
            and isinstance(site_config["bindings"].get("elhandel"), dict)
            for site_id, site_config in self.state.get("site_configs", {}).items()
            if site_id != active_site_id
        )

    async def async_bind_grid_runtime(self, grid_manager) -> None:
        """Record the selected grid facility while keeping credentials global."""
        if not grid_manager or not grid_manager.provider:
            raise ValueError("grid_unavailable")
        state = grid_manager.provider.state
        self._set_binding("grid", {
            "config_entry_id": grid_manager.entry.entry_id,
            "provider": getattr(grid_manager.definition, "provider_id", None),
            "facility": deepcopy(state.get("facility")),
            "tariff": deepcopy(state.get("tariff")),
            "grid_price": deepcopy(state.get("grid_price")),
            "configured_at": _now(),
        })
        config = self.state.setdefault("site_configs", {}).setdefault(
            self.state["active_site_id"], self._empty_site_config()
        )
        config.setdefault("runtime", {})["grid_state"] = deepcopy(state)
        await self.store.async_save(self.state)
        await grid_manager.async_apply_site_binding(
            self.active_binding("grid"), deepcopy(state)
        )

    async def async_unbind_grid_runtime(self) -> bool:
        """Remove only the active site's grid binding and return whether another remains."""
        active_site_id = self.state.get("active_site_id")
        config = self.state.setdefault("site_configs", {}).setdefault(
            active_site_id, self._empty_site_config()
        )
        bindings = config.setdefault("bindings", {})
        bindings.pop("grid", None)
        config.get("runtime", {}).pop("grid_state", None)
        await self.store.async_save(self.state)
        return any(
            isinstance(site_config, dict)
            and isinstance(site_config.get("bindings"), dict)
            and isinstance(site_config["bindings"].get("grid"), dict)
            for site_id, site_config in self.state.get("site_configs", {}).items()
            if site_id != active_site_id
        )

    async def async_prepare_solar_contexts(self, managers: dict[str, Any]) -> None:
        """Migrate and apply explicit site context for solar and weather managers."""
        self._solar_managers = {name: manager for name, manager in managers.items() if manager is not None}
        managers = self._solar_managers
        self._normalize_sites()
        config = self.state.setdefault("site_configs", {}).setdefault(
            self.state["active_site_id"], self._empty_site_config()
        )
        bindings = config.setdefault("bindings", {})
        legacy_site_migration = len(self.state.get("sites", [])) == 1
        for name, manager in managers.items():
            if legacy_site_migration and not bindings.get(name):
                discover = getattr(manager, "discovered_binding", None)
                binding = discover() if discover else None
                if binding:
                    self._set_binding(name, binding)
        await self.store.async_save(self.state)
        active_site_id = self.state["active_site_id"]
        for name, manager in managers.items():
            apply_context = getattr(manager, "async_apply_site_context", None)
            if apply_context:
                await apply_context(active_site_id, self.active_binding(name))

    def _snapshot_runtime_state(self) -> None:
        """Persist non-secret state needed to restore the active site context."""
        if not self._grid_manager or not self._grid_manager.provider:
            return
        config = self.state.setdefault("site_configs", {}).setdefault(
            self.state["active_site_id"], self._empty_site_config()
        )
        config.setdefault("runtime", {})["grid_state"] = deepcopy(
            self._grid_manager.provider.state
        )

    async def _restore_active_config(self) -> None:
        configs = self.state.setdefault("site_configs", {})
        config = configs.setdefault(self.state["active_site_id"], self._empty_site_config())
        if hasattr(self.power_manager, "async_restore_mapping"):
            await self.power_manager.async_restore_mapping(config.get("power"))
        if hasattr(self.meter_manager, "async_restore_mapping"):
            await self.meter_manager.async_restore_mapping(config.get("meter"))

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
        for item in ledger:
            if isinstance(item, dict) and not item.get("resource_id"):
                item["resource_id"] = str(uuid.uuid4())
        self._normalize_sites()
        site_id = self.state["active_site_id"]
        config = self.state.setdefault("site_configs", {}).setdefault(site_id, self._empty_site_config())
        config.update(self._current_mapping_config())
        config.setdefault("bindings", {})
        initial_migration = self.state.get("migration_complete") is not True
        for role, entity_ids in current.items():
            active = [
                item for item in ledger
                if item.get("site_id") == site_id
                and item.get("logical_role") == role
                and item.get("effective_to") is None
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
                    if match.get("canonicalization") is None:
                        semantics = ROLE_CANONICALIZATION.get(role)
                        if semantics:
                            match["canonicalization"] = deepcopy(semantics)
                            match.setdefault("provenance", {})["canonicalization_source"] = "logical_role_contract_v1"
                    continue
                ledger.append({
                    "generation_id": str(uuid.uuid4()),
                    "resource_id": str(uuid.uuid4()),
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
                    "classification": ROLE_CANONICALIZATION.get(role, {}).get("classification"),
                    "canonicalization": deepcopy(ROLE_CANONICALIZATION.get(role)),
                    "created_at": _now(),
                })
                if role in ROLE_CANONICALIZATION:
                    ledger[-1]["provenance"]["canonicalization_source"] = "logical_role_contract_v1"
            for index, old in enumerate(active):
                if index not in matched and old.get("effective_to") is None:
                    old["effective_to"] = _now()
                    old.setdefault("provenance", {})["end_reason"] = "mapping_changed_or_removed"
        current_roles = set(current)
        for item in ledger:
            if item.get("site_id") == site_id and item.get("effective_to") is None and item.get("logical_role") not in current_roles:
                item["effective_to"] = _now()
                item.setdefault("provenance", {})["end_reason"] = "mapping_removed"
        self.state["migration_complete"] = True
        await self.store.async_save(self.state)

    def public_state(self) -> dict[str, Any]:
        self._normalize_sites()
        ledger = self.state.get("ledger", [])
        active_site_id = self.state.get("active_site_id")
        return {
            "site": dict(self.state.get("site", {})),
            "site_id": active_site_id,
            "current_site": dict(self.state.get("site", {})),
            "available_sites": [dict(site) for site in self.state.get("sites", [])],
            "site_configured": bool(
                self.state.get("site_configs", {}).get(active_site_id, {}).get("power", {}).get("solar_entities")
                or any(self.state.get("site_configs", {}).get(active_site_id, {}).get("power", {}).get(field) for field in POWER_FIELDS)
                or any(self.state.get("site_configs", {}).get(active_site_id, {}).get("meter", {}).get(field) for field in METER_FIELDS)
            ),
            "ella_binding_verified": self.active_ella_binding() is not None,
            "bindings": deepcopy(self.state.get("site_configs", {}).get(active_site_id, {}).get("bindings", {})),
            "global_bindings": deepcopy(self.state.get("global_bindings", {})),
            "logical_roles": [item for item in ledger if item.get("site_id") == active_site_id and item.get("effective_to") is None],
            "source_ledger": [
                item for item in ledger
                if item.get("site_id") == active_site_id
            ],
        }

    def active_site_is_configured(self) -> bool:
        """Return whether the active site has an explicit physical source mapping."""
        self._normalize_sites()
        config = self.state.get("site_configs", {}).get(self.state.get("active_site_id"), {})
        power = config.get("power", {}) if isinstance(config, dict) else {}
        meter = config.get("meter", {}) if isinstance(config, dict) else {}
        return bool(
            power.get("solar_entities")
            or any(power.get(field) for field in POWER_FIELDS)
            or any(meter.get(field) for field in METER_FIELDS)
        )
