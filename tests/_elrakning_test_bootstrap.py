"""Small import-only test harness for running integration units without HA installed."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys


ROOT = Path(__file__).resolve().parents[1]
CUSTOM_COMPONENTS = ROOT / "custom_components"
ELRAKNING = CUSTOM_COMPONENTS / "elrakning"


def _module(name: str, *, package: bool = False) -> ModuleType:
    value = ModuleType(name)
    if package:
        value.__path__ = []
    sys.modules[name] = value
    return value


def install_elrakning_package_stub() -> None:
    """Expose the real integration submodules without executing integration setup."""
    custom_components = sys.modules.get("custom_components")
    if custom_components is None:
        custom_components = _module("custom_components", package=True)
    custom_components.__path__ = [str(CUSTOM_COMPONENTS)]
    elrakning = sys.modules.get("custom_components.elrakning")
    if elrakning is None:
        elrakning = _module("custom_components.elrakning", package=True)
    elrakning.__path__ = [str(ELRAKNING)]
    elrakning.__package__ = "custom_components.elrakning"
    elnat = sys.modules.get("custom_components.elrakning.elnat")
    if elnat is not None:
        elnat.__path__ = [str(ELRAKNING / "elnat")]


def install_homeassistant_stubs() -> None:
    """Install only the Home Assistant symbols imported by the tested modules."""
    homeassistant = sys.modules.get("homeassistant") or _module("homeassistant", package=True)
    components = sys.modules.get("homeassistant.components") or _module("homeassistant.components", package=True)
    helpers = sys.modules.get("homeassistant.helpers") or _module("homeassistant.helpers", package=True)

    core = sys.modules.get("homeassistant.core") or _module("homeassistant.core")
    core.EVENT_STATE_CHANGED = "state_changed"
    core.Event = object
    core.callback = lambda function: function
    core.State = object
    core.HomeAssistant = object
    core.ServiceCall = object
    core.valid_entity_id = lambda value: isinstance(value, str) and "." in value

    config_entries = sys.modules.get("homeassistant.config_entries") or _module("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    class OptionsFlow:
        @property
        def config_entry(self):
            return getattr(self, "_config_entry", None)

        def async_create_entry(self, *, title, data):
            return {"type": "create_entry", "title": title, "data": data}

    class OptionsFlowWithReload(OptionsFlow):
        pass

    config_entries.OptionsFlow = OptionsFlow
    config_entries.OptionsFlowWithReload = OptionsFlowWithReload
    exceptions = sys.modules.get("homeassistant.exceptions") or _module("homeassistant.exceptions")
    exceptions.HomeAssistantError = RuntimeError

    dt_module = sys.modules.get("homeassistant.util.dt") or _module("homeassistant.util.dt")
    dt_module.now = lambda: datetime.now(timezone.utc)
    dt_module.as_local = lambda value: value
    dt_module.parse_datetime = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else None
    dt_module.start_of_local_day = lambda value: value.replace(hour=0, minute=0, second=0, microsecond=0)
    util = sys.modules.get("homeassistant.util") or _module("homeassistant.util", package=True)
    util.dt = dt_module

    storage = sys.modules.get("homeassistant.helpers.storage") or _module("homeassistant.helpers.storage")

    class Store:
        def __init__(self, *args, **kwargs):
            self.data = None

        async def async_load(self):
            return self.data

        async def async_save(self, data):
            self.data = data

    storage.Store = Store
    event = sys.modules.get("homeassistant.helpers.event") or _module("homeassistant.helpers.event")
    event.async_track_time_interval = lambda *args, **kwargs: lambda: None
    event.async_track_time_change = event.async_track_time_interval
    event.async_call_later = event.async_track_time_interval
    aiohttp_client = sys.modules.get("homeassistant.helpers.aiohttp_client") or _module("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None
    aiohttp_client.async_create_clientsession = lambda hass, *args, **kwargs: None
    entity_registry = sys.modules.get("homeassistant.helpers.entity_registry") or _module("homeassistant.helpers.entity_registry")
    entity_registry.async_get = lambda hass: SimpleNamespace(entities={})
    sun = sys.modules.get("homeassistant.helpers.sun") or _module("homeassistant.helpers.sun")
    sun.get_astral_observer = lambda *args, **kwargs: None
    update_coordinator = sys.modules.get("homeassistant.helpers.update_coordinator") or _module("homeassistant.helpers.update_coordinator")

    class DataUpdateCoordinator:
        @classmethod
        def __class_getitem__(cls, _item):
            return cls

    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator

    loader = sys.modules.get("homeassistant.loader") or _module("homeassistant.loader")
    loader.async_get_integration = lambda *args, **kwargs: None
    websocket_api = sys.modules.get("homeassistant.components.websocket_api") or _module("homeassistant.components.websocket_api")
    websocket_api.ActiveConnection = object
    websocket_api.websocket_command = lambda *args, **kwargs: lambda function: function
    websocket_api.async_response = lambda function: function
    websocket_api.async_register_command = lambda *args, **kwargs: None
    recorder = sys.modules.get("homeassistant.components.recorder") or _module("homeassistant.components.recorder")
    recorder.get_instance = lambda *args, **kwargs: None
    recorder.history = _module("homeassistant.components.recorder.history")
    weather = sys.modules.get("homeassistant.components.weather") or _module("homeassistant.components.weather")
    weather.DOMAIN = "weather"
    weather.SERVICE_GET_FORECASTS = "get_forecasts"
    http = sys.modules.get("homeassistant.components.http") or _module("homeassistant.components.http")
    http.HomeAssistantView = object

    homeassistant.components = components
    homeassistant.core = core
    homeassistant.config_entries = config_entries
    homeassistant.exceptions = exceptions
    homeassistant.helpers = helpers
    homeassistant.util = util
    components.websocket_api = websocket_api
    components.recorder = recorder
    components.weather = weather
    components.http = http
    helpers.storage = storage
    helpers.event = event
    helpers.aiohttp_client = aiohttp_client
    helpers.entity_registry = entity_registry
    helpers.sun = sun
    helpers.update_coordinator = update_coordinator


def install_optional_dependency_stubs() -> None:
    """Provide import-only aiohttp and voluptuous symbols when dependencies are absent."""
    if "aiohttp" not in sys.modules:
        aiohttp = _module("aiohttp", package=True)
        aiohttp.ClientError = RuntimeError
        aiohttp.ClientResponse = object
        aiohttp.CookieJar = object
        aiohttp.ClientSession = object
        aiohttp.web = _module("aiohttp.web")
        aiohttp.web.Request = object
        aiohttp.web.Response = object
        aiohttp.web.json_response = lambda *args, **kwargs: None
    if "voluptuous" not in sys.modules:
        voluptuous = _module("voluptuous")
        voluptuous.Required = lambda value, *args, **kwargs: value
        voluptuous.Optional = voluptuous.Required
        voluptuous.In = lambda value, *args, **kwargs: value
        voluptuous.All = lambda *values, **kwargs: values[0] if values else None
        voluptuous.Coerce = lambda value, *args, **kwargs: value
        voluptuous.Range = lambda *args, **kwargs: lambda value: value
        voluptuous.Length = lambda *args, **kwargs: lambda value: value
        voluptuous.Schema = lambda value, *args, **kwargs: value
    if "yarl" not in sys.modules:
        yarl = _module("yarl")

        class URL(str):
            pass

        yarl.URL = URL
