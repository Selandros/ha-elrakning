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
    build_user_confirmed_grid_tariff_record,
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


def _manual_fact():
    return {
        "site_id": SITE,
        "provider": "eon",
        "product_name": "16 A, upp till 8000 kWh/år. Elnätsområde Nord",
        "source_status": "MANUALLY_VERIFIED",
        "facility": {
            "installation_identifier": "installation",
            "grid_area": "MEL",
            "price_area": "SE 2",
            "fuse_ampere": 16.0,
        },
        "agreement": {
            "status": "MANUALLY_VERIFIED",
            "source_status": "MANUALLY_VERIFIED",
            "name": "16 A, upp till 8000 kWh/år. Elnätsområde Nord",
            "start_date": "2026-09-01",
            "end_date": "2026-10-01",
        },
        "grid_price": {
            "fixed_monthly_sek": 226.25,
            "variable_total_ore_per_kwh_gross": 142.0,
            "vat_included": True,
            "price_basis": "gross",
            "contract_source_status": "MANUALLY_VERIFIED",
        },
        "provenance": {"verification_method": "user_confirmed_manual_fact"},
    }


def _manual_state():
    return {
        "agreement": {
            "status": "future",
            "name": "16 A, upp till 8000 kWh/år. Elnätsområde Nord",
        },
        "facility": _manual_fact()["facility"],
    }


def test_user_confirmed_tariff_is_september_only_and_keeps_provenance():
    manual = build_user_confirmed_grid_tariff_record(
        site_id=SITE,
        binding={"config_entry_id": "eon-entry", "facility": _manual_fact()["facility"]},
        state=_manual_state(),
        fact=_manual_fact(),
        captured_at=CAPTURED,
    )
    future = build_grid_tariff_record(site_id=SITE, binding=BINDING, state=_state(), captured_at=CAPTURED)
    records = merge_grid_tariff_record(merge_grid_tariff_record([], manual), future)
    sep = resolve_grid_tariff(
        records, site_id=SITE, at=datetime(2026, 9, 30, 21, tzinfo=timezone.utc), decision_at=CAPTURED
    )
    oct = resolve_grid_tariff(
        records, site_id=SITE, at=datetime(2026, 10, 1, 0, tzinfo=timezone.utc), decision_at=CAPTURED
    )
    assert sep["source_status"] == "MANUALLY_VERIFIED"
    assert sep["provenance"]["origin"] == "user_confirmed"
    assert sep["provenance"]["provider_api_verified"] is False
    assert oct["source_status"] == "FUTURE"
    assert oct["provenance"]["origin"] == "eon_grid_state"


def test_user_confirmed_tariff_requires_exact_runtime_identity_and_is_deterministic():
    fact = _manual_fact()
    binding = {"config_entry_id": "eon-entry", "facility": fact["facility"]}
    first = build_user_confirmed_grid_tariff_record(
        site_id=SITE, binding=binding, state=_manual_state(), fact=fact, captured_at=CAPTURED
    )
    second = build_user_confirmed_grid_tariff_record(
        site_id=SITE, binding=binding, state=_manual_state(), fact=fact, captured_at=CAPTURED.replace(hour=21)
    )
    assert first["source_generation_id"] == second["source_generation_id"]
    mismatched = dict(_manual_state())
    mismatched["facility"] = {**mismatched["facility"], "price_area": "SE 3"}
    assert build_user_confirmed_grid_tariff_record(
        site_id=SITE, binding=binding, state=mismatched, fact=fact, captured_at=CAPTURED
    ) is None


def _timeline_record(generation, known_at, valid_from, valid_to, price, site=SITE):
    return {
        "schema": "elrakning.grid_tariff_timeline.v1",
        "site_id": site,
        "provider": "eon",
        "source_generation_id": generation,
        "known_at": known_at,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "grid_price": {"variable_total_ore_per_kwh_gross": price},
    }


def test_resolver_uses_causal_applicable_historical_revision_not_future_record():
    records = [
        _timeline_record(
            "october",
            "2026-09-29T22:00:00+00:00",
            "2026-09-30T22:00:00+00:00",
            None,
            150.0,
        ),
        _timeline_record(
            "september",
            "2026-09-27T22:21:31+00:00",
            "2026-08-31T22:00:00+00:00",
            "2026-09-30T22:00:00+00:00",
            142.0,
        ),
    ]
    resolved = resolve_grid_tariff(
        records,
        site_id=SITE,
        at=datetime(2026, 9, 30, 1, 15, tzinfo=timezone.utc),
        decision_at=datetime(2026, 9, 30, 1, 15, tzinfo=timezone.utc),
    )
    assert resolved["source_generation_id"] == "september"


def test_resolver_revision_choice_is_independent_of_input_order():
    records = [
        _timeline_record("old", "2026-09-27T22:00:00+00:00", "2026-08-31T22:00:00+00:00", "2026-09-30T22:00:00+00:00", 140.0),
        _timeline_record("new", "2026-09-28T12:00:00+00:00", "2026-08-31T22:00:00+00:00", "2026-09-30T22:00:00+00:00", 142.0),
    ]
    decision = datetime(2026, 9, 30, 7, 15, tzinfo=timezone.utc)
    first = resolve_grid_tariff(records, site_id=SITE, at=decision, decision_at=decision)
    second = resolve_grid_tariff(list(reversed(records)), site_id=SITE, at=decision, decision_at=decision)
    assert first["source_generation_id"] == second["source_generation_id"] == "new"


def test_resolver_rejects_future_known_or_effective_records_and_wrong_site():
    decision = datetime(2026, 9, 30, 7, 15, tzinfo=timezone.utc)
    records = [
        _timeline_record("known-later", "2026-10-01T00:00:00+00:00", "2026-08-31T22:00:00+00:00", "2026-09-30T22:00:00+00:00", 142.0),
        _timeline_record("effective-later", "2026-09-27T22:00:00+00:00", "2026-09-30T22:00:00+00:00", None, 150.0),
        _timeline_record("wrong-site", "2026-09-27T22:00:00+00:00", "2026-08-31T22:00:00+00:00", "2026-09-30T22:00:00+00:00", 142.0, site="other"),
    ]
    assert resolve_grid_tariff(records, site_id=SITE, at=decision, decision_at=decision) is None
