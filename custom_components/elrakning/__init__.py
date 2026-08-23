"""The Elräkning integration."""

from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, ELECTRICITY_PROVIDER_UPDATE_EVENT
from .coordinator import ElrakningCoordinator
from .elhandel.manager import ElhandelManager
from .meter import MeterManager
from .websocket import async_register_websocket_commands

PANEL_PATH = DOMAIN
PANEL_LOADER_PATH = f"/{DOMAIN}/elrakning-loader.js"
PANEL_RESOURCE_PATH = f"/{DOMAIN}/elrakning-panel.js"
PANEL_MANIFEST_PATH = f"/{DOMAIN}/manifest.json"


def _schedule_price_update(hass: HomeAssistant) -> None:
    """Schedule the existing price update event on Home Assistant's loop."""
    hass.loop.call_soon_threadsafe(hass.bus.async_fire, "elrakning_price_update")


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

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Elräkning from a config entry."""
    frontend_data = hass.data.get(DOMAIN, {})
    if unsubscribe := frontend_data.pop("coordinator_unsub", None):
        unsubscribe()
    if unsubscribe := frontend_data.pop("electricity_provider_price_unsub", None):
        unsubscribe()
    if manager := frontend_data.pop("elhandel_manager", None):
        await manager.async_shutdown()
    frontend_data.pop("meter_manager", None)
    if frontend.async_panel_exists(hass, PANEL_PATH):
        frontend.async_remove_panel(hass, PANEL_PATH)
    return True
