"""Stage 7 execution contract tests using only deterministic fake adapters."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning import ella_execution as execution


class FakeStore:
    def __init__(self):
        self.data = None

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data


class FakeAdapter:
    def __init__(self, *, matches=True, fail=False, delay=0):
        self.matches = matches
        self.fail = fail
        self.delay = delay
        self.calls = []

    async def async_execute(self, command):
        self.calls.append("execute")
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("adapter failure")
        return {"acknowledged": True}

    async def async_readback(self, command):
        self.calls.append("readback")
        return {"matches": self.matches}

    async def async_rollback(self, command):
        self.calls.append("rollback")
        return {"rolled_back": True}


def _manager(monkeypatch):
    monkeypatch.setattr(execution, "Store", lambda *args, **kwargs: FakeStore())
    return execution.EllaExecutionStore(SimpleNamespace())


def _plan(site="site-a", resource="load-a"):
    return {
        "site_id": site,
        "plan_id": "plan-1",
        "revision": 1,
        "plan_blocks": [{
            "plan_block_id": "block-1",
            "actions": [{"code": "schedule", "load_id": resource}],
        }],
    }


def _permission(site="site-a", resource="load-a"):
    return {
        "site_id": site, "resource_id": resource, "actuator_id": "switch.test",
        "enabled": True, "armed": True, "verified": True,
        "control_mode": "controllable", "execution_eligible": True,
        "confirm": True,
    }


def test_default_permissions_are_off_and_missing_adapter_is_zero_write(monkeypatch):
    manager = _manager(monkeypatch)
    result = asyncio.run(manager.async_dispatch({
        "site_id": "site-a", "resource_id": "load-a", "idempotency_key": "one",
        "plan_id": "plan-1", "revision": 1, "plan_block_id": "block-1",
    }, _plan()))
    assert result["failure_class"] == "permission_disabled"
    assert result["actuator_writes_enabled"] is False
    assert manager.permission("site-a", "load-a")["armed"] is False


def test_permission_requires_explicit_confirmation_and_wrong_site_is_rejected(monkeypatch):
    manager = _manager(monkeypatch)
    with pytest.raises(ValueError, match="explicit_arm_confirmation_required"):
        asyncio.run(manager.async_set_permission({**_permission(), "confirm": False}))
    result = asyncio.run(manager.async_dispatch({
        "site_id": "site-b", "resource_id": "load-a", "idempotency_key": "one",
        "plan_id": "plan-1", "revision": 1, "plan_block_id": "block-1",
    }, _plan(site="site-a")))
    assert result["failure_class"] == "wrong_site"
    assert result["actuator_writes_enabled"] is False


def test_success_requires_explicit_adapter_and_duplicate_is_idempotent(monkeypatch):
    manager = _manager(monkeypatch)
    asyncio.run(manager.async_set_permission(_permission()))
    adapter = FakeAdapter()
    manager.register_adapter("site-a", "load-a", adapter)
    request = {"site_id": "site-a", "resource_id": "load-a", "idempotency_key": "same", "plan_id": "plan-1", "revision": 1, "plan_block_id": "block-1"}
    first = asyncio.run(manager.async_dispatch(request, _plan()))
    second = asyncio.run(manager.async_dispatch(request, _plan()))
    assert first["status"] == "ACKNOWLEDGED"
    assert second == first
    assert adapter.calls == ["execute", "readback"]


def test_readback_mismatch_rolls_back_and_failures_open_breaker(monkeypatch):
    manager = _manager(monkeypatch)
    asyncio.run(manager.async_set_permission({**_permission(), "rate_limit_per_minute": 10}))
    adapter = FakeAdapter(matches=False)
    manager.register_adapter("site-a", "load-a", adapter)
    for index in range(3):
        result = asyncio.run(manager.async_dispatch({"site_id": "site-a", "resource_id": "load-a", "idempotency_key": str(index), "plan_id": "plan-1", "revision": 1, "plan_block_id": "block-1"}, _plan()))
        assert result["failure_class"] == "readback_mismatch"
    blocked = asyncio.run(manager.async_dispatch({"site_id": "site-a", "resource_id": "load-a", "idempotency_key": "four", "plan_id": "plan-1", "revision": 1, "plan_block_id": "block-1"}, _plan()))
    assert blocked["failure_class"] == "circuit_open"
    assert adapter.calls == ["execute", "readback", "rollback"] * 3


def test_manual_override_and_stale_plan_fail_closed(monkeypatch):
    manager = _manager(monkeypatch)
    asyncio.run(manager.async_set_permission(_permission()))
    manager.register_adapter("site-a", "load-a", FakeAdapter())
    asyncio.run(manager.async_set_manual_override("site-a", True, "operator"))
    result = asyncio.run(manager.async_dispatch({"site_id": "site-a", "resource_id": "load-a", "idempotency_key": "override", "plan_id": "plan-1", "revision": 1, "plan_block_id": "block-1"}, _plan()))
    assert result["failure_class"] == "manual_override_active"
    asyncio.run(manager.async_set_manual_override("site-a", False, "operator"))
    stale = asyncio.run(manager.async_dispatch({"site_id": "site-a", "resource_id": "load-a", "idempotency_key": "stale", "plan_id": "wrong", "revision": 1, "plan_block_id": "block-1"}, _plan()))
    assert stale["failure_class"] == "stale_plan"


def test_timeout_is_classified_without_generic_service_call(monkeypatch):
    manager = _manager(monkeypatch)
    asyncio.run(manager.async_set_permission({**_permission(), "rate_limit_per_minute": 10}))
    manager.register_adapter("site-a", "load-a", FakeAdapter(delay=0.02))
    monkeypatch.setattr(execution, "COMMAND_TIMEOUT_SECONDS", 0.001)
    result = asyncio.run(manager.async_dispatch({"site_id": "site-a", "resource_id": "load-a", "idempotency_key": "timeout", "plan_id": "plan-1", "revision": 1, "plan_block_id": "block-1"}, _plan()))
    assert result["failure_class"] == "timeout"
    assert result["actuator_writes_enabled"] is True


def test_rate_limit_is_persistent_and_site_scoped(monkeypatch):
    manager = _manager(monkeypatch)
    asyncio.run(manager.async_set_permission({**_permission(), "rate_limit_per_minute": 1}))
    manager.register_adapter("site-a", "load-a", FakeAdapter())
    first = asyncio.run(manager.async_dispatch({"site_id": "site-a", "resource_id": "load-a", "idempotency_key": "rate-1", "plan_id": "plan-1", "revision": 1, "plan_block_id": "block-1"}, _plan()))
    second = asyncio.run(manager.async_dispatch({"site_id": "site-a", "resource_id": "load-a", "idempotency_key": "rate-2", "plan_id": "plan-1", "revision": 1, "plan_block_id": "block-1"}, _plan()))
    assert first["status"] == "ACKNOWLEDGED"
    assert second["failure_class"] == "rate_limited"
    assert manager.permission("site-b", "load-a")["armed"] is False
