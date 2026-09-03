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
