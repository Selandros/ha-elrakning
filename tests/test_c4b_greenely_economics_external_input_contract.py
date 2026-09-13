import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs/architecture/C4B_GREENELY_ECONOMICS_EXTERNAL_INPUT_CONTRACT_V1.md"
FIXTURE_PATH = ROOT / "docs/architecture/contracts/c4b_greenely_economics_external_input_contract_v1.fixtures.json"


def _semantic_key(dataset, site_id, generation_id, role, target):
    return "|".join((dataset, site_id, generation_id, role, target))


class C4BGreenelyEconomicsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = DOC_PATH.read_text(encoding="utf-8")
        cls.fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_invoice_and_current_snapshot_are_separate_datasets_and_chains(self):
        datasets = {item["id"]: item for item in self.fixtures["datasets"]}
        self.assertEqual(datasets["invoice_economics"]["dataset"], "greenely.invoice_economics.v1")
        self.assertEqual(datasets["current_tariff_snapshot"]["dataset"], "greenely.current_tariff_snapshot.v1")
        self.assertEqual(datasets["invoice_economics"]["share_revision_chain_with"], [])
        self.assertEqual(datasets["current_tariff_snapshot"]["share_revision_chain_with"], [])
        self.assertFalse(self.fixtures["revision_rules"]["cross_dataset_supersedes"])
        self.assertIn("must never share a semantic key, revision chain or supersedes chain", self.doc)

    def test_provider_components_are_separate_from_spot_settlement_grid_and_customer_price(self):
        contract = self.fixtures["component_contract"]
        self.assertEqual(
            set(contract["included"]),
            {"economic.provider.import.variable", "economic.provider.fixed.subscription"},
        )
        for excluded in (
            "nord_pool_spot", "invoice_weighted_spot_average", "credits",
            "amount_due", "customer_price", "grid_economics",
        ):
            self.assertIn(excluded, contract["excluded"])
        self.assertEqual(contract["missing_component_rule"], "unavailable_not_zero_filled")
        self.assertIn("Nord Pool remains the shared market-price source", self.doc)

    def test_attribution_requires_site_facility_contract_and_invoice_without_active_site_fallback(self):
        attribution = self.fixtures["attribution"]
        generation = attribution["common_generation_fields"]
        self.assertIn("site_binding_identity", generation)
        self.assertIn("facility_id", generation)
        self.assertIn("contract_id", generation)
        self.assertEqual(
            attribution["invoice_target_fields"],
            ["invoice_key", "contract_id", "facility_id", "billing_period"],
        )
        self.assertTrue(attribution["fail_closed_on_mismatch"])
        self.assertIn("active_site_id", attribution["generation_excludes"])
        self.assertIn("A facility mismatch, contract mismatch, invoice mismatch", self.doc)

    def test_invoice_generation_includes_verified_timezone_but_current_snapshot_does_not(self):
        attribution = self.fixtures["attribution"]
        self.assertEqual(
            attribution["invoice_generation_additional_fields"],
            ["site_timezone", "site_timezone_verification_state"],
        )
        self.assertEqual(attribution["current_snapshot_generation_additional_fields"], [])
        self.assertIn("for `greenely.invoice_economics.v1` only: verified site timezone identity", self.doc)
        self.assertIn("current-snapshot generation does not inherit the invoice-only site", self.doc)

    def test_invoice_identity_is_target_not_generation_and_contract_replacement_is_new_generation(self):
        attribution = self.fixtures["attribution"]
        self.assertNotIn("invoice_key", attribution["common_generation_fields"])
        self.assertIn("invoice_key", attribution["generation_excludes"])
        rules = self.fixtures["revision_rules"]
        self.assertEqual(rules["new_invoice_same_contract"], "new_semantic_target_same_generation")
        self.assertEqual(
            rules["new_contract_or_facility"],
            "new_generation_revision_1_no_cross_generation_supersedes",
        )
        self.assertIn("Invoice identity is an invoice-economics target, not a new\nsource generation", self.doc)

    def test_semantic_identity_excludes_values_times_revision_and_active_site(self):
        spec = self.fixtures["semantic_key"]
        invoice = _semantic_key(
            "greenely.invoice_economics.v1", "site-a", "gen-a",
            "economic.provider.import.variable", "invoice:invoice-a:2026-08-01_2026-08-31",
        )
        current = _semantic_key(
            "greenely.current_tariff_snapshot.v1", "site-a", "gen-a",
            "economic.provider.import.variable", "current_tariff_snapshot",
        )
        self.assertEqual(invoice, spec["examples"]["invoice_variable"])
        self.assertEqual(current, spec["examples"]["current_variable"])
        self.assertNotEqual(invoice, current)
        for field in ("value", "captured_at", "fetched_at", "known_at", "revision", "active_site_id"):
            self.assertIn(field, spec["excludes"])

    def test_verified_timezone_resolves_invoice_period_with_dst_correct_utc_boundaries(self):
        fixture = self.fixtures["dst_fixture"]
        zone = ZoneInfo(fixture["timezone"])
        start_date = datetime.fromisoformat(fixture["period_start"])
        end_date = datetime.fromisoformat(fixture["period_end"])
        local_start = start_date.replace(tzinfo=zone)
        local_end_exclusive = (end_date + timedelta(days=1)).replace(tzinfo=zone)
        start_utc = local_start.astimezone(timezone.utc)
        end_utc = local_end_exclusive.astimezone(timezone.utc)
        self.assertEqual(start_utc.isoformat(), fixture["expected_valid_from_utc"])
        self.assertEqual(end_utc.isoformat(), fixture["expected_valid_to_utc"])
        self.assertEqual((end_utc - start_utc).total_seconds() / 3600, fixture["duration_hours"])
        self.assertIn("if the site's timezone is `verified`", self.doc)

    def test_unknown_timezone_fails_closed_instead_of_fabricating_invoice_validity(self):
        invoice = self.fixtures["timestamp_contract"]["invoice"]
        schema = self.fixtures["schema"]
        self.assertEqual(invoice["unknown_timezone"], "no_canonical_invoice_economics_frame")
        self.assertEqual(schema["unknown_timezone_invoice_point_policy"], "fail_closed_no_frame")
        self.assertIn("must not invent UTC boundaries", self.doc)

    def test_contract_effective_from_is_eligibility_provenance_not_tariff_validity(self):
        effective = self.fixtures["timestamp_contract"]["contract_effective_from"]
        self.assertEqual(effective["meaning"], "contract_eligibility_provenance_only")
        self.assertFalse(effective["may_define_invoice_valid_from"])
        self.assertFalse(effective["may_define_current_snapshot_valid_from"])
        self.assertIn("must not be copied into invoice `valid_from`", self.doc)

    def test_current_snapshot_is_capture_instant_only_and_never_backfill(self):
        snapshot = self.fixtures["timestamp_contract"]["current_snapshot"]
        self.assertIsNone(snapshot["valid_from"])
        self.assertIsNone(snapshot["valid_to"])
        self.assertEqual(snapshot["point_valid_at"], "captured_at")
        self.assertEqual(snapshot["known_at"], "captured_at")
        self.assertIsNone(snapshot["fetched_at"])
        self.assertFalse(snapshot["backfill_allowed"])
        self.assertFalse(self.fixtures["no_backfill"]["current_snapshot_as_historical_interval"])
        self.assertIn("must never be replayed as proof that the same\ntariff was current yesterday", self.doc)

    def test_fetched_at_is_not_fabricated_from_runtime_or_invoice_timestamps(self):
        timestamps = self.fixtures["timestamp_contract"]
        self.assertIsNone(timestamps["invoice"]["fetched_at"])
        self.assertIsNone(timestamps["current_snapshot"]["fetched_at"])
        self.assertIn("manager `last_update`, invoice\n  date and parser completion time are provenance, not fabricated fetch time", self.doc)

    def test_fiskvik_is_clean_room_with_only_future_metadata(self):
        fiskvik = self.fixtures["site_fixtures"]["fiskvik"]
        self.assertEqual(fiskvik["historical_invoice_count"], 0)
        self.assertEqual(fiskvik["historical_consumption_samples"], 0)
        self.assertFalse(fiskvik["attributed_current_summary_present"])
        self.assertEqual(fiskvik["future_contract_metadata"]["eligibility"], "FUTURE")
        self.assertEqual(fiskvik["expected_invoice_economics_frames"], 0)
        self.assertEqual(fiskvik["expected_current_tariff_snapshot_frames"], 0)
        self.assertIn("Fiskvik remains a strict clean room", self.doc)

    def test_no_historical_tariff_reconstruction_from_latest_summary(self):
        rules = self.fixtures["no_backfill"]
        self.assertTrue(all(value is False for value in rules.values()))
        self.assertIn("copying today's/latest invoice tariff over older invoice metadata", self.doc)
        self.assertIn("C.4B itself performs\nno backfill", self.doc)

    def test_revision_and_replay_rules_preserve_decision_time_knowledge(self):
        rules = self.fixtures["revision_rules"]
        self.assertEqual(rules["same_normalized_knowledge"], "deduplicate")
        self.assertEqual(rules["changed_same_semantic_target"], "next_revision_same_generation")
        replay = self.fixtures["replay_fixture"]
        rev1 = datetime.fromisoformat(replay["revision_1"]["known_at"].replace("Z", "+00:00"))
        rev2 = datetime.fromisoformat(replay["revision_2"]["known_at"].replace("Z", "+00:00"))
        early = datetime.fromisoformat(replay["decision_early"]["decision_at"].replace("Z", "+00:00"))
        late = datetime.fromisoformat(replay["decision_late"]["decision_at"].replace("Z", "+00:00"))
        self.assertLessEqual(rev1, early)
        self.assertGreater(rev2, early)
        self.assertLessEqual(rev2, late)
        self.assertEqual(replay["decision_early"]["expected_value_sek_per_kwh"], 0.1816)
        self.assertEqual(replay["decision_late"]["expected_value_sek_per_kwh"], 0.1900)
        self.assertIn("known_at <= decision_at", self.doc)

    def test_active_site_is_not_producer_ownership(self):
        ownership = self.fixtures["ownership"]
        self.assertEqual(ownership["producer_scope_source"], "collection_enabled_site_elhandel_binding")
        self.assertFalse(ownership["active_site_id_is_ownership"])
        self.assertFalse(ownership["shared_credentials_may_define_ownership"])
        self.assertFalse(ownership["active_provider_namespace_may_define_ownership"])
        self.assertIn("`active_site_id` is UI/read context only", self.doc)

    def test_c1_schema_is_sufficient_without_migration(self):
        schema_fixture = self.fixtures["schema"]
        self.assertTrue(schema_fixture["external_input_frame_model_sufficient"])
        self.assertFalse(schema_fixture["schema_migration_required"])
        schema = (ROOT / "custom_components/elrakning/p0_storage_schema_v1.sql").read_text(encoding="utf-8")
        for token in (
            "source_generation_id TEXT NOT NULL",
            "semantic_key TEXT NOT NULL",
            "supersedes_frame_id TEXT",
            "published_at_us INTEGER",
            "fetched_at_us INTEGER",
            "known_at_us INTEGER NOT NULL",
            "captured_at_us INTEGER NOT NULL",
            "valid_from_us INTEGER",
            "valid_to_us INTEGER",
            "valid_at_us INTEGER NOT NULL",
        ):
            self.assertIn(token, schema)
        self.assertIn("No schema migration is required by C.4B", self.doc)

    def test_scope_is_design_and_tests_only(self):
        guards = self.fixtures["scope_guards"]
        self.assertTrue(all(value is False for value in guards.values()))
        self.assertIn("No C.4 production implementation is authorized", self.doc)


if __name__ == "__main__":
    unittest.main()
