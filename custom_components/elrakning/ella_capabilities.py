"""Derived site-scoped ELLA capability inventory v1."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from .ella_load_registry import EllaLoadRegistry


SCHEMA = "ella_capability_inventory.v1"


def _status(available: bool, *, reason: str | None = None, partial: bool = False, stale: bool = False) -> str:
    if stale:
        return "stale"
    if available and partial:
        return "partial"
    return "available" if available else "unavailable"


def _capability(
    capability_id: str,
    capability_type: str,
    site_id: str,
    *,
    available: bool = False,
    partial: bool = False,
    reason: str | None = None,
    source: dict[str, Any] | None = None,
    observation_available: bool = False,
    forecast_available: bool = False,
    actuator_available: bool = False,
    control_mode: str = "observe_only",
    execution_eligible: bool = False,
    used_by_current_plan: bool = False,
    quality: Any = None,
) -> dict[str, Any]:
    source = source or {}
    return {
        "capability_id": capability_id,
        "type": capability_type,
        "site_id": site_id,
        "availability": _status(available, partial=partial),
        "verified": bool(available),
        "reason": reason,
        "source": {
            "dataset": source.get("dataset"),
            "logical_role": source.get("logical_role"),
            "entity_id": source.get("entity_id"),
            "generation_id": source.get("generation_id"),
            "resource_id": source.get("resource_id"),
            "frame_ids": sorted(source.get("frame_ids", [])),
            "resources": deepcopy(source.get("resources", [])),
            "binding_fingerprint": source.get("binding_fingerprint"),
            "entities": deepcopy(source.get("entities", {})),
        },
        "known_at": source.get("known_at"),
        "captured_at": source.get("captured_at"),
        "freshness": source.get("freshness"),
        "quality": deepcopy(quality),
        "observation_available": observation_available,
        "forecast_available": forecast_available,
        "actuator_available": actuator_available,
        "control_mode": control_mode,
        "execution_eligible": execution_eligible,
        "used_by_current_plan": used_by_current_plan,
    }


def _site_rows(site_manager: Any, site_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    state = getattr(site_manager, "state", {})
    sites = state.get("sites", []) if isinstance(state, dict) else []
    site = next((deepcopy(item) for item in sites if isinstance(item, dict) and item.get("site_id") == site_id), None)
    ledger = state.get("ledger", []) if isinstance(state, dict) else []
    rows = [deepcopy(item) for item in ledger if isinstance(item, dict) and item.get("site_id") == site_id and item.get("effective_to") is None]
    return site or {}, rows


def _roles(rows: list[dict[str, Any]], role: str) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("logical_role") == role]


def _binding(site_manager: Any, site_id: str, service: str) -> dict[str, Any] | None:
    state = getattr(site_manager, "state", {})
    config = state.get("site_configs", {}).get(site_id, {}) if isinstance(state, dict) else {}
    bindings = config.get("bindings", {}) if isinstance(config, dict) else {}
    value = bindings.get(service) if isinstance(bindings, dict) else None
    return deepcopy(value) if isinstance(value, dict) else None


def _source(row: dict[str, Any] | None, *, dataset: str | None = None) -> dict[str, Any]:
    if not row:
        return {"dataset": dataset}
    return {
        "dataset": dataset,
        "logical_role": row.get("logical_role"),
        "entity_id": row.get("entity_id"),
        "generation_id": row.get("generation_id"),
        "resource_id": row.get("resource_id"),
        "known_at": row.get("provenance", {}).get("known_at") if isinstance(row.get("provenance"), dict) else None,
    }


def _sources(rows: list[dict[str, Any]], *, dataset: str | None = None) -> dict[str, Any]:
    """Preserve every active resource while keeping the legacy first source shape."""
    resources = [_source(row, dataset=dataset) for row in rows]
    first = deepcopy(resources[0]) if resources else {"dataset": dataset}
    first["resources"] = resources
    return first


def _valid_binding(site_manager: Any, binding: dict[str, Any] | None) -> bool:
    if not isinstance(binding, dict):
        return False
    fingerprint = binding.get("binding_fingerprint")
    checker = getattr(site_manager, "binding_fingerprint", None)
    if not isinstance(fingerprint, str) or not callable(checker):
        return False
    return fingerprint == checker(binding)


def build_capability_inventory(
    site_manager: Any,
    load_registry: EllaLoadRegistry,
    site_id: str,
    *,
    load_forecast: dict[str, Any] | None = None,
    now: datetime | None = None,
    entity_available: Any = None,
) -> dict[str, Any]:
    """Build a deterministic inventory from explicit bindings and canonical roles."""
    site, rows = _site_rows(site_manager, site_id)
    if not site:
        raise ValueError("site_not_found")
    now_value = (now or datetime.now().astimezone()).isoformat()
    price_binding = getattr(site_manager, "global_binding", lambda _service: None)("nord_pool")
    retail_binding = _binding(site_manager, site_id, "elhandel")
    grid_binding = _binding(site_manager, site_id, "grid")
    forecast_binding = _binding(site_manager, site_id, "forecast")
    house = _roles(rows, "house.consumption")
    solar = _roles(rows, "solar.production")
    grid_power = _roles(rows, "grid.power/import")
    grid_import = _roles(rows, "grid.energy_import")
    grid_export = _roles(rows, "grid.energy_export")
    battery_power = _roles(rows, "battery.power")
    battery_soc = _roles(rows, "battery.soc")
    battery_capacity = _roles(rows, "battery.capacity")
    forecast = load_forecast or {"available": False, "reason": "not_loaded", "frames": []}
    frames = forecast.get("frames", []) if isinstance(forecast, dict) else []
    load_available = bool(forecast.get("available")) and all(frame.get("site_id") == site_id for frame in frames if isinstance(frame, dict))
    load_source = {
        "dataset": "load_forecast.v1",
        "logical_role": "load.forecast",
        "frame_ids": [frame.get("frame_id") for frame in frames if isinstance(frame, dict) and frame.get("frame_id")],
        "known_at": max((frame.get("known_at") for frame in frames if isinstance(frame, dict) and frame.get("known_at")), default=None),
    }
    capabilities = [
        _capability("price.spot", "price", site_id, available=_valid_binding(site_manager, price_binding), reason=None if _valid_binding(site_manager, price_binding) else "explicit_price_binding_invalid", source={"dataset": "price_data.v1", "binding_fingerprint": price_binding.get("binding_fingerprint") if isinstance(price_binding, dict) else None}, forecast_available=_valid_binding(site_manager, price_binding), used_by_current_plan=_valid_binding(site_manager, price_binding), quality="verified_binding" if _valid_binding(site_manager, price_binding) else None),
        _capability("cost.electricity_retail", "electricity_retail", site_id, available=_valid_binding(site_manager, retail_binding), reason=None if _valid_binding(site_manager, retail_binding) else "explicit_retail_binding_invalid", source={"dataset": "electricity_provider_binding.v1", "binding_fingerprint": retail_binding.get("binding_fingerprint") if isinstance(retail_binding, dict) else None}),
        _capability("cost.grid_tariff", "grid_tariff", site_id, available=_valid_binding(site_manager, grid_binding), reason=None if _valid_binding(site_manager, grid_binding) else "explicit_grid_binding_invalid", source={"dataset": "grid_binding.v1", "binding_fingerprint": grid_binding.get("binding_fingerprint") if isinstance(grid_binding, dict) else None}),
        _capability("load.house_total.actual", "house_total_consumption", site_id, available=bool(house), reason=None if house else "canonical_role_missing", source=_sources(house, dataset="canonical.house.consumption"), observation_available=bool(house)),
        _capability("load.house_total.forecast", "load_forecast", site_id, available=load_available, reason=None if load_available else forecast.get("reason", "no_supported_history"), source=load_source, forecast_available=load_available, quality=[frame.get("quality") for frame in frames if isinstance(frame, dict)]),
        _capability("grid.power", "grid_import_export_power", site_id, available=bool(grid_power), reason=None if grid_power else "canonical_role_missing", source=_sources(grid_power, dataset="canonical.grid.power"), observation_available=bool(grid_power)),
        _capability("grid.energy_import", "grid_import_energy", site_id, available=bool(grid_import), reason=None if grid_import else "canonical_role_missing", source=_sources(grid_import, dataset="canonical.grid.energy_import"), observation_available=bool(grid_import)),
        _capability("grid.energy_export", "grid_export_energy", site_id, available=bool(grid_export), reason=None if grid_export else "canonical_role_missing", source=_sources(grid_export, dataset="canonical.grid.energy_export"), observation_available=bool(grid_export)),
        _capability("solar.actual", "solar_actual", site_id, available=bool(solar), reason=None if solar else "canonical_role_missing", source=_sources(solar, dataset="canonical.solar.production"), observation_available=bool(solar), used_by_current_plan=False),
        _capability("solar.forecast", "solar_forecast", site_id, available=_valid_binding(site_manager, forecast_binding), reason=None if _valid_binding(site_manager, forecast_binding) else "explicit_forecast_binding_invalid", source={"dataset": "solar_forecast.v1", "binding_fingerprint": forecast_binding.get("binding_fingerprint") if isinstance(forecast_binding, dict) else None, "entities": forecast_binding.get("entities", {}) if isinstance(forecast_binding, dict) else {}, "resources": [{"dataset": "solar_forecast.v1", "binding_fingerprint": forecast_binding.get("binding_fingerprint"), "entities": forecast_binding.get("entities", {})}] if isinstance(forecast_binding, dict) else []}, forecast_available=_valid_binding(site_manager, forecast_binding), used_by_current_plan=False),
        _capability("battery.power", "battery_power", site_id, available=bool(battery_power), reason=None if battery_power else "canonical_role_missing", source=_sources(battery_power, dataset="canonical.battery.power"), observation_available=bool(battery_power), used_by_current_plan=False),
        _capability("battery.soc", "battery_soc", site_id, available=bool(battery_soc), reason=None if battery_soc else "canonical_role_missing", source=_sources(battery_soc, dataset="canonical.battery.soc"), observation_available=bool(battery_soc), used_by_current_plan=False),
        _capability("battery.capacity", "battery_capacity", site_id, available=bool(battery_capacity), reason=None if battery_capacity else "canonical_role_missing", source=_sources(battery_capacity, dataset="canonical.battery.capacity"), observation_available=bool(battery_capacity), used_by_current_plan=False),
    ]
    loads = load_registry.list_for_site(site_id)
    individual = []
    for load in loads:
        measurement = load.get("measurement")
        actuator = load.get("actuator")
        measurement_present = bool(measurement and entity_available and entity_available(measurement))
        actuator_present = bool(actuator and entity_available and entity_available(actuator))
        individual.append({
            "load_id": load["load_id"], "site_id": site_id, "enabled": load["enabled"],
            "measurement_configured": bool(measurement), "measurement_available": measurement_present,
            "actuator_configured": bool(actuator), "actuator_available": actuator_present,
            "reason": "entity_missing" if (measurement and not measurement_present) or (actuator and not actuator_present) else None,
            "control_mode": load["control_mode"], "criticality": load["criticality"],
            "flexibility": load["flexibility"], "execution_eligible": False,
        })
    capabilities.append(_capability("loads.individual", "individual_loads", site_id, available=bool(individual), partial=any(not row["measurement_available"] for row in individual), reason=None if individual else "registry_empty", source={"dataset": "ella_load_registry.v1"}, observation_available=any(row["measurement_available"] for row in individual), actuator_available=any(row["actuator_available"] for row in individual), execution_eligible=False))
    capabilities.append(_capability("actuators.loads", "load_actuators", site_id, available=False, partial=any(row["actuator_available"] for row in individual), reason="execution_disabled_stage_1", source={"dataset": "ella_load_registry.v1"}, actuator_available=any(row["actuator_available"] for row in individual), execution_eligible=False))
    price_valid = _valid_binding(site_manager, price_binding)
    planner_eligible = price_valid
    return {
        "schema": SCHEMA,
        "site_id": site_id,
        "site": {"site_id": site.get("site_id"), "name": site.get("name")},
        "known_at": now_value,
        "captured_at": now_value,
        "planner": {
            "current_plan": "price_load_v1",
            "price_eligible": price_valid,
            "load_eligible": bool(house),
            "planner_eligible": planner_eligible,
            "solar_ess_used_by_current_plan": False,
        },
        "capabilities": sorted(capabilities, key=lambda item: item["capability_id"]),
        "individual_loads": {"count": len(individual), "items": individual},
        "invariants": {
            "actuator_writes_enabled": False,
            "execution_eligible": False,
            "site_isolation": True,
            "no_fabricated_values": True,
        },
    }
