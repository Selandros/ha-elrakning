"""The Elräkning integration."""

from functools import partial
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change

from .const import DOMAIN, EON_GRID_UPDATE_EVENT, ELECTRICITY_PROVIDER_UPDATE_EVENT, INTEGRATION_READY_EVENT, SOLAR_WEATHER_UPDATE_EVENT
from .coordinator import ElrakningCoordinator
from .elhandel.manager import ElhandelManager
from .elnat.manager import GridManager
from .elnat.eon_handoff import async_register_eon_handoff_views
from .meter import MeterManager
from .power import PowerManager
from .solar_forecast import SolarForecastManager
from .solar_shadow import SolarShadowManager
from .solar_weather import SolarWeatherManager
from .websocket import async_register_websocket_commands

PANEL_PATH = DOMAIN
PANEL_LOADER_PATH = f"/{DOMAIN}/elrakning-loader.js"
PANEL_RESOURCE_PATH = f"/{DOMAIN}/elrakning-panel.js"
PANEL_MANIFEST_PATH = f"/{DOMAIN}/manifest.json"


def _schedule_price_update(hass: HomeAssistant) -> None:
    """Schedule the existing price update event on Home Assistant's loop."""
    hass.loop.call_soon_threadsafe(hass.bus.async_fire, "elrakning_price_update")


async def _async_midnight_refresh(coordinator: ElrakningCoordinator, _now) -> None:
    """Refresh the coordinator once at the local start of each day."""
    await coordinator.async_request_refresh()
    coordinator.async_schedule_midnight_recovery()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Elräkning from a config entry."""
    coordinator = ElrakningCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    manager = ElhandelManager(hass, entry)
    await manager.async_load()
    hass.data.setdefault(DOMAIN, {})["elhandel_manager"] = manager
    if manager.state["configured"]:
        manager.async_start_refresh()
    meter_manager = MeterManager(hass, manager.async_diagnostic)
    await meter_manager.async_load()
    hass.data.setdefault(DOMAIN, {})["meter_manager"] = meter_manager
    power_manager = PowerManager(hass, manager.async_diagnostic)
    await power_manager.async_load()
    hass.data.setdefault(DOMAIN, {})["power_manager"] = power_manager
    solar_forecast_manager = SolarForecastManager(hass, manager.async_diagnostic)
    await solar_forecast_manager.async_load()
    hass.data.setdefault(DOMAIN, {})["solar_forecast_manager"] = solar_forecast_manager
    solar_weather_manager = SolarWeatherManager(hass)
    await solar_weather_manager.async_load()
    hass.data.setdefault(DOMAIN, {})["solar_weather_manager"] = solar_weather_manager
    solar_shadow_manager = SolarShadowManager(hass, solar_forecast_manager, solar_weather_manager, power_manager)
    await solar_shadow_manager.async_load()
    hass.data.setdefault(DOMAIN, {})["solar_shadow_manager"] = solar_shadow_manager
    grid_manager = GridManager(hass, entry)
    await grid_manager.async_load()
    hass.data.setdefault(DOMAIN, {})["grid_manager"] = grid_manager
    async_register_eon_handoff_views(hass)
    if grid_manager.configured:
        grid_manager.async_start_refresh()

    integration_dir = Path(__file__).parent
    frontend_data = hass.data.setdefault(DOMAIN, {})
    async_register_websocket_commands(hass)
    frontend_data["coordinator_unsub"] = coordinator.async_add_listener(
        lambda: hass.bus.async_fire("elrakning_price_update")
    )
    frontend_data["electricity_provider_price_unsub"] = hass.bus.async_listen(
        ELECTRICITY_PROVIDER_UPDATE_EVENT,
        lambda _: _schedule_price_update(hass),
    )
    frontend_data["eon_grid_unsub"] = hass.bus.async_listen(
        EON_GRID_UPDATE_EVENT,
        lambda _: _schedule_price_update(hass),
    )
    frontend_data["solar_weather_unsub"] = hass.bus.async_listen(
        SOLAR_WEATHER_UPDATE_EVENT,
        lambda _: _schedule_price_update(hass),
    )
    if unsubscribe := frontend_data.pop("midnight_refresh_unsub", None):
        unsubscribe()
    frontend_data["midnight_refresh_unsub"] = async_track_time_change(
        hass,
        partial(_async_midnight_refresh, coordinator),
        hour=0,
        minute=0,
        second=0,
    )
    if not frontend_data.get("static_path_registered"):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    PANEL_LOADER_PATH,
                    str(integration_dir / "frontend" / "elrakning-loader.js"),
                    cache_headers=False,
                ),
                StaticPathConfig(
                    PANEL_RESOURCE_PATH,
                    str(integration_dir / "frontend" / "elrakning-panel.js"),
                    cache_headers=False,
                ),
                StaticPathConfig(
                    PANEL_MANIFEST_PATH,
                    str(integration_dir / "manifest.json"),
                    cache_headers=False,
                ),
            ]
        )
        frontend_data["static_path_registered"] = True

    if not frontend.async_panel_exists(hass, PANEL_PATH):
        frontend.async_register_built_in_panel(
            hass,
            component_name="custom",
            frontend_url_path=PANEL_PATH,
            sidebar_title="Elräkning",
            sidebar_icon="mdi:flash-outline",
            config={
                "_panel_custom": {
                    "name": "elrakning-panel",
                    "js_url": PANEL_LOADER_PATH,
                    "embed_iframe": False,
                }
            },
        )

    hass.bus.async_fire(INTEGRATION_READY_EVENT)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Elräkning from a config entry."""
    frontend_data = hass.data.get(DOMAIN, {})
    if unsubscribe := frontend_data.pop("coordinator_unsub", None):
        unsubscribe()
    if unsubscribe := frontend_data.pop("electricity_provider_price_unsub", None):
        unsubscribe()
    if unsubscribe := frontend_data.pop("eon_grid_unsub", None):
        unsubscribe()
    if unsubscribe := frontend_data.pop("solar_weather_unsub", None):
        unsubscribe()
    if solar_weather_manager := frontend_data.pop("solar_weather_manager", None):
        await solar_weather_manager.async_shutdown()
    if solar_shadow_manager := frontend_data.pop("solar_shadow_manager", None):
        await solar_shadow_manager.async_shutdown()
    if unsubscribe := frontend_data.pop("midnight_refresh_unsub", None):
        unsubscribe()
    coordinator.cancel_midnight_recovery()
    if manager := frontend_data.pop("elhandel_manager", None):
        await manager.async_shutdown()
    if meter_manager := frontend_data.pop("meter_manager", None):
        await meter_manager.async_shutdown()
    if power_manager := frontend_data.pop("power_manager", None):
        await power_manager.async_shutdown()
    if solar_forecast_manager := frontend_data.pop("solar_forecast_manager", None):
        await solar_forecast_manager.async_shutdown()
    if grid_manager := frontend_data.pop("grid_manager", None):
        await grid_manager.async_shutdown()
    if frontend.async_panel_exists(hass, PANEL_PATH):
        frontend.async_remove_panel(hass, PANEL_PATH)
    return True
