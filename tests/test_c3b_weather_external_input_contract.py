import hashlib
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs/architecture/C3B_WEATHER_EXTERNAL_INPUT_CONTRACT_V1.md"
FIXTURE_PATH = ROOT / "docs/architecture/contracts/c3b_weather_external_input_contract_v1.fixtures.json"


def _fingerprint(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _semantic_key(dataset, site_id, generation_id, role, target):
    return "|".join((dataset, site_id, generation_id, role, target))


class C3BWeatherContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = DOC_PATH.read_text(encoding="utf-8")
        cls.fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_current_and_forecast_are_separate_datasets_and_chains(self):
        datasets = {item["id"]: item for item in self.fixtures["datasets"]}
        self.assertEqual(datasets["smhi_current"]["dataset"], "smhi.current_weather.v1")
        self.assertEqual(datasets["smhi_hourly"]["dataset"], "smhi.hourly_forecast.v1")
        self.assertEqual(datasets["smhi_current"]["share_revision_chain_with"], [])
        self.assertEqual(datasets["smhi_hourly"]["share_revision_chain_with"], [])
        self.assertIn("They must never\nshare a semantic or revision chain", self.doc)

    def test_generation_identity_excludes_values_and_timestamps(self):
        base = {
            "provider_integration": "smhi",
            "config_entry_id": "entry-a",
            "weather_entity": "weather.smhi_home",
            "site_binding_identity": "binding-a",
            "request_contract": "hourly",
            "adapter_version": 1,
            "role_mapping": {"cloud_total": "sensor.cloud"},
        }
        volatile = {
            **base,
            "values": {"temperature": 13.6},
            "captured_at": "2026-09-13T10:00:00Z",
            "known_at": "2026-09-13T10:00:00Z",
        }
        self.assertEqual(_fingerprint(base), _fingerprint({k: v for k, v in volatile.items() if k in base}))
        self.assertEqual(self.fixtures["generation_excludes"][0], "values")
        self.assertIn("Binding/entity/config replacement", self.doc)

    def test_site_and_generation_are_in_semantic_identity(self):
        a = _semantic_key("smhi.hourly_forecast.v1", "site-a", "gen-a", "weather.forecast.hourly", "2026-09-13T15:00:00Z")
        b = _semantic_key("smhi.hourly_forecast.v1", "site-b", "gen-a", "weather.forecast.hourly", "2026-09-13T15:00:00Z")
        replaced = _semantic_key("smhi.hourly_forecast.v1", "site-a", "gen-b", "weather.forecast.hourly", "2026-09-13T15:00:00Z")
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, replaced)

    def test_target_is_in_key_but_values_and_timestamps_are_not(self):
        current = self.fixtures["semantic_key_examples"]["current"]
        hourly_frame = self.fixtures["semantic_key_examples"]["hourly_frame"]
        hourly_point_15 = self.fixtures["semantic_key_examples"]["hourly_point_15"]
        hourly_point_16 = self.fixtures["semantic_key_examples"]["hourly_point_16"]
        self.assertNotEqual(current, hourly_frame)
        self.assertNotEqual(hourly_point_15, hourly_point_16)
        self.assertEqual(
            _semantic_key(
                "smhi.hourly_forecast.v1", "site-a", "gen-a",
                "weather.forecast.hourly", "forecast_request_vintage",
            ),
            hourly_frame,
        )
        self.assertEqual(
            self.fixtures["semantic_key_excludes"],
            ["values", "captured_at", "fetched_at", "known_at", "revision"],
        )

    def test_decision_time_selects_only_known_forecast_revision(self):
        fixtures = self.fixtures["replay_vintage"]
        early = datetime.fromisoformat(fixtures["decision_early"]["decision_at"].replace("Z", "+00:00"))
        late = datetime.fromisoformat(fixtures["decision_late"]["decision_at"].replace("Z", "+00:00"))
        rev1 = datetime.fromisoformat(fixtures["revision_1"]["known_at"].replace("Z", "+00:00"))
        rev2 = datetime.fromisoformat(fixtures["revision_2"]["known_at"].replace("Z", "+00:00"))
        self.assertLessEqual(rev1, early)
        self.assertGreater(rev2, early)
        self.assertLessEqual(rev2, late)
        self.assertEqual(fixtures["decision_early"]["expected_value"], 10.0)
        self.assertEqual(fixtures["decision_late"]["expected_value"], 20.0)
        self.assertIn("known_at <= decision_at", self.doc)

    def test_current_has_no_fabricated_valid_at_and_forecast_has_valid_at(self):
        datasets = {item["id"]: item for item in self.fixtures["datasets"]}
        self.assertIsNone(datasets["smhi_current"]["valid_at"])
        self.assertEqual(datasets["smhi_hourly"]["valid_at"], "forecast_item.datetime_normalized_utc")
        self.assertIsNone(self.fixtures["timestamp_rules"]["current_valid_at"])
        self.assertEqual(self.fixtures["timestamp_rules"]["forecast_published_at"], None)

    def test_schema_time_invariants_match_the_contract(self):
        schema = (ROOT / "custom_components/elrakning/p0_storage_schema_v1.sql").read_text(encoding="utf-8")
        self.assertIn("CHECK (known_at_us >= captured_at_us)", schema)
        self.assertIn("CHECK (fetched_at_us IS NULL OR known_at_us >= fetched_at_us)", schema)
        self.assertIn("same_normalized_payload", self.fixtures["revision_rules"])

    def test_revision_rules_are_explicit_for_both_dataset_types(self):
        rules = self.fixtures["revision_rules"]
        self.assertEqual(rules["same_normalized_payload"], "deduplicate")
        self.assertEqual(rules["changed_current_payload"], "next_revision_same_generation")
        self.assertEqual(rules["changed_forecast_payload_same_target"], "next_revision_same_generation")
        self.assertEqual(rules["new_generation"], "revision_1_without_cross_generation_supersedes")
        self.assertIn("An unchanged normalized current payload deduplicates", self.doc)
        self.assertIn("An identical response\ndeduplicates", self.doc)

    def test_fail_closed_site_and_timestamp_rules(self):
        fiskvik = self.fixtures["site_fixtures"]["fiskvik"]
        self.assertFalse(fiskvik["weather_binding"])
        self.assertEqual(fiskvik["expected_weather_frames"], 0)
        self.assertEqual(self.fixtures["timestamp_rules"]["forecast_naive_datetime"], "reject_quality_gap")
        for phrase in (
            "No binding means no collection target, no service call and no weather frame.",
            "no interpolation, clamping, zero-fill or synthetic hourly points",
            "published_at = null",
        ):
            self.assertIn(phrase, self.doc)

    def test_non_regression_and_no_runtime_writes_are_locked(self):
        non_regression = self.fixtures["non_regression"]
        self.assertTrue(non_regression["solar_shadow_store_untouched"])
        self.assertTrue(non_regression["solar_evidence_store_untouched"])
        self.assertTrue(non_regression["no_backfill"])
        self.assertTrue(non_regression["no_producer_in_scope"])
        self.assertIn("No C.3 production implementation is authorized", self.doc)

    def test_offset_aware_forecast_timestamp_normalizes_to_utc(self):
        value = datetime.fromisoformat("2026-10-25T02:00:00+02:00")
        normalized = value.astimezone(timezone.utc)
        self.assertEqual(normalized.isoformat(), "2026-10-25T00:00:00+00:00")
        self.assertTrue(self.fixtures["timestamp_rules"]["preserve_source_offset"])
        self.assertEqual(self.fixtures["timestamp_rules"]["normalize_valid_at_to"], "UTC")


if __name__ == "__main__":
    unittest.main()
