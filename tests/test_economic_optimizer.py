"""Deterministic Step 8 optimizer contract tests."""

import ast
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
build_eon_economics = MODULE.build_eon_economics
derive_provider_reference = MODULE.derive_provider_reference


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
        "economics": {
            "known_at": datetime(2026, 9, 27, 10, tzinfo=timezone.utc).isoformat(),
            "valid_from": datetime(2026, 9, 27, 0, tzinfo=timezone.utc).isoformat(),
            "valid_to": datetime(2026, 10, 1, 0, tzinfo=timezone.utc).isoformat(),
            "source_schema": "test.economics.v1",
        },
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
    del inputs["economics"]
    assert build_economic_plan(inputs)["reason"] == "decision_economics_provenance_missing"
    inputs = _inputs()
    del inputs["ess"]["capacity_kwh"]
    assert build_economic_plan(inputs)["reason"] == "verified_ess_bounds_missing"
    inputs = _inputs()
    del inputs["ess"]["resource_identity"]
    assert build_economic_plan(inputs)["reason"] == "shared_ess_resource_identity_missing"


def test_diagnostic_mode_never_loads_highspy_and_fails_closed():
    assert MODULE.HIGHSPY_DIAGNOSTIC_MODE is True
    assert MODULE.Highs is None
    assert MODULE._HIGHS_IMPORT_ATTEMPTED is False
    result = build_economic_plan(_inputs())
    assert result["available"] is False
    assert result["reason"] == "highspy_disabled_for_diagnostics"
    assert MODULE._HIGHS_IMPORT_ATTEMPTED is False


def test_core_import_chain_has_no_eager_highspy_import():
    for relative_path in (
        "custom_components/elrakning/__init__.py",
        "custom_components/elrakning/replay_runtime.py",
        "custom_components/elrakning/websocket.py",
    ):
        tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
        assert not any(
            isinstance(node, ast.ImportFrom) and node.module == "highspy"
            for node in ast.walk(tree)
        )
        assert not any(
            isinstance(node, ast.Import) and any(alias.name == "highspy" for alias in node.names)
            for node in ast.walk(tree)
        )
    optimizer_source = (ROOT / "custom_components/elrakning/economic_optimizer.py").read_text(encoding="utf-8")
    assert "def _load_highspy" in optimizer_source
    assert "from highspy import Highs" in optimizer_source


def test_known_at_and_15_minute_causal_gate():
    inputs = _inputs()
    inputs["known_at"] = inputs["slots"][0]["valid_at"]
    assert build_economic_plan(inputs)["reason"] == "forecast_not_causal"
    inputs = _inputs()
    inputs["slots"][1]["valid_at"] = (datetime(2026, 9, 27, 13, tzinfo=timezone.utc)).isoformat()
    assert build_economic_plan(inputs)["reason"] == "slots_not_15_minute_aligned"


def test_future_tariff_window_fails_closed_before_valid_from():
    inputs = _inputs()
    inputs["economics"]["valid_from"] = datetime(2026, 10, 1, tzinfo=timezone.utc).isoformat()
    assert build_economic_plan(inputs)["reason"] == "decision_economics_not_valid"


@pytest.mark.skipif(MODULE.Highs is None, reason="highspy is not installed in the local test environment")
def test_future_provider_tariff_with_known_applicability_override_is_eligible():
    inputs = _inputs()
    inputs["economics"]["provider_valid_from"] = datetime(2026, 10, 1, tzinfo=timezone.utc).isoformat()
    inputs["economics"]["valid_from"] = datetime(2026, 10, 1, tzinfo=timezone.utc).isoformat()
    inputs["economics"]["provider_reference"] = "eon-agreement-fingerprint"
    inputs["economics"]["planning_applicability_override"] = {
        "source_type": "user_configured_planning_applicability_override",
        "known_at": inputs["known_at"],
        "effective_from": inputs["known_at"],
        "provider_valid_from": inputs["economics"]["provider_valid_from"],
        "provider_reference": inputs["economics"]["provider_reference"],
    }
    result = build_economic_plan(inputs)
    assert result["available"] is True
    assert result["economics_provenance"]["provider_valid_from"] == "2026-10-01T00:00:00+00:00"
    assert result["economics_provenance"]["planning_applicability_override"]["source_type"] == "user_configured_planning_applicability_override"


def test_eon_runtime_payload_derives_matching_reference_without_copying_prices():
    state = {
        "provider": "eon",
        "agreement": {"type": "ELECTRICITY_CONS_GRID", "start_date": "2026-10-01", "end_date": None},
        "facility": {"installation_identifier": "installation:verified"},
        "grid_price": {
            "vat_included": True,
            "price_basis": "gross",
            "fixed_monthly_sek": 226.25,
            "transfer_ore_per_kwh_gross": 97.0,
            "energy_tax_ore_per_kwh_gross": 45.0,
            "variable_total_ore_per_kwh_gross": 142.0,
        },
    }
    economics = build_eon_economics(state, {"facility": state["facility"]}, "2026-09-26T12:00:00+00:00")
    assert economics["provider_valid_from"] == "2026-10-01T00:00:00+00:00"
    assert economics["provider_reference"] == derive_provider_reference(state, {"facility": state["facility"]})
    assert "fixed_monthly_sek" not in economics


def test_future_provider_override_reference_mismatch_fails_closed():
    inputs = _inputs()
    inputs["economics"]["provider_valid_from"] = "2026-10-01T00:00:00+00:00"
    inputs["economics"]["valid_from"] = "2026-10-01T00:00:00+00:00"
    inputs["economics"]["provider_reference"] = "eon-agreement-real"
    inputs["economics"]["planning_applicability_override"] = {
        "source_type": "user_configured_planning_applicability_override",
        "known_at": inputs["known_at"],
        "effective_from": inputs["known_at"],
        "provider_valid_from": inputs["economics"]["provider_valid_from"],
        "provider_reference": "eon-agreement-wrong",
    }
    assert build_economic_plan(inputs)["reason"] == "decision_economics_not_valid"


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


@pytest.mark.skipif(MODULE.Highs is None, reason="highspy is not installed in the local test environment")
def test_planning_efficiency_and_replanning_defaults_are_separate_from_physical_facts():
    inputs = _inputs()
    inputs["ess"].pop("charge_efficiency")
    inputs["ess"].pop("discharge_efficiency")
    inputs["ess"]["planning_efficiency"] = {
        "charge_efficiency": 0.85,
        "discharge_efficiency": 0.85,
        "source_type": "conservative_calibration_planning_assumption",
        "uncertainty": "bounded_fixture",
    }
    inputs.pop("replanning")
    result = build_economic_plan(inputs)
    assert result["available"] is True
    assert result["constraint_provenance"]["execution_eligible"] is False
    assert result["constraint_provenance"]["efficiency"]["physical_safety_limit"] is False
    assert result["objective"]["replanning_provenance"]["source_type"] == "product_policy_default"
    assert result["objective"]["replanning_provenance"]["previous_action_source"] == "no_prior_action"


def test_site_isolation_is_part_of_result_fingerprint():
    first = build_economic_plan(_inputs("site-a"))
    second = build_economic_plan(_inputs("site-b"))
    assert first["reason"] if not first["available"] else first["site_id"] == "site-a"
    assert second["reason"] if not second["available"] else second["site_id"] == "site-b"
    if first.get("available") and second.get("available"):
        assert first["input_fingerprint"] != second["input_fingerprint"]
