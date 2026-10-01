import asyncio
import json
import tempfile
import unittest
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.canonical_storage import CanonicalStorage
from custom_components.elrakning.external_input_frames import persist_nord_pool_frame
from custom_components.elrakning.site_economic_frames import (
    _async_capture_eon_grid_economic_snapshot,
    build_eon_grid_economic_frames,
    matching_grid_binding_targets,
    persist_eon_grid_economic_snapshot,
    resolve_grid_binding_site_id,
    schedule_eon_grid_economic_capture,
    _persist_eon_grid_economic_snapshot_with_retry,
)
from unittest.mock import patch


UTC = timezone.utc


def _binding(fingerprint="binding-a", street="Street 1"):
    return {
        "config_entry_id": "grid-entry",
        "provider": "eon",
        "binding_fingerprint": fingerprint,
        "facility": {
            "address": {"street": street, "city": "Town", "postal_code": "123 45"},
            "grid_area": "Grid",
            "price_area": "SE 2",
            "fuse_ampere": 16,
        },
    }


def _state(
    *,
    updated_at="2026-09-05T20:00:00+00:00",
    status="active",
    transfer=97.0,
    tax=45.0,
    fixed=226.25,
    street="Street 1",
    vat_included=True,
    price_basis="gross",
    source="grouped_contracts",
    start_date="2026-01-01",
    end_date=None,
):
    return {
        "configured": True,
        "updated_at": updated_at,
        "agreement": {
            "status": status,
            "source_status": status.upper(),
            "type": "ELECTRICITY_CONS_GRID",
            "name": "16 A Grid",
            "start_date": start_date,
            "end_date": end_date,
        },
        "facility": {
            "address": {"street": street, "city": "Town", "postal_code": "123 45"},
            "grid_area": "Grid",
            "price_area": "SE 2",
            "fuse_ampere": 16,
        },
        "grid_price": {
            "source": source,
            "source_subtitle": "Samtliga priser är inklusive moms.",
            "vat_included": vat_included,
            "price_basis": price_basis,
            "fixed_monthly_sek": fixed,
            "transfer_ore_per_kwh_gross": transfer,
            "energy_tax_ore_per_kwh_gross": tax,
            "variable_total_ore_per_kwh_gross": (
                transfer + tax
                if isinstance(transfer, (int, float)) and isinstance(tax, (int, float))
                else None
            ),
        },
    }


def _price_data():
    start = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    return SimpleNamespace(
        area="SE2",
        currency="SEK",
        date=date(2026, 9, 5),
        periods=(
            SimpleNamespace(start=start, end=start + timedelta(minutes=15), price=0.42),
            SimpleNamespace(
                start=start + timedelta(minutes=15),
                end=start + timedelta(minutes=30),
                price=0.43,
            ),
        ),
    )


class SiteEconomicFrameTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "canonical.sqlite"
        self.storage = CanonicalStorage(self.path)
        self.storage.open()
        self.captured = datetime(2026, 9, 5, 20, 1, tzinfo=UTC)

    def tearDown(self):
        self.storage.close()
        self.directory.cleanup()

    def test_locked_idempotent_snapshot_write_retries_once_in_executor_path(self):
        with patch(
            "custom_components.elrakning.site_economic_frames.persist_eon_grid_economic_snapshot_path",
            side_effect=[sqlite3.OperationalError("database is locked"), 3],
        ) as persist:
            result = _persist_eon_grid_economic_snapshot_with_retry(
                self.path, "site-a", _binding(), _state(), self.captured
            )
        self.assertEqual(result, 3)
        self.assertEqual(persist.call_count, 2)

    def test_matching_targets_fan_out_shared_source_without_active_site_identity(self):
        binding_a = _binding(fingerprint="a")
        binding_b = _binding(fingerprint="b")
        state = {
            "active_site_id": "site-disabled",
            "site_configs": {
                "site-a": {
                    "collection_enabled": True,
                    "bindings": {"grid": binding_a},
                },
                "site-b": {
                    "collection_enabled": True,
                    "bindings": {"grid": binding_b},
                },
                "site-disabled": {
                    "collection_enabled": False,
                    "bindings": {"grid": _binding(fingerprint="disabled")},
                },
                "site-other-facility": {
                    "collection_enabled": True,
                    "bindings": {"grid": _binding(fingerprint="other", street="Street 2")},
                },
                "site-other-entry": {
                    "collection_enabled": True,
                    "bindings": {"grid": {**_binding(fingerprint="entry"), "config_entry_id": "other-entry"}},
                },
            },
        }

        targets = matching_grid_binding_targets(state, _state(), "grid-entry")

        self.assertEqual([site_id for site_id, _binding_value in targets], ["site-a", "site-b"])
        self.assertEqual(
            {binding_value["binding_fingerprint"] for _site_id, binding_value in targets},
            {"a", "b"},
        )

    def test_capture_scheduler_uses_all_matching_bindings_not_active_runtime_binding(self):
        binding_a = _binding(fingerprint="a")
        binding_b = _binding(fingerprint="b")
        site_state = {
            "active_site_id": "site-b",
            "site_configs": {
                "site-a": {"collection_enabled": True, "bindings": {"grid": binding_a}},
                "site-b": {"collection_enabled": True, "bindings": {"grid": binding_b}},
            },
        }

        class _Hass:
            def __init__(self):
                self.calls = []
                self.data = {
                    "elrakning": {
                        "site_identity_manager": SimpleNamespace(state=site_state),
                        "grid_manager": SimpleNamespace(
                            _site_binding=None,
                            provider=SimpleNamespace(state=_state()),
                            entry=SimpleNamespace(entry_id="grid-entry"),
                        ),
                        "canonical_collector": SimpleNamespace(
                            storage=SimpleNamespace(path=Path("/tmp/canonical.sqlite"))
                        ),
                    }
                }

            async def async_add_executor_job(self, function, *args):
                self.calls.append((function, args))
                return 0

        hass = _Hass()
        asyncio.run(_async_capture_eon_grid_economic_snapshot(hass, self.captured))

        self.assertEqual([call[1][1] for call in hass.calls], ["site-a", "site-b"])
        self.assertEqual([call[1][2]["binding_fingerprint"] for call in hass.calls], ["a", "b"])

    def test_scheduler_hands_task_creation_to_home_assistant_loop(self):
        class _Loop:
            def __init__(self):
                self.callback = None

            def call_soon_threadsafe(self, callback):
                self.callback = callback

        class _Hass:
            def __init__(self):
                self.loop = _Loop()
                self.tasks = []

            def async_create_task(self, coroutine):
                self.tasks.append(coroutine)
                coroutine.close()

        hass = _Hass()
        schedule_eon_grid_economic_capture(hass)

        self.assertEqual(hass.tasks, [])
        self.assertIsNotNone(hass.loop.callback)
        hass.loop.callback()
        self.assertEqual(len(hass.tasks), 1)

    def test_active_eon_snapshot_round_trips_with_separate_economic_roles(self):
        inserted = persist_eon_grid_economic_snapshot(
            self.storage, "site-a", _binding(), _state(), self.captured
        )
        self.assertEqual(inserted, 3)
        self.assertEqual(self.storage.count_external_frames(), 3)
        self.assertEqual(
            self.storage.connection.execute("SELECT COUNT(*) FROM external_input_points").fetchone()[0],
            3,
        )
        rows = self.storage.connection.execute(
            """SELECT source_scope, site_id, logical_role, fetched_at_us, known_at_us,
                      captured_at_us, valid_from_us, valid_to_us, provenance_json
                 FROM external_input_frames ORDER BY logical_role"""
        ).fetchall()
        self.assertTrue(all(row[0] == "site" and row[1] == "site-a" for row in rows))
        self.assertTrue(all(row[3] == int(datetime(2026, 9, 5, 20, 0, tzinfo=UTC).timestamp() * 1_000_000) for row in rows))
        self.assertTrue(all(row[4] == int(self.captured.timestamp() * 1_000_000) for row in rows))
        self.assertTrue(all(row[5] == int(self.captured.timestamp() * 1_000_000) for row in rows))
        self.assertTrue(all(row[6] is None and row[7] is None for row in rows))
        roles = {row[2] for row in rows}
        self.assertEqual(
            roles,
            {
                "economic.grid.import.transfer",
                "economic.grid.import.energy_tax",
                "economic.grid.fixed.subscription",
            },
        )
        self.assertFalse(any("export" in role or "total" in role for role in roles))
        for row in rows:
            provenance = json.loads(row[8])
            self.assertIs(provenance["vat_included"], True)
            self.assertEqual(provenance["price_basis"], "gross")
            self.assertFalse(provenance["effective_validity"]["utc_boundaries_resolved"])

        points = {
            role: (value, unit, json.loads(point_json))
            for role, value, unit, point_json in self.storage.connection.execute(
                """SELECT f.logical_role, p.value, p.unit, p.point_json
                     FROM external_input_frames f
                     JOIN external_input_points p ON p.frame_id = f.frame_id"""
            ).fetchall()
        }
        self.assertEqual(points["economic.grid.import.transfer"][0:2], (0.97, "SEK/kWh"))
        self.assertEqual(points["economic.grid.import.energy_tax"][0:2], (0.45, "SEK/kWh"))
        self.assertEqual(points["economic.grid.fixed.subscription"][0:2], (226.25, "SEK/month"))
        self.assertEqual(points["economic.grid.import.transfer"][2]["sign_convention"], "positive_import_cost")
        self.assertEqual(points["economic.grid.fixed.subscription"][2]["sign_convention"], "positive_fixed_cost")

    def test_exact_replay_is_idempotent_and_preserves_first_availability(self):
        binding = _binding()
        state = _state()
        self.assertEqual(
            persist_eon_grid_economic_snapshot(self.storage, "site-a", binding, state, self.captured),
            3,
        )
        later = self.captured + timedelta(hours=1)
        self.assertEqual(
            persist_eon_grid_economic_snapshot(self.storage, "site-a", binding, state, later),
            0,
        )
        self.assertEqual(self.storage.count_external_frames(), 3)
        known_values = {
            row[0]
            for row in self.storage.connection.execute(
                "SELECT known_at_us FROM external_input_frames"
            ).fetchall()
        }
        self.assertEqual(known_values, {int(self.captured.timestamp() * 1_000_000)})

    def test_same_snapshot_correction_creates_revision_without_destroying_old_value(self):
        binding = _binding()
        state = _state()
        persist_eon_grid_economic_snapshot(self.storage, "site-a", binding, state, self.captured)
        corrected = _state(transfer=99.0)
        self.assertEqual(
            persist_eon_grid_economic_snapshot(
                self.storage, "site-a", binding, corrected, self.captured + timedelta(minutes=2)
            ),
            1,
        )
        rows = self.storage.connection.execute(
            """SELECT f.revision, f.supersedes_frame_id, p.value
                 FROM external_input_frames f
                 JOIN external_input_points p ON p.frame_id = f.frame_id
                WHERE f.logical_role = 'economic.grid.import.transfer'
                ORDER BY f.revision"""
        ).fetchall()
        self.assertEqual([row[0] for row in rows], [1, 2])
        self.assertIsNotNone(rows[1][1])
        self.assertEqual([row[2] for row in rows], [0.97, 0.99])

    def test_no_lookahead_rejects_source_snapshot_after_capture(self):
        state = _state(updated_at="2026-09-05T20:02:00Z")
        with self.assertRaisesRegex(ValueError, "economic_snapshot_fetched_after_capture"):
            persist_eon_grid_economic_snapshot(
                self.storage, "site-a", _binding(), state, self.captured
            )
        self.assertEqual(self.storage.count_external_frames(), 0)

    def test_naive_source_timestamp_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "economic_fetched_time_invalid"):
            build_eon_grid_economic_frames(
                "site-a",
                _binding(),
                _state(updated_at="2026-09-05T20:00:00"),
                self.captured,
            )

    def test_ambiguous_vat_or_non_grouped_source_fails_closed(self):
        for state in (
            _state(vat_included=False),
            _state(price_basis="unknown"),
            _state(source="web_profile"),
        ):
            self.assertEqual(
                persist_eon_grid_economic_snapshot(
                    self.storage, "site-a", _binding(), state, self.captured
                ),
                0,
            )
        self.assertEqual(self.storage.count_external_frames(), 0)

    def test_missing_components_remain_unavailable_instead_of_zero(self):
        state = _state(tax=None, fixed=None)
        self.assertEqual(
            persist_eon_grid_economic_snapshot(
                self.storage, "site-a", _binding(), state, self.captured
            ),
            1,
        )
        row = self.storage.connection.execute(
            """SELECT f.logical_role, p.value
                 FROM external_input_frames f
                 JOIN external_input_points p ON p.frame_id = f.frame_id"""
        ).fetchone()
        self.assertEqual(row, ("economic.grid.import.transfer", 0.97))

    def test_invalid_present_component_fails_closed(self):
        for value in (-1, float("nan"), "not-a-number"):
            state = _state(transfer=value)
            with self.assertRaisesRegex(ValueError, "economic_component_invalid"):
                build_eon_grid_economic_frames(
                    "site-a", _binding(), state, self.captured
                )

    def test_future_or_unbound_facility_does_not_create_active_tariff_frames(self):
        self.assertEqual(
            persist_eon_grid_economic_snapshot(
                self.storage, "site-a", _binding(), _state(status="future"), self.captured
            ),
            0,
        )
        self.assertEqual(
            persist_eon_grid_economic_snapshot(
                self.storage,
                "site-a",
                _binding(street="Bound Street"),
                _state(street="Different Street"),
                self.captured,
            ),
            0,
        )
        self.assertEqual(self.storage.count_external_frames(), 0)

    def test_source_generation_is_site_scoped_and_does_not_leak_between_sites(self):
        binding = _binding()
        state = _state()
        persist_eon_grid_economic_snapshot(self.storage, "site-a", binding, state, self.captured)
        persist_eon_grid_economic_snapshot(self.storage, "site-b", binding, state, self.captured)
        generations = self.storage.connection.execute(
            """SELECT source_generation_id, owner_site_id, logical_role
                 FROM source_generations
                WHERE source_scope = 'site'"""
        ).fetchall()
        self.assertEqual(len(generations), 6)
        self.assertEqual({row[1] for row in generations}, {"site-a", "site-b"})
        self.assertEqual(len({row[0] for row in generations}), 6)
        frames = self.storage.connection.execute(
            "SELECT DISTINCT source_scope, site_id FROM external_input_frames"
        ).fetchall()
        self.assertEqual(set(frames), {("site", "site-a"), ("site", "site-b")})

    def test_explicit_binding_owner_resolution_never_uses_active_site(self):
        binding_a = _binding(fingerprint="a")
        binding_b = _binding(fingerprint="b", street="Street 2")
        state = {
            "active_site_id": "site-b",
            "site_configs": {
                "site-a": {"bindings": {"grid": binding_a}},
                "site-b": {"bindings": {"grid": binding_b}},
            },
        }
        self.assertEqual(resolve_grid_binding_site_id(state, binding_a), "site-a")
        ambiguous = {
            "active_site_id": "site-a",
            "site_configs": {
                "site-a": {"bindings": {"grid": binding_a}},
                "site-b": {"bindings": {"grid": dict(binding_a)}},
            },
        }
        self.assertIsNone(resolve_grid_binding_site_id(ambiguous, binding_a))

    def test_facility_replacement_creates_new_source_generation_not_revision(self):
        persist_eon_grid_economic_snapshot(
            self.storage, "site-a", _binding(), _state(), self.captured
        )
        persist_eon_grid_economic_snapshot(
            self.storage,
            "site-a",
            _binding(fingerprint="binding-b", street="Street 2"),
            _state(street="Street 2"),
            self.captured + timedelta(hours=1),
        )
        transfer = self.storage.connection.execute(
            """SELECT source_generation_id, revision
                 FROM external_input_frames
                WHERE logical_role = 'economic.grid.import.transfer'
                ORDER BY fetched_at_us"""
        ).fetchall()
        self.assertEqual(len(transfer), 2)
        self.assertNotEqual(transfer[0][0], transfer[1][0])
        self.assertEqual([row[1] for row in transfer], [1, 1])

    def test_restart_reopen_preserves_idempotency(self):
        binding = _binding()
        state = _state()
        persist_eon_grid_economic_snapshot(self.storage, "site-a", binding, state, self.captured)
        self.storage.close()
        self.storage = CanonicalStorage(self.path)
        self.storage.open()
        self.assertEqual(
            persist_eon_grid_economic_snapshot(
                self.storage, "site-a", binding, state, self.captured + timedelta(hours=1)
            ),
            0,
        )
        self.assertEqual(self.storage.count_external_frames(), 3)

    def test_date_only_contract_validity_is_preserved_without_dst_inference(self):
        fetched = "2026-10-25T00:30:00Z"
        captured = datetime(2026, 10, 25, 0, 31, tzinfo=UTC)
        persist_eon_grid_economic_snapshot(
            self.storage,
            "site-a",
            _binding(),
            _state(
                updated_at=fetched,
                start_date="2026-10-25",
                end_date="2027-03-28",
            ),
            captured,
        )
        row = self.storage.connection.execute(
            """SELECT valid_from_us, valid_to_us, provenance_json
                 FROM external_input_frames LIMIT 1"""
        ).fetchone()
        self.assertIsNone(row[0])
        self.assertIsNone(row[1])
        provenance = json.loads(row[2])
        validity = provenance["effective_validity"]
        self.assertEqual(validity["source_start_date"], "2026-10-25")
        self.assertEqual(validity["source_end_date"], "2027-03-28")
        self.assertFalse(validity["utc_boundaries_resolved"])
        valid_at = self.storage.connection.execute(
            "SELECT valid_at_us FROM external_input_points LIMIT 1"
        ).fetchone()[0]
        self.assertEqual(
            valid_at,
            int(datetime(2026, 10, 25, 0, 30, tzinfo=UTC).timestamp() * 1_000_000),
        )

    def test_existing_global_nord_pool_frame_is_unchanged(self):
        data = _price_data()
        np_binding = {"config_entry_id": "np-entry", "area": "SE2", "currency": "SEK"}
        np_capture = datetime(2026, 9, 5, 1, 0, tzinfo=UTC)
        self.assertTrue(persist_nord_pool_frame(self.storage, data, np_binding, np_capture))
        before_frame = self.storage.connection.execute(
            """SELECT frame_id, semantic_key, source_scope, site_id, logical_role,
                      known_at_us, provenance_json
                 FROM external_input_frames WHERE source_scope = 'global'"""
        ).fetchall()
        before_points = self.storage.connection.execute(
            """SELECT p.point_id, p.point_key, p.valid_at_us, p.value, p.unit, p.point_json
                 FROM external_input_points p
                 JOIN external_input_frames f ON f.frame_id = p.frame_id
                WHERE f.source_scope = 'global'
                ORDER BY p.point_key"""
        ).fetchall()
        persist_eon_grid_economic_snapshot(
            self.storage, "site-a", _binding(), _state(), self.captured
        )
        after_frame = self.storage.connection.execute(
            """SELECT frame_id, semantic_key, source_scope, site_id, logical_role,
                      known_at_us, provenance_json
                 FROM external_input_frames WHERE source_scope = 'global'"""
        ).fetchall()
        after_points = self.storage.connection.execute(
            """SELECT p.point_id, p.point_key, p.valid_at_us, p.value, p.unit, p.point_json
                 FROM external_input_points p
                 JOIN external_input_frames f ON f.frame_id = p.frame_id
                WHERE f.source_scope = 'global'
                ORDER BY p.point_key"""
        ).fetchall()
        self.assertEqual(after_frame, before_frame)
        self.assertEqual(after_points, before_points)

    def test_decision_reader_keeps_site_economic_frames_isolated(self):
        binding_a = _binding(fingerprint="a", street="Street A")
        binding_b = _binding(fingerprint="b", street="Street B")
        captured = datetime(2026, 9, 5, 20, 1, tzinfo=UTC)
        persist_eon_grid_economic_snapshot(self.storage, "site-a", binding_a, _state(street="Street A"), captured)
        persist_eon_grid_economic_snapshot(self.storage, "site-b", binding_b, _state(street="Street B"), captured)
        result = self.storage.read_external_input_frames(
            captured + timedelta(minutes=1),
            source_scope="site", site_id="site-a",
            logical_role="economic.grid.fixed.subscription",
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["site_id"], "site-a")
        self.assertEqual(result[0]["points"][0]["value"], 226.25)


if __name__ == "__main__":
    unittest.main()
