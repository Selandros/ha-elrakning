"""Websocket access to Elräkning's cached price periods."""

from __future__ import annotations

import asyncio
import logging
import inspect
import json
import time
from functools import partial
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    EON_GRID_UPDATE_EVENT,
    ELECTRICITY_PROVIDER_UPDATE_EVENT,
    GREENELY_PROVIDER,
    NORD_POOL_DOMAIN,
    SUPPORTED_ELECTRICITY_PROVIDERS,
)
from .coordinator import ElrakningCoordinator, PriceData
from .customer_price import build_customer_price_data, grid_price_is_current, grid_variable_cost_ex_vat
from .energy_history import async_build_energy_history
from .elhandel.manager import CHART_LAYER_DEFAULTS, MAIN_CARD_DEFAULTS, PHASE_HISTORY_METRICS, PHASE_HISTORY_VISIBLE_DEFAULTS, PRICE_COMPARISON_DEFAULTS, ElhandelManager
from .elhandel.models import ProviderData, serialize_provider_state
from .elhandel.providers.greenely_client import GreenelyClient, GreenelyError
from .elhandel.providers.greenely_consumption import normalize_greenely_consumption
from .elhandel.providers.greenely_source import paginate_source
from .elnat.manager import GridManager
from .elnat.provider_registry import GRID_PROVIDER_REGISTRY
from .meter import MeterManager
from .invoice import build_today_variable_cost
from .power import PowerManager
from .load_forecast import build_historical_model_points
from .ella_capabilities import build_capability_inventory
from .ella_site_state import build_site_state, resolve_timezone
from .ella_action_plan import build_action_plan
from .ella_stage6 import build_stage6_state
from .ella_ess_twin import build_ess_digital_twin, resolve_shared_ess_resource
from .economic_optimizer import build_economic_plan, build_eon_economics, derive_provider_reference
from .ella_ess_facts import EllaEssFactsStore
from .replay_artifact_store import ReplayArtifactStore
from .ella_economic_policy import EllaEconomicPolicyStore
from .power_forecast import build_power_forecast
from .ella_execution import EllaExecutionStore
from .price_only_planner import build_price_only_plan, enrich_plan_with_load
from .solar_forecast import SolarForecastManager
from .solar_single_run import build_single_run_targets
from .solar_weather import build_sun_context
from .site_identity import SiteIdentityManager

COMMAND = f"{DOMAIN}/price_data"
GREENELY_TEST_COMMAND = f"{DOMAIN}/greenely_test"
GREENELY_CONSUMPTION_TEST_COMMAND = f"{DOMAIN}/greenely_consumption_test"
GREENELY_PARSE_LATEST_COMMAND = f"{DOMAIN}/greenely_parse_latest_test"
ELECTRICITY_PROVIDER_STATE_COMMAND = f"{DOMAIN}/electricity_provider_state"
ELECTRICITY_PROVIDER_SAVE_COMMAND = f"{DOMAIN}/electricity_provider_save"
ELECTRICITY_PROVIDER_SOURCE_DATA_COMMAND = f"{DOMAIN}/electricity_provider_source_data"
ELECTRICITY_PROVIDER_REMOVE_COMMAND = f"{DOMAIN}/electricity_provider_remove"
EON_GRID_STATE_COMMAND = f"{DOMAIN}/eon_grid_state"
EON_GRID_SAVE_COMMAND = f"{DOMAIN}/eon_grid_save"
EON_GRID_APP_SAVE_COMMAND = f"{DOMAIN}/eon_grid_app_save"
EON_GRID_WEB_SAVE_COMMAND = f"{DOMAIN}/eon_grid_web_save"
EON_GRID_SOURCE_DATA_COMMAND = f"{DOMAIN}/eon_grid_source_data"
EON_GRID_REMOVE_COMMAND = f"{DOMAIN}/eon_grid_remove"
GRID_PROVIDERS_COMMAND = f"{DOMAIN}/grid/providers"
GRID_STATE_COMMAND = f"{DOMAIN}/grid/state"
GRID_LOGIN_COMMAND = f"{DOMAIN}/grid/login"
GRID_SOURCE_DATA_COMMAND = f"{DOMAIN}/grid/source_data"
GRID_WEB_HANDOFF_START_COMMAND = f"{DOMAIN}/grid/web_handoff_start"
GRID_REMOVE_COMMAND = f"{DOMAIN}/grid/remove"
ELECTRICITY_HISTORY_STATE_COMMAND = f"{DOMAIN}/electricity_history_state"
ELECTRICITY_HISTORY_PURGE_COMMAND = f"{DOMAIN}/electricity_history_purge"
DIAGNOSTICS_STATE_COMMAND = f"{DOMAIN}/diagnostics_state"
CANONICAL_COLLECTOR_STATE_COMMAND = f"{DOMAIN}/canonical_collector_state"
DIAGNOSTICS_CLEAR_COMMAND = f"{DOMAIN}/diagnostics_clear"
FRONTEND_PREFERENCES_COMMAND = f"{DOMAIN}/frontend_preferences"
FRONTEND_PREFERENCES_SET_COMMAND = f"{DOMAIN}/frontend_preferences_set"
CHART_LAYERS_COMMAND = f"{DOMAIN}/ui_preferences/get"
CHART_LAYERS_SET_COMMAND = f"{DOMAIN}/ui_preferences/set"
METER_SAVE_COMMAND = f"{DOMAIN}/meter_save"
METER_DIAGNOSTIC_COMMAND = f"{DOMAIN}/meter_diagnostic"
METER_STATE_COMMAND = f"{DOMAIN}/meter_state"
METER_SOURCE_COMMAND = f"{DOMAIN}/meter_source"
METER_STORE_CLEAR_COMMAND = f"{DOMAIN}/meter_store_clear"
METER_POWER_HISTORY_COMMAND = f"{DOMAIN}/meter_power_history"
BILLING_HISTORY_COMMAND = f"{DOMAIN}/billing_history"
POWER_SAVE_COMMAND = f"{DOMAIN}/power_save"
POWER_STATE_COMMAND = f"{DOMAIN}/power_state"
POWER_HISTORY_COMMAND = f"{DOMAIN}/power_history"
POWER_HISTORY_ENRICHMENT_COMMAND = f"{DOMAIN}/power_history_enrichment"
POWER_FORECAST_COMMAND = f"{DOMAIN}/power_forecast"
LOAD_FORECAST_COMMAND = f"{DOMAIN}/load_forecast"
FORECAST_EVALUATION_COMMAND = f"{DOMAIN}/ella_forecast_evaluation"
SITE_IDENTITY_COMMAND = f"{DOMAIN}/site_identity"
SITE_RENAME_COMMAND = f"{DOMAIN}/site_rename"
SITE_CREATE_COMMAND = f"{DOMAIN}/site_create"
SITE_ACTIVATE_COMMAND = f"{DOMAIN}/site_activate"
ELLA_BINDING_SET_COMMAND = f"{DOMAIN}/ella_binding_set"
SOLAR_FORECAST_STATE_COMMAND = f"{DOMAIN}/solar_forecast_state"
SOLAR_EVIDENCE_STATE_COMMAND = f"{DOMAIN}/solar_evidence_state"
ELLA_PLAN_COMMAND = f"{DOMAIN}/ella_plan"
ELLA_CAPABILITIES_COMMAND = f"{DOMAIN}/ella_capabilities"
ELLA_LOADS_LIST_COMMAND = f"{DOMAIN}/ella_loads/list"
ELLA_LOADS_STATE_COMMAND = f"{DOMAIN}/ella_loads/state"
ELLA_LOADS_UPSERT_COMMAND = f"{DOMAIN}/ella_loads/upsert"
ELLA_LOADS_REMOVE_COMMAND = f"{DOMAIN}/ella_loads/remove"
ELLA_SITE_STATE_COMMAND = f"{DOMAIN}/ella_site_state"
ELLA_ACTION_PLAN_COMMAND = f"{DOMAIN}/ella_action_plan"
ELLA_DEBUG_SNAPSHOT_COMMAND = f"{DOMAIN}/ella_action_plan/debug"
ELLA_EXECUTION_STATE_COMMAND = f"{DOMAIN}/ella_execution/state"
ELLA_EXECUTION_PERMISSION_SET_COMMAND = f"{DOMAIN}/ella_execution/permission_set"
ELLA_EXECUTION_OVERRIDE_COMMAND = f"{DOMAIN}/ella_execution/manual_override"
ELLA_EXECUTION_DISPATCH_COMMAND = f"{DOMAIN}/ella_execution/dispatch"
ECONOMIC_OPTIMIZER_COMMAND = f"{DOMAIN}/economic_optimizer"
ESS_FACTS_LIST_COMMAND = f"{DOMAIN}/ess_facts/list"
ESS_FACTS_IMPORT_COMMAND = f"{DOMAIN}/ess_facts/import"
REPLAY_ARTIFACT_APPEND_COMMAND = f"{DOMAIN}/replay_artifact/append"
REPLAY_ARTIFACT_LIST_COMMAND = f"{DOMAIN}/replay_artifact/list"
REPLAY_BENCHMARK_EVIDENCE_COMMAND = f"{DOMAIN}/replay_benchmark_evidence"
ECONOMIC_POLICY_IMPORT_COMMAND = f"{DOMAIN}/economic_policy/import"
ECONOMIC_POLICY_STATE_COMMAND = f"{DOMAIN}/economic_policy/state"
UPDATE_EVENT = "elrakning_price_update"
_LOGGER = logging.getLogger(__name__)


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register the websocket command once per Home Assistant instance."""
    if hass.data.get(f"{DOMAIN}_websocket_registered"):
        return
    websocket_api.async_register_command(hass, websocket_get_price_data)
    websocket_api.async_register_command(hass, websocket_greenely_test)
    websocket_api.async_register_command(hass, websocket_greenely_consumption_test)
    websocket_api.async_register_command(hass, websocket_electricity_provider_state)
    websocket_api.async_register_command(hass, websocket_electricity_provider_save)
    websocket_api.async_register_command(hass, websocket_greenely_parse_latest)
    websocket_api.async_register_command(hass, websocket_electricity_provider_source_data)
    websocket_api.async_register_command(hass, websocket_electricity_provider_remove)
    websocket_api.async_register_command(hass, websocket_eon_grid_state)
    websocket_api.async_register_command(hass, websocket_eon_grid_save)
    websocket_api.async_register_command(hass, websocket_eon_grid_app_save)
    websocket_api.async_register_command(hass, websocket_eon_grid_web_save)
    websocket_api.async_register_command(hass, websocket_eon_grid_source_data)
    websocket_api.async_register_command(hass, websocket_eon_grid_remove)
    websocket_api.async_register_command(hass, websocket_grid_providers)
    websocket_api.async_register_command(hass, websocket_grid_state)
    websocket_api.async_register_command(hass, websocket_grid_login)
    websocket_api.async_register_command(hass, websocket_grid_source_data)
    websocket_api.async_register_command(hass, websocket_grid_web_handoff_start)
    websocket_api.async_register_command(hass, websocket_grid_remove)
    websocket_api.async_register_command(hass, websocket_electricity_history_state)
    websocket_api.async_register_command(hass, websocket_electricity_history_purge)
    websocket_api.async_register_command(hass, websocket_diagnostics_state)
    websocket_api.async_register_command(hass, websocket_canonical_collector_state)
    websocket_api.async_register_command(hass, websocket_diagnostics_clear)
    websocket_api.async_register_command(hass, websocket_frontend_preferences)
    websocket_api.async_register_command(hass, websocket_frontend_preferences_set)
    websocket_api.async_register_command(hass, websocket_chart_layers)
    websocket_api.async_register_command(hass, websocket_chart_layers_set)
    _LOGGER.debug("websocket_command_name=%s registered", METER_SAVE_COMMAND)
    websocket_api.async_register_command(hass, websocket_meter_save)
    websocket_api.async_register_command(hass, websocket_meter_diagnostic)
    websocket_api.async_register_command(hass, websocket_meter_state)
    websocket_api.async_register_command(hass, websocket_meter_source)
    websocket_api.async_register_command(hass, websocket_meter_store_clear)
    websocket_api.async_register_command(hass, websocket_meter_power_history)
    websocket_api.async_register_command(hass, websocket_billing_history)
    websocket_api.async_register_command(hass, websocket_power_save)
    websocket_api.async_register_command(hass, websocket_power_state)
    websocket_api.async_register_command(hass, websocket_power_history)
    websocket_api.async_register_command(hass, websocket_power_history_enrichment)
    websocket_api.async_register_command(hass, websocket_power_forecast)
    websocket_api.async_register_command(hass, websocket_load_forecast)
    websocket_api.async_register_command(hass, websocket_ella_forecast_evaluation)
    websocket_api.async_register_command(hass, websocket_site_identity)
    websocket_api.async_register_command(hass, websocket_site_rename)
    websocket_api.async_register_command(hass, websocket_site_create)
    websocket_api.async_register_command(hass, websocket_site_activate)
    websocket_api.async_register_command(hass, websocket_ella_binding_set)
    websocket_api.async_register_command(hass, websocket_ella_plan)
    websocket_api.async_register_command(hass, websocket_ella_capabilities)
    websocket_api.async_register_command(hass, websocket_ella_loads_list)
    websocket_api.async_register_command(hass, websocket_ella_loads_state)
    websocket_api.async_register_command(hass, websocket_ella_loads_upsert)
    websocket_api.async_register_command(hass, websocket_ella_loads_remove)
    websocket_api.async_register_command(hass, websocket_ella_site_state)
    websocket_api.async_register_command(hass, websocket_ella_action_plan)
    websocket_api.async_register_command(hass, websocket_ella_debug_snapshot)
    websocket_api.async_register_command(hass, websocket_ella_execution_state)
    websocket_api.async_register_command(hass, websocket_ella_execution_permission_set)
    websocket_api.async_register_command(hass, websocket_ella_execution_override)
    websocket_api.async_register_command(hass, websocket_ella_execution_dispatch)
    websocket_api.async_register_command(hass, websocket_economic_optimizer)
    websocket_api.async_register_command(hass, websocket_ess_facts_list)
    websocket_api.async_register_command(hass, websocket_ess_facts_import)
    websocket_api.async_register_command(hass, websocket_replay_artifact_append)
    websocket_api.async_register_command(hass, websocket_replay_artifact_list)
    websocket_api.async_register_command(hass, websocket_replay_benchmark_evidence)
    websocket_api.async_register_command(hass, websocket_economic_policy_import)
    websocket_api.async_register_command(hass, websocket_economic_policy_state)
    websocket_api.async_register_command(hass, websocket_solar_forecast_state)
    websocket_api.async_register_command(hass, websocket_solar_evidence_state)
    hass.data[f"{DOMAIN}_websocket_registered"] = True


@websocket_api.websocket_command({vol.Required("type"): COMMAND, vol.Optional("date"): str})
@websocket_api.async_response
async def websocket_get_price_data(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Return cached periods and discovered Nord Pool sensor values."""
    entry = next(iter(hass.config_entries.async_entries(DOMAIN)), None)
    coordinator: ElrakningCoordinator | None = entry.runtime_data if entry else None
    data = None
    if coordinator:
        requested_date = msg.get("date")
        if requested_date:
            try:
                target_date = date.fromisoformat(requested_date)
                current_data = coordinator.data
                data = (
                    current_data
                    if current_data and current_data.date == target_date and current_data.periods
                    else await coordinator.async_get_price_data(target_date)
                )
            except ValueError:
                data = None
        else:
            data = coordinator.data
    response = _serialize_price_data(hass, data)
    if data is not None and data.periods:
        site_manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
        collector = hass.data.get(DOMAIN, {}).get("canonical_collector")
        response["energy_history"] = await async_build_energy_history(
            hass, site_manager, collector,
            min(period.start for period in data.periods),
            max(period.end for period in data.periods),
        )
    connection.send_result(msg["id"], response)


