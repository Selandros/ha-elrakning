from datetime import date, datetime, timedelta, timezone

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)

install_homeassistant_stubs()
install_elrakning_package_stub()
install_optional_dependency_stubs()

from custom_components.elrakning.coordinator import PricePeriod
from custom_components.elrakning.ella_site_state import build_site_state, local_day_slots, resolve_timezone


UTC = timezone.utc


def _row(site, role, start, value, generation="gen"):
    return {
        "site_id": site,
        "logical_role": role,
        "source_generation_id": generation,
        "interval_start": start,
        "interval_end": start + timedelta(minutes=15),
        "resolution_seconds": 900,
        "value": value,
        "unit": "W",
        "quality_status": "good",
        "coverage_ratio": 1.0,
    }


def _frame(site, start, value, known_at):
    return {
        "frame_id": "forecast-frame",
        "source_generation_id": "forecast-generation",
        "site_id": site,
        "payload_schema": "load_forecast.v1",
        "quality_status": "good",
        "quality": {"status": "good"},
        "known_at": known_at,
        "valid_from": start,
        "valid_to": start + timedelta(minutes=30),
        "points": [{
            "point_id": "forecast-point",
            "valid_at": start,
            "value": value,
            "unit": "W",
            "quality_status": "good",
            "point": {},
        }],
    }


def test_local_day_handles_normal_and_dst_days():
    assert len(local_day_slots(date(2026, 1, 15), "Europe/Stockholm")) == 96
    assert len(local_day_slots(date(2026, 3, 29), "Europe/Stockholm")) == 92
    assert len(local_day_slots(date(2026, 10, 25), "Europe/Stockholm")) == 100


def test_state_load_precedence_and_no_zero_fill():
    site = "site-a"
    decision = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    slots = local_day_slots(date(2026, 9, 20), "Europe/Stockholm")
    first, second, third, fourth = [slot[0] for slot in slots[:4]]
    rows = [_row(site, "house.consumption", first, 100)]
    frame = _frame(site, second, 200, decision - timedelta(minutes=1))
    model = [{
        "valid_at": third, "value": 300, "unit": "W", "source": "model",
        "quality": {"model_version": "load-profile-v1", "sample_support": 7},
    }]
    state = build_site_state(
        site, "Europe/Stockholm", date(2026, 9, 20), decision,
        periods=[PricePeriod(start, end, 1.0) for start, end in slots],
        price_source_generation_id="price-generation", actual_rows=rows,
        load_frames=[frame], model_points=model,
    )
    loads = [item["load"] for item in state["slots"][:4]]
    assert [item["source"] for item in loads[:3]] == ["actual", "forecast", "model"]
    assert loads[3]["availability"] == "unavailable"
    assert loads[3].get("value") is None
    assert state["slots"][0]["price"]["availability"] == "available"
    assert state["execution_eligible"] is False
    assert state["actuator_writes_enabled"] is False


def test_future_forecast_known_after_decision_is_rejected_and_wrong_site_isolated():
    site = "site-a"
    decision = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    slots = local_day_slots(date(2026, 9, 20), "Europe/Stockholm")
    future = slots[20][0]
    wrong_site = _frame("site-b", future, 500, decision - timedelta(minutes=1))
    late = _frame(site, future, 500, decision + timedelta(minutes=1))
    state = build_site_state(site, "Europe/Stockholm", date(2026, 9, 20), decision, load_frames=[wrong_site, late])
    assert state["slots"][20]["load"]["availability"] == "unavailable"


def test_multiresource_solar_is_preserved_and_coarse_forecast_is_not_distributed():
    site = "site-a"
    decision = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    slots = local_day_slots(date(2026, 9, 20), "Europe/Stockholm")
    start = slots[0][0]
    rows = [
        _row(site, "solar.production", start, 100, "solar-1"),
        _row(site, "solar.production", start, 200, "solar-2"),
    ]
    coarse = {
        "frame_id": "coarse", "site_id": site, "payload_schema": "forecast_solar.observed_fact.v1",
        "logical_role": "forecast_solar.today", "known_at": decision,
        "valid_from": start, "valid_to": start + timedelta(days=1),
    }
    state = build_site_state(site, "Europe/Stockholm", date(2026, 9, 20), decision, actual_rows=rows, solar_forecast_frames=[coarse])
    resources = state["slots"][0]["solar"]["resources"]
    assert [item["source_generation_id"] for item in resources] == ["solar-1", "solar-2"]
    assert state["source_facts"][0]["frame_id"] == "coarse"
    assert state["slots"][0]["solar"].get("forecast") is None


