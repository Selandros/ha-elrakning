import hashlib
import json
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs/architecture/C2_1_EXTERNAL_INPUT_CONTRACT_V1.md"
FIXTURE_PATH = ROOT / "docs/architecture/contracts/c2_1_external_input_contract_v1.fixtures.json"
SCHEMA_PATH = ROOT / "custom_components/elrakning/p0_storage_schema_v1.sql"


def _canonical_fingerprint(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _generation_identity(payload):
    excluded = {"captured_at", "fetched_at", "known_at", "value", "values", "evidence_counters"}
    return _canonical_fingerprint({key: value for key, value in payload.items() if key not in excluded})


def _semantic_key(dataset, site_id, generation_id, role, target):
    return "|".join((dataset, site_id, generation_id, role, target))


class C21ExternalInputContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = DOC_PATH.read_text(encoding="utf-8")
        cls.fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.schema = SCHEMA_PATH.read_text(encoding="utf-8")

    def test_matrix_keeps_evidence_contracts_distinct(self):
        matrix = {item["id"]: item for item in self.fixtures["source_matrix"]}
        self.assertEqual(matrix["forecast_solar_observed"]["dataset"], "forecast_solar.observed_facts.v1")
        self.assertEqual(matrix["forecast_solar_evidence_day_ahead"]["dataset"], "forecast_solar.observed_facts.v1")
        self.assertEqual(matrix["open_meteo_manager"]["dataset"], "open_meteo.manager_forecast.v1")
        self.assertEqual(matrix["open_meteo_evidence_previous_day1"]["dataset"], "open_meteo.evidence_previous_day1.v1")
        self.assertEqual(matrix["open_meteo_evidence_previous_day1"]["share_revision_chain"], "never_with_manager")
        self.assertIn("canonical observation != evidence frozen baseline", self.doc.lower())

    def test_forecast_roles_are_explicit_and_unsafe_roles_fail_closed(self):
        roles = {item["role"]: item for item in self.fixtures["forecast_solar_roles"]}
        self.assertEqual(roles["today_kwh"]["target"], "local_calendar_day")
        self.assertTrue(roles["remaining_today_kwh"]["capture_relative"])
        for role in ("this_hour_kwh", "next_hour_kwh", "power_next_hour_kw", "power_next_12_hours_kw", "power_next_24_hours_kw"):
            self.assertEqual(roles[role]["status"], "unknown_unsafe")
        self.assertIn("synthetic hourly points", self.doc.lower())

    def test_generation_and_semantic_identity_exclude_knowledge_times(self):
        base = {"provider": "forecast_solar", "config_entry_id": "entry-a", "site_id": "site-a", "role_map": {"today_kwh": "sensor.a"}, "contract_version": 1, "adapter_version": 1}
        with_volatile = {**base, "captured_at": "2026-09-06T10:00:00Z", "known_at": "2026-09-06T10:00:01Z", "value": 18.4}
        self.assertEqual(_generation_identity(base), _generation_identity(with_volatile))
        self.assertEqual(self.fixtures["generation_excludes"], ["captured_at", "fetched_at", "known_at", "values", "evidence_counters"])
        self.assertEqual(self.fixtures["semantic_key_excludes"], ["captured_at", "fetched_at", "known_at", "value", "revision"])
        self.assertRegex(self.doc, r"UNIQUE\(semantic_key, revision\)")
        self.assertIn("new generation starts revision 1", self.doc)

    def test_revisions_share_target_identity_but_generations_do_not(self):
        first = _semantic_key("forecast_solar.observed_facts.v1", "site-a", "gen-1", "today_kwh", "2026-09-06")
        second = _semantic_key("forecast_solar.observed_facts.v1", "site-a", "gen-1", "today_kwh", "2026-09-06")
        replaced = _semantic_key("forecast_solar.observed_facts.v1", "site-a", "gen-2", "today_kwh", "2026-09-06")
        self.assertEqual(first, second)
        self.assertNotEqual(first, replaced)

    def test_local_day_dst_boundaries_are_real_utc_intervals(self):
        zone = ZoneInfo("Europe/Stockholm")
        spring_start = datetime(2026, 3, 29, tzinfo=zone)
        spring_end = datetime(2026, 3, 30, tzinfo=zone)
        fall_start = datetime(2026, 10, 25, tzinfo=zone)
        fall_end = datetime(2026, 10, 26, tzinfo=zone)
        spring_hours = (spring_end.astimezone(timezone.utc) - spring_start.astimezone(timezone.utc)).total_seconds() / 3600
        fall_hours = (fall_end.astimezone(timezone.utc) - fall_start.astimezone(timezone.utc)).total_seconds() / 3600
        self.assertEqual(spring_hours, 23)
        self.assertEqual(fall_hours, 25)

    def test_aggregate_roles_are_not_expanded_and_site_context_is_explicit(self):
        roles = {item["role"]: item for item in self.fixtures["forecast_solar_roles"]}
        self.assertEqual(roles["power_next_12_hours_kw"]["status"], "unknown_unsafe")
        self.assertEqual(roles["power_next_24_hours_kw"]["status"], "unknown_unsafe")
        site_a = _semantic_key("open_meteo.manager_forecast.v1", "site-a", "gen-a", "solar.irradiance.forecast", "2026-09-06T12:00:00Z")
        site_b = _semantic_key("open_meteo.manager_forecast.v1", "site-b", "gen-b", "solar.irradiance.forecast", "2026-09-06T12:00:00Z")
        self.assertNotEqual(site_a, site_b)

    def test_open_meteo_request_contracts_are_not_mergeable(self):
        manager = self.fixtures["open_meteo"]["manager"]
        evidence = self.fixtures["open_meteo"]["evidence"]
        self.assertNotEqual(manager["endpoint"], evidence["endpoint"])
        self.assertNotEqual(manager["variables"], evidence["variables"])
        self.assertNotEqual(manager["timezone"], evidence["timezone"])
        self.assertNotEqual(manager["dataset"], evidence["dataset"])
        self.assertEqual(manager["forecast_days"], 3)
        self.assertTrue(evidence["previous_day1"])

    def test_c1_schema_contains_required_frame_and_point_contract(self):
        for field in ("semantic_key", "source_generation_id", "known_at_us", "captured_at_us", "fetched_at_us", "valid_from_us", "valid_to_us", "provenance_json"):
            self.assertIn(field, self.schema)
        self.assertIn("valid_at_us", self.schema)
        self.assertIn("UNIQUE (semantic_key, revision)", self.schema)
        self.assertIn("UNIQUE (frame_id, point_key)", self.schema)
        self.assertIn("known_at_us >= captured_at_us", self.schema)

    def test_dst_and_non_regression_requirements_are_locked(self):
        self.assertIn("23/24/25 hours", self.doc)
        self.assertIn("`solar_evidence` Store, evidence-v1 qualification", self.doc)
        self.assertEqual(self.fixtures["non_regression"]["minimum_open_meteo_count"], 8)
        self.assertEqual(self.fixtures["non_regression"]["minimum_forecast_solar_common_count"], 7)
        self.assertTrue(self.fixtures["non_regression"]["no_backfill"])
        self.assertTrue(self.fixtures["non_regression"]["no_counter_reset"])


if __name__ == "__main__":
    unittest.main()