@websocket_api.websocket_command(
    {
        vol.Required("type"): GREENELY_TEST_COMMAND,
        vol.Required("email"): str,
        vol.Required("password"): str,
    }
)
@websocket_api.async_response
async def websocket_greenely_test(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Test Greenely credentials and return sanitized facility metadata."""
    email = msg.get("email")
    password = msg.get("password")
    if not isinstance(email, str) or not email.strip() or not isinstance(password, str) or not password:
        connection.send_result(msg["id"], {"success": False, "error": "invalid_input"})
        return
    try:
        client = GreenelyClient(hass)
        await client.async_login(email.strip(), password)
        facilities = await client.async_get_facilities()
    except GreenelyError as err:
        _LOGGER.warning("Greenely test failed: %s", err.code)
        connection.send_result(msg["id"], {"success": False, "error": err.code})
        return
    if not facilities:
        _LOGGER.warning("Greenely test failed: no_facilities")
        connection.send_result(msg["id"], {"success": False, "error": "no_facilities"})
        return
    connection.send_result(msg["id"], {"success": True, "facilities": [_sanitize_facility(item) for item in facilities]})


def _sanitize_facility(facility: dict) -> dict:
    """Return only safe discovery fields and names of non-sensitive fields."""
    result = {"raw_keys": sorted(key for key in facility if _safe_key_name(key))}
    for key in ("id", "is_primary", "name", "address"):
        value = facility.get(key)
        if key == "is_primary" and isinstance(value, bool):
            result[key] = value
        elif key in ("id", "name", "address") and isinstance(value, (str, int)):
            result[key] = str(value)
    return result


@websocket_api.websocket_command({
    vol.Required("type"): ECONOMIC_OPTIMIZER_COMMAND,
    vol.Optional("inputs"): dict,
    vol.Optional("site_id"): str,
})
@websocket_api.async_response
async def websocket_economic_optimizer(hass, connection, msg):
    """Return a read-only deterministic Step 8 plan or an explicit unavailable result."""
    inputs = msg.get("inputs")
    if not isinstance(inputs, dict):
        site_manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
        site_id = msg.get("site_id") or (site_manager.state.get("active_site_id") if site_manager else None)
        inputs = await _async_optimizer_runtime_inputs(hass, site_id)
    facts_store = hass.data.get(DOMAIN, {}).get("ella_ess_facts_store")
    if isinstance(inputs, dict) and isinstance(facts_store, EllaEssFactsStore):
        inputs = facts_store.apply_to_optimizer_inputs(inputs)
    if isinstance(inputs, dict) and "economics" not in inputs:
        site_manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
        grid_manager = hass.data.get(DOMAIN, {}).get("grid_manager")
        binding = site_manager.active_binding("grid") if site_manager and hasattr(site_manager, "active_binding") else None
        grid_state = grid_manager.public_state_for_binding(binding) if grid_manager and binding else None
        normalized_economics = build_eon_economics(grid_state, binding, inputs.get("known_at")) if isinstance(grid_state, dict) else None
        if normalized_economics is not None:
            inputs["economics"] = normalized_economics
    policy_store = hass.data.get(DOMAIN, {}).get("ella_economic_policy_store")
    if isinstance(inputs, dict) and isinstance(policy_store, EllaEconomicPolicyStore):
        economics = inputs.get("economics")
        if isinstance(economics, dict) and isinstance(inputs.get("site_id"), str):
            override = policy_store.resolve(inputs["site_id"], inputs.get("known_at"))
            if override is not None and "planning_applicability_override" not in economics:
                inputs["economics"] = {**economics, "planning_applicability_override": override}
    result = build_economic_plan(inputs)
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({vol.Required("type"): ESS_FACTS_LIST_COMMAND, vol.Required("site_id"): str})
@websocket_api.async_response
async def websocket_ess_facts_list(hass, connection, msg):
    """Return non-secret manually verified ESS facts for one exact site."""
    store = hass.data.get(DOMAIN, {}).get("ella_ess_facts_store")
    facts = store.list_site(msg["site_id"]) if isinstance(store, EllaEssFactsStore) else []
    connection.send_result(msg["id"], {"schema": "ella_ess_facts.v1", "site_id": msg["site_id"], "facts": facts})


@websocket_api.websocket_command({vol.Required("type"): REPLAY_ARTIFACT_APPEND_COMMAND, vol.Required("artifact"): dict})
@websocket_api.async_response
async def websocket_replay_artifact_append(hass, connection, msg):
    """Persist one already-built immutable replay artifact without execution."""
    store = hass.data.get(DOMAIN, {}).get("replay_artifact_store")
    if not isinstance(store, ReplayArtifactStore):
        connection.send_error(msg["id"], "not_ready", "Replay artifact store is not ready")
        return
    accepted = await store.async_append(msg["artifact"])
    connection.send_result(msg["id"], {"schema": "ella_replay_artifact.v1", "accepted": accepted})


@websocket_api.websocket_command({vol.Required("type"): REPLAY_ARTIFACT_LIST_COMMAND, vol.Required("site_id"): str})
@websocket_api.async_response
async def websocket_replay_artifact_list(hass, connection, msg):
    """Return immutable artifacts for one exact site only."""
    store = hass.data.get(DOMAIN, {}).get("replay_artifact_store")
    records = store.state.get("sites", {}).get(msg["site_id"], []) if isinstance(store, ReplayArtifactStore) else []
    connection.send_result(msg["id"], {"schema": "ella_replay_artifact.v1", "site_id": msg["site_id"], "artifacts": records})


@websocket_api.websocket_command({vol.Required("type"): REPLAY_BENCHMARK_EVIDENCE_COMMAND, vol.Required("site_id"): str})
@websocket_api.async_response
async def websocket_replay_benchmark_evidence(hass, connection, msg):
    """Return bounded readiness evidence for one exact site."""
    store = hass.data.get(DOMAIN, {}).get("replay_artifact_store")
    evidence = store.public_evidence(msg["site_id"]) if isinstance(store, ReplayArtifactStore) else {
        "schema": "ella_replay_benchmark_evidence.v1", "site_id": msg["site_id"], "available": False, "status": "unavailable", "blocker": "store_unavailable",
    }
    connection.send_result(msg["id"], evidence)


@websocket_api.websocket_command({vol.Required("type"): ESS_FACTS_IMPORT_COMMAND, vol.Required("facts"): list})
@websocket_api.async_response
async def websocket_ess_facts_import(hass, connection, msg):
    """Append/update verified facts through authenticated HA WebSocket access."""
    store = hass.data.get(DOMAIN, {}).get("ella_ess_facts_store")
    if not isinstance(store, EllaEssFactsStore):
        connection.send_error(msg["id"], "not_ready", "ESS facts store is not ready")
        return
    accepted = await store.async_upsert(msg["facts"])
    connection.send_result(msg["id"], {"schema": "ella_ess_facts.v1", "accepted": accepted})


@websocket_api.websocket_command({vol.Required("type"): ECONOMIC_POLICY_IMPORT_COMMAND, vol.Required("override"): dict})
@websocket_api.async_response
async def websocket_economic_policy_import(hass, connection, msg):
    """Persist an explicit applicability decision without copying tariff values."""
    store = hass.data.get(DOMAIN, {}).get("ella_economic_policy_store")
    if not isinstance(store, EllaEconomicPolicyStore):
        connection.send_error(msg["id"], "not_ready", "Economic policy store is not ready")
        return
    override = dict(msg["override"])
    if not isinstance(override.get("provider_reference"), str):
        site_manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
        grid_manager = hass.data.get(DOMAIN, {}).get("grid_manager")
        active_site = getattr(site_manager, "state", {}).get("active_site_id") if site_manager else None
        binding = site_manager.active_binding("grid") if site_manager and hasattr(site_manager, "active_binding") else None
        if override.get("site_id") != active_site or not grid_manager or not binding:
            connection.send_result(msg["id"], {"schema": "ella_economic_policy.v1", "accepted": False, "error": "provider_reference_unavailable"})
            return
        grid_state = grid_manager.public_state_for_binding(binding)
        reference = derive_provider_reference(grid_state, binding) if isinstance(grid_state, dict) else None
        agreement = grid_state.get("agreement") if isinstance(grid_state, dict) else None
        if not reference or not isinstance(agreement, dict) or not isinstance(agreement.get("start_date"), str):
            connection.send_result(msg["id"], {"schema": "ella_economic_policy.v1", "accepted": False, "error": "provider_reference_unavailable"})
            return
        override["provider_reference"] = reference
        override.setdefault("provider_valid_from", agreement["start_date"])
    accepted = await store.async_upsert(override)
    connection.send_result(msg["id"], {"schema": "ella_economic_policy.v1", "accepted": accepted})


@websocket_api.websocket_command({vol.Required("type"): ECONOMIC_POLICY_STATE_COMMAND, vol.Required("site_id"): str})
@websocket_api.async_response
async def websocket_economic_policy_state(hass, connection, msg):
    """Return the persisted applicability metadata for one exact site."""
    store = hass.data.get(DOMAIN, {}).get("ella_economic_policy_store")
    state = store.state.get("sites", {}).get(msg["site_id"], {}) if isinstance(store, EllaEconomicPolicyStore) else {}
    connection.send_result(msg["id"], {"schema": "ella_economic_policy.v1", "site_id": msg["site_id"], "state": state})


def _safe_key_name(key: object) -> bool:
    """Exclude names that suggest credential or personal security metadata."""
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return not any(
        word in lowered
        for word in (
            "personal",
            "personnummer",
            "phone",
            "cell_phone",
            "first_name",
            "last_name",
            "email",
            "customer",
            "token",
            "password",
            "secret",
            "auth",
            "ssn",
        )
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): GREENELY_CONSUMPTION_TEST_COMMAND,
        vol.Required("email"): str,
        vol.Required("password"): str,
        vol.Required("facility_id"): str,
    }
)
@websocket_api.async_response
async def websocket_greenely_consumption_test(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Test Greenely consumption response shape without exposing raw data."""
    email = msg.get("email")
    password = msg.get("password")
    facility_id = msg.get("facility_id")
    if (
        not isinstance(email, str)
        or not email.strip()
        or not isinstance(password, str)
        or not password
        or not isinstance(facility_id, str)
        or not facility_id.strip()
    ):
        connection.send_result(msg["id"], {"success": False, "error": "invalid_input"})
        return

    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=1)
    try:
        client = GreenelyClient(hass)
        await client.async_login(email.strip(), password)
        payload = await client.async_get_consumption(
            facility_id.strip(), start_date, end_date
        )
        summary = _summarize_consumption(payload)
    except GreenelyError as err:
        _LOGGER.warning("Greenely consumption test failed: %s", err.code)
        connection.send_result(msg["id"], {"success": False, "error": err.code})
        return

    if summary is None:
        _LOGGER.warning("Greenely consumption test failed: unexpected_response")
        connection.send_result(
            msg["id"], {"success": False, "error": "unexpected_response"}
        )
        return
    connection.send_result(msg["id"], {"success": True, **summary})


def _summarize_consumption(payload: object) -> dict | None:
    """Return a bounded, non-sensitive summary of a consumption response."""
    if isinstance(payload, dict):
        top_level_keys = sorted(
            key for key in payload if _safe_key_name(key)
        )
        data = payload.get("data")
        response_type = "object"
    elif isinstance(payload, list):
        top_level_keys = []
        data = payload
        response_type = "array"
    else:
        return None

    samples = normalize_greenely_consumption(payload)
    if not samples:
        return None
    return {
        "response_type": response_type,
        "top_level_keys": top_level_keys,
        "data_type": "object" if isinstance(data, dict) else "array",
        "data_count": len(samples),
        "sample_items": samples[:3],
    }


def _elhandel_manager(hass: HomeAssistant) -> ElhandelManager | None:
    manager = hass.data.get(DOMAIN, {}).get("elhandel_manager")
    return manager if isinstance(manager, ElhandelManager) else None


def _site_is_configured(hass: HomeAssistant) -> bool:
    manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    checker = getattr(manager, "active_site_is_configured", None)
    return manager is None or checker is None or checker()


def _site_binding_is_configured(hass: HomeAssistant, service: str) -> bool:
    """Check one site-scoped service without requiring physical mappings."""
    manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    if manager is None:
        return True
    binding = getattr(manager, "active_binding", lambda _service: None)(service)
    return isinstance(binding, dict) and bool(binding)


def _runtime_status(hass: HomeAssistant) -> str:
    """Return the setup lifecycle state exposed by the control plane."""
    return hass.data.get(DOMAIN, {}).get("runtime_status", "unavailable")


def _runtime_not_ready(hass: HomeAssistant) -> dict | None:
    status = _runtime_status(hass)
    if status == "ready":
        return None
    return {"success": False, "status": status, "error": "runtime_not_ready"}


def _electricity_provider_state(manager: ElhandelManager | None) -> dict:
    state = manager.public_state() if manager else serialize_provider_state(ProviderData())
    return {
        **state,
        "providers": [
            {"provider": provider, "name": name}
            for provider, name in SUPPORTED_ELECTRICITY_PROVIDERS.items()
        ],
    }


