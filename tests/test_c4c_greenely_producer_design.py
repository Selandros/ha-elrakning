import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs/architecture/C4C_GREENELY_PRODUCER_DESIGN_V1.md"
FIXTURE_PATH = ROOT / "docs/architecture/contracts/c4c_greenely_producer_design_v1.fixtures.json"


def _semantic_key(candidate):
    return tuple(candidate[field] for field in ("dataset", "site_id", "generation_id", "role", "target"))


def _append_immutable(records, candidate):
    key = _semantic_key(candidate)
    same_target = [record for record in records if _semantic_key(record) == key]
    if same_target and same_target[-1]["knowledge"] == candidate["knowledge"]:
        return "deduplicate"
    revision = len(same_target) + 1
    frame = dict(candidate)
    frame["revision"] = revision
    frame["supersedes_frame_id"] = same_target[-1]["frame_id"] if same_target else None
    records.append(frame)
    return frame


def _attribute_to_binding(candidate, binding):
    if candidate["facility_id"] != binding["facility_id"]:
        return None
    if candidate["generation_id"] != binding["generation_id"]:
        return None
    return candidate


def _invoice_candidates(source):
    if not source["collection_enabled"] or not source["valid_binding"]:
        return []
    if not source["invoice_evidence"] or source["invoice_attribution"] != "ATTRIBUTED":
        return []
    if source["inherited_site_data"] and not source["facility_attribution_proof"]:
        return []
    return [{"dataset": "greenely.invoice_economics.v1", "site_id": source["site_id"]}]


def _current_snapshot_candidates(source):
    if not source["collection_enabled"] or not source["valid_binding"]:
        return []
    if source["contract_status"] != "CURRENT" or not source["current_tariff_evidence"]:
        return []
    if source["inherited_site_data"] and not source["facility_attribution_proof"]:
        return []
    return [{"dataset": "greenely.current_tariff_snapshot.v1", "site_id": source["site_id"]}]


