"""Optional, bounded client for the local Elräkning shadow App."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .app_contract import CONTRACT_VERSION, AppContractError, validate_state_snapshot
from .const import APP_SHADOW_ENABLED, APP_SHADOW_TOKEN, APP_SHADOW_URL


DEFAULT_APP_URL = ""
_APP_PORT = 8099
_AUTO_DISCOVERY_HOST = "elrakning-app"
_APP_SLUG_SUFFIX = "_elrakning_app"
_REQUEST_TIMEOUT_SECONDS = 1.0


def _discover_app_url(hass: Any) -> str:
    """Resolve the installed App from Home Assistant's cached Supervisor data."""
    try:
        from homeassistant.components.hassio import get_apps_list

        apps = get_apps_list(hass)
    except Exception:
        return ""

    slugs = {
        app.get("slug")
        for app in apps
        if isinstance(app, dict)
        and isinstance(app.get("slug"), str)
        and app["slug"].endswith(_APP_SLUG_SUFFIX)
    }
    if len(slugs) != 1:
        return ""
    hostname = next(iter(slugs)).replace("_", "-")
    return f"http://{hostname}:{_APP_PORT}"


def _resolve_app_url(hass: Any, configured_url: Any) -> str:
    """Resolve the default/legacy alias without hardcoding a repository id."""
    return _resolve_app_url_details(hass, configured_url)[0]


def _resolve_app_url_details(hass: Any, configured_url: Any) -> tuple[str, str, str]:
    """Return the effective URL and non-secret resolution metadata."""
    raw_url = configured_url.strip() if isinstance(configured_url, str) else ""
    configured_host = (urlsplit(raw_url).hostname or "") if raw_url else ""
    if not raw_url:
        discovered_url = _discover_app_url(hass)
        source = "supervisor_discovery" if discovered_url else "unavailable"
        return discovered_url, configured_host, source
    if configured_host == _AUTO_DISCOVERY_HOST:
        discovered_url = _discover_app_url(hass)
        if discovered_url:
            return discovered_url, configured_host, "supervisor_discovery"
        return raw_url, configured_host, "legacy_alias_fallback"
    return raw_url, configured_host, "configured"


class AppShadowClient:
    """Use the App only when explicitly enabled; never block HA setup."""

    def __init__(
        self,
        hass: Any,
        *,
        base_url: str,
        token: str,
        enabled: bool,
        configured_host: str = "",
        resolution_source: str = "configured",
    ) -> None:
        self.hass = hass
        parsed_url = urlsplit(base_url) if isinstance(base_url, str) else None
        self.base_url = (
            base_url.rstrip("/")
            if parsed_url and parsed_url.scheme in {"http", "https"}
            and parsed_url.hostname and not parsed_url.username and not parsed_url.password
            else ""
        )
        self.token = token if isinstance(token, str) else ""
        self.enabled = enabled is True and bool(self.base_url) and bool(self.token)
        self.configured_host = configured_host
        self.effective_host = urlsplit(self.base_url).hostname if self.base_url else None
        self.resolution_source = resolution_source

    @classmethod
    def from_config_entry(cls, hass: Any, entry: Any) -> "AppShadowClient":
        options = getattr(entry, "options", {}) or {}
        configured_url = options.get(APP_SHADOW_URL, DEFAULT_APP_URL)
        base_url, configured_host, resolution_source = _resolve_app_url_details(
            hass, configured_url
        )
        return cls(
            hass,
            base_url=base_url,
            token=options.get(APP_SHADOW_TOKEN, ""),
            enabled=options.get(APP_SHADOW_ENABLED, False) is True,
            configured_host=configured_host,
            resolution_source=resolution_source,
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.enabled:
            return {"available": False, "reason": "shadow_disabled"}
        session = async_get_clientsession(self.hass)
        if session is None:
            return {"available": False, "reason": "http_session_unavailable"}
        try:
            request = getattr(session, method.lower())
            async with request(
                f"{self.base_url}{path}",
                headers=self._headers(),
                timeout=_REQUEST_TIMEOUT_SECONDS,
                **kwargs,
            ) as response:
                body = await response.json(content_type=None)
                if response.status >= 400:
                    return {"available": False, "reason": "app_http_error", "status": response.status}
                return body if isinstance(body, dict) else {"available": False, "reason": "malformed_app_response"}
        except (asyncio.TimeoutError, OSError, AppContractError):
            return {"available": False, "reason": "app_unavailable"}
        except Exception:
            return {"available": False, "reason": "app_unavailable"}

    async def async_health(self) -> dict[str, Any]:
        """Check liveness and readiness with bounded, explicit requests."""
        live = await self._request("get", "/v1/health/live")
        if live.get("reason") == "shadow_disabled":
            ready = await self._request("get", "/v1/health/ready")
            return {"available": False, "live": live, "ready": ready}
        if live.get("live") is not True:
            if live.get("reason"):
                return live
            return {"available": False, "reason": "app_live_check_failed", "live": live}
        if live.get("contract_version") != CONTRACT_VERSION:
            return {"available": False, "reason": "unsupported_contract_version", "live": live}
        ready = await self._request("get", "/v1/health/ready")
        available = (
            ready.get("ready") is True
            and ready.get("contract_version") == CONTRACT_VERSION
        )
        return {"available": available, "live": live, "ready": ready}

    async def async_submit_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Submit one validated read-only snapshot; never wait for computation."""
        try:
            validated = validate_state_snapshot(snapshot)
        except AppContractError as error:
            return {"accepted": False, "reason": str(error)}
        return await self._request("post", "/v1/snapshots", json=validated)
