from datetime import datetime, timedelta, timezone
import asyncio
import copy

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.ella_stage6 import (
    EllaStage6CalibrationStore,
    build_ess_action_eligibility,
    build_ess_physical_state,
    build_planned_soc_trajectory,
    build_solar_calibration,
)


UTC = timezone.utc
SITE = "site-a"
GEN = "solar-generation"


def _actual(start, value, coverage=1.0, quality="good"):
    return {
        "site_id": SITE, "logical_role": "solar.production", "resource_id": GEN,
        "source_generation_id": GEN, "interval_start": start,
        "interval_end": start + timedelta(minutes=15), "value": value, "unit": "W",
        "coverage_ratio": coverage, "quality_status": quality,
    }


def _forecast(start, value, known_at):
    return {
        "site_id": SITE, "logical_role": "solar.slot_forecast", "classification": "forecast",
        "payload_schema": "solar.slot_forecast.v1", "source_generation_id": GEN,
        "frame_id": f"frame-{start.minute}", "revision": 1, "known_at": known_at,
        "points": [{"valid_at": start, "value": value, "unit": "W", "quality_status": "good"}],
    }


def test_solar_overlap_requires_support_and_is_deterministic():
    decision = datetime(2026, 9, 20, 12, tzinfo=UTC)
    starts = [datetime(2026, 9, 20, 10, index * 15, tzinfo=UTC) for index in range(3)]
    actual = [_actual(start, 600) for start in starts]
    frames = [_forecast(start, 1000, decision - timedelta(hours=3)) for start in starts]
    first = build_solar_calibration(SITE, actual, frames, decision)
    second = build_solar_calibration(SITE, actual, frames, decision)
    assert first == second
    resource = first["resources"][GEN]
    assert resource["factor"] == 0.85
    assert resource["support_count"] == 3
    assert resource["reason"] == "support_sufficient"


def test_solar_missing_hindsight_or_low_quality_does_not_learn():
    decision = datetime(2026, 9, 20, 12, tzinfo=UTC)
    start = datetime(2026, 9, 20, 10, tzinfo=UTC)
    actual = [_actual(start, 600, coverage=0.89, quality="partial")]
    frames = [_forecast(start, 1000, decision + timedelta(minutes=1))]
    result = build_solar_calibration(SITE, actual, frames, decision)
    assert result["available"] is False
    assert result["reason"] == "no_slot_resolved_forecast_overlap"


def test_ess_physical_facts_do_not_become_policy_or_execution():
    observed = datetime(2026, 9, 20, 10, tzinfo=UTC)
    rows = [
        {"site_id": SITE, "logical_role": "battery.soc", "resource_id": "ess-1", "source_generation_id": "ess-1", "value": 55, "unit": "%", "quality_status": "good", "observed_at": observed},
        {"site_id": SITE, "logical_role": "battery.capacity", "resource_id": "ess-1", "source_generation_id": "ess-1", "value": 13.5, "unit": "kWh", "quality_status": "good", "observed_at": observed},
    ]
    physical = build_ess_physical_state(SITE, rows, observed + timedelta(minutes=1))
    actions = build_ess_action_eligibility(physical, {})
    assert physical["available"] is True
    assert actions["charge_ess"]["eligible"] is False
    assert "efficiency" in actions["charge_ess"]["missing_fields"]
    assert all(item["execution_eligible"] is False for item in actions.values())


def test_planned_soc_trajectory_requires_policy_and_respects_bounds():
    physical = {"available": True}
    slots = [{"start": "2026-09-20T10:00:00+00:00", "end": "2026-09-20T10:15:00+00:00"}]
    policy = {"policy_version": "test", "soc_fraction": 0.5, "usable_capacity_kwh": 10, "min_soc_fraction": 0.2, "max_soc_fraction": 0.9, "reserve_soc_fraction": 0.3, "max_charge_power_kw": 4, "max_discharge_power_kw": 4, "charge_efficiency": 0.8, "discharge_efficiency": 0.9}
    result = build_planned_soc_trajectory(slots, physical, policy, {slots[0]["start"]: {"code": "charge_ess", "power_kw": 4}})
    assert result["available"] is True
    assert result["points"][0]["semantics"] == "PLANNED"
    assert result["points"][0]["soc_fraction"] <= 0.9
    missing = build_planned_soc_trajectory(slots, physical, {})
    assert missing["available"] is False
    assert "charge_efficiency" in missing["missing_fields"]


def test_ess_store_is_site_scoped_bounded_and_restart_safe():
    class MemoryStore:
        def __init__(self):
            self.value = None

        async def async_load(self):
            return copy.deepcopy(self.value)

        async def async_save(self, value):
            self.value = copy.deepcopy(value)

    async def run():
        store = EllaStage6CalibrationStore(object())
        memory = MemoryStore()
        store.store = memory
        calibration = build_solar_calibration(
            SITE,
            [_actual(datetime(2026, 9, 20, 10, index * 15, tzinfo=UTC), 600) for index in range(3)],
            [_forecast(datetime(2026, 9, 20, 10, index * 15, tzinfo=UTC), 1000, datetime(2026, 9, 20, 8, tzinfo=UTC)) for index in range(3)],
            datetime(2026, 9, 20, 12, tzinfo=UTC),
        )
        await store.async_record(SITE, calibration)
        await store.async_record(SITE, calibration)
        assert len(store.public_state(SITE)["resources"][GEN]["evidence"]) == 3
        assert store.public_state("site-b")["available"] is False
        restarted = EllaStage6CalibrationStore(object())
        restarted.store = memory
        await restarted.async_load()
        assert len(restarted.public_state(SITE)["resources"][GEN]["evidence"]) == 3

    asyncio.run(run())
