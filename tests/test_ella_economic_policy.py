"""Tests for site-scoped planning applicability overrides."""

import asyncio
import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ella_economic_policy", ROOT / "custom_components/elrakning/ella_economic_policy.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeStore:
    def __init__(self):
        self.saved = []

    async def async_save(self, value):
        self.saved.append(value)

    async def async_load(self):
        return None


def _override(site="site-a", known="2026-09-26T12:00:00+00:00", effective="2026-09-26T12:00:00+00:00"):
    return {
        "site_id": site,
        "known_at": known,
        "effective_from": effective,
        "provider_valid_from": "2026-10-01T00:00:00+00:00",
        "provider_reference": "eon-agreement-fingerprint",
    }


def _store():
    store = MODULE.EllaEconomicPolicyStore(object())
    store.store = FakeStore()
    return store


def test_override_is_idempotent_site_scoped_and_preserves_provider_date():
    store = _store()
    assert asyncio.run(store.async_upsert(_override())) is True
    assert asyncio.run(store.async_upsert(_override())) is True
    resolved = store.resolve("site-a", "2026-09-26T13:00:00+00:00")
    assert resolved["source_type"] == MODULE.OVERRIDE_SOURCE
    assert resolved["provider_valid_from"] == "2026-10-01T00:00:00+00:00"
    assert store.resolve("site-b", "2026-09-26T13:00:00+00:00") is None


def test_override_is_not_visible_before_decision_or_effective_time():
    store = _store()
    asyncio.run(store.async_upsert(_override()))
    assert store.resolve("site-a", "2026-09-26T11:59:59+00:00") is None
    assert store.resolve("site-a", "2026-09-25T00:00:00+00:00") is None


def test_invalid_override_does_not_accept_provider_values():
    assert MODULE.normalize_override({"site_id": "site-a", "value": 0.2}) is None
