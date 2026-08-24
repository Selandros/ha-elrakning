"""Websocket access to Elräkning's cached price periods."""

from __future__ import annotations

import logging
from datetime import date, timedelta

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN,
    GREENELY_PROVIDER,
    NORD_POOL_DOMAIN,
    SUPPORTED_ELECTRICITY_PROVIDERS,
)
from .coordinator import ElrakningCoordinator, PriceData
from .customer_price import build_customer_price_data
from .elhandel.manager import CHART_LAYER_DEFAULTS, ElhandelManager
from .elhandel.models import ProviderData, serialize_provider_state
from .elhandel.providers.greenely_client import GreenelyClient, GreenelyError
from .elhandel.providers.greenely_consumption import normalize_greenely_consumption
from .elhandel.providers.greenely_source import paginate_source
from .meter import MeterManager

COMMAND = f"{DOMAIN}/price_data"
GREENELY_TEST_COMMAND = f"{DOMAIN}/greenely_test"
GREENELY_CONSUMPTION_TEST_COMMAND = f"{DOMAIN}/greenely_consumption_test"
GREENELY_PARSE_LATEST_COMMAND = f"{DOMAIN}/greenely_parse_latest_test"
ELECTRICITY_PROVIDER_STATE_COMMAND = f"{DOMAIN}/electricity_provider_state"
ELECTRICITY_PROVIDER_SAVE_COMMAND = f"{DOMAIN}/electricity_provider_save"
ELECTRICITY_PROVIDER_SOURCE_DATA_COMMAND = f"{DOMAIN}/electricity_provider_source_data"
ELECTRICITY_PROVIDER_REMOVE_COMMAND = f"{DOMAIN}/electricity_provider_remove"
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
    hass.data[f"{DOMAIN}_websocket_registered"] = True


@websocket_api.websocket_command({vol.Required("type"): COMMAND})
@websocket_api.async_response
async def websocket_get_price_data(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Return cached periods and discovered Nord Pool sensor values."""
    entry = next(iter(hass.config_entries.async_entries(DOMAIN)), None)
    coordinator: ElrakningCoordinator | None = entry.runtime_data if entry else None
    data = coordinator.data if coordinator else None
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
    connection.send_result(msg["id"], {"success": True, **_electricity_provider_state(_elhandel_manager(hass))})


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
    try:
        await manager.async_disconnect(purge_history=purge_history)
    except GreenelyError as err:
        connection.send_result(msg["id"], {"success": False, "error": err.code})
        return
    except Exception:
        _LOGGER.exception("Electricity provider removal failed unexpectedly")
        connection.send_result(msg["id"], {"success": False, "error": "internal_error"})
        return
    connection.send_result(msg["id"], {"success": True, **_electricity_provider_state(manager)})


@websocket_api.websocket_command({vol.Required("type"): ELECTRICITY_HISTORY_STATE_COMMAND})
@websocket_api.async_response
async def websocket_electricity_history_state(hass, connection, msg):
    manager = _elhandel_manager(hass)
    history = await manager.async_history_metadata() if manager else []
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
    connection.send_result(msg["id"], {"logs": manager.diagnostics if manager else []})


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
    chart_layers = await manager.async_get_chart_layers(connection.user.id)
    configuration_cards_visible = await manager.async_get_configuration_cards_visible(connection.user.id)
    connection.send_result(msg["id"], {
        "success": True,
        "chart_layers": chart_layers,
        "configuration_cards_visible": configuration_cards_visible,
    })


@websocket_api.websocket_command(
    {
        vol.Required("type"): CHART_LAYERS_SET_COMMAND,
        vol.Required("chart_layers"): {
            vol.Optional(key): bool for key in CHART_LAYER_DEFAULTS
        },
        vol.Optional("configuration_cards_visible"): bool,
    }
)
@websocket_api.async_response
async def websocket_chart_layers_set(hass, connection, msg):
    manager = _elhandel_manager(hass)
    if not manager or not getattr(connection, "user", None):
        connection.send_result(msg["id"], {"success": False, "error": "not_configured"})
        return
    chart_layers = await manager.async_set_chart_layers(connection.user.id, msg["chart_layers"])
    configuration_cards_visible = await manager.async_get_configuration_cards_visible(connection.user.id)
    if "configuration_cards_visible" in msg:
        configuration_cards_visible = await manager.async_set_configuration_cards_visible(
            connection.user.id, msg["configuration_cards_visible"]
        )
    connection.send_result(msg["id"], {
        "success": True,
        "chart_layers": chart_layers,
        "configuration_cards_visible": configuration_cards_visible,
    })


def _meter_manager(hass) -> MeterManager | None:
    manager = hass.data.get(DOMAIN, {}).get("meter_manager")
    return manager if isinstance(manager, MeterManager) else None


@websocket_api.websocket_command(
    {
        vol.Required("type"): METER_SAVE_COMMAND,
        vol.Optional("power_entity", default=""): str,
        vol.Optional("energy_import_entity", default=""): str,
        vol.Optional("energy_export_entity", default=""): str,
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
        vol.Optional("component", default="meter"): vol.In({"meter", "price"}),
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
    manager = _meter_manager(hass)
    state = await manager.async_state() if manager else {"configured": False}
    connection.send_result(msg["id"], {"success": True, **state})


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


def _serialize_price_data(hass: HomeAssistant, data: PriceData | None) -> dict:
    """Serialize backend data without creating a Home Assistant entity."""
    if data is None:
        return {"error": "missing_integration", "periods": []}

    manager = _elhandel_manager(hass)
    provider_state = manager.public_state() if manager else None
    customer_price_data = build_customer_price_data(data.periods, provider_state)
    result = {
        "error": data.error,
        "area": data.area,
        "currency": data.currency,
        "date": data.date.isoformat(),
        "mode": customer_price_data.mode,
        "adjustments": {
            "provider": customer_price_data.provider,
            "electricity_cost_ex_vat": customer_price_data.electricity_cost_ex_vat,
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
            }
            for period in customer_price_data.periods
        ],
    }
    if data.area:
        nord_pool_entry = next(
            iter(hass.config_entries.async_entries(NORD_POOL_DOMAIN)), None
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
