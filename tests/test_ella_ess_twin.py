from datetime import datetime, timedelta, timezone

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.ella_ess_twin import build_ess_digital_twin, build_ess_trajectory, resolve_shared_ess_resource


UTC = timezone.utc
SITE = "site-a"


def _identity_target(role, generation, *, site=SITE, device="device-1", config="config-1", strength="strong"):
    return {
        "site_id": site,
        "logical_role": role,
        "generation_id": generation,
        "source_identity": {
            "identity_strength": strength,
            "device_id": device,
            "config_entry_id": config,
        },
    }


def test_shared_ess_resource_requires_exact_strong_same_device_identity():
    bindings = {
        role: _identity_target(role, f"{role}-gen")
        for role in ("battery.power", "battery.soc", "battery.capacity")
    }
    active = {role: {item["generation_id"]} for role, item in bindings.items()}
    result = resolve_shared_ess_resource(SITE, bindings, active)
    assert result["available"] is True
    assert result["method"] == "strong_registry_config_entry_and_device_identity"
    assert len(result["resource_id"]) == 36

    different = {role: dict(item) for role, item in bindings.items()}
    different["battery.soc"] = _identity_target("battery.soc", "battery.soc-gen", device="device-2")
    assert resolve_shared_ess_resource(SITE, different, active)["reason"] == "shared_identity_mismatch"


def test_shared_ess_resource_fails_closed_for_missing_identity_generation_or_site():
    bindings = {role: _identity_target(role, f"{role}-gen") for role in ("battery.power", "battery.soc", "battery.capacity")}
    active = {role: {item["generation_id"]} for role, item in bindings.items()}
    missing = {role: dict(item) for role, item in bindings.items()}
    missing["battery.power"] = {**missing["battery.power"], "source_identity": {"identity_strength": "strong"}}
    assert resolve_shared_ess_resource(SITE, missing, active)["reason"] == "shared_identity_missing"
    ambiguous = {role: dict(item) for role, item in bindings.items()}
    assert resolve_shared_ess_resource(SITE, ambiguous, {**active, "battery.power": {"battery.power-gen", "other"}})["reason"] == "active_generation_ambiguous"
    assert resolve_shared_ess_resource("site-b", bindings, active)["reason"] == "shared_identity_missing"


def _row(role, value, start, generation, *, site=SITE, resource=None, unit=None, sign=None):
    return {
        "site_id": site,
        "logical_role": role,
        "source_generation_id": generation,
        "resource_id": resource,
        "interval_start": start,
        "interval_end": start + timedelta(minutes=15),
        "observed_at": start + timedelta(minutes=14),
        "value": value,
        "unit": unit or {"battery.power": "W", "battery.soc": "%", "battery.capacity": "kWh"}[role],
        "sign_convention": sign or {"battery.power": "positive_discharge_negative_charge", "battery.soc": "unsigned_0_100", "battery.capacity": "positive_usable_or_nominal"}[role],
        "quality_status": "good",
        "coverage_ratio": 1.0,
    }


def test_twin_is_deterministic_site_scoped_and_fails_closed_without_resource_mapping():
    start = datetime(2026, 9, 26, 10, tzinfo=UTC)
    rows = [
        _row("battery.power", 500, start, "power-a"),
        _row("battery.soc", 60, start, "soc-a"),
        _row("battery.capacity", 25, start, "capacity-a"),
        _row("battery.power", 999, start, "power-other", site="site-b"),
    ]
    active = {"battery.power": {"power-a"}, "battery.soc": {"soc-a"}, "battery.capacity": {"capacity-a"}}
    first = build_ess_digital_twin(SITE, rows, start + timedelta(minutes=15), active_generations=active)
    second = build_ess_digital_twin(SITE, rows, start + timedelta(minutes=15), active_generations=active)
    assert first == second
    assert first["available"] is True
    assert first["aggregate"]["available"] is False
    assert first["aggregate"]["reason"] == "no_verified_resource_mapping"
    assert first["observed"]["battery_power"][0]["value"] == 500
    assert first["health"]["throughput"]["available"] is True
    assert first["execution_eligible"] is False
    assert first["actuator_writes_enabled"] is False


def test_twin_aggregate_and_health_require_explicit_same_resource_mapping():
    start = datetime(2026, 9, 26, 10, tzinfo=UTC)
    rows = [
        _row("battery.power", 500, start, "power-a"),
        _row("battery.soc", 60, start, "soc-a"),
        _row("battery.capacity", 25, start, "capacity-a"),
    ]
    active = {"battery.power": {"power-a"}, "battery.soc": {"soc-a"}, "battery.capacity": {"capacity-a"}}
    result = build_ess_digital_twin(
        SITE, rows, start + timedelta(minutes=15), active_generations=active,
        resource_bindings={"power-a": "ess-1", "soc-a": "ess-1", "capacity-a": "ess-1"},
    )
    assert result["aggregate"]["available"] is True
    assert result["aggregate"]["capacity_kwh"] == 25
    assert result["aggregate"]["power_w"] == 500
    assert result["health"]["efc"]["available"] is False
    assert result["health"]["soh"]["available"] is False


def test_trajectory_respects_power_efficiency_and_reserve_without_execution():
    start = datetime(2026, 9, 26, 10, tzinfo=UTC)
    slots = [{"start": start.isoformat(), "end": (start + timedelta(minutes=15)).isoformat()}]
    result = build_ess_trajectory(
        slots, soc_fraction=0.5, usable_capacity_kwh=10, min_soc_fraction=0.2,
        max_soc_fraction=0.9, reserve_soc_fraction=0.3, max_charge_power_kw=4,
        max_discharge_power_kw=4, charge_efficiency=0.8, discharge_efficiency=0.9,
        actions={start.isoformat(): {"code": "charge_ess", "power_kw": 8}},
    )
    assert result["available"] is True
    assert result["points"][0]["power_kw"] == 4
    assert result["points"][0]["soc_fraction"] == 0.58
    assert result["execution_eligible"] is False
    assert result["actuator_writes_enabled"] is False


def test_temperature_derating_and_soc_drift_are_explicitly_unavailable_without_evidence():
    decision = datetime(2026, 9, 26, 10, tzinfo=UTC)
    result = build_ess_digital_twin(SITE, [], decision)
    assert result["health"]["temperature"]["reason"] == "verified_temperature_source_missing"
    assert result["health"]["derating"]["reason"] == "verified_derating_source_missing"
    assert result["soc_drift"]["reason"] == "no_predicted_soc_trajectory"


def test_multiple_active_singleton_generations_fail_closed():
    start = datetime(2026, 9, 26, 10, tzinfo=UTC)
    rows = [_row("battery.power", 500, start, "power-a"), _row("battery.power", 700, start, "power-b")]
    result = build_ess_digital_twin(
        SITE, rows, start + timedelta(minutes=15),
        active_generations={"battery.power": {"power-a", "power-b"}},
    )
    assert result["available"] is False
    assert result["aggregate"]["reason"] == "no_verified_resource_mapping"
    assert result["health"]["throughput"]["available"] is False
