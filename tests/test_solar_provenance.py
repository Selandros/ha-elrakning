import unittest
from datetime import datetime, timezone

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)

install_elrakning_package_stub()
install_homeassistant_stubs()
install_optional_dependency_stubs()

from custom_components.elrakning.solar_provenance import (
    FORECAST_SOLAR_DATASET,
    OPEN_METEO_EVIDENCE_DATASET,
    append_immutable,
    build_provenance_record,
    classify_record,
    select_for_decision,
)


def _record(value, known_at, dataset=FORECAST_SOLAR_DATASET):
    instant = datetime.fromisoformat(known_at.replace("Z", "+00:00"))
    return build_provenance_record(
        site_id="site-vik",
        source="forecast_solar" if dataset.startswith("forecast") else "open_meteo",
        dataset=dataset,
        target="local_day:2026-09-12",
        value=value,
        unit="kWh",
        captured_at=instant,
        known_at=instant,
        fetched_at=instant if dataset == OPEN_METEO_EVIDENCE_DATASET else None,
    )


class SolarProvenanceTests(unittest.TestCase):
    def test_same_knowledge_has_stable_identity_even_when_recaptured(self):
        first = _record(12.5, "2026-09-11T20:00:00Z")
        second = _record(12.5, "2026-09-11T21:00:00Z")
        self.assertEqual(first["frame_fingerprint"], second["frame_fingerprint"])

    def test_changed_knowledge_is_retained_as_distinct_observation(self):
        records = []
        self.assertTrue(append_immutable(records, _record(12.5, "2026-09-11T20:00:00Z")))
        self.assertTrue(append_immutable(records, _record(13.5, "2026-09-11T21:00:00Z")))
        self.assertEqual(len(records), 2)
        self.assertEqual([item["revision"] for item in records], [1, 2])

    def test_duplicate_capture_does_not_overwrite_causal_history(self):
        records = []
        item = _record(12.5, "2026-09-11T20:00:00Z")
        self.assertTrue(append_immutable(records, item))
        self.assertFalse(append_immutable(records, dict(item)))
        self.assertEqual(len(records), 1)

    def test_pre_decision_selection_excludes_post_decision_observation(self):
        records = [
            _record(12.5, "2026-09-11T20:00:00Z"),
            _record(13.5, "2026-09-12T02:00:00Z"),
        ]
        status, selected = select_for_decision(
            records,
            site_id="site-vik",
            dataset=FORECAST_SOLAR_DATASET,
            target="local_day:2026-09-12",
            decision_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(status, "VERIFIED_PRE_DECISION")
        self.assertEqual(selected["value"], 12.5)

    def test_multiple_same_time_values_fail_closed(self):
        records = [
            _record(12.5, "2026-09-11T20:00:00Z"),
            _record(13.5, "2026-09-11T20:00:00Z"),
        ]
        status, selected = select_for_decision(
            records,
            site_id="site-vik",
            dataset=FORECAST_SOLAR_DATASET,
            target="local_day:2026-09-12",
            decision_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(status, "AMBIGUOUS")
        self.assertIsNone(selected)

    def test_missing_known_at_fails_closed(self):
        item = _record(12.5, "2026-09-11T20:00:00Z")
        item["known_at"] = None
        self.assertEqual(
            classify_record(item, datetime(2026, 9, 12, tzinfo=timezone.utc)),
            "INSUFFICIENT_PROVENANCE",
        )

    def test_open_meteo_evidence_dataset_is_not_manager_dataset(self):
        self.assertNotEqual(OPEN_METEO_EVIDENCE_DATASET, "open_meteo.manager_forecast.v1")


if __name__ == "__main__":
    unittest.main()
