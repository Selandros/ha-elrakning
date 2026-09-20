"""Deterministic Stage 3 shadow/recommend-only action planning."""

from __future__ import annotations

from datetime import datetime, time
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


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


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


def _clock(value: Any) -> time | None:
    if not isinstance(value, str):
        return None
    try:
        return time.fromisoformat(value)
    except ValueError:
        return None


def _window_contains(start: datetime, end: datetime, windows: Any) -> bool:
    """Accept only explicit ISO intervals or local HH:MM intervals; unknown shapes fail closed."""
    if windows is None:
        return True
    if not isinstance(windows, list) or not windows:
        return False
    for window in windows:
        if not isinstance(window, dict):
            continue
        window_start, window_end = _parse(window.get("start")), _parse(window.get("end"))
        if window_start is not None and window_end is not None:
            if start >= window_start and end <= window_end:
                return True
            continue
        clock_start, clock_end = _clock(window.get("start")), _clock(window.get("end"))
        if clock_start is None or clock_end is None:
            continue
        current_start, current_end = start.timetz().replace(tzinfo=None), end.timetz().replace(tzinfo=None)
        if clock_start <= clock_end and current_start >= clock_start and current_end <= clock_end:
            return True
        if clock_start > clock_end and (current_start >= clock_start or current_end <= clock_end):
            return True
    return False


def _load_schedule(slots: list[dict[str, Any]], load: dict[str, Any]) -> set[str]:
    """Choose a deterministic contiguous recommendation for one explicit load."""
    if not load.get("enabled") or load.get("flexibility") != "shiftable" or load.get("control_mode") == "observe_only":
        return set()
    nominal, energy = load.get("nominal_power_w"), load.get("energy_need_kwh")
    deadline = _parse(load.get("deadline") or load.get("ready_by"))
    if not isinstance(nominal, (int, float)) or isinstance(nominal, bool) or nominal <= 0 or not isinstance(energy, (int, float)) or isinstance(energy, bool) or energy <= 0 or deadline is None:
        return set()
    minimum_runtime = load.get("min_runtime_minutes") or 0
    if not isinstance(minimum_runtime, int) or minimum_runtime < 0:
        return set()
    required = max(1, math.ceil(float(energy) / ((float(nominal) / 1000.0) * 0.25)), math.ceil(minimum_runtime / 15))
    candidates: list[tuple[float, int, datetime, int, dict[str, Any]]] = []
    for index, slot in enumerate(slots):
        start, end = _parse(slot.get("start")), _parse(slot.get("end"))
        cost, _, _ = _cost(slot)
        if start is None or end is None or end > deadline or cost is None or not _window_contains(start, end, load.get("allowed_windows")):
            continue
        priority = load.get("priority") if isinstance(load.get("priority"), int) else 10**9
        candidates.append((cost, priority, start, index, slot))
    by_index = {item[3]: item for item in candidates}
    if len(candidates) < required:
        return set()
    runs: list[tuple[float, int, datetime, str, list[dict[str, Any]]]] = []
    for first in sorted(by_index):
        run = [by_index.get(index) for index in range(first, first + required)]
        if any(item is None for item in run):
            continue
        typed_run = [item for item in run if item is not None]
        if any(typed_run[index + 1][4].get("start") != typed_run[index][4].get("end") for index in range(len(typed_run) - 1)):
            continue
        runs.append((sum(item[0] for item in typed_run), typed_run[0][1], typed_run[0][2], load.get("load_id", ""), [item[4] for item in typed_run]))
    if not runs:
        return set()
    chosen = min(runs, key=lambda item: (item[0], item[1], item[2], item[3]))
    return {item.get("start") for item in chosen[4]}


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


def build_action_plan(state: dict[str, Any]) -> dict[str, Any]:
    """Build an immutable shadow recommendation from one decision-time state."""
    if not isinstance(state, dict) or state.get("schema") != "ella_site_state.v1":
        return {"available": False, "reason": "invalid_site_state", "plan_blocks": []}
    slots = [item for item in state.get("slots") or [] if isinstance(item, dict)]
    site_id, known_at = state.get("site_id"), state.get("known_at")
    if not isinstance(site_id, str) or not slots or not isinstance(known_at, str) or _parse(known_at) is None:
        return {"available": False, "reason": "incomplete_site_state", "plan_blocks": []}
    loads = [item for item in state.get("individual_loads") or [] if isinstance(item, dict) and item.get("enabled")]
    schedules = {load.get("load_id"): _load_schedule(slots, load) for load in loads}
    cost_values = {slot.get("start"): _cost(slot)[0] for slot in slots}
    comparable = [value for value in cost_values.values() if value is not None]
    low, high = _percentile(comparable, 1 / 3), _percentile(comparable, 2 / 3)
    per_slot = []
    decision_time = _parse(known_at)
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
        elapsed = start is not None and end is not None and end <= decision_time
        scheduled = [load for load in loads if slot.get("start") in schedules.get(load.get("load_id"), set())]
        if scheduled and not elapsed:
            action = {"code": "run_flexible_loads", "label": "Kör flexibla laster"}
            actions = [{"code": "schedule", "load_id": load.get("load_id"), "control_mode": "recommend_only"} for load in scheduled]
            reason = "Flexibel last planeras till en verifierad billig period."
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
        public_blocks.append({"plan_block_id": _hash(identity, "ella-action-"), "start": block["start"], "end": block["end"], "price_context": block["price_context"], "title": block["price_context"]["title"], "primary_action": block["primary_action"], "short_reason": block["short_reason"], "actions": block["actions"], "sub_actions": block["actions"], "elapsed": block["elapsed"], "control_semantics": {"mode": "shadow", "execution_status": "NOT_APPLICABLE" if block["elapsed"] else "recommend_only"}, "execution_status": "NOT_APPLICABLE" if block["elapsed"] else "recommend_only", "execution_eligible": False, "constraints": {"load_registry": "verified_only", "actuator_writes_enabled": False}, "provenance": block["provenance"]})
    plan_identity = {"schema": SCHEMA, "site_id": site_id, "state_id": state.get("state_id"), "blocks": public_blocks}
    plan_id = _hash(plan_identity, "ella-plan-")
    return {"available": True, "schema": SCHEMA, "site_id": site_id, "date": (state.get("horizon") or {}).get("date"), "timezone": state.get("timezone"), "plan_id": plan_id, "revision": 1, "plan_version": PLAN_VERSION, "action_version": PLAN_VERSION, "generated_at": known_at, "known_at": known_at, "decision_at": known_at, "input_state_id": state.get("state_id"), "input_revision": state.get("state_id"), "horizon": state.get("horizon"), "execution_mode": "shadow", "plan_blocks": public_blocks, "capability_references": {"state_id": state.get("state_id")}, "execution_eligible": False, "actuator_writes_enabled": False, "eligibility": {"ess": {"eligible": False, "reason": "missing_verified_ess_policy_constraints"}}}
