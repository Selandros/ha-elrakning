"""One-time capability endpoint for E.ON browser handoff."""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from ..const import DOMAIN
from .eon_auth import EonAuthError
from .manager import GridManager


def _grid_manager(request: web.Request) -> GridManager | None:
    manager = request.app["hass"].data.get(DOMAIN, {}).get("grid_manager")
    return manager if isinstance(manager, GridManager) else None


class EonHandoffCompleteView(HomeAssistantView):
    """Accept one allowlisted cookie set using a short-lived capability."""

    requires_auth = False
    url = "/api/elrakning/eon/handoff/complete"
    name = "api:elrakning:eon:handoff:complete"

    async def post(self, request: web.Request) -> web.Response:
        manager = _grid_manager(request)
        if not manager:
            return web.json_response({"error": "handoff_unavailable"}, status=503)
        try:
            payload = await request.json()
            state = payload.get("state") if isinstance(payload, dict) else None
            cookies = payload.get("cookies") if isinstance(payload, dict) else None
            result = await manager.async_complete_web_handoff(state, cookies)
        except EonAuthError as err:
            return web.json_response({"success": False, "error": err.code}, status=400)
        except (TypeError, ValueError):
            return web.json_response({"success": False, "error": "handoff_rejected"}, status=400)
        return web.json_response({"success": True, **result})


def async_register_eon_handoff_views(hass) -> None:
    """Register the E.ON handoff endpoints once per Home Assistant instance."""
    key = f"{DOMAIN}_eon_handoff_registered"
    if hass.data.get(key):
        return
    hass.http.register_view(EonHandoffCompleteView)
    hass.data[key] = True
