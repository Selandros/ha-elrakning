"""E.ON web-cookie and app authorization authentication."""

from __future__ import annotations

import base64
import binascii
import json
import secrets
import time
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from html.parser import HTMLParser
from typing import Any, Mapping
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from aiohttp import ClientError, ClientResponse, CookieJar, ClientSession
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from yarl import URL

EON_WEB_BASE = "https://www.eon.se"
SESSION_PATH = "/bin/eon-se/codeflow/session"
REFRESH_PATH = "/bin/eon-se/codeflow/refreshToken"
EON_APP_BASE = "https://api.apps.eon.se"
APP_AUTHORIZATION_PATH = "/neo/oauth/v2/authorization"
APP_AUTHENTICATOR_PATH = "/authn/authenticate/isu-sap-authenticator"
APP_TOKEN_URL = "https://eonappapimrun.azure-api.net/middlelayer/token"
APP_CLIENT_ID = "eon-app"
APP_CLIENT_SECRET = "n3Di9kVrFIcjc5f9toN8NcEZgqJhmH"
APP_REDIRECT_URI = "https://redirect"
APP_AUTH_SCHEME = "secret-sauce"
APP_ACR = "urn:se:curity:authentication:isu-sap-authenticator:isu-sap-authenticator"
APP_SCOPE = "100koll openid cjcv cjip cjmc cjpf cjero cjim serviceorder:read-restricted serviceorder:create-restricted serviceorder:delete-restricted stgo outage:read-restricted hancustchoice:read-restricted hancustchoice:update-restricted elnastatus:read-restricted elnastatus:update-restricted installation:read-restricted invoice:read-restricted"
ALLOWED_COOKIES = frozenset({
    "MyEonSession", "MyEonAccessToken", "MyEonAccessToken-ValidUntil",
    "MyEonAccessScopes", "MyEonIDToken", "MyEonResumeAt",
})


