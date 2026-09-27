from datetime import datetime, timedelta, timezone

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.monthly_forecast import build_actual_priced_cost_to_date, build_month_end_slots, build_monthly_cost_forecast
from custom_components.elrakning.monthly_forecast_manager import MonthlyForecastManager


UTC = timezone.utc


def _points(start, count=4, value=2.0):
    return [
        {
            "valid_at": (start + timedelta(minutes=15 * index)).isoformat(),
            "end_at": (start + timedelta(minutes=15 * (index + 1))).isoformat(),
            "import_kw": value,
            "known_at": datetime(2026, 9, 1, tzinfo=UTC).isoformat(),
            "provenance": {"source_generation_id": "grid-forecast-1"},
        }
        for index in range(count)
    ]


def test_monthly_forecast_is_deterministic_and_site_scoped():
    decision = datetime(2026, 9, 1, tzinfo=UTC)
    points = _points(decision)
    periods = [{"start": decision.isoformat(), "end": (decision + timedelta(hours=1)).isoformat(), "total_ore_per_kwh_gross": 100}]
    first = build_monthly_cost_forecast(
        site_id="site-a", timezone_name="UTC", decision_at=decision,
        target_month="2026-09", actual_cost_to_date_sek=10, actual_import_to_date_kwh=1,
        future_points=points, price_periods=periods, source_generations=["grid-forecast-1"],
    )
    second = build_monthly_cost_forecast(
        site_id="site-a", timezone_name="UTC", decision_at=decision,
        target_month="2026-09", actual_cost_to_date_sek=10, actual_import_to_date_kwh=1,
        future_points=points, price_periods=periods, source_generations=["grid-forecast-1"],
    )
    assert first == second
    assert first["site_id"] == "site-a"
    assert first["execution_eligible"] is False
    assert first["actuator_writes_enabled"] is False


def test_missing_future_slot_fails_closed_and_never_becomes_future_cost():
    decision = datetime(2026, 9, 1, tzinfo=UTC)
    result = build_monthly_cost_forecast(
        site_id="site-a", timezone_name="UTC", decision_at=decision,
        target_month="2026-09", actual_cost_to_date_sek=20, actual_import_to_date_kwh=5,
        future_points=_points(decision, count=1),
        price_periods=[{"start": decision.isoformat(), "end": (decision + timedelta(minutes=15)).isoformat(), "total_ore_per_kwh_gross": 100}],
    )
    assert result["available"] is False
    assert result["estimated_month_total_sek"] is None
    assert result["expected_future_cost_sek"] is None
    assert "causal_future_slot_or_price_missing" in result["reasons"]


def test_ambiguous_overlap_fails_closed():
    decision = datetime(2026, 9, 1, tzinfo=UTC)
    points = _points(decision, count=1)
    points.append({**points[0], "import_kw": 3.0})
    result = build_monthly_cost_forecast(
        site_id="site-a", timezone_name="UTC", decision_at=decision,
        target_month="2026-09", actual_cost_to_date_sek=0, actual_import_to_date_kwh=0,
        future_points=points,
        price_periods=[{"start": decision.isoformat(), "end": (decision + timedelta(minutes=15)).isoformat(), "total_ore_per_kwh_gross": 100}],
    )
    assert result["available"] is False
    assert result["reasons"] == ["ambiguous_forecast_slot"]


def test_missing_past_is_not_added_to_future():
    decision = datetime(2026, 9, 1, tzinfo=UTC)
    result = build_monthly_cost_forecast(
        site_id="site-a", timezone_name="UTC", decision_at=decision,
        target_month="2026-09", actual_cost_to_date_sek=12, actual_import_to_date_kwh=0,
        future_points=[], price_periods=[],
    )
    assert result["available"] is False
    assert result["expected_future_cost_sek"] is None
    assert result["actual_cost_to_date_sek"] == 12


def test_runtime_manager_deduplicates_snapshots_and_marks_legacy_fallback():
    class Store:
        def __init__(self):
            self.writes = 0

        async def async_record_monthly_forecast(self, site_id, forecast):
            self.writes += 1
            return {"written": True}

        def monthly_forecast_state(self, site_id):
            return {"evaluations": [], "latest": None}

    store = Store()
    manager = MonthlyForecastManager(store)
    import asyncio

    kwargs = {
        "site_id": "site-a", "timezone_name": "UTC", "decision_at": datetime(2026, 9, 1, tzinfo=UTC),
        "target_month": "2026-09", "actual_cost_to_date_sek": 10, "actual_import_to_date_kwh": 1,
        "future_points": [], "price_periods": [],
    }
    first = asyncio.run(manager.async_refresh(**kwargs))
    second = asyncio.run(manager.async_refresh(**kwargs))
    assert first["forecast_method"] == "legacy_explicit_fallback_required"
    assert second["forecast_method"] == "legacy_explicit_fallback_required"
    assert store.writes == 1


def test_actual_import_keeps_unpriced_energy_out_of_cost():
    start = datetime(2026, 9, 1, tzinfo=UTC)
    points = [
        {"timestamp": start.isoformat(), "import_kw": 2},
        {"timestamp": (start + timedelta(minutes=15)).isoformat(), "import_kw": 2},
        {"timestamp": (start + timedelta(minutes=30)).isoformat(), "import_kw": 2},
    ]
    result = build_actual_priced_cost_to_date(
        points=points,
        price_periods=[{"start": start.isoformat(), "end": (start + timedelta(minutes=15)).isoformat(), "trade_customer_price_ore_per_kwh": 100, "grid_variable_ore_per_kwh": 50}],
        month_start=start, now=start + timedelta(minutes=30),
    )
    assert result["actual_import_to_date_kwh"] == 1.0
    assert result["priced_import_to_date_kwh"] == 0.5
    assert result["missing_past_import_kwh"] == 0.5
    assert result["actual_cost_to_date_sek"] == 0.75


def test_month_end_profile_is_not_blind_36h_repetition():
    decision = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    rows = [{"logical_role": "grid.power/import", "interval_start": datetime(2026, 8, 25, 12, minute, tzinfo=UTC), "value": 4} for minute in (0, 15, 30, 45)]
    result = build_month_end_slots(
        decision_at=decision, month_end=decision + timedelta(hours=1),
        near_term_points=[], historical_rows=rows, timezone_name="UTC", known_price_periods=[],
    )
    assert result["slot_count"] == 4
    assert result["fallback_slot_count"] == 4
    assert all(item["method"] == "causal_weekday_slot_profile" for item in result["slots"])
