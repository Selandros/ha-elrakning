from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "invoice.py"
_spec = spec_from_file_location("elrakning_invoice_source_selection", _path)
_module = module_from_spec(_spec)
_spec.loader.exec_module(_module)
select_billing_energy_source = _module.select_billing_energy_source


def test_reconciled_p1_merge_wins_over_raw_meter_history():
    raw = [{"timestamp": "2026-10-01T00:00:00+02:00", "import_kw": 0.4}]
    reconciled = [{"timestamp": "2026-10-01T00:00:00+02:00", "import_kwh": 0.1, "source": "p1"}]

    points, source = select_billing_energy_source(raw, reconciled, [])

    assert points == reconciled
    assert source == "reconciled_grid_import"


def test_raw_meter_is_fallback_when_no_canonical_energy_exists():
    raw = [{"timestamp": "2026-10-01T00:00:00+02:00", "import_kw": 0.4}]

    points, source = select_billing_energy_source(raw, [], [])

    assert points == raw
    assert source == "local_meter_history"
