import asyncio
import copy
from datetime import datetime, timezone, timedelta

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.ella_learning import EllaLearningStore, MAX_POWER_RECORDS_PER_SITE


class _Store:
    def __init__(self, value=None):
        self.value = value

    async def async_load(self):
        return copy.deepcopy(self.value)

    async def async_save(self, value):
        self.value = copy.deepcopy(value)


def test_learning_store_is_site_scoped_bounded_and_restart_safe():
    async def run():
        store = EllaLearningStore(object())
        store.store = _Store()
        for index in range(520):
            await store.async_record("site-a", {
                "records": [{"frame_id": f"frame-{index}", "revision": 1, "valid_at": f"2026-09-{index // 20 + 1:02d}T00:00:00+00:00"}],
                "summary": {"count": 1},
            }, {"factor": 1.0})
        assert len(store.state["sites"]["site-a"]["records"]) == 512
        assert store.public_state("site-b")["available"] is False
        restarted = EllaLearningStore(object())
        restarted.store = _Store(store.state)
        await restarted.async_load()
        assert len(restarted.state["sites"]["site-a"]["records"]) == 512
        assert restarted.public_state("site-a")["calibration"] == {"factor": 1.0}
    asyncio.run(run())


def test_learning_store_does_not_create_execution_failure_without_actuator():
    async def run():
        store = EllaLearningStore(object())
        store.store = _Store()
        await store.async_record("site-a", {"records": []}, {"factor": 1.0})
        result = store.public_state("site-a")
        assert result["available"] is False
    asyncio.run(run())


def test_persistent_calibration_is_prior_day_site_scoped_and_bounded():
    async def run():
        store = EllaLearningStore(object())
        store.store = _Store()
        for index in range(3):
            await store.async_record("site-a", {
                "records": [{
                    "frame_id": f"prior-{index}", "revision": 1,
                    "valid_at": f"2026-09-{3 + index * 7:02d}T18:00:00+00:00",
                    "baseline_w": 1000, "actual_w": 600, "learning_eligible": True,
                }],
            }, {})
        calibration = store.persistent_calibration("site-a", "Europe/Stockholm", __import__("datetime").datetime(2026, 9, 20, 12, tzinfo=__import__("datetime").timezone.utc))
        assert calibration["by_slot"]
        assert next(iter(calibration["by_slot"].values()))["factor"] < 1.0
        assert store.persistent_calibration("site-b", "Europe/Stockholm", __import__("datetime").datetime(2026, 9, 20, 12, tzinfo=__import__("datetime").timezone.utc))["by_slot"] == {}
    asyncio.run(run())


def test_power_forecast_evidence_is_immutable_scored_and_calibrated_per_context():
    async def run():
        store = EllaLearningStore(object())
        store.store = _Store()
        known_at = datetime(2026, 9, 20, 19, 0, tzinfo=timezone.utc)
        now = datetime(2026, 9, 20, 21, 0, tzinfo=timezone.utc)
        points = {}
        for index in range(3):
            start = known_at + timedelta(hours=1, minutes=index * 15)
            points[start.isoformat()] = {
                "value_w": 100.0,
                "provenance": {
                    "context_level": "near_zero_discharge_coverage_ratio",
                    "sample_count": 16,
                    "confidence": "supported",
                },
            }
        forecast = {
            "schema": "ella_power_forecast.v1", "site_id": "site-a",
            "known_at": known_at.isoformat(), "horizon": {"date": "2026-09-20"},
            "battery": {"forecast_points": [
                {"valid_at": key, "end_at": (datetime.fromisoformat(key) + timedelta(minutes=15)).isoformat(), **value}
                for key, value in points.items()
            ]},
            "series": {},
        }
        actual = [{
            "site_id": "site-a", "logical_role": "battery.power", "unit": "W",
            "interval_start": datetime.fromisoformat(key),
            "interval_end": datetime.fromisoformat(key) + timedelta(minutes=15),
            "value": 90.0, "coverage_ratio": 1.0, "quality_status": "good",
            "gap_status": "complete", "source_generation_id": "battery-a",
        } for key in points]
        first = await store.async_record_power_forecast("site-a", forecast, actual, now)
        assert first["written"] is True
        assert first["evaluated"] == 3
        assert first["calibration"]["by_context"]["near_zero_discharge_coverage_ratio"]["factor"] < 1.0
        assert len(store.state["sites"]["site-a"]["power_forecasts"]) == 1
        original = copy.deepcopy(store.state["sites"]["site-a"]["power_forecasts"][0])
        forecast["battery"]["forecast_points"][0]["value_w"] = 9999.0
        assert store.state["sites"]["site-a"]["power_forecasts"][0] == original
        assert store.public_state("site-b")["power_forecast"]["available"] is False
        second = await store.async_record_power_forecast("site-a", forecast, actual, now)
        assert second["evaluated"] == 0
        assert len(store.state["sites"]["site-a"]["power_records"]) == 3

    asyncio.run(run())


