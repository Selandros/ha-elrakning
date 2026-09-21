from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.power_forecast import build_power_forecast
from custom_components.elrakning.canonical_storage import CanonicalStorage


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


def _soc_row(start, value, *, site=SITE, support=1.0, generation="soc-gen"):
    row = _row("battery.soc", start, value, site=site, support=support, generation=generation)
    row["unit"] = "%"
    return row


def _context_rows(starts, battery_values, *, load=1000.0, solar=600.0, soc=65.0):
    rows = []
    for start, battery in zip(starts, battery_values):
        rows.extend([
            _row("battery.power", start, battery, generation="battery-gen"),
            _soc_row(start, soc),
            _row("house.consumption", start, load, generation="load-gen"),
            _row("solar.production", start, solar / 2, generation="solar-a"),
            _row("solar.production", start, solar / 2, generation="solar-b"),
        ])
    return rows


def _load_frame(points, known_at):
    return {"frames": [{
        "site_id": SITE,
        "frame_id": "load-v2",
        "revision": 1,
        "payload_schema": "load_forecast.v1",
        "known_at": known_at.isoformat(),
        "quality": {"model_version": "load-profile-v2"},
        "points": [{"valid_at": start.isoformat(), "value": value, "unit": "W"} for start, value in points],
    }]}


def test_forecast_is_site_scoped_and_deterministic_with_battery_sign_split():
    known_at = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)
    rows = _context_rows(
        [datetime(2026, 9, day, 18, 15, tzinfo=UTC) for day in (7, 14, 20)],
        [-400, -400, -400],
    )
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
    assert result["series"]["charging"]["forecast_points"][0]["value_w"] == 0
    assert result["series"]["discharging"]["forecast_points"][0]["value_w"] == 400
    assert result["series"]["charging"]["forecast_points"][0]["provenance"]["sample_count"] == 3
    assert result["series"]["charging"]["forecast_points"][0]["provenance"]["context_level"] == "quarter_soc_net"
    assert battery["model_version"] == "battery-behavior-profile-v2"
    assert result == build_power_forecast(
        SITE, "Europe/Stockholm", rows, _load_frame([(future, 1000)], known_at),
        {"this_hour_kwh": 0.6, "next_hour_kwh": None},
        {"binding_fingerprint": "bind", "entities": {"this_hour_kwh": "sensor.solar_hour"}}, known_at,
    )


def test_battery_split_never_emits_negative_magnitudes():
    known_at = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)
    rows = []
    for day in (7, 14, 20):
        rows.extend(_context_rows(
            [datetime(2026, 9, day, 18, minute, tzinfo=UTC) for minute in (15, 30, 45)],
            [-400, 250, 0],
        ))
    result = build_power_forecast(
        SITE, "Europe/Stockholm", rows,
        _load_frame([(datetime(2026, 9, 21, 18, minute, tzinfo=UTC), 1000) for minute in (15, 30, 45)], known_at),
        {"this_hour_kwh": 0.6}, {"entities": {"this_hour_kwh": "sensor.solar_hour"}}, known_at,
    )
    charging = {point["valid_at"]: point["value_w"] for point in result["series"]["charging"]["forecast_points"]}
    discharging = {point["valid_at"]: point["value_w"] for point in result["series"]["discharging"]["forecast_points"]}
    assert all(value >= 0 for value in charging.values())
    assert all(value >= 0 for value in discharging.values())
    assert charging["2026-09-21T18:15:00+00:00"] == 0
    assert discharging["2026-09-21T18:15:00+00:00"] == 400
    assert charging["2026-09-21T18:30:00+00:00"] == 250
    assert discharging["2026-09-21T18:30:00+00:00"] == 0
    assert charging["2026-09-21T18:45:00+00:00"] == 0
    assert discharging["2026-09-21T18:45:00+00:00"] == 0
    assert result["series"]["charging"]["forecast_points"][0]["value_w"] == 0
    assert result["series"]["discharging"]["forecast_points"][0]["value_w"] == 400
    assert result["series"]["charging"]["forecast_points"][0]["provenance"]["sample_count"] == 3


def test_insufficient_support_and_wrong_site_fail_closed():
    known_at = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)
    rows = [_row("battery.power", datetime(2026, 9, 20, 18, 0, tzinfo=UTC), 0), _row("battery.power", datetime(2026, 9, 14, 18, 0, tzinfo=UTC), 0, site="site-b")]
    result = build_power_forecast(SITE, "Europe/Stockholm", rows, {"frames": []}, {}, None, known_at)
    assert result["battery"]["available"] is False
    assert result["series"]["import"]["available"] is False
    assert result["site_id"] == SITE


def test_storage_history_rows_preserve_site_id_for_battery_forecast():
    known_at = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)
    start = datetime(2026, 9, 7, 18, 15, tzinfo=UTC)
    with TemporaryDirectory() as directory:
        storage = CanonicalStorage(Path(directory) / "canonical.sqlite")
        storage.open()
        storage.ensure_source_generation({
            "site_id": SITE,
            "logical_role": "battery.power",
            "generation_id": "battery-gen",
            "source_identity": {"identity_key": "battery-gen", "identity_strength": "strong"},
        }, start)
        for day in (7, 14, 20):
            observed = datetime(2026, 9, day, 18, 15, tzinfo=UTC)
            storage.insert_observation({
                "semantic_key": f"{SITE}|battery.power|battery-gen|{observed.isoformat()}",
                "site_id": SITE,
                "logical_role": "battery.power",
                "source_generation_id": "battery-gen",
                "interval_start": observed,
                "observed_at": observed + timedelta(minutes=14),
                "captured_at": observed + timedelta(minutes=15),
                "known_at": observed + timedelta(minutes=15),
                "classification": "measured",
                "value": -400,
                "unit": "W",
                "sign_convention": "positive_discharge_negative_charge",
                "quality_status": "good",
                "coverage_ratio": 1.0,
                "gap_status": "none",
            })
        rows = storage.read_site_energy_history(SITE, start, known_at)
        assert rows and all(row["site_id"] == SITE for row in rows)
        result = build_power_forecast(SITE, "Europe/Stockholm", rows, {"frames": []}, {}, None, known_at)
        assert result["battery"]["available"] is False
        storage.close()


