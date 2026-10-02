import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub


install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.canonical_storage import CanonicalStorage
from custom_components.elrakning.replay_runtime import _observation_known_at, _observation_observed_at


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
    def test_replay_reads_and_reconciled_reads_share_one_connection_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = CanonicalStorage(Path(directory) / "canonical.sqlite")
            storage.open()
            site_id = "site-a"
            generation_id = "eon-generation"
            start = datetime(2026, 10, 1, tzinfo=UTC)
            storage.ensure_source_generation(_target(site_id, generation_id), start)
            observation = _observation(site_id, generation_id, start, 0)
            storage.insert_observation(observation)
            row = {"site_id": site_id, "logical_role": "grid.energy_import", "source_generation_id": generation_id, "interval_start": start}
            real_connection = storage.connection
            active = 0
            maximum = 0
            state_lock = threading.Lock()

            class TrackingConnection:
                def execute(self, *args, **kwargs):
                    nonlocal active, maximum
                    with state_lock:
                        active += 1
                        maximum = max(maximum, active)
                    try:
                        time.sleep(0.001)
                        return real_connection.execute(*args, **kwargs)
                    finally:
                        with state_lock:
                            active -= 1

                def __getattr__(self, name):
                    return getattr(real_connection, name)

            storage.connection = TrackingConnection()
            decision_at = start + timedelta(days=2)

            def replay_read(index):
                return _observation_known_at(storage, row, decision_at) if index % 2 == 0 else _observation_observed_at(storage, row, decision_at)

            def reconciled_read(_):
                return storage.read_reconciled_grid_import(site_id, start, start + timedelta(days=1))

            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(replay_read, index) for index in range(40)]
                futures.extend(executor.submit(reconciled_read, index) for index in range(40))
                [future.result() for future in futures]

            self.assertEqual(maximum, 1)
            storage.close()

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

    def test_separate_storage_instances_share_one_path_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canonical.sqlite"
            first = CanonicalStorage(path)
            second = CanonicalStorage(path)
            self.assertIs(first.connection_lock(), second.connection_lock())
            first.open()
            second.open()
            try:
                self.assertEqual(first.integrity_check(), "ok")
                self.assertEqual(second.integrity_check(), "ok")
            finally:
                second.close()
                first.close()

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
