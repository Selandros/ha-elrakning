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
    GREENELY_FACILITY_METER_IDENTITY_UNAVAILABLE,
    normalize_greenely_facility_meter_identity,
)


ROOT = Path(__file__).resolve().parents[1]


def test_bounded_state_contract_is_locked_without_raw_identity():
    path = ROOT / "docs/architecture/contracts/c4c1b_greenely_meter_identity_state_amendment_v1.fixtures.json"
    fixture = json.loads(path.read_text())
    assert fixture["allowed_state"] == GREENELY_FACILITY_METER_IDENTITY_UNAVAILABLE
    assert fixture["rules"]["exactly_one_facility_representation"] is True
    assert fixture["rules"]["free_form_state"] is False
    assert fixture["rules"]["raw_identity"] is False
    assert fixture["rules"]["invoice_installation_fingerprint_still_required"] is True


def test_facility_meter_identity_requires_exactly_one_bounded_representation():
    assert normalize_greenely_facility_meter_identity({"facility_meter_id_fingerprint": "fp"}) == "fp"
    assert normalize_greenely_facility_meter_identity({
        "facility_meter_identity_state": GREENELY_FACILITY_METER_IDENTITY_UNAVAILABLE,
    }) == GREENELY_FACILITY_METER_IDENTITY_UNAVAILABLE
    assert normalize_greenely_facility_meter_identity({}) is None
    assert normalize_greenely_facility_meter_identity({
        "facility_meter_id_fingerprint": "fp",
        "facility_meter_identity_state": GREENELY_FACILITY_METER_IDENTITY_UNAVAILABLE,
    }) is None
    assert normalize_greenely_facility_meter_identity({"facility_meter_identity_state": "free_text"}) is None
