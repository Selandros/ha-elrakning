"""Deterministic Stage 3 shadow/recommend-only action planning."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import math
from typing import Any

SCHEMA = "ella_action_plan.v1"
PLAN_VERSION = "action-shadow-v1"
ACTION_CODES = frozenset({"normal_operation", "run_flexible_loads", "defer_flexible_loads", "reduce_flexible_loads", "charge_ess", "hold_ess", "discharge_ess"})


def _stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _hash(value: Any, prefix: str) -> str:
    return prefix + sha256(_stable(value).encode()).hexdigest()[:32]


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _cost(slot: dict[str, Any]) -> tuple[float | None, str, list[dict[str, Any]]]:
    stack = slot.get("cost_stack") or {}
    components = [item for item in stack.get("components") or [] if isinstance(item, dict) and item.get("availability") == "available" and isinstance(item.get("value"), (int, float)) and not isinstance(item.get("value"), bool)]
    if not components:
        return None, "unknown", []
    total = sum(float(item["value"]) for item in components)
    if not math.isfinite(total):
        return None, "unknown", []
    basis = "spot" if len(components) == 1 and components[0].get("source") == "nord_pool.price_periods.v1" else "marginal_cost_stack"
    return total, basis, components


def _valid_absolute_windows(windows: Any) -> bool:
    if not isinstance(windows, list) or not windows:
        return False
    return all(isinstance(item, dict) and _parse(item.get("start")) is not None and _parse(item.get("end")) is not None and _parse(item["start"]) < _parse(item["end"]) for item in windows)


def _window_contains(start: datetime, end: datetime, windows: Any) -> bool:
    return any(start >= _parse(item["start"]) and end <= _parse(item["end"]) for item in windows)


def _qualify_load(load: dict[str, Any]) -> dict[str, Any]:
    """Return explicit planning eligibility; unknown non-empty constraints fail closed."""
    mode = load.get("control_mode")
    flexibility = load.get("flexibility")
    base = {"load_id": load.get("load_id"), "source_control_mode": mode, "planner_execution_mode": "shadow", "eligible": False}
    if not load.get("enabled"):
        return {**base, "reason": "disabled"}
    if mode == "observe_only":
        return {**base, "reason": "observe_only_no_recommendation"}
    if mode not in {"recommend_only", "controllable"}:
        return {**base, "reason": "missing_or_invalid_control_mode"}
    if flexibility == "fixed":
        return {**base, "reason": "fixed_load_not_optimizable"}
    if flexibility in {"reducible", "interruptible"}:
        return {**base, "reason": "requires_verified_demand_and_reduction_bounds"}
    if flexibility != "shiftable":
        return {**base, "reason": "unsupported_flexibility"}
    nominal, energy = load.get("nominal_power_w"), load.get("energy_need_kwh")
    if not isinstance(nominal, (int, float)) or isinstance(nominal, bool) or nominal <= 0:
        return {**base, "reason": "missing_verified_nominal_power"}
    if not isinstance(energy, (int, float)) or isinstance(energy, bool) or energy <= 0:
        return {**base, "reason": "missing_verified_energy_need"}
    if _parse(load.get("deadline") or load.get("ready_by")) is None:
        return {**base, "reason": "missing_verified_deadline"}
    windows = load.get("allowed_windows")
    if windows is not None and not _valid_absolute_windows(windows):
        return {**base, "reason": "unsupported_allowed_windows_form"}
    if load.get("min_off_minutes") not in (None, 0):
        return {**base, "reason": "min_off_requires_verified_history"}
    if load.get("constraints"):
        return {**base, "reason": "unsupported_nonempty_constraints"}
    runtime = load.get("min_runtime_minutes")
    if runtime is not None and (isinstance(runtime, bool) or not isinstance(runtime, int) or runtime < 0):
        return {**base, "reason": "invalid_min_runtime"}
    return {**base, "eligible": True, "reason": "qualified_shiftable_load"}


def _net_load_rank(slot: dict[str, Any]) -> int:
    net_load = slot.get("net_load") or {}
    value = net_load.get("value_w") if isinstance(net_load, dict) else None
    return 0 if net_load.get("availability") == "available" and isinstance(value, (int, float)) and value < 0 else 1


def _load_schedule(slots: list[dict[str, Any]], load: dict[str, Any], decision_time: datetime) -> dict[str, Any]:
    """Choose a future contiguous run and expose earlier feasible slots for defer semantics."""
    qualification = _qualify_load(load)
    if not qualification["eligible"]:
        return {"scheduled": set(), "deferred": set(), "qualification": qualification}
    deadline = _parse(load.get("deadline") or load.get("ready_by"))
    nominal, energy = float(load["nominal_power_w"]), float(load["energy_need_kwh"])
    runtime = int(load.get("min_runtime_minutes") or 0)
    required = max(1, math.ceil(energy / ((nominal / 1000.0) * 0.25)), math.ceil(runtime / 15))
    candidates: list[tuple[float, int, int, datetime, int, dict[str, Any]]] = []
    for index, slot in enumerate(slots):
        start, end = _parse(slot.get("start")), _parse(slot.get("end"))
        cost, _, _ = _cost(slot)
        if start is None or end is None or start <= decision_time or end > deadline or cost is None:
            continue
        windows = load.get("allowed_windows")
        if windows is not None and not _window_contains(start, end, windows):
            continue
        priority = load.get("priority") if isinstance(load.get("priority"), int) else 10**9
        candidates.append((cost, _net_load_rank(slot), priority, start, index, slot))
    by_index = {item[4]: item for item in candidates}
    runs: list[tuple[float, int, int, datetime, str, list[dict[str, Any]]]] = []
    for first in sorted(by_index):
        run = [by_index.get(index) for index in range(first, first + required)]
        if any(item is None for item in run):
            continue
        typed_run = [item for item in run if item is not None]
        if any(typed_run[index + 1][5].get("start") != typed_run[index][5].get("end") for index in range(len(typed_run) - 1)):
            continue
        runs.append((sum(item[0] for item in typed_run), sum(item[1] for item in typed_run), typed_run[0][2], typed_run[0][3], load.get("load_id", ""), [item[5] for item in typed_run]))
    if not runs:
        return {"scheduled": set(), "deferred": set(), "qualification": {**qualification, "eligible": False, "reason": "no_future_contiguous_feasible_window"}}
    chosen = min(runs, key=lambda item: (item[0], item[1], item[2], item[3], item[4]))
    scheduled = {item.get("start") for item in chosen[5]}
    first_start = chosen[5][0].get("start")
    deferred = {item[5].get("start") for item in candidates if item[3].isoformat() < first_start and item[5].get("start") not in scheduled}
    return {"scheduled": scheduled, "deferred": deferred, "qualification": qualification}


def _slot_provenance(slot: dict[str, Any]) -> dict[str, Any]:
    refs: set[str] = set()
    qualities: set[str] = set()
    for layer_name in ("price", "load", "solar", "ess", "net_load"):
        layer = slot.get(layer_name) or {}
        if isinstance(layer, dict):
            for key in ("source_generation_id", "generation_id", "frame_id", "resource_id"):
                if isinstance(layer.get(key), str):
                    refs.add(layer[key])
            if isinstance(layer.get("quality"), str):
                qualities.add(layer["quality"])
    for component in (slot.get("cost_stack") or {}).get("components") or []:
        if isinstance(component, dict):
            for key in ("source_generation_id", "generation_id", "frame_id", "resource_id", "source"):
                if isinstance(component.get(key), str):
                    refs.add(component[key])
            if isinstance(component.get("quality"), str):
                qualities.add(component["quality"])
    return {"references": sorted(refs), "quality": sorted(qualities)}


def _ess_eligibility(state: dict[str, Any]) -> dict[str, Any]:
    stage6 = state.get("stage6") if isinstance(state.get("stage6"), dict) else {}
    action_eligibility = (stage6.get("ess") or {}).get("action_eligibility") if isinstance(stage6, dict) else None
    if isinstance(action_eligibility, dict):
        missing = sorted({field for item in action_eligibility.values() if isinstance(item, dict) for field in item.get("missing_fields") or []})
        return {
            "eligible": any(
                item.get("eligible") is True
                for action, item in action_eligibility.items()
                if action != "hold_ess" and isinstance(item, dict)
            ),
            "missing_fields": missing,
            "reason": None if not missing else "missing_verified_ess_policy_constraints",
            "actions": action_eligibility,
        }
    required = ["soc", "usable_capacity", "min_soc", "max_soc", "reserve_soc", "max_charge_power", "max_discharge_power", "grid_charge_permission", "efficiency"]
    policy = state.get("ess_policy")
    missing = [field for field in required if not isinstance(policy, dict) or policy.get(field) is None]
    return {"eligible": not missing, "missing_fields": missing, "reason": None if not missing else "missing_verified_ess_policy_constraints"}


def build_action_plan(state: dict[str, Any]) -> dict[str, Any]:
    """Build an immutable shadow recommendation from one decision-time state."""
    if not isinstance(state, dict) or state.get("schema") != "ella_site_state.v1":
        return {"available": False, "reason": "invalid_site_state", "plan_blocks": []}
    slots = [item for item in state.get("slots") or [] if isinstance(item, dict)]
    site_id, known_at = state.get("site_id"), state.get("known_at")
    decision_time = _parse(known_at)
    if not isinstance(site_id, str) or not slots or decision_time is None:
        return {"available": False, "reason": "incomplete_site_state", "plan_blocks": []}
    loads = [item for item in state.get("individual_loads") or [] if isinstance(item, dict) and item.get("enabled") and item.get("site_id", site_id) == site_id]
    schedules = {load.get("load_id"): _load_schedule(slots, load, decision_time) for load in loads}
    cost_values = {slot.get("start"): _cost(slot)[0] for slot in slots}
    comparable = [value for value in cost_values.values() if value is not None]
    low, high = _percentile(comparable, 1 / 3), _percentile(comparable, 2 / 3)
    per_slot = []
    for slot in slots:
        cost, basis, components = _cost(slot)
        if cost is None:
            category, title = "unknown", "Okänd kostnadsperiod"
        elif cost <= low:
            category, title = "low", "Billig prisperiod"
        elif cost >= high:
            category, title = "high", "Dyr prisperiod"
        else:
            category, title = "mid", "Normal prisperiod"
        start, end = _parse(slot.get("start")), _parse(slot.get("end"))
        elapsed = start is None or end is None or end <= decision_time
        run_loads = [load for load in loads if slot.get("start") in schedules.get(load.get("load_id"), {}).get("scheduled", set())]
        defer_loads = [load for load in loads if slot.get("start") in schedules.get(load.get("load_id"), {}).get("deferred", set())]
        if run_loads:
            action = {"code": "run_flexible_loads", "label": "Kör flexibla laster"}
            actions = [{"code": "schedule", "load_id": load.get("load_id"), "source_control_mode": load.get("control_mode"), "planner_execution_mode": "shadow"} for load in run_loads]
            reason = f"Kör {run_loads[0].get('name', run_loads[0].get('load_id'))} under billigare timmar."
        elif defer_loads and not elapsed:
            action = {"code": "defer_flexible_loads", "label": "Flytta flexibla laster"}
            actions = [{"code": "defer", "load_id": load.get("load_id"), "source_control_mode": load.get("control_mode"), "planner_execution_mode": "shadow"} for load in defer_loads]
            reason = f"Flytta {defer_loads[0].get('name', defer_loads[0].get('load_id'))} till billigare timmar."
        else:
            action = {"code": "normal_operation", "label": "Normal drift"}
            actions = []
            reason = "Observerat tidsfönster; ingen retroaktiv rekommendation." if elapsed else "Ingen kvalificerad flexibel resurs kräver åtgärd"
        per_slot.append({"start": slot.get("start"), "end": slot.get("end"), "price_context": {"category": category, "title": title, "basis": basis, "completeness": "complete" if cost is not None else "unknown", "value": cost, "component_refs": components}, "primary_action": action, "short_reason": reason, "actions": actions, "elapsed": elapsed, "provenance": _slot_provenance(slot)})
    blocks: list[dict[str, Any]] = []
    for item in per_slot:
        key = _stable({"category": item["price_context"]["category"], "action": item["primary_action"], "actions": item["actions"], "reason": item["short_reason"], "elapsed": item["elapsed"]})
        if blocks and blocks[-1]["_key"] == key and blocks[-1]["end"] == item["start"]:
            blocks[-1]["end"] = item["end"]
            blocks[-1]["provenance"]["references"] = sorted(set(blocks[-1]["provenance"]["references"]) | set(item["provenance"]["references"]))
            blocks[-1]["provenance"]["quality"] = sorted(set(blocks[-1]["provenance"]["quality"]) | set(item["provenance"]["quality"]))
            continue
        blocks.append({**item, "_key": key})
    public_blocks = []
    for block in blocks:
        identity = {"site_id": site_id, "state_id": state.get("state_id"), "start": block["start"], "end": block["end"], "key": block["_key"]}
        has_action = bool(block["actions"])
        execution_status = "recommend_only" if has_action and not block["elapsed"] else "NOT_APPLICABLE"
        public_blocks.append({"plan_block_id": _hash(identity, "ella-action-"), "start": block["start"], "end": block["end"], "price_context": block["price_context"], "title": block["price_context"]["title"], "primary_action": block["primary_action"], "short_reason": block["short_reason"], "actions": block["actions"], "sub_actions": block["actions"], "elapsed": block["elapsed"], "control_semantics": {"mode": "shadow", "execution_status": execution_status}, "execution_status": execution_status, "execution_eligible": False, "constraints": {"load_registry": "verified_only", "actuator_writes_enabled": False}, "provenance": block["provenance"]})
    plan_identity = {"schema": SCHEMA, "site_id": site_id, "state_id": state.get("state_id"), "blocks": public_blocks}
    return {"available": True, "schema": SCHEMA, "site_id": site_id, "date": (state.get("horizon") or {}).get("date"), "timezone": state.get("timezone"), "plan_id": _hash(plan_identity, "ella-plan-"), "revision": 1, "plan_version": PLAN_VERSION, "action_version": PLAN_VERSION, "generated_at": known_at, "known_at": known_at, "decision_at": known_at, "input_state_id": state.get("state_id"), "input_revision": state.get("state_id"), "horizon": state.get("horizon"), "execution_mode": "shadow", "plan_blocks": public_blocks, "capability_references": {"state_id": state.get("state_id")}, "execution_eligible": False, "actuator_writes_enabled": False, "eligibility": {"ess": _ess_eligibility(state)}, "load_eligibility": {load.get("load_id"): schedules[load.get("load_id")]["qualification"] for load in loads}}
