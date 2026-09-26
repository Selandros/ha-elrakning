"""Deterministic read-only Step 8 economic optimizer."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

try:
    from highspy import Highs, HighsModelStatus, HighsVarType
except ImportError:  # pragma: no cover - exercised by fail-closed runtime tests
    Highs = None
    HighsModelStatus = None
    HighsVarType = None


SCHEMA = "ella_economic_optimizer.v1"
MODEL_VERSION = "highs-mpc-v1"
SLOT_SECONDS = 900
MIN_SLOTS = 96
MAX_SLOTS = 144
EXPORT_FALLBACK_FACTOR = 0.75
PLANNING_EFFICIENCY_SOURCE = "conservative_calibration_planning_assumption"


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime) and value.tzinfo:
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    return None


def _moment(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def derive_provider_reference(grid_state: dict[str, Any], binding: dict[str, Any] | None = None) -> str | None:
    """Derive a stable reference from the exact E.ON agreement components."""
    if not isinstance(grid_state, dict) or grid_state.get("provider") not in {None, "eon"}:
        return None
    agreement = grid_state.get("agreement") if isinstance(grid_state.get("agreement"), dict) else {}
    grid_price = grid_state.get("grid_price") if isinstance(grid_state.get("grid_price"), dict) else {}
    facility = (binding or {}).get("facility") if isinstance(binding, dict) else None
    facility = facility if isinstance(facility, dict) else grid_state.get("facility")
    facility = facility if isinstance(facility, dict) else {}
    identity = {
        "provider": "eon",
        "installation_identifier": facility.get("installation_identifier"),
        "point_of_delivery_number": facility.get("point_of_delivery_number"),
        "agreement": {key: agreement.get(key) for key in ("type", "start_date", "end_date")},
        "grid_price": {key: grid_price.get(key) for key in (
            "vat_included", "price_basis", "fixed_monthly_sek",
            "transfer_ore_per_kwh_gross", "energy_tax_ore_per_kwh_gross",
            "variable_total_ore_per_kwh_gross", "yearly_estimated_sek",
        )},
    }
    if not identity["installation_identifier"] and not identity["point_of_delivery_number"]:
        return None
    if any(identity["grid_price"].get(key) is None for key in (
        "vat_included", "price_basis", "fixed_monthly_sek",
        "transfer_ore_per_kwh_gross", "energy_tax_ore_per_kwh_gross",
        "variable_total_ore_per_kwh_gross",
    )):
        return None
    return f"eon-agreement-{_fingerprint(identity)[:32]}"


def build_eon_economics(grid_state: dict[str, Any], binding: dict[str, Any] | None, decision_at: Any) -> dict[str, Any] | None:
    """Normalize an existing E.ON agreement without copying provider values into storage."""
    if not isinstance(grid_state, dict) or not isinstance(grid_state.get("agreement"), dict):
        return None
    grid_price = grid_state.get("grid_price")
    agreement = grid_state["agreement"]
    reference = derive_provider_reference(grid_state, binding)
    known_at = _iso(decision_at)
    provider_valid_from = agreement.get("start_date")
    if not isinstance(grid_price, dict) or not reference or not known_at or not isinstance(provider_valid_from, str):
        return None
    if len(provider_valid_from) == 10:
        provider_valid_from = f"{provider_valid_from}T00:00:00+00:00"
    provider_valid_to = agreement.get("end_date")
    if isinstance(provider_valid_to, str) and len(provider_valid_to) == 10:
        provider_valid_to = f"{provider_valid_to}T00:00:00+00:00"
    required = ("fixed_monthly_sek", "transfer_ore_per_kwh_gross", "energy_tax_ore_per_kwh_gross", "variable_total_ore_per_kwh_gross", "vat_included")
    if any(grid_price.get(key) is None for key in required) or grid_price.get("vat_included") is not True:
        return None
    return {
        "source_schema": "eon.grid_economic_active_snapshot.v1",
        "known_at": known_at,
        "valid_from": provider_valid_from,
        "valid_to": provider_valid_to,
        "provider_valid_from": provider_valid_from,
        "provider_reference": reference,
        "component_provenance": {
            "provider": "eon",
            "vat_treatment": "gross_included",
            "fixed_fee_not_in_marginal_objective": True,
            "agreement_metadata_preserved": True,
        },
    }


def _unavailable(reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "available": False,
        "reason": reason,
        "model_version": MODEL_VERSION,
        "model_kind": "deterministic_mip",
        **extra,
    }


def _resolve_planning_efficiency(ess: dict[str, Any]) -> tuple[float | None, float | None, dict[str, Any]]:
    """Resolve planning-only efficiency without changing Step 7 physical facts."""
    charge = _number(ess.get("charge_efficiency"))
    discharge = _number(ess.get("discharge_efficiency"))
    if charge is not None and discharge is not None:
        return charge, discharge, {"source_type": "verified_physical_fact"}
    assumption = ess.get("planning_efficiency")
    if not isinstance(assumption, dict) or assumption.get("source_type") != PLANNING_EFFICIENCY_SOURCE:
        return None, None, {}
    charge = _number(assumption.get("charge_efficiency"))
    discharge = _number(assumption.get("discharge_efficiency"))
    if charge is None or discharge is None or not 0 < charge <= 1 or not 0 < discharge <= 1:
        return None, None, {}
    return charge, discharge, {
        "source_type": PLANNING_EFFICIENCY_SOURCE,
        "uncertainty": assumption.get("uncertainty", "bounded_planning_only"),
        "physical_safety_limit": False,
    }


def _resolve_replanning_policy(ess: dict[str, Any], replanning: Any) -> tuple[dict[str, float] | None, dict[str, Any]]:
    """Use explicit policy or deterministic product defaults derived from ESS caps."""
    if isinstance(replanning, dict) and all(_number(replanning.get(key)) is not None for key in (
        "max_charge_ramp_kw", "max_discharge_ramp_kw", "hysteresis_kw",
        "previous_charge_kw", "previous_discharge_kw",
    )):
        return {key: float(replanning[key]) for key in (
            "max_charge_ramp_kw", "max_discharge_ramp_kw", "hysteresis_kw",
            "previous_charge_kw", "previous_discharge_kw",
        )}, {"source_type": "site_override"}
    charge_cap = _number(ess.get("max_charge_kw"))
    discharge_cap = _number(ess.get("max_discharge_kw"))
    if charge_cap is None or discharge_cap is None:
        return None, {}
    return {
        "max_charge_ramp_kw": charge_cap,
        "max_discharge_ramp_kw": discharge_cap,
        "hysteresis_kw": 0.05 * min(charge_cap, discharge_cap),
        "previous_charge_kw": 0.0,
        "previous_discharge_kw": 0.0,
    }, {
        "source_type": "product_policy_default",
        "previous_action_source": "no_prior_action",
        "hysteresis_formula": "0.05 * min(max_charge_kw, max_discharge_kw)",
    }


def _validate_inputs(inputs: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(inputs, dict):
        return None, "inputs_missing"
    site_id = inputs.get("site_id")
    known_at = _iso(inputs.get("known_at"))
    slots = inputs.get("slots")
    ess = inputs.get("ess")
    replanning = inputs.get("replanning")
    economics = inputs.get("economics")
    if not isinstance(site_id, str) or not site_id or not known_at:
        return None, "site_or_known_at_missing"
    if not isinstance(slots, list) or not MIN_SLOTS <= len(slots) <= MAX_SLOTS:
        return None, "horizon_outside_24_to_36_hours"
    if not isinstance(economics, dict):
        return None, "decision_economics_provenance_missing"
    economics_known_at = _moment(_iso(economics.get("known_at")) or "")
    economics_valid_from = _moment(_iso(economics.get("valid_from")) or "")
    economics_valid_to = _moment(_iso(economics.get("valid_to")) or "") if economics.get("valid_to") else None
    known_moment = _moment(known_at)
    provider_valid_from = _moment(_iso(economics.get("provider_valid_from")) or "") if economics.get("provider_valid_from") else None
    override = economics.get("planning_applicability_override")
    override_allowed = False
    override_effective = None
    if provider_valid_from is not None and known_moment is not None and provider_valid_from > known_moment:
        override_known = _moment(_iso(override.get("known_at")) or "") if isinstance(override, dict) else None
        override_effective = _moment(_iso(override.get("effective_from")) or "") if isinstance(override, dict) else None
        if (
            not isinstance(override, dict)
            or override.get("source_type") != "user_configured_planning_applicability_override"
            or override.get("provider_valid_from") != economics.get("provider_valid_from")
            or override.get("provider_reference") != economics.get("provider_reference")
            or not isinstance(override.get("provider_reference"), str)
            or override_known is None or override_effective is None
            or override_known > known_moment or override_effective > known_moment
        ):
            return None, "decision_economics_not_valid"
        override_allowed = True
    effective_economics_valid_from = override_effective if override_allowed and override_effective is not None else economics_valid_from
    if (
        known_moment is None
        or economics_known_at is None
        or economics_valid_from is None
        or economics_known_at > known_moment
        or (economics_valid_from > known_moment and not override_allowed)
        or (economics_valid_to is not None and economics_valid_to <= known_moment)
    ):
        return None, "decision_economics_not_valid"
    if not isinstance(ess, dict):
        return None, "verified_ess_facts_missing"
    resource_identity = ess.get("resource_identity")
    if (
        not isinstance(resource_identity, dict)
        or resource_identity.get("available") is not True
        or resource_identity.get("site_id") != site_id
        or not isinstance(resource_identity.get("resource_id"), str)
        or resource_identity.get("method") != "strong_registry_config_entry_and_device_identity"
    ):
        return None, "shared_ess_resource_identity_missing"
    required_ess = (
        "soc_fraction", "capacity_kwh", "reserve_soc_fraction", "max_charge_kw",
        "max_discharge_kw", "charge_efficiency", "discharge_efficiency",
    )
    values = {key: _number(ess.get(key)) for key in required_ess}
    charge_efficiency, discharge_efficiency, efficiency_provenance = _resolve_planning_efficiency(ess)
    values["charge_efficiency"] = charge_efficiency
    values["discharge_efficiency"] = discharge_efficiency
    if any(value is None for value in values.values()):
        return None, "verified_ess_bounds_missing"
    if not 0 <= values["reserve_soc_fraction"] <= values["soc_fraction"] <= 1:
        return None, "invalid_verified_soc_state"
    if values["capacity_kwh"] <= 0 or values["max_charge_kw"] < 0 or values["max_discharge_kw"] < 0:
        return None, "invalid_verified_ess_bounds"
    if not 0 < values["charge_efficiency"] <= 1 or not 0 < values["discharge_efficiency"] <= 1:
        return None, "invalid_verified_efficiency"
    policy_values, policy_provenance = _resolve_replanning_policy(ess, replanning)
    if policy_values is None:
        return None, "replanning_policy_or_ess_caps_missing"
    if any(value < 0 for value in policy_values.values()) or policy_values["hysteresis_kw"] > max(values["max_charge_kw"], values["max_discharge_kw"]):
        return None, "invalid_replanning_policy"
    if policy_values["previous_charge_kw"] > values["max_charge_kw"] or policy_values["previous_discharge_kw"] > values["max_discharge_kw"]:
        return None, "invalid_previous_action"
    normalized_slots = []
    previous_valid_at = None
    previous_moment = None
    for slot in slots:
        if not isinstance(slot, dict):
            return None, "invalid_slot"
        valid_at = _iso(slot.get("valid_at"))
        valid_moment = _moment(valid_at) if valid_at else None
        required = {key: _number(slot.get(key)) for key in (
            "load_kw", "solar_kw", "import_price_sek_per_kwh",
        )}
        if not valid_at or valid_moment is None or any(value is None for value in required.values()):
            return None, "decision_economics_or_forecast_missing"
        explicit_export = slot.get("export_value_sek_per_kwh")
        if explicit_export is None:
            export_value = required["import_price_sek_per_kwh"] * EXPORT_FALLBACK_FACTOR
            export_value_source = "derived_export_value_fallback"
        else:
            export_value = _number(explicit_export)
            if export_value is None:
                return None, "decision_economics_or_forecast_missing"
            export_value_source = "explicit_export_compensation"
        if known_moment is None or valid_moment <= known_moment:
            return None, "forecast_not_causal"
        if effective_economics_valid_from is None or valid_moment < effective_economics_valid_from or (economics_valid_to is not None and valid_moment >= economics_valid_to):
            return None, "decision_economics_not_valid"
        if required["load_kw"] < 0 or required["solar_kw"] < 0:
            return None, "invalid_economic_input"
        if previous_valid_at is not None and valid_at <= previous_valid_at:
            return None, "slots_not_strictly_ordered"
        if previous_moment is not None and (valid_moment - previous_moment).total_seconds() != SLOT_SECONDS:
            return None, "slots_not_15_minute_aligned"
        previous_valid_at = valid_at
        previous_moment = valid_moment
        normalized_slots.append({
            "valid_at": valid_at,
            **required,
            "export_value_sek_per_kwh": export_value,
            "export_value_source": export_value_source,
        })
    return {
        "site_id": site_id, "known_at": known_at, "slots": normalized_slots,
        "ess": {**values, "resource_identity": resource_identity},
        "replanning": policy_values,
        "economics": economics,
        "efficiency_provenance": efficiency_provenance,
        "replanning_provenance": policy_provenance,
    }, None


def build_economic_plan(inputs: dict[str, Any]) -> dict[str, Any]:
    """Solve a bounded 15-minute import/export battery MIP without writes."""
    normalized, reason = _validate_inputs(inputs)
    if normalized is None:
        return _unavailable(reason or "invalid_inputs")
    if Highs is None:
        return _unavailable("highspy_unavailable")

    site_id = normalized["site_id"]
    slots = normalized["slots"]
    ess = normalized["ess"]
    replanning = normalized["replanning"]
    horizon = len(slots)
    dt_hours = SLOT_SECONDS / 3600
    solver = Highs()
    solver.setOptionValue("output_flag", False)
    charge = []
    discharge = []
    grid_import = []
    grid_export = []
    energy = [solver.addVariable(
        lb=ess["soc_fraction"] * ess["capacity_kwh"],
        ub=ess["soc_fraction"] * ess["capacity_kwh"],
        name="energy_0",
    )]
    modes = []
    charge_active = []
    discharge_active = []
    grid_modes = []
    grid_bound = max(
        1.0,
        max((slot["load_kw"] + slot["solar_kw"] + ess["max_charge_kw"] + ess["max_discharge_kw"] for slot in slots), default=1.0),
    )
    for index, slot in enumerate(slots):
        charge.append(solver.addVariable(lb=0, ub=ess["max_charge_kw"], obj=0, name=f"charge_{index}"))
        discharge.append(solver.addVariable(lb=0, ub=ess["max_discharge_kw"], obj=0, name=f"discharge_{index}"))
        grid_import.append(solver.addVariable(lb=0, ub=math.inf, obj=slot["import_price_sek_per_kwh"] * dt_hours, name=f"import_{index}"))
        grid_export.append(solver.addVariable(lb=0, ub=math.inf, obj=-slot["export_value_sek_per_kwh"] * dt_hours, name=f"export_{index}"))
        charge_active.append(solver.addVariable(lb=0, ub=1, type=HighsVarType.kInteger, name=f"charge_active_{index}"))
        discharge_active.append(solver.addVariable(lb=0, ub=1, type=HighsVarType.kInteger, name=f"discharge_active_{index}"))
        grid_modes.append(solver.addVariable(lb=0, ub=1, type=HighsVarType.kInteger, name=f"grid_mode_{index}"))
        energy.append(solver.addVariable(lb=ess["reserve_soc_fraction"] * ess["capacity_kwh"], ub=ess["capacity_kwh"], name=f"energy_{index + 1}"))
        solver.addConstr(grid_import[index] - grid_export[index] + slot["solar_kw"] + discharge[index] - charge[index] == slot["load_kw"], name=f"balance_{index}")
        solver.addConstr(charge[index] <= ess["max_charge_kw"] * charge_active[index], name=f"charge_mode_{index}")
        solver.addConstr(discharge[index] <= ess["max_discharge_kw"] * discharge_active[index], name=f"discharge_mode_{index}")
        solver.addConstr(charge[index] >= replanning["hysteresis_kw"] * charge_active[index], name=f"charge_hysteresis_{index}")
        solver.addConstr(discharge[index] >= replanning["hysteresis_kw"] * discharge_active[index], name=f"discharge_hysteresis_{index}")
        solver.addConstr(charge_active[index] + discharge_active[index] <= 1, name=f"battery_direction_{index}")
        previous_charge = replanning["previous_charge_kw"] if index == 0 else charge[index - 1]
        previous_discharge = replanning["previous_discharge_kw"] if index == 0 else discharge[index - 1]
        solver.addConstr(charge[index] - previous_charge <= replanning["max_charge_ramp_kw"], name=f"charge_ramp_up_{index}")
        solver.addConstr(previous_charge - charge[index] <= replanning["max_charge_ramp_kw"], name=f"charge_ramp_down_{index}")
        solver.addConstr(discharge[index] - previous_discharge <= replanning["max_discharge_ramp_kw"], name=f"discharge_ramp_up_{index}")
        solver.addConstr(previous_discharge - discharge[index] <= replanning["max_discharge_ramp_kw"], name=f"discharge_ramp_down_{index}")
        solver.addConstr(grid_import[index] <= grid_bound * grid_modes[index], name=f"import_mode_{index}")
        solver.addConstr(grid_export[index] <= grid_bound * (1 - grid_modes[index]), name=f"export_mode_{index}")
        solver.addConstr(energy[index + 1] == energy[index] + charge[index] * dt_hours * ess["charge_efficiency"] - discharge[index] * dt_hours / ess["discharge_efficiency"], name=f"energy_balance_{index}")
    solver.minimize()
    if solver.getModelStatus() != HighsModelStatus.kOptimal:
        return _unavailable("optimizer_no_optimal_solution", site_id=site_id)
    solution = solver.getSolution().col_value
    points = []
    offset = 1
    for index, slot in enumerate(slots):
        points.append({
            "valid_at": slot["valid_at"],
            "charge_kw": round(float(solution[offset]), 9),
            "discharge_kw": round(float(solution[offset + 1]), 9),
            "import_kw": round(float(solution[offset + 2]), 9),
            "export_kw": round(float(solution[offset + 3]), 9),
            "energy_kwh": round(float(solution[offset + 7]), 9),
            "export_value_source": slot["export_value_source"],
        })
        offset += 8
    canonical_inputs = {**normalized, "model_version": MODEL_VERSION}
    return {
        "schema": SCHEMA,
        "available": True,
        "site_id": site_id,
        "model_version": MODEL_VERSION,
        "model_kind": "deterministic_mip",
        "solver": "HiGHS",
        "horizon_slots": horizon,
        "slot_seconds": SLOT_SECONDS,
        "points": points,
        "objective": {
            "energy_cost_sek": round(float(solver.getInfo().objective_function_value), 9),
            "fixed_fees_in_objective": False,
            "degradation_cost": "omitted_unavailable",
            "replanning_policy": replanning,
            "replanning_provenance": normalized["replanning_provenance"],
        },
        "economics_provenance": {
            "known_at": normalized["economics"].get("known_at"),
            "valid_from": normalized["economics"].get("valid_from"),
            "valid_to": normalized["economics"].get("valid_to"),
            "provider_valid_from": normalized["economics"].get("provider_valid_from"),
            "planning_applicability_override": normalized["economics"].get("planning_applicability_override"),
            "export_value_policy": "explicit_or_spot_minus_25_percent",
            "derived_export_value_fallback": {
                "formula": "spot_price_sek_per_kwh * 0.75",
                "factor": EXPORT_FALLBACK_FACTOR,
                "source_type": "derived_policy",
            },
        },
        "constraint_provenance": {
            "verified_ess_facts": True,
            "shared_ess_resource_identity": ess["resource_identity"],
            "no_simultaneous_charge_discharge": True,
            "baseline_forecast_input_only": True,
            "execution_eligible": False,
            "efficiency": normalized["efficiency_provenance"],
        },
        "input_fingerprint": _fingerprint(canonical_inputs),
    }
