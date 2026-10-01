import asyncio
import types
import unittest

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)


install_elrakning_package_stub()
install_homeassistant_stubs()
install_optional_dependency_stubs()

from custom_components.elrakning.elnat import manager as manager_module  # noqa: E402
from custom_components.elrakning.const import DOMAIN  # noqa: E402
from custom_components.elrakning.elnat.eon_manager import EonGridManager  # noqa: E402


class _Provider:
    configured = True

    def __init__(self):
        self.state = {}
        self.cancelled = 0

    def _cancel_web_refresh(self):
        self.cancelled += 1

    def _empty_state(self):
        return {"configured": False}


class GridManagerLifecycleTests(unittest.TestCase):
    def _manager(self):
        provider = _Provider()
        definition = types.SimpleNamespace(manager_factory=lambda hass, entry: provider)
        original = manager_module.configured_grid_provider
        manager_module.configured_grid_provider = lambda entry: definition
        try:
            manager = manager_module.GridManager(types.SimpleNamespace(), types.SimpleNamespace(data={}))
        finally:
            manager_module.configured_grid_provider = original
        return manager, provider

    def test_site_binding_is_safe_before_refresh_subscription_exists(self):
        manager, provider = self._manager()
        asyncio.run(manager.async_apply_site_binding({"provider": "eon"}))

        self.assertIsNone(manager._refresh_unsub)
        self.assertEqual(manager._site_binding, {"provider": "eon"})
        self.assertEqual(provider.cancelled, 1)

    def test_unconfigured_binding_clears_provider_state_without_refresh_callback(self):
        manager, provider = self._manager()
        asyncio.run(manager.async_apply_site_binding(None))

        self.assertIsNone(manager._refresh_unsub)
        self.assertIsNone(manager._site_binding)
        self.assertEqual(provider.state, {"configured": False})

    def test_unconfigured_provider_preserves_historical_tariff_timeline(self):
        hass = types.SimpleNamespace(data={DOMAIN: {}})
        manager = EonGridManager(hass, types.SimpleNamespace(data={}))
        historical = {
            "site_id": "site-a",
            "source_generation_id": "manual-september",
            "known_at": "2026-09-27T22:21:31+00:00",
            "valid_from": "2026-08-31T22:00:00+00:00",
            "valid_to": "2026-09-30T22:00:00+00:00",
            "grid_price": {"variable_total_ore_per_kwh_gross": 142.0},
        }

        manager.store = types.SimpleNamespace(async_load=lambda: _async_value({"configured": True}))
        manager.tariff_timeline_store = types.SimpleNamespace(
            async_load=lambda: _async_value({"records": [historical]})
        )
        manager._async_capture_tariff_fact = lambda: _async_value(None)
        asyncio.run(manager.async_load())

        self.assertEqual(manager.tariff_timeline, [historical])


async def _async_value(value):
    return value
