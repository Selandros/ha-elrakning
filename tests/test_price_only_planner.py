import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from tests._elrakning_test_bootstrap import install_elrakning_package_stub, install_homeassistant_stubs, install_optional_dependency_stubs

install_homeassistant_stubs()
install_elrakning_package_stub()
install_optional_dependency_stubs()

from custom_components.elrakning.price_only_planner import build_price_only_plan
from custom_components.elrakning.site_identity import SiteIdentityManager
from custom_components.elrakning.websocket import websocket_ella_plan


UTC = timezone.utc


def periods(values, start=None):
    start = start or datetime(2026, 9, 20, 0, 0, tzinfo=UTC)
    return [
        SimpleNamespace(start=start + timedelta(minutes=15 * index), end=start + timedelta(minutes=15 * (index + 1)), price=value)
        for index, value in enumerate(values)
    ]


class PriceOnlyPlannerTests(unittest.TestCase):
    def test_valid_prices_create_deterministic_price_only_blocks(self):
        now = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
        values = [0.20, 0.21, 0.70, 0.72, 0.40, 0.41]
        first = build_price_only_plan("site-a", periods(values), now, source_generation_id="generation-a")
        second = build_price_only_plan("site-a", periods(values), now, source_generation_id="generation-a")
        self.assertTrue(first["available"])
        self.assertEqual(first["plan_blocks"], second["plan_blocks"])
        self.assertGreaterEqual(len(first["plan_blocks"]), 2)
        for block in first["plan_blocks"]:
            self.assertNotIn("load", block)
            self.assertNotIn("solar", block)
            self.assertNotIn("battery", block)
            self.assertEqual(block["execution_status"], "not_executed_no_actuator")
            self.assertTrue(block["plan_block_id"])

    def test_missing_or_stale_prices_fail_closed(self):
        now = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
        self.assertFalse(build_price_only_plan("site-a", [], now, source_generation_id="generation-a")["available"])
        old = periods([0.2], start=datetime(2026, 9, 20, 0, 0, tzinfo=UTC))
        result = build_price_only_plan("site-a", old, now, source_generation_id="generation-a")
        self.assertEqual(result["reason"], "stale_price_periods")

    def test_different_sites_are_scoped_and_do_not_share_ids(self):
        now = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
        a = build_price_only_plan("site-a", periods([0.2, 0.8]), now, source_generation_id="generation-a")
        b = build_price_only_plan("site-b", periods([0.3, 0.6]), now, source_generation_id="generation-b")
        self.assertNotEqual(a["plan_blocks"], b["plan_blocks"])
        self.assertEqual(a["site_id"], "site-a")
        self.assertEqual(b["site_id"], "site-b")
        self.assertNotEqual(a["capability"]["source_generation_id"], b["capability"]["source_generation_id"])

    def test_invalid_periods_do_not_create_capability(self):
        now = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
        invalid = [SimpleNamespace(start=datetime(2026, 9, 20), end=datetime(2026, 9, 20, 0, 15), price=0.2)]
        result = build_price_only_plan("site-a", invalid, now, source_generation_id="generation-a")
        self.assertEqual(result["reason"], "invalid_price_periods")

    def test_websocket_price_plan_does_not_require_legacy_ella_binding(self):
        class Identity:
            state = {"active_site_id": "fiskvik"}

            def global_binding(self, service):
                binding = {"config_entry_id": "price-entry", "area": "SE2", "currency": "SEK"}
                binding["binding_fingerprint"] = SiteIdentityManager.binding_fingerprint(binding)
                return binding

        class Coordinator:
            async def async_get_price_data(self, target):
                return SimpleNamespace(
                    periods=periods([0.2, 0.8], start=datetime.now(UTC) + timedelta(hours=1)),
                    error=None,
                )

        class Entries:
            def async_entries(self, domain):
                return [SimpleNamespace(runtime_data=Coordinator())]

        class Hass:
            config_entries = Entries()
            data = {"elrakning": {"site_identity_manager": Identity()}}

        class Connection:
            def __init__(self):
                self.result = None

            def send_result(self, message_id, result):
                self.result = result

        connection = Connection()
        import asyncio
        asyncio.run(websocket_ella_plan(Hass(), connection, {"id": 1, "type": "elrakning/ella_plan"}))
        self.assertTrue(connection.result["available"])
        self.assertEqual(connection.result["site_id"], "fiskvik")

    def test_websocket_price_plan_rejects_tampered_global_price_provenance(self):
        class Identity:
            state = {"active_site_id": "fiskvik"}

            def global_binding(self, service):
                return {
                    "config_entry_id": "price-entry",
                    "area": "SE2",
                    "currency": "SEK",
                    "binding_fingerprint": "0" * 64,
                }

        class Coordinator:
            async def async_get_price_data(self, target):
                return SimpleNamespace(periods=periods([0.2, 0.8], start=datetime.now(UTC) + timedelta(hours=1)), error=None)

        class Entries:
            def async_entries(self, domain):
                return [SimpleNamespace(runtime_data=Coordinator())]

        class Hass:
            config_entries = Entries()
            data = {"elrakning": {"site_identity_manager": Identity()}}

        class Connection:
            def __init__(self):
                self.result = None

            def send_result(self, message_id, result):
                self.result = result

        connection = Connection()
        import asyncio
        asyncio.run(websocket_ella_plan(Hass(), connection, {"id": 1, "type": "elrakning/ella_plan"}))
        self.assertFalse(connection.result["available"])
        self.assertEqual(connection.result["reason"], "price_provenance_invalid")


if __name__ == "__main__":
    unittest.main()
