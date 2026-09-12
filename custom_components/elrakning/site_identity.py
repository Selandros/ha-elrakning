"""Persistent site identity and configured source mapping history."""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from datetime import datetime
from typing import Any

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .meter import METER_FIELDS
from .power import POWER_FIELDS


STORE_KEY = "elrakning.site_identity"
STORE_VERSION = 1
SITE_BINDING_SERVICES = ("elhandel", "grid")

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
            if migrated_global_price:
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

    def active_binding(self, service: str) -> dict[str, Any] | None:
        """Return only the active site's explicit binding for one service."""
        self._normalize_sites()
        config = self.state.get("site_configs", {}).get(self.state.get("active_site_id"), {})
        bindings = config.get("bindings", {}) if isinstance(config, dict) else {}
        binding = bindings.get(service) if isinstance(bindings, dict) else None
        return dict(binding) if isinstance(binding, dict) else None

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