@websocket_api.websocket_command({vol.Required("type"): ELECTRICITY_PROVIDER_STATE_COMMAND})
@websocket_api.async_response
async def websocket_electricity_provider_state(hass, connection, msg):
    if not _site_binding_is_configured(hass, "elhandel"):
        connection.send_result(msg["id"], {"success": True, **_electricity_provider_state(None), "site_status": "unconfigured"})
        return
    manager = _elhandel_manager(hass)
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "electricity_manager_unavailable"})
        return
    connection.send_result(msg["id"], {"success": True, **_electricity_provider_state(manager)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): ELECTRICITY_PROVIDER_REMOVE_COMMAND,
        vol.Optional("provider"): str,
        vol.Optional("purge_history", default=False): bool,
    }
)
@websocket_api.async_response
async def websocket_electricity_provider_remove(hass, connection, msg):
    manager = _elhandel_manager(hass)
    state = _electricity_provider_state(manager)
    provider = msg.get("provider") or state["provider"]
    purge_history = msg.get("purge_history", False)
    if provider is None:
        connection.send_result(msg["id"], {"success": True, **state})
        return
    if provider != GREENELY_PROVIDER or provider != state["provider"]:
        connection.send_result(msg["id"], {"success": False, "error": "unsupported_provider"})
        return
    site_manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    try:
        if site_manager is not None:
            binding = site_manager.active_binding("elhandel")
            if binding is None:
                connection.send_result(msg["id"], {"success": True, **_electricity_provider_state(None), "site_status": "unconfigured"})
                return
            facility_id = binding.get("facility_id")
            binding_provider = binding.get("provider") or GREENELY_PROVIDER
            has_other_binding = await site_manager.async_unbind_provider_runtime()
            if has_other_binding:
                if purge_history and isinstance(facility_id, str) and facility_id:
                    await manager.storage.async_remove_provider(
                        facility_id, binding_provider, purge_history=True
                    )
                await manager.async_apply_site_binding(None)
                hass.bus.async_fire(ELECTRICITY_PROVIDER_UPDATE_EVENT)
            else:
                await manager.async_disconnect(purge_history=purge_history)
                await manager.async_apply_site_binding(None)
        else:
            await manager.async_disconnect(purge_history=purge_history)
    except GreenelyError as err:
        connection.send_result(msg["id"], {"success": False, "error": err.code})
        return
    except Exception:
        _LOGGER.exception("Electricity provider removal failed unexpectedly")
        connection.send_result(msg["id"], {"success": False, "error": "internal_error"})
        return
    connection.send_result(msg["id"], {"success": True, **_electricity_provider_state(manager)})


def _grid_manager(hass) -> GridManager | None:
    manager = hass.data.get(DOMAIN, {}).get("grid_manager")
    return manager if isinstance(manager, GridManager) else None


def _active_grid_state(hass, manager: GridManager | None) -> dict | None:
    """Resolve grid presentation from the active site's explicit binding."""
    if manager is None:
        return None
    site_manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    binding = site_manager.active_binding("grid") if site_manager else None
    if hasattr(manager, "public_state_for_binding"):
        return manager.public_state_for_binding(binding)
    return manager.public_state()


@websocket_api.websocket_command({vol.Required("type"): GRID_PROVIDERS_COMMAND})
@websocket_api.async_response
async def websocket_grid_providers(hass, connection, msg):
    connection.send_result(msg["id"], {
        "success": True,
        "providers": [
            {"id": item.provider_id, "name": item.name, "auth_methods": list(item.auth_methods)}
            for item in GRID_PROVIDER_REGISTRY.values()
        ],
    })


@websocket_api.websocket_command({vol.Required("type"): GRID_STATE_COMMAND})
@websocket_api.async_response
async def websocket_grid_state(hass, connection, msg):
    if not _site_binding_is_configured(hass, "grid"):
        connection.send_result(msg["id"], {"success": True, "configured": False, "site_status": "unconfigured"})
        return
    manager = _grid_manager(hass)
    connection.send_result(msg["id"], {"success": True, **(_active_grid_state(hass, manager) or {"configured": False})})


@websocket_api.websocket_command({
    vol.Required("type"): GRID_LOGIN_COMMAND,
    vol.Required("provider"): str,
    vol.Required("auth_method"): str,
    vol.Required("account_id"): str,
    vol.Required("password"): str,
})
@websocket_api.async_response
async def websocket_grid_login(hass, connection, msg):
    manager = _grid_manager(hass)
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "grid_unavailable"})
        return
    if not msg["account_id"].strip() or not msg["password"]:
        connection.send_result(msg["id"], {"success": False, "error": "invalid_input"})
        return
    try:
        result = await manager.async_login(
            msg["provider"], msg["auth_method"], msg["account_id"].strip(), msg["password"]
        )
    except Exception as err:
        connection.send_result(msg["id"], {"success": False, "error": getattr(err, "code", "configuration_failed")})
        return
    site_manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    provider = getattr(manager, "provider", None)
    if result.get("configured") and site_manager and provider and isinstance(provider.state.get("facility"), dict):
        await site_manager.async_bind_grid_runtime(manager)
        manager.async_start_refresh()
    connection.send_result(msg["id"], {"success": result.get("status") not in {"browser_attestation_required", "invalid_input"}, **result})


@websocket_api.websocket_command({vol.Required("type"): GRID_SOURCE_DATA_COMMAND})
@websocket_api.async_response
async def websocket_grid_source_data(hass, connection, msg):
    if not _site_binding_is_configured(hass, "grid"):
        connection.send_result(msg["id"], {"success": False, "error": "site_unconfigured"})
        return
    manager = _grid_manager(hass)
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "grid_unavailable"})
        return
    try:
        connection.send_result(msg["id"], {"success": True, **await manager.async_source_data()})
    except Exception as err:
        connection.send_result(msg["id"], {"success": False, "error": getattr(err, "code", "source_unavailable")})


@websocket_api.websocket_command({vol.Required("type"): GRID_REMOVE_COMMAND})
@websocket_api.async_response
async def websocket_grid_remove(hass, connection, msg):
    manager = _grid_manager(hass)
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "grid_unavailable"})
        return
    site_manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    if site_manager is not None:
        if site_manager.active_binding("grid") is None:
            connection.send_result(msg["id"], {"success": True, "configured": False, "site_status": "unconfigured"})
            return
        has_other_binding = await site_manager.async_unbind_grid_runtime()
        await manager.async_apply_site_binding(None)
        if not has_other_binding:
            await manager.async_remove()
        else:
            hass.bus.async_fire(EON_GRID_UPDATE_EVENT)
        connection.send_result(msg["id"], {"success": True, "configured": False, "site_status": "unconfigured"})
        return
    connection.send_result(msg["id"], {"success": True, **await manager.async_remove()})


@websocket_api.websocket_command({vol.Required("type"): GRID_WEB_HANDOFF_START_COMMAND})
@websocket_api.async_response
async def websocket_grid_web_handoff_start(hass, connection, msg):
    manager = _grid_manager(hass)
    user = getattr(connection, "user", None)
    user_id = getattr(user, "id", None)
    if manager is None or not isinstance(user_id, str) or not user_id:
        connection.send_result(msg["id"], {"success": False, "error": "handoff_unavailable"})
        return
    try:
        result = await manager.async_start_web_handoff(user_id)
    except Exception as err:
        connection.send_result(msg["id"], {"success": False, "error": getattr(err, "code", "handoff_failed")})
        return
    connection.send_result(msg["id"], {"success": result.get("status") == "waiting_for_login", **result})


@websocket_api.websocket_command({vol.Required("type"): EON_GRID_STATE_COMMAND})
@websocket_api.async_response
async def websocket_eon_grid_state(hass, connection, msg):
    if not _site_binding_is_configured(hass, "grid"):
        connection.send_result(msg["id"], {"success": True, "configured": False, "site_status": "unconfigured"})
        return
    manager = _grid_manager(hass)
    site_manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    binding = site_manager.active_binding("grid") if site_manager else None
    state = (
        manager.public_state_for_binding(binding)
        if manager and hasattr(manager, "public_state_for_binding")
        else manager.public_state() if manager else {"configured": False}
    )
    connection.send_result(msg["id"], {"success": True, **state})


@websocket_api.websocket_command({
    vol.Required("type"): EON_GRID_SAVE_COMMAND,
    vol.Required("cookie_header"): str,
})
@websocket_api.async_response
async def websocket_eon_grid_save(hass, connection, msg):
    manager = _grid_manager(hass)
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "eon_grid_unavailable"})
        return
    try:
        state = await manager.async_save_cookie_header(msg["cookie_header"])
        site_manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
        if site_manager and state.get("facility"):
            await site_manager.async_bind_grid_runtime(manager)
            manager.async_start_refresh()
    except Exception as err:
        connection.send_result(msg["id"], {"success": False, "error": getattr(err, "code", "configuration_failed")})
        return
    connection.send_result(msg["id"], {"success": True, **state})


@websocket_api.websocket_command({
    vol.Required("type"): EON_GRID_APP_SAVE_COMMAND,
    vol.Required("account_id"): str,
    vol.Required("password"): str,
})
@websocket_api.async_response
async def websocket_eon_grid_app_save(hass, connection, msg):
    manager = _grid_manager(hass)
    account_id = msg.get("account_id")
    password = msg.get("password")
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "eon_grid_unavailable"})
        return
    if not isinstance(account_id, str) or not account_id.strip() or not isinstance(password, str) or not password:
        connection.send_result(msg["id"], {"success": False, "error": "invalid_input"})
        return
    try:
        state = await manager.async_save_app_credentials(account_id.strip(), password)
        site_manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
        if site_manager and state.get("facility"):
            await site_manager.async_bind_grid_runtime(manager)
            manager.async_start_refresh()
    except Exception as err:
        connection.send_result(msg["id"], {"success": False, "error": getattr(err, "code", "configuration_failed")})
        return
    connection.send_result(msg["id"], {"success": True, **state})


@websocket_api.websocket_command({
    vol.Required("type"): EON_GRID_WEB_SAVE_COMMAND,
    vol.Required("account_id"): str,
    vol.Required("password"): str,
})
@websocket_api.async_response
async def websocket_eon_grid_web_save(hass, connection, msg):
    manager = _grid_manager(hass)
    account_id = msg.get("account_id")
    password = msg.get("password")
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "eon_grid_unavailable"})
        return
    if not isinstance(account_id, str) or not account_id.strip() or not isinstance(password, str) or not password:
        connection.send_result(msg["id"], {"success": False, "error": "invalid_input"})
        return
    result = await manager.async_save_web_credentials(account_id.strip(), password)
    connection.send_result(msg["id"], {"success": result.get("status") == "authenticated", **result})


@websocket_api.websocket_command({vol.Required("type"): EON_GRID_SOURCE_DATA_COMMAND})
@websocket_api.async_response
async def websocket_eon_grid_source_data(hass, connection, msg):
    if not _site_binding_is_configured(hass, "grid"):
        connection.send_result(msg["id"], {"success": False, "error": "site_unconfigured"})
        return
    manager = _grid_manager(hass)
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "eon_grid_unavailable"})
        return
    try:
        source = await manager.async_source_data()
    except Exception as err:
        connection.send_result(msg["id"], {"success": False, "error": getattr(err, "code", "source_unavailable")})
        return
    connection.send_result(msg["id"], {"success": True, **source})


@websocket_api.websocket_command({vol.Required("type"): EON_GRID_REMOVE_COMMAND})
@websocket_api.async_response
async def websocket_eon_grid_remove(hass, connection, msg):
    manager = _grid_manager(hass)
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "eon_grid_unavailable"})
        return
    site_manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    if site_manager is not None:
        if site_manager.active_binding("grid") is None:
            connection.send_result(msg["id"], {"success": True, "configured": False, "site_status": "unconfigured"})
            return
        has_other_binding = await site_manager.async_unbind_grid_runtime()
        await manager.async_apply_site_binding(None)
        if not has_other_binding:
            await manager.async_remove()
        else:
            hass.bus.async_fire(EON_GRID_UPDATE_EVENT)
        connection.send_result(msg["id"], {"success": True, "configured": False, "site_status": "unconfigured"})
        return
    connection.send_result(msg["id"], {"success": True, **await manager.async_remove()})


@websocket_api.websocket_command({vol.Required("type"): ELECTRICITY_HISTORY_STATE_COMMAND})
@websocket_api.async_response
async def websocket_electricity_history_state(hass, connection, msg):
    if not _site_is_configured(hass):
        connection.send_result(msg["id"], {"success": True, "history": [], "site_status": "unconfigured"})
        return
    manager = _elhandel_manager(hass)
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "electricity_manager_unavailable"})
        return
    history = await manager.async_history_metadata()
    connection.send_result(msg["id"], {"success": True, "history": history})


@websocket_api.websocket_command(
    {
        vol.Required("type"): ELECTRICITY_HISTORY_PURGE_COMMAND,
        vol.Required("facility_id"): str,
        vol.Required("provider"): str,
    }
)
@websocket_api.async_response
async def websocket_electricity_history_purge(hass, connection, msg):
    manager = _elhandel_manager(hass)
    if not manager:
        connection.send_result(msg["id"], {"success": False, "error": "not_configured"})
        return
    try:
        history = await manager.async_purge_history(msg["facility_id"], msg["provider"])
    except GreenelyError as err:
        connection.send_result(msg["id"], {"success": False, "error": err.code})
        return
    except Exception:
        _LOGGER.exception("Electricity history purge failed unexpectedly")
        connection.send_result(msg["id"], {"success": False, "error": "internal_error"})
        return
    connection.send_result(msg["id"], {"success": True, "history": history})


@websocket_api.websocket_command(
    {
        vol.Required("type"): ELECTRICITY_PROVIDER_SAVE_COMMAND,
        vol.Required("email"): str,
        vol.Required("password"): str,
        vol.Required("facility_id"): str,
    }
)
@websocket_api.async_response
async def websocket_electricity_provider_save(hass, connection, msg):
    manager = _elhandel_manager(hass)
    email = msg.get("email")
    password = msg.get("password")
    facility_id = msg.get("facility_id")
    if not manager or not all(isinstance(value, str) and value.strip() for value in (email, password, facility_id)):
        connection.send_result(msg["id"], {"success": False, "error": "invalid_input"})
        return
    try:
        state = await manager.async_save_config(email.strip(), password, facility_id.strip())
        site_manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
        if site_manager:
            await site_manager.async_bind_provider_runtime(manager)
            manager.async_start_refresh("site_binding")
    except GreenelyError as err:
        _LOGGER.warning("Greenely save failed: %s", err.code)
        connection.send_result(msg["id"], {"success": False, "error": err.code})
        return
    except Exception:
        _LOGGER.exception("Greenely configuration failed unexpectedly")
        connection.send_result(msg["id"], {"success": False, "error": "internal_error"})
        return
    connection.send_result(msg["id"], {"success": True, **state})