class EonAuthError(Exception):
    """Raised with a non-sensitive E.ON auth error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _HiddenInputParser(HTMLParser):
    """Extract only the verified authorization form fields."""

    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "input":
            return
        fields = dict(attrs)
        name = fields.get("name")
        value = fields.get("value")
        if name in {"token", "state"} and isinstance(value, str):
            self.values[name] = value


def parse_authenticator_form(html: str) -> dict[str, str]:
    """Parse only token and state from the verified authenticator form."""
    if not isinstance(html, str):
        raise EonAuthError("invalid_authenticator_response")
    parser = _HiddenInputParser()
    parser.feed(html)
    if set(parser.values) != {"token", "state"}:
        raise EonAuthError("invalid_authenticator_response")
    return parser.values


def extract_authorization_code(location: str, expected_state: str) -> str:
    """Validate the OAuth redirect state and return its authorization code."""
    try:
        query = parse_qs(urlparse(location).query, strict_parsing=True)
        code = query.get("code", [""])[0]
        state = query.get("state", [""])[0]
    except (TypeError, ValueError):
        code = state = ""
    if not code or state != expected_state:
        raise EonAuthError("oauth_state_mismatch" if state else "authorization_code_missing")
    return code


def parse_app_token_response(payload: Any) -> dict[str, Any]:
    """Validate app token metadata without exposing token values."""
    if not isinstance(payload, Mapping):
        raise EonAuthError("invalid_token_response")
    required = ("access_token", "refresh_token", "customer_id", "token_type", "expires_in")
    if any(not payload.get(key) for key in required):
        raise EonAuthError("invalid_token_response")
    if payload.get("token_type") != APP_AUTH_SCHEME or not isinstance(payload["customer_id"], str):
        raise EonAuthError("invalid_token_response")
    return {key: payload.get(key) for key in (*required, "scope")}


class EonAppSession:
    """Run the verified E.ON app login and keep tokens in memory only."""

    def __init__(self, hass) -> None:
        self._session: ClientSession = async_get_clientsession(hass)
        self._access_token: str | None = None
        self._expires_at = 0.0
        self.customer_id: str | None = None

    async def async_login(self, account_id: str, password: str) -> str:
        """Complete the verified authorization-code flow."""
        if not isinstance(account_id, str) or not account_id.strip() or not isinstance(password, str) or not password:
            raise EonAuthError("invalid_credentials")
        state = secrets.token_urlsafe(32)
        auth_url = f"{EON_APP_BASE}{APP_AUTHORIZATION_PATH}"
        params = {
            "client_id": APP_CLIENT_ID,
            "acr": APP_ACR,
            "response_type": "code",
            "redirect_uri": APP_REDIRECT_URI,
            "scope": APP_SCOPE,
            "state": state,
        }
        try:
            async with self._session.get(auth_url, params=params, allow_redirects=False) as response:
                location = response.headers.get("Location")
            if not location:
                raise EonAuthError("authorization_start_failed")
            authenticator_url = urljoin(auth_url, location)
            async with self._session.get(authenticator_url, allow_redirects=False) as response:
                await response.read()
            if response.status >= 400:
                raise EonAuthError("authenticator_failed")
            async with self._session.post(
                f"{EON_APP_BASE}{APP_AUTHENTICATOR_PATH}",
                data={"accountId": account_id.strip(), "password": password},
                allow_redirects=False,
            ) as response:
                form = parse_authenticator_form(await response.text())
            if response.status >= 400:
                raise EonAuthError("authenticator_failed")
            async with self._session.post(auth_url, data=form, allow_redirects=False) as response:
                redirect = response.headers.get("Location")
            if response.status != 303 or not redirect:
                raise EonAuthError("authorization_failed")
            code = extract_authorization_code(redirect, state)
            async with self._session.post(
                APP_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": APP_CLIENT_ID,
                    "client_secret": APP_CLIENT_SECRET,
                    "code": code,
                },
            ) as response:
                payload = await response.json(content_type=None)
        except EonAuthError:
            raise
        except (ClientError, TimeoutError, TypeError, ValueError) as err:
            raise EonAuthError("app_login_failed") from err
        if response.status >= 400:
            raise EonAuthError("app_login_failed")
        token = parse_app_token_response(payload)
        self._access_token = token["access_token"]
        self.customer_id = token["customer_id"]
        self._expires_at = time.monotonic() + float(token["expires_in"])
        return self.customer_id

    async def request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        """Call a middlelayer endpoint with the verified app auth scheme."""
        if not self._access_token or self._expires_at <= time.monotonic() + 30:
            raise EonAuthError("reauth_required")
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"{APP_AUTH_SCHEME} {self._access_token}"
        try:
            async with self._session.request(method, url, headers=headers, **kwargs) as response:
                if response.status in (401, 403):
                    raise EonAuthError("reauth_required")
                if response.status >= 400:
                    raise EonAuthError("api_error")
                return await response.json(content_type=None)
        except EonAuthError:
            raise
        except (ClientError, TimeoutError, TypeError, ValueError) as err:
            raise EonAuthError("app_api_failed") from err


def parse_cookie_header(value: str) -> dict[str, str]:
    """Keep only the explicitly supported E.ON cookies."""
    if not isinstance(value, str) or not value.strip():
        raise EonAuthError("invalid_cookie_header")
    parsed = SimpleCookie()
    try:
        parsed.load(value)
    except (TypeError, ValueError):
        raise EonAuthError("invalid_cookie_header") from None
    cookies = {key: morsel.value for key, morsel in parsed.items() if key in ALLOWED_COOKIES and morsel.value}
    if "MyEonIDToken" not in cookies:
        raise EonAuthError("customer_id_missing")
    return cookies


def customer_id_from_id_token(token: str) -> str:
    """Read only the verified CustID claim from the JWT payload."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
        customer_id = data.get("extra_claims_data", {}).get("CustID")
    except (IndexError, ValueError, TypeError, KeyError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
        customer_id = None
    if not isinstance(customer_id, str) or not customer_id:
        raise EonAuthError("customer_id_missing")
    return customer_id


class EonSession:
    """Maintain the minimum persistent E.ON cookie/session state."""

    def __init__(self, hass, cookies: Mapping[str, str] | None = None) -> None:
        self._session: ClientSession = async_get_clientsession(hass)
        self._jar = CookieJar()
        self._cookies = {key: value for key, value in (cookies or {}).items() if key in ALLOWED_COOKIES and isinstance(value, str) and value}
        self._jar.update_cookies(self._cookies, response_url=URL(EON_WEB_BASE))
        self._access_token: str | None = self._cookies.get("MyEonAccessToken")
        self._expires_at = 0.0

    @property
    def cookies(self) -> dict[str, str]:
        """Return only the allowed cookie values for persistence."""
        return {key: morsel.value for key, morsel in self._jar.filter_cookies(URL(EON_WEB_BASE)).items() if key in ALLOWED_COOKIES and morsel.value}

    async def bootstrap(self, cookie_header: str) -> str:
        cookies = parse_cookie_header(cookie_header)
        self._cookies = cookies
        self._jar.update_cookies(cookies, response_url=URL(EON_WEB_BASE))
        customer_id = customer_id_from_id_token(cookies["MyEonIDToken"])
        await self._session_info()
        return customer_id

    async def request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        token = await self._ensure_token()
        response = await self._request(method, url, token, **kwargs)
        if response.status == 401:
            response.release()
            await self.refresh()
            response = await self._request(method, url, self._access_token, **kwargs)
        if response.status in (401, 403):
            response.release()
            raise EonAuthError("reauth_required")
        if response.status >= 400:
            response.release()
            raise EonAuthError("api_error")
        try:
            return await response.json(content_type=None)
        except (TypeError, ValueError) as err:
            raise EonAuthError("invalid_response") from err

    async def refresh(self) -> None:
        try:
            async with self._session.get(EON_WEB_BASE + REFRESH_PATH, cookies=self.cookies) as response:
                self._apply_response_cookies(response)
                payload = await response.json(content_type=None)
        except (ClientError, TimeoutError, TypeError, ValueError) as err:
            raise EonAuthError("refresh_failed") from err
        if response.status != 200 or not isinstance(payload, Mapping) or payload.get("errorCode") != 0:
            raise EonAuthError("reauth_required")
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise EonAuthError("reauth_required")
        self._access_token = token
        self._jar.update_cookies({"MyEonAccessToken": token}, response_url=URL(EON_WEB_BASE))
        expires_in = payload.get("expires_in")
        self._expires_at = time.monotonic() + float(expires_in) if isinstance(expires_in, (int, float)) else 0.0

    async def _ensure_token(self) -> str:
        if self._access_token and self._expires_at > time.monotonic() + 30:
            return self._access_token
        await self._session_info()
        if not self._access_token:
            await self.refresh()
        return self._access_token or ""

    async def _session_info(self) -> None:
        query = urlencode({"pagePath": "/mitt-e-on"})
        try:
            async with self._session.get(f"{EON_WEB_BASE}{SESSION_PATH}?{query}", cookies=self.cookies) as response:
                self._apply_response_cookies(response)
                payload = await response.json(content_type=None)
        except (ClientError, TimeoutError, TypeError, ValueError) as err:
            raise EonAuthError("session_failed") from err
        if response.status != 200 or not isinstance(payload, Mapping):
            raise EonAuthError("reauth_required")
        token = payload.get("currentToken")
        if isinstance(token, str) and token:
            self._access_token = token
            self._expires_at = _expiry_from_session(payload)

    async def _request(self, method: str, url: str, token: str | None, **kwargs: Any) -> ClientResponse:
        headers = dict(kwargs.pop("headers", {}))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return await self._session.request(method, url, headers=headers, cookies=self.cookies, **kwargs)

    def _apply_response_cookies(self, response: ClientResponse) -> None:
        self._jar.update_cookies(response.cookies, response_url=response.url)


def _expiry_from_session(payload: Mapping[str, Any]) -> float:
    absolute = payload.get("currentAccessTokenExpiresAt")
    if isinstance(absolute, str):
        try:
            parsed = datetime.fromisoformat(absolute.replace("Z", "+00:00"))
            timestamp = (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()
            return time.monotonic() + max(0.0, timestamp - time.time())
        except ValueError:
            pass
    value = payload.get("tokenExpiersIn")
    if isinstance(value, (int, float)):
        return time.monotonic() + float(value)
    return time.monotonic() + 60
