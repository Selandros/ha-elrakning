from datetime import datetime, timedelta, timezone

from tests._elrakning_test_bootstrap import install_elrakning_package_stub, install_homeassistant_stubs

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.replay_benchmark import (
    CheapestPriceBaseline,
    ESSReplayLimits,
    FixedBatteryBaseline,
    ThresholdBaseline,
    build_replay_run,
    select_causal_frames,
)


UTC = timezone.utc
SITE = "site-a"


def _frames(site=SITE, known_at=None, generation="load-gen"):
    known_at = known_at or datetime(2026, 9, 1, 12, tzinfo=UTC)
    return [{
        "frame_id": f"frame-{generation}", "semantic_key": f"{site}|load.forecast|{generation}",
        "site_id": site, "source_scope": "site", "source_generation_id": generation,
        "revision": 1, "schema_version": "canonical.v1", "dataset_version": "load.v1",
        "known_at": known_at.isoformat(), "quality_status": "good",
        "provenance": {"model_version": "load-v1", "calibration_version": "cal-v1"},
    }]


def _slots(start, count=4, frame_id="frame-load-gen", *, price=True):
    return [{
        "valid_at": (start + timedelta(minutes=15 * index)).isoformat(),
        "end_at": (start + timedelta(minutes=15 * (index + 1))).isoformat(),
        "load_kw": 1.0, "solar_kw": 0.5,
        "import_price_sek_per_kwh": 1.0 if price else None,
        "export_value_sek_per_kwh": 0.75 if price else None,
        "frame_ids": [frame_id],
    } for index in range(count)]


ESS = ESSReplayLimits(10.0, 0.2, 3.0, 3.0, 0.9, 0.9, 0.8)


def test_causal_selection_excludes_future_and_wrong_site():
    decision = datetime(2026, 9, 1, 13, tzinfo=UTC)
    result = select_causal_frames(
        _frames() + _frames("site-b") + _frames(known_at=datetime(2026, 9, 1, 14, tzinfo=UTC), generation="future"),
        site_id=SITE, decision_at=decision,
    )
    assert result["available"] is True
    assert [item["frame_id"] for item in result["frames"]] == ["frame-load-gen"]
    assert result["future_frame_count"] == 1
    assert result["wrong_site_frame_count"] == 1


def test_replay_is_deterministic_and_site_scoped():
    decision = datetime(2026, 9, 1, 12, tzinfo=UTC)
    slots = _slots(datetime(2026, 9, 1, 12, 15, tzinfo=UTC))
    first = build_replay_run(site_id=SITE, decision_at=decision, frames=_frames(), slots=slots, model_identity={"model": "fixture"}, ess=ESS)
    second = build_replay_run(site_id=SITE, decision_at=decision, frames=_frames(), slots=slots, model_identity={"model": "fixture"}, ess=ESS)
    assert first["qualification"]["qualified"] is True
    assert first["run_fingerprint"] == second["run_fingerprint"]
    assert first["baselines"]["no_battery"]["scorecard"]["import_kwh"] == 0.5
    assert first["baselines"]["self_consumption_only"]["scorecard"]["import_kwh"] == 0.0


def test_gaps_stale_and_missing_frame_provenance_fail_closed():
    decision = datetime(2026, 9, 1, 12, tzinfo=UTC)
    slots = _slots(datetime(2026, 9, 1, 12, 15, tzinfo=UTC))
    slots[2]["valid_at"] = (datetime(2026, 9, 1, 12, 45, tzinfo=UTC) + timedelta(minutes=15)).isoformat()
    slots[3]["frame_ids"] = ["missing-frame"]
    result = build_replay_run(site_id=SITE, decision_at=decision, frames=_frames(), slots=slots, model_identity={"model": "fixture"}, ess=ESS)
    assert result["qualification"]["qualified"] is False
    assert "slot_gap_or_misalignment" in result["qualification"]["reasons"]
    assert "slot_frame_provenance_missing" in result["qualification"]["reasons"]

    stale_frames = [{**_frames()[0], "quality_status": "stale"}]
    stale = build_replay_run(site_id=SITE, decision_at=decision, frames=stale_frames, slots=_slots(datetime(2026, 9, 1, 12, 15, tzinfo=UTC)), model_identity={"model": "fixture"}, ess=ESS)
    assert stale["qualification"]["qualified"] is False
    assert "frame_quality_unqualified" in stale["qualification"]["reasons"]