@websocket_api.websocket_command({vol.Required("type"): GREENELY_PARSE_LATEST_COMMAND})
@websocket_api.async_response
async def websocket_greenely_parse_latest(hass, connection, msg):
    """Parse one fresh latest invoice and return only normalized fields."""
    manager = _elhandel_manager(hass)
    if not manager or not manager.state["configured"]:
        connection.send_result(msg["id"], {"success": False, "error": "not_configured"})
        return
    try:
        await manager.async_refresh("manual_debug")
        await manager.async_refresh_consumption("manual_debug")
        result = await manager.async_parse_latest_invoice()
    except GreenelyError as err:
        _LOGGER.warning("Greenely invoice parse failed: %s", err.code)
        connection.send_result(msg["id"], {"success": False, "error": err.code})
        return
    connection.send_result(msg["id"], {"success": True, **result, "electricity_provider_state": manager.public_state()})


@websocket_api.websocket_command({
    vol.Required("type"): ELECTRICITY_PROVIDER_SOURCE_DATA_COMMAND,
    vol.Optional("section"): str,
    vol.Optional("offset", default=0): int,
    vol.Optional("limit", default=200): int,
})
@websocket_api.async_response
async def websocket_electricity_provider_source_data(hass, connection, msg):
    """Return paginated sanitized Greenely source data on explicit request."""
    manager = _elhandel_manager(hass)
    if not manager or not manager.state.get("configured"):
        connection.send_result(msg["id"], {"success": False, "error": "not_configured"})
        return
    await manager.async_diagnostic("INFO", "websocket", "source_command_received", "Command received: electricity_provider_source_data")
    await manager.async_diagnostic("INFO", "source", "source_loading", "Loading source data")
    source = manager.source_data()
    section = msg.get("section")
    offset = msg.get("offset", 0)
    limit = msg.get("limit", 200)
    try:
        offset = int(offset)
        limit = int(limit)
    except (TypeError, ValueError):
        offset, limit = 0, 200
    if section in ("consumption", "invoices", "contracts"):
        items = source.get(section, {}).get("samples", []) if section == "consumption" else source.get(section, [])
        connection.send_result(msg["id"], {"success": True, "section": section, **paginate_source(items, offset, limit)})
        await manager.async_diagnostic("INFO", "source", f"source_{section}_loaded", f"{section.capitalize()} loaded: {len(items)}")
        await manager.async_diagnostic("INFO", "websocket", "source_response_sent", "Response sent")
        return
    contracts = source.get("contracts", [])
    invoices = source.get("invoices", [])
    consumption = source.get("consumption", {}).get("samples", [])
    await manager.async_diagnostic("INFO", "source", "source_facility_loaded", "Facility loaded")
    await manager.async_diagnostic("INFO", "source", "source_contracts_loaded", f"Contracts loaded: {len(contracts)}")
    await manager.async_diagnostic("INFO", "source", "source_invoices_loaded", f"Invoices loaded: {len(invoices)}")
    await manager.async_diagnostic("INFO", "source", "source_consumption_loaded", f"Consumption samples loaded: {len(consumption)}")
    connection.send_result(msg["id"], {"success": True, "section": "facility", "facility": source.get("facility"), "contracts": contracts, "invoices": paginate_source(invoices, offset, limit), "consumption": paginate_source(consumption, offset, limit)})
    await manager.async_diagnostic("INFO", "websocket", "source_response_sent", "Response sent")


@websocket_api.websocket_command({
    vol.Required("type"): DIAGNOSTICS_STATE_COMMAND,
    vol.Optional("include_inventory", default=True): bool,
})
@websocket_api.async_response
async def websocket_diagnostics_state(hass, connection, msg):
    manager = _elhandel_manager(hass)
    site_identity = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    inventory = None
    if msg.get("include_inventory", True) and site_identity is not None and _ella_load_registry(hass) is not None:
        site_id = getattr(site_identity, "state", {}).get("active_site_id")
        if isinstance(site_id, str):
            inventory = build_capability_inventory(
                site_identity,
                _ella_load_registry(hass),
                site_id,
                load_forecast=await _async_load_forecast_state(hass, site_id),
                entity_available=lambda entity_id: _ella_entity_available(hass, entity_id),
            )
    connection.send_result(msg["id"], {
        "logs": manager.diagnostics if manager else [],
        "site_identity": site_identity.public_state() if site_identity else {
            "site_id": None,
            "logical_roles": [],
            "source_ledger": [],
        },
        "ella_capability_inventory": inventory,
        "ella_loads": {
            "schema": "ella_load_registry.v1",
            "site_id": inventory.get("site_id") if inventory else None,
            "count": inventory.get("individual_loads", {}).get("count", 0) if inventory else 0,
            "execution_eligible": False,
        },
    })


@websocket_api.websocket_command({vol.Required("type"): DIAGNOSTICS_CLEAR_COMMAND})
@websocket_api.async_response
async def websocket_diagnostics_clear(hass, connection, msg):
    manager = _elhandel_manager(hass)
    if manager:
        await manager.async_clear_diagnostics()
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command({vol.Required("type"): CANONICAL_COLLECTOR_STATE_COMMAND})
@websocket_api.async_response
async def websocket_canonical_collector_state(hass, connection, msg):
    """Return read-only in-memory canonical collector diagnostics."""
    collector = hass.data.get(DOMAIN, {}).get("canonical_collector")
    if collector is None:
        connection.send_result(msg["id"], {"success": False, "error": "not_ready"})
        return
    connection.send_result(msg["id"], {
        "success": True,
        "forecast_solar": collector.forecast_capture_status(),
        "open_meteo": collector.open_meteo_capture_status(),
        "weather": collector.weather_capture_status(),
    })


@websocket_api.websocket_command({vol.Required("type"): FRONTEND_PREFERENCES_COMMAND})
@websocket_api.async_response
async def websocket_frontend_preferences(hass, connection, msg):
    manager = _elhandel_manager(hass)
    preferences = await manager.async_get_frontend_preferences() if manager else {"debug_enabled": False}
    connection.send_result(msg["id"], {"success": True, **preferences})


@websocket_api.websocket_command(
    {
        vol.Required("type"): FRONTEND_PREFERENCES_SET_COMMAND,
        vol.Required("debug_enabled"): bool,
    }
)
@websocket_api.async_response
async def websocket_frontend_preferences_set(hass, connection, msg):
    manager = _elhandel_manager(hass)
    if not manager:
        connection.send_result(msg["id"], {"success": False, "error": "not_configured"})
        return
    preferences = await manager.async_set_debug_enabled(msg["debug_enabled"])
    connection.send_result(msg["id"], {"success": True, **preferences})


@websocket_api.websocket_command({vol.Required("type"): CHART_LAYERS_COMMAND})
@websocket_api.async_response
async def websocket_chart_layers(hass, connection, msg):
    manager = _elhandel_manager(hass)
    if not manager or not getattr(connection, "user", None):
        connection.send_result(msg["id"], {"success": False, "error": "not_configured"})
        return
    preferences = await manager.async_get_ui_preferences(connection.user.id)
    connection.send_result(msg["id"], {
        "success": True,
        **preferences,
    })


@websocket_api.websocket_command(
    {
        vol.Required("type"): CHART_LAYERS_SET_COMMAND,
        vol.Optional("chart_layers", default={}): {
            vol.Optional(key): bool for key in CHART_LAYER_DEFAULTS
        },
        vol.Optional("configuration_cards_visible"): bool,
        vol.Optional("main_cards", default={}): {
            vol.Optional(key): bool for key in MAIN_CARD_DEFAULTS
        },
        vol.Optional("price_comparison", default={}): {
            vol.Optional(key): bool for key in PRICE_COMPARISON_DEFAULTS
        },
        vol.Optional("phase_history_visible", default={}): {
            vol.Optional(key): bool for key in PHASE_HISTORY_VISIBLE_DEFAULTS
        },
        vol.Optional("phase_history_metric"): vol.In(PHASE_HISTORY_METRICS),
    }
)
@websocket_api.async_response
async def websocket_chart_layers_set(hass, connection, msg):
    manager = _elhandel_manager(hass)
    if not manager or not getattr(connection, "user", None):
        connection.send_result(msg["id"], {"success": False, "error": "not_configured"})
        return
    updates = {
        key: msg[key]
        for key in (
            "chart_layers",
            "configuration_cards_visible",
            "main_cards",
            "price_comparison",
            "phase_history_visible",
            "phase_history_metric",
        )
        if key in msg
    }
    preferences = await manager.async_update_ui_preferences(connection.user.id, updates) if updates else await manager.async_get_ui_preferences(connection.user.id)
    connection.send_result(msg["id"], {
        "success": True,
        **preferences,
    })


def _meter_manager(hass) -> MeterManager | None:
    manager = hass.data.get(DOMAIN, {}).get("meter_manager")
    return manager if isinstance(manager, MeterManager) else None


def _power_manager(hass) -> PowerManager | None:
    manager = hass.data.get(DOMAIN, {}).get("power_manager")
    return manager if isinstance(manager, PowerManager) else None


@websocket_api.websocket_command(
    {
        vol.Required("type"): METER_SAVE_COMMAND,
        vol.Optional("power_entity", default=""): str,
        vol.Optional("energy_import_entity", default=""): str,
        vol.Optional("energy_export_entity", default=""): str,
        vol.Optional("invert_power", default=False): bool,
    }
)
@websocket_api.async_response
async def websocket_meter_save(hass, connection, msg):
    diagnostics = hass.data.get(DOMAIN, {}).get("elhandel_manager")
    raw_fields = sorted(key for key in msg if key != "type")
    _LOGGER.debug("websocket_command_received_raw command=%s fields=%s", msg.get("type"), raw_fields)
    _LOGGER.debug("meter_save_handler_entered command=%s", METER_SAVE_COMMAND)
    async def diagnostic(level: str, event: str, message: str) -> None:
        if diagnostics:
            try:
                await diagnostics.async_diagnostic(level, "meter", event, message)
            except Exception:
                _LOGGER.exception("Failed to write meter diagnostic event %s", event)

    try:
        await diagnostic("INFO", "websocket_command_received_raw", f"Payload fields: {', '.join(raw_fields)}")
        await diagnostic("INFO", "websocket_command_name", METER_SAVE_COMMAND)
        await diagnostic("INFO", "meter_save_handler_entered", "Meter save handler entered")
        await diagnostic("INFO", "meter_websocket_received", "Meter save websocket request received")
        await diagnostic("INFO", "meter_payload_received", f"Meter payload fields: {', '.join(raw_fields)}")
        await diagnostic("INFO", "meter_validation_started", "Meter payload validation started")
        manager = _meter_manager(hass)
        if not manager:
            raise RuntimeError("meter_manager_unavailable")
        await diagnostic("INFO", "meter_store_write_started", "Meter store write started")
        state = await manager.async_save_mapping(msg)
    except Exception as err:
        exception_message = str(err) or "empty_exception_message"
        error = f"{type(err).__name__}: {exception_message}"
        await diagnostic("ERROR", "meter_store_write_failed", f"{error}")
        connection.send_result(msg["id"], {"success": False, "error": error})
        return
    connection.send_result(msg["id"], {"success": True, **state})


@websocket_api.websocket_command(
    {
        vol.Required("type"): METER_DIAGNOSTIC_COMMAND,
        vol.Optional("component", default="meter"): vol.In({"meter", "price", "performance", "frontend_power_flow"}),
        vol.Required("level"): vol.In({"INFO", "WARNING", "ERROR"}),
        vol.Required("event"): str,
        vol.Required("message"): str,
    }
)
@websocket_api.async_response
async def websocket_meter_diagnostic(hass, connection, msg):
    manager = hass.data.get(DOMAIN, {}).get("elhandel_manager")
    if manager:
        await manager.async_diagnostic(
            msg["level"], msg["component"], msg["event"], msg["message"]
        )
    connection.send_result(msg["id"], {"success": bool(manager)})


@websocket_api.websocket_command({vol.Required("type"): METER_STATE_COMMAND})
@websocket_api.async_response
async def websocket_meter_state(hass, connection, msg):
    if response := _runtime_not_ready(hass):
        connection.send_result(msg["id"], response)
        return
    manager = _meter_manager(hass)
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "meter_unavailable"})
        return
    connection.send_result(msg["id"], {"success": True, **await manager.async_state()})


@websocket_api.websocket_command({vol.Required("type"): METER_SOURCE_COMMAND})
@websocket_api.async_response
async def websocket_meter_source(hass, connection, msg):
    manager = _meter_manager(hass)
    source = await manager.async_source() if manager else {"mapping": {}, "state": {"configured": False}}
    connection.send_result(msg["id"], {"success": True, **source})


@websocket_api.websocket_command({vol.Required("type"): METER_STORE_CLEAR_COMMAND})
@websocket_api.async_response
async def websocket_meter_store_clear(hass, connection, msg):
    manager = _meter_manager(hass)
    state = await manager.async_clear() if manager else {"configured": False}
    connection.send_result(msg["id"], {"success": True, **state})


