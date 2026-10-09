"""Optional, bounded client for the local Elräkning shadow App."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .app_contract import AppContractError, validate_state_snapshot


DEFAULT_APP_URL = "http://elrakning-app:8099"
_REQUEST_TIMEOUT_SECONDS = 1.0


class AppShadowClient:
    """Use the App only when explicitly enabled; never block HA setup."""

    def __init__(self, hass: Any, *, base_url: str, token: str, enabled: bool) -> None:
        self.hass = hass
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.enabled = enabled and bool(self.base_url) and bool(self.token)

    @classmethod
    def from_environment(cls, hass: Any) -> "AppShadowClient":
        enabled = os.getenv("ELRAKNING_APP_SHADOW", "0").lower() in {"1", "true", "yes"}
        return cls(
            hass,
            base_url=os.getenv("ELRAKNING_APP_URL", DEFAULT_APP_URL),
            token=os.getenv("ELRAKNING_APP_TOKEN", ""),
            enabled=enabled,
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
        if not live.get("available", False) and live.get("reason") != "shadow_disabled":
            return live
        ready = await self._request("get", "/v1/health/ready")
        return {"available": bool(ready.get("ready")), "live": live, "ready": ready}

    async def async_submit_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Submit one validated read-only snapshot; never wait for computation."""
        try:
            validated = validate_state_snapshot(snapshot)
        except AppContractError as error:
            return {"accepted": False, "reason": str(error)}
        return await self._request("post", "/v1/snapshots", json=validated)
