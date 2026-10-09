from datetime import datetime, timezone

import pytest

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub


install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.app_contract import (
    AppContractError,
    validate_app_result,
    validate_state_snapshot,
)


def _snapshot(**updates):
    value = {
        "contract_version": 1,
        "site_id": "site-a",
        "source_generation_id": "generation-a",
        "captured_at": "2026-10-09T10:00:02Z",
        "decision_context": {"decision_at": "2026-10-09T10:00:00Z"},
        "entity_source_identity": {"logical_role": "grid.power/import", "entity": "sensor.test"},
        "value": 1.25,
        "unit": "kW",
        "sign_convention": "positive_import",
        "observed_at": "2026-10-09T09:59:00Z",
        "known_at": "2026-10-09T09:59:30Z",
        "quality": {"status": "good"},
        "status": "available",
    }
    value.update(updates)
    return value


def _result(**updates):
    value = {
        "contract_version": 1,
        "site_id": "site-a",
        "source_generation_id": "generation-a",
        "provenance": {"source": "shadow-test"},
        "revision": 1,
        "fingerprint": "a" * 64,
        "validity_interval": {"from": "2026-10-09T09:00:00Z", "to": "2026-10-09T11:00:00Z"},
        "known_at": "2026-10-09T09:59:30Z",
        "fail_closed": False,
        "status": "available",
        "diagnostics": {},
    }
    value.update(updates)
    return value


def test_state_snapshot_accepts_numeric_and_preserves_null_unavailable():
    assert validate_state_snapshot(_snapshot())["value"] == 1.25
    unavailable = validate_state_snapshot(_snapshot(value=None, status="unavailable"))
    assert unavailable["value"] is None


@pytest.mark.parametrize("updates,reason", [
    ({"known_at": "2026-10-09T10:00:01Z"}, "known_at_after_decision_at"),
    ({"value": None}, "available_value_must_not_be_null"),
])
def test_state_snapshot_rejects_unsafe_payloads(updates, reason):
    payload = _snapshot(**updates)
    with pytest.raises(AppContractError, match=reason):
        validate_state_snapshot(payload)


def test_result_requires_exact_context_and_known_at_rule():
    decision_at = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)
    result = validate_app_result(
        _result(),
        expected_site_id="site-a",
        expected_source_generation_id="generation-a",
        decision_at=decision_at,
        now=datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc),
    )
    assert result["fingerprint"] == "a" * 64
    with pytest.raises(AppContractError, match="site_id_mismatch"):
        validate_app_result(
            _result(site_id="site-b"),
            expected_site_id="site-a",
            expected_source_generation_id="generation-a",
            decision_at=decision_at,
        )
    with pytest.raises(AppContractError, match="known_at_after_decision_at"):
        validate_app_result(
            _result(known_at="2026-10-09T10:00:01Z"),
            expected_site_id="site-a",
            expected_source_generation_id="generation-a",
            decision_at=decision_at,
        )
    with pytest.raises(AppContractError, match="provenance_source"):
        validate_app_result(
            _result(provenance={}),
            expected_site_id="site-a",
            expected_source_generation_id="generation-a",
            decision_at=decision_at,
        )


def test_contract_rejects_malformed_and_nonfinite_values():
    with pytest.raises(AppContractError, match="snapshot_must_be_object"):
        validate_state_snapshot([])
    with pytest.raises(AppContractError, match="value_must_be_finite"):
        validate_state_snapshot(_snapshot(value=float("nan")))


def test_stale_result_is_rejected():
    with pytest.raises(AppContractError, match="stale_result"):
        validate_app_result(
            _result(),
            expected_site_id="site-a",
            expected_source_generation_id="generation-a",
            decision_at=datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc),
            now=datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc),
        )