def test_power_learning_matures_retained_snapshot_on_later_cadence_and_is_combined():
    async def run():
        store = EllaLearningStore(object())
        store.store = _Store()
        start = datetime(2026, 9, 20, 10, 15, tzinfo=timezone.utc)
        end = start + timedelta(minutes=15)

        def forecast(known_at, valid_at, value):
            return {
                "schema": "ella_power_forecast.v1", "site_id": "site-a",
                "known_at": known_at.isoformat(), "horizon": {"date": "2026-09-20"},
                "battery": {"forecast_points": [{
                    "valid_at": valid_at.isoformat(), "end_at": end.isoformat(), "value_w": value,
                    "provenance": {"context_level": "net_load_ratio"},
                }]}, "series": {},
            }

        actual = [{
            "site_id": "site-a", "logical_role": "battery.power", "unit": "W",
            "interval_start": start, "interval_end": end, "value": 80.0,
            "coverage_ratio": 1.0, "quality_status": "good", "gap_status": "complete",
            "source_generation_id": "battery-active",
        }]
        first = await store.async_record_power_forecast(
            "site-a", forecast(datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc), start, 100.0),
            actual, datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc),
            {"battery.power": {"battery-active"}},
        )
        assert first["evaluated"] == 0
        second = await store.async_record_power_forecast(
            "site-a", forecast(datetime(2026, 9, 20, 10, 30, tzinfo=timezone.utc), end, 120.0),
            actual, datetime(2026, 9, 20, 10, 45, tzinfo=timezone.utc),
            {"battery.power": {"battery-active"}},
        )
        assert second["evaluated"] == 1
        records = store.state["sites"]["site-a"]["power_records"]
        assert len(records) == 1
        assert records[0]["valid_at"] == start.isoformat()
        assert records[0]["forecast_id"] == store.state["sites"]["site-a"]["power_forecasts"][0]["forecast_id"]
        assert records[0]["series"]["battery"]["signed_error_w"] == -20.0
        assert records[0]["battery_context_level"] == "net_load_ratio"
        repeated = await store.async_record_power_forecast(
            "site-a", forecast(datetime(2026, 9, 20, 10, 45, tzinfo=timezone.utc), end + timedelta(minutes=15), 130.0),
            actual, datetime(2026, 9, 20, 11, 0, tzinfo=timezone.utc),
            {"battery.power": {"battery-active"}},
        )
        assert repeated["evaluated"] == 0
        assert len(store.state["sites"]["site-a"]["power_records"]) == 1

    asyncio.run(run())


def test_power_learning_uses_active_generation_and_enforces_end_gate():
    async def run():
        store = EllaLearningStore(object())
        store.store = _Store()
        known_at = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
        start = datetime(2026, 9, 20, 10, 15, tzinfo=timezone.utc)
        end = start + timedelta(minutes=15)
        forecast = {
            "site_id": "site-a", "known_at": known_at.isoformat(), "horizon": {},
            "battery": {"forecast_points": [{"valid_at": start.isoformat(), "end_at": end.isoformat(), "value_w": 100.0, "provenance": {"context_level": "net_load_ratio"}}]},
            "series": {},
        }
        rows = []
        for generation, value in (("battery-closed", -900.0), ("battery-active", 80.0)):
            rows.append({"site_id": "site-a", "logical_role": "battery.power", "unit": "W", "interval_start": start, "interval_end": end, "value": value, "coverage_ratio": 1.0, "quality_status": "good", "gap_status": "complete", "source_generation_id": generation})
        before_end = await store.async_record_power_forecast("site-a", forecast, rows, start + timedelta(minutes=14), {"battery.power": {"battery-active"}})
        assert before_end["evaluated"] == 0
        after_end = await store.async_record_power_forecast("site-a", forecast, rows, end, {"battery.power": {"battery-active"}})
        assert after_end["evaluated"] == 1
        assert store.state["sites"]["site-a"]["power_records"][0]["series"]["battery"]["actual_w"] == 80.0
        assert MAX_POWER_RECORDS_PER_SITE >= 2880

    asyncio.run(run())


