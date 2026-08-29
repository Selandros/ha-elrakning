import importlib.util
import sys
import time
import types
from pathlib import Path


root = Path(__file__).parents[1] / "custom_components" / "elrakning" / "elnat"
homeassistant = types.ModuleType("homeassistant")
helpers = types.ModuleType("homeassistant.helpers")
aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
aiohttp_client.async_get_clientsession = lambda hass: None
aiohttp_client.async_create_clientsession = lambda hass, **kwargs: None
homeassistant.helpers = helpers
helpers.aiohttp_client = aiohttp_client
sys.modules.setdefault("homeassistant", homeassistant)
sys.modules.setdefault("homeassistant.helpers", helpers)
sys.modules.setdefault("homeassistant.helpers.aiohttp_client", aiohttp_client)

aiohttp = types.ModuleType("aiohttp")
aiohttp.ClientError = type("ClientError", (Exception,), {})
aiohttp.ClientResponse = object
aiohttp.ClientSession = object
aiohttp.CookieJar = object
sys.modules.setdefault("aiohttp", aiohttp)
yarl = types.ModuleType("yarl")
yarl.URL = str
sys.modules.setdefault("yarl", yarl)

spec = importlib.util.spec_from_file_location("eon_auth", root / "eon_auth.py")
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)


def test_authenticator_form_parses_only_verified_hidden_fields():
    result = auth.parse_authenticator_form(
        '<form><input type="hidden" name="token" value="form-token">'
        '<input type="hidden" name="state" value="form-state">'
        '<input name="ignored" value="ignored"></form>'
    )
    assert result == {"token": "form-token", "state": "form-state"}


def test_redirect_code_requires_matching_state():
    assert auth.extract_authorization_code(
        "https://redirect?code=auth-code&state=expected&session_state=opaque", "expected"
    ) == "auth-code"
    try:
        auth.extract_authorization_code("https://redirect?code=auth-code&state=wrong", "expected")
    except auth.EonAuthError as error:
        assert error.code == "oauth_state_mismatch"
    else:
        raise AssertionError("state mismatch was accepted")


def test_app_token_response_requires_secret_sauce_and_returns_metadata_only():
    result = auth.parse_app_token_response({
        "access_token": "access",
        "refresh_token": "refresh",
        "customer_id": "customer",
        "token_type": "secret-sauce",
        "expires_in": 7199,
        "scope": "scope",
    })
    assert result["token_type"] == "secret-sauce"
    assert result["customer_id"] == "customer"


def test_auth_errors_do_not_echo_credentials():
    try:
        auth.parse_authenticator_form("password=secret")
    except auth.EonAuthError as error:
        assert str(error) == "invalid_authenticator_response"
        assert "secret" not in str(error)
    else:
        raise AssertionError("invalid form was accepted")


def test_session_expiry_uses_numeric_epoch_milliseconds_first():
    now = time.time()
    expiry = auth._expiry_from_session({
        "currentAccessTokenExpiresAt": (now + 120) * 1000,
        "tokenExpiersIn": 898000,
    })
    remaining = expiry - time.monotonic()
    assert 115 < remaining < 125


def test_session_expiry_fallback_treats_remaining_value_as_milliseconds():
    expiry = auth._expiry_from_session({"tokenExpiersIn": 898000})
    remaining = expiry - time.monotonic()
    assert 890 < remaining < 905


def test_bearer_probe_uses_isolated_session_and_returns_success_payload():
    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def json(self, **kwargs):
            return {"customerIdentifier": "synthetic-customer"}

    class Session:
        def __init__(self):
            self.calls = []

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return Response()

    session = auth.EonAppSession.__new__(auth.EonAppSession)
    session._access_token = "synthetic-token"
    session._expires_at = 10**12
    session._bearer_session = Session()
    result = __import__("asyncio").run(session.async_request_bearer_json(
        "GET", "https://example.invalid/user", params={"customerId": "synthetic-customer"}
    ))
    assert result == {"status": 200, "payload": {"customerIdentifier": "synthetic-customer"}}
    method, url, kwargs = session._bearer_session.calls[0]
    assert method == "GET"
    assert url.endswith("/user")
    assert kwargs["headers"]["Authorization"] == "Bearer synthetic-token"
    assert "cookies" not in kwargs


