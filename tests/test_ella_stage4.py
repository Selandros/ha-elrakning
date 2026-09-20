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


@run_async
async def test_snapshot_retention_uses_decision_time_not_lexical_plan_id():
    store = EllaDebugSnapshotStore(object())
    retained_hash = None
    newest = None
    for index in range(16):
        state = _state()
        state["known_at"] = f"2026-09-{index + 1:02d}T00:00:00+00:00"
        plan = build_action_plan(state)
        plan["plan_id"] = "z-old" if index == 0 else f"a-plan-{index:02d}"
        await store.async_put_plan(state, plan)
        if index == 2:
            block = plan["plan_blocks"][0]
            retained_hash = store.get("site-a", plan["plan_id"], plan["revision"], block["plan_block_id"])["snapshot_hash"]
        if index == 15:
            newest = plan
    snapshots = store.state["sites"]["site-a"]["snapshots"]
    plan_ids = {item["plan_id"] for item in snapshots.values()}
    assert len(plan_ids) == 14
    assert "z-old" not in plan_ids
    assert newest["plan_id"] in plan_ids
    newest_block = newest["plan_blocks"][0]
    assert store.get("site-a", newest["plan_id"], 1, newest_block["plan_block_id"]) is not None
    retained = next(item for item in snapshots.values() if item["plan_id"] == "a-plan-02")
    assert retained["snapshot_hash"] == retained_hash


@run_async
async def test_snapshot_retention_keeps_new_timestamped_plan_ahead_of_legacy_data_and_reloads():
    store = EllaDebugSnapshotStore(object())
    legacy_plan = build_action_plan(_state())
    legacy_plan["plan_id"] = "legacy-plan"
    await store.async_put_plan(_state(), legacy_plan)
    for snapshot in store.state["sites"]["site-a"]["snapshots"].values():
        snapshot.pop("generated_at", None)
        snapshot.pop("decision_at", None)
        snapshot.pop("known_at", None)
    for index in range(14):
        state = _state()
        state["known_at"] = f"2026-10-{index + 1:02d}T00:00:00+00:00"
        plan = build_action_plan(state)
        plan["plan_id"] = f"timestamped-{index:02d}"
        await store.async_put_plan(state, plan)
    snapshots = store.state["sites"]["site-a"]["snapshots"]
    assert "legacy-plan" not in {item["plan_id"] for item in snapshots.values()}
    persisted = copy.deepcopy(store.state)
    reloaded = EllaDebugSnapshotStore(object())
    reloaded.state = persisted
    newest = next(item for item in snapshots.values() if item["plan_id"] == "timestamped-13")
    assert reloaded.get("site-a", "timestamped-13", newest["revision"], newest["plan_block_id"])["snapshot_hash"] == newest["snapshot_hash"]


@run_async
async def test_snapshot_retention_isolated_between_sites():
    store = EllaDebugSnapshotStore(object())
    for site_id in ("site-a", "site-b"):
        for index in range(15):
            state = _state(site_id)
            state["known_at"] = f"2026-11-{index + 1:02d}T00:00:00+00:00"
            plan = build_action_plan(state)
            plan["plan_id"] = f"{site_id}-{index:02d}"
            await store.async_put_plan(state, plan)
    for site_id in ("site-a", "site-b"):
        snapshots = store.state["sites"][site_id]["snapshots"]
        assert len({item["plan_id"] for item in snapshots.values()}) == 14
    assert store.get("site-a", "site-b-14", 1, "missing") is None


def test_snapshot_redacts_sensitive_keys_and_preserves_absence():
    state = _state()
    state["capabilities"]["api_token"] = "secret-value"
    plan = build_action_plan(state)
    snapshot = build_snapshot(state, plan, plan["plan_blocks"][0])
    encoded = str(snapshot)
    assert "secret-value" not in encoded
    assert snapshot["slots"][0]["solar"]["availability"] == "unavailable"
    assert snapshot["execution_eligible"] is False
