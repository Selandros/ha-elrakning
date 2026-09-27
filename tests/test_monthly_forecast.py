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


def test_runtime_manager_persists_fail_closed_input_builder_state():
    class Store:
        def __init__(self):
            self.writes = []

        async def async_record_monthly_forecast(self, site_id, forecast):
            self.writes.append((site_id, forecast))
            return {"written": True}

        def monthly_forecast_state(self, site_id):
            return {"evaluations": [], "latest": self.writes[-1][1] if self.writes else None}

    import asyncio

    store = Store()
    manager = MonthlyForecastManager(store)
    result = asyncio.run(manager.async_record_unavailable(
        site_id="site-a", decision_at=datetime(2026, 9, 1, tzinfo=UTC),
        target_month="2026-09", reason="monthly_forecast_input_builder_failed",
    ))
    assert result["available"] is False
    assert result["reasons"] == ["monthly_forecast_input_builder_failed"]
    assert store.writes[0][0] == "site-a"
    assert store.writes[0][1]["fingerprint"] == result["fingerprint"]


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
    assert all(item["import_kw"] == 0.004 for item in result["slots"])


def test_month_end_uses_causal_recent_known_price_fallback_with_provenance():
    decision = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    rows = [{
        "logical_role": "grid.power/import",
        "interval_start": datetime(2026, 8, 25, 12, minute, tzinfo=UTC),
        "value": 4000,
    } for minute in (0, 15, 30, 45)]
    result = build_month_end_slots(
        decision_at=decision,
        month_end=decision + timedelta(hours=1),
        near_term_points=[],
        historical_rows=rows,
        timezone_name="UTC",
        known_price_periods=[{
            "start": (decision - timedelta(hours=1)).isoformat(),
            "end": decision.isoformat(),
            "total_customer_price_ore_per_kwh": 125,
        }],
    )
    assert result["available"] is True
    assert result["price_method_counts"] == {"causal_recent_known_price_fallback": 4}
    assert all(item["price_ore_per_kwh_gross"] == 125 for item in result["slots"])
    assert all(item["price_provenance"]["method"] == "causal_recent_known_price_fallback" for item in result["slots"])


def test_month_end_keeps_trade_profile_when_grid_tariff_is_missing():
    decision = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    rows = [{
        "logical_role": "grid.power/import",
        "interval_start": datetime(2026, 8, 25, 12, minute, tzinfo=UTC),
        "value": 4000,
    } for minute in (0, 15, 30, 45)]
    result = build_month_end_slots(
        decision_at=decision,
        month_end=decision + timedelta(hours=1),
        near_term_points=[],
        historical_rows=rows,
        timezone_name="UTC",
        known_price_periods=[{
            "start": (start := datetime(2026, 8, 25, 12, minute, tzinfo=UTC)).isoformat(),
            "end": (start + timedelta(minutes=15)).isoformat(),
            "trade_customer_price_ore_per_kwh": 125,
            "price_known_at": datetime(2026, 8, 25, 13, tzinfo=UTC).isoformat(),
            "price_source_generation_id": "np-test",
            "price_area": "SE2",
            "price_currency": "SEK",
        } for minute in (0, 15, 30, 45)],
    )
    assert result["available"] is False
    assert result["energy_price_method_counts"] == {"causal_weekday_slot_trade_price_profile": 4}
    assert all(item["price_ore_per_kwh_gross"] is None for item in result["slots"])
    assert all(item["energy_price_ore_per_kwh_gross"] == 125 for item in result["slots"])
    forecast = build_monthly_cost_forecast(
        site_id="site-a", timezone_name="UTC", decision_at=decision,
        target_month="2026-09", actual_cost_to_date_sek=10, actual_import_to_date_kwh=1,
        future_points=result["slots"], price_periods=[],
    )
    assert forecast["available"] is False
    assert forecast["grid_tariff_missing_count"] == 4
    assert forecast["missing_reasons"]["grid_tariff_missing"] == 4
    assert "price_missing" not in forecast["missing_reasons"]
    assert forecast["price_method_counts"] == {}


def test_serialized_total_customer_price_is_a_valid_causal_price_basis():
    decision = datetime(2026, 9, 1, tzinfo=UTC)
    result = build_monthly_cost_forecast(
        site_id="site-a",
        timezone_name="UTC",
        decision_at=decision,
        target_month="2026-09",
        actual_cost_to_date_sek=10,
        actual_import_to_date_kwh=1,
        future_points=_points(decision),
        price_periods=[{
            "start": decision.isoformat(),
            "end": (decision + timedelta(hours=1)).isoformat(),
            "total_customer_price_ore_per_kwh": 125,
        }],
    )
    assert result["available"] is False
    assert result["missing_reasons"]["forecast_slot_missing"] > 0
    assert result["missing_reasons"].get("price_missing") is None


def test_price_fallback_does_not_use_future_known_period_as_past_basis():
    decision = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    rows = [{
        "logical_role": "grid.power/import",
        "interval_start": datetime(2026, 8, 25, 12, minute, tzinfo=UTC),
        "value": 4000,
    } for minute in (0, 15, 30, 45)]
    result = build_month_end_slots(
        decision_at=decision,
        month_end=decision + timedelta(hours=1),
        near_term_points=[],
        historical_rows=rows,
        timezone_name="UTC",
        known_price_periods=[{
            "start": (decision + timedelta(hours=1)).isoformat(),
            "end": (decision + timedelta(hours=2)).isoformat(),
            "total_customer_price_ore_per_kwh": 125,
        }],
    )
    assert result["available"] is False
    assert result["price_missing_slot_count"] == 4


def test_unaligned_decision_uses_next_canonical_slot_without_partial_future_slot():
    decision = datetime(2026, 9, 1, 12, 7, 3, tzinfo=UTC)
    aligned = datetime(2026, 9, 1, 12, 15, tzinfo=UTC)
    rows = [{
        "logical_role": "grid.power/import",
        "interval_start": datetime(2026, 8, 25, 12, minute, tzinfo=UTC),
        "value": 4000,
    } for minute in (15, 30)]
    result = build_month_end_slots(
        decision_at=decision,
        month_end=aligned + timedelta(minutes=30),
        near_term_points=[{
            "valid_at": aligned.isoformat(),
            "end_at": (aligned + timedelta(minutes=15)).isoformat(),
            "import_kw": 2,
            "known_at": decision.isoformat(),
            "provenance": {"source_generation_id": "power-1"},
        }],
        historical_rows=rows,
        timezone_name="UTC",
        known_price_periods=[{
            "start": (aligned - timedelta(minutes=15)).isoformat(),
            "end": aligned.isoformat(),
            "total_customer_price_ore_per_kwh": 125,
        }],
    )
    assert result["slot_count"] == 2
    assert result["method_counts"]["canonical_power_forecast"] == 1
    assert result["method_counts"]["causal_weekday_slot_profile"] == 1
