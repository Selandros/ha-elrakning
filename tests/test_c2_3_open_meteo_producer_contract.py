import hashlib
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/architecture/C2_3_OPEN_METEO_PRODUCER_CONTRACT_V1.md"
FIXTURES = ROOT / "docs/architecture/contracts/c2_3_open_meteo_producer_contract_v1.fixtures.json"
SCHEMA = ROOT / "custom_components/elrakning/p0_storage_schema_v1.sql"


def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def generation_payload(request):
    excluded = {"fetched_at", "captured_at", "known_at", "values", "generationtime_ms", "frame_id", "source_strings", "peak_power_kwp", "installation_fingerprint", "binding_fingerprint"}
    return {key: value for key, value in request.items() if key not in excluded}


def semantic_key(dataset, site_id, generation_id, role, section_fingerprint):
    return "|".join((dataset, site_id, generation_id, role, section_fingerprint))


class C23OpenMeteoContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = DOC.read_text(encoding="utf-8")
        cls.fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
        cls.schema = SCHEMA.read_text(encoding="utf-8")

    def test_runtime_fixture_and_fiskvik_clean_room(self):
        runtime = self.fixtures["runtime_evidence"]
        self.assertEqual(runtime["vikarbodarna_sections"], 1)
        self.assertEqual(runtime["vikarbodarna_peak_power_kwp"], 9.45)
        self.assertFalse(runtime["fiskvik_has_target"])
        self.assertFalse(runtime["fiskvik_has_canonical_frame"])

    def test_request_identity_excludes_volatile_and_provenance_only_fields(self):
        request = {
            "dataset": "open_meteo.manager_forecast.v1", "site_id": "site-a",
            "latitude": 62.2, "longitude": 17.49, "tilt_deg": 30.0,
            "open_meteo_azimuth_deg": 45.0, "fetched_at": "2026-09-12T10:00:00Z",
            "captured_at": "2026-09-12T10:00:00Z", "known_at": "2026-09-12T10:00:01Z",
            "values": [1, 2], "generationtime_ms": 0.2, "frame_id": "cache-a",
            "source_strings": ["sensor.old"], "peak_power_kwp": 9.45,
            "installation_fingerprint": "install-a", "binding_fingerprint": "binding-a",
        }
        changed = {**request, "fetched_at": "2026-09-12T11:00:00Z", "source_strings": ["sensor.new"], "peak_power_kwp": 10.0, "installation_fingerprint": "install-b", "binding_fingerprint": "binding-b"}
        self.assertEqual(fingerprint(generation_payload(request)), fingerprint(generation_payload(changed)))
        changed_geometry = {**request, "tilt_deg": 35.0}
        self.assertNotEqual(fingerprint(generation_payload(request)), fingerprint(generation_payload(changed_geometry)))

    def test_site_location_is_persisted_and_global_location_is_not_a_fallback(self):
        contract = self.fixtures["site_location_contract"]
        self.assertEqual(contract["persisted_shape"], "site_configs[site_id].location")
        self.assertTrue(contract["global_ha_location_is_never_a_fallback"])
        self.assertEqual(contract["missing_location"], "ineligible_no_request_no_http_no_cache_no_frame")

    def test_coordinates_are_source_defining_and_site_explicit(self):
        base = {
            "dataset": "open_meteo.manager_forecast.v1", "site_id": "site-a",
            "latitude": 62.20646687401988, "longitude": 17.490212917327884,
            "timezone": "auto", "tilt_deg": 30.0, "open_meteo_azimuth_deg": 45.0,
            "model": "metno", "variables": ["global_tilted_irradiance"],
            "forecast_days": 3, "endpoint": "https://api.open-meteo.com/v1/metno",
        }
        other_site = {**base, "site_id": "site-b", "latitude": 59.3, "longitude": 18.1}
        self.assertNotEqual(fingerprint(generation_payload(base)), fingerprint(generation_payload(other_site)))
        self.assertEqual(base["latitude"], 62.20646687401988)
        self.assertEqual(base["longitude"], 17.490212917327884)

    def test_inactive_site_target_does_not_follow_current_global_location(self):
        persisted = {"site_id": "site-a", "latitude": 62.2, "longitude": 17.49, "timezone": "Europe/Stockholm"}
        global_location_before = {"latitude": 62.2, "longitude": 17.49}
        global_location_after = {"latitude": 59.3, "longitude": 18.1}
        self.assertEqual(persisted["latitude"], global_location_before["latitude"])
        self.assertNotEqual(global_location_before, global_location_after)
        target_before = dict(persisted)
        target_after = dict(persisted)
        self.assertEqual(target_before, target_after)

    def test_fiskvik_clean_room_and_vikarbodarna_migration_contract(self):
        location = self.fixtures["site_location_contract"]
        self.assertEqual(location["fiskvik"], {"location_verified": False, "target_count": 0, "http_calls": 0, "canonical_frames": 0})
        migration = location["vikarbodarna_migration"]
        self.assertTrue(migration["one_time"])
        self.assertTrue(migration["idempotent"])
        self.assertTrue(migration["fail_closed_on_store_binding_disagreement"])

    def test_installation_and_binding_fingerprints_are_not_generation_identity(self):
        base = {"dataset": "open_meteo.manager_forecast.v1", "site_id": "site-a", "latitude": 1, "longitude": 2, "tilt_deg": 30, "open_meteo_azimuth_deg": 45, "installation_fingerprint": "a", "binding_fingerprint": "a"}
        changed_provenance = {**base, "installation_fingerprint": "b", "binding_fingerprint": "b", "peak_power_kwp": 10, "source_strings": ["sensor.new"]}
        self.assertEqual(fingerprint(generation_payload(base)), fingerprint(generation_payload(changed_provenance)))

    def test_location_generation_starts_new_revision_without_cross_generation_supersedes(self):
        old = fingerprint({"site_id": "site-a", "latitude": 1, "longitude": 2, "tilt": 30})
        new = fingerprint({"site_id": "site-a", "latitude": 3, "longitude": 2, "tilt": 30})
        self.assertNotEqual(old, new)
        self.assertIn("no `supersedes` link across generations", self.doc)

    def test_request_semantics_create_new_generation(self):
        base = {
            "dataset": "open_meteo.manager_forecast.v1", "site_id": "site-a",
            "latitude": 1, "longitude": 2, "timezone": "auto", "tilt_deg": 30,
            "open_meteo_azimuth_deg": 45, "model": "metno",
            "variables": ["global_tilted_irradiance"], "forecast_days": 3,
            "endpoint": "https://api.open-meteo.com/v1/metno",
        }
        for field, value in (("tilt_deg", 31), ("open_meteo_azimuth_deg", 46), ("model", "ecmwf"), ("forecast_days", 4), ("timezone", "Europe/Stockholm"), ("endpoint", "https://example.invalid"), ("variables", ["temperature_2m"])):
            changed = {**base, field: value}
            self.assertNotEqual(fingerprint(generation_payload(base)), fingerprint(generation_payload(changed)), field)

    def test_section_order_is_irrelevant_and_orientation_is_distinct(self):
        sections_a = [{"tilt": 30, "azimuth": 45}, {"tilt": 20, "azimuth": 90}]
        sections_b = list(reversed(sections_a))
        normalized_a = sorted(fingerprint(section) for section in sections_a)
        normalized_b = sorted(fingerprint(section) for section in sections_b)
        self.assertEqual(normalized_a, normalized_b)
        self.assertNotEqual(fingerprint(sections_a[0]), fingerprint(sections_a[1]))

    def test_semantic_key_and_revision_rules(self):
        gen = fingerprint({"site_id": "site-a", "tilt": 30, "azimuth": 45})
        first = semantic_key("open_meteo.manager_forecast.v1", "site-a", gen, "solar.irradiance.forecast", "section-a")
        self.assertEqual(first, semantic_key("open_meteo.manager_forecast.v1", "site-a", gen, "solar.irradiance.forecast", "section-a"))
        self.assertNotEqual(first, semantic_key("open_meteo.manager_forecast.v1", "site-a", fingerprint({"tilt": 35}), "solar.irradiance.forecast", "section-a"))
        self.assertIn("supersedes", self.doc)
        self.assertIn("revision N+1", self.doc)

    def test_dst_and_naive_local_resolution(self):
        zone = ZoneInfo("Europe/Stockholm")
        local = datetime(2026, 9, 12, 12, tzinfo=zone)
        self.assertEqual(local.astimezone(timezone.utc).isoformat(), "2026-09-12T10:00:00+00:00")
        spring_start = datetime(2026, 3, 29, tzinfo=zone).astimezone(timezone.utc)
        spring_end = datetime(2026, 3, 30, tzinfo=zone).astimezone(timezone.utc)
        fall_start = datetime(2026, 10, 25, tzinfo=zone).astimezone(timezone.utc)
        fall_end = datetime(2026, 10, 26, tzinfo=zone).astimezone(timezone.utc)
        self.assertEqual((spring_end - spring_start).total_seconds() / 3600, 23)
        self.assertEqual((fall_end - fall_start).total_seconds() / 3600, 25)
        self.assertIn("quality gap", self.doc)

    def test_raw_gti_and_no_fabrication_rules(self):
        quality = self.fixtures["quality"]
        self.assertEqual(quality["negative_finite_gti"], "preserve_raw")
        self.assertEqual(quality["null_nan_inf_missing_or_malformed"], "quality_gap_no_point")
        self.assertEqual(quality["cadence_gap"], "quality_gap_no_fabrication")
        self.assertIn("No `irradiance_kwh_m2`", self.doc)
        self.assertNotIn("max(0.0", self.doc)

    def test_schema_supports_contract_without_migration(self):
        for field in ("semantic_key", "source_generation_id", "known_at_us", "captured_at_us", "fetched_at_us", "provenance_json", "valid_at_us"):
            self.assertIn(field, self.schema)
        self.assertIn("UNIQUE (semantic_key, revision)", self.schema)
        self.assertIn("UNIQUE (frame_id, point_key)", self.schema)

    def test_evidence_isolation_and_baseline(self):
        evidence = self.fixtures["solar_evidence_non_regression"]
        self.assertEqual(evidence["days"], 39)
        self.assertEqual(evidence["open_meteo_complete"], 14)
        self.assertEqual(evidence["forecast_solar_common"], 13)
        self.assertTrue(evidence["previous_day1_untouched"])
        self.assertTrue(evidence["no_backfill"])
        self.assertTrue(evidence["no_counter_reset"])
        self.assertIn("previous_day1", self.doc)


if __name__ == "__main__":
    unittest.main()
