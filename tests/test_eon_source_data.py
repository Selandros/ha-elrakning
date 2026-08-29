from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_eon_source_data_command_and_manager_path_exist():
    websocket = (ROOT / "custom_components/elrakning/websocket.py").read_text()
    manager = (ROOT / "custom_components/elrakning/elnat/eon_manager.py").read_text()
    assert "eon_grid_source_data" in websocket
    assert "async_source_data" in manager
    assert "contract_accounts" in manager
    assert "monthly_transfer" in manager
    assert "outages" in manager


def test_source_redaction_covers_credentials_and_account_identifiers():
    namespace = {}
    source = (ROOT / "custom_components/elrakning/elnat/eon_manager.py").read_text()
    assert "customeridentifier" in source.lower()
    assert "contractaccountidentifier" in source.lower()
    assert "authorization" in source.lower()
