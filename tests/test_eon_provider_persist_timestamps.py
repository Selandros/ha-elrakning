import asyncio
import json
import threading
import tempfile
import time
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)


install_homeassistant_stubs()
install_elrakning_package_stub()
install_optional_dependency_stubs()

from custom_components.elrakning.canonical_storage import CanonicalStorage  # noqa: E402
from custom_components.elrakning.const import DOMAIN  # noqa: E402
from custom_components.elrakning.elnat.eon_manager import (  # noqa: E402
    EonGridManager,
    _persist_cached_historical_observations,
)
from custom_components.elrakning.elnat.eon_models import facility_identity  # noqa: E402
import custom_components.elrakning.grid_reconciliation  # noqa: E402,F401


class _SiteManager:
    def __init__(self, site_id, binding):
        self.state = {
            "site_configs": {
                site_id: {"collection_enabled": True, "bindings": {"grid": binding}},
            },
        }


class EonProviderPersistTimestampTests(unittest.TestCase):
    def test_cached_recovery_isolates_immutable_conflicts(self):
        class Storage:
            def __init__(self):
                self.calls = []

            def insert_historical_observations_atomic(self, observations):
                self.calls.append(len(observations))
                if len(observations) > 1 or observations[0].get("conflict"):
                    raise ValueError("canonical_historical_revision_conflict")
                return 1

        storage = Storage()
        self.assertEqual(
            _persist_cached_historical_observations(storage, [{"conflict": True}, {"conflict": False}]),
            1,
        )
        self.assertEqual(storage.calls, [2, 1, 1])

    def test_persisted_iso_timestamps_are_normalized_before_canonical_insert(self):
        site_id = "site-a"
        binding = {"provider": "eon", "config_entry_id": "entry-a", "facility": {"installation_identifier": "install-a"}}
        state = {
            "facility": {"installation_identifier": "install-a", "point_of_delivery_number": "pod-a"},
            "backfill_transfer": [{
                "date": "2026-10-01",
                "resolution": "QUARTER_HOUR",
                "captured_at": "2026-10-02T11:56:13.777384+00:00",
                "known_at": "2026-10-02T11:56:13.777384+00:00",
                "parsed": {
                    "status": "ok",
                    "actual_points": [{
                        "timestamp": "2026-10-01T00:00:00+00:00",
                        "consumption_kwh": 0.25,
                        "padded": False,
                    }],
                },
            }],
        }
        class Hass:
            def __init__(self):
                self.data = {DOMAIN: {}}

            async def async_add_executor_job(self, function, *args):
                return await asyncio.to_thread(function, *args)

        hass = Hass()
        manager = object.__new__(EonGridManager)
        manager.hass = hass
        manager.entry = types.SimpleNamespace(entry_id="entry-a")
        manager.state = state
        manager.facility_states = {}
        hass.data[DOMAIN]["site_identity_manager"] = _SiteManager(site_id, binding)

        with tempfile.TemporaryDirectory() as directory:
            storage = CanonicalStorage(Path(directory) / "canonical.sqlite")
            storage.open()
            hass.data[DOMAIN]["canonical_collector"] = types.SimpleNamespace(storage=storage)
            identity = facility_identity(state["facility"])
            asyncio.run(manager._async_persist_provider_imports({identity: state}))
            rows = storage.read_site_energy_history(
                site_id,
                datetime(2026, 10, 1, tzinfo=timezone.utc),
                datetime(2026, 10, 2, tzinfo=timezone.utc),
            )
            storage.close()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["value"], 0.25)
        self.assertEqual(rows[0]["unit"], "kWh")

    def _manager_for_async_persist_test(self, site_configs):
        class Hass:
            def __init__(self):
                self.data = {DOMAIN: {}}

            async def async_add_executor_job(self, function, *args):
                return await asyncio.to_thread(function, *args)

        hass = Hass()
        manager = object.__new__(EonGridManager)
        manager.hass = hass
        manager.entry = types.SimpleNamespace(entry_id="entry-a")
        hass.data[DOMAIN]["site_identity_manager"] = types.SimpleNamespace(
            state={"site_configs": site_configs}
        )
        hass.data[DOMAIN]["canonical_collector"] = types.SimpleNamespace(storage=object())
        return manager

    @staticmethod
    def _bound_config(site_id, entry_id, installation_id):
        return {
            "collection_enabled": True,
            "bindings": {
                "grid": {
                    "provider": "eon",
                    "config_entry_id": entry_id,
                    "facility": {"installation_identifier": installation_id},
                },
            },
        }

    @staticmethod
    def _state(installation_id):
        return {"facility": {"installation_identifier": installation_id}}

    def test_provider_persistence_runs_off_event_loop(self):
        site_id = "site-a"
        state = self._state("install-a")
        manager = self._manager_for_async_persist_test({site_id: self._bound_config(site_id, "entry-a", "install-a")})
        started = threading.Event()
        release = threading.Event()
        calls = []

        def blocking_persist(storage, work_items, captured_at):
            calls.append([item["site_id"] for item in work_items])
            started.set()
            release.wait(1)

        manager._persist_provider_imports_sync = blocking_persist

        async def scenario():
            task = asyncio.create_task(manager._async_persist_provider_imports({"installation:install-a": state}))
            await asyncio.wait_for(asyncio.to_thread(started.wait), 1)
            loop_probe = asyncio.Event()
            asyncio.get_running_loop().call_soon(loop_probe.set)
            await asyncio.wait_for(loop_probe.wait(), 0.5)
            release.set()
            await task

        asyncio.run(scenario())
        self.assertEqual(calls, [[site_id]])

    def test_provider_persistence_remains_single_flight_and_site_scoped(self):
        configs = {
            "site-a": self._bound_config("site-a", "entry-a", "install-a"),
            "site-b": self._bound_config("site-b", "entry-b", "install-b"),
        }
        manager = self._manager_for_async_persist_test(configs)
        states = {
            "installation:install-a": self._state("install-a"),
            "installation:install-b": self._state("install-b"),
        }
        active = 0
        maximum = 0
        calls = []

        def serialized_persist(storage, work_items, captured_at):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            calls.append([item["site_id"] for item in work_items])
            time.sleep(0.02)
            active -= 1

        manager._persist_provider_imports_sync = serialized_persist

        async def scenario():
            await asyncio.gather(
                manager._async_persist_provider_imports(states),
                manager._async_persist_provider_imports(states),
            )

        asyncio.run(scenario())
        self.assertEqual(maximum, 1)
        self.assertEqual(calls, [["site-a"], ["site-a"]])


if __name__ == "__main__":
    unittest.main()