def test_ambiguous_revision_and_source_generation_replacement_are_explicit():
    decision = datetime(2026, 9, 1, 12, tzinfo=UTC)
    frames = _frames() + [{**_frames(generation="replacement")[0], "frame_id": "frame-replacement", "semantic_key": f"{SITE}|load.forecast|replacement"}]
    slots = _slots(datetime(2026, 9, 1, 12, 15, tzinfo=UTC), frame_id="frame-replacement")
    result = build_replay_run(site_id=SITE, decision_at=decision, frames=frames, slots=slots, model_identity={"model": "fixture"}, ess=ESS)
    assert result["qualification"]["qualified"] is True
    assert {item["source_generation_id"] for item in result["input_identity"]["frames"]} == {"load-gen", "replacement"}
    ambiguous = _frames() + [{**_frames()[0], "frame_id": "duplicate", "revision": 1}]
    selected = select_causal_frames(ambiguous, site_id=SITE, decision_at=decision)
    assert selected["available"] is False
    assert "ambiguous_frame_revision" in selected["reasons"]


def test_dst_slot_shape_and_missing_prices_remain_truthful():
    decision = datetime(2026, 10, 25, 0, 45, tzinfo=UTC)
    slots = _slots(datetime(2026, 10, 25, 1, 0, tzinfo=UTC), count=4, price=False)
    result = build_replay_run(site_id=SITE, decision_at=decision, frames=_frames(), slots=slots, model_identity={"model": "fixture"}, ess=ESS, timezone_name="Europe/Stockholm")
    assert result["qualification"]["qualified"] is True
    score = result["baselines"]["no_battery"]["scorecard"]
    assert score["cost_sek"] is None
    assert score["cost_status"] == "unavailable_missing_price"
    assert result["timezone"] == "Europe/Stockholm"


def test_publication_cutoff_and_relevant_filtered_frames_are_not_contamination():
    decision = datetime(2026, 9, 1, 12, tzinfo=UTC)
    slots = _slots(datetime(2026, 9, 1, 12, 15, tzinfo=UTC))
    result = build_replay_run(
        site_id=SITE,
        decision_at=decision,
        frames=_frames() + _frames("site-b") + _frames(known_at=datetime(2026, 9, 1, 13, tzinfo=UTC), generation="future"),
        slots=slots,
        model_identity={"model": "fixture"},
        ess=ESS,
    )
    assert result["qualification"]["qualified"] is True
    assert result["qualification"]["contaminated"] is False
    assert result["qualification"]["hindsight_used_for_decision"] is False


def test_canonical_sign_balance_and_constraint_scorecard():
    decision = datetime(2026, 9, 1, 12, tzinfo=UTC)
    slots = _slots(datetime(2026, 9, 1, 12, 15, tzinfo=UTC), count=1)
    result = build_replay_run(site_id=SITE, decision_at=decision, frames=_frames(), slots=slots, model_identity={"model": "fixture"}, ess=ESS)
    no_battery = result["baselines"]["no_battery"]
    self_consumption = result["baselines"]["self_consumption_only"]
    assert no_battery["points"][0]["grid_import_kw"] == 0.5
    assert self_consumption["points"][0]["battery_signed_kw"] == 0.5
    assert self_consumption["points"][0]["grid_import_kw"] == 0.0
    assert self_consumption["scorecard"]["constraint_violations"] == 0
    assert self_consumption["scorecard"]["safety_qualified"] is True


def test_explicit_fixed_cheapest_and_threshold_baselines_are_deterministic_and_bounded():
    decision = datetime(2026, 9, 1, 12, tzinfo=UTC)
    slots = _slots(decision + timedelta(minutes=15), count=4)
    prices = [0.40, 0.10, 0.90, 0.20]
    for slot, price in zip(slots, prices):
        slot["import_price_sek_per_kwh"] = price
        slot["export_value_sek_per_kwh"] = price * 0.75
    fixed = FixedBatteryBaseline({slots[0]["valid_at"]: "charge", slots[2]["valid_at"]: "discharge"}, charge_kw=2.0, discharge_kw=2.0)
    cheapest = CheapestPriceBaseline(charge_slot_count=1, discharge_slot_count=1, charge_kw=2.0, discharge_kw=2.0)
    threshold = ThresholdBaseline(charge_below_sek_per_kwh=0.15, discharge_above_sek_per_kwh=0.85, charge_kw=2.0, discharge_kw=2.0)
    result = build_replay_run(site_id=SITE, decision_at=decision, frames=_frames(), slots=slots,
                              model_identity={"model": "fixture"}, ess=ESS,
                              baselines=(fixed, cheapest, threshold))
    assert result["qualification"]["qualified"] is True
    assert set(result["baselines"]) == {"fixed", "cheapest", "threshold"}
    for item in result["baselines"].values():
        assert item["scorecard"]["constraint_violations"] == 0
        assert item["scorecard"]["safety_qualified"] is True
    repeat = build_replay_run(site_id=SITE, decision_at=decision, frames=_frames(), slots=slots,
                              model_identity={"model": "fixture"}, ess=ESS,
                              baselines=(fixed, cheapest, threshold))
    assert result["run_fingerprint"] == repeat["run_fingerprint"]
