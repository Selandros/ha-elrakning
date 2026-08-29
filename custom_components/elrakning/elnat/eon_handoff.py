"""Authenticated one-time browser handoff endpoints for E.ON web sessions."""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from ..const import DOMAIN
from .manager import GridManager


def _grid_manager(request: web.Request) -> GridManager | None:
    manager = request.app["hass"].data.get(DOMAIN, {}).get("grid_manager")
    return manager if isinstance(manager, GridManager) else None


def _user_id(request: web.Request) -> str | None:
    user = request.get("hass_user")
    value = getattr(user, "id", None)
    return value if isinstance(value, str) and value else None


class EonHandoffPendingView(HomeAssistantView):
    """Return the one-time handoff state to the authenticated HA browser."""

    requires_auth = True
    url = "/api/elrakning/eon/handoff/pending"
    name = "api:elrakning:eon:handoff:pending"

    async def get(self, request: web.Request) -> web.Response:
        manager = _grid_manager(request)
        user_id = _user_id(request)
        pending = manager.pending_web_handoff(user_id) if manager and user_id else None
        if not pending:
            return web.json_response({"active": False}, status=404)
        return web.json_response({"active": True, **pending})


class EonHandoffCompleteView(HomeAssistantView):
    """Accept allowlisted cookies for one authenticated pending handoff."""

    requires_auth = True
    url = "/api/elrakning/eon/handoff/complete"
    name = "api:elrakning:eon:handoff:complete"

    async def post(self, request: web.Request) -> web.Response:
        manager = _grid_manager(request)
        user_id = _user_id(request)
        if not manager or not user_id:
            return web.json_response({"error": "handoff_unavailable"}, status=503)
        try:
            payload = await request.json()
            state = payload.get("state") if isinstance(payload, dict) else None
            cookies = payload.get("cookies") if isinstance(payload, dict) else None
            result = await manager.async_complete_web_handoff(user_id, state, cookies)
        except Exception as err:
            return web.json_response({"error": getattr(err, "code", "handoff_failed")}, status=400)
        return web.json_response({"success": True, **result})


def async_register_eon_handoff_views(hass) -> None:
    """Register the E.ON handoff endpoints once per Home Assistant instance."""
    key = f"{DOMAIN}_eon_handoff_registered"
    if hass.data.get(key):
        return
    hass.http.register_view(EonHandoffPendingView)
    hass.http.register_view(EonHandoffCompleteView)
    hass.data[key] = True
