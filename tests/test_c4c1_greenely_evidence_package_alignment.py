from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)

install_homeassistant_stubs()
install_elrakning_package_stub()
install_optional_dependency_stubs()

from custom_components.elrakning.site_identity import (
    GREENELY_EVIDENCE_PACKAGE_VERSION,
    GREENELY_PROOF_RELATION,
    validate_greenely_evidence_package,
)


def test_exact_v1_package_is_accepted_only_with_matching_semantic_identity():
    semantic_identity = "a" * 64
    package = {
        "package_version": GREENELY_EVIDENCE_PACKAGE_VERSION,
        "procedure": "operator_compared_provider_and_invoice_sections",
        "relation": GREENELY_PROOF_RELATION,
        "semantic_identity": semantic_identity,
        "recorded_at": "2026-09-19T12:00:00Z",
    }
    digest = validate_greenely_evidence_package(package, semantic_identity)
    assert isinstance(digest, str) and len(digest) == 64


def test_evidence_package_rejects_contract_version_extra_keys_raw_keys_and_free_text():
    semantic_identity = "a" * 64
    base = {
        "package_version": GREENELY_EVIDENCE_PACKAGE_VERSION,
        "procedure": "operator_compared_provider_and_invoice_sections",
        "relation": GREENELY_PROOF_RELATION,
        "semantic_identity": semantic_identity,
        "recorded_at": "2026-09-19T12:00:00Z",
    }
    assert validate_greenely_evidence_package({**base, "contract_version": 1}, semantic_identity) is None
    assert validate_greenely_evidence_package({**base, "meter_id": "x"}, semantic_identity) is None
    assert validate_greenely_evidence_package({**base, "procedure": "free_text"}, semantic_identity) is None
    assert validate_greenely_evidence_package({**base, "relation": "other_relation"}, semantic_identity) is None
    assert validate_greenely_evidence_package({**base, "semantic_identity": "b" * 64}, semantic_identity) is None
    assert validate_greenely_evidence_package({**base, "recorded_at": "2026-09-19"}, semantic_identity) is None
    assert validate_greenely_evidence_package({**base, "recorded_at": "not-a-time"}, semantic_identity) is None
