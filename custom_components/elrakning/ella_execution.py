"""Fail-closed, vendor-neutral Stage 7 execution ledger and guardrails."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Any, Protocol

from homeassistant.helpers.storage import Store

SCHEMA = "ella_execution.v1"
STORE_SCHEMA = "ella_execution_store.v1"
STORE_VERSION = 1
STORE_KEY = "elrakning.ella_execution"
MAX_COMMANDS_PER_RESOURCE = 256
DEFAULT_RATE_LIMIT = 4
FAILURE_THRESHOLD = 3
BREAKER_SECONDS = 300
COMMAND_TIMEOUT_SECONDS = 15

FAILURE_CLASSES = frozenset({
    "permission_denied", "wrong_site", "stale_plan", "outside_window",
    "adapter_unavailable", "rate_limited", "circuit_open", "timeout",
    "ack_missing", "readback_mismatch", "adapter_error", "rolled_back",
})


class ActuatorAdapter(Protocol):
    """A vendor-neutral adapter; production must register this explicitly."""

    async def async_execute(self, command: dict[str, Any]) -> dict[str, Any]: ...
    async def async_readback(self, command: dict[str, Any]) -> dict[str, Any]: ...
    async def async_rollback(self, command: dict[str, Any]) -> dict[str, Any]: ...


def _stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _now(value: Any = None) -> datetime:
    if isinstance(value, datetime) and value.tzinfo:
        return value
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo else None


def _idempotency_id(site_id: str, key: str) -> str:
    return "ella-command-" + hashlib.sha256(_stable({"site_id": site_id, "key": key}).encode()).hexdigest()[:32]


def _default_permission(site_id: str, resource_id: str) -> dict[str, Any]:
    return {
        "schema": "ella_execution_permission.v1", "site_id": site_id,
        "resource_id": resource_id, "actuator_id": None, "enabled": False,
        "armed": False, "verified": False, "control_mode": "observe_only",
        "execution_eligible": False, "valid_from": None, "valid_until": None,
        "rate_limit_per_minute": DEFAULT_RATE_LIMIT, "updated_at": None,
        "source": "default_off",
    }


def _permission_valid(permission: dict[str, Any], site_id: str, resource_id: str, now: datetime) -> tuple[bool, str]:
    if permission.get("site_id") != site_id or permission.get("resource_id") != resource_id:
        return False, "wrong_site_or_resource"
    if not (permission.get("enabled") is True and permission.get("armed") is True):
        return False, "permission_disabled"
    if permission.get("verified") is not True or permission.get("execution_eligible") is not True:
        return False, "actuator_not_verified"
    if permission.get("control_mode") != "controllable":
        return False, "control_mode_not_controllable"
    start, end = _parse(permission.get("valid_from")), _parse(permission.get("valid_until"))
    if start and now < start or end and now >= end:
        return False, "permission_outside_window"
    return True, "permission_valid"


def _target_matches(action: dict[str, Any], resource_id: str) -> bool:
    return any(action.get(key) == resource_id for key in ("resource_id", "load_id", "actuator_id"))


def _find_action(plan_block: dict[str, Any], resource_id: str) -> dict[str, Any] | None:
    for action in plan_block.get("actions") or []:
        if isinstance(action, dict) and _target_matches(action, resource_id):
            return action
    for action in plan_block.get("sub_actions") or []:
        if isinstance(action, dict) and _target_matches(action, resource_id):
            return action
    return None


class EllaExecutionStore:
    """Persist permissions and bounded command results, defaulting everything off."""

    def __init__(self, hass) -> None:
        self.store = Store(hass, STORE_VERSION, STORE_KEY)
        self.state: dict[str, Any] = {"schema": STORE_SCHEMA, "version": 1, "sites": {}}
        self.adapters: dict[tuple[str, str], ActuatorAdapter] = {}

    async def async_load(self) -> None:
        cached = await self.store.async_load()
        if isinstance(cached, dict) and cached.get("schema") == STORE_SCHEMA and isinstance(cached.get("sites"), dict):
            self.state = {"schema": STORE_SCHEMA, "version": 1, "sites": cached["sites"]}

    def _site(self, site_id: str) -> dict[str, Any]:
        return self.state.setdefault("sites", {}).setdefault(site_id, {"permissions": {}, "commands": {}, "breaker": {}, "manual_override": None})

    def permission(self, site_id: str, resource_id: str) -> dict[str, Any]:
        return deepcopy(self._site(site_id).setdefault("permissions", {}).get(resource_id) or _default_permission(site_id, resource_id))

    def public_state(self, site_id: str) -> dict[str, Any]:
        site = self._site(site_id)
        return {
            "schema": SCHEMA, "site_id": site_id,
            "permissions": deepcopy(site.get("permissions", {})),
            "command_ledger": deepcopy(site.get("commands", {})),
            "breaker": deepcopy(site.get("breaker", {})),
            "manual_override": deepcopy(site.get("manual_override")),
            "execution_eligible": False,
            "actuator_writes_enabled": False,
        }

    async def async_set_permission(self, permission: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
        site_id, resource_id = permission.get("site_id"), permission.get("resource_id")
        if not isinstance(site_id, str) or not isinstance(resource_id, str) or not resource_id:
            raise ValueError("invalid_site_or_resource")
        if permission.get("armed") is True and permission.get("confirm") is not True:
            raise ValueError("explicit_arm_confirmation_required")
        merged = _default_permission(site_id, resource_id)
        merged.update({key: value for key, value in permission.items() if key not in {"confirm"}})
        merged["execution_eligible"] = bool(
            merged.get("enabled") is True and merged.get("armed") is True
            and merged.get("verified") is True and merged.get("control_mode") == "controllable"
        )
        merged["updated_at"] = _iso(_now(now))
        merged["source"] = "explicit_admin"
        self._site(site_id).setdefault("permissions", {})[resource_id] = merged
        await self.store.async_save(self.state)
        return deepcopy(merged)

    def register_adapter(self, site_id: str, resource_id: str, adapter: ActuatorAdapter) -> None:
        """Register only an explicit adapter; production has no implicit adapters."""
        self.adapters[(site_id, resource_id)] = adapter

    async def async_set_manual_override(self, site_id: str, active: bool, reason: str, now: datetime | None = None) -> dict[str, Any]:
        value = {"active": bool(active), "reason": str(reason)[:200], "updated_at": _iso(_now(now))}
        self._site(site_id)["manual_override"] = value
        await self.store.async_save(self.state)
        return deepcopy(value)

    def _breaker_open(self, site_id: str, resource_id: str, now: datetime) -> bool:
        item = self._site(site_id).setdefault("breaker", {}).get(resource_id) or {}
        opened = _parse(item.get("opened_at"))
        return bool(opened and now < opened + timedelta(seconds=BREAKER_SECONDS))

    def _rate_limited(self, site_id: str, resource_id: str, permission: dict[str, Any], now: datetime) -> bool:
        cutoff = now - timedelta(minutes=1)
        count = 0
        for item in self._site(site_id).setdefault("commands", {}).values():
            stamp = _parse(item.get("created_at")) if isinstance(item, dict) else None
            if isinstance(item, dict) and item.get("resource_id") == resource_id and stamp and stamp >= cutoff and item.get("status") in {"ACKNOWLEDGED", "EXECUTING", "ROLLED_BACK"}:
                count += 1
        limit = permission.get("rate_limit_per_minute", DEFAULT_RATE_LIMIT)
        return count >= limit if isinstance(limit, int) and limit > 0 else True

    async def async_dispatch(self, request: dict[str, Any], plan: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
        now_value = _now(now)
        site_id, resource_id, idem = request.get("site_id"), request.get("resource_id"), request.get("idempotency_key")
        if not all(isinstance(value, str) and value for value in (site_id, resource_id, idem)):
            return {"success": False, "status": "REJECTED", "failure_class": "invalid_request", "execution_eligible": False}
        site = self._site(site_id)
        command_id = _idempotency_id(site_id, idem)
        existing = site.setdefault("commands", {}).get(command_id)
        if existing is not None:
            return deepcopy(existing)
        block = next((item for item in plan.get("plan_blocks", []) if isinstance(item, dict) and item.get("plan_block_id") == request.get("plan_block_id")), None)
        if plan.get("site_id") != site_id or plan.get("plan_id") != request.get("plan_id") or plan.get("revision") != request.get("revision"):
            reason = "wrong_site" if plan.get("site_id") != site_id else "stale_plan"
            return await self._record_rejection(site_id, command_id, resource_id, reason, request, now_value)
        if block is None:
            return await self._record_rejection(site_id, command_id, resource_id, "stale_plan", request, now_value)
        if block.get("elapsed") is True:
            return await self._record_rejection(site_id, command_id, resource_id, "outside_window", request, now_value)
        action = _find_action(block, resource_id)
        if action is None:
            return await self._record_rejection(site_id, command_id, resource_id, "action_target_mismatch", request, now_value)
        permission = self.permission(site_id, resource_id)
        valid, reason = _permission_valid(permission, site_id, resource_id, now_value)
        adapter = self.adapters.get((site_id, resource_id))
        if not valid:
            return await self._record_rejection(site_id, command_id, resource_id, reason, request, now_value)
        if (site.get("manual_override") or {}).get("active") is True:
            return await self._record_rejection(site_id, command_id, resource_id, "manual_override_active", request, now_value)
        if self._breaker_open(site_id, resource_id, now_value):
            return await self._record_rejection(site_id, command_id, resource_id, "circuit_open", request, now_value)
        if self._rate_limited(site_id, resource_id, permission, now_value):
            return await self._record_rejection(site_id, command_id, resource_id, "rate_limited", request, now_value)
        if adapter is None:
            return await self._record_rejection(site_id, command_id, resource_id, "adapter_unavailable", request, now_value)
        command = {"command_id": command_id, "site_id": site_id, "resource_id": resource_id, "plan_id": plan.get("plan_id"), "revision": plan.get("revision"), "plan_block_id": block.get("plan_block_id"), "action": action, "created_at": _iso(now_value)}
        result = {"success": False, "command_id": command_id, "site_id": site_id, "resource_id": resource_id, "status": "FAILED", "failure_class": None, "execution_eligible": True, "actuator_writes_enabled": True, "created_at": _iso(now_value)}
        try:
            ack = await asyncio.wait_for(adapter.async_execute(command), timeout=COMMAND_TIMEOUT_SECONDS)
            if not isinstance(ack, dict) or ack.get("acknowledged") is not True:
                raise _ExecutionFailure("ack_missing")
            readback = await asyncio.wait_for(adapter.async_readback(command), timeout=COMMAND_TIMEOUT_SECONDS)
            if not isinstance(readback, dict) or readback.get("matches") is not True:
                await asyncio.wait_for(adapter.async_rollback(command), timeout=COMMAND_TIMEOUT_SECONDS)
                raise _ExecutionFailure("readback_mismatch")
            result.update({"success": True, "status": "ACKNOWLEDGED", "ack": ack, "readback": readback})
            self._clear_breaker(site_id, resource_id)
        except asyncio.TimeoutError:
            result["failure_class"] = "timeout"
            try:
                await asyncio.wait_for(adapter.async_rollback(command), timeout=COMMAND_TIMEOUT_SECONDS)
                result["status"] = "ROLLED_BACK"
                result["rollback"] = {"attempted": True, "safe_fallback": "normal_operation"}
            except Exception:
                result["rollback"] = {"attempted": True, "safe_fallback": "normal_operation", "status": "unconfirmed"}
            self._record_failure(site_id, resource_id, now_value)
        except _ExecutionFailure as err:
            result["failure_class"] = err.failure_class
            result["status"] = "ROLLED_BACK" if err.failure_class == "readback_mismatch" else "FAILED"
            self._record_failure(site_id, resource_id, now_value)
        except Exception:
            result["failure_class"] = "adapter_error"
            self._record_failure(site_id, resource_id, now_value)
        site.setdefault("commands", {})[command_id] = result
        self._trim(site)
        await self.store.async_save(self.state)
        return deepcopy(result)

    async def _record_rejection(self, site_id: str, command_id: str, resource_id: str, reason: str, request: dict[str, Any], now: datetime) -> dict[str, Any]:
        item = {"success": False, "command_id": command_id, "site_id": site_id, "resource_id": resource_id, "status": "REJECTED", "failure_class": reason, "execution_eligible": False, "actuator_writes_enabled": False, "fallback": {"code": "normal_operation", "status": "safe_fallback"}, "created_at": _iso(now), "request": {key: request.get(key) for key in ("plan_id", "revision", "plan_block_id")}}
        self._site(site_id).setdefault("commands", {})[command_id] = item
        self._trim(self._site(site_id))
        await self.store.async_save(self.state)
        return deepcopy(item)

    def _record_failure(self, site_id: str, resource_id: str, now: datetime) -> None:
        item = self._site(site_id).setdefault("breaker", {}).setdefault(resource_id, {"failure_count": 0})
        item["failure_count"] = int(item.get("failure_count", 0)) + 1
        if item["failure_count"] >= FAILURE_THRESHOLD:
            item["opened_at"] = _iso(now)

    def _clear_breaker(self, site_id: str, resource_id: str) -> None:
        self._site(site_id).setdefault("breaker", {}).pop(resource_id, None)

    @staticmethod
    def _trim(site: dict[str, Any]) -> None:
        commands = site.setdefault("commands", {})
        if len(commands) <= MAX_COMMANDS_PER_RESOURCE:
            return
        ordered = sorted(commands.items(), key=lambda item: (item[1].get("created_at") or "", item[0]))
        for key, _value in ordered[:-MAX_COMMANDS_PER_RESOURCE]:
            commands.pop(key, None)


class _ExecutionFailure(Exception):
    def __init__(self, failure_class: str) -> None:
        super().__init__(failure_class)
        self.failure_class = failure_class
