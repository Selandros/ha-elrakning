from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_eon_source_data_command_and_manager_path_exist():
    websocket = (ROOT / "custom_components/elrakning/websocket.py").read_text()
    manager = (ROOT / "custom_components/elrakning/elnat/eon_manager.py").read_text()
    assert "eon_grid_source_data" in websocket
    assert "async_source_data" in manager
    assert "contract_accounts" in manager
    assert "monthly_transfer" in manager
    assert "quarter_hour_transfer" in manager
    assert "day_transfer" in manager
    assert "trend" in manager
    assert "outages" in manager
    assert "EON_BACKFILL_DAYS = 7" in manager
    assert "EON_BACKFILL_RETRY_HOURS = 6" in manager


def test_source_data_reuses_manager_session_instead_of_logging_in_inline():
    method = manager_text().split("    async def async_source_data", 1)[1].split("    def public_state", 1)[0]
    assert "async_fetch_app_sources" in method
    assert "async_login" not in method


def test_app_source_collector_is_the_single_path_for_normal_and_raw_app_data():
    source = manager_text()
    collector = source.split("    async def async_fetch_app_sources", 1)[1].split("    async def async_save_web_credentials", 1)[0]
    assert "async_get_contract_accounts" in collector
    assert "async_get_locations" in collector
    assert "async_get_grouped_contracts" in collector
    assert "async_get_monthly_transfer" in collector
    assert "async_get_quarter_hour_transfer" in collector
    assert "async_get_daily_transfer" in collector
    assert "async_get_trend" in collector
    assert "async_get_outages" in collector
    assert "_async_fetch_closed_day_backfill" in collector
    assert "async_get_transfer" in source
    assert "self._app_source_snapshot = sources" in collector
    assert "async_fetch_app_sources()" in source.split("    async def async_source_data", 1)[1]
    refresh = source.split("    async def _refresh_app", 1)[1].split("    def _build_app_state", 1)[0]
    assert "await self._async_persist_provider_imports(states)" in refresh


def test_completed_backfill_without_retained_transfer_is_recoverable():
    source = manager_text()
    method = source.split("    async def _async_fetch_closed_day_backfill", 1)[1].split("    async def async_save_web_credentials", 1)[0]
    assert "retained_transfer_dates" in method
    assert "completed_without_payload" in method
    assert "not completed_without_payload" in method


def test_optional_endpoint_failure_does_not_abort_cached_cost_state():
    collector = manager_text().split("    async def async_fetch_app_sources", 1)[1].split("    async def async_save_web_credentials", 1)[0]
    assert 'getattr(err, "code", None) == "reauth_required"' in collector
    assert 'monthly_status.append({"status": "failed"' in collector
    assert 'hourly_status.append({"status": "failed"' in collector
    assert 'quarter_hour_status.append({"status": "failed"' in collector
    assert 'trend_status.append({"status": "failed"' in collector
    assert '"includeElectricityCost": "false"' in collector
    assert "_current_month_trend_cache" in collector
    assert '"status": "stale_cached"' in collector


def test_trend_request_uses_verified_non_cost_request_shape():
    source = (ROOT / "custom_components/elrakning/elnat/eon_client.py").read_text()
    method = source.split("    async def async_get_trend", 1)[1].split("    async def", 1)[0]
    assert '"installations": f"{installation_identifier}:ELECTRICITY:GRID:false"' in method
    assert '"includeElectricityCost": "false"' in method
    assert '"language": "sv"' in method


def test_source_redaction_covers_credentials_and_account_identifiers():
    source = (ROOT / "custom_components/elrakning/elnat/eon_manager.py").read_text()
    assert "from ..diagnostics import sanitize_source_data" in source
    assert "_redact_source_data" in source


def test_manager_preserves_independent_app_and_web_configuration():
    source = manager_text()
    assert 'config["web"] = {"cookies": session.cookies, "customer_id": customer_id}' in source
    assert 'def _config_with_migration' in source
    assert 'self._web_session' in source


def test_web_credentials_do_not_replace_existing_app_configuration():
    source = manager_text()
    method = source.split("    async def async_save_web_credentials", 1)[1].split("    async def async_refresh", 1)[0]
    assert "browser_attestation_required" in method
    assert "_save_config" not in method


def manager_text():
    return (ROOT / "custom_components/elrakning/elnat/eon_manager.py").read_text()