@websocket_api.websocket_command(
    {
        vol.Required("type"): METER_POWER_HISTORY_COMMAND,
        vol.Optional("entity_id"): str,
    }
)
@websocket_api.async_response
async def websocket_meter_power_history(hass, connection, msg):
    """Return today's normalized live power history for the selected meter."""
    manager = _meter_manager(hass)
    result = await manager.async_power_history(msg.get("entity_id")) if manager else {
        "success": False,
        "entity_id": msg.get("entity_id"),
        "points": [],
        "error": "meter_unavailable",
    }
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({vol.Required("type"): BILLING_HISTORY_COMMAND})
@websocket_api.async_response
async def websocket_billing_history(hass, connection, msg):
    """Return canonical current-month meter and price history for billing."""
    if not _site_is_configured(hass):
        connection.send_result(msg["id"], {"success": False, "error": "site_unconfigured", "points": []})
        return
    meter = _meter_manager(hass)
    billing = await meter.async_billing_history() if meter else {
        "success": False,
        "points": [],
        "error": "meter_unavailable",
    }
    if not billing.get("success"):
        connection.send_result(msg["id"], {"success": False, **billing})
        return
    entry = next(iter(hass.config_entries.async_entries(DOMAIN)), None)
    coordinator: ElrakningCoordinator | None = entry.runtime_data if entry else None
    if coordinator is None:
        connection.send_result(msg["id"], {"success": True, **billing, "price_periods": [], "price_coverage": {"period_count": 0}})
        return
    start = date.fromisoformat(billing["start"][:10])
    end = date.fromisoformat(billing["end"][:10])
    month_end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    price_periods = []
    missing_price_dates = 0
    target = start
    while target < month_end:
        data = await coordinator.async_get_price_data(target)
        serialized = _serialize_price_data(hass, data)
        periods = serialized.get("periods", [])
        if periods:
            price_periods.extend(periods)
        else:
            missing_price_dates += 1
        target += timedelta(days=1)
    invoice_today = build_today_variable_cost(
        billing.get("points", []),
        price_periods,
        dt_util.as_local(dt_util.now()),
    )
    connection.send_result(msg["id"], {
        "success": True,
        "start": billing["start"],
        "end": billing["end"],
        "energy_points": billing.get("points", []),
        "baseline_energy_points": billing.get("baseline_points", []),
        "energy_source": {
            "method": "integrated_grid_power",
            "entity_id": billing.get("entity_id"),
            "source_entity": billing.get("entity_id"),
            "raw_unit": "kW",
        },
        "integration_method": "trapezoidal_power_integration",
        "energy_coverage": billing.get("coverage", {}),
        "baseline_energy_coverage": billing.get("baseline_coverage", {}),
        "price_periods": price_periods,
        "price_source": "nord_pool_historical_daily_periods",
        "invoice_estimate": {"today": invoice_today},
        "price_coverage": {
            "period_count": len(price_periods),
            "missing_dates": missing_price_dates,
            "price_start": price_periods[0]["start"] if price_periods else None,
            "price_end": price_periods[-1]["end"] if price_periods else None,
        },
    })


@websocket_api.websocket_command(
    {
        vol.Required("type"): POWER_SAVE_COMMAND,
        vol.Optional("solar_entities", default=[]): [str],
        vol.Optional("solar_array_metadata", default={}): dict,
        vol.Optional("consumption_entity", default=""): str,
        vol.Optional("charging_entity", default=""): str,
        vol.Optional("discharging_entity", default=""): str,
        vol.Optional("battery_power_entity", default=""): str,
        vol.Optional("invert_battery_power", default=False): bool,
        vol.Optional("soc_entity", default=""): str,
        vol.Optional("capacity_entity", default=""): str,
    }
)
@websocket_api.async_response
async def websocket_power_save(hass, connection, msg):
    manager = _power_manager(hass)
    try:
        if manager is None:
            raise RuntimeError("power_unavailable")
        state = await manager.async_save_mapping(msg)
    except Exception as err:
        connection.send_result(msg["id"], {"success": False, "error": str(err) or "power_save_failed"})
        return
    pvgis_manager = hass.data.get(DOMAIN, {}).get("solar_pvgis_manager")
    if pvgis_manager:
        await pvgis_manager.async_refresh_for_power_state(state)
    connection.send_result(msg["id"], {"success": True, **state})


@websocket_api.websocket_command({vol.Required("type"): POWER_STATE_COMMAND})
@websocket_api.async_response
async def websocket_power_state(hass, connection, msg):
    if response := _runtime_not_ready(hass):
        connection.send_result(msg["id"], response)
        return
    manager = _power_manager(hass)
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "power_unavailable"})
        return
    connection.send_result(msg["id"], {"success": True, **await manager.async_state()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): POWER_HISTORY_COMMAND,
        vol.Optional("days", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=7)),
        vol.Optional("date"): str,
    }
)
@websocket_api.async_response
async def websocket_power_history(hass, connection, msg):
    manager = _elhandel_manager(hass)
    started = time.monotonic()
    counters = hass.data.setdefault(DOMAIN, {}).setdefault("power_flow_diagnostics", {"history_active": 0, "enrichment_active": 0, "forecast_active": 0})
    counters["history_active"] += 1
    await _power_flow_diagnostic(hass, "INFO", "history_handler_start", {
        "request_id": msg.get("id"), "date": msg.get("date"), "history_active": counters["history_active"],
    })
    manager = _power_manager(hass)
    try:
        result = await manager.async_history(msg.get("days", 1)) if manager else {
            "success": False,
            "series": {},
            "error": "power_unavailable",
        }
        connection.send_result(msg["id"], result)
    finally:
        counters["history_active"] = max(0, counters["history_active"] - 1)
        await _power_flow_diagnostic(hass, "INFO", "history_handler_end", {
            "request_id": msg.get("id"), "date": msg.get("date"),
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
            "history_active": counters["history_active"],
            "series_counts": {key: len(value.get("points", [])) for key, value in (result.get("series", {}) if "result" in locals() else {}).items() if isinstance(value, dict)},
        })


@websocket_api.websocket_command(
    {
        vol.Required("type"): POWER_HISTORY_ENRICHMENT_COMMAND,
        vol.Optional("date"): str,
    }
)
@websocket_api.async_response
async def websocket_power_history_enrichment(hass, connection, msg):
    """Return forecast and optional solar state without blocking power history."""
    requested_date = None
    if msg.get("date"):
        try:
            requested_date = date.fromisoformat(msg["date"])
        except ValueError:
            requested_date = None
    started = time.monotonic()
    counters = hass.data.setdefault(DOMAIN, {}).setdefault("power_flow_diagnostics", {"history_active": 0, "enrichment_active": 0, "forecast_active": 0})
    counters["enrichment_active"] += 1
    await _power_flow_diagnostic(hass, "INFO", "enrichment_handler_start", {
        "request_id": msg.get("id"), "date": msg.get("date"), "enrichment_active": counters["enrichment_active"],
    })
    try:
        connection.send_result(msg["id"], await _async_power_history_enrichment(hass, requested_date, msg.get("id")))
    finally:
        counters["enrichment_active"] = max(0, counters["enrichment_active"] - 1)
        await _power_flow_diagnostic(hass, "INFO", "enrichment_handler_end", {
            "request_id": msg.get("id"), "date": msg.get("date"),
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
            "enrichment_active": counters["enrichment_active"],
        })


async def _power_flow_diagnostic(hass, level: str, event: str, details: dict) -> None:
    """Write bounded day-switch diagnostics through the existing UI log store."""
    if event == "load_input_frames_read_complete":
        # High-frequency frame reads are useful in transient profiling, but not in the bounded UI store.
        return
    manager = _elhandel_manager(hass)
    if manager is None:
        return
    identity = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    active_site_id = getattr(identity, "state", {}).get("active_site_id") if identity else None
    diagnostic_state = hass.data.setdefault(DOMAIN, {})
    diagnostic_base = diagnostic_state.setdefault("power_flow_diagnostic_base", time.monotonic())
    payload = {"relative_ms": round((time.monotonic() - diagnostic_base) * 1000, 3), "site_id": active_site_id, **details}
    await manager.async_diagnostic(level, "power_flow", event, json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))


async def _async_power_history_enrichment(hass, requested_date: date | None = None, request_id=None) -> dict:
    """Build the existing forecast/state enrichment independently of history."""
    forecast_manager = _solar_forecast_manager(hass)
    forecast = forecast_manager.public_state() if forecast_manager and _site_is_configured(hass) else SolarForecastManager._unavailable_facts()
    enrichment = {
        "solar_forecast": forecast,
        "solar_forecast_baselines": forecast.get("baselines", {}),
    }
    shadow = hass.data.get(DOMAIN, {}).get("solar_shadow_manager")
    enrichment["solar_shadow"] = shadow.public_state() if shadow and _site_is_configured(hass) else {"available": False, "snapshots": []}
    weather_manager = hass.data.get(DOMAIN, {}).get("solar_weather_manager")
    enrichment["solar_weather"] = weather_manager.public_state() if weather_manager else {"available": False, "source": "smhi", "status": "unavailable", "current": {}, "hourly_forecast": []}
    pvgis_manager = hass.data.get(DOMAIN, {}).get("solar_pvgis_manager")
    enrichment["solar_pvgis"] = pvgis_manager.public_state() if pvgis_manager and _site_is_configured(hass) else {"available": False, "source": "jrc_pvgis"}
    enrichment["solar_sun"] = build_sun_context(hass)
    load_started = time.monotonic()
    enrichment["load_forecast"] = await _async_load_forecast_state(hass, request_id=request_id)
    await _power_flow_diagnostic(hass, "INFO", "load_forecast_complete", {
        "request_id": request_id, "date": requested_date.isoformat() if requested_date else None,
        "duration_ms": round((time.monotonic() - load_started) * 1000, 3),
        "frame_count": len(enrichment["load_forecast"].get("frames", [])),
    })
    power_started = time.monotonic()
    enrichment["power_forecast"] = await _async_power_forecast_state(
        hass, requested_date, load_forecast=enrichment["load_forecast"], request_id=request_id
    )
    await _power_flow_diagnostic(hass, "INFO", "power_forecast_complete", {
        "request_id": request_id, "date": requested_date.isoformat() if requested_date else None,
        "duration_ms": round((time.monotonic() - power_started) * 1000, 3),
        "series_count": len(enrichment["power_forecast"].get("series", {})),
    })
    return enrichment


async def _async_power_forecast_state(
    hass,
    requested_date: date | None = None,
    requested_site_id: str | None = None,
    load_forecast: dict[str, Any] | None = None,
    request_id=None,
) -> dict:
    """Return cached, read-only site power forecasts for the active chart day."""
    identity = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    collector = hass.data.get(DOMAIN, {}).get("canonical_collector")
    site_id = requested_site_id or (getattr(identity, "state", {}).get("active_site_id") if identity else None)
    if not site_id or collector is None:
        return {"schema": "ella_power_forecast.v1", "available": False, "reason": "site_or_storage_unavailable", "series": {}}
    now = dt_util.now()
    bucket = int(now.timestamp()) // 900
    if load_forecast is None:
        load_forecast = await _async_load_forecast_state(hass, site_id)
    load_frame_ids = tuple(sorted(str(frame.get("frame_id")) for frame in load_forecast.get("frames", []) if isinstance(frame, dict)))
    forecast_manager = _solar_forecast_manager(hass)
    solar_facts = forecast_manager.public_state() if forecast_manager and _site_is_configured(hass) else SolarForecastManager._unavailable_facts()
    binding = ((getattr(identity, "state", {}).get("site_configs", {}).get(site_id, {}) or {}).get("bindings", {}) or {}).get("forecast")
    binding_fingerprint = binding.get("binding_fingerprint") if isinstance(binding, dict) else None
    site = next((item for item in getattr(identity, "state", {}).get("sites", []) if isinstance(item, dict) and item.get("site_id") == site_id), {})
    location = site.get("location") if isinstance(site, dict) else {}
    timezone_name, _ = resolve_timezone((location or {}).get("timezone"), getattr(getattr(hass, "config", None), "time_zone", None))
    target_date = requested_date or now.astimezone(ZoneInfo(timezone_name)).date()
    learning_store = hass.data.get(DOMAIN, {}).get("ella_learning_store")
    power_calibration = learning_store.persistent_power_calibration(str(site_id), now) if learning_store else {}
    cache_key = (
        str(site_id),
        target_date.isoformat(),
        bucket,
        load_frame_ids,
        str(binding_fingerprint or ""),
        tuple(sorted((key, str(value)) for key, value in solar_facts.items() if key != "baselines")),
        json.dumps(power_calibration, sort_keys=True, separators=(",", ":"), default=str),
    )
    counters = hass.data.setdefault(DOMAIN, {}).setdefault("power_flow_diagnostics", {"history_active": 0, "enrichment_active": 0, "forecast_active": 0})
    inflight = hass.data.setdefault(DOMAIN, {}).setdefault("power_forecast_inflight", {})
    inflight_key = cache_key
    task = inflight.get(inflight_key)
    if task is None:
        counters["forecast_active"] += 1
        await _power_flow_diagnostic(hass, "INFO", "power_forecast_new", {
            "request_id": request_id, "date": target_date.isoformat(), "forecast_active": counters["forecast_active"],
        })
        task = asyncio.create_task(_build_power_forecast_state(
            hass,
            site_id,
            timezone_name,
            rows=None,
            load_forecast=load_forecast,
            binding=binding,
            now=now,
            active_battery_generation_ids={
                str(target.get("generation_id"))
                for target in identity.collection_targets()
                if target.get("site_id") == str(site_id) and target.get("logical_role") == "battery.power"
            },
            active_solar_generation_ids={
                str(target.get("generation_id"))
                for target in identity.collection_targets()
                if target.get("site_id") == str(site_id) and target.get("logical_role") == "solar.production"
            },
            open_meteo_targets=build_single_run_targets(getattr(identity, "collection_site_configs", lambda: {})()),
            solar_facts=solar_facts,
            target_date=target_date,
            power_calibration=power_calibration,
            request_id=request_id,
        ))
        inflight[inflight_key] = task

        def clear(completed, request_key=inflight_key):
            if inflight.get(request_key) is completed:
                inflight.pop(request_key, None)
                counters["forecast_active"] = max(0, counters["forecast_active"] - 1)
                asyncio.create_task(_power_flow_diagnostic(hass, "INFO", "power_forecast_task_complete", {
                    "request_id": request_id, "date": target_date.isoformat(),
                    "forecast_active": counters["forecast_active"],
                }))

        task.add_done_callback(clear)
    else:
        await _power_flow_diagnostic(hass, "INFO", "power_forecast_join_existing", {
            "request_id": request_id, "date": target_date.isoformat(), "forecast_active": counters["forecast_active"],
        })
    result = await asyncio.shield(task)
    return result


