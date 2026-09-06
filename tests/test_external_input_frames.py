import tempfile
import unittest
import sqlite3
import hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.canonical_storage import CanonicalStorage
from custom_components.elrakning.external_input_frames import (
    build_nord_pool_frame,
    persist_nord_pool_frame,
)


UTC = timezone.utc


def price_data(values):
    start = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    periods = tuple(
        SimpleNamespace(start=start + timedelta(minutes=15 * index), end=start + timedelta(minutes=15 * (index + 1)), price=value)
        for index, value in enumerate(values)
    )
    return SimpleNamespace(area="SE2", currency="SEK", date=date(2026, 9, 5), periods=periods)


class ExternalInputFrameTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.storage = CanonicalStorage(Path(self.directory.name) / "canonical.sqlite")
        self.storage.open()
        self.binding = {"config_entry_id": "np-entry", "area": "SE2", "currency": "SEK"}

    def tearDown(self):
        self.storage.close()
        self.directory.cleanup()

    def test_global_nord_pool_frame_round_trips_and_is_idempotent(self):
        data = price_data([0.42, 0.43])
        captured = datetime(2026, 9, 5, 1, 0, tzinfo=UTC)
        self.assertTrue(persist_nord_pool_frame(self.storage, data, self.binding, captured))
        self.assertFalse(persist_nord_pool_frame(self.storage, data, self.binding, captured + timedelta(minutes=15)))
        self.assertEqual(self.storage.count_external_frames(), 1)
        row = self.storage.connection.execute(
            "SELECT source_scope, site_id, logical_role, known_at_us, valid_from_us, valid_to_us FROM external_input_frames"
        ).fetchone()
        self.assertEqual(row[:3], ("global", None, "market.price.energy"))
        self.assertEqual(row[3], int(captured.timestamp() * 1_000_000))
        self.assertEqual(self.storage.connection.execute("SELECT COUNT(*) FROM external_input_points").fetchone()[0], 2)

    def test_changed_real_periods_create_revision_without_destroying_old_frame(self):
        data = price_data([0.42, 0.43])
        captured = datetime(2026, 9, 5, 1, 0, tzinfo=UTC)
        persist_nord_pool_frame(self.storage, data, self.binding, captured)
        changed = price_data([0.99, 0.43])
        persist_nord_pool_frame(self.storage, changed, self.binding, captured + timedelta(minutes=20))
        self.assertFalse(persist_nord_pool_frame(self.storage, changed, self.binding, captured + timedelta(minutes=30)))
        rows = self.storage.connection.execute(
            "SELECT revision, supersedes_frame_id FROM external_input_frames ORDER BY revision"
        ).fetchall()
        self.assertEqual([row[0] for row in rows], [1, 2])
        self.assertIsNotNone(rows[1][1])

    def test_source_scope_mismatch_is_rejected(self):
        data = price_data([0.42])
        frame, points = build_nord_pool_frame(data, self.binding, datetime.now(UTC))
        frame["source_scope"] = "site"
        frame["site_id"] = "site-a"
        with self.assertRaises(ValueError):
            self.storage.insert_external_frame(frame, points)

    def test_unknown_or_nonfinite_point_is_rejected(self):
        data = price_data([0.42])
        frame, points = build_nord_pool_frame(data, self.binding, datetime.now(UTC))
        points[0]["value"] = float("nan")
        self.storage.ensure_global_source_generation(
            {
                "generation_id": frame["source_generation_id"],
                "logical_role": frame["logical_role"],
                "source_identity": {"identity_key": "np-entry|SE2|SEK", "identity_strength": "strong"},
            },
            datetime.now(UTC),
        )
        with self.assertRaises(ValueError):
            self.storage.insert_external_frame(frame, points)

    def test_points_are_immutable(self):
        persist_nord_pool_frame(
            self.storage, price_data([0.42, 0.43]), self.binding,
            datetime(2026, 9, 5, 1, 0, tzinfo=UTC),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.storage.connection.execute(
                "UPDATE external_input_points SET value = 99 WHERE point_key LIKE '2026-%'"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.storage.connection.execute(
                "DELETE FROM external_input_points WHERE point_key LIKE '2026-%'"
            )

    def test_external_frame_write_rolls_back_frame_and_points_on_point_failure(self):
        frame, points = build_nord_pool_frame(
            price_data([0.42, 0.43]), self.binding,
            datetime(2026, 9, 5, 1, 0, tzinfo=UTC),
        )
        self.storage.ensure_global_source_generation(
            {
                "generation_id": frame["source_generation_id"],
                "logical_role": frame["logical_role"],
                "source_identity": {"identity_key": "np-entry|SE2|SEK", "identity_strength": "strong"},
            },
            datetime(2026, 9, 5, 1, 0, tzinfo=UTC),
        )
        points[1]["valid_at"] = datetime(2026, 9, 6, 0, 0, tzinfo=UTC)
        with self.assertRaises(ValueError):
            self.storage.insert_external_frame(frame, points)
        self.assertEqual(self.storage.count_external_frames(), 0)
        self.assertEqual(
            self.storage.connection.execute("SELECT COUNT(*) FROM external_input_points").fetchone()[0],
            0,
        )

    def test_decision_time_reader_selects_known_revision_and_target_point(self):
        first_capture = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
        second_capture = datetime(2026, 9, 5, 14, 0, tzinfo=UTC)
        persist_nord_pool_frame(self.storage, price_data([0.42, 0.43]), self.binding, first_capture)
        persist_nord_pool_frame(self.storage, price_data([0.99, 0.43]), self.binding, second_capture)
        target = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
        before_correction = self.storage.read_external_input_frames(
            datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
            source_scope="global", logical_role="market.price.energy", valid_at=target,
        )
        after_correction = self.storage.read_external_input_frames(
            datetime(2026, 9, 5, 15, 0, tzinfo=UTC),
            source_scope="global", logical_role="market.price.energy", valid_at=target,
        )
        self.assertEqual(len(before_correction), 1)
        self.assertEqual(before_correction[0]["revision"], 1)
        self.assertEqual(before_correction[0]["points"][0]["value"], 0.42)
        self.assertEqual(len(after_correction), 1)
        self.assertEqual(after_correction[0]["revision"], 2)
        self.assertEqual(after_correction[0]["points"][0]["value"], 0.99)

    def test_future_frames_are_invisible_and_source_generation_is_explicit(self):
        first_capture = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
        second_capture = datetime(2026, 9, 5, 14, 0, tzinfo=UTC)
        first_binding = self.binding
        second_binding = {**self.binding, "config_entry_id": "np-entry-2"}
        persist_nord_pool_frame(self.storage, price_data([0.42]), first_binding, first_capture)
        persist_nord_pool_frame(self.storage, price_data([0.52]), second_binding, second_capture)
        target = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
        before = self.storage.read_external_input_frames(
            datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
            source_scope="global", logical_role="market.price.energy", valid_at=target,
        )
        self.assertEqual(len(before), 1)
        expected_generation = "np-" + hashlib.sha256(
            "nord_pool|np-entry|SE2|SEK".encode()
        ).hexdigest()[:32]
        self.assertEqual(before[0]["source_generation_id"], expected_generation)
        after = self.storage.read_external_input_frames(
            datetime(2026, 9, 5, 15, 0, tzinfo=UTC),
            source_scope="global", logical_role="market.price.energy", valid_at=target,
            source_generation_id=before[0]["source_generation_id"],
        )
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]["points"][0]["value"], 0.42)

    def test_invalid_reader_scope_and_decision_timestamps_fail_closed(self):
        with self.assertRaises(ValueError):
            self.storage.read_external_input_frames(
                datetime(2026, 9, 5, 12, 0, tzinfo=UTC), source_scope="site"
            )
        with self.assertRaises(ValueError):
            self.storage.read_external_input_frames(
                datetime(2026, 9, 5, 12, 0), source_scope="global"
            )

    def test_integrity_migration_is_idempotent_across_reopen(self):
        migration = self.storage.connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version = 2"
        ).fetchone()
        self.assertIsNotNone(migration)
        self.storage.close()
        self.storage.open()
        self.assertEqual(
            self.storage.connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' "
                "AND name IN ('point_immutable_update', 'point_immutable_delete')"
            ).fetchone()[0],
            2,
        )


if __name__ == "__main__":
    unittest.main()
