import hashlib
import hmac
import json
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/architecture/C4C1A_GREENELY_PROOF_PROVISIONING_AMENDMENT_V1.md"
FIXTURES = ROOT / "docs/architecture/contracts/c4c1a_greenely_proof_provisioning_amendment_v1.fixtures.json"

ALLOWED_METHODS = {
    "provider_native_semantic_proof",
    "explicit_out_of_band_invoice_verification",
}
SEMANTIC_FIELDS = (
    "relation", "provider_config_entry_identity_domain", "site_binding_identity",
    "facility_identity", "contract_identity_scope", "facility_meter_identity_state",
    "contract_meter_identity_state", "invoice_installation_identity",
    "verification_method", "proof_schema_version", "fingerprint_version",
    "parser_identity", "normalization_identity",
)
AUDIT_FIELDS = ("verification_actor", "verified_at", "evidence_reference", "evidence_digest")
ACTOR_SOURCE = "authenticated_home_assistant_service_context"
LOOKUP_OK = "LOOKUP_OK"
LOOKUP_FAILED = "LOOKUP_FAILED"
REFERENCE_NAMESPACE = "c4c1a-audit-ref-v1:"
EVIDENCE_PACKAGE_VERSION = "c4c1a-evidence-package-v1"


def identity(fields):
    return hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def semantic_identity(proof):
    return identity({field: proof[field] for field in SEMANTIC_FIELDS})


def audit_identity(proof):
    return identity({field: proof[field] for field in AUDIT_FIELDS})


def source_generation_projection(context):
    fields = {
        key: context[key]
        for key in (
            "provider_config_entry_identity_domain",
            "site_binding_identity",
            "facility_identity",
            "contract_identity_scope",
            "dataset_identity",
            "parser_identity",
            "normalization_identity",
            "proof_semantic_identity",
        )
    }
    return identity(fields)


def opaque_reference_valid(reference, raw_values):
    return (
        isinstance(reference, str)
        and reference.startswith(REFERENCE_NAMESPACE)
        and len(reference) <= 256
        and len(reference) > len(REFERENCE_NAMESPACE)
        and not any(value and value in reference for value in raw_values)
    )