async def _build_power_forecast_state(
    hass,
    site_id,
    timezone_name,
    *,
    rows,
    load_forecast,
    binding,
    now,
    active_battery_generation_ids,
    active_solar_generation_ids,
    open_meteo_targets,
    solar_facts,
    target_date,
    power_calibration,
    request_id=None,
):
    """Build one immutable forecast result for a shared site/day computation."""
    collector = hass.data.get(DOMAIN, {}).get("canonical_collector")
    identity = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    if rows is None:
        history_started = time.monotonic()
        rows = await hass.async_add_executor_job(
            collector.storage.read_site_energy_history,
            str(site_id), now - timedelta(days=30), now,
        )
        await _power_flow_diagnostic(hass, "INFO", "power_history_read_complete", {
            "request_id": request_id, "date": target_date.isoformat(),
            "duration_ms": round((time.monotonic() - history_started) * 1000, 3), "row_count": len(rows),
        })
    open_meteo_frames = []
    try:
        frames_started = time.monotonic()
        raw_frames = await hass.async_add_executor_job(
            partial(
                collector.storage.read_external_input_frames,
                now,
                source_scope="site",
                site_id=str(site_id),
                logical_role="solar.irradiance.day_ahead_pv_forecast",
            ),
        )
        await _power_flow_diagnostic(hass, "INFO", "power_input_frames_read_complete", {
            "request_id": request_id, "date": target_date.isoformat(),
            "duration_ms": round((time.monotonic() - frames_started) * 1000, 3), "frame_count": len(raw_frames),
        })
        open_meteo_frames = [
            {
                **frame,
                "known_at": frame.get("known_at"),
                "valid_from": frame.get("valid_from"),
                "valid_to": frame.get("valid_to"),
            }
            for frame in raw_frames
        ]
    except Exception:
        open_meteo_frames = []
    build_started = time.monotonic()
    result = build_power_forecast(
        str(site_id), timezone_name, rows, load_forecast, solar_facts, binding, now,
        active_battery_generation_ids,
        active_solar_generation_ids=active_solar_generation_ids,
        target_date=target_date,
        open_meteo_frames=open_meteo_frames,
        open_meteo_targets=open_meteo_targets,
        learning_calibration=power_calibration,
    )
    await _power_flow_diagnostic(hass, "INFO", "power_forecast_build_complete", {
        "request_id": request_id, "date": target_date.isoformat(),
        "duration_ms": round((time.monotonic() - build_started) * 1000, 3),
        "series_count": len(result.get("series", {})),
    })
    result["learning_calibration"] = power_calibration
    return result


def _optimizer_datetime(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


async def _async_optimizer_runtime_inputs(hass, site_id):
    """Build optimizer inputs from the existing causal baseline forecast only."""
    decision_at = dt_util.now().astimezone(timezone.utc)
    if not isinstance(site_id, str) or not site_id:
        return {"site_id": site_id or "", "known_at": decision_at.isoformat(), "slots": []}
    identity = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    config = (getattr(identity, "state", {}).get("site_configs", {}).get(site_id, {}) if identity else {})
    timezone_name, _ = resolve_timezone(
        (config.get("location") or {}).get("timezone"),
        getattr(getattr(hass, "config", None), "time_zone", None),
    )
    zone = ZoneInfo(timezone_name)
    local_today = decision_at.astimezone(zone).date()
    load_forecast = await _async_load_forecast_state(hass, site_id)
    power_states = [
        await _async_power_forecast_state(
            hass,
            requested_date=local_today + timedelta(days=offset),
            requested_site_id=site_id,
            load_forecast=load_forecast,
        )
        for offset in (0, 1)
    ]
    price_by_valid_at = {}
    entry = next(iter(hass.config_entries.async_entries(DOMAIN)), None)
    coordinator = entry.runtime_data if entry else None
    if coordinator is not None:
        for target_date in (local_today, local_today + timedelta(days=1)):
            data = await coordinator.async_get_price_data(target_date)
            if data is None or data.error:
                continue
            for period in data.periods:
                start = _optimizer_datetime(getattr(period, "start", None))
                price = getattr(period, "price", None)
                if start is None:
                    continue
                try:
                    price = float(price)
                except (TypeError, ValueError):
                    continue
                if price == price and abs(price) != float("inf"):
                    price_by_valid_at[start] = price

    points_by_valid_at = {}
    for forecast in power_states:
        series = forecast.get("series", {}) if isinstance(forecast, dict) else {}
        load_points = (series.get("consumption") or {}).get("forecast_points", [])
        solar_points = (series.get("solar") or {}).get("forecast_points", [])
        loads = {valid_at: point for point in load_points if isinstance(point, dict) for valid_at in [_optimizer_datetime(point.get("valid_at"))] if valid_at is not None}
        solar = {valid_at: point for point in solar_points if isinstance(point, dict) for valid_at in [_optimizer_datetime(point.get("valid_at"))] if valid_at is not None}
        for valid_at in sorted(set(loads) & set(solar) & set(price_by_valid_at)):
            if valid_at is None or valid_at <= decision_at or valid_at in points_by_valid_at:
                continue
            load_kw = loads[valid_at].get("value_kw")
            solar_kw = solar[valid_at].get("value_kw")
            try:
                load_kw, solar_kw = float(load_kw), float(solar_kw)
            except (TypeError, ValueError):
                continue
            if not all(value == value and abs(value) != float("inf") and value >= 0 for value in (load_kw, solar_kw)):
                continue
            points_by_valid_at[valid_at] = {
                "valid_at": valid_at.isoformat(),
                "load_kw": load_kw,
                "solar_kw": solar_kw,
                "import_price_sek_per_kwh": price_by_valid_at[valid_at],
            }

    selected = []
    current = []
    for valid_at in sorted(points_by_valid_at):
        if current and (valid_at - current[-1]).total_seconds() != 900:
            if len(current) >= 96 and not selected:
                selected = current
            current = []
        current.append(valid_at)
    if len(current) >= 96 and not selected:
        selected = current
    if not selected:
        selected = current
    slots = [points_by_valid_at[valid_at] for valid_at in selected[:144]]

    class _Capture:
        def __init__(self):
            self.payload = None

        def send_result(self, _message_id, payload):
            self.payload = payload

    capture = _Capture()
    state_handler = getattr(websocket_ella_site_state, "__wrapped__", websocket_ella_site_state)
    state_result = state_handler(
        hass,
        capture,
        {"id": 1, "type": ELLA_SITE_STATE_COMMAND, "site_id": site_id},
    )
    if inspect.isawaitable(state_result):
        await state_result
    state = capture.payload if isinstance(capture.payload, dict) else {}
    twin = state.get("ess_digital_twin") if isinstance(state.get("ess_digital_twin"), dict) else {}
    resources = twin.get("resources") if isinstance(twin.get("resources"), list) else []
    resource_identity = None
    if len(resources) == 1 and isinstance(resources[0], dict) and isinstance(resources[0].get("resource_id"), str):
        resource_identity = {
            "available": True,
            "site_id": site_id,
            "resource_id": resources[0]["resource_id"],
            "method": "strong_registry_config_entry_and_device_identity",
        }
    resource_state = resources[0].get("state") if len(resources) == 1 and isinstance(resources[0], dict) else {}
    soc_percent = resource_state.get("soc_percent") if isinstance(resource_state, dict) else None
    try:
        soc_fraction = float(soc_percent) / 100.0
    except (TypeError, ValueError):
        soc_fraction = None
    return {
        "site_id": site_id,
        "known_at": decision_at.isoformat(),
        "slots": slots,
        "ess": {
            "soc_fraction": soc_fraction,
            "resource_identity": resource_identity,
        },
    }


@websocket_api.websocket_command({
    vol.Required("type"): POWER_FORECAST_COMMAND,
    vol.Optional("date"): str,
})
@websocket_api.async_response
async def websocket_power_forecast(hass, connection, msg):
    requested_date = None
    if msg.get("date"):
        try:
            requested_date = date.fromisoformat(msg["date"])
        except ValueError:
            connection.send_result(msg["id"], {"available": False, "reason": "invalid_date", "series": {}})
            return
    connection.send_result(msg["id"], await _async_power_forecast_state(hass, requested_date=requested_date))


async def _async_load_forecast_state(
    hass,
    requested_site_id: str | None = None,
    request_id=None,
) -> dict:
    """Share one in-flight immutable frame read between concurrent callers."""
    identity = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    site_id = requested_site_id or (getattr(identity, "state", {}).get("active_site_id") if identity else None)
    if not site_id:
        return {"available": False, "reason": "site_unconfigured", "frames": []}
    domain_data = hass.data.setdefault(DOMAIN, {})
    inflight = domain_data.setdefault("load_forecast_inflight", {})
    key = str(site_id)
    task = inflight.get(key)
    if task is None:
        task = asyncio.create_task(_async_load_forecast_state_uncached(hass, key, request_id))
        inflight[key] = task

        def clear(completed, request_key=key):
            if inflight.get(request_key) is completed:
                inflight.pop(request_key, None)

        task.add_done_callback(clear)
    return await asyncio.shield(task)


async def _async_load_forecast_state_uncached(
    hass,
    requested_site_id: str | None = None,
    request_id=None,
) -> dict:
    """Serialize the active site's immutable load forecast, if available."""
    identity = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    collector = hass.data.get(DOMAIN, {}).get("canonical_collector")
    site_id = requested_site_id or (getattr(identity, "state", {}).get("active_site_id") if identity else None)
    if not site_id or collector is None:
        return {"available": False, "reason": "site_unconfigured", "frames": []}
    now = dt_util.now().astimezone()
    try:
        started = time.monotonic()
        frames = await hass.async_add_executor_job(
            partial(
                collector.storage.read_external_input_frames,
                now,
                source_scope="site",
                site_id=site_id,
                logical_role="load.forecast",
            ),
        )
        await _power_flow_diagnostic(hass, "INFO", "load_input_frames_read_complete", {
            "request_id": request_id, "site_id": site_id,
            "duration_ms": round((time.monotonic() - started) * 1000, 3), "frame_count": len(frames),
        })
    except Exception:
        return {"available": False, "reason": "history_unavailable", "frames": []}
    serialized = []
    for frame in frames:
        serialized.append({
            "frame_id": frame["frame_id"], "revision": frame["revision"],
            "site_id": frame["site_id"], "known_at": frame["known_at"].isoformat(),
            "valid_from": frame["valid_from"].isoformat() if frame.get("valid_from") else None,
            "valid_to": frame["valid_to"].isoformat() if frame.get("valid_to") else None,
            "payload_schema": frame["payload_schema"], "source_generation_id": frame.get("source_generation_id"),
            "classification": frame.get("classification"), "quality_status": frame["quality_status"],
            "quality": frame["quality"], "provenance": frame["provenance"],
            "points": [{"point_id": point["point_id"], "point_key": point["point_key"],
                        "valid_at": point["valid_at"].isoformat(), "value": point["value"],
                        "unit": point["unit"], "quality_status": point["quality_status"],
                        "point": point["point"]} for point in frame["points"]],
        })
    return {"available": bool(serialized), "reason": None if serialized else "no_supported_history", "frames": serialized}


def _ella_entity_available(hass, entity_id: str) -> bool:
    """Check only explicit registry/state presence; never infer an entity by name."""
    registry = er.async_get(hass)
    registry_entry = registry.async_get(entity_id) if registry is not None and hasattr(registry, "async_get") else None
    states = getattr(hass, "states", None)
    state = states.get(entity_id) if states is not None and hasattr(states, "get") else None
    return registry_entry is not None or state is not None


@websocket_api.websocket_command({vol.Required("type"): LOAD_FORECAST_COMMAND})
@websocket_api.async_response
async def websocket_load_forecast(hass, connection, msg):
    connection.send_result(msg["id"], await _async_load_forecast_state(hass))


@websocket_api.websocket_command({vol.Required("type"): FORECAST_EVALUATION_COMMAND, vol.Optional("site_id"): str})
@websocket_api.async_response
async def websocket_ella_forecast_evaluation(hass, connection, msg):
    site_id, error = _ella_requested_site(hass, msg)
    learning_store = hass.data.get(DOMAIN, {}).get("ella_learning_store")
    if error or learning_store is None:
        connection.send_result(msg["id"], {"success": False, "available": False, "error": error or "learning_store_unavailable"})
        return
    connection.send_result(msg["id"], {"success": True, **learning_store.public_state(site_id, include_records=True)})


def _ella_site_manager(hass):
    return hass.data.get(DOMAIN, {}).get("site_identity_manager")


def _ella_load_registry(hass):
    return hass.data.get(DOMAIN, {}).get("ella_load_registry")


def _ella_requested_site(hass, msg, *, required: bool = False):
    identity = _ella_site_manager(hass)
    if identity is None:
        return None, "site_manager_unavailable"
    site_id = msg.get("site_id") or getattr(identity, "state", {}).get("active_site_id")
    if required and not isinstance(msg.get("site_id"), str):
        return None, "site_id_required"
    sites = getattr(identity, "state", {}).get("sites", [])
    if not isinstance(site_id, str) or not any(item.get("site_id") == site_id for item in sites if isinstance(item, dict)):
        return None, "site_not_found"
    return site_id, None


@websocket_api.websocket_command({vol.Required("type"): ELLA_CAPABILITIES_COMMAND, vol.Optional("site_id"): str})
@websocket_api.async_response
async def websocket_ella_capabilities(hass, connection, msg):
    site_id, error = _ella_requested_site(hass, msg)
    registry = _ella_load_registry(hass)
    if error or registry is None:
        connection.send_result(msg["id"], {"success": False, "error": error or "load_registry_unavailable"})
        return
    forecast = await _async_load_forecast_state(hass, site_id)
    try:
        inventory = build_capability_inventory(
            _ella_site_manager(hass), registry, site_id,
            load_forecast=forecast,
            entity_available=lambda entity_id: _ella_entity_available(hass, entity_id),
        )
    except ValueError as err:
        connection.send_result(msg["id"], {"success": False, "error": str(err)})
        return
    connection.send_result(msg["id"], {"success": True, **inventory})


@websocket_api.websocket_command({vol.Required("type"): ELLA_SITE_STATE_COMMAND, vol.Optional("site_id"): str, vol.Optional("date"): str})
@websocket_api.async_response
async def websocket_ella_site_state(hass, connection, msg):
    """Return the read-only, site-scoped Stage 2 decision state."""
    identity = _ella_site_manager(hass)
    registry = _ella_load_registry(hass)
    site_id, error = _ella_requested_site(hass, msg)
    if error or identity is None or registry is None:
        connection.send_result(msg["id"], {"success": False, "error": error or "site_state_unavailable"})
        return
    config = getattr(identity, "state", {}).get("site_configs", {}).get(site_id, {})
    site_timezone = (config.get("location") or {}).get("timezone")
    installation_timezone = getattr(getattr(hass, "config", None), "time_zone", None)
    try:
        timezone_name, timezone_source = resolve_timezone(site_timezone, installation_timezone)
    except ValueError:
        connection.send_result(msg["id"], {"success": False, "error": "site_timezone_unavailable", "site_id": site_id})
        return
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(timezone_name)
        target = datetime.now(zone).date()
        if msg.get("date"):
            target = date.fromisoformat(msg["date"])
    except (TypeError, ValueError, KeyError):
        connection.send_result(msg["id"], {"success": False, "error": "invalid_date_or_timezone", "site_id": site_id})
        return
    decision_at = dt_util.now()
    entry = next(iter(hass.config_entries.async_entries(DOMAIN)), None)
    coordinator = entry.runtime_data if entry else None
    price_data = await coordinator.async_get_price_data(target) if coordinator else PriceData(None, None, target, (), "price_unavailable")
    binding = identity.global_binding("nord_pool") if callable(getattr(identity, "global_binding", None)) else None
    source_id = binding.get("binding_fingerprint") if isinstance(binding, dict) else None
    collector = hass.data.get(DOMAIN, {}).get("canonical_collector")
    if collector is None:
        connection.send_result(msg["id"], {"success": False, "error": "canonical_storage_unavailable", "site_id": site_id})
        return
    from .ella_capabilities import build_capability_inventory
    skip_load_forecast = msg.get("_skip_load_forecast") is True
    forecast = (
        {"available": False, "reason": "not_required_for_empty_load_plan", "frames": []}
        if skip_load_forecast
        else await _async_load_forecast_state(hass, site_id)
    )
    learning_store = hass.data.get(DOMAIN, {}).get("ella_learning_store")
    forecast_evaluation = learning_store.public_state(site_id) if learning_store else None
    stage6_store = hass.data.get(DOMAIN, {}).get("ella_stage6_store")
    try:
        inventory = build_capability_inventory(
            identity, registry, site_id, load_forecast=forecast,
            entity_available=lambda entity_id: _ella_entity_available(hass, entity_id),
        )
        prior_stage6 = stage6_store.public_state(site_id) if stage6_store else None
        configured_loads = registry.list_for_site(site_id)
        minimal_action_plan = msg.get("_minimal_action_plan") is True
        from .ella_site_state import local_day_slots
        day_slots = local_day_slots(target, timezone_name)
        if minimal_action_plan:
            actual_rows = []
            model_points = []
            solar_frames = []
            economic_frames = []
            stage6 = prior_stage6
            ess_digital_twin = build_ess_digital_twin(site_id, [], decision_at)
        else:
            actual_rows = await hass.async_add_executor_job(
                collector.storage.read_site_energy_history,
                site_id, day_slots[0][0] - timedelta(days=60), day_slots[-1][1],
            )
            model_points = build_historical_model_points(actual_rows, timezone_name, day_slots[0][0], day_slots[-1][1])
            all_frames = await hass.async_add_executor_job(
                partial(collector.storage.read_external_input_frames, decision_at, source_scope="site", site_id=site_id)
            )
            solar_frames = [frame for frame in all_frames if str(frame.get("payload_schema", "")).startswith("forecast_solar.")]
            economic_frames = [frame for frame in all_frames if frame.get("payload_schema") == "eon.grid_economic_active_snapshot.v1"]
            stage6 = build_stage6_state(site_id, actual_rows, solar_frames, decision_at, prior_stage6)
            targets = [
                target for target in identity.collection_targets()
                if target.get("site_id") == site_id
            ]
            active_generations = {}
            resource_bindings = {}
            ess_bindings = {}
            for collection_target in targets:
                role = collection_target.get("logical_role")
                generation = collection_target.get("generation_id")
                if not role or not generation:
                    continue
                active_generations.setdefault(role, set()).add(str(generation))
                if collection_target.get("resource_id"):
                    resource_bindings[str(generation)] = str(collection_target["resource_id"])
                if role in {"battery.power", "battery.soc", "battery.capacity"}:
                    ess_bindings[role] = collection_target
            shared_ess = resolve_shared_ess_resource(site_id, ess_bindings, active_generations)
            if shared_ess.get("available"):
                for generation in shared_ess["generation_ids"].values():
                    resource_bindings[generation] = shared_ess["resource_id"]
            ess_digital_twin = build_ess_digital_twin(
                site_id, actual_rows, decision_at,
                active_generations=active_generations,
                resource_bindings=resource_bindings,
            )
        availability_by_id = {
            item.get("load_id"): item
            for item in (inventory.get("individual_loads", {}).get("items", []) if isinstance(inventory.get("individual_loads"), dict) else [])
            if isinstance(item, dict)
        }
        state_loads = [
            {**load, **availability_by_id.get(load.get("load_id"), {})}
            for load in configured_loads
        ]
        state = build_site_state(
            site_id, timezone_name, target, decision_at,
            periods=price_data.periods if price_data and not price_data.error else (),
            price_source_generation_id=source_id,
            actual_rows=actual_rows,
            load_frames=forecast.get("frames", []),
            model_points=model_points,
            capability_snapshot=inventory,
            individual_loads=state_loads,
            solar_forecast_frames=solar_frames,
            economic_frames=economic_frames,
            forecast_evaluation=forecast_evaluation,
            stage6=stage6,
            ess_digital_twin=ess_digital_twin,
            timezone_source=timezone_source,
        )
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError) as err:
        connection.send_result(msg["id"], {"success": False, "error": str(err), "site_id": site_id})
        return
    connection.send_result(msg["id"], {"success": True, **state})


