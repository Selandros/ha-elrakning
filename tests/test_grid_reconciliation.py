from datetime import datetime, timedelta, timezone

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.grid_reconciliation import reconcile_grid_import


UTC = timezone.utc


def _row(site, start, value, *, provider=False, padded=False, final=False, record_id="r"):
    return {
        "record_id": record_id,
        "site_id": site,
        "logical_role": "grid.energy_import",
        "interval_start": start,
        "interval_end": start + timedelta(minutes=15),
        "resolution_seconds": 900,
        "value": value,
        "unit": "kWh",
        "quality_status": "good",
        "gap_status": "none",
        "known_at": start + timedelta(hours=1),
        "provenance": ({"provider": "eon", "provider_actual": not padded, "padded": padded, "settlement_authoritative": final} if provider else {}),
    }


def test_provider_fills_gap_and_padded_is_rejected_without_raw_mutation():
    start = datetime(2026, 10, 1, tzinfo=UTC)
    raw = [_row("site-a", start, 0.5, provider=True, record_id="provider")]
    result = reconcile_grid_import(raw)
    assert result[0]["source_status"] == "provider_gap_fill"
    assert result[0]["correction_reason"] == "gap_fill"
    assert raw[0]["value"] == 0.5
    assert reconcile_grid_import([_row("site-a", start, 0.5, provider=True, padded=True)]) == []


def test_local_primary_and_explicit_settlement_correction():
    start = datetime(2026, 10, 1, tzinfo=UTC)
    local = _row("site-a", start, 0.5, record_id="local")
    provider = _row("site-a", start, 0.5, provider=True, final=True, record_id="provider")
    result = reconcile_grid_import([local, provider])
    assert result[0]["source_status"] == "provider_reconciled"
    assert result[0]["correction_reason"] == "provider_reconciliation"


def test_provider_conflict_is_exposed_not_averaged_and_sites_are_isolated():
    start = datetime(2026, 10, 1, tzinfo=UTC)
    result = reconcile_grid_import([
        _row("site-a", start, 0.5, record_id="local-a"),
        _row("site-a", start, 0.8, provider=True, record_id="provider-a"),
        _row("site-b", start, 0.2, provider=True, record_id="provider-b"),
    ])
    by_site = {item["site_id"]: item for item in result}
    assert by_site["site-a"]["source_status"] == "conflict"
    assert by_site["site-a"]["value"] is None
    assert by_site["site-a"]["local_value"] == 0.5
    assert by_site["site-a"]["provider_value"] == 0.8
    assert by_site["site-b"]["source_status"] == "provider_gap_fill"
    assert by_site["site-a"]["provenance"]["site_id"] == "site-a"


def test_resolution_is_exact_bucket_not_disaggregated():
    start = datetime(2026, 10, 1, tzinfo=UTC)
    coarse = _row("site-a", start, 2.0, provider=True, record_id="hour")
    coarse["interval_end"] = start + timedelta(hours=1)
    coarse["resolution_seconds"] = 3600
    result = reconcile_grid_import([coarse])
    assert len(result) == 1
    assert result[0]["resolution_seconds"] == 3600
    assert result[0]["interval_end"] == start + timedelta(hours=1)


def test_finer_provider_resolution_prevents_double_counting_coarser_bucket():
    start = datetime(2026, 10, 1, tzinfo=UTC)
    quarter = _row("site-a", start, 0.5, provider=True, record_id="quarter")
    hour = _row("site-a", start, 2.0, provider=True, record_id="hour")
    hour["interval_end"] = start + timedelta(hours=1)
    hour["resolution_seconds"] = 3600
    result = reconcile_grid_import([hour, quarter])
    assert [(item["resolution_seconds"], item["value"]) for item in result] == [(900, 0.5)]