def test_no_solar_or_ess_remains_truthful_and_state_id_is_deterministic():
    decision = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    args = ("site-a", "Europe/Stockholm", date(2026, 9, 20), decision)
    first = build_site_state(*args)
    second = build_site_state(*args)
    assert first["state_id"] == second["state_id"]
    assert first["slots"][0]["solar"]["availability"] == "unavailable"
    assert first["slots"][0]["ess"]["battery.capacity"]["availability"] == "unavailable"
    assert first["slots"][0]["load"]["availability"] == "unavailable"


def test_unresolved_economic_frame_is_fact_only_not_smeared_into_slots():
    decision = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    frame = {
        "frame_id": "eon-frame", "site_id": "site-a",
        "source_generation_id": "eon-generation",
        "logical_role": "economic.grid.import.transfer",
        "payload_schema": "eon.grid_economic_active_snapshot.v1",
        "known_at": decision, "valid_from": None, "valid_to": None,
        "provenance": {"effective_validity": {"utc_boundaries_resolved": False}},
    }
    state = build_site_state(
        "site-a", "Europe/Stockholm", date(2026, 9, 20), decision,
        economic_frames=[frame],
    )
    assert state["economic_facts"][0]["applicability"] == "unknown_unresolved_utc_boundaries"
    assert all(not any(item.get("logical_role") == frame["logical_role"] for item in slot["cost_stack"]["components"]) for slot in state["slots"])


def test_price_component_requires_matching_interval():
    decision = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    slots = local_day_slots(date(2026, 9, 20), "Europe/Stockholm")
    start, end = slots[0]
    state = build_site_state(
        "site-a", "Europe/Stockholm", date(2026, 9, 20), decision,
        periods=[PricePeriod(start, end, 2.0)],
        price_source_generation_id="price-generation",
    )
    assert state["slots"][0]["price"]["value"] == 2.0
    assert state["slots"][1]["price"]["availability"] == "unavailable"


def test_timezone_resolution_prefers_site_and_falls_back_to_configured_ha_timezone():
    assert resolve_timezone("Europe/Oslo", "Europe/Stockholm") == ("Europe/Oslo", "site_location")
    assert resolve_timezone(None, "Europe/Stockholm") == ("Europe/Stockholm", "home_assistant_config_default")


def test_complete_multi_pv_net_load_and_partial_resource_coverage():
    site = "site-a"
    decision = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    start, end = local_day_slots(date(2026, 9, 20), "Europe/Stockholm")[0]
    rows = [
        _row(site, "house.consumption", start, 1000, "load"),
        _row(site, "solar.production", start, 200, "solar-1"),
        _row(site, "solar.production", start, 300, "solar-2"),
    ]
    capability = {"capabilities": [{"capability_id": "solar.actual", "source": {"resources": [{"generation_id": "solar-1"}, {"generation_id": "solar-2"}]}}]}
    complete = build_site_state(site, "Europe/Stockholm", date(2026, 9, 20), decision, actual_rows=rows, capability_snapshot=capability)
    assert complete["slots"][0]["net_load"]["value_w"] == 500
    partial = build_site_state(site, "Europe/Stockholm", date(2026, 9, 20), decision, actual_rows=rows[:2], capability_snapshot=capability)
    assert partial["slots"][0]["solar"]["availability"] == "partial"
    assert partial["slots"][0]["net_load"]["availability"] == "unavailable"


def test_source_facts_are_limited_to_horizon_and_latest_current_fact():
    site = "site-a"
    decision = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    slots = local_day_slots(date(2026, 9, 20), "Europe/Stockholm")
    old = {"frame_id": "old", "site_id": site, "payload_schema": "forecast_solar.observed_fact.v1", "logical_role": "forecast_solar.today", "known_at": decision, "valid_from": slots[0][0] - timedelta(days=2), "valid_to": slots[0][0] - timedelta(days=1)}
    current_old = {"frame_id": "current-old", "site_id": site, "payload_schema": "forecast_solar.observed_fact.v1", "logical_role": "forecast_solar.power_now", "known_at": decision - timedelta(minutes=2), "valid_from": None, "valid_to": None}
    current_new = {**current_old, "frame_id": "current-new", "known_at": decision - timedelta(minutes=1)}
    state = build_site_state(site, "Europe/Stockholm", date(2026, 9, 20), decision, solar_forecast_frames=[old, current_old, current_new])
    assert [item["frame_id"] for item in state["source_facts"]] == ["current-new"]