@websocket_api.websocket_command({vol.Required("type"): ELLA_ACTION_PLAN_COMMAND, vol.Optional("site_id"): str, vol.Optional("date"): str})
@websocket_api.async_response
async def websocket_ella_action_plan(hass, connection, msg):
    """Return the Stage 3 shadow/recommend-only plan without device writes."""
    class _Capture:
        def __init__(self):
            self.payload = None

        def send_result(self, _message_id, payload):
            self.payload = payload

    capture = _Capture()
    state_handler = getattr(websocket_ella_site_state, "__wrapped__", websocket_ella_site_state)
    plan_msg = dict(msg)
    plan_site_id, _ = _ella_requested_site(hass, msg)
    registry = _ella_load_registry(hass)
    if isinstance(plan_site_id, str) and registry is not None:
        try:
            configured_loads = registry.list_for_site(plan_site_id)
        except Exception:
            configured_loads = None
        if configured_loads == []:
            # Price-only plans without configured individual loads do not need
            # the expensive load forecast to produce a truthful normal-operation plan.
            plan_msg["_skip_load_forecast"] = True
            plan_msg["_minimal_action_plan"] = True
    state_result = state_handler(hass, capture, plan_msg)
    if inspect.isawaitable(state_result):
        await state_result
    state = capture.payload
    if not isinstance(state, dict) or state.get("success") is not True:
        connection.send_result(msg["id"], state or {"success": False, "error": "site_state_unavailable"})
        return
    result = build_action_plan({key: value for key, value in state.items() if key != "success"})
    snapshot_store = hass.data.get(DOMAIN, {}).get("ella_debug_snapshot_store")
    if result.get("available") is True and snapshot_store is not None:
        await snapshot_store.async_put_plan({key: value for key, value in state.items() if key != "success"}, result)
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({
    vol.Required("type"): ELLA_DEBUG_SNAPSHOT_COMMAND,
    vol.Required("site_id"): str,
    vol.Required("plan_id"): str,
    vol.Required("revision"): int,
    vol.Required("plan_block_id"): str,
})
@websocket_api.async_response
async def websocket_ella_debug_snapshot(hass, connection, msg):
    """Return only the immutable persisted decision-time snapshot for one block."""
    site_id, error = _ella_requested_site(hass, msg, required=True)
    if error:
        connection.send_result(msg["id"], {"success": False, "available": False, "error": error})
        return
    snapshot_store = hass.data.get(DOMAIN, {}).get("ella_debug_snapshot_store")
    if snapshot_store is None:
        connection.send_result(msg["id"], {"success": False, "available": False, "error": "snapshot_store_unavailable"})
        return
    snapshot = snapshot_store.get(site_id, msg["plan_id"], msg["revision"], msg["plan_block_id"])
    if snapshot is None:
        connection.send_result(msg["id"], {"success": False, "available": False, "error": "snapshot_not_found_or_revision_mismatch", "site_id": site_id})
        return
    connection.send_result(msg["id"], {"success": True, "available": True, "snapshot": snapshot})


def _ella_execution_store(hass) -> EllaExecutionStore | None:
    store = hass.data.get(DOMAIN, {}).get("ella_execution_store")
    return store if isinstance(store, EllaExecutionStore) else None


def _execution_admin(connection) -> bool:
    user = getattr(connection, "user", None)
    return user is not None and getattr(user, "is_admin", False) is True


async def _verified_execution_resource(hass, site_id: str, resource_id: str, permission: dict) -> bool:
    """Verify an actuator from the current site inventory; never trust client flags."""
    identity = _ella_site_manager(hass)
    registry = _ella_load_registry(hass)
    if identity is None or registry is None:
        return False
    try:
        inventory = build_capability_inventory(
            identity,
            registry,
            site_id,
            entity_available=lambda entity_id: _ella_entity_available(hass, entity_id),
        )
    except (KeyError, TypeError, ValueError):
        return False
    if permission.get("capability_type") == "load":
        item = next((item for item in (inventory.get("individual_loads", {}).get("items") or []) if item.get("load_id") == resource_id), None)
        return bool(
            isinstance(item, dict)
            and item.get("actuator_available") is True
            and item.get("control_mode") == "controllable"
            and permission.get("actuator_id")
        )
    for capability in inventory.get("capabilities") or []:
        if not isinstance(capability, dict) or capability.get("actuator_available") is not True:
            continue
        source = capability.get("source") or {}
        resources = source.get("resources") or []
        if source.get("resource_id") == resource_id or any(isinstance(item, dict) and item.get("resource_id") == resource_id for item in resources):
            return bool(permission.get("actuator_id"))
    return False


@websocket_api.websocket_command({vol.Required("type"): ELLA_EXECUTION_STATE_COMMAND, vol.Optional("site_id"): str})
@websocket_api.async_response
async def websocket_ella_execution_state(hass, connection, msg):
    """Return permissions, ledger and breaker state; never performs a write."""
    store = _ella_execution_store(hass)
    site_id, error = _ella_requested_site(hass, msg)
    if store is None or error:
        connection.send_result(msg["id"], {"success": False, "error": error or "execution_store_unavailable"})
        return
    connection.send_result(msg["id"], {"success": True, **store.public_state(site_id)})


@websocket_api.websocket_command({vol.Required("type"): ELLA_EXECUTION_PERMISSION_SET_COMMAND, vol.Required("permission"): dict})
@websocket_api.async_response
async def websocket_ella_execution_permission_set(hass, connection, msg):
    """Persist an explicit permission; arming requires an admin confirmation."""
    if not _execution_admin(connection):
        connection.send_result(msg["id"], {"success": False, "error": "admin_required"})
        return
    store = _ella_execution_store(hass)
    permission = msg["permission"]
    site_id = permission.get("site_id") if isinstance(permission, dict) else None
    site_id, error = _ella_requested_site(hass, {**msg, "site_id": site_id}, required=True)
    if store is None or error:
        connection.send_result(msg["id"], {"success": False, "error": error or "execution_store_unavailable"})
        return
    if permission.get("site_id") != site_id:
        connection.send_result(msg["id"], {"success": False, "error": "wrong_site"})
        return
    if permission.get("armed") is True and not await _verified_execution_resource(hass, site_id, permission.get("resource_id"), permission):
        connection.send_result(msg["id"], {"success": False, "error": "verified_controllable_actuator_required", "execution_eligible": False, "actuator_writes_enabled": False})
        return
    try:
        result = await store.async_set_permission(permission)
    except ValueError as err:
        connection.send_result(msg["id"], {"success": False, "error": str(err)})
        return
    connection.send_result(msg["id"], {"success": True, "permission": result, "execution_eligible": result["execution_eligible"], "actuator_writes_enabled": False})


@websocket_api.websocket_command({vol.Required("type"): ELLA_EXECUTION_OVERRIDE_COMMAND, vol.Required("site_id"): str, vol.Required("active"): bool, vol.Optional("reason", default="manual_override"): str})
@websocket_api.async_response
async def websocket_ella_execution_override(hass, connection, msg):
    """Set a persistent manual override that blocks automated dispatch."""
    if not _execution_admin(connection):
        connection.send_result(msg["id"], {"success": False, "error": "admin_required"})
        return
    store = _ella_execution_store(hass)
    site_id, error = _ella_requested_site(hass, msg, required=True)
    if store is None or error:
        connection.send_result(msg["id"], {"success": False, "error": error or "execution_store_unavailable"})
        return
    override = await store.async_set_manual_override(site_id, msg["active"], msg.get("reason", "manual_override"))
    connection.send_result(msg["id"], {"success": True, "site_id": site_id, "manual_override": override, "execution_eligible": False})


@websocket_api.websocket_command({
    vol.Required("type"): ELLA_EXECUTION_DISPATCH_COMMAND,
    vol.Required("site_id"): str,
    vol.Required("plan_id"): str,
    vol.Required("revision"): int,
    vol.Required("plan_block_id"): str,
    vol.Required("resource_id"): str,
    vol.Required("idempotency_key"): str,
    vol.Optional("date"): str,
})
@websocket_api.async_response
async def websocket_ella_execution_dispatch(hass, connection, msg):
    """Dispatch only through an explicitly registered vendor-neutral adapter."""
    if not _execution_admin(connection):
        connection.send_result(msg["id"], {"success": False, "status": "REJECTED", "failure_class": "admin_required", "execution_eligible": False, "actuator_writes_enabled": False})
        return
    store = _ella_execution_store(hass)
    site_id, error = _ella_requested_site(hass, msg, required=True)
    if store is None or error:
        connection.send_result(msg["id"], {"success": False, "status": "REJECTED", "failure_class": error or "execution_store_unavailable", "execution_eligible": False, "actuator_writes_enabled": False})
        return
    class _Capture:
        def __init__(self):
            self.payload = None

        def send_result(self, _message_id, payload):
            self.payload = payload

    capture = _Capture()
    state_handler = getattr(websocket_ella_action_plan, "__wrapped__", websocket_ella_action_plan)
    state_handler_msg = {"id": -msg["id"], "type": ELLA_ACTION_PLAN_COMMAND, "site_id": site_id}
    if msg.get("date"):
        state_handler_msg["date"] = msg["date"]
    state_result = state_handler(hass, capture, state_handler_msg)
    if inspect.isawaitable(state_result):
        await state_result
    plan = capture.payload
    if not isinstance(plan, dict) or plan.get("available") is not True:
        connection.send_result(msg["id"], {"success": False, "status": "REJECTED", "failure_class": "stale_plan", "execution_eligible": False, "actuator_writes_enabled": False})
        return
    result = await store.async_dispatch(msg, plan)
    connection.send_result(msg["id"], result)


