"""Provider-neutral grid manager facade."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..const import EON_GRID_CONFIG_KEY, GRID_CONFIG_KEY
from .provider_registry import configured_grid_provider, get_grid_provider


class GridManager:
    """Dispatch grid lifecycle and actions to the configured provider."""

    def __init__(self, hass, entry) -> None:
        self.hass = hass
        self.entry = entry
        definition = configured_grid_provider(entry)
        self.definition = definition
        self.provider = definition.manager_factory(hass, entry) if definition else None
        self._site_binding: dict[str, Any] | None = None

    @property
    def configured(self) -> bool:
        return bool(self.provider and self.provider.configured)

    async def async_load(self) -> None:
        self._migrate_legacy_config()
        if self.provider:
            await self.provider.async_load()

    def _migrate_legacy_config(self) -> None:
        """Move the legacy E.ON entry into the generic provider envelope."""
        if isinstance(self.entry.data.get(GRID_CONFIG_KEY), dict):
            return
        legacy = self.entry.data.get(EON_GRID_CONFIG_KEY)
        if not isinstance(legacy, dict):
            return
        data = dict(self.entry.data)
        data[GRID_CONFIG_KEY] = {
            "provider": "eon",
            "auth_method": "app" if legacy.get("auth") == "app" else "web",
            "provider_config": dict(legacy),
        }
        data.pop(EON_GRID_CONFIG_KEY, None)
        self.hass.config_entries.async_update_entry(self.entry, data=data)

    def async_start_refresh(self) -> None:
        if self.provider and self._site_binding:
            self.provider.async_start_refresh()

    async def async_apply_site_binding(
        self, binding: dict[str, Any] | None, state: dict[str, Any] | None = None
    ) -> None:
        """Apply explicit site context without duplicating shared credentials."""
        self._site_binding = dict(binding) if isinstance(binding, dict) else None
        if not self.provider:
            return
        if self._refresh_unsub:
            self._refresh_unsub()
            self._refresh_unsub = None
        self.provider._cancel_web_refresh()
        if not self._site_binding:
            self.provider.state = self.provider._empty_state()
            return
        self.provider.state = deepcopy(state) if isinstance(state, dict) else self.provider._empty_state()

    async def async_refresh(self) -> dict[str, Any]:
        return await self.provider.async_refresh() if self.provider else {"configured": False}

    async def async_save_app_credentials(self, account_id: str, password: str) -> dict[str, Any]:
        return await self.provider.async_save_app_credentials(account_id, password)

    async def async_save_web_credentials(self, account_id: str, password: str) -> dict[str, Any]:
        return await self.provider.async_save_web_credentials(account_id, password)

    async def async_login(self, provider_id: str, auth_method: str, account_id: str, password: str) -> dict[str, Any]:
        """Dispatch login to the selected provider and auth method."""
        definition = get_grid_provider(provider_id)
        if not definition or not self.provider or definition is not self.definition:
            return {"status": "unsupported_provider", "error": "unsupported_provider"}
        return await self.provider.async_login(auth_method, account_id, password)

    async def async_save_cookie_header(self, cookie_header: str) -> dict[str, Any]:
        return await self.provider.async_save_cookie_header(cookie_header)

    async def async_start_web_handoff(self, user_id: str) -> dict[str, Any]:
        if not self.provider or not hasattr(self.provider, "async_start_web_handoff"):
            return {"status": "unsupported"}
        return await self.provider.async_start_web_handoff(user_id)

    async def async_complete_web_handoff(
        self, state: str, cookies: dict[str, str]
    ) -> dict[str, Any]:
        if not self.provider or not hasattr(self.provider, "async_complete_web_handoff"):
            return {"status": "unsupported"}
        return await self.provider.async_complete_web_handoff(state, cookies)

    async def async_source_data(self) -> dict[str, Any]:
        return await self.provider.async_source_data()

    async def async_remove(self) -> dict[str, Any]:
        return await self.provider.async_remove()

    async def async_shutdown(self) -> None:
        if self.provider:
            await self.provider.async_shutdown()

    def public_state(self) -> dict[str, Any]:
        return self.provider.public_state() if self.provider else {
            "configured": False,
            "provider": None,
            "provider_name": None,
            "auth_method": None,
        }
