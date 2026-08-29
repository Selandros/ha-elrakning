import asyncio
import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).parents[1]
PKG = "custom_components.elrakning.elnat"


def _load_manager():
    homeassistant = types.ModuleType("homeassistant")
    helpers = types.ModuleType("homeassistant.helpers")
    event = types.ModuleType("homeassistant.helpers.event")
    event.async_track_time_interval = lambda *args, **kwargs: None
    event.async_call_later = lambda *args, **kwargs: None
    storage = types.ModuleType("homeassistant.helpers.storage")
    storage.Store = type("Store", (), {})
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_create_clientsession = lambda *args, **kwargs: None
    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.helpers", helpers)
    sys.modules.setdefault("homeassistant.helpers.event", event)
    sys.modules.setdefault("homeassistant.helpers.storage", storage)
    sys.modules.setdefault("homeassistant.helpers.aiohttp_client", aiohttp_client)

    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientError = type("ClientError", (Exception,), {})
    aiohttp.ClientResponse = object
    aiohttp.ClientSession = object
    aiohttp.CookieJar = type("CookieJar", (), {})
    sys.modules.setdefault("aiohttp", aiohttp)
    yarl = types.ModuleType("yarl")
    yarl.URL = str
    sys.modules.setdefault("yarl", yarl)

    const = types.ModuleType("custom_components.elrakning.const")
    const.DOMAIN = "elrakning"
    const.EON_GRID_CONFIG_KEY = "eon_grid"
    const.EON_GRID_PROVIDER = "eon"
    const.EON_GRID_UPDATE_EVENT = "eon_update"
    const.GRID_CONFIG_KEY = "grid_config"
    sys.modules["custom_components.elrakning.const"] = const
    for name in ("custom_components", "custom_components.elrakning", PKG):
        package = sys.modules.setdefault(name, types.ModuleType(name))
        package.__path__ = []
    for module_name in ("eon_auth", "eon_client", "eon_models", "eon_manager"):
        full_name = f"{PKG}.{module_name}"
        path = ROOT / "custom_components/elrakning/elnat" / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(full_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = module
        spec.loader.exec_module(module)
    return sys.modules[f"{PKG}.eon_manager"]


manager_module = _load_manager()


def _load_registry():
    name = f"{PKG}.provider_registry"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "custom_components/elrakning/elnat/provider_registry.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _manager(config=None):
    manager = object.__new__(manager_module.EonGridManager)
    manager.hass = object()
    manager._web_session = object()
    manager._config = lambda: config or {"web": {"cookies": {"MyEonSession": "cookie"}, "customer_id": "web-customer"}}
    return manager


def _profile(*facilities):
    return {
        "customerIdentifier": "web-customer",
        "privateContractAccounts": [{
            "deliveryContracts": [
                {"installation": {
                    "installationIdentifier": item[0],
                    "pointOfDeliveryNumber": item[1],
                    "gridArea": {"priceArea": "SE2"},
                    "fuse": {"size": 16},
                }, "engagements": [{
                    "engagementType": "ELECTRICITY_GRID",
                    "engagementStatus": "ACTIVE",
                    "prices": {
                        "subscriptionFee": {"grossAmount": 100},
                        "transferFee": {"grossAmount": 90},
                        "energyTax": {"grossAmount": 40},
                    },
                }]}
                for item in facilities
            ],
        }],
    }


def test_app_only_refresh_keeps_middlelayer_state_without_web_tariff():
    from datetime import date

    class _AppClient:
        def __init__(self, session):
            pass

        async def async_get_contract_accounts(self):
            return {"allAccountIds": ["account"]}

        async def async_get_locations(self):
            return [{"installations": [{
                "id": "app-installation", "podId": "app-pod", "productType": "ELECTRICITY",
                "serviceType": "GRID", "production": False, "isFuture": False,
                "priceArea": "SE2", "address": {"fullStreet": "Street 1", "city": "Town", "postalCode": "123 45"},
            }]}]

        async def async_get_monthly_transfer(self, *args):
            return {"productType": "ELECTRICITY", "aggregation": "MONTH", "transfer": [{
                "timestamp": f"{date.today():%Y-%m}-01T00:00:00Z",
                "consumption": {"total": 12, "padded": False},
            }]}

        async def async_get_outages(self, pod):
            return {"outageType": "NO_INFO", "affected": 0}

    manager = object.__new__(manager_module.EonGridManager)
    manager.entry = types.SimpleNamespace(data={"eon_grid": {
        "auth": "app", "account_id": "account", "password": "password",
    }})
    manager.state = manager_module.EonGridManager._empty_state()
    manager._app_session = object()
    manager.store = types.SimpleNamespace(async_save=lambda state: asyncio.sleep(0))
    manager.hass = types.SimpleNamespace(bus=types.SimpleNamespace(async_fire=lambda event: None))
    manager._get_app_session = lambda config, session=None: asyncio.sleep(0, result=object())
    original = manager_module.EonAppClient
    manager_module.EonAppClient = _AppClient
    try:
        result = asyncio.run(manager._refresh_app(manager._app_session))
    finally:
        manager_module.EonAppClient = original
    assert result["configured"] is True
    assert result["consumption"]["status"] == "ok"
    assert result["tariff"] is None
    assert result["reauth_required"] is False


def test_public_state_filters_internal_installation_identifiers():
    manager = object.__new__(manager_module.EonGridManager)
    manager.state = {"facility": {
        "installation_identifier": "internal-installation",
        "point_of_delivery_number": "internal-pod",
        "price_area": "SE2",
        "fuse_ampere": 16,
    }}
    manager._config = lambda: {"auth": "app", "account_id": "account", "password": "password"}
    public = manager.public_state()
    assert public["facility"] == {"price_area": "SE2", "fuse_ampere": 16}


def test_source_redaction_removes_identifiers_and_credentials():
    redacted = manager_module._redact_source_data({
        "id": "id-value", "podId": "pod-value", "installationIdentifier": "installation-value",
        "customerIdentifier": "customer-value", "access_token": "access-value",
        "MyEonSession": "session-value", "safe": "kept",
    })
    assert all(value == "[redacted]" for key, value in redacted.items() if key != "safe")
    assert redacted["safe"] == "kept"


def test_web_api_request_uses_bearer_without_explicit_web_cookies():
    calls = []

    class _Session:
        async def request(self, *args, **kwargs):
            calls.append((args, kwargs))
            return "response"

    session = object.__new__(manager_module.EonSession)
    session._session = _Session()
    session_result = asyncio.run(session._request("GET", "https://eon.example/api", "web-token"))
    assert session_result == "response"
    assert calls[0][1]["headers"] == {"Authorization": "Bearer web-token"}
    assert "cookies" not in calls[0][1]


def test_legacy_web_config_is_migrated_without_losing_app_config():
    manager = object.__new__(manager_module.EonGridManager)
    manager.entry = types.SimpleNamespace(data={"eon_grid": {
        "auth": "app", "account_id": "account", "password": "password",
        "cookies": {"MyEonSession": "cookie"}, "customer_id": "web-customer",
    }})
    migrated = manager._config_with_migration()
    assert migrated["auth"] == "app"
    assert migrated["web"]["customer_id"] == "web-customer"
    assert "cookies" not in migrated


def test_saving_app_credentials_replaces_active_auth_method():
    class _Session:
        def __init__(self, hass):
            pass

        async def async_login(self, account_id, password):
            return "app-customer"

    manager = object.__new__(manager_module.EonGridManager)
    manager.hass = types.SimpleNamespace(config_entries=types.SimpleNamespace(async_update_entry=lambda *args: None))
    manager.entry = types.SimpleNamespace(data={"eon_grid": {
        "web": {"cookies": {"MyEonSession": "cookie"}, "customer_id": "web-customer"},
    }})
    manager._app_session = None
    saved = []
    async def _save_config(value):
        saved.append(value)

    manager._save_config = _save_config
    manager._refresh_app = lambda session: asyncio.sleep(0, result={})
    original = manager_module.EonAppSession
    manager_module.EonAppSession = _Session
    try:
        asyncio.run(manager.async_save_app_credentials("account", "password"))
    finally:
        manager_module.EonAppSession = original
    assert "web" not in saved[0]
    assert saved[0]["account_id"] == "account"


def test_saving_web_cookies_preserves_existing_app_configuration():
    class _CookieSession:
        def __init__(self, hass):
            self.cookies = {"MyEonSession": "new-cookie"}

        async def bootstrap(self, cookie_header):
            return "web-customer"

    class _Client:
        def __init__(self, session):
            pass

        async def async_get_user(self, customer_id):
            return {"customerIdentifier": customer_id}

    class _ConfigEntries:
        def async_update_entry(self, entry, data):
            entry.data = data

    manager = object.__new__(manager_module.EonGridManager)
    manager.hass = types.SimpleNamespace(
        config_entries=_ConfigEntries(),
        bus=types.SimpleNamespace(async_fire=lambda event: None),
    )
    manager.entry = types.SimpleNamespace(data={"eon_grid": {
        "auth": "app", "account_id": "account", "password": "password",
    }})
    manager.store = types.SimpleNamespace(async_save=lambda state: asyncio.sleep(0))
    manager._app_session = None
    manager._refresh_app = lambda session: asyncio.sleep(0, result={})
    manager._build_state = lambda normalized, client: asyncio.sleep(0, result={})
    original_session = manager_module.EonSession
    original_client = manager_module.EonClient
    original_normalize = manager_module.normalize_user_profile
    manager_module.EonSession = _CookieSession
    manager_module.EonClient = _Client
    manager_module.normalize_user_profile = lambda payload, customer_id: {}
    try:
        asyncio.run(manager.async_save_cookie_header("MyEonSession=synthetic"))
    finally:
        manager_module.EonSession = original_session
        manager_module.EonClient = original_client
        manager_module.normalize_user_profile = original_normalize
    config = manager.entry.data["grid_config"]["provider_config"]
    assert config["auth"] == "app"
    assert config["account_id"] == "account"
    assert config["web"]["customer_id"] == "web-customer"


def test_web_credentials_report_attestation_without_using_app_auth_or_mutating_config():
    manager = object.__new__(manager_module.EonGridManager)
    manager.entry = types.SimpleNamespace(data={"eon_grid": {
        "auth": "app", "account_id": "app-account", "password": "app-password",
    }})
    result = asyncio.run(manager.async_save_web_credentials("web-account", "web-password"))
    assert result == {"status": "browser_attestation_required", "error": "browser_attestation_required"}
    assert manager.entry.data["eon_grid"]["account_id"] == "app-account"


def test_grid_registry_accepts_a_second_provider_without_core_changes():
    registry = _load_registry()
    synthetic = registry.GridProviderDefinition("synthetic", "Synthetic Grid", ("app",), lambda hass, entry: object())
    registry.GRID_PROVIDER_REGISTRY[synthetic.provider_id] = synthetic
    try:
        assert registry.get_grid_provider("synthetic") is synthetic
        entry = types.SimpleNamespace(data={"grid_config": {"provider": "synthetic"}})
        assert registry.configured_grid_provider(entry) is synthetic
    finally:
        registry.GRID_PROVIDER_REGISTRY.pop(synthetic.provider_id, None)


def test_common_api_probe_uses_existing_app_session_and_redacts_result():
    class Session:
        customer_id = "synthetic-customer"

        def __init__(self):
            self.calls = []

        async def async_request_bearer_json(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return {"status": 200, "payload": {
                "customerIdentifier": "synthetic-customer",
                "installation": {"pointOfDeliveryNumber": "synthetic-pod"},
                "prices": {"transferFee": 97},
            }}

    manager = object.__new__(manager_module.EonGridManager)
    manager._config = lambda: {"auth": "app", "customer_id": "synthetic-customer"}
    manager._app_session = Session()
    result = asyncio.run(manager.async_common_api_probe())
    assert result["status"] == "ok"
    assert result["payload"]["customerIdentifier"] == "[redacted]"
    assert result["payload"]["installation"]["pointOfDeliveryNumber"] == "[redacted]"
    method, url, kwargs = manager._app_session.calls[0]
    assert method == "GET"
    assert url.endswith("/rest/v2/user")
    assert kwargs["params"] == {"readMeterChange": "true", "customerId": "synthetic-customer"}
