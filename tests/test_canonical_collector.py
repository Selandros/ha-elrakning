import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub


install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.canonical_collector import CanonicalCollector  # noqa: E402
from custom_components.elrakning.canonical_storage import CanonicalStorage, SCHEMA_PATH, quarter_start  # noqa: E402
from custom_components.elrakning.site_identity import SiteIdentityManager  # noqa: E402


UTC = timezone.utc


class _State:
    def __init__(self, value, unit, when):
        self.state = value
        self.last_updated = when
        self.attributes = {"unit_of_measurement": unit}


class _Identity:
    def __init__(self, targets):
        self.targets = targets

    def collection_targets(self):
        return self.targets


class _Hass:
    async def async_add_executor_job(self, callback, *args):
        return callback(*args)


class _Bus:
    def __init__(self):
        self.listeners = []

    def async_listen(self, event_type, action, **kwargs):
        self.listeners.append((event_type, action, kwargs))
        return lambda: None


class _StartHass(_Hass):
    def __init__(self):
        self.bus = _Bus()


def _target(site, role, entity, generation, mapping=None):
    power_semantics = {
        "house.consumption": ("W", "positive_consumption", "time_weighted_mean"),
        "solar.production": ("W", "positive_production", "time_weighted_mean"),
        "grid.power/import": ("W", "positive_import_negative_export", "time_weighted_mean"),
        "battery.power": ("W", "positive_discharge_negative_charge", "time_weighted_mean"),
        "battery.soc": ("%", "unsigned_0_100", "last_valid"),
    }
    unit, sign, aggregation = power_semantics[role]
    return {
        "site_id": site,
        "logical_role": role,
        "entity_id": entity,
        "generation_id": generation,
        "source_identity": {"identity_key": f"{site}:{generation}", "identity_strength": "strong"},
        "mapping": mapping or {},
        "classification": "measured",
        "canonicalization": {
            "unit": unit,
            "sign_convention": sign,
            "aggregation": aggregation,
            "classification": "measured",
            "max_hold_seconds": 60 if aggregation == "last_valid" else None,
            "invert_power": bool((mapping or {}).get("invert_power")),
            "invert_battery_power": bool((mapping or {}).get("invert_battery_power")),
            "absolute_value": role in {"house.consumption", "solar.production"},
        },
    }


class CanonicalCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_state_reported_subscription_is_filtered_to_ready_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            hass = _StartHass()
            collector = CanonicalCollector(
                hass, _Identity([target]), Path(directory) / "canonical.sqlite"
            )
            await collector.async_start()
            reported = hass.bus.listeners[1]
            self.assertIn("event_filter", reported[2])
            event_filter = reported[2]["event_filter"]
            self.assertTrue(event_filter(types.SimpleNamespace(data={"entity_id": "sensor.load"})))
            self.assertFalse(event_filter(types.SimpleNamespace(data={"entity_id": "sensor.other"})))
            await collector.async_shutdown()

    async def test_event_stream_is_site_explicit_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            target_a = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            target_b = _target("site-b", "house.consumption", "sensor.load", "gen-b")
            collector = CanonicalCollector(
                _Hass(), _Identity([target_a, target_b]), Path(directory) / "canonical.sqlite"
            )
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            collector._buffers[("site-a", "house.consumption", "gen-a", start)]["target"] = target_a
            collector._buffers[("site-a", "house.consumption", "gen-a", start)]["samples"] = [
                (start, 100.0),
                (start + timedelta(seconds=900), 100.0),
            ]
            collector._buffers[("site-b", "house.consumption", "gen-b", start)]["target"] = target_b
            collector._buffers[("site-b", "house.consumption", "gen-b", start)]["samples"] = [
                (start, 200.0),
                (start + timedelta(seconds=900), 200.0),
            ]
            self.assertEqual(await collector.async_flush(start, start + timedelta(seconds=900)), 2)
            self.assertEqual(collector.storage.count_observations(), 2)
            collector._buffers[("site-a", "house.consumption", "gen-a", start)]["target"] = target_a
            collector._buffers[("site-a", "house.consumption", "gen-a", start)]["samples"] = [
                (start, 100.0), (start + timedelta(seconds=900), 100.0)
            ]
            self.assertEqual(await collector.async_flush(start, start + timedelta(seconds=901)), 0)
            self.assertEqual(collector.storage.integrity_check(), "ok")
            rows = collector.storage._connection().execute(
                "SELECT site_id, value, quality_status FROM energy_observations ORDER BY site_id"
            ).fetchall()
            self.assertEqual(rows, [("site-a", 100.0, "good"), ("site-b", 200.0, "good")])
            collector.storage.close()

    async def test_missing_edges_are_partial_and_never_zero_filled(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            collector = CanonicalCollector(_Hass(), _Identity([target]), Path(directory) / "canonical.sqlite")
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            collector._buffers[("site-a", "house.consumption", "gen-a", start)]["target"] = target
            collector._buffers[("site-a", "house.consumption", "gen-a", start)]["samples"] = [
                (start + timedelta(seconds=300), 100.0),
                (start + timedelta(seconds=600), 100.0),
            ]
            await collector.async_flush(start, start + timedelta(seconds=900))
            row = collector.storage._connection().execute(
                "SELECT value, quality_status, gap_status, coverage_ratio FROM energy_observations"
            ).fetchone()
            self.assertEqual(row[0], 100.0)
            self.assertEqual(row[1:], ("partial", "gap", 300 / 900))
            collector.storage.close()

    async def test_source_replacement_mid_quarter_keeps_both_generations(self):
        with tempfile.TemporaryDirectory() as directory:
            old = _target("site-a", "solar.production", "sensor.solar_old", "gen-old")
            new = _target("site-a", "solar.production", "sensor.solar_new", "gen-new")
            identity = _Identity([old])
            collector = CanonicalCollector(_Hass(), identity, Path(directory) / "canonical.sqlite")
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            old_key = ("site-a", "solar.production", "gen-old", start)
            collector._buffers[old_key]["target"] = old
            collector._buffers[old_key]["samples"] = [
                (start + timedelta(seconds=60), 100.0),
                (start + timedelta(seconds=420), 100.0),
            ]
            identity.targets = [new]
            new_key = ("site-a", "solar.production", "gen-new", start)
            collector._buffers[new_key]["target"] = new
            collector._buffers[new_key]["samples"] = [
                (start + timedelta(seconds=480), 200.0),
                (start + timedelta(seconds=840), 200.0),
            ]
            await collector.async_flush(start, start + timedelta(seconds=900))
            rows = collector.storage._connection().execute(
                "SELECT source_generation_id, value, quality_status FROM energy_observations ORDER BY source_generation_id"
            ).fetchall()
            self.assertEqual(rows, [("gen-new", 200.0, "partial"), ("gen-old", 100.0, "partial")])
            collector.storage.close()

    async def test_reported_events_preserve_constant_value_freshness(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            collector = CanonicalCollector(_Hass(), _Identity([target]), Path(directory) / "canonical.sqlite")
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            event_type = types.SimpleNamespace
            for seconds in (60, 120, 180):
                await collector._async_state_reported(event_type(
                    data={"entity_id": "sensor.load", "state": _State("100", "W", start)},
                    time_fired=start + timedelta(seconds=seconds),
                ))
            buffer = collector._buffers[("site-a", "house.consumption", "gen-a", start)]
            self.assertEqual([item[0] for item in buffer["samples"]], [
                start + timedelta(seconds=60), start + timedelta(seconds=120), start + timedelta(seconds=180)
            ])

    async def test_reported_and_changed_pair_is_one_canonical_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "grid.power/import", "sensor.grid", "gen-a")
            collector = CanonicalCollector(
                _Hass(), _Identity([target]), Path(directory) / "canonical.sqlite"
            )
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            state = _State("1", "kW", start)
            event = types.SimpleNamespace(
                data={"entity_id": "sensor.grid", "new_state": state},
                time_fired=start + timedelta(seconds=60),
            )
            await collector._async_state_reported(event)
            await collector._async_state_changed(event)
            buffer = collector._buffers[("site-a", "grid.power/import", "gen-a", start)]
            self.assertEqual(len(buffer["samples"]), 1)

    async def test_silent_source_finalizes_as_gap_without_fabricated_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            collector = CanonicalCollector(
                _Hass(), _Identity([target]), Path(directory) / "canonical.sqlite"
            )
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            await collector.async_flush(start, start + timedelta(seconds=900))
            row = collector.storage._connection().execute(
                "SELECT value, quality_status, gap_status FROM energy_observations"
            ).fetchone()
            self.assertEqual(row, (None, "unknown", "gap"))

    async def test_target_without_source_semantics_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            target["canonicalization"] = None
            collector = CanonicalCollector(
                _Hass(), _Identity([target]), Path(directory) / "canonical.sqlite"
            )
            collector.storage.open()
            collector._started = True
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            await collector._async_state_changed(types.SimpleNamespace(
                data={"entity_id": "sensor.load", "new_state": _State("1", "kW", start)},
                time_fired=start,
            ))
            self.assertEqual(collector._buffers, {})

    def test_signs_and_soc_follow_contract(self):
        battery = _target("site-a", "battery.power", "sensor.battery", "gen-b", {"invert_battery_power": True})
        grid = _target("site-a", "grid.power/import", "sensor.grid", "gen-g", {"invert_power": True})
        when = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        self.assertEqual(CanonicalCollector._value_for_target(battery, _State("-2", "kW", when)), 2000.0)
        self.assertEqual(CanonicalCollector._value_for_target(grid, _State("-1", "kW", when)), 1000.0)
        soc = _target("site-a", "battery.soc", "sensor.soc", "gen-s")
        self.assertEqual(CanonicalCollector._value_for_target(soc, _State("57", "%", when)), 57.0)
        self.assertIsNone(CanonicalCollector._value_for_target(soc, _State("unknown", "%", when)))

    def test_explicit_target_canonicalization_controls_source_transform(self):
        when = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        target = _target(
            "site-a", "grid.power/import", "sensor.grid", "gen-g",
            {"invert_power": False},
        )
        target["canonicalization"] = {
            "unit": "W",
            "sign_convention": "positive_import_negative_export",
            "aggregation": "time_weighted_mean",
            "classification": "derived",
            "max_hold_seconds": None,
            "invert_power": True,
            "invert_battery_power": False,
            "absolute_value": False,
        }
        self.assertEqual(CanonicalCollector._value_for_target(target, _State("-1", "kW", when)), 1000.0)

    def test_duplicate_revision_payload_mismatch_is_explicit_error(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = CanonicalStorage(Path(directory) / "canonical.sqlite")
            storage.open()
            start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            target = _target("site-a", "house.consumption", "sensor.load", "gen-a")
            storage.ensure_source_generation(target, start)
            observation = {
                "semantic_key": "site-a|house.consumption|gen-a|2026-01-01T12:00:00+00:00",
                "site_id": "site-a", "logical_role": "house.consumption", "source_generation_id": "gen-a",
                "interval_start": start, "observed_at": start, "captured_at": start + timedelta(seconds=900),
                "known_at": start + timedelta(seconds=900), "value": 100.0, "unit": "W",
                "sign_convention": "positive_consumption", "quality_status": "good", "coverage_ratio": 1.0,
                "gap_status": "none", "quality": {"coverage_ratio": 1.0}, "provenance": {"origin": "a"},
            }
            self.assertTrue(storage.insert_observation(observation))
            changed = dict(observation, provenance={"origin": "b"})
            with self.assertRaises(ValueError):
                storage.insert_observation(changed)
            storage.close()

    def test_storage_reopen_verifies_schema_without_recreating_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canonical.sqlite"
            first = CanonicalStorage(path)
            first.open()
            first.close()
            second = CanonicalStorage(path)
            second.open()
            self.assertEqual(second.integrity_check(), "ok")
            second.close()

    def test_storage_fails_closed_on_schema_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canonical.sqlite"
            schema = Path(directory) / "schema.sql"
            schema.write_text(SCHEMA_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            storage = CanonicalStorage(path, schema)
            storage.open()
            storage.close()
            schema.write_text(schema.read_text(encoding="utf-8") + "\n-- tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "canonical_schema_mismatch"):
                CanonicalStorage(path, schema).open()

    def test_fresh_storage_fails_closed_when_initialization_marker_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canonical.sqlite"
            (Path(directory) / "canonical.sqlite.initializing").touch()
            with self.assertRaisesRegex(RuntimeError, "canonical_initialization_incomplete"):
                CanonicalStorage(path).open()

    def test_existing_empty_storage_fails_closed_without_auto_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canonical.sqlite"
            path.touch()
            with self.assertRaisesRegex(RuntimeError, "canonical_initialization_incomplete"):
                CanonicalStorage(path).open()

    def test_quarter_mapping_is_utc_aligned(self):
        value = datetime(2026, 3, 29, 1, 7, 4, tzinfo=UTC)
        self.assertEqual(quarter_start(value), datetime(2026, 3, 29, 1, 0, tzinfo=UTC))

    def test_collection_enabled_is_independent_of_active_site(self):
        manager = SiteIdentityManager.__new__(SiteIdentityManager)
        manager.state = {
            "active_site_id": "site-b",
            "sites": [{"site_id": "site-a"}, {"site_id": "site-b"}],
            "site_configs": {
                "site-a": {"collection_enabled": True},
                "site-b": {"collection_enabled": False},
            },
            "ledger": [{
                "site_id": "site-a", "logical_role": "house.consumption",
                "entity_id": "sensor.load", "generation_id": "gen-a",
                "classification": "measured",
                "canonicalization": {
                    "unit": "W", "sign_convention": "positive_consumption",
                "aggregation": "time_weighted_mean", "classification": "measured",
                    "max_hold_seconds": None,
                },
            }, {
                "site_id": "site-b", "logical_role": "house.consumption",
                "entity_id": "sensor.load", "generation_id": "gen-b",
                "classification": "measured",
                "canonicalization": {
                    "unit": "W", "sign_convention": "positive_consumption",
                    "aggregation": "time_weighted_mean", "classification": "measured",
                },
            }],
        }
        targets = manager.collection_targets()
        self.assertEqual([(item["site_id"], item["generation_id"]) for item in targets], [("site-a", "gen-a")])
