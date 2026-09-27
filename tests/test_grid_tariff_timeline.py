from datetime import datetime, timezone

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)

install_elrakning_package_stub()
install_homeassistant_stubs()
install_optional_dependency_stubs()

from custom_components.elrakning.grid_tariff_timeline import (
    build_grid_tariff_record,
    merge_grid_tariff_record,
    resolve_grid_tariff,
)


SITE = "site-vik"
BINDING = {"config_entry_id": "eon-entry"}
CAPTURED = datetime(2026, 9, 27, 20, tzinfo=timezone.utc)


def _state(status="FUTURE", start="2026-10-01", updated="2026-09-27T19:00:00+00:00"):
    return {
        "agreement": {"status": status, "source_status": status, "start_date": start},
        "facility": {"installation_identifier": "installation", "price_area": "SE2"},
        "grid_price": {
            "fixed_monthly_sek": 226.25,
            "variable_total_ore_per_kwh_gross": 142.0,
            "vat_included": True,
            "price_basis": "gross",
            "contract_source_status": status,
        },
        "updated_at": updated,
    }


def test_future_tariff_does_not_price_september_but_switches_on_effective_date():
    record = build_grid_tariff_record(site_id=SITE, binding=BINDING, state=_state(), captured_at=CAPTURED)
    records = merge_grid_tariff_record([], record)
    assert resolve_grid_tariff(records, site_id=SITE, at=datetime(2026, 9, 30, 21, tzinfo=timezone.utc), decision_at=CAPTURED) is None
    resolved = resolve_grid_tariff(records, site_id=SITE, at=datetime(2026, 10, 1, 0, tzinfo=timezone.utc), decision_at=CAPTURED)
    assert resolved["grid_price"]["variable_total_ore_per_kwh_gross"] == 142.0


def test_timeline_is_idempotent_and_site_scoped():
    record = build_grid_tariff_record(site_id=SITE, binding=BINDING, state=_state(), captured_at=CAPTURED)
    records = merge_grid_tariff_record([], record)
    assert merge_grid_tariff_record(records, record) == records
    assert resolve_grid_tariff(records, site_id="other-site", at=datetime(2026, 10, 1, tzinfo=timezone.utc), decision_at=CAPTURED) is None


def test_missing_effective_start_never_infers_past_validity():
    state = _state()
    state["agreement"].pop("start_date")
    assert build_grid_tariff_record(site_id=SITE, binding=BINDING, state=state, captured_at=CAPTURED) is None
