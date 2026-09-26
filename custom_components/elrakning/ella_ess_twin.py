"""Deterministic, read-only ESS digital-twin and health facts."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from statistics import median
from typing import Any


SCHEMA = "ella_ess_digital_twin.v1"
MODEL_VERSION = "ess-digital-twin-v1"
QUALITY = {"good", "partial"}
MIN_COVERAGE = 0.9


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else None
    return None


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _resource_id(row: dict[str, Any], bindings: dict[str, str]) -> str | None:
    explicit = row.get("resource_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    generation = row.get("source_generation_id")
    bound = bindings.get(str(generation)) if generation else None
    if isinstance(bound, str) and bound:
        return bound
    provenance = row.get("provenance")
    if isinstance(provenance, dict):
        value = provenance.get("resource_id")
        if isinstance(value, str) and value:
            return value
    return None


def _usable_row(
    row: dict[str, Any], site_id: str, role: str, decision_at: datetime,
    active_generations: set[str] | None,
) -> bool:
    if row.get("site_id") != site_id or row.get("logical_role") != role:
        return False
    if row.get("quality_status") not in QUALITY:
        return False
    coverage = _number(row.get("coverage_ratio"))
    if coverage is not None and coverage < MIN_COVERAGE:
        return False
    if active_generations is not None and str(row.get("source_generation_id")) not in active_generations:
        return False
    observed = _datetime(row.get("observed_at")) or _datetime(row.get("interval_end"))
    if observed is None or observed > decision_at:
        return False
    return _number(row.get("value")) is not None


def _latest_by_generation(rows: list[dict[str, Any]], role: str, site_id: str, decision_at: datetime,
                          active_generations: set[str] | None, bindings: dict[str, str]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not _usable_row(row, site_id, role, decision_at, active_generations):
            continue
        generation = str(row.get("source_generation_id") or "")
        if not generation:
            continue
        observed = _datetime(row.get("observed_at")) or _datetime(row.get("interval_end"))
        previous = latest.get(generation)
        if previous is None or observed > previous["_observed"]:
            latest[generation] = {
                "source_generation_id": generation,
                "resource_id": _resource_id(row, bindings),
                "value": _number(row.get("value")),
                "unit": row.get("unit"),
                "observed_at": _iso(observed),
                "_observed": observed,
                "quality_status": row.get("quality_status"),
                "coverage_ratio": row.get("coverage_ratio"),
                "sign_convention": row.get("sign_convention"),
            }
    for item in latest.values():
        item.pop("_observed", None)
    return [latest[key] for key in sorted(latest)]


def _role_facts(rows: list[dict[str, Any]], site_id: str, role: str, decision_at: datetime,
                active_generations: dict[str, set[str]] | None, bindings: dict[str, str]) -> list[dict[str, Any]]:
    active = active_generations.get(role) if isinstance(active_generations, dict) else None
    if role in {"battery.power", "battery.soc", "battery.capacity"} and active is not None and len(active) > 1:
        return []
    return _latest_by_generation(rows, role, site_id, decision_at, active, bindings)


def _throughput(rows: list[dict[str, Any]], site_id: str, decision_at: datetime,
                active_generations: set[str] | None) -> dict[str, Any]:
    if active_generations is not None and len(active_generations) > 1:
        return {"available": False, "reason": "ambiguous_active_battery_generation", "sample_count": 0}
    values: list[float] = []
    generation_ids: set[str] = set()
    for row in rows:
        if not _usable_row(row, site_id, "battery.power", decision_at, active_generations):
            continue
        if row.get("unit") != "W" or row.get("sign_convention") != "positive_discharge_negative_charge":
            continue
        start = _datetime(row.get("interval_start"))
        end = _datetime(row.get("interval_end"))
        value = _number(row.get("value"))
        if not start or not end or end <= start or value is None:
            continue
        values.append(abs(value) * (end - start).total_seconds() / 3_600_000)
        generation_ids.add(str(row.get("source_generation_id")))
    if not values:
        return {"available": False, "reason": "no_qualified_active_battery_power", "sample_count": 0}
    return {
        "available": True,
        "throughput_kwh": sum(values),
        "sample_count": len(values),
        "source_generation_ids": sorted(generation_ids),
        "method": "sum_absolute_canonical_power_times_interval",
    }


def _unavailable(reason: str, **extra: Any) -> dict[str, Any]:
    return {"available": False, "reason": reason, **extra}


def build_ess_trajectory(
    slots: list[dict[str, Any]],
    *,
    soc_fraction: float,
    usable_capacity_kwh: float,
    min_soc_fraction: float,
    max_soc_fraction: float,
    reserve_soc_fraction: float,
    max_charge_power_kw: float,
    max_discharge_power_kw: float,
    charge_efficiency: float,
    discharge_efficiency: float,
    actions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project an explicitly supplied physical trajectory without writes."""
    values = [soc_fraction, usable_capacity_kwh, min_soc_fraction, max_soc_fraction,
              reserve_soc_fraction, max_charge_power_kw, max_discharge_power_kw,
              charge_efficiency, discharge_efficiency]
    if not all(math.isfinite(float(value)) for value in values) or usable_capacity_kwh <= 0:
        return _unavailable("invalid_verified_trajectory_inputs", points=[], execution_eligible=False)
    minimum = max(min_soc_fraction, reserve_soc_fraction)
    if not (0 <= minimum <= soc_fraction <= max_soc_fraction <= 1 and
            max_charge_power_kw >= 0 and max_discharge_power_kw >= 0 and
            0 < charge_efficiency <= 1 and 0 < discharge_efficiency <= 1):
        return _unavailable("invalid_verified_trajectory_inputs", points=[], execution_eligible=False)
    current_energy = soc_fraction * usable_capacity_kwh
    points = []
    for slot in slots:
        start = _datetime(slot.get("start"))
        end = _datetime(slot.get("end"))
        if not start or not end or end <= start:
            return _unavailable("invalid_slot_interval", points=[], execution_eligible=False)
        action = (actions or {}).get(_iso(start), {})
        code = action.get("code", "hold_ess")
        requested = _number(action.get("power_kw")) or 0.0
        if requested < 0 or code not in {"hold_ess", "charge_ess", "discharge_ess"}:
            return _unavailable("unsupported_trajectory_action", points=[], execution_eligible=False)
        hours = (end - start).total_seconds() / 3600
        if code == "charge_ess":
            power_kw = min(requested, max_charge_power_kw)
            current_energy = min(max_soc_fraction * usable_capacity_kwh,
                                 current_energy + power_kw * hours * charge_efficiency)
        elif code == "discharge_ess":
            power_kw = min(requested, max_discharge_power_kw)
            current_energy = max(minimum * usable_capacity_kwh,
                                 current_energy - power_kw * hours / discharge_efficiency)
        else:
            power_kw = 0.0
        points.append({
            "start": _iso(start), "end": _iso(end), "action": code,
            "power_kw": power_kw, "energy_kwh": current_energy,
            "soc_fraction": current_energy / usable_capacity_kwh,
            "semantics": "READ_ONLY_TRAJECTORY",
        })
    return {
        "available": True, "reason": "verified_bounded_trajectory", "points": points,
        "execution_eligible": False, "actuator_writes_enabled": False,
        "constraints": {"min_soc_fraction": minimum, "max_soc_fraction": max_soc_fraction,
                        "max_charge_power_kw": max_charge_power_kw,
                        "max_discharge_power_kw": max_discharge_power_kw,
                        "charge_efficiency": charge_efficiency,
                        "discharge_efficiency": discharge_efficiency},
    }