async def _ella_loads_response(hass, msg):
    site_id, error = _ella_requested_site(hass, msg)
    registry = _ella_load_registry(hass)
    if error or registry is None:
        return {"success": False, "error": error or "load_registry_unavailable"}
    return {"success": True, "schema": "ella_load_registry.v1", "site_id": site_id, "loads": registry.list_for_site(site_id)}


@websocket_api.websocket_command({vol.Required("type"): ELLA_LOADS_LIST_COMMAND, vol.Optional("site_id"): str})
@websocket_api.async_response
async def websocket_ella_loads_list(hass, connection, msg):
    connection.send_result(msg["id"], await _ella_loads_response(hass, msg))


@websocket_api.websocket_command({vol.Required("type"): ELLA_LOADS_STATE_COMMAND, vol.Optional("site_id"): str})
@websocket_api.async_response
async def websocket_ella_loads_state(hass, connection, msg):
    connection.send_result(msg["id"], await _ella_loads_response(hass, msg))


@websocket_api.websocket_command({vol.Required("type"): ELLA_LOADS_UPSERT_COMMAND, vol.Required("site_id"): str, vol.Required("load"): dict})
@websocket_api.async_response
async def websocket_ella_loads_upsert(hass, connection, msg):
    user = getattr(connection, "user", None)
    if user is None or getattr(user, "is_admin", False) is not True:
        connection.send_result(msg["id"], {"success": False, "error": "admin_required"})
        return
    site_id, error = _ella_requested_site(hass, msg, required=True)
    registry = _ella_load_registry(hass)
    if error or registry is None:
        connection.send_result(msg["id"], {"success": False, "error": error or "load_registry_unavailable"})
        return
    try:
        load = await registry.async_upsert(site_id, msg["load"])
    except ValueError as err:
        connection.send_result(msg["id"], {"success": False, "error": str(err)})
        return
    connection.send_result(msg["id"], {"success": True, "schema": "ella_load_registry.v1", "site_id": site_id, "load": load, "execution_eligible": False})


@websocket_api.websocket_command({vol.Required("type"): ELLA_LOADS_REMOVE_COMMAND, vol.Required("site_id"): str, vol.Required("load_id"): str})
@websocket_api.async_response
async def websocket_ella_loads_remove(hass, connection, msg):
    user = getattr(connection, "user", None)
    if user is None or getattr(user, "is_admin", False) is not True:
        connection.send_result(msg["id"], {"success": False, "error": "admin_required"})
        return
    site_id, error = _ella_requested_site(hass, msg, required=True)
    registry = _ella_load_registry(hass)
    if error or registry is None:
        connection.send_result(msg["id"], {"success": False, "error": error or "load_registry_unavailable"})
        return
    removed = await registry.async_remove(site_id, msg["load_id"])
    connection.send_result(msg["id"], {"success": True, "site_id": site_id, "load_id": msg["load_id"], "removed": removed})


@websocket_api.websocket_command({vol.Required("type"): SOLAR_FORECAST_STATE_COMMAND})
@websocket_api.async_response
async def websocket_solar_forecast_state(hass, connection, msg):
    """Return current Forecast.Solar facts and stored daily baselines."""
    manager = _solar_forecast_manager(hass) if _site_is_configured(hass) else None
    connection.send_result(msg["id"], manager.public_state() if manager else SolarForecastManager._unavailable_facts())


@websocket_api.websocket_command({vol.Required("type"): ELLA_PLAN_COMMAND, vol.Optional("date"): str})
@websocket_api.async_response
async def websocket_ella_plan(hass, connection, msg):
    """Return the active site's truthful price-only plan."""
    identity = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    if identity is None:
        connection.send_result(msg["id"], {"available": False, "reason": "site_identity_unavailable", "plan_blocks": []})
        return
    site_id = identity.state.get("active_site_id")
    if not isinstance(site_id, str) or not site_id:
        connection.send_result(msg["id"], {"available": False, "reason": "site_unconfigured", "plan_blocks": []})
        return
    entry = next(iter(hass.config_entries.async_entries(DOMAIN)), None)
    coordinator = entry.runtime_data if entry else None
    if coordinator is None:
        connection.send_result(msg["id"], {"available": False, "reason": "price_unavailable", "plan_blocks": []})
        return
    target = dt_util.now().date()
    if msg.get("date"):
        try:
            target = date.fromisoformat(msg["date"])
        except ValueError:
            connection.send_result(msg["id"], {"available": False, "reason": "invalid_date", "plan_blocks": []})
            return
    data = await coordinator.async_get_price_data(target)
    binding_getter = getattr(identity, "global_binding", None)
    binding = binding_getter("nord_pool") if callable(binding_getter) else None
    stored_fingerprint = binding.get("binding_fingerprint") if isinstance(binding, dict) else None
    computed_fingerprint = SiteIdentityManager.binding_fingerprint(binding)
    if not stored_fingerprint or stored_fingerprint != computed_fingerprint:
        connection.send_result(msg["id"], {"available": False, "reason": "price_provenance_invalid", "plan_blocks": []})
        return
    decision_at = dt_util.now()
    result = build_price_only_plan(
        site_id,
        data.periods if data and not data.error else (),
        decision_at,
        source_generation_id=stored_fingerprint,
    )
    if result.get("available"):
        load_state = await _async_load_forecast_state(hass)
        actual_rows = []
        model_points = []
        collector = hass.data.get(DOMAIN, {}).get("canonical_collector")
        if collector is not None and result.get("plan_blocks"):
            try:
                starts = [datetime.fromisoformat(block["start"]) for block in result["plan_blocks"]]
                ends = [datetime.fromisoformat(block["end"]) for block in result["plan_blocks"]]
                location = identity.state.get("site_configs", {}).get(site_id, {}).get("location", {})
                timezone_name = location.get("timezone")
                actual_rows = await hass.async_add_executor_job(
                    collector.storage.read_site_energy_history,
                    site_id, decision_at - timedelta(days=60), max(ends),
                )
                if isinstance(timezone_name, str) and timezone_name:
                    model_points = build_historical_model_points(
                        actual_rows, timezone_name, min(starts), max(ends)
                    )
            except (KeyError, TypeError, ValueError):
                actual_rows = []
        result = enrich_plan_with_load(
            result, load_state.get("frames", []), actual_rows=actual_rows,
            decision_at=decision_at, model_points=model_points,
        )
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({vol.Required("type"): SOLAR_EVIDENCE_STATE_COMMAND})
@websocket_api.async_response
async def websocket_solar_evidence_state(hass, connection, msg):
    manager = hass.data.get(DOMAIN, {}).get("solar_evidence_manager") if _site_is_configured(hass) else None
    connection.send_result(msg["id"], manager.public_state() if manager else {"available": False, "days": []})


@websocket_api.websocket_command({vol.Required("type"): SITE_IDENTITY_COMMAND})
@websocket_api.async_response
async def websocket_site_identity(hass, connection, msg):
    """Return current site identity and configured source generations."""
    if response := _runtime_not_ready(hass):
        connection.send_result(msg["id"], response)
        return
    manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    connection.send_result(msg["id"], manager.public_state() if manager else {"site_id": None, "logical_roles": [], "source_ledger": []})


@websocket_api.websocket_command(
    {
        vol.Required("type"): SITE_RENAME_COMMAND,
        vol.Required("site_id"): str,
        vol.Required("name"): str,
    }
)
@websocket_api.async_response
async def websocket_site_rename(hass, connection, msg):
    manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "site_manager_unavailable"})
        return
    try:
        state = await manager.async_rename_site(msg["site_id"], msg["name"])
    except ValueError as err:
        connection.send_result(msg["id"], {"success": False, "error": str(err)})
        return
    connection.send_result(msg["id"], {"success": True, **state})


@websocket_api.websocket_command(
    {
        vol.Required("type"): SITE_CREATE_COMMAND,
        vol.Required("name"): str,
    }
)
@websocket_api.async_response
async def websocket_site_create(hass, connection, msg):
    manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "site_manager_unavailable"})
        return
    try:
        state = await manager.async_create_site(msg["name"])
    except ValueError as err:
        connection.send_result(msg["id"], {"success": False, "error": str(err)})
        return
    connection.send_result(msg["id"], {"success": True, **state})


@websocket_api.websocket_command(
    {
        vol.Required("type"): SITE_ACTIVATE_COMMAND,
        vol.Required("site_id"): str,
        vol.Required("confirm"): bool,
    }
)
@websocket_api.async_response
async def websocket_site_activate(hass, connection, msg):
    manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "site_manager_unavailable"})
        return
    if msg["confirm"] is not True:
        connection.send_result(msg["id"], {"success": False, "error": "confirmation_required"})
        return
    try:
        state = await manager.async_activate_site(msg["site_id"])
    except ValueError as err:
        connection.send_result(msg["id"], {"success": False, "error": str(err)})
        return
    connection.send_result(msg["id"], {"success": True, **state})


@websocket_api.websocket_command(
    {
        vol.Required("type"): ELLA_BINDING_SET_COMMAND,
        vol.Required("site_id"): str,
        vol.Required("enabled"): bool,
    }
)
@websocket_api.async_response
async def websocket_ella_binding_set(hass, connection, msg):
    """Explicitly grant/revoke planner-only ELLA capability for one site."""
    user = getattr(connection, "user", None)
    if user is None or getattr(user, "is_admin", False) is not True:
        connection.send_result(msg["id"], {"success": False, "error": "admin_required"})
        return
    manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "site_manager_unavailable"})
        return
    try:
        state = await manager.async_set_ella_planner_binding(msg["site_id"], msg["enabled"])
    except ValueError as err:
        connection.send_result(msg["id"], {"success": False, "error": str(err)})
        return
    connection.send_result(msg["id"], {"success": True, **state})


def _solar_forecast_manager(hass) -> SolarForecastManager | None:
    return hass.data.get(DOMAIN, {}).get("solar_forecast_manager")


def _serialize_price_data(hass: HomeAssistant, data: PriceData | None) -> dict:
    """Serialize backend data without creating a Home Assistant entity."""
    if data is None:
        return {"error": "integration_unavailable", "periods": []}

    manager = _elhandel_manager(hass)
    provider_data = manager.provider_data() if manager else None
    customer_price_data = build_customer_price_data(data.periods, provider_data)
    grid_manager = _grid_manager(hass)
    grid_state = _active_grid_state(hass, grid_manager)
    grid_price = grid_state.get("grid_price") if isinstance(grid_state, dict) else None
    grid_contract_is_current = grid_price_is_current(grid_price)
    grid_cost_ex_vat = (
        grid_variable_cost_ex_vat(grid_price)
        if grid_contract_is_current
        else None
    )
    grid_variable_gross = (
        grid_price.get("variable_total_ore_per_kwh_gross")
        if isinstance(grid_price, dict)
        and grid_contract_is_current
        else None
    )
    grid_source_status = (
        grid_price.get("contract_source_status")
        if isinstance(grid_price, dict)
        else None
    )
    grid_preview_applied = (
        grid_price.get("preview_applied") is True
        if isinstance(grid_price, dict)
        else False
    )
    result = {
        "error": data.error,
        "area": data.area,
        "currency": data.currency,
        "date": data.date.isoformat(),
        "mode": customer_price_data.mode,
        "adjustments": {
            "provider": customer_price_data.provider,
            "electricity_cost_ex_vat": customer_price_data.electricity_cost_ex_vat,
            "grid_cost_ex_vat": grid_cost_ex_vat,
            "grid_price": grid_price,
        },
        "periods": [
            {
                "start": period.start.isoformat(),
                "end": period.end.isoformat(),
                "price": period.customer_price,
                "spot_price_ex_vat": period.spot_price_ex_vat,
                "electricity_cost_ex_vat": period.electricity_cost_ex_vat,
                "subtotal_ex_vat": period.subtotal_ex_vat,
                "vat": period.vat,
                "customer_price": period.customer_price,
                "grid_cost_ex_vat": grid_cost_ex_vat,
                "trade_customer_price_ore_per_kwh": period.customer_price * 100,
                "grid_provider": "eon" if grid_price else None,
                "grid_contract_source_status": grid_source_status,
                "grid_contract_preview_applied": grid_preview_applied,
                "grid_vat_included": grid_price.get("vat_included") if isinstance(grid_price, dict) else None,
                "grid_transfer_ore_per_kwh": grid_price.get("transfer_ore_per_kwh_gross") if isinstance(grid_price, dict) else None,
                "grid_energy_tax_ore_per_kwh": grid_price.get("energy_tax_ore_per_kwh_gross") if isinstance(grid_price, dict) else None,
                "grid_variable_ore_per_kwh": grid_variable_gross,
                "total_customer_price_ore_per_kwh": (
                    period.customer_price * 100 + grid_variable_gross
                    if grid_variable_gross is not None
                    else None
                ),
            }
            for period in customer_price_data.periods
        ],
    }
    if data.area:
        site_manager = hass.data.get(DOMAIN, {}).get("site_identity_manager")
        bound_price = site_manager.global_binding("nord_pool") if site_manager else None
        bound_entry_id = bound_price.get("config_entry_id") if isinstance(bound_price, dict) else None
        nord_pool_entry = next(
            (
                entry for entry in hass.config_entries.async_entries(NORD_POOL_DOMAIN)
                if bound_entry_id and entry.entry_id == bound_entry_id
            ),
            None,
        )
        if nord_pool_entry:
            registry = er.async_get(hass)
            for key in ("current_price", "lowest_price", "highest_price"):
                entity_id = registry.async_get_entity_id(
                    "sensor", NORD_POOL_DOMAIN, f"{data.area}-{key}"
                )
                if entity_id:
                    registry_entry = registry.async_get(entity_id)
                    if registry_entry and registry_entry.config_entry_id == nord_pool_entry.entry_id:
                        state = hass.states.get(entity_id)
                        result[key] = _serialize_sensor_state(state)
    return result


def _serialize_sensor_state(state) -> dict | None:
    """Serialize one existing Nord Pool sensor state."""
    if state is None:
        return None
    return {
        "state": state.state,
        "start": state.attributes.get("start"),
        "end": state.attributes.get("end"),
    }
