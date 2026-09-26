"""Persisted site policy for applying an existing provider agreement to planning."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

try:
    from homeassistant.helpers.storage import Store
except ModuleNotFoundError:  # pragma: no cover - lightweight contract tests
    class Store:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass


SCHEMA = "ella_economic_policy.v1"
STORE_KEY = "elrakning.ella_economic_policy"
STORE_VERSION = 1
OVERRIDE_SOURCE = "user_configured_planning_applicability_override"


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat() if value.tzinfo else None
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else None
    return None


def normalize_override(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    site_id = value.get("site_id")
    known_at = _iso(value.get("known_at"))
    effective_from = _iso(value.get("effective_from"))
    provider_valid_from = _iso(value.get("provider_valid_from"))
    reference = value.get("provider_reference")
    if (
        not isinstance(site_id, str) or not site_id.strip()
        or not known_at or not effective_from or not provider_valid_from
        or not isinstance(reference, str) or not reference.strip()
    ):
        return None
    return {
        "site_id": site_id,
        "known_at": known_at,
        "effective_from": effective_from,
        "provider_valid_from": provider_valid_from,
        "provider_reference": reference,
        "source_type": OVERRIDE_SOURCE,
        "provider_metadata_preserved": True,
    }


class EllaEconomicPolicyStore:
    """Store only applicability metadata; provider tariff values remain external."""

    def __init__(self, hass: Any) -> None:
        self.store = Store(hass, STORE_VERSION, STORE_KEY)
        self.state: dict[str, Any] = {"schema": SCHEMA, "version": 1, "sites": {}}

    async def async_load(self) -> None:
        cached = await self.store.async_load()
        if isinstance(cached, dict) and cached.get("schema") == SCHEMA and isinstance(cached.get("sites"), dict):
            self.state = {"schema": SCHEMA, "version": 1, "sites": cached["sites"]}

    async def async_upsert(self, override: Any) -> bool:
        normalized = normalize_override(override)
        if normalized is None:
            return False
        site = self.state.setdefault("sites", {}).setdefault(normalized["site_id"], {})
        if site.get("planning_applicability_override") == normalized:
            return True
        site["planning_applicability_override"] = normalized
        await self.store.async_save(self.state)
        return True

    def resolve(self, site_id: str, decision_at: Any) -> dict[str, Any] | None:
        override = self.state.get("sites", {}).get(site_id, {}).get("planning_applicability_override")
        if not isinstance(override, dict):
            return None
        decision = _iso(decision_at)
        if decision is None or override.get("known_at", "") > decision or override.get("effective_from", "") > decision:
            return None
        return deepcopy(override)