def evidence_package_digest(package):
    required = {"package_version", "procedure", "relation", "semantic_identity", "recorded_at"}
    if set(package) != required or package["package_version"] != EVIDENCE_PACKAGE_VERSION:
        return None
    if not all(isinstance(package[key], str) and package[key] for key in required):
        return None
    if package["procedure"] in {"raw_installation_only", "raw_meter_only"}:
        return None
    encoded = json.dumps(package, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def verify_evidence_digest(package, supplied_digest):
    calculated = evidence_package_digest(package)
    if calculated is None:
        return False
    if not isinstance(supplied_digest, str) or len(supplied_digest) != 64:
        return False
    if any(character not in "0123456789abcdef" for character in supplied_digest):
        return False
    return hmac.compare_digest(calculated, supplied_digest)


def provider_relation_lookup(context, lookup_state, contracts):
    if lookup_state != LOOKUP_OK or context.get("provider") != "greenely":
        return False
    matches = [contract for contract in contracts if contract.get("id") == context.get("contract_id")]
    return len(matches) == 1 and matches[0].get("facility_id") == context.get("facility_id")


def provider_relation_valid(context, contracts):
    return provider_relation_lookup(context, LOOKUP_OK, contracts)


def proof_eligible(proof, context, contracts):
    if not provider_relation_lookup(context, context.get("lookup_state", LOOKUP_OK), contracts):
        return False
    if proof.get("verification_method") not in ALLOWED_METHODS:
        return False
    if proof.get("verification_state") != "EXPLICITLY_VERIFIED":
        return False
    if proof.get("verification_actor_source") != ACTOR_SOURCE:
        return False
    actor = proof.get("verification_actor")
    if not isinstance(actor, str) or not actor.strip():
        return False
    if not opaque_reference_valid(proof.get("evidence_reference"), context.get("raw_values", ())):
        return False
    if not all(proof.get(field) for field in ("verified_at", "evidence_digest")):
        return False
    if not isinstance(proof["evidence_digest"], str) or len(proof["evidence_digest"]) != 64:
        return False
    return proof.get("site_binding_fingerprint") == context.get("site_binding_fingerprint")


def provisioning_state_eligible(
    proof,
    context,
    contracts,
    current_binding_before_persist,
    current_lookup_state=None,
    current_contracts=None,
):
    if not context.get("authenticated") or not context.get("is_admin"):
        return False
    if context.get("expected_binding") != context.get("initial_binding"):
        return False
    if current_binding_before_persist != context.get("initial_binding"):
        return False
    if current_lookup_state is None:
        current_lookup_state = context.get("lookup_state", LOOKUP_OK)
    if current_contracts is None:
        current_contracts = contracts
    if not provider_relation_lookup(context, current_lookup_state, current_contracts):
        return False
    return proof_eligible(proof, context, contracts)


def proof_semantic_context(proof):
    return {field: proof[field] for field in SEMANTIC_FIELDS}


def proof_is_current(proof, current_context):
    return proof_semantic_context(proof) == {
        field: current_context[field] for field in SEMANTIC_FIELDS
    }


class C4C1AProofProvisioningAmendmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = DOC.read_text(encoding="utf-8")
        cls.fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))

    def setUp(self):
        self.context = {
            "provider": "greenely",
            "facility_id": "facility-a",
            "contract_id": "contract-a",
            "site_binding_fingerprint": "binding-a",
            "active_site_id": "unrelated-site",
            "lookup_state": LOOKUP_OK,
            "raw_values": ("facility-a", "contract-a", "meter-a", "install-a", "ocr-a"),
        }
        self.contracts = [{"id": "contract-a", "facility_id": "facility-a"}]
        self.proof = {
            "verification_state": "EXPLICITLY_VERIFIED",
            "verification_method": "explicit_out_of_band_invoice_verification",
            "site_binding_fingerprint": "binding-a",
            "verification_actor": "ha-admin-user",
            "verification_actor_source": ACTOR_SOURCE,
            "verified_at": "2026-09-13T10:00:00Z",
            "evidence_reference": f"{REFERENCE_NAMESPACE}opaque-1",
            "evidence_digest": "a" * 64,
        }

    def test_precedence_and_scope_are_locked(self):
        self.assertEqual(self.fixtures["status"], "READY_FOR_REVIEW")
        self.assertFalse(self.fixtures["precedence"]["c1_schema_migration_required"])
        self.assertIn("C.4B, C.4C, and C.4C.1 remain locked", self.doc)
        self.assertIn("proof-provisioning and audit-evidence", self.doc)
        self.assertIn("No C.1 schema migration is required", self.doc)

    def test_provider_relation_requires_exact_unambiguous_contract(self):
        self.assertTrue(provider_relation_valid(self.context, self.contracts))
        self.assertFalse(provider_relation_lookup(self.context, LOOKUP_FAILED, self.contracts))
        self.assertFalse(provider_relation_valid(self.context, []))
        self.assertFalse(provider_relation_valid(self.context, [{"id": "contract-a", "facility_id": "facility-b"}]))
        self.assertFalse(provider_relation_valid(self.context, self.contracts * 2))
        self.assertFalse(provider_relation_valid({**self.context, "provider": "other"}, self.contracts))

    def test_admin_alone_and_incomplete_audit_evidence_reject(self):
        self.assertFalse(proof_eligible({"verification_state": "EXPLICITLY_VERIFIED"}, self.context, self.contracts))
        for field in AUDIT_FIELDS:
            incomplete = deepcopy(self.proof)
            incomplete.pop(field)
            self.assertFalse(proof_eligible(incomplete, self.context, self.contracts))
        self.assertFalse(proof_eligible({**self.proof, "evidence_digest": "short"}, self.context, self.contracts))

    def test_allowed_methods_and_stale_binding(self):
        self.assertTrue(proof_eligible(self.proof, self.context, self.contracts))
        self.assertFalse(proof_eligible({**self.proof, "verification_method": "user_confirmation"}, self.context, self.contracts))
        self.assertFalse(proof_eligible(self.proof, {**self.context, "site_binding_fingerprint": "binding-b"}, self.contracts))

    def test_actor_provenance_and_opaque_reference_are_required(self):
        self.assertTrue(proof_eligible(self.proof, self.context, self.contracts))
        for source in (None, "caller_supplied", "payload_supplied", "unknown"):
            candidate = {**self.proof, "verification_actor_source": source}
            self.assertFalse(proof_eligible(candidate, self.context, self.contracts))
        for actor in (None, "", "   "):
            candidate = {**self.proof, "verification_actor": actor}
            self.assertFalse(proof_eligible(candidate, self.context, self.contracts))
        missing_actor = deepcopy(self.proof)
        missing_actor.pop("verification_actor")
        self.assertFalse(proof_eligible(missing_actor, self.context, self.contracts))
        for reference in ("", "facility-a", "install-a", f"{REFERENCE_NAMESPACE}facility-a"):
            candidate = {**self.proof, "evidence_reference": reference}
            self.assertFalse(proof_eligible(candidate, self.context, self.contracts))

    def test_audit_dimensions_are_independent_from_semantic_identity(self):
        proof = self._semantic_proof()
        semantic = semantic_identity(proof)
        audit = audit_identity(proof)
        for field, value in {
            "verification_actor": "another-admin",
            "verified_at": "2026-09-14T10:00:00Z",
            "evidence_reference": f"{REFERENCE_NAMESPACE}opaque-2",
            "evidence_digest": "b" * 64,
        }.items():
            candidate = {**proof, field: value}
            self.assertEqual(semantic_identity(candidate), semantic)
            self.assertNotEqual(audit_identity(candidate), audit)

    def test_source_generation_uses_semantic_not_audit_identity(self):
        proof = self._semantic_proof()
        context = {
            "provider_config_entry_identity_domain": "0" * 64,
            "site_binding_identity": "1" * 64,
            "facility_identity": "2" * 64,
            "contract_identity_scope": "3" * 64,
            "dataset_identity": "greenely.invoice_economics.v1",
            "parser_identity": "parser-v1",
            "normalization_identity": "normalizer-v1",
            "proof_semantic_identity": semantic_identity(proof),
        }
        generation = source_generation_projection(context)
        for field, value in {
            "verification_actor": "another-admin",
            "verified_at": "2026-09-14T10:00:00Z",
            "evidence_reference": f"{REFERENCE_NAMESPACE}opaque-2",
            "evidence_digest": "b" * 64,
        }.items():
            changed = {**context, field: value, "proof_audit_identity": audit_identity({**proof, field: value})}
            self.assertEqual(source_generation_projection(changed), generation)
        changed_semantic = {**context, "proof_semantic_identity": "f" * 64}
        self.assertNotEqual(source_generation_projection(changed_semantic), generation)

    def test_provisioning_state_requires_unchanged_binding_and_complete_proof(self):
        proof = self._semantic_proof()
        context = {
            **self.context,
            "authenticated": True,
            "is_admin": True,
            "initial_binding": "binding-a",
            "expected_binding": "binding-a",
        }
        self.assertTrue(provisioning_state_eligible(proof, context, self.contracts, "binding-a"))
        self.assertFalse(provisioning_state_eligible(proof, context, self.contracts, "binding-b"))
        self.assertFalse(provisioning_state_eligible({**proof, "evidence_digest": None}, context, self.contracts, "binding-a"))
        self.assertFalse(provisioning_state_eligible(proof, {**context, "lookup_state": LOOKUP_FAILED}, self.contracts, "binding-a"))

    def test_provisioning_revalidates_provider_relation_before_persist(self):
        proof = self._semantic_proof()
        context = {
            **self.context,
            "authenticated": True,
            "is_admin": True,
            "initial_binding": "binding-a",
            "expected_binding": "binding-a",
        }
        self.assertTrue(
            provisioning_state_eligible(
                proof, context, self.contracts, "binding-a", LOOKUP_OK, self.contracts
            )
        )
        for current_contracts, current_lookup_state in (
            ([{"id": "contract-a", "facility_id": "facility-b"}], LOOKUP_OK),
            ([], LOOKUP_OK),
            (self.contracts * 2, LOOKUP_OK),
            (self.contracts, LOOKUP_FAILED),
            ([{"id": "contract-b", "facility_id": "facility-a"}], LOOKUP_OK),
        ):
            self.assertFalse(
                provisioning_state_eligible(
                    proof,
                    context,
                    self.contracts,
                    "binding-a",
                    current_lookup_state,
                    current_contracts,
                )
            )

    def test_semantic_context_changes_invalidate_proof(self):
        proof = self._semantic_proof()
        self.assertTrue(proof_is_current(proof, proof))
        for field in SEMANTIC_FIELDS:
            changed = {**proof, field: f"changed-{field}"}
            self.assertFalse(proof_is_current(proof, changed))
        for field, value in {
            "verification_actor": "another-admin",
            "verified_at": "2026-09-14T10:00:00Z",
            "evidence_reference": f"{REFERENCE_NAMESPACE}opaque-2",
            "evidence_digest": "b" * 64,
        }.items():
            self.assertTrue(proof_is_current(proof, {**proof, field: value}))

    def test_versioned_evidence_package_digest_is_deterministic_and_not_raw_identity(self):
        package = {
            "package_version": EVIDENCE_PACKAGE_VERSION,
            "procedure": "operator_compared_provider_and_invoice_sections",
            "relation": "greenely_meter_id_to_invoice_installation_id",
            "semantic_identity": "5" * 64,
            "recorded_at": "2026-09-13T10:00:00Z",
        }
        digest = evidence_package_digest(package)
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, evidence_package_digest(dict(reversed(list(package.items())))))
        self.assertNotEqual(digest, evidence_package_digest({**package, "procedure": "different"}))
        self.assertIsNone(evidence_package_digest({"Anl.id": "install-a"}))
        self.assertIsNone(evidence_package_digest({"meter_id": "meter-a"}))
        self.assertIsNone(evidence_package_digest({**package, "package_version": ""}))
        self.assertIsNone(evidence_package_digest({**package, "procedure": "raw_installation_only"}))

    def test_supplied_evidence_digest_is_verified_against_versioned_package(self):
        package = {
            "package_version": EVIDENCE_PACKAGE_VERSION,
            "procedure": "operator_compared_provider_and_invoice_sections",
            "relation": "greenely_meter_id_to_invoice_installation_id",
            "semantic_identity": "5" * 64,
            "recorded_at": "2026-09-13T10:00:00Z",
        }
        digest = evidence_package_digest(package)
        self.assertTrue(verify_evidence_digest(package, digest))
        self.assertTrue(
            verify_evidence_digest(dict(reversed(list(package.items()))), digest)
        )
        self.assertFalse(verify_evidence_digest(package, "b" * 64))
        self.assertFalse(
            verify_evidence_digest({**package, "relation": "changed"}, digest)
        )
        for supplied in (None, "", "not-a-digest", "a" * 63, "a" * 65):
            self.assertFalse(verify_evidence_digest(package, supplied))

    def _semantic_proof(self):
        return {
            "relation": "greenely_meter_id_to_invoice_installation_id",
            "provider_config_entry_identity_domain": "0" * 64,
            "site_binding_identity": "1" * 64,
            "facility_identity": "2" * 64,
            "contract_identity_scope": "3" * 64,
            "facility_meter_identity_state": "4" * 64,
            "contract_meter_identity_state": "4" * 64,
            "invoice_installation_identity": "5" * 64,
            "verification_method": "explicit_out_of_band_invoice_verification",
            "proof_schema_version": "v1",
            "fingerprint_version": "sha256-v1",
            "parser_identity": "parser-v1",
            "normalization_identity": "normalizer-v1",
            **self.proof,
        }

    def test_semantic_identity_is_deterministic_and_audit_is_separate(self):
        proof = {
            "relation": "greenely_meter_id_to_invoice_installation_id",
            "provider_config_entry_identity_domain": "0" * 64,
            "site_binding_identity": "1" * 64,
            "facility_identity": "2" * 64,
            "contract_identity_scope": "3" * 64,
            "facility_meter_identity_state": "4" * 64,
            "contract_meter_identity_state": "4" * 64,
            "invoice_installation_identity": "5" * 64,
            "verification_method": "explicit_out_of_band_invoice_verification",
            "proof_schema_version": "v1",
            "fingerprint_version": "sha256-v1",
            "parser_identity": "parser-v1",
            "normalization_identity": "normalizer-v1",
            **self.proof,
        }
        semantic = semantic_identity(proof)
        self.assertEqual(semantic, semantic_identity(dict(reversed(list(proof.items())))))
        self.assertEqual(semantic, semantic_identity({**proof, "verification_actor": "another-admin", "verified_at": "2026-09-14T10:00:00Z"}))
        self.assertNotEqual(semantic, semantic_identity({**proof, "contract_identity_scope": "contract-b"}))
        self.assertNotEqual(audit_identity(proof), audit_identity({**proof, "evidence_digest": "b" * 64}))

    def test_active_site_does_not_enter_identity_or_raw_identities_are_not_output(self):
        proof = {**self._semantic_proof(), "verification_method": "provider_native_semantic_proof"}
        self.assertEqual(semantic_identity(proof), semantic_identity({**proof, "active_site_id": "different"}))
        encoded = json.dumps(proof)
        for raw in ("facility-a", "contract-a", "meter-a", "install-a", "ocr-a"):
            self.assertNotIn(raw, encoded)
        self.assertIn("proof_semantic_identity", self.fixtures["source_generation"]["includes"])
        self.assertIn("verification_actor", self.fixtures["source_generation"]["excludes"])


if __name__ == "__main__":
    unittest.main()
