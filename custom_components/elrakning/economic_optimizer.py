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


def _unavailable(reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "available": False,
        "reason": reason,
        "model_version": MODEL_VERSION,
        "model_kind": "deterministic_mip",
        **extra,
    }


def _validate_inputs(inputs: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(inputs, dict):
        return None, "inputs_missing"
    site_id = inputs.get("site_id")
    known_at = _iso(inputs.get("known_at"))
    slots = inputs.get("slots")
    ess = inputs.get("ess")
    replanning = inputs.get("replanning")
    if not isinstance(site_id, str) or not site_id or not known_at:
        return None, "site_or_known_at_missing"
    if not isinstance(slots, list) or not MIN_SLOTS <= len(slots) <= MAX_SLOTS:
        return None, "horizon_outside_24_to_36_hours"
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
    if not isinstance(replanning, dict):
        return None, "explicit_replanning_policy_missing"
    required_ess = (
        "soc_fraction", "capacity_kwh", "reserve_soc_fraction", "max_charge_kw",
        "max_discharge_kw", "charge_efficiency", "discharge_efficiency",
    )
    values = {key: _number(ess.get(key)) for key in required_ess}
    if any(value is None for value in values.values()):
        return None, "verified_ess_bounds_missing"
    if not 0 <= values["reserve_soc_fraction"] <= values["soc_fraction"] <= 1:
        return None, "invalid_verified_soc_state"
    if values["capacity_kwh"] <= 0 or values["max_charge_kw"] < 0 or values["max_discharge_kw"] < 0:
        return None, "invalid_verified_ess_bounds"
    if not 0 < values["charge_efficiency"] <= 1 or not 0 < values["discharge_efficiency"] <= 1:
        return None, "invalid_verified_efficiency"
    policy_fields = ("max_charge_ramp_kw", "max_discharge_ramp_kw", "hysteresis_kw", "previous_charge_kw", "previous_discharge_kw")
    policy_values = {key: _number(replanning.get(key)) for key in policy_fields}
    if any(value is None for value in policy_values.values()):
        return None, "explicit_replanning_policy_incomplete"
    if any(value < 0 for value in policy_values.values()) or policy_values["hysteresis_kw"] > max(values["max_charge_kw"], values["max_discharge_kw"]):
        return None, "invalid_replanning_policy"
    if policy_values["previous_charge_kw"] > values["max_charge_kw"] or policy_values["previous_discharge_kw"] > values["max_discharge_kw"]:
        return None, "invalid_previous_action"
    normalized_slots = []
    known_moment = _moment(known_at)
    previous_valid_at = None
    previous_moment = None
    for slot in slots:
        if not isinstance(slot, dict):
            return None, "invalid_slot"
        valid_at = _iso(slot.get("valid_at"))
        valid_moment = _moment(valid_at) if valid_at else None
        required = {key: _number(slot.get(key)) for key in (
            "load_kw", "solar_kw", "import_price_sek_per_kwh", "export_value_sek_per_kwh",
        )}
        if not valid_at or valid_moment is None or any(value is None for value in required.values()):
            return None, "decision_economics_or_forecast_missing"
        if known_moment is None or valid_moment <= known_moment:
            return None, "forecast_not_causal"
        if required["load_kw"] < 0 or required["solar_kw"] < 0:
            return None, "invalid_economic_input"
        if previous_valid_at is not None and valid_at <= previous_valid_at:
            return None, "slots_not_strictly_ordered"
        if previous_moment is not None and (valid_moment - previous_moment).total_seconds() != SLOT_SECONDS:
            return None, "slots_not_15_minute_aligned"
        previous_valid_at = valid_at
        previous_moment = valid_moment
        normalized_slots.append({"valid_at": valid_at, **required})
    return {
        "site_id": site_id, "known_at": known_at, "slots": normalized_slots,
        "ess": {**values, "resource_identity": resource_identity},
        "replanning": policy_values,
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
        },
        "constraint_provenance": {
            "verified_ess_facts": True,
            "shared_ess_resource_identity": ess["resource_identity"],
            "no_simultaneous_charge_discharge": True,
            "baseline_forecast_input_only": True,
            "execution_eligible": False,
        },
        "input_fingerprint": _fingerprint(canonical_inputs),
    }
