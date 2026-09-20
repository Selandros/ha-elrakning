"""Deterministic Stage 3 shadow/recommend-only action planning."""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import json
import math
from typing import Any

SCHEMA = "ella_action_plan.v1"
PLAN_VERSION = "action-shadow-v1"


def _stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


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
    components = [item for item in stack.get("components") or [] if isinstance(item, dict) and item.get("availability") == "available" and isinstance(item.get("value"), (int, float))]
    if not components:
        return None, "unknown", []
    total = sum(float(item["value"]) for item in components)
    if not math.isfinite(total):
        return None, "unknown", []
    basis = "spot" if len(components) == 1 and components[0].get("source") == "nord_pool.price_periods.v1" else "marginal_cost_stack"
    return total, basis, components


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _load_schedule(slots: list[dict[str, Any]], load: dict[str, Any]) -> set[str]:
    """Choose cheapest feasible slots for one explicitly schedulable load."""
    if not load.get("enabled") or load.get("flexibility") != "shiftable":
        return set()
    nominal = load.get("nominal_power_w")
    energy = load.get("energy_need_kwh")
    deadline = _parse(load.get("deadline") or load.get("ready_by"))
    if not isinstance(nominal, (int, float)) or nominal <= 0 or not isinstance(energy, (int, float)) or energy <= 0 or deadline is None:
        return set()
    required = max(1, math.ceil(float(energy) / ((float(nominal) / 1000.0) * 0.25)))
    candidates = []
    for slot in slots:
        start, end = _parse(slot.get("start")), _parse(slot.get("end"))
        cost, _, _ = _cost(slot)
        if start is None or end is None or end > deadline or cost is None:
            continue
        candidates.append((cost, int(load.get("priority") if isinstance(load.get("priority"), int) else 10**9), start, slot))
    candidates.sort(key=lambda item: (item[0], item[1], item[2], load.get("load_id", "")))
    if len(candidates) < required:
        return set()
    return {item[3].get("start") for item in candidates[:required]}


def build_action_plan(state: dict[str, Any]) -> dict[str, Any]:
    """Build immutable shadow recommendations from one decision-time state."""
    if not isinstance(state, dict) or state.get("schema") != "ella_site_state.v1":
        return {"available": False, "reason": "invalid_site_state", "plan_blocks": []}
    slots = list(state.get("slots") or [])
    site_id = state.get("site_id")
    known_at = state.get("known_at")
    if not isinstance(site_id, str) or not slots or not isinstance(known_at, str):
        return {"available": False, "reason": "incomplete_site_state", "plan_blocks": []}
    loads = [item for item in state.get("individual_loads") or [] if isinstance(item, dict) and item.get("enabled")]
    schedules = {load.get("load_id"): _load_schedule(slots, load) for load in loads}
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
        start = _parse(slot.get("start"))
        end = _parse(slot.get("end"))
        elapsed = end is not None and _parse(known_at) is not None and end <= _parse(known_at)
        scheduled = [load for load in loads if slot.get("start") in schedules.get(load.get("load_id"), set())]
        if scheduled and not elapsed:
            action = {"code": "run_flexible_loads", "label": "Kör flexibla laster"}
            sub_actions = [{"load_id": load.get("load_id"), "code": "schedule", "control_mode": "recommend_only"} for load in scheduled]
            reason = "Flexibel last planeras till en verifierad billig period."
        else:
            action = {"code": "normal_operation", "label": "Normal drift"}
            sub_actions = []
            reason = "Observerat tidsfönster; ingen retroaktiv rekommendation." if elapsed else "Ingen kvalificerad flexibel resurs kräver åtgärd"
        per_slot.append({"start": slot.get("start"), "end": slot.get("end"), "price_context": {"category": category, "title": title, "basis": basis, "completeness": "complete" if cost is not None else "unknown", "value": cost, "component_refs": components}, "primary_action": action, "short_reason": reason, "sub_actions": sub_actions, "elapsed": elapsed})
    blocks = []
    for item in per_slot:
        key = _stable({"category": item["price_context"]["category"], "action": item["primary_action"], "sub_actions": item["sub_actions"], "elapsed": item["elapsed"]})
        if blocks and blocks[-1]["_key"] == key and blocks[-1]["end"] == item["start"]:
            blocks[-1]["end"] = item["end"]
            continue
        blocks.append({**item, "_key": key})
    public_blocks = []
    for block in blocks:
        identity = {"site_id": site_id, "state_id": state.get("state_id"), "start": block["start"], "end": block["end"], "key": block["_key"]}
        block_id = "ella-action-" + sha256(_stable(identity).encode()).hexdigest()[:32]
        public_blocks.append({
            "plan_block_id": block_id, "start": block["start"], "end": block["end"],
            "price_context": block["price_context"], "title": block["price_context"]["title"],
            "primary_action": block["primary_action"], "short_reason": block["short_reason"],
            "sub_actions": block["sub_actions"], "elapsed": block["elapsed"],
            "execution_status": "NOT_APPLICABLE" if block["elapsed"] else "recommend_only",
            "execution_eligible": False,
            "constraints": {"load_registry": "verified_only", "actuator_writes_enabled": False},
        })
    plan_identity = {"schema": SCHEMA, "site_id": site_id, "state_id": state.get("state_id"), "blocks": public_blocks}
    return {
        "available": True, "schema": SCHEMA, "site_id": site_id,
        "plan_id": "ella-plan-" + sha256(_stable(plan_identity).encode()).hexdigest()[:32],
        "plan_version": PLAN_VERSION, "action_version": PLAN_VERSION,
        "known_at": known_at, "decision_at": known_at, "input_state_id": state.get("state_id"),
        "horizon": state.get("horizon"), "execution_mode": "shadow", "plan_blocks": public_blocks,
        "execution_eligible": False, "actuator_writes_enabled": False,
        "eligibility": {"ess": {"eligible": False, "reason": "missing_verified_ess_policy_constraints"}},
    }
