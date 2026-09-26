"""Deterministic Step 8 optimizer contract tests."""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "economic_optimizer", ROOT / "custom_components/elrakning/economic_optimizer.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
build_economic_plan = MODULE.build_economic_plan


def _inputs(site_id="site-a", solar=0.0):
    start = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
    slots = []
    for index in range(96):
        slots.append({
            "valid_at": (start + timedelta(minutes=15 * index)).isoformat(),
            "load_kw": 1.0,
            "solar_kw": solar,
            "import_price_sek_per_kwh": 0.20 if index < 48 else 1.20,
            "export_value_sek_per_kwh": 0.10,
        })
    return {
        "site_id": site_id,
        "known_at": datetime(2026, 9, 27, 11, tzinfo=timezone.utc).isoformat(),
        "slots": slots,
        "ess": {
            "resource_identity": {
                "available": True,
                "site_id": site_id,
                "resource_id": "ess-shared-1",
                "method": "strong_registry_config_entry_and_device_identity",
            },
            "soc_fraction": 0.8,
            "capacity_kwh": 10.0,
            "reserve_soc_fraction": 0.2,
            "max_charge_kw": 3.0,
            "max_discharge_kw": 3.0,
            "charge_efficiency": 0.9,
            "discharge_efficiency": 0.9,
        },
        "replanning": {
            "max_charge_ramp_kw": 3.0,
            "max_discharge_ramp_kw": 3.0,
            "hysteresis_kw": 0.0,
            "previous_charge_kw": 0.0,
            "previous_discharge_kw": 0.0,
        },
    }


def test_missing_economics_or_ess_facts_fail_closed():
    inputs = _inputs()
    del inputs["slots"][0]["import_price_sek_per_kwh"]
    assert build_economic_plan(inputs)["reason"] == "decision_economics_or_forecast_missing"
    inputs = _inputs()
    del inputs["ess"]["capacity_kwh"]
    assert build_economic_plan(inputs)["reason"] == "verified_ess_bounds_missing"
    inputs = _inputs()
    del inputs["ess"]["resource_identity"]
    assert build_economic_plan(inputs)["reason"] == "shared_ess_resource_identity_missing"


def test_known_at_and_15_minute_causal_gate():
    inputs = _inputs()
    inputs["known_at"] = inputs["slots"][0]["valid_at"]
    assert build_economic_plan(inputs)["reason"] == "forecast_not_causal"
    inputs = _inputs()
    inputs["slots"][1]["valid_at"] = (datetime(2026, 9, 27, 13, tzinfo=timezone.utc)).isoformat()
    assert build_economic_plan(inputs)["reason"] == "slots_not_15_minute_aligned"


@pytest.mark.skipif(MODULE.Highs is None, reason="highspy is not installed in the local test environment")
def test_real_highs_mip_is_deterministic_and_has_no_simultaneous_flow():
    first = build_economic_plan(_inputs())
    second = build_economic_plan(_inputs())
    assert first["available"] is True
    assert first["solver"] == "HiGHS"
    assert first["input_fingerprint"] == second["input_fingerprint"]
    assert first["points"] == second["points"]
    for point in first["points"]:
        assert not (point["charge_kw"] > 1e-8 and point["discharge_kw"] > 1e-8)


@pytest.mark.skipif(MODULE.Highs is None, reason="highspy is not installed in the local test environment")
def test_negative_price_and_export_value_are_modeled_without_fixed_fee_objective():
    inputs = _inputs(solar=2.0)
    for slot in inputs["slots"]:
        slot["import_price_sek_per_kwh"] = -0.10
        slot["export_value_sek_per_kwh"] = 0.50
    result = build_economic_plan(inputs)
    assert result["available"] is True
    assert result["objective"]["fixed_fees_in_objective"] is False
    assert result["constraint_provenance"]["execution_eligible"] is False


@pytest.mark.skipif(MODULE.Highs is None, reason="highspy is not installed in the local test environment")
def test_missing_export_value_uses_explicit_spot_minus_25_percent_fallback():
    inputs = _inputs()
    for slot in inputs["slots"]:
        slot.pop("export_value_sek_per_kwh")
    result = build_economic_plan(inputs)
    assert result["available"] is True
    assert result["economics_provenance"]["derived_export_value_fallback"]["factor"] == 0.75
    assert {point["export_value_source"] for point in result["points"]} == {"derived_export_value_fallback"}


@pytest.mark.skipif(MODULE.Highs is None, reason="highspy is not installed in the local test environment")
def test_explicit_export_value_wins_over_fallback():
    result = build_economic_plan(_inputs())
    assert result["available"] is True
    assert {point["export_value_source"] for point in result["points"]} == {"explicit_export_compensation"}


def test_negative_spot_price_is_used_mathematically_by_export_fallback():
    inputs = _inputs()
    for slot in inputs["slots"]:
        slot.pop("export_value_sek_per_kwh")
        slot["import_price_sek_per_kwh"] = -0.20
    normalized, reason = MODULE._validate_inputs(inputs)
    assert reason is None
    assert normalized is not None
    assert normalized["slots"][0]["export_value_sek_per_kwh"] == pytest.approx(-0.15)
    assert normalized["slots"][0]["export_value_source"] == "derived_export_value_fallback"


def test_site_isolation_is_part_of_result_fingerprint():
    first = build_economic_plan(_inputs("site-a"))
    second = build_economic_plan(_inputs("site-b"))
    assert first["reason"] if not first["available"] else first["site_id"] == "site-a"
    assert second["reason"] if not second["available"] else second["site_id"] == "site-b"
    if first.get("available") and second.get("available"):
        assert first["input_fingerprint"] != second["input_fingerprint"]