def test_legacy_power_records_are_dropped_without_touching_load_learning():
    async def run():
        legacy = {
            "schema": "ella_learning_state.v1", "version": 1,
            "sites": {"site-a": {
                "records": [{"frame_id": "load", "valid_at": "2026-09-20T10:00:00+00:00"}],
                "power_records": [{"series": "battery", "valid_at": "2026-09-20T10:15:00+00:00", "predicted_w": 100.0}],
            }},
        }
        store = EllaLearningStore(object())
        store.store = _Store(legacy)
        await store.async_load()
        assert store.state["sites"]["site-a"]["power_records"] == []
        assert len(store.state["sites"]["site-a"]["records"]) == 1
        assert store.public_state("site-a")["power_forecast"]["available"] is False
        assert store.persistent_power_calibration("site-a")["by_context"] == {}

    asyncio.run(run())


def test_near_zero_small_prediction_scores_but_does_not_calibrate():
    async def run():
        store = EllaLearningStore(object())
        store.store = _Store()
        known_at = datetime(2026, 9, 20, 19, 0, tzinfo=timezone.utc)
        valid_at = datetime(2026, 9, 20, 19, 15, tzinfo=timezone.utc)
        forecast = {
            "site_id": "site-a", "known_at": known_at.isoformat(), "horizon": {},
            "battery": {"forecast_points": [{"valid_at": valid_at.isoformat(), "end_at": (valid_at + timedelta(minutes=15)).isoformat(), "value_w": 50.0, "provenance": {"context_level": "near_zero_discharge_coverage_ratio"}}]},
            "series": {},
        }
        actual = [{"site_id": "site-a", "logical_role": "battery.power", "unit": "W", "interval_start": valid_at, "interval_end": valid_at + timedelta(minutes=15), "value": 40.0, "coverage_ratio": 1.0, "quality_status": "good", "gap_status": "complete", "source_generation_id": "battery-a"}]
        result = await store.async_record_power_forecast("site-a", forecast, actual, valid_at + timedelta(minutes=15))
        assert result["evaluated"] == 1
        assert result["calibration"]["by_context"] == {}
        assert store.state["sites"]["site-a"]["power_records"][0]["series"]["battery"]["absolute_error_w"] == 10.0

    asyncio.run(run())


def test_power_learning_normalizes_forecast_offsets_to_utc_slot_keys():
    async def run():
        store = EllaLearningStore(object())
        store.store = _Store()
        plus_two = timezone(timedelta(hours=2))
        known_at = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
        valid_at = datetime(2026, 9, 20, 12, 15, tzinfo=plus_two)
        end_at = valid_at + timedelta(minutes=15)
        forecast = {
            "site_id": "site-a", "known_at": known_at.isoformat(), "horizon": {},
            "battery": {"forecast_points": [{"valid_at": valid_at.isoformat(), "end_at": end_at.isoformat(), "value_w": 100.0, "provenance": {"context_level": "net_load_ratio"}}]},
            "series": {},
        }
        actual_start = valid_at.astimezone(timezone.utc)
        actual = [{"site_id": "site-a", "logical_role": "battery.power", "unit": "W", "interval_start": actual_start, "interval_end": actual_start + timedelta(minutes=15), "value": 90.0, "coverage_ratio": 1.0, "quality_status": "good", "gap_status": "complete", "source_generation_id": "battery-a"}]
        result = await store.async_record_power_forecast("site-a", forecast, actual, actual_start + timedelta(minutes=15))
        assert result["evaluated"] == 1
        assert store.state["sites"]["site-a"]["power_records"][0]["valid_at"] == "2026-09-20T10:15:00+00:00"

    asyncio.run(run())


def test_power_forecast_learning_requires_causal_qualified_actual_and_is_restart_safe():
    async def run():
        store = EllaLearningStore(object())
        store.store = _Store()
        known_at = datetime(2026, 9, 20, 20, 0, tzinfo=timezone.utc)
        valid_at = datetime(2026, 9, 20, 20, 15, tzinfo=timezone.utc)
        forecast = {
            "site_id": "site-a", "known_at": known_at.isoformat(), "horizon": {},
            "battery": {"forecast_points": [{
                "valid_at": valid_at.isoformat(), "end_at": (valid_at + timedelta(minutes=15)).isoformat(),
                "value_w": 100.0, "provenance": {"context_level": "net_load_ratio"},
            }]}, "series": {},
        }
        poor_actual = [{
            "site_id": "site-a", "logical_role": "battery.power", "unit": "W",
            "interval_start": valid_at, "interval_end": valid_at + timedelta(minutes=15),
            "value": 100.0, "coverage_ratio": 0.5, "quality_status": "partial", "gap_status": "partial",
        }]
        result = await store.async_record_power_forecast("site-a", forecast, poor_actual, valid_at + timedelta(hours=1))
        assert result["evaluated"] == 0
        restarted = EllaLearningStore(object())
        restarted.store = _Store(store.state)
        await restarted.async_load()
        assert restarted.public_state("site-a")["power_forecast"]["evaluation_count"] == 0

    asyncio.run(run())
