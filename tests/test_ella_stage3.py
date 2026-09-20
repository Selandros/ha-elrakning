from datetime import datetime, timezone

from tests._elrakning_test_bootstrap import install_elrakning_package_stub, install_homeassistant_stubs, install_optional_dependency_stubs

install_homeassistant_stubs()
install_elrakning_package_stub()
install_optional_dependency_stubs()

from custom_components.elrakning.ella_action_plan import build_action_plan


UTC = timezone.utc


def _state(loads=None, known_at="2026-09-19T23:00:00+00:00"):
    slots = []
    for index, cost in enumerate((1.0, 2.0, 3.0, None)):
        start = f"2026-09-20T{index:02d}:00:00+00:00"
        end = f"2026-09-20T{index:02d}:15:00+00:00"
        components = [{"availability": "available", "value": cost, "source": "nord_pool.price_periods.v1"}] if cost is not None else []
        slots.append({"start": start, "end": end, "cost_stack": {"components": components}, "load": {"availability": "unavailable"}})
    return {"schema": "ella_site_state.v1", "site_id": "site-a", "state_id": "state-a", "known_at": known_at, "timezone": "Europe/Stockholm", "horizon": {"date": "2026-09-20"}, "slots": slots, "individual_loads": loads or []}


def test_empty_registry_is_clean_shadow_plan_without_battery_action():
    plan = build_action_plan(_state())
    assert plan["available"] is True
    assert plan["execution_mode"] == "shadow"
    assert plan["execution_eligible"] is False
    assert plan["actuator_writes_enabled"] is False
    assert plan["date"] == "2026-09-20"
    assert plan["timezone"] == "Europe/Stockholm"
    assert plan["generated_at"] == plan["known_at"]
    assert plan["revision"] == 1
    assert plan["eligibility"]["ess"]["eligible"] is False
    assert all(block["primary_action"]["code"] == "normal_operation" for block in plan["plan_blocks"])
    assert {block["price_context"]["title"] for block in plan["plan_blocks"]} >= {"Billig prisperiod", "Normal prisperiod", "Dyr prisperiod"}


def test_plan_is_deterministic_and_elapsed_slots_do_not_claim_recommendation():
    first = build_action_plan(_state(known_at="2026-09-20T00:30:00+00:00"))
    second = build_action_plan(_state(known_at="2026-09-20T00:30:00+00:00"))
    assert first == second
    assert first["plan_blocks"][0]["elapsed"] is True
    assert first["plan_blocks"][0]["execution_status"] == "NOT_APPLICABLE"


def test_qualifying_shiftable_load_uses_cheapest_feasible_slots_and_priority_tiebreak():
    load = {"load_id": "washer", "enabled": True, "flexibility": "shiftable", "nominal_power_w": 1000, "energy_need_kwh": 0.25, "deadline": "2026-09-20T02:00:00+00:00", "priority": 1, "control_mode": "controllable"}
    plan = build_action_plan(_state([load]))
    scheduled = [sub["load_id"] for block in plan["plan_blocks"] for sub in block["sub_actions"]]
    assert scheduled == ["washer"]
    assert all(block["execution_eligible"] is False for block in plan["plan_blocks"])
    assert any(action["code"] == "schedule" for block in plan["plan_blocks"] for action in block["actions"])
    assert all(block["control_semantics"]["mode"] == "shadow" for block in plan["plan_blocks"])


def test_incomplete_load_underlay_never_creates_fake_schedule():
    load = {"load_id": "dryer", "enabled": True, "flexibility": "shiftable", "nominal_power_w": 1000, "energy_need_kwh": 5, "deadline": "2026-09-20T01:00:00+00:00", "priority": 1}
    plan = build_action_plan(_state([load]))
    assert all(not block["sub_actions"] for block in plan["plan_blocks"])


def test_observe_only_and_critical_fixed_loads_do_not_create_recommendations():
    loads = [
        {"load_id": "sensor_only", "enabled": True, "flexibility": "shiftable", "control_mode": "observe_only", "nominal_power_w": 1000, "energy_need_kwh": 0.25, "deadline": "2026-09-20T02:00:00+00:00"},
        {"load_id": "critical_fixed", "enabled": True, "flexibility": "fixed", "control_mode": "recommend_only", "nominal_power_w": 1000, "energy_need_kwh": 0.25, "deadline": "2026-09-20T02:00:00+00:00"},
    ]
    plan = build_action_plan(_state(loads))
    assert all(not block["actions"] for block in plan["plan_blocks"])


def test_min_runtime_and_allowed_window_are_fail_closed_and_contiguous():
    load = {"load_id": "heater", "enabled": True, "flexibility": "shiftable", "control_mode": "recommend_only", "nominal_power_w": 1000, "energy_need_kwh": 0.5, "deadline": "2026-09-20T04:00:00+00:00", "min_runtime_minutes": 30, "allowed_windows": [{"start": "01:00", "end": "04:00"}]}
    state = _state([load])
    for index, slot in enumerate(state["slots"]):
        hour, minute = 1, index * 15
        slot["start"] = f"2026-09-20T{hour + minute // 60:02d}:{minute % 60:02d}:00+00:00"
        next_minute = minute + 15
        slot["end"] = f"2026-09-20T{hour + next_minute // 60:02d}:{next_minute % 60:02d}:00+00:00"
    plan = build_action_plan(state)
    selected = [(block["start"], block["end"]) for block in plan["plan_blocks"] if block["actions"]]
    assert selected == [
        ("2026-09-20T01:00:00+00:00", "2026-09-20T01:15:00+00:00"),
        ("2026-09-20T01:15:00+00:00", "2026-09-20T01:30:00+00:00"),
    ]
