import hashlib
import hmac
import json
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/architecture/C4C1_GREENELY_IDENTITY_AMENDMENT_V1.md"
FIXTURES = ROOT / "docs/architecture/contracts/c4c1_greenely_identity_amendment_v1.fixtures.json"


TEST_KEY = b"synthetic-test-key-only"
EXPECTED_SOURCE_GENERATION_INCLUDES = [
    "provider_adapter_version", "config_entry_identity", "site_binding_identity",
    "facility_identity", "contract_identity", "dataset_identity", "parser_version",
    "normalization_version", "vat_semantics", "unit_semantics",
    "verified_timezone_identity_and_state", "installation_attribution_proof_identity_state_version",
    "pseudonymization_key_id_identity_domain_id",
]
EXPECTED_SOURCE_GENERATION_EXCLUDES = [
    "raw_ocr", "invoice_occurrence_identity", "billing_period", "economic_values",
    "captured_at", "fetched_at", "known_at", "frame_id", "revision", "active_site_id",
]
EXPECTED_C1_CONCEPTS = [
    "source_generation_id", "semantic_key", "revision", "supersedes_frame_id", "site_id",
    "site_scope", "known_at", "captured_at", "valid_from", "valid_to", "provenance",
    "quality", "external_input_points",
]
EXPECTED_PROOF_SCHEMA = "v1"
ALLOWED_VERIFICATION_METHODS = {
    "provider_native_semantic_proof",
    "explicit_out_of_band_invoice_verification",
}


def canonical_occurrence_payload(
    *, identity_version, provider_namespace, config_entry_identity,
    contract_identity, provider_invoice_occurrence_reference,
):
    fields = {
        "identity_version": identity_version,
        "provider_namespace": provider_namespace,
        "config_entry_identity": config_entry_identity,
        "contract_identity": contract_identity,
        "provider_invoice_occurrence_reference": provider_invoice_occurrence_reference,
    }
    if any(not isinstance(value, str) or not value for value in fields.values()):
        return None
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def occurrence_identity(key, **fields):
    if not isinstance(key, bytes) or not key:
        return None
    required = {
        "identity_version",
        "provider_namespace",
        "config_entry_identity",
        "contract_identity",
        "provider_invoice_occurrence_reference",
    }
    if set(fields) != required or not fields["provider_invoice_occurrence_reference"].strip():
        return None
    message = canonical_occurrence_payload(**fields)
    return hmac.new(key, message, hashlib.sha256).hexdigest() if message else None


def proof_valid(proof, binding):
    if not isinstance(proof, dict) or not isinstance(binding, dict):
        return False
    if proof.get("verification_state") != "EXPLICITLY_VERIFIED":
        return False
    if proof.get("provider") != "greenely":
        return False
    if proof.get("verification_method") not in ALLOWED_VERIFICATION_METHODS:
        return False
    if proof.get("proof_schema_version") != EXPECTED_PROOF_SCHEMA:
        return False
    verified_at = proof.get("verified_at")
    if not isinstance(verified_at, str) or not verified_at.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(verified_at[:-1] + "+00:00")
    except ValueError:
        return False
    for field in (
        "site_binding_fingerprint",
        "facility_identity_fingerprint",
        "contract_identity_fingerprint",
        "facility_meter_id_fingerprint",
        "contract_meter_id_fingerprint_or_state",
        "invoice_installation_identity_fingerprint",
        "provider",
        "config_entry_identity",
        "contract_scope",
        "verification_method",
        "verified_at",
        "proof_schema_version",
        "parser_identity",
        "normalization_identity",
    ):
        if proof.get(field) != binding.get(field):
            return False
    return True


def replay_visible(records, decision_at):
    return [record for record in records if record["known_at"] <= decision_at]


def select_replay(records, decision_at):
    visible = replay_visible(records, decision_at)
    selected = {}
    for record in visible:
        target = (record["occurrence"], record["billing_period"], record["role"])
        if target not in selected or record["revision"] > selected[target]["revision"]:
            selected[target] = record
    return list(selected.values())


