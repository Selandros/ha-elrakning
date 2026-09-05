import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs/architecture/contracts/p0_data_contract_v1.contract.json"
FIXTURES_PATH = ROOT / "docs/architecture/contracts/p0_data_contract_v1.fixtures.json"
DESIGN_PATH = ROOT / "docs/architecture/P0_DATA_CONTRACT_V1.md"


class P0DataContractDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT_PATH.read_text())
        cls.fixtures = json.loads(FIXTURES_PATH.read_text())
        cls.design = DESIGN_PATH.read_text()

    def test_contract_identity_and_canonical_interval(self):
        self.assertEqual(self.contract["contract_id"], "elrakning.p0_data_contract")
        self.assertEqual(self.contract["contract_version"], 1)
        self.assertEqual(self.contract["timestamp_contract"]["canonical_timezone"], "UTC")
        self.assertEqual(self.contract["timestamp_contract"]["interval_alignment_seconds"], 900)
        self.assertEqual(self.contract["datasets"]["energy_observation"]["resolution_seconds"], 900)

    def test_required_roles_and_site_independent_collection(self):
        self.assertEqual(
            set(self.contract["logical_roles"]),
            {"house.consumption", "solar.production", "grid.power/import", "battery.power", "battery.soc"},
        )
        self.assertIsNone(self.contract["source_generation_contract"]["global_owner_site_id"])
        invariant_ids = {item["id"] for item in self.contract["invariants"]}
        self.assertIn("INV-SITE-001", invariant_ids)

    def test_fixture_suite_covers_accept_and_reject_contract_cases(self):
        cases = self.fixtures["cases"]
        self.assertGreaterEqual(len(cases), 30)
        self.assertTrue(any(case["expected"] == "accept" for case in cases))
        self.assertTrue(any(case["expected"] == "reject" for case in cases))
        invariant_ids = {item["id"] for item in self.contract["invariants"]}
        for case in cases:
            referenced = case.get("assert_invariants", []) + [case.get("reject_invariant")]
            self.assertTrue(all(item in invariant_ids for item in referenced if item))

    def test_design_is_storage_neutral_and_rejects_false_precision(self):
        self.assertRegex(self.design, r"known_at\s*<=\s*decision_at")
        self.assertIn("must never\nbe expanded into four equal 15-minute records", self.design)
        self.assertNotRegex(self.design.lower(), r"\b(sqlite|jsonl|postgres)\b")

    def test_fixture_ids_are_unique_and_well_formed(self):
        ids = [case["id"] for case in self.fixtures["cases"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(re.fullmatch(r"(?:F|N)\d{2}", item) for item in ids))


if __name__ == "__main__":
    unittest.main()
