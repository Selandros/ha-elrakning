"""Small registry that keeps provider-specific adapters out of core code."""

from __future__ import annotations

from typing import Any, Mapping

from .models import ProviderData
from ..diagnostics import sanitize_source_data
from .providers.greenely_adapter import provider_data_from_greenely_state
from .providers.greenely_source import sanitize_greenely_source


PROVIDER_DATA_ADAPTERS = {
    "greenely": provider_data_from_greenely_state,
}

PROVIDER_SOURCE_SANITIZERS = {
    "greenely": sanitize_greenely_source,
}


def provider_data_from_state(provider: str | None, state: Mapping[str, Any]) -> ProviderData:
    """Convert a provider state through its registered adapter."""
    adapter = PROVIDER_DATA_ADAPTERS.get(provider)
    return adapter(state) if adapter else ProviderData(provider=provider)


def sanitize_provider_source(provider: str | None, source: Any) -> Any:
    sanitizer = PROVIDER_SOURCE_SANITIZERS.get(provider)
    sanitized = sanitizer(source) if sanitizer else source
    return sanitize_source_data(sanitized)