def invoice_candidates(site):
    required = (
        site.get("collection_enabled"),
        site.get("legitimate_binding"),
        site.get("invoice_evidence"),
        site.get("invoice_attribution") == "EXPLICITLY_VERIFIED",
        isinstance(site.get("occurrence_reference"), str) and bool(site["occurrence_reference"].strip()),
        site.get("verified_timezone"),
        site.get("component_evidence"),
        site.get("facility_attribution", True),
    )
    return [site] if all(required) else []


def source_generation_identity(source):
    return tuple(source[field] for field in EXPECTED_SOURCE_GENERATION_INCLUDES)


def append_occurrence(records, candidate):
    key = tuple(candidate[field] for field in ("occurrence", "billing_period", "role"))
    same = [item for item in records if tuple(item[field] for field in ("occurrence", "billing_period", "role")) == key]
    if same and same[-1]["knowledge"] == candidate["knowledge"]:
        return "deduplicate"
    frame = dict(candidate)
    frame["revision"] = len(same) + 1
    frame["supersedes"] = same[-1]["frame_id"] if same else None
    records.append(frame)
    return frame


class C4C1GreenelyIdentityAmendmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = DOC.read_text(encoding="utf-8")
        cls.fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))

    def test_scope_and_resolved_key_model(self):
        self.assertEqual(self.fixtures["status"], "READY_FOR_REVIEW")
        self.assertEqual(self.fixtures["hmac_key_audit"]["status"], "HMAC_KEY_MODEL_RESOLVED")
        self.assertTrue(self.fixtures["hmac_key_audit"]["production_key_selected"])
        self.assertFalse(self.fixtures["hmac_key_audit"]["production_key_material_created"])
        self.assertIn("private=True", self.fixtures["hmac_key_audit"]["storage"])
        self.assertIn("atomic_writes=True", self.fixtures["hmac_key_audit"]["storage"])
        self.assertTrue(self.fixtures["hmac_key_audit"]["key_id_is_source_generation_input"])
        self.assertFalse(self.fixtures["hmac_key_audit"]["plain_sha_fallback_allowed"])
        self.assertIn("C.4B and C.4C remain locked", self.doc)
        self.assertIn("does not authorize a", self.doc)
        self.assertIn("IDENTITY AMENDMENT READY FOR REVIEW", self.doc)

    def test_proof_requires_exact_binding_and_state(self):
        binding = {
            "site_binding_fingerprint": "bind-a",
            "facility_identity_fingerprint": "facility-a",
            "contract_identity_fingerprint": "contract-a",
            "facility_meter_id_fingerprint": "meter-a",
            "contract_meter_id_fingerprint_or_state": "meter-a",
            "invoice_installation_identity_fingerprint": "install-a",
            "provider": "greenely",
            "config_entry_identity": "entry-a",
            "contract_scope": "contract-a",
            "verification_method": "provider_native_semantic_proof",
            "verified_at": "2026-09-13T10:00:00Z",
            "proof_schema_version": "v1",
            "parser_identity": "parser-a",
            "normalization_identity": "normalizer-a",
        }
        proof = dict(binding, verification_state="EXPLICITLY_VERIFIED")
        self.assertTrue(proof_valid(proof, binding))
        self.assertFalse(proof_valid(dict(proof, verification_state="UNVERIFIED"), binding))
        self.assertFalse(proof_valid(dict(proof, facility_identity_fingerprint="facility-b"), binding))
        self.assertFalse(proof_valid(dict(proof, facility_meter_id_fingerprint="meter-b"), binding))
        self.assertFalse(proof_valid(dict(proof, provider="other"), binding))
        self.assertFalse(proof_valid(dict(proof, verification_method="user_confirmation"), binding))
        self.assertFalse(proof_valid({key: value for key, value in proof.items() if key != "verification_method"}, binding))
        self.assertFalse(proof_valid({key: value for key, value in proof.items() if key != "verified_at"}, binding))
        self.assertFalse(proof_valid(dict(proof, verified_at="not-a-timestamp"), binding))
        self.assertFalse(proof_valid(dict(proof, verified_at="2026-09-13T10:00:00"), binding))
        self.assertFalse(proof_valid(dict(proof, proof_schema_version="v2"), binding))
        self.assertFalse(proof_valid({key: value for key, value in proof.items() if key != "proof_schema_version"}, binding))

    def test_proof_invalidation_fields_are_required(self):
        binding = {
            "site_binding_fingerprint": "bind-a",
            "facility_identity_fingerprint": "facility-a",
            "contract_identity_fingerprint": "contract-a",
            "facility_meter_id_fingerprint": "meter-a",
            "contract_meter_id_fingerprint_or_state": "meter-a",
            "invoice_installation_identity_fingerprint": "install-a",
            "provider": "greenely",
            "config_entry_identity": "entry-a",
            "contract_scope": "contract-a",
            "verification_method": "explicit_out_of_band_invoice_verification",
            "verified_at": "2026-09-13T10:00:00Z",
            "proof_schema_version": "v1",
            "parser_identity": "parser-a",
            "normalization_identity": "normalizer-a",
        }
        proof = dict(binding, verification_state="EXPLICITLY_VERIFIED")
        for field in binding:
            with self.subTest(field=field):
                self.assertFalse(proof_valid(dict(proof, **{field: "changed"}), binding))
        self.assertTrue(proof_valid(dict(proof, active_site_id="unrelated-site"), binding))

    def test_occurrence_identity_is_contract_scoped_and_opaque(self):
        fields = dict(identity_version="v1", provider_namespace="greenely", config_entry_identity="entry-a", contract_identity="contract-a", provider_invoice_occurrence_reference="ocr-a")
        first = occurrence_identity(TEST_KEY, **fields)
        same = occurrence_identity(TEST_KEY, **dict(reversed(list(fields.items()))))
        other_contract = occurrence_identity(TEST_KEY, **dict(fields, contract_identity="contract-b"))
        self.assertEqual(first, same)
        self.assertNotEqual(first, other_contract)
        self.assertIsNone(occurrence_identity(TEST_KEY, **dict(fields, provider_invoice_occurrence_reference="")))
        self.assertIsNone(occurrence_identity(TEST_KEY, **dict(fields, provider_invoice_occurrence_reference="   ")))
        self.assertNotIn("ocr-a", first)

    def test_key_domain_separation_is_deterministic(self):
        fields = dict(identity_version="v1", provider_namespace="greenely", config_entry_identity="entry-a", contract_identity="contract-a", provider_invoice_occurrence_reference="ocr-a")
        first = occurrence_identity(TEST_KEY, **fields)
        same = occurrence_identity(TEST_KEY, **fields)
        other_domain = occurrence_identity(
            b"synthetic-test-key-other-domain", **dict(fields, config_entry_identity="entry-b")
        )
        self.assertEqual(first, same)
        self.assertNotEqual(first, other_domain)
        self.assertNotIn("synthetic-test-key", first)

    def test_hmac_uses_versioned_canonical_json_without_mutable_fields(self):
        fields = dict(identity_version="v1", provider_namespace="greenely", config_entry_identity="entry-a", contract_identity="contract-a", provider_invoice_occurrence_reference="ocr-a")
        first = occurrence_identity(TEST_KEY, **fields)
        different_version = occurrence_identity(TEST_KEY, **dict(fields, identity_version="v2"))
        same_occurrence_without_period = occurrence_identity(TEST_KEY, **dict(fields))
        self.assertNotEqual(first, different_version)
        self.assertEqual(first, same_occurrence_without_period)
        self.assertEqual(canonical_occurrence_payload(**fields), canonical_occurrence_payload(**dict(reversed(list(fields.items())))))
        self.assertEqual(len(first), 64)
        self.assertNotEqual(
            occurrence_identity(TEST_KEY, **dict(fields, provider_namespace="other")), first
        )
        self.assertNotEqual(
            occurrence_identity(TEST_KEY, **dict(fields, provider_invoice_occurrence_reference="ocr-b")), first
        )
        self.assertNotIn("billing_period", canonical_occurrence_payload(**fields).decode("utf-8"))
        self.assertNotIn("captured_at", canonical_occurrence_payload(**fields).decode("utf-8"))
        self.assertIn("canonical JSON", self.doc)
        self.assertIn("identity_version", self.doc)
        self.assertIn("no mutable timestamps", self.doc)

    def test_hmac_input_order_and_occurrence_reference_are_identity_relevant(self):
        fields = {
            "identity_version": "v1",
            "provider_namespace": "greenely",
            "config_entry_identity": "entry-a",
            "contract_identity": "contract-a",
            "provider_invoice_occurrence_reference": "ocr-a",
        }
        reordered = dict(reversed(list(fields.items())))
        def digest(payload):
            message = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            return hmac.new(TEST_KEY, message, hashlib.sha256).hexdigest()
        self.assertEqual(digest(fields), digest(reordered))
        self.assertNotEqual(digest(fields), digest(dict(fields, provider_invoice_occurrence_reference="ocr-b")))
        self.assertNotIn("ocr-a", digest(fields))
        self.assertNotIn(TEST_KEY.decode(), digest(fields))

    def test_same_occurrence_deduplicates_and_revises(self):
        records = []
        base = {
            "occurrence": "opaque-a",
            "billing_period": "2026-08",
            "role": "economic.provider.import.variable",
            "knowledge": {"value": 0.17},
            "frame_id": "frame-1",
        }
        self.assertEqual(append_occurrence(records, base), {**base, "revision": 1, "supersedes": None})
        self.assertEqual(append_occurrence(records, dict(base, frame_id="duplicate")), "deduplicate")
        revised = append_occurrence(records, dict(base, knowledge={"value": 0.18}, frame_id="frame-2"))
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(revised["supersedes"], "frame-1")

    def test_different_occurrence_same_period_is_new_target_without_supersedes(self):
        records = []
        base = {
            "billing_period": "2026-08",
            "role": "economic.provider.import.variable",
            "knowledge": {"value": 0.17},
        }
        first = append_occurrence(records, dict(base, occurrence="opaque-a", frame_id="frame-a"))
        second = append_occurrence(records, dict(base, occurrence="opaque-b", frame_id="frame-b"))
        self.assertEqual(first["revision"], 1)
        self.assertEqual(second["revision"], 1)
        self.assertIsNone(second["supersedes"])

    def test_fixture_cases_and_locked_invariants(self):
        self.assertEqual(len(self.fixtures["identity_cases"]), 8)
        self.assertEqual(len(self.fixtures["occurrence_cases"]), 9)
        self.assertIn("known_at <= decision_at", self.doc)
        self.assertIn("no latest-wins rule exists", self.doc)
        self.assertIn("active_site_id", self.fixtures["source_generation"]["excludes"])
        self.assertIn("raw_ocr", self.fixtures["source_generation"]["excludes"])
        self.assertEqual(self.fixtures["source_generation"]["includes"], EXPECTED_SOURCE_GENERATION_INCLUDES)
        self.assertEqual(self.fixtures["source_generation"]["excludes"], EXPECTED_SOURCE_GENERATION_EXCLUDES)
        self.assertFalse(self.fixtures["source_generation"]["schema_migration_required"])
        self.assertEqual(self.fixtures["source_generation"]["c1_compatibility_concepts"], EXPECTED_C1_CONCEPTS)
        self.assertEqual(len(self.fixtures["key_lifecycle_cases"]), 8)
        self.assertIn("no_key_with_dependent_history", {case["name"] for case in self.fixtures["key_lifecycle_cases"]})

    def test_no_cross_domain_supersedes_or_implicit_recovery(self):
        self.assertIn("cross-key matching", self.doc)
        self.assertIn("attach it implicitly", self.doc)
        self.assertIn("fail_closed_no_implicit_attachment", {
            case["expected"] for case in self.fixtures["key_lifecycle_cases"]
        })
        self.assertIn("different_key_domains_have_different_occurrence_identity", {
            case["name"] for case in self.fixtures["privacy_cases"]
        })

    def test_rotation_is_separate_v1_contract(self):
        self.assertIn("unsupported_v1_fail_closed", self.fixtures["hmac_key_audit"]["rotation"])
        self.assertIn("V1 rotation is unsupported", self.doc)
        self.assertIn("future rotation requires separate identity domain", self.fixtures["hmac_key_audit"]["rotation"])

    def test_replay_and_clean_room_are_executable_invariants(self):
        records = [
            {"frame_id": "old", "occurrence": "occ-a", "billing_period": "2026-08", "role": "variable", "revision": 1, "known_at": "2026-09-13T10:00:00Z"},
            {"frame_id": "new", "occurrence": "occ-a", "billing_period": "2026-08", "role": "variable", "revision": 2, "known_at": "2026-09-13T11:00:00Z"},
            {"frame_id": "other", "occurrence": "occ-b", "billing_period": "2026-08", "role": "variable", "revision": 1, "known_at": "2026-09-13T10:15:00Z"},
        ]
        self.assertEqual(replay_visible(records, "2026-09-13T10:30:00Z"), [records[0], records[2]])
        self.assertEqual(
            select_replay(records, "2026-09-13T10:30:00Z"), [records[0], records[2]]
        )
        self.assertEqual(select_replay(records, "2026-09-13T11:30:00Z"), [records[1], records[2]])
        eligible = {
            "collection_enabled": True,
            "legitimate_binding": True,
            "invoice_evidence": True,
            "invoice_attribution": "EXPLICITLY_VERIFIED",
            "occurrence_reference": "ocr-a",
            "verified_timezone": True,
            "component_evidence": True,
            "site_id": "synthetic-a",
        }
        self.assertEqual(len(invoice_candidates(eligible)), 1)
        future = dict(eligible, invoice_evidence=False, invoice_attribution="INSUFFICIENT_EVIDENCE")
        self.assertEqual(invoice_candidates(future), [])
        other_site = dict(eligible, site_id="synthetic-b")
        self.assertEqual(len(invoice_candidates(eligible)), len(invoice_candidates(other_site)))
        ended = dict(eligible, current_contract_status="ENDED")
        self.assertEqual(len(invoice_candidates(ended)), 1)
        foreign = dict(eligible, facility_attribution=False)
        self.assertEqual(invoice_candidates(foreign), [])

    def test_eligibility_requires_each_input(self):
        base = {
            "collection_enabled": True,
            "legitimate_binding": True,
            "invoice_evidence": True,
            "invoice_attribution": "EXPLICITLY_VERIFIED",
            "occurrence_reference": "ocr-a",
            "verified_timezone": True,
            "component_evidence": True,
            "facility_attribution": True,
        }
        for field in base:
            with self.subTest(field=field):
                value = "" if field == "occurrence_reference" else False
                self.assertEqual(invoice_candidates(dict(base, **{field: value})), [])

    def test_source_generation_changes_only_for_source_semantics(self):
        base = {field: field + "-a" for field in EXPECTED_SOURCE_GENERATION_INCLUDES}
        base["pseudonymization_key_id_identity_domain_id"] = "domain-a"
        target_only = dict(base, invoice_occurrence_identity="target-a", raw_ocr="ocr-a")
        self.assertEqual(source_generation_identity(base), source_generation_identity(target_only))
        self.assertNotEqual(
            source_generation_identity(base),
            source_generation_identity(dict(base, pseudonymization_key_id_identity_domain_id="domain-b")),
        )
        self.assertNotEqual(
            source_generation_identity(base),
            source_generation_identity(dict(base, installation_attribution_proof_identity_state_version="proof-b")),
        )

    def test_no_runtime_or_raw_identity_contract(self):
        guards = self.fixtures["scope_guards"]
        self.assertTrue(all(value is False for value in guards.values()))
        self.assertIn("raw installation identifiers", self.doc)
        self.assertIn("must never be logged or exposed", self.doc)
        self.assertIn("C.4C.1 PRODUCTION IMPLEMENTATION: NOT AUTHORIZED", self.doc)
        self.assertIn("No C.1 schema migration", self.doc)


if __name__ == "__main__":
    unittest.main()
