"""Provider registry for the provider-neutral grid layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..const import EON_GRID_CONFIG_KEY, GRID_CONFIG_KEY
from .eon_manager import EonGridManager


@dataclass(frozen=True)
class GridProviderDefinition:
    """Describe a grid provider without exposing provider implementation details."""

    provider_id: str
    name: str
    auth_methods: tuple[str, ...]
    manager_factory: Callable[[Any, Any], Any]


GRID_PROVIDER_REGISTRY = {
    "eon": GridProviderDefinition(
        provider_id="eon",
        name="E.ON",
        auth_methods=("app",),
        manager_factory=EonGridManager,
    ),
}


def get_grid_provider(provider_id: str | None) -> GridProviderDefinition | None:
    """Return a registered provider definition."""
    return GRID_PROVIDER_REGISTRY.get(provider_id)


def configured_grid_provider(entry: Any) -> GridProviderDefinition | None:
    """Resolve the provider from the new or legacy entry representation."""
    config = entry.data.get(GRID_CONFIG_KEY)
    if not isinstance(config, dict):
        config = entry.data.get(EON_GRID_CONFIG_KEY)
    provider_id = config.get("provider") if isinstance(config, dict) else None
    if provider_id is None and isinstance(config, dict) and config:
        provider_id = "eon"
    if provider_id is None and len(GRID_PROVIDER_REGISTRY) == 1:
        provider_id = next(iter(GRID_PROVIDER_REGISTRY))
    return get_grid_provider(provider_id)
