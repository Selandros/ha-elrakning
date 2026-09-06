import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from tests._elrakning_test_bootstrap import install_elrakning_package_stub, install_homeassistant_stubs

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.canonical_storage import CanonicalStorage
from custom_components.elrakning.energy_history import (
    canonical_contributions,
    history_targets,
    long_term_contributions,
    merge_contributions,
)

UTC = timezone.utc


def _ledger(site, role, entity, generation, **extra):
    return {
        "site_id": site,
        "logical_role": role,
        "entity_id": entity,
        "generation_id": generation,
        **extra,
    }


class EnergyHistoryTests(unittest.TestCase):
    def test_history_targets_are_site_explicit_not_active_site(self):
        start = datetime(2026, 8, 30, tzinfo=UTC)
        end = start + timedelta(days=1)
        manager = SimpleNamespace(state={
            "active_site_id": "site-b",
            "ledger": [
                _ledger("site-a", "house.consumption", "sensor.a", "gen-a"),
                _ledger("site-b", "house.consumption", "sensor.b", "gen-b"),
            ],
        })
        targets = history_targets(manager, "site-a", start, end)
        self.assertEqual([(item["site_id"], item["generation_id"]) for item in targets], [("site-a", "gen-a")])

    def test_canonical_sums_parallel_solar_and_splits_signed_grid(self):
        start = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)
        end = start + timedelta(minutes=15)
        rows = [
            {"logical_role": "solar.production", "source_generation_id": "pv1", "interval_start": start,
             "interval_end": end, "value": 1200.0, "unit": "W", "quality_status": "good",
             "coverage_ratio": 1.0, "storage_class": "canonical"},
            {"logical_role": "solar.production", "source_generation_id": "pv2", "interval_start": start,
             "interval_end": end, "value": 800.0, "unit": "W", "quality_status": "good",
             "coverage_ratio": 1.0, "storage_class": "canonical"},
            {"logical_role": "grid.power/import", "source_generation_id": "grid", "interval_start": start,
             "interval_end": end, "value": -1500.0, "unit": "W", "quality_status": "good",
             "coverage_ratio": 1.0, "storage_class": "canonical"},
        ]
        ledger = {generation: _ledger("site-a", "solar.production" if generation.startswith("pv") else "grid.power/import", "sensor.x", generation)
                  for generation in ("pv1", "pv2", "grid")}
        series = merge_contributions(canonical_contributions(rows, ledger))
        self.assertEqual(series["solar"][0]["value_kw"], 2.0)
        self.assertEqual(series["import"][0]["value_kw"], 0.0)
        self.assertEqual(series["export"][0]["value_kw"], 1.5)
        self.assertEqual(series["solar"][0]["resolution_seconds"], 900)

    def test_canonical_interval_wins_over_overlapping_long_term_hour(self):
        start = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)
        canonical = [{
            "series": "consumption", "start": start, "end": start + timedelta(minutes=15),
            "value_kw": 2.0, "priority": 30, "source": "canonical", "generation_id": "gen",
            "quality_status": "good", "coverage_ratio": 1.0,
        }]
        long_term = [{
            "series": "consumption", "start": start, "end": start + timedelta(hours=1),
            "value_kw": 1.0, "priority": 20, "source": "home_assistant_long_term_statistics",
            "generation_id": "gen", "quality_status": "good", "coverage_ratio": None,
        }]
        series = merge_contributions(canonical + long_term)
        self.assertEqual(len(series["consumption"]), 1)
        self.assertEqual(series["consumption"][0]["source"], "canonical")
        self.assertEqual(series["consumption"][0]["value_kw"], 2.0)

    def test_long_term_keeps_hourly_mean_and_energy_counter_fallback(self):
        start = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
        targets = [
            _ledger("site-a", "house.consumption", "sensor.load", "load-gen"),
            _ledger("site-a", "grid.energy_import", "sensor.import", "import-gen"),
        ]
        metadata = {
            "sensor.load": (1, {"unit_of_measurement": "W"}),
            "sensor.import": (2, {"unit_of_measurement": "kWh"}),
        }
        statistics = {
            "sensor.load": [{"start": start.timestamp(), "mean": 2000.0}],
            "sensor.import": [{"start": start.timestamp(), "change": 1.25}],
        }
        series = merge_contributions(long_term_contributions(targets, metadata, statistics))
        self.assertEqual(series["consumption"][0]["value_kw"], 2.0)
        self.assertEqual(series["consumption"][0]["resolution_seconds"], 3600)
        self.assertEqual(series["import"][0]["value_kw"], 1.25)
        self.assertEqual(series["import"][0]["source"], "home_assistant_long_term_statistics_energy")

    def test_storage_history_is_site_scoped_and_uses_read_only_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = CanonicalStorage(Path(directory) / "canonical.sqlite")
            storage.open()
            start = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)
            for site, generation, value in (("site-a", "gen-a", 1000.0), ("site-b", "gen-b", 2000.0)):
                storage.ensure_source_generation({
                    "site_id": site,
                    "logical_role": "house.consumption",
                    "generation_id": generation,
                    "source_identity": {"identity_key": generation, "identity_strength": "strong"},
                }, start)
                storage.insert_observation({
                    "semantic_key": f"{site}|house.consumption|{generation}|{start.isoformat()}",
                    "site_id": site,
                    "logical_role": "house.consumption",
                    "source_generation_id": generation,
                    "interval_start": start,
                    "observed_at": start + timedelta(minutes=14),
                    "captured_at": start + timedelta(minutes=15),
                    "known_at": start + timedelta(minutes=15),
                    "classification": "measured",
                    "value": value,
                    "unit": "W",
                    "sign_convention": "positive_consumption",
                    "quality_status": "good",
                    "coverage_ratio": 1.0,
                    "gap_status": "none",
                })
            rows = storage.read_site_energy_history("site-a", start, start + timedelta(minutes=15))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source_generation_id"], "gen-a")
            self.assertEqual(rows[0]["value"], 1000.0)
            self.assertEqual(rows[0]["storage_class"], "canonical")
            storage.close()


if __name__ == "__main__":
    unittest.main()
