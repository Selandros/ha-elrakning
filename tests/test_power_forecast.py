from datetime import datetime, timedelta, timezone

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.power_forecast import build_power_forecast


SITE = "site-a"
UTC = timezone.utc


def _row(role, start, value, *, site=SITE, support=1.0, quality="good", generation="gen-a"):
    return {
        "site_id": site,
        "logical_role": role,
        "source_generation_id": generation,
        "interval_start": start,
        "interval_end": start + timedelta(minutes=15),
        "unit": "W",
        "value": value,
        "quality_status": quality,
        "coverage_ratio": support,
        "gap_status": "none",
    }


def _load_frame(points, known_at):
    return {"frames": [{
        "site_id": SITE,
        "frame_id": "load-v2",
        "revision": 1,
        "payload_schema": "load_forecast.v1",
        "known_at": known_at.isoformat(),
        "quality": {"model_version": "load-profile-v2"},
        "points": [{"valid_at": start.isoformat(), "value": value} for start, value in points],
    }]}


def test_forecast_is_site_scoped_and_deterministic_with_battery_sign_split():
    known_at = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)
    rows = []
    for day in (7, 14, 20):
        start = datetime(2026, 9, day, 18, 15, tzinfo=UTC)
        rows.append(_row("battery.power", start, -400))
    future = datetime(2026, 9, 21, 18, 15, tzinfo=UTC)
    result = build_power_forecast(
        SITE, "Europe/Stockholm", rows,
        _load_frame([(future, 1000)], known_at),
        {"this_hour_kwh": 0.6, "next_hour_kwh": None},
        {"binding_fingerprint": "bind", "entities": {"this_hour_kwh": "sensor.solar_hour"}},
        known_at,
    )
    assert result["execution_eligible"] is False
    assert result["actuator_writes_enabled"] is False
    battery = result["battery"]
    assert battery["schema"] == "battery_power_forecast.v1"
    assert battery["available"] is True
    assert result["series"]["charging"]["forecast_points"][0]["value_w"] == 400
    assert result["series"]["discharging"]["forecast_points"][0]["value_w"] == 0
    assert result["series"]["charging"]["forecast_points"][0]["provenance"]["sample_count"] == 3
    assert result == build_power_forecast(
        SITE, "Europe/Stockholm", rows, _load_frame([(future, 1000)], known_at),
        {"this_hour_kwh": 0.6, "next_hour_kwh": None},
        {"binding_fingerprint": "bind", "entities": {"this_hour_kwh": "sensor.solar_hour"}}, known_at,
    )


def test_insufficient_support_and_wrong_site_fail_closed():
    known_at = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)
    rows = [_row("battery.power", datetime(2026, 9, 20, 18, 0, tzinfo=UTC), 0), _row("battery.power", datetime(2026, 9, 14, 18, 0, tzinfo=UTC), 0, site="site-b")]
    result = build_power_forecast(SITE, "Europe/Stockholm", rows, {"frames": []}, {}, None, known_at)
    assert result["battery"]["available"] is False
    assert result["series"]["import"]["available"] is False
    assert result["site_id"] == SITE


def test_grid_balance_splits_import_and_export_without_zero_filling_missing_inputs():
    known_at = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)
    slot = datetime(2026, 9, 21, 18, 15, tzinfo=UTC)
    rows = [_row("battery.power", datetime(2026, 9, day, 18, 15, tzinfo=UTC), 100) for day in (7, 14, 20)]
    result = build_power_forecast(
        SITE, "Europe/Stockholm", rows, _load_frame([(slot, 1000)], known_at),
        {"this_hour_kwh": 0.3, "next_hour_kwh": None},
        {"entities": {"this_hour_kwh": "sensor.solar_hour"}}, known_at,
    )
    assert result["series"]["import"]["available"] is True
    assert result["series"]["export"]["available"] is True
    assert result["series"]["import"]["forecast_points"][0]["value_w"] == 600
    assert result["series"]["export"]["forecast_points"][0]["value_w"] == 0
    assert result["series"]["import"]["forecast_points"][0]["provenance"]["method"] == "load_minus_solar_minus_signed_battery_power"


def test_solar_hour_energy_is_split_only_into_four_aligned_slots():
    known_at = datetime(2026, 9, 21, 17, 50, tzinfo=UTC)
    result = build_power_forecast(
        SITE, "Europe/Stockholm", [], {"frames": []},
        {"this_hour_kwh": 1.2, "next_hour_kwh": 2.0, "power_next_12_hours_kw": 99},
        {"binding_fingerprint": "bind", "entities": {"this_hour_kwh": "sensor.this", "next_hour_kwh": "sensor.next"}}, known_at,
    )
    points = result["series"]["solar"]["forecast_points"]
    assert len(points) == 4
    assert all(point["value_w"] in {1200.0, 2000.0} for point in points)
    assert all(point["provenance"]["source_role"] in {"this_hour_kwh", "next_hour_kwh"} for point in points)
    assert not any(point["provenance"]["source_role"] == "power_next_12_hours_kw" for point in points)
