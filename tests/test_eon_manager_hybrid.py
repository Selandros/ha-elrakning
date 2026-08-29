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


def _manager(config=None):
    manager = object.__new__(manager_module.EonGridManager)
    manager.hass = object()
    manager._web_session = object()
    manager._app_test_session = None
    manager._app_test_source = None
    manager._app_test_summary = None
    manager._app_test_locations = []
    manager._web_test_locations = []
    manager._web_test_state = {"status": "not_configured"}
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


class _WebClient:
    payload = None

    def __init__(self, session):
        self.session = session

    async def async_get_user(self, customer_id):
        return self.payload


def _enrich(profile, app_installation, consumption):
    _WebClient.payload = profile
    original = manager_module.EonClient
    manager_module.EonClient = _WebClient
    manager = _manager()
    state = {
        "agreement": {"status": "configured"},
        "facility": {"price_area": "SE2"},
        "consumption": consumption,
        "tariff": None,
        "cost": None,
    }
    try:
        asyncio.run(manager._enrich_app_state_from_web(
            state, app_installation, manager._config()
        ))
    finally:
        manager_module.EonClient = original
    return state


def test_hybrid_matches_web_contract_by_pod_and_enriches_state():
    state = _enrich(
        _profile(("web-installation", "shared-pod")),
        {"installation_identifier": "app-installation", "point_of_delivery_number": "shared-pod"},
        {"status": "ok", "consumption_kwh": 10},
    )
    assert state["web_data"]["status"] == "ok"
    assert state["tariff"]["subscription_fee_sek_per_month"] == 100
    assert state["facility"]["fuse_ampere"] == 16
    assert state["cost"]["total_sek"] == 113


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


def test_hybrid_matches_web_contract_by_installation_identifier():
    state = _enrich(
        _profile(("shared-installation", "web-pod")),
        {"installation_identifier": "shared-installation", "point_of_delivery_number": "app-pod"},
        {"status": "ok", "consumption_kwh": 10},
    )
    assert state["web_data"]["status"] == "ok"
    assert state["tariff"] is not None


def test_hybrid_requires_one_unambiguous_match():
    ambiguous = _enrich(
        _profile(("shared", "pod-a"), ("shared", "pod-b")),
        {"installation_identifier": "shared", "point_of_delivery_number": "unused"},
        {"status": "ok", "consumption_kwh": 10},
    )
    missing = _enrich(
        _profile(("other", "other-pod")),
        {"installation_identifier": "missing", "point_of_delivery_number": "target"},
        {"status": "ok", "consumption_kwh": 10},
    )
    for state in (ambiguous, missing):
        assert state["web_data"]["error"] == "web_contract_match_required"
        assert state["tariff"] is None


def test_padded_app_consumption_does_not_calculate_web_cost():
    state = _enrich(
        _profile(("installation", "pod")),
        {"installation_identifier": "installation", "point_of_delivery_number": "pod"},
        {"status": "missing", "reason": "padded"},
    )
    assert state["tariff"] is not None
    assert state["cost"] is None


def test_web_auth_failure_preserves_app_state_without_global_reauth():
    class _FailingClient:
        def __init__(self, session):
            pass

        async def async_get_user(self, customer_id):
            raise manager_module.EonAuthError("reauth_required")

    original = manager_module.EonClient
    manager_module.EonClient = _FailingClient
    manager = _manager()
    state = {
        "facility": {"point_of_delivery_number": "internal-pod"},
        "consumption": {"status": "ok", "consumption_kwh": 4},
        "outage": {"status": "no_known_outage"},
        "tariff": None,
        "cost": None,
    }
    try:
        asyncio.run(manager._enrich_app_state_from_web(
            state, {"installation_identifier": "app", "point_of_delivery_number": "pod"}, manager._config()
        ))
    finally:
        manager_module.EonClient = original
    assert state["consumption"]["status"] == "ok"
    assert state["facility"]["point_of_delivery_number"] == "internal-pod"
    assert state["outage"]["status"] == "no_known_outage"
    assert state["web_data"]["status"] == "error"
    assert "reauth_required" not in state


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


def test_app_test_login_uses_only_its_isolated_app_session():
    calls = []

    class _AppSession:
        def __init__(self, hass):
            calls.append("created")

        async def async_login(self, account_id, password):
            calls.append((account_id, password))

    original = manager_module.EonAppSession
    manager_module.EonAppSession = _AppSession
    try:
        result = asyncio.run(_manager().async_app_test_login("synthetic-account", "synthetic-password"))
    finally:
        manager_module.EonAppSession = original
    assert result["status"] == "authenticated"
    assert calls == ["created", ("synthetic-account", "synthetic-password")]


def test_web_test_login_never_falls_back_to_app_auth():
    class _UnexpectedAppSession:
        def __init__(self, hass):
            raise AssertionError("app auth was used")

    original = manager_module.EonAppSession
    manager_module.EonAppSession = _UnexpectedAppSession
    try:
        result = asyncio.run(_manager().async_web_test_login("synthetic-account", "synthetic-password"))
    finally:
        manager_module.EonAppSession = original
    assert result["status"] == "browser_attestation_required"


def test_app_and_web_comparison_reports_pod_and_installation_matches_without_values():
    app = [{"point_of_delivery_number": "shared-pod", "installation_identifier": "app-id"}]
    web = [{"point_of_delivery_number": "shared-pod", "installation_identifier": "web-id"}]
    fields = manager_module._comparison_fields(app, web)
    assert fields[1] == {"field": "POD match", "app": "ja", "web": "ja"}
    assert fields[2] == {"field": "Installation ID match", "app": "nej", "web": "nej"}
    web[0]["installation_identifier"] = "app-id"
    assert manager_module._comparison_fields(app, web)[2]["app"] == "ja"


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


def test_saving_app_credentials_preserves_existing_web_configuration():
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
    assert saved[0]["web"]["customer_id"] == "web-customer"
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
    config = manager.entry.data["eon_grid"]
    assert config["auth"] == "app"
    assert config["account_id"] == "account"
    assert config["web"]["customer_id"] == "web-customer"
