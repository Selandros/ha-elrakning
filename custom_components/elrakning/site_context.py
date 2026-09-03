"""Small helpers for migrating legacy stores into immutable site namespaces."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from homeassistant.helpers.storage import Store


async def async_load_site_store(
    hass: Any,
    store_key: str,
    version: int,
    site_id: str,
    legacy_data: dict[str, Any] | None = None,
) -> tuple[Store, dict[str, Any] | None]:
    """Load one site store, migrating legacy data only for the existing site."""
    store = Store(hass, version, f"{store_key}.{site_id}")
    cached = await store.async_load()
    if cached is None and isinstance(legacy_data, dict):
        cached = deepcopy(legacy_data)
        await store.async_save(cached)
    return store, cached if isinstance(cached, dict) else None
