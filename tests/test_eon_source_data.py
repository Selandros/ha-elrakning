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


def test_source_data_reuses_manager_session_instead_of_logging_in_inline():
    method = manager_text().split("    async def async_source_data", 1)[1].split("    async def async_app_test_login", 1)[0]
    assert "_get_app_session" in method
    assert "async_login" not in method


def test_source_redaction_covers_credentials_and_account_identifiers():
    namespace = {}
    source = (ROOT / "custom_components/elrakning/elnat/eon_manager.py").read_text()
    assert "customeridentifier" in source.lower()
    assert "contractaccountidentifier" in source.lower()
    assert "authorization" in source.lower()


def test_manager_preserves_independent_app_and_web_configuration():
    source = manager_text()
    assert 'config["web"] = {"cookies": session.cookies, "customer_id": customer_id}' in source
    assert 'config.update({' in source
    assert 'def _config_with_migration' in source
    assert 'self._web_session' in source


def manager_text():
    return (ROOT / "custom_components/elrakning/elnat/eon_manager.py").read_text()
