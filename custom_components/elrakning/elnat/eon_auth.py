"""Cookie-backed E.ON session authentication."""

from __future__ import annotations

import base64
import binascii
import json
import time
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from typing import Any, Mapping
from urllib.parse import urlencode

from aiohttp import ClientError, ClientResponse, CookieJar, ClientSession
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from yarl import URL

EON_WEB_BASE = "https://www.eon.se"
SESSION_PATH = "/bin/eon-se/codeflow/session"
REFRESH_PATH = "/bin/eon-se/codeflow/refreshToken"
ALLOWED_COOKIES = frozenset({
    "MyEonSession", "MyEonAccessToken", "MyEonAccessToken-ValidUntil",
    "MyEonAccessScopes", "MyEonIDToken", "MyEonResumeAt",
})


class EonAuthError(Exception):
    """Raised with a non-sensitive E.ON auth error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


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
