from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.ella_learning_governance import build_learning_governance


def _record(index, predicted=100.0, actual=90.0):
    return {
        "valid_at": f"2026-09-20T{index:02d}:00:00+00:00",
        "series": {"battery": {"predicted_w": predicted, "actual_w": actual, "signed_error_w": actual - predicted}},
    }


def test_governance_is_site_scoped_and_gates_promotion_without_live_evidence():
    state = build_learning_governance("site-a", [_record(index) for index in range(6)], {"version": "cal-v1"})
    assert state["schema"] == "ella_learning_governance.v1"
    assert state["candidate"]["candidate_id"]
    assert state["promotion"]["eligible"] is False
    assert "benchmark_live_qualified" in state["promotion"]["reasons"]
    assert state["rollback"]["available"] is False


def test_governance_is_deterministic_and_detects_drift():
    records = [_record(index, actual=90.0 if index < 3 else 140.0) for index in range(6)]
    first = build_learning_governance("site-a", records, {"version": "cal-v1"})
    second = build_learning_governance("site-a", records, {"version": "cal-v1"})
    assert first == second
    assert first["drift"]["status"] == "detected"


def test_low_support_is_neutral_and_no_observation_does_not_learn():
    state = build_learning_governance("site-a", [_record(1)], {"version": "cal-v1"})
    assert state["drift"]["status"] == "unavailable"
    assert state["promotion"]["eligible"] is False
    empty = build_learning_governance("site-a", [], {"version": "cal-v1"})
    assert empty["available"] is False
    assert "observation" in empty["promotion"]["reasons"]


def test_sign_mismatch_blocks_promotion_and_step9_step10_gates_are_explicit():
    records = [_record(index) for index in range(5)] + [_record(6, predicted=100.0, actual=-90.0)]
    state = build_learning_governance(
        "site-a", records, {"version": "cal-v1"},
        benchmark_evidence={"qualified": False},
        shadow_evidence={"qualified": False},
    )
    assert state["promotion"]["gates"]["sign_mismatch_absent"] is False
    assert state["promotion"]["gates"]["benchmark_live_qualified"] is False
    assert state["promotion"]["gates"]["shadow_live_qualified"] is False