class C4CGreenelyProducerDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = DOC_PATH.read_text(encoding="utf-8")
        cls.fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_scope_is_design_only(self):
        self.assertTrue(all(value is False for value in self.fixtures["scope_guards"].values()))
        self.assertIn("does not authorize a", self.doc)
        self.assertIn("production producer", self.doc)
        self.assertIn("Fixtures and tests must cover", self.doc)

    def test_identity_fields_are_kept_separate(self):
        expected = {
            "site_id", "configured_facility_id", "api_facility_id", "facility_meter_id",
            "contract_id", "contract_facility_id", "invoice_key", "invoice_contract_id",
            "pdf_installation_id", "verified_site_timezone",
        }
        self.assertEqual(set(self.fixtures["identity_fields"]), expected)
        for field in ("facility_id", "meter_id", "Anl.id"):
            self.assertIn(field, self.doc)
        self.assertIn("must not silently equate", self.doc)

    def test_multi_installation_attribution_is_fail_closed(self):
        cases = {item["name"]: item for item in self.fixtures["identity_cases"]}
        self.assertEqual(cases["one_installation_exact_identity"]["candidate_count"], 1)
        self.assertEqual(cases["multi_installation_exact_selected_identity"]["selected_section_count"], 1)
        for name in (
            "multi_installation_without_selected_identity",
            "selected_identity_has_no_section_match",
            "multiple_plausible_sections",
            "facility_identity_mismatch",
            "contract_facility_mismatch",
            "missing_contract_attribution",
        ):
            self.assertEqual(cases[name]["candidate_count"], 0)
            self.assertNotEqual(cases[name]["status"], "ATTRIBUTED")
        equal_without_proof = cases["equal_meter_and_installation_without_relation_proof"]
        self.assertEqual(equal_without_proof["facility_meter_id"], equal_without_proof["pdf_installation_id"])
        self.assertFalse(equal_without_proof["identity_relation_proof"])
        self.assertEqual(equal_without_proof["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(equal_without_proof["candidate_count"], 0)
        self.assertIn("There is no fallback to the first section", self.doc)

    def test_component_boundary_is_explicit(self):
        contract = self.fixtures["component_contract"]
        self.assertEqual(
            set(contract["included"]),
            {"economic.provider.import.variable", "economic.provider.fixed.subscription"},
        )
        self.assertTrue(all(item["requires_explicit_vat_basis"] for item in contract["included"].values()))
        for excluded in ("nord_pool_spot", "credits", "amount_due", "grid_economics", "customer_price"):
            self.assertIn(excluded, contract["excluded"])
        self.assertEqual(contract["missing_component_rule"], "unavailable_not_zero_filled")
        self.assertIn("Economic component boundary", self.doc)

    def test_datasets_have_separate_revision_chains(self):
        datasets = self.fixtures["dataset_matrix"]
        self.assertEqual(len(datasets), 2)
        self.assertEqual(datasets[0]["shares_revision_chain_with"], [])
        self.assertEqual(datasets[1]["shares_revision_chain_with"], [])
        self.assertIn("never share semantic keys, revisions, or supersedes links", self.doc)

    def test_dst_and_unknown_timezone_rules(self):
        dst = next(item for item in self.fixtures["timestamp_cases"] if item["name"] == "stockholm_dst_period")
        zone = ZoneInfo(dst["timezone"])
        start = datetime.fromisoformat(dst["period_start"]).replace(tzinfo=zone)
        end = (datetime.fromisoformat(dst["period_end"]) + timedelta(days=1)).replace(tzinfo=zone)
        self.assertEqual(start.astimezone(timezone.utc).isoformat(), dst["expected_valid_from_utc"])
        self.assertEqual(end.astimezone(timezone.utc).isoformat(), dst["expected_valid_to_utc"])
        self.assertEqual((end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() / 3600, dst["duration_hours"])
        spring = next(item for item in self.fixtures["timestamp_cases"] if item["name"] == "stockholm_spring_dst_period")
        spring_start = datetime.fromisoformat(spring["period_start"]).replace(tzinfo=zone)
        spring_end = (datetime.fromisoformat(spring["period_end"]) + timedelta(days=1)).replace(tzinfo=zone)
        self.assertEqual(spring_start.astimezone(timezone.utc).isoformat(), spring["expected_valid_from_utc"])
        self.assertEqual(spring_end.astimezone(timezone.utc).isoformat(), spring["expected_valid_to_utc"])
        self.assertEqual((spring_end.astimezone(timezone.utc) - spring_start.astimezone(timezone.utc)).total_seconds() / 3600, spring["duration_hours"])
        unknown = next(item for item in self.fixtures["timestamp_cases"] if item["name"] == "unknown_timezone_fails_closed")
        self.assertFalse(unknown["expected_frame"])
        self.assertIn("Without a verified timezone", self.doc)

    def test_current_snapshot_cannot_be_backfilled(self):
        snapshot = next(item for item in self.fixtures["timestamp_cases"] if item["name"] == "current_snapshot_is_capture_instant")
        self.assertIsNone(snapshot["valid_from"])
        self.assertIsNone(snapshot["valid_to"])
        self.assertEqual(snapshot["valid_at"], "captured_at")
        self.assertFalse(snapshot["backfill_allowed"])
        self.assertIn("not expanded backwards", self.doc)

    def test_generation_and_target_identity_are_separate(self):
        excluded = set(self.fixtures["source_generation_excludes"])
        included = set(self.fixtures["source_generation_includes"])
        self.assertEqual(
            included,
            {
                "provider_adapter_version", "config_entry_identity", "site_binding_identity",
                "facility_identity", "contract_identity", "dataset_identity", "parser_version",
                "normalization_version", "vat_semantics", "unit_semantics",
                "verified_timezone_identity_and_state",
            },
        )
        self.assertEqual(
            excluded,
            {
                "invoice_key", "invoice_number", "billing_period", "pdf_section_index", "economic_values",
                "captured_at", "fetched_at", "known_at", "revision", "frame_id", "active_site_id",
            },
        )
        self.assertIn("Invoice identity, billing period", self.doc)

    def test_replay_and_revision_rules(self):
        cases = {item["name"]: item for item in self.fixtures["identity_and_revision_cases"]}
        self.assertEqual(cases["same_knowledge_deduplicates"]["expected"], "deduplicate")
        self.assertEqual(cases["changed_knowledge_same_target_revises"]["expected"], "revision_next_same_generation")
        replay = cases["known_at_replay_filter"]
        decision = datetime.fromisoformat(replay["decision_at"].replace("Z", "+00:00"))
        self.assertLessEqual(datetime.fromisoformat(replay["revision_1_known_at"].replace("Z", "+00:00")), decision)
        self.assertGreater(datetime.fromisoformat(replay["revision_2_known_at"].replace("Z", "+00:00")), decision)
        self.assertEqual(replay["expected_visible_revision"], 1)
        self.assertIn("known_at <= decision_at", self.doc)

    def test_immutable_dedup_revision_and_generation_reset_are_materialized(self):
        records = []
        base = {
            "dataset": "greenely.invoice_economics.v1",
            "site_id": "site-a",
            "generation_id": "gen-a",
            "role": "economic.provider.import.variable",
            "target": "invoice:invoice-a:2026-08",
            "knowledge": {"value": 0.17, "known_at": "2026-09-13T10:00:00Z"},
            "frame_id": "frame-1",
        }
        first = _append_immutable(records, base)
        self.assertEqual(first["revision"], 1)
        self.assertIsNone(first["supersedes_frame_id"])
        self.assertEqual(
            _append_immutable(records, dict(base, frame_id="frame-duplicate")),
            "deduplicate",
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["revision"], 1)
        self.assertIsNone(records[0]["supersedes_frame_id"])
        self.assertEqual(records[0]["frame_id"], "frame-1")
        second = _append_immutable(
            records,
            dict(base, knowledge={"value": 0.18, "known_at": "2026-09-13T11:00:00Z"}, frame_id="frame-2"),
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(second["revision"], 2)
        self.assertEqual(second["supersedes_frame_id"], "frame-1")
        new_generation = _append_immutable(
            records,
            dict(base, generation_id="gen-b", knowledge=base["knowledge"], frame_id="frame-3"),
        )
        self.assertEqual(new_generation["revision"], 1)
        self.assertIsNone(new_generation["supersedes_frame_id"])

    def test_rebinding_rejects_old_attribution_and_starts_new_generation(self):
        old = {
            "site_id": "site-a",
            "facility_id": "facility-a",
            "generation_id": "gen-a",
            "frame_id": "old-frame",
        }
        old_binding = {"site_id": "site-a", "facility_id": "facility-a", "generation_id": "gen-a"}
        new_binding = {"site_id": "site-a", "facility_id": "facility-b", "generation_id": "gen-b"}
        self.assertEqual(old_binding["site_id"], new_binding["site_id"])
        self.assertNotEqual(old_binding["facility_id"], new_binding["facility_id"])
        self.assertNotEqual(old_binding["generation_id"], new_binding["generation_id"])
        self.assertEqual(old["facility_id"], old_binding["facility_id"])
        self.assertNotEqual(old["facility_id"], new_binding["facility_id"])
        self.assertEqual(old["generation_id"], old_binding["generation_id"])
        self.assertNotEqual(old["generation_id"], new_binding["generation_id"])
        self.assertIsNone(_attribute_to_binding(old, new_binding))
        new = dict(old, facility_id="facility-b", generation_id="gen-b", frame_id="new-frame")
        self.assertEqual(_attribute_to_binding(new, new_binding), new)
        self.assertEqual(
            _append_immutable(
                [],
                {
                    "dataset": "greenely.invoice_economics.v1",
                    "site_id": "site-a",
                    "generation_id": "gen-b",
                    "role": "economic.provider.import.variable",
                    "target": "invoice:invoice-a:2026-08",
                    "knowledge": {"value": 0.17},
                    "frame_id": "new-frame",
                },
            )["revision"],
            1,
        )

    def test_clean_room_zero_is_caused_by_generic_source_eligibility(self):
        fixture = next(item for item in self.fixtures["site_cases"] if item["name"] == "fiskvik_future_clean_room")
        base = {
            "site_id": fixture["site_id"],
            "collection_enabled": fixture["collection_enabled"],
            "valid_binding": True,
            "invoice_evidence": fixture["invoice_evidence"],
            "invoice_attribution": "INSUFFICIENT_EVIDENCE",
            "contract_status": fixture["contract_status"],
            "current_tariff_evidence": False,
            "inherited_site_data": fixture["inherited_site_data"],
            "facility_attribution_proof": False,
        }
        self.assertEqual(_invoice_candidates(base), [])
        self.assertEqual(_current_snapshot_candidates(base), [])

        historical = dict(
            base,
            site_id="generic-site-a",
            invoice_evidence=True,
            invoice_attribution="ATTRIBUTED",
            contract_status="ENDED",
            facility_attribution_proof=True,
        )
        self.assertEqual(len(_invoice_candidates(historical)), 1)

        foreign = dict(base, inherited_site_data=True, facility_attribution_proof=False)
        self.assertEqual(_invoice_candidates(foreign), [])
        self.assertEqual(_current_snapshot_candidates(foreign), [])

        same_inputs_other_site = dict(base, site_id="generic-site-b")
        self.assertEqual(_invoice_candidates(base), _invoice_candidates(same_inputs_other_site))
        self.assertEqual(_current_snapshot_candidates(base), _current_snapshot_candidates(same_inputs_other_site))

    def test_site_independence_and_fiskvik_clean_room(self):
        cases = {item["name"]: item for item in self.fixtures["site_cases"]}
        self.assertTrue(cases["inactive_bound_site_is_targeted"]["expected_target"])
        self.assertFalse(cases["active_site_without_binding_is_not_targeted"]["expected_target"])
        fiskvik = cases["fiskvik_future_clean_room"]
        self.assertTrue(fiskvik["collection_enabled"])
        self.assertFalse(fiskvik["invoice_evidence"])
        self.assertEqual(fiskvik["contract_status"], "FUTURE")
        self.assertFalse(fiskvik["inherited_site_data"])
        self.assertEqual(fiskvik["eligibility_basis"], "future_contract_without_invoice_evidence")
        self.assertEqual(fiskvik["expected_invoice_frames"], 0)
        self.assertEqual(fiskvik["expected_current_snapshot_frames"], 0)
        self.assertEqual(cases["site_rebinding_never_reuses_old_attribution"]["expected"], "new_generation_no_old_data_attribution")
        self.assertIn("`active_site_id` is UI/read context only", self.doc)


if __name__ == "__main__":
    unittest.main()