def build_ess_digital_twin(
    site_id: str,
    actual_rows: list[dict[str, Any]],
    decision_at: datetime,
    *,
    active_generations: dict[str, set[str]] | None = None,
    resource_bindings: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build observed ESS facts and fail closed where physical mapping is absent."""
    bindings = resource_bindings or {}
    roles = {role: _role_facts(actual_rows, site_id, role, decision_at, active_generations, bindings)
             for role in ("battery.power", "battery.soc", "battery.capacity", "battery.temperature", "battery.soh")}
    mapped: dict[str, dict[str, dict[str, Any]]] = {}
    for role, facts in roles.items():
        for fact in facts:
            resource = fact.get("resource_id")
            if resource:
                mapped.setdefault(resource, {})[role] = fact
    resources = []
    for resource, facts in sorted(mapped.items()):
        required = {"battery.power", "battery.soc", "battery.capacity"}
        if not required <= facts.keys():
            continue
        capacity = facts["battery.capacity"].get("value")
        soc = facts["battery.soc"].get("value")
        resources.append({
            "resource_id": resource, "facts": facts,
            "state": {"soc_percent": soc, "capacity_kwh": capacity,
                       "power_w": facts["battery.power"].get("value")},
            "constraints": _unavailable("verified_ess_limits_missing"),
            "energy_balance": _unavailable("verified_efficiency_or_standby_loss_missing"),
            "health": {"available": False, "reason": "no_verified_soh_or_capacity_pair"},
            "provenance": {"source_generation_ids": sorted({item.get("source_generation_id") for item in facts.values()})},
        })
    battery_generations = (active_generations or {}).get("battery.power") if active_generations else None
    throughput = _throughput(actual_rows, site_id, decision_at, battery_generations)
    efc = _unavailable("no_verified_resource_capacity_pair")
    temperature = _unavailable("verified_temperature_source_missing")
    derating = _unavailable("verified_derating_source_missing")
    aggregate = (
        {"available": True, "resource_count": len(resources),
         "soc_percent": median([item["state"]["soc_percent"] for item in resources]),
         "capacity_kwh": sum(item["state"]["capacity_kwh"] for item in resources),
         "power_w": sum(item["state"]["power_w"] for item in resources),
         "method": "sum_verified_resource_states"}
        if resources else _unavailable("no_verified_resource_mapping")
    )
    return {
        "schema": SCHEMA, "model_version": MODEL_VERSION, "site_id": site_id,
        "known_at": _iso(decision_at), "available": bool(roles["battery.power"]),
        "observed": {"battery_power": roles["battery.power"], "soc": roles["battery.soc"],
                     "capacity": roles["battery.capacity"]},
        "resources": resources, "aggregate": aggregate,
        "health": {"throughput": throughput, "efc": efc,
                    "soh": _unavailable("no_verified_soh_source_or_capacity_pair"),
                    "temperature": temperature, "derating": derating},
        "energy_balance": _unavailable("no_verified_resource_mapping_or_efficiency"),
        "soc_drift": _unavailable("no_predicted_soc_trajectory"),
        "quality": {"status": "observed_facts_only", "active_generation_ids": {
            role: sorted(values) for role, values in (active_generations or {}).items()}},
        "execution_eligible": False, "actuator_writes_enabled": False,
    }
