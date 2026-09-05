import types
import unittest
from datetime import datetime, timedelta, timezone

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)

install_optional_dependency_stubs()
install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning import cadence_audit as module  # noqa: E402


class _Store:
    def __init__(self, data=None):
        self.data = data
        self.removed = False

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data

    async def async_remove(self):
        self.data = None
        self.removed = True


class _State:
    def __init__(self, value, when):
        self.state = value
        self.last_reported = when
        self.last_updated = when
        self.last_changed = when


class _Event:
    def __init__(self, entity_id, when, new_state, old_state=None):
        self.time_fired = when
        self.data = {
            "entity_id": entity_id,
            "new_state": new_state,
            "old_state": old_state,
        }


def _identity(key, platform, strength="strong", provenance="registry"):
    return {
        "identity_key": key,
        "identity_strength": strength,
        "identity_provenance": provenance,
        "platform": platform,
    }


class _SiteIdentity:
    def __init__(self):
        self.site_id = "site-a"
        self.roles = [
            {
                "generation_id": "gen-load",
                "logical_role": "house.consumption",
                "entity_id": "sensor.load_a",
                "source_identity": _identity("load-key", "provider_a"),
            },
            {
                "generation_id": "gen-solar-1",
                "logical_role": "solar.production",
                "entity_id": "sensor.solar_a_1",
                "source_identity": _identity("solar-key-1", "provider_a"),
            },
            {
                "generation_id": "gen-solar-2",
                "logical_role": "solar.production",
                "entity_id": "sensor.solar_a_2",
                "source_identity": _identity("solar-key-2", "provider_b"),
            },
            {
                "generation_id": "gen-grid",
                "logical_role": "grid.power/import",
                "entity_id": "sensor.grid_a",
                "source_identity": _identity(
                    "grid-key", "provider_c", "medium", "registry_partial"
                ),
            },
            {
                "generation_id": "gen-battery-power",
                "logical_role": "battery.power",
                "entity_id": "sensor.battery_power_a",
                "source_identity": _identity("battery-power-key", "provider_d"),
            },
            {
                "generation_id": "gen-battery-soc",
                "logical_role": "battery.soc",
                "entity_id": "sensor.battery_soc_a",
                "source_identity": _identity("battery-soc-key", "provider_d"),
            },
        ]

    def public_state(self):
        return {
            "site_id": self.site_id,
            "current_site": {"site_id": self.site_id, "name": "Site A"},
            "logical_roles": self.roles,
        }


class CadenceAuditTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixed_now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
        module._utcnow = lambda: self.fixed_now
        module.event_helper.async_track_state_report_event = (
            lambda *_args, **_kwargs: (lambda: None)
        )
        module.event_helper.async_track_state_change_event = (
            lambda *_args, **_kwargs: (lambda: None)
        )
        module.event_helper.async_call_later = lambda *_args, **_kwargs: (lambda: None)
        self.hass = types.SimpleNamespace(states={})
        self.site = _SiteIdentity()
        self.identity_by_entity = {
            item["entity_id"]: dict(item["source_identity"])
            for item in self.site.roles
        }
        module.resolve_source_identity = (
            lambda _hass, entity_id: dict(
                self.identity_by_entity.get(
                    entity_id,
                    {
                        "identity_key": entity_id,
                        "identity_strength": "weak",
                        "identity_provenance": "entity_id_only",
                        "platform": None,
                    },
                )
            )
        )
        self.manager = module.CadenceAuditManager(self.hass, self.site)
        self.manager.store = _Store()

    async def test_start_snapshots_logical_roles_and_source_generations(self):
        result = await self.manager.async_start()
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["site_id"], "site-a")
        self.assertEqual(len(result["signals"]), 6)
        self.assertEqual(
            {item["logical_role"] for item in result["signals"]},
            {
                "house.consumption",
                "solar.production",
                "grid.power/import",
                "battery.power",
                "battery.soc",
            },
        )
        self.assertEqual(
            {item["source_generation_id"] for item in result["signals"]},
            {
                "gen-load",
                "gen-solar-1",
                "gen-solar-2",
                "gen-grid",
                "gen-battery-power",
                "gen-battery-soc",
            },
        )
        self.assertTrue(result["scope"]["source_agnostic"])
        self.assertFalse(result["scope"]["polling"])
        self.assertIsNone(result["scope"]["stale_after_seconds"])
        self.assertTrue(result["observation_homogeneous"])

    async def test_runtime_events_measure_cadence_without_assuming_stale(self):
        await self.manager.async_start()
        t0 = self.fixed_now
        first = _State("100", t0)
        second_time = t0 + timedelta(seconds=17)
        second = _State("100", second_time)
        third_time = t0 + timedelta(seconds=34)
        third = _State("110", third_time)

        self.manager._on_state_reported(_Event("sensor.load_a", t0, first))
        self.manager._on_state_reported(
            _Event("sensor.load_a", second_time, second)
        )
        self.manager._on_state_changed(
            _Event("sensor.load_a", third_time, third, second)
        )

        result = await self.manager.async_state()
        load = next(
            item
            for item in result["signals"]
            if item["source_generation_id"] == "gen-load"
        )
        self.assertEqual(load["report_count"], 3)
        self.assertEqual(load["same_value_report_count"], 2)
        self.assertEqual(load["state_changed_count"], 1)
        self.assertEqual(load["state_value_change_count"], 1)
        self.assertEqual(
            load["cadence"]["observed_event_gap_seconds"]["median"], 17.0
        )
        self.assertEqual(
            load["cadence"]["observed_event_gap_seconds"]["max"], 17.0
        )
        self.assertEqual(load["stale"]["status"], "not_classified")
        self.assertIsNone(load["stale"]["stale_after_seconds"])
        self.assertEqual(load["source_continuity"]["status"], "verified_unchanged")

    async def test_state_changed_without_value_change_is_counted_separately(self):
        await self.manager.async_start()
        t0 = self.fixed_now
        old = _State("100", t0)
        new = _State("100", t0 + timedelta(seconds=15))
        self.manager._on_state_changed(
            _Event("sensor.load_a", t0 + timedelta(seconds=15), new, old)
        )
        result = await self.manager.async_state()
        load = next(
            item
            for item in result["signals"]
            if item["source_generation_id"] == "gen-load"
        )
        self.assertEqual(load["state_changed_count"], 1)
        self.assertEqual(load["state_value_change_count"], 0)
        self.assertEqual(load["state_changed_without_state_value_change_count"], 1)
        self.assertEqual(load["same_value_report_count"], 1)

    async def test_unavailable_period_is_measured_only(self):
        await self.manager.async_start()
        t0 = self.fixed_now
        unavailable = _State("unavailable", t0)
        available_time = t0 + timedelta(seconds=45)
        available = _State("50", available_time)
        self.manager._on_state_changed(
            _Event("sensor.grid_a", t0, unavailable, _State("40", t0))
        )
        self.manager._on_state_changed(
            _Event("sensor.grid_a", available_time, available, unavailable)
        )
        result = await self.manager.async_state()
        grid = next(
            item
            for item in result["signals"]
            if item["source_generation_id"] == "gen-grid"
        )
        self.assertEqual(grid["unavailable"]["period_count"], 1)
        self.assertEqual(grid["unavailable"]["duration_seconds"], 45.0)

    async def test_source_snapshot_does_not_follow_later_rebinding(self):
        await self.manager.async_start()
        self.site.roles[0] = {
            "generation_id": "gen-load-new",
            "logical_role": "house.consumption",
            "entity_id": "sensor.load_b",
            "source_identity": _identity("new-load-key", "different_provider"),
        }
        result = await self.manager.async_state()
        load = next(
            item
            for item in result["signals"]
            if item["logical_role"] == "house.consumption"
        )
        self.assertEqual(load["source_generation_id"], "gen-load")
        self.assertEqual(load["entity_id"], "sensor.load_a")

    async def test_identity_change_on_same_entity_stops_mixing_generations(self):
        await self.manager.async_start()
        t0 = self.fixed_now
        first = _State("100", t0)
        self.manager._on_state_reported(_Event("sensor.load_a", t0, first))
        self.identity_by_entity["sensor.load_a"] = _identity(
            "replacement-key", "provider_z"
        )
        second_time = t0 + timedelta(seconds=15)
        second = _State("101", second_time)
        self.manager._on_state_changed(
            _Event("sensor.load_a", second_time, second, first)
        )
        result = await self.manager.async_state()
        load = next(
            item
            for item in result["signals"]
            if item["source_generation_id"] == "gen-load"
        )
        self.assertEqual(load["report_count"], 1)
        self.assertEqual(load["source_continuity"]["status"], "changed")
        self.assertFalse(load["observation_homogeneous"])
        self.assertFalse(result["observation_homogeneous"])

    async def test_weak_identity_is_measured_without_false_continuity_claim(self):
        self.site.roles[0]["source_identity"] = _identity(
            "weak-key", "provider_x", "weak", "entity_id_only"
        )
        self.identity_by_entity["sensor.load_a"] = dict(
            self.site.roles[0]["source_identity"]
        )
        result = await self.manager.async_start()
        load = next(
            item
            for item in result["signals"]
            if item["source_generation_id"] == "gen-load"
        )
        self.assertEqual(load["source_continuity"]["status"], "not_guaranteed")
        self.assertIsNone(load["observation_homogeneous"])
        self.assertIsNone(result["observation_homogeneous"])

    async def test_restart_resumes_same_deadline_and_marks_runtime_gap(self):
        await self.manager.async_start()
        saved = self.manager.store.data
        restart_time = self.fixed_now + timedelta(minutes=5)
        module._utcnow = lambda: restart_time
        restarted = module.CadenceAuditManager(self.hass, self.site)
        restarted.store = _Store(saved)
        await restarted.async_load()
        result = await restarted.async_state()
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["restart_count"], 1)
        self.assertEqual(result["runtime_gap_seconds"], 300.0)
        self.assertEqual(
            result["planned_end_at"],
            (self.fixed_now + module.AUDIT_DURATION).isoformat(),
        )

    async def test_restart_after_deadline_caps_runtime_gap_at_deadline(self):
        await self.manager.async_start()
        saved = self.manager.store.data
        saved["last_checkpoint_at"] = (
            self.fixed_now + timedelta(hours=23)
        ).isoformat()
        restart_time = self.fixed_now + timedelta(hours=25)
        module._utcnow = lambda: restart_time
        restarted = module.CadenceAuditManager(self.hass, self.site)
        restarted.store = _Store(saved)
        await restarted.async_load()
        result = await restarted.async_state()
        self.assertEqual(result["status"], "completed_with_runtime_gap")
        self.assertEqual(result["runtime_gap_seconds"], 3600.0)
        self.assertEqual(
            result["completed_at"],
            (self.fixed_now + module.AUDIT_DURATION).isoformat(),
        )
        self.assertTrue(result["minimum_24h_window_met"])

    async def test_cleanup_removes_only_temporary_audit_store(self):
        await self.manager.async_start()
        await self.manager.async_stop()
        result = await self.manager.async_cleanup()
        self.assertEqual(result["status"], "idle")
        self.assertTrue(self.manager.store.removed)

    async def test_missing_roles_are_explicit_and_no_vendor_is_required(self):
        self.site.roles = self.site.roles[:1]
        result = await self.manager.async_start()
        self.assertEqual(len(result["signals"]), 1)
        self.assertIn("grid.power/import", result["missing_roles"])
        self.assertIn("solar.production", result["missing_roles"])


if __name__ == "__main__":
    unittest.main()
