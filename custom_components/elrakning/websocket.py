"""Websocket access to Elräkning's cached price periods."""

from __future__ import annotations

import logging
from datetime import date, timedelta

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
from .customer_price import build_customer_price_data, grid_variable_cost_ex_vat
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
from .solar_forecast import SolarForecastManager
from .solar_weather import build_sun_context

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
SITE_IDENTITY_COMMAND = f"{DOMAIN}/site_identity"
SITE_RENAME_COMMAND = f"{DOMAIN}/site_rename"
SITE_CREATE_COMMAND = f"{DOMAIN}/site_create"
SITE_ACTIVATE_COMMAND = f"{DOMAIN}/site_activate"
SOLAR_FORECAST_STATE_COMMAND = f"{DOMAIN}/solar_forecast_state"
SOLAR_EVIDENCE_STATE_COMMAND = f"{DOMAIN}/solar_evidence_state"
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
    websocket_api.async_register_command(hass, websocket_site_identity)
    websocket_api.async_register_command(hass, websocket_site_rename)
    websocket_api.async_register_command(hass, websocket_site_create)
    websocket_api.async_register_command(hass, websocket_site_activate)
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
    connection.send_result(msg["id"], _serialize_price_data(hass, data))


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
    connection.send_result(msg["id"], {"success": True, **(manager.public_state() if manager else {"configured": False})})


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
    connection.send_result(msg["id"], {"success": True, **(manager.public_state() if manager else {"configured": False})})


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


@websocket_api.websocket_command({vol.Required("type"): DIAGNOSTICS_STATE_COMMAND})
@websocket_api.async_response
async def websocket_diagnostics_state(hass, connection, msg):
    manager = _elhandel_manager(hass)
    site_identity = hass.data.get(DOMAIN, {}).get("site_identity_manager")
    connection.send_result(msg["id"], {
        "logs": manager.diagnostics if manager else [],
        "site_identity": site_identity.public_state() if site_identity else {
            "site_id": None,
            "logical_roles": [],
            "source_ledger": [],
        },
    })


@websocket_api.websocket_command({vol.Required("type"): DIAGNOSTICS_CLEAR_COMMAND})
@websocket_api.async_response
async def websocket_diagnostics_clear(hass, connection, msg):
    manager = _elhandel_manager(hass)
    if manager:
        await manager.async_clear_diagnostics()
    connection.send_result(msg["id"], {"success": True})


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
        vol.Optional("component", default="meter"): vol.In({"meter", "price", "performance"}),
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
    price_periods = []
    missing_price_dates = 0
    target = start
    while target <= end:
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
        "energy_source": {
            "method": "integrated_grid_power",
            "entity_id": billing.get("entity_id"),
            "source_entity": billing.get("entity_id"),
            "raw_unit": "kW",
        },
        "integration_method": "trapezoidal_power_integration",
        "energy_coverage": billing.get("coverage", {}),
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
    }
)
@websocket_api.async_response
async def websocket_power_history(hass, connection, msg):
    manager = _power_manager(hass)
    result = await manager.async_history(msg.get("days", 1)) if manager else {
        "success": False,
        "series": {},
        "error": "power_unavailable",
    }
    forecast_manager = _solar_forecast_manager(hass)
    forecast = forecast_manager.public_state() if forecast_manager and _site_is_configured(hass) else SolarForecastManager._unavailable_facts()
    result["solar_forecast"] = forecast
    result["solar_forecast_baselines"] = forecast.get("baselines", {})
    shadow = hass.data.get(DOMAIN, {}).get("solar_shadow_manager")
    result["solar_shadow"] = shadow.public_state() if shadow and _site_is_configured(hass) else {"available": False, "snapshots": []}
    weather_manager = hass.data.get(DOMAIN, {}).get("solar_weather_manager")
    result["solar_weather"] = weather_manager.public_state() if weather_manager else {"available": False, "source": "smhi", "status": "unavailable", "current": {}, "hourly_forecast": []}
    pvgis_manager = hass.data.get(DOMAIN, {}).get("solar_pvgis_manager")
    result["solar_pvgis"] = pvgis_manager.public_state() if pvgis_manager and _site_is_configured(hass) else {"available": False, "source": "jrc_pvgis"}
    result["solar_sun"] = build_sun_context(hass)
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({vol.Required("type"): SOLAR_FORECAST_STATE_COMMAND})
@websocket_api.async_response
async def websocket_solar_forecast_state(hass, connection, msg):
    """Return current Forecast.Solar facts and stored daily baselines."""
    manager = _solar_forecast_manager(hass) if _site_is_configured(hass) else None
    connection.send_result(msg["id"], manager.public_state() if manager else SolarForecastManager._unavailable_facts())


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


def _solar_forecast_manager(hass) -> SolarForecastManager | None:
    return hass.data.get(DOMAIN, {}).get("solar_forecast_manager")


def _serialize_price_data(hass: HomeAssistant, data: PriceData | None) -> dict:
    """Serialize backend data without creating a Home Assistant entity."""
    if data is None:
        return {"error": "integration_unavailable", "periods": []}

    manager = _elhandel_manager(hass)
    provider_state = manager.public_state() if manager else None
    customer_price_data = build_customer_price_data(data.periods, provider_state)
    grid_manager = _grid_manager(hass)
    grid_state = grid_manager.public_state() if grid_manager else None
    grid_price = grid_state.get("grid_price") if isinstance(grid_state, dict) else None
    grid_cost_ex_vat = grid_variable_cost_ex_vat(grid_price)
    grid_variable_gross = (
        grid_price.get("variable_total_ore_per_kwh_gross")
        if isinstance(grid_price, dict)
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
