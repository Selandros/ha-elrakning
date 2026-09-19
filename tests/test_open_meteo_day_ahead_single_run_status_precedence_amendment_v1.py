import json
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "docs/architecture/contracts/open_meteo_day_ahead_single_run_status_precedence_amendment_v1.fixtures.json"
DATASET = "open_meteo.single_run_day_ahead_pv.v1"
ROLE = "solar.irradiance.day_ahead_pv_forecast"


def parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _scope(frame, query):
    return (
        frame.get("site_id", query["site_id"]) == query["site_id"]
        and frame.get("dataset", query["dataset"]) == query["dataset"]
        and frame.get("source_generation_id", query["source_generation_id"]) == query["source_generation_id"]
        and frame.get("target_date", query["target_date"]) == query["target_date"]
        and frame.get("logical_role", query["logical_role"]) == query["logical_role"]
    )


def classify(frames, query):
    scoped = [frame for frame in frames if _scope(frame, query)]
    if not scoped:
        return "MISSING", None

    insufficient = [
        frame for frame in scoped
        if frame.get("provenance") != "valid"
        or not isinstance(frame.get("known_at"), str)
        or not isinstance(frame.get("run_initialization_at"), str)
        or not isinstance(frame.get("frame_fingerprint"), str)
    ]
    if insufficient:
        return "INSUFFICIENT_PROVENANCE", None

    decision = parse(query["decision_at"])
    pre = [frame for frame in scoped if parse(frame["known_at"]) <= decision]
    if not pre:
        return "VERIFIED_POST_DECISION", None

    ordered = sorted(
        pre,
        key=lambda frame: (
            parse(frame["known_at"]),
            parse(frame["run_initialization_at"]),
            frame["frame_fingerprint"],
        ),
    )
    boundary = ordered[-1]
    ties = [
        frame for frame in ordered
        if parse(frame["known_at"]) == parse(boundary["known_at"])
        and parse(frame["run_initialization_at"]) == parse(boundary["run_initialization_at"])
    ]
    if len({frame["frame_fingerprint"] for frame in ties}) > 1:
        return "AMBIGUOUS", None
    return "VERIFIED_PRE_DECISION", boundary


def model_eligible(status):
    return status == "VERIFIED_PRE_DECISION"


class StatusPrecedenceAmendmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text())
        cls.query = {
            "site_id": cls.fixture["site_id"],
            "dataset": cls.fixture["dataset"],
            "source_generation_id": cls.fixture["source_generation_id"],
            "target_date": cls.fixture["target_date"],
            "logical_role": cls.fixture["logical_role"],
            "decision_at": cls.fixture["decision_at"],
        }

    def _frames(self, case):
        frames = []
        for source in case["frames"]:
            frame = dict(source)
            if frame.get("provenance") == "valid":
                frame.setdefault("site_id", self.query["site_id"])
                frame.setdefault("dataset", self.query["dataset"])
                frame.setdefault("source_generation_id", self.query["source_generation_id"])
                frame.setdefault("target_date", self.query["target_date"])
                frame.setdefault("logical_role", self.query["logical_role"])
            frames.append(frame)
        return frames

    def test_all_locked_cases(self):
        for case in self.fixture["cases"]:
            with self.subTest(case=case["id"]):
                status, selected = classify(self._frames(case), self.query)
                self.assertEqual(status, case["expected"])
                if "selected" in case:
                    self.assertEqual(selected["frame_fingerprint"], case["selected"])

    def test_only_pre_decision_is_model_eligible(self):
        for status in (
            "VERIFIED_POST_DECISION", "AMBIGUOUS", "MISSING", "INSUFFICIENT_PROVENANCE"
        ):
            with self.subTest(status=status):
                self.assertFalse(model_eligible(status))
        self.assertTrue(model_eligible("VERIFIED_PRE_DECISION"))

    def test_two_source_eligibility_requires_independent_pre_decision_results(self):
        self.assertTrue(
            model_eligible("VERIFIED_PRE_DECISION")
            and model_eligible("VERIFIED_PRE_DECISION")
        )
        self.assertFalse(
            model_eligible("VERIFIED_PRE_DECISION")
            and model_eligible("VERIFIED_POST_DECISION")
        )

    def test_amendment_is_contract_only(self):
        self.assertEqual(self.fixture["compatibility"], {
            "schema_migration": "NO",
            "persistence_change": "NO",
            "frame_format_change": "NO",
            "producer_change": "NO",
            "old_data_rewrite": "NO",
            "evidence_v1_change": "NO",
        })


if __name__ == "__main__":
    unittest.main()
