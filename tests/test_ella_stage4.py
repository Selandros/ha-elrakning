import copy
import asyncio

from tests._elrakning_test_bootstrap import install_elrakning_package_stub, install_homeassistant_stubs, install_optional_dependency_stubs

install_homeassistant_stubs()
install_elrakning_package_stub()
install_optional_dependency_stubs()

from custom_components.elrakning.ella_action_plan import build_action_plan
from custom_components.elrakning.ella_debug_snapshot import EllaDebugSnapshotStore, build_snapshot


def run_async(function):
    def wrapper():
        return asyncio.run(function())
    return wrapper


def _state(site_id="site-a"):
    return {
        "schema": "ella_site_state.v1",
        "site_id": site_id,
        "state_id": "state-a",
        "known_at": "2026-09-20T00:00:00+00:00",
        "timezone": "Europe/Stockholm",
        "horizon": {"date": "2026-09-20"},
        "capabilities": {"site_id": site_id, "solar": {"availability": "unavailable", "reason": "canonical_role_missing"}},
        "slots": [{
            "start": "2026-09-20T01:00:00+00:00",
            "end": "2026-09-20T01:15:00+00:00",
            "cost_stack": {"components": [{"availability": "available", "value": 1.0, "source": "nord_pool.price_periods.v1"}]},
            "load": {"availability": "unavailable", "reason": "no_verified_actual_forecast_or_model"},
            "solar": {"availability": "unavailable", "reason": "canonical_role_missing"},
            "ess": {"availability": "unavailable", "reason": "canonical_role_missing"},
        }],
        "individual_loads": [],
        "source_facts": [],
        "economic_facts": [],
    }


@run_async
async def test_snapshot_is_decision_time_immutable_and_idempotent():
    state = _state()
    plan = build_action_plan(state)
    store = EllaDebugSnapshotStore(object())
    await store.async_put_plan(state, plan)
    block = plan["plan_blocks"][0]
    first = copy.deepcopy(store.get("site-a", plan["plan_id"], plan["revision"], block["plan_block_id"]))
    state["slots"][0]["load"] = {"availability": "available", "value_w": 9999}
    await store.async_put_plan(state, plan)
    second = store.get("site-a", plan["plan_id"], plan["revision"], block["plan_block_id"])
    assert second == first
    assert second["slots"][0]["load"]["availability"] == "unavailable"


@run_async
async def test_capability_inventory_is_frozen_in_public_snapshot_field():
    state = _state()
    state["capabilities"] = {"site_id": "site-a", "price": {"availability": "available"}}
    plan = build_action_plan(state)
    store = EllaDebugSnapshotStore(object())
    await store.async_put_plan(state, plan)
    block = plan["plan_blocks"][0]
    snapshot = store.get("site-a", plan["plan_id"], plan["revision"], block["plan_block_id"])
    assert snapshot["capability_snapshot"] == state["capabilities"]
    state["capabilities"]["price"]["availability"] = "unavailable"
    assert snapshot["capability_snapshot"]["price"]["availability"] == "available"


@run_async
async def test_snapshot_survives_reload_and_is_site_scoped():
    state = _state()
    plan = build_action_plan(state)
    store = EllaDebugSnapshotStore(object())
    await store.async_put_plan(state, plan)
    persisted = copy.deepcopy(store.state)
    reloaded = EllaDebugSnapshotStore(object())
    reloaded.state = persisted
    block_id = plan["plan_blocks"][0]["plan_block_id"]
    assert reloaded.get("site-a", plan["plan_id"], plan["revision"], block_id)["site_id"] == "site-a"
    assert reloaded.get("site-b", plan["plan_id"], plan["revision"], block_id) is None
    assert reloaded.get("site-a", "wrong-plan", plan["revision"], block_id) is None
    assert reloaded.get("site-a", plan["plan_id"], 99, block_id) is None
    assert reloaded.get("site-a", plan["plan_id"], plan["revision"], "wrong-block") is None


@run_async
async def test_snapshot_retention_is_bounded_and_deterministic():
    store = EllaDebugSnapshotStore(object())
    for index in range(16):
        state = _state()
        state["state_id"] = f"state-{index}"
        state["known_at"] = f"2026-09-{index + 1:02d}T00:00:00+00:00"
        plan = build_action_plan(state)
        await store.async_put_plan(state, plan)
    snapshots = store.state["sites"]["site-a"]["snapshots"]
    assert len({item["plan_id"] for item in snapshots.values()}) == 14
    assert len(snapshots) == 14


def test_snapshot_redacts_sensitive_keys_and_preserves_absence():
    state = _state()
    state["capabilities"]["api_token"] = "secret-value"
    plan = build_action_plan(state)
    snapshot = build_snapshot(state, plan, plan["plan_blocks"][0])
    encoded = str(snapshot)
    assert "secret-value" not in encoded
    assert snapshot["slots"][0]["solar"]["availability"] == "unavailable"
    assert snapshot["execution_eligible"] is False