def test_bearer_probe_maps_denied_status_without_payload():
    class Response:
        status = 403

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    class Session:
        def request(self, method, url, **kwargs):
            return Response()

    session = auth.EonAppSession.__new__(auth.EonAppSession)
    session._access_token = "synthetic-token"
    session._expires_at = 10**12
    session._bearer_session = Session()
    result = __import__("asyncio").run(session.async_request_bearer_json("GET", "https://example.invalid/user"))
    assert result == {"status": 403, "payload": None}


def test_bearer_probe_requires_existing_token():
    session = auth.EonAppSession.__new__(auth.EonAppSession)
    session._access_token = None
    session._expires_at = 10**12
    try:
        __import__("asyncio").run(session.async_request_bearer_json("GET", "https://example.invalid/user"))
    except auth.EonAuthError as error:
        assert error.code == "reauth_required"
    else:
        raise AssertionError("probe accepted a missing app token")


def test_web_refresh_uses_supported_request_and_updates_dynamic_expiry():
    import asyncio

    class Morsel:
        def __init__(self, value):
            self.value = value

    class Jar:
        def __init__(self):
            self.updates = []

        def filter_cookies(self, url):
            return {"MyEonSession": Morsel("synthetic-cookie")}

        def update_cookies(self, cookies, response_url=None):
            self.updates.append((cookies, response_url))

    class Response:
        status = 200
        cookies = {"MyEonAccessToken": "synthetic-response-cookie"}
        url = "https://www.eon.se/bin/eon-se/codeflow/refreshToken"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def json(self, **kwargs):
            return {
                "access_token": "synthetic-new-token",
                "refresh_token": "synthetic-refresh",
                "scope": "scope",
                "expires_in": 300,
                "errorCode": 0,
            }

    class Session:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return Response()

    session = auth.EonSession.__new__(auth.EonSession)
    session._session = Session()
    session._jar = Jar()
    session._access_token = "synthetic-old-token"
    session._expires_at = 0.0
    asyncio.run(session.refresh())

    assert session._access_token == "synthetic-new-token"
    assert 299 <= session.seconds_until_expiry <= 300
    url, kwargs = session._session.calls[0]
    assert url.endswith("/refreshToken")
    assert kwargs["headers"] == {"X-Requested-With": "XMLHttpRequest"}
    assert "Authorization" not in kwargs["headers"]
    assert kwargs["cookies"] == {"MyEonSession": "synthetic-cookie"}
    assert session._jar.updates


def test_web_ensure_token_refreshes_expired_session_without_revoke():
    import asyncio

    class Jar:
        def filter_cookies(self, url):
            return {}

        def update_cookies(self, cookies, response_url=None):
            return None

    class Response:
        def __init__(self, url):
            self.url = url
            self.status = 200
            self.cookies = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def json(self, **kwargs):
            if url := self.url:
                if url.endswith("/session?pagePath=%2Fcontent%2Feon-se%2Fsv_SE%2Fmitt-e-on"):
                    return {"currentToken": "synthetic-expired-token", "tokenExpiersIn": 0}
            return {
                "access_token": "synthetic-refreshed-token",
                "refresh_token": "synthetic-refresh",
                "expires_in": 180,
                "errorCode": 0,
            }

    class Session:
        def __init__(self):
            self.urls = []

        def get(self, url, **kwargs):
            self.urls.append(url)
            return Response(url)

    session = auth.EonSession.__new__(auth.EonSession)
    session._session = Session()
    session._jar = Jar()
    session._access_token = "synthetic-old-token"
    session._expires_at = 0.0
    token = asyncio.run(session._ensure_token())

    assert token == "synthetic-refreshed-token"
    assert session._session.urls[0].endswith("/session?pagePath=%2Fcontent%2Feon-se%2Fsv_SE%2Fmitt-e-on")
    assert session._session.urls[1].endswith("/refreshToken")
    assert not any("revokeToken" in url for url in session._session.urls)
