from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.energy_history import energy_history_billing_points


def test_canonical_energy_history_becomes_verified_billing_buckets():
    points = energy_history_billing_points({
        "series": {"import": [{
            "start": "2026-10-06T00:00:00Z",
            "end": "2026-10-06T00:15:00Z",
            "value_kw": 0.74,
        }]},
    })
    assert points == [{
        "timestamp": "2026-10-06T00:00:00+00:00",
        "end": "2026-10-06T00:15:00+00:00",
        "import_kwh": 0.185,
    }]


def test_invalid_canonical_energy_intervals_fail_closed():
    assert energy_history_billing_points({
        "series": {"import": [{
            "start": "2026-10-06T00:00:00Z",
            "end": "2026-10-06T00:15:00Z",
            "value_kw": None,
        }]},
    }) == []
