import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from tests._elrakning_test_bootstrap import install_elrakning_package_stub, install_homeassistant_stubs, install_optional_dependency_stubs

install_homeassistant_stubs()
install_elrakning_package_stub()
install_optional_dependency_stubs()

from custom_components.elrakning.price_only_planner import build_price_only_plan, enrich_plan_with_load
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
    def _load_frame(self, site_id="site-a", quality_status="good", points=None):
        points = points or [
            {"valid_at": "2026-09-20T00:00:00+00:00", "value": 1000, "unit": "W", "quality_status": "good"},
            {"valid_at": "2026-09-20T00:15:00+00:00", "value": 2000, "unit": "W", "quality_status": "good"},
        ]
        return {"site_id": site_id, "payload_schema": "load_forecast.v1", "quality_status": quality_status,
                "frame_id": "frame-a", "source_generation_id": "load-gen-a", "quality": {"status": quality_status},
                "known_at": "2026-09-19T12:00:00+00:00", "points": points}

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

    def test_verified_complete_load_enriches_price_blocks_deterministically(self):
        now = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
        plan = build_price_only_plan("site-a", periods([0.2, 0.2]), now, source_generation_id="generation-a")
        enriched = enrich_plan_with_load(plan, [self._load_frame()])
        self.assertEqual(enriched, enrich_plan_with_load(plan, [self._load_frame()]))
        self.assertEqual(enriched["plan_blocks"][0]["load"]["energy_kwh"], 0.75)
        self.assertEqual(enriched["plan_blocks"][0]["load"]["coverage"], "complete")
        self.assertIn("load", enriched["plan_blocks"][0]["verified_inputs"]["capabilities"])

    def test_all_fully_covered_price_blocks_are_load_enriched(self):
        now = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
        plan = build_price_only_plan("site-a", periods([0.2, 0.8, 0.2]), now, source_generation_id="generation-a")
        points = [
            {"valid_at": f"2026-09-20T00:{minutes:02d}:00+00:00", "value": 1000 + minutes, "unit": "W", "quality_status": "good"}
            for minutes in (0, 15, 30)
        ]
        enriched = enrich_plan_with_load(plan, [self._load_frame(points=points)])
        self.assertEqual(len(enriched["plan_blocks"]), 3)
        self.assertTrue(all(block.get("load", {}).get("coverage") == "complete" for block in enriched["plan_blocks"]))

    def test_actual_and_forecast_slots_form_complete_nonduplicated_estimate(self):
        decision_at = datetime(2026, 9, 20, 10, 30, tzinfo=UTC)
        plan = {
            "available": True,
            "site_id": "site-a",
            "capability": {"known_at": decision_at.isoformat()},
            "plan_blocks": [
                {"plan_block_id": "past", "start": "2026-09-20T10:00:00+00:00", "end": "2026-09-20T10:15:00+00:00"},
                {"plan_block_id": "future", "start": "2026-09-20T10:30:00+00:00", "end": "2026-09-20T10:45:00+00:00"},
                {"plan_block_id": "mixed", "start": "2026-09-20T10:15:00+00:00", "end": "2026-09-20T10:45:00+00:00"},
            ],
        }
        frame = self._load_frame(points=[
            {"valid_at": "2026-09-20T10:30:00+00:00", "value": 2000, "unit": "W", "quality_status": "good"},
            {"valid_at": "2026-09-20T10:45:00+00:00", "value": 2000, "unit": "W", "quality_status": "good"},
        ])
        actual_rows = [
            {"logical_role": "house.consumption", "interval_start": datetime(2026, 9, 20, 10, 0, tzinfo=UTC),
             "interval_end": datetime(2026, 9, 20, 10, 15, tzinfo=UTC), "resolution_seconds": 900,
             "source_generation_id": "canonical-a", "unit": "W", "value": 1000, "quality_status": "good"},
            {"logical_role": "house.consumption", "interval_start": datetime(2026, 9, 20, 10, 15, tzinfo=UTC),
             "interval_end": datetime(2026, 9, 20, 10, 30, tzinfo=UTC), "resolution_seconds": 900,
             "source_generation_id": "canonical-a", "unit": "W", "value": 1000, "quality_status": "partial"},
        ]
        enriched = enrich_plan_with_load(plan, [frame], actual_rows=actual_rows, decision_at=decision_at)
        self.assertEqual(enriched["plan_blocks"][0]["load"]["estimate_kind"], "actual")
        self.assertEqual(enriched["plan_blocks"][0]["load"]["energy_kwh"], 0.25)
        self.assertEqual(enriched["plan_blocks"][1]["load"]["estimate_kind"], "forecast")
        self.assertEqual(enriched["plan_blocks"][1]["load"]["energy_kwh"], 0.5)
        self.assertEqual(enriched["plan_blocks"][2]["load"]["estimate_kind"], "mixed")
        self.assertEqual(enriched["plan_blocks"][2]["load"]["energy_kwh"], 0.75)
        self.assertEqual(enriched["plan_blocks"][2]["load"]["actual_slots"], 1)
        self.assertEqual(enriched["plan_blocks"][2]["load"]["forecast_slots"], 1)

    def test_model_fills_missing_slot_without_zero_fill_or_double_counting(self):
        decision_at = datetime(2026, 9, 20, 10, 30, tzinfo=UTC)
        plan = {
            "available": True, "site_id": "site-a", "capability": {"known_at": decision_at.isoformat()},
            "plan_blocks": [{"plan_block_id": "mixed", "start": "2026-09-20T10:00:00+00:00", "end": "2026-09-20T10:30:00+00:00"}],
        }
        model = [{
            "valid_at": datetime(2026, 9, 20, 10, 15, tzinfo=UTC), "value": 3000,
            "source": "model", "source_generation_id": "canonical-a", "source_generation_ids": ["canonical-a"],
            "frame_id": None, "quality": {"status": "model"},
        }]
        actual = [{
            "logical_role": "house.consumption", "interval_start": datetime(2026, 9, 20, 10, 0, tzinfo=UTC),
            "interval_end": datetime(2026, 9, 20, 10, 15, tzinfo=UTC), "resolution_seconds": 900,
            "source_generation_id": "canonical-a", "unit": "W", "value": 1000, "quality_status": "good",
        }]
        result = enrich_plan_with_load(plan, [], actual_rows=actual, decision_at=decision_at, model_points=model)
        load = result["plan_blocks"][0]["load"]
        self.assertEqual(load["estimate_kind"], "mixed")
        self.assertEqual(load["actual_slots"], 1)
        self.assertEqual(load["model_slots"], 1)
        self.assertEqual(load["energy_kwh"], 1.0)
        self.assertEqual(load["model_support"]["model_version"], "load-profile-v1")

    def test_missing_model_support_stays_fail_closed(self):
        decision_at = datetime(2026, 9, 20, 10, 30, tzinfo=UTC)
        plan = {
            "available": True, "site_id": "site-a", "capability": {"known_at": decision_at.isoformat()},
            "plan_blocks": [{"plan_block_id": "gap", "start": "2026-09-20T10:00:00+00:00", "end": "2026-09-20T10:15:00+00:00"}],
        }
        result = enrich_plan_with_load(plan, [], actual_rows=[], decision_at=decision_at, model_points=[])
        self.assertNotIn("load", result["plan_blocks"][0])

    def test_actual_load_is_site_scoped_and_gaps_fail_closed(self):
        decision_at = datetime(2026, 9, 20, 10, 30, tzinfo=UTC)
        plan = {
            "available": True, "site_id": "site-a", "capability": {"known_at": decision_at.isoformat()},
            "plan_blocks": [{"plan_block_id": "gap", "start": "2026-09-20T10:00:00+00:00", "end": "2026-09-20T10:30:00+00:00"}],
        }
        actual = [{"logical_role": "house.consumption", "interval_start": datetime(2026, 9, 20, 10, 0, tzinfo=UTC),
                   "interval_end": datetime(2026, 9, 20, 10, 15, tzinfo=UTC), "resolution_seconds": 900,
                   "source_generation_id": "canonical-a", "unit": "W", "value": 1000, "quality_status": "good",
                   "site_id": "site-b"}]
        result = enrich_plan_with_load(plan, [], actual_rows=actual, decision_at=decision_at)
        self.assertNotIn("load", result["plan_blocks"][0])

    def test_missing_stale_or_partial_load_falls_back_without_fabrication(self):
        now = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
        plan = build_price_only_plan("site-a", periods([0.2, 0.2]), now, source_generation_id="generation-a")
        partial = self._load_frame(points=[{"valid_at": "2026-09-20T00:00:00+00:00", "value": 1000, "unit": "W", "quality_status": "good"}])
        for frames in ([], [self._load_frame(quality_status="stale")], [self._load_frame("site-b")]):
            result = enrich_plan_with_load(plan, frames)
            self.assertTrue(all("load" not in block for block in result["plan_blocks"]))
        incomplete = enrich_plan_with_load(plan, [partial])
        self.assertTrue(all(block["load"] == {"coverage": "unavailable", "reason": "incomplete_forecast_coverage"}
                           for block in incomplete["plan_blocks"]))

    def test_load_enrichment_is_site_scoped(self):
        now = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
        plan_a = build_price_only_plan("site-a", periods([0.2, 0.8]), now, source_generation_id="generation-a")
        plan_b = build_price_only_plan("site-b", periods([0.2, 0.8]), now, source_generation_id="generation-a")
        self.assertTrue(any("load" in block for block in enrich_plan_with_load(plan_a, [self._load_frame()])["plan_blocks"]))
        self.assertTrue(all("load" not in block for block in enrich_plan_with_load(plan_b, [self._load_frame()])["plan_blocks"]))

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
