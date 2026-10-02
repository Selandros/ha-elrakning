import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub


install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.canonical_storage import CanonicalStorage


UTC = timezone.utc


def _target(site_id: str, generation_id: str) -> dict:
    return {
        "site_id": site_id,
        "logical_role": "grid.energy_import",
        "generation_id": generation_id,
        "source_identity": {"identity_key": f"{site_id}:{generation_id}", "identity_strength": "strong"},
        "source_resolution_kind": "native_bucket",
        "source_resolution_seconds": 900,
        "timezone_state": "verified",
    }


def _observation(site_id: str, generation_id: str, start: datetime, index: int) -> dict:
    interval_start = start + timedelta(minutes=15 * index)
    captured = interval_start + timedelta(hours=1)
    return {
        "semantic_key": f"{site_id}|grid.energy_import|{generation_id}|{interval_start.isoformat()}",
        "site_id": site_id,
        "logical_role": "grid.energy_import",
        "source_generation_id": generation_id,
        "interval_start": interval_start,
        "interval_end": interval_start + timedelta(minutes=15),
        "resolution_seconds": 900,
        "source_resolution_kind": "native_bucket",
        "source_resolution_seconds": 900,
        "observed_at": interval_start,
        "captured_at": captured,
        "fetched_at": captured,
        "known_at": captured,
        "value": float(index) / 1000,
        "unit": "kWh",
        "sign_convention": "positive_import_energy",
        "quality_status": "good",
        "coverage_ratio": 1.0,
        "gap_status": "none",
        "quality": {"padded": False},
        "provenance": {"provider": "test", "provider_actual": True, "padded": False},
    }


class CanonicalStorageConcurrencyTests(unittest.TestCase):
    def test_parallel_reads_and_writes_are_serialized_on_one_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = CanonicalStorage(Path(directory) / "canonical.sqlite")
            storage.open()
            site_id = "site-a"
            generation_id = "eon-generation"
            now = datetime(2026, 10, 1, tzinfo=UTC)
            storage.ensure_source_generation(_target(site_id, generation_id), now)
            observations = [_observation(site_id, generation_id, now, index) for index in range(24)]

            def write(item):
                return int(storage.insert_observation(item))

            def read(_):
                return storage.count_observations()

            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(write, item) for item in observations]
                futures.extend(executor.submit(read, index) for index in range(24))
                results = [future.result() for future in futures]

            self.assertEqual(sum(result for result in results[:24]), 24)
            self.assertEqual(storage.read_site_energy_history(site_id, now, now + timedelta(hours=6)).__len__(), 24)
            storage.close()

    def test_reentrant_storage_lock_preserves_nested_helper_access(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = CanonicalStorage(Path(directory) / "canonical.sqlite")
            storage.open()
            with storage.connection_lock():
                with storage.connection_lock():
                    self.assertEqual(storage.count_observations(), 0)
            storage.close()

    def test_revision_conflict_remains_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = CanonicalStorage(Path(directory) / "canonical.sqlite")
            storage.open()
            site_id = "site-a"
            generation_id = "eon-generation"
            start = datetime(2026, 10, 1, tzinfo=UTC)
            storage.ensure_source_generation(_target(site_id, generation_id), start)
            observation = _observation(site_id, generation_id, start, 0)
            self.assertEqual(storage.insert_historical_observations_atomic([observation]), 1)
            changed = dict(observation, value=9.999)
            with self.assertRaisesRegex(ValueError, "canonical_historical_revision_conflict"):
                storage.insert_historical_observations_atomic([changed])
            storage.close()


if __name__ == "__main__":
    unittest.main()
