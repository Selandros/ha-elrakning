import json
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).parents[1]
FIXTURE_PATH = ROOT / "docs/architecture/contracts/open_meteo_day_ahead_single_run_contract_v1.fixtures.json"
DATASET = "open_meteo.single_run_day_ahead_pv.v1"


def parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def classify(record, decision_at):
    if record.get("dataset") != DATASET:
        return "REJECT_DATASET"
    if not record.get("site_id") or not record.get("source_generation_id"):
        return "INSUFFICIENT_PROVENANCE"
    if not record.get("known_at"):
        return "INSUFFICIENT_PROVENANCE"
    return "VERIFIED_PRE_DECISION" if parse(record["known_at"]) <= decision_at else "VERIFIED_POST_DECISION"


class OpenMeteoSingleRunContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE_PATH.read_text())

    def test_fixture_contract_identity_and_cases(self):
        self.assertEqual(self.fixture["dataset"], DATASET)
        self.assertEqual(self.fixture["decision_rule"], "known_at <= decision_at")
        self.assertGreaterEqual(len(self.fixture["cases"]), 15)

    def test_known_at_is_not_run_initialization(self):
        record = {
            "dataset": DATASET,
            "site_id": "site-vik",
            "source_generation_id": "om-1",
            "run_initialization_at": "2026-09-11T00:00:00Z",
            "known_at": "2026-09-11T05:00:00Z",
        }
        self.assertEqual(classify(record, parse("2026-09-12T22:00:00Z")), "VERIFIED_PRE_DECISION")
        self.assertNotEqual(record["known_at"], record["run_initialization_at"])

    def test_acquisition_after_cutoff_is_post_decision(self):
        record = {
            "dataset": DATASET,
            "site_id": "site-vik",
            "source_generation_id": "om-1",
            "run_initialization_at": "2026-09-11T00:00:00Z",
            "known_at": "2026-09-12T23:00:00Z",
        }
        self.assertEqual(classify(record, parse("2026-09-12T22:00:00Z")), "VERIFIED_POST_DECISION")

    def test_wrong_datasets_fail_closed(self):
        for dataset in ("open_meteo.manager_forecast.v1", "open_meteo.evidence_previous_day1.v1"):
            record = {"dataset": dataset, "site_id": "site-vik", "source_generation_id": "om-1", "known_at": "2026-09-11T05:00:00Z"}
            self.assertEqual(classify(record, parse("2026-09-12T22:00:00Z")), "REJECT_DATASET")

    def test_missing_timing_or_generation_fails_closed(self):
        base = {"dataset": DATASET, "site_id": "site-vik", "known_at": "2026-09-11T05:00:00Z"}
        self.assertEqual(classify(base, parse("2026-09-12T22:00:00Z")), "INSUFFICIENT_PROVENANCE")
        base["source_generation_id"] = "om-1"
        base["known_at"] = None
        self.assertEqual(classify(base, parse("2026-09-12T22:00:00Z")), "INSUFFICIENT_PROVENANCE")

    def test_fixture_has_dst_and_coverage_cases(self):
        cases = {case["id"]: case for case in self.fixture["cases"]}
        self.assertEqual(cases["dst_23_hour_day"]["expected"], "ACCEPT_IF_COMPLETE")
        self.assertEqual(cases["dst_25_hour_day"]["expected"], "ACCEPT_IF_COMPLETE")
        self.assertEqual(cases["partial_target_day"]["expected"], "REJECT_COVERAGE")

    def test_decision_boundary_is_inclusive(self):
        record = {
            "dataset": DATASET,
            "site_id": "site-vik",
            "source_generation_id": "om-1",
            "known_at": "2026-09-12T22:00:00Z",
        }
        self.assertEqual(classify(record, parse("2026-09-12T22:00:00Z")), "VERIFIED_PRE_DECISION")


if __name__ == "__main__":
    unittest.main()