def test_grid_balance_splits_import_and_export_without_zero_filling_missing_inputs():
    known_at = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)
    slot = datetime(2026, 9, 21, 18, 15, tzinfo=UTC)
    rows = _context_rows([datetime(2026, 9, day, 18, 15, tzinfo=UTC) for day in (7, 14, 20)], [100, 100, 100], load=1000, solar=300)
    result = build_power_forecast(
        SITE, "Europe/Stockholm", rows, _load_frame([(slot, 1000)], known_at),
        {"this_hour_kwh": 0.3, "next_hour_kwh": None},
        {"entities": {"this_hour_kwh": "sensor.solar_hour"}}, known_at,
    )
    assert result["series"]["import"]["available"] is True
    assert result["series"]["export"]["available"] is True
    assert result["series"]["import"]["forecast_points"][0]["value_w"] == 800
    assert result["series"]["export"]["forecast_points"][0]["value_w"] == 0
    assert result["series"]["import"]["forecast_points"][0]["provenance"]["method"] == "load_minus_solar_plus_signed_battery_behavior"


def test_load_forecast_requires_canonical_w_unit():
    known_at = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)
    slot = datetime(2026, 9, 21, 18, 15, tzinfo=UTC)
    frame = _load_frame([(slot, 1000)], known_at)
    frame["frames"][0]["points"][0]["unit"] = "kW"
    result = build_power_forecast(SITE, "Europe/Stockholm", [], frame, {}, None, known_at)
    assert result["series"]["consumption"]["available"] is False


def test_context_fallback_prefers_soc_and_net_load_over_quarter():
    known_at = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)
    rows = _context_rows(
        [datetime(2026, 9, day, 18, 30, tzinfo=UTC) for day in (7, 14, 20)],
        [-300, -300, -300],
    )
    future = datetime(2026, 9, 21, 18, 15, tzinfo=UTC)
    result = build_power_forecast(
        SITE, "Europe/Stockholm", rows, _load_frame([(future, 1000)], known_at),
        {"this_hour_kwh": 0.6}, {"entities": {"this_hour_kwh": "sensor.solar_hour"}}, known_at,
    )
    point = result["battery"]["forecast_points"][0]
    assert point["value_w"] == -300
    assert point["provenance"]["context_level"] == "soc_net"
    assert point["provenance"]["sample_count"] == 3


def test_solar_context_fallback_is_behavior_only_without_soc_feature():
    known_at = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)
    rows = []
    for day in (7, 14, 20):
        start = datetime(2026, 9, day, 19, 0, tzinfo=UTC)
        rows.extend([
            _row("battery.power", start, -700),
            _row("house.consumption", start, 1000),
            _row("solar.production", start, 0, generation="solar-a"),
            _row("solar.production", start, 0, generation="solar-b"),
        ])
    future = datetime(2026, 9, 21, 18, 15, tzinfo=UTC)
    result = build_power_forecast(
        SITE, "Europe/Stockholm", rows, _load_frame([(future, 1000)], known_at),
        {"this_hour_kwh": 0.6}, {"entities": {"this_hour_kwh": "sensor.solar_hour"}}, known_at,
    )
    point = result["battery"]["forecast_points"][0]
    assert point["value_w"] == -700
    assert point["provenance"]["context_level"] == "solar_context"
    assert point["provenance"]["context"]["solar_context"] == "no_solar_surplus"


def test_future_only_context_samples_do_not_train_baseline():
    known_at = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)
    rows = _context_rows(
        [datetime(2026, 9, day, 18, 15, tzinfo=UTC) for day in (21, 22, 23)],
        [-300, -300, -300],
    )
    future = datetime(2026, 9, 21, 18, 15, tzinfo=UTC)
    result = build_power_forecast(
        SITE, "Europe/Stockholm", rows, _load_frame([(future, 1000)], known_at),
        {"this_hour_kwh": 0.6}, {"entities": {"this_hour_kwh": "sensor.solar_hour"}}, known_at,
    )
    assert result["battery"]["available"] is False


def test_insufficient_behavior_support_is_unavailable():
    known_at = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)
    rows = _context_rows(
        [datetime(2026, 9, day, 18, 15, tzinfo=UTC) for day in (7, 14)],
        [-300, -300],
    )
    future = datetime(2026, 9, 21, 18, 15, tzinfo=UTC)
    result = build_power_forecast(
        SITE, "Europe/Stockholm", rows, _load_frame([(future, 1000)], known_at),
        {"this_hour_kwh": 0.6}, {"entities": {"this_hour_kwh": "sensor.solar_hour"}}, known_at,
    )
    assert result["battery"]["available"] is False
    assert result["series"]["import"]["available"] is False


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
