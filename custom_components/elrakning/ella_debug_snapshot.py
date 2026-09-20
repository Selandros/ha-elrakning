"""Bounded, persistent decision-time snapshots for Stage 4 explainability."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any

from homeassistant.helpers.storage import Store

SCHEMA = "ella_debug_snapshot.v1"
STORE_SCHEMA = "ella_debug_snapshot_store.v1"
STORE_VERSION = 1
STORE_KEY = "elrakning.ella_debug_snapshots"
MAX_PLANS_PER_SITE = 14
SENSITIVE_KEY = re.compile(r"(?:password|passcode|authorization|cookie|secret|token|credential|api[_-]?key|client[_-]?secret|jwt|csrf)", re.I)


def _stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _redact(value: Any, key: str = "") -> Any:
    if SENSITIVE_KEY.search(key):
        return "[redacted]"
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {child_key: _redact(child_value, child_key) for child_key, child_value in value.items()}
    return value


def build_snapshot(state: dict[str, Any], plan: dict[str, Any], block: dict[str, Any]) -> dict[str, Any]:
    """Freeze only the decision inputs and plan facts available at plan creation."""
    block_id = block.get("plan_block_id")
    block_start, block_end = block.get("start"), block.get("end")
    slots = [
        slot for slot in state.get("slots") or []
        if isinstance(slot, dict) and slot.get("start") >= block_start and slot.get("end") <= block_end
    ]
    base = {
        "schema": SCHEMA,
        "schema_version": 1,
        "site_id": plan.get("site_id"),
        "date": plan.get("date"),
        "timezone": plan.get("timezone"),
        "plan_id": plan.get("plan_id"),
        "revision": plan.get("revision"),
        "plan_version": plan.get("plan_version"),
        "action_version": plan.get("action_version"),
        "plan_block_id": block_id,
        "generated_at": plan.get("generated_at"),
        "known_at": plan.get("known_at"),
        "decision_at": plan.get("decision_at"),
        "input_state_id": plan.get("input_state_id"),
        "input_revision": plan.get("input_revision"),
        "block": block,
        "slots": slots,
        "planner_inputs": {
            "individual_loads": state.get("individual_loads") or [],
            "load_eligibility": plan.get("load_eligibility") or {},
            "capability_references": plan.get("capability_references") or {},
            "ess_eligibility": (plan.get("eligibility") or {}).get("ess", {}),
        },
        # ``capabilities`` is the canonical Stage 2 state field.  Keep the
        # public Stage 4 name while freezing that decision-time object.
        "capability_snapshot": state.get("capabilities") or state.get("capability_snapshot") or {},
        "source_facts": state.get("source_facts") or [],
        "economic_facts": state.get("economic_facts") or [],
        "forecast_evaluation": state.get("forecast_evaluation") or {
            "available": False, "reason": "no_evaluation_history", "records": [],
        },
        "execution_mode": plan.get("execution_mode"),
        "execution_status": block.get("execution_status"),
        "execution_eligible": False,
        "actuator_writes_enabled": False,
        "decision_explanation": {
            "primary_action": block.get("primary_action"),
            "short_reason": block.get("short_reason"),
            "price_context": block.get("price_context"),
            "availability_semantics": "available values are preserved; unavailable, missing and stale layers are not zero-filled",
        },
    }
    snapshot = _redact(base)
    snapshot["snapshot_hash"] = sha256(_stable(snapshot).encode()).hexdigest()
    return snapshot


class EllaDebugSnapshotStore:
    """Own immutable snapshots with deterministic bounded retention per site."""

    def __init__(self, hass) -> None:
        self.store = Store(hass, STORE_VERSION, STORE_KEY)
        self.state: dict[str, Any] = {"schema": STORE_SCHEMA, "version": 1, "sites": {}}

    async def async_load(self) -> None:
        cached = await self.store.async_load()
        if isinstance(cached, dict) and cached.get("schema") == STORE_SCHEMA and isinstance(cached.get("sites"), dict):
            self.state = {"schema": STORE_SCHEMA, "version": 1, "sites": cached["sites"]}

    @staticmethod
    def _key(plan_id: str, revision: Any, block_id: str) -> str:
        return f"{plan_id}:{revision}:{block_id}"

    async def async_put_plan(self, state: dict[str, Any], plan: dict[str, Any]) -> None:
        site_id = plan.get("site_id")
        if not isinstance(site_id, str):
            return
        blocks = {block.get("plan_block_id"): block for block in plan.get("plan_blocks") or [] if isinstance(block, dict) and isinstance(block.get("plan_block_id"), str)}
        site = self.state.setdefault("sites", {}).setdefault(site_id, {"snapshots": {}})
        snapshots = site.setdefault("snapshots", {})
        for block_id, block in blocks.items():
            key = self._key(plan.get("plan_id"), plan.get("revision"), block_id)
            if key not in snapshots:
                snapshots[key] = build_snapshot(state, plan, block)
        plan_ids = sorted(
            {snapshot.get("plan_id") for snapshot in snapshots.values() if isinstance(snapshot, dict)},
            key=lambda plan_id: _stable(next(snapshot for snapshot in snapshots.values() if snapshot.get("plan_id") == plan_id)),
        )
        for old_plan_id in plan_ids[:-MAX_PLANS_PER_SITE]:
            for key in [key for key, snapshot in snapshots.items() if snapshot.get("plan_id") == old_plan_id]:
                snapshots.pop(key, None)
        await self.store.async_save(self.state)

    def get(self, site_id: str, plan_id: str, revision: Any, block_id: str) -> dict[str, Any] | None:
        site = self.state.get("sites", {}).get(site_id)
        if not isinstance(site, dict):
            return None
        snapshot = site.get("snapshots", {}).get(self._key(plan_id, revision, block_id))
        return snapshot if isinstance(snapshot, dict) and snapshot.get("site_id") == site_id else None
