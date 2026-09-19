import json
from pathlib import Path

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)

install_homeassistant_stubs()
install_elrakning_package_stub()
install_optional_dependency_stubs()

from custom_components.elrakning.site_identity import (
    GREENELY_CONTRACT_METER_IDENTITY_UNAVAILABLE,
    GREENELY_FACILITY_METER_IDENTITY_UNAVAILABLE,
    normalize_greenely_contract_meter_identity,
)


ROOT = Path(__file__).resolve().parents[1]


def test_contract_meter_state_contract_is_locked_separately_from_facility_state():
    path = ROOT / "docs/architecture/contracts/c4c1c_greenely_contract_meter_identity_state_amendment_v1.fixtures.json"
    fixture = json.loads(path.read_text())
    assert fixture["allowed_unavailable_state"] == GREENELY_CONTRACT_METER_IDENTITY_UNAVAILABLE
    assert fixture["allowed_unavailable_state"] != GREENELY_FACILITY_METER_IDENTITY_UNAVAILABLE
    assert fixture["rules"]["facility_state_is_not_reused"] is True
    assert fixture["rules"]["free_form_state"] is False


def test_contract_meter_identity_accepts_only_fingerprint_or_exact_state():
    assert normalize_greenely_contract_meter_identity("a" * 64) == "a" * 64
    assert normalize_greenely_contract_meter_identity(
        GREENELY_CONTRACT_METER_IDENTITY_UNAVAILABLE
    ) == GREENELY_CONTRACT_METER_IDENTITY_UNAVAILABLE
    assert normalize_greenely_contract_meter_identity("foo") is None
    assert normalize_greenely_contract_meter_identity("A" * 64) is None
    assert normalize_greenely_contract_meter_identity(
        GREENELY_FACILITY_METER_IDENTITY_UNAVAILABLE
    ) is None
    assert normalize_greenely_contract_meter_identity("") is None
