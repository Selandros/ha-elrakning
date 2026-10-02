import asyncio
import json
import tempfile
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
from custom_components.elrakning.elnat.eon_manager import EonGridManager  # noqa: E402
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
        hass = types.SimpleNamespace(data={DOMAIN: {}})
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


if __name__ == "__main__":
    unittest.main()
