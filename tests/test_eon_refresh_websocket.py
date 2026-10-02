import asyncio
import types
import unittest

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)


install_homeassistant_stubs()
install_elrakning_package_stub()
install_optional_dependency_stubs()

from custom_components.elrakning import websocket  # noqa: E402


class _Connection:
    def __init__(self, is_admin=True):
        self.user = types.SimpleNamespace(is_admin=is_admin)
        self.results = []

    def send_result(self, message_id, payload):
        self.results.append((message_id, payload))


class _Manager:
    definition = types.SimpleNamespace(provider_id="eon")

    def __init__(self, result=None, error=None):
        self.calls = 0
        self.provider = types.SimpleNamespace(state={"updated_at": "2026-10-02T10:00:00+00:00"})
        self.result = result or {"configured": True}
        self.error = error

    async def async_refresh(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class EonRefreshWebsocketTests(unittest.TestCase):
    def setUp(self):
        self.original_manager = websocket._grid_manager
        self.original_binding = websocket._site_binding_is_configured
        websocket._grid_manager = lambda _hass: self.manager
        websocket._site_binding_is_configured = lambda _hass, _service: True
        self.hass = types.SimpleNamespace(data={})

    def tearDown(self):
        websocket._grid_manager = self.original_manager
        websocket._site_binding_is_configured = self.original_binding

    def test_admin_calls_manager_once_and_returns_sanitized_timestamps(self):
        self.manager = _Manager()
        connection = _Connection()
        asyncio.run(websocket.websocket_eon_grid_refresh(self.hass, connection, {"id": 1}))

        self.assertEqual(self.manager.calls, 1)
        payload = connection.results[-1][1]
        self.assertEqual(payload["success"], True)
        self.assertEqual(payload["provider"], "eon")
        self.assertEqual(payload["updated_at"], "2026-10-02T10:00:00+00:00")
        self.assertIn("refreshed_at", payload)
        self.assertNotIn("state", payload)

    def test_non_admin_is_rejected_without_refresh(self):
        self.manager = _Manager()
        connection = _Connection(is_admin=False)
        asyncio.run(websocket.websocket_eon_grid_refresh(self.hass, connection, {"id": 2}))

        self.assertEqual(self.manager.calls, 0)
        self.assertEqual(connection.results[-1][1], {"success": False, "error": "admin_required"})

    def test_manager_error_is_stable_and_contains_no_exception_text(self):
        self.manager = _Manager(error=RuntimeError("secret-token-value"))
        connection = _Connection()
        asyncio.run(websocket.websocket_eon_grid_refresh(self.hass, connection, {"id": 3}))

        self.assertEqual(self.manager.calls, 1)
        self.assertEqual(connection.results[-1][1], {
            "success": False,
            "provider": "eon",
            "error": "refresh_failed",
        })

    def test_provider_error_result_is_fail_closed(self):
        self.manager = _Manager(result={"error": "reauth_required", "reauth_required": True})
        connection = _Connection()
        asyncio.run(websocket.websocket_eon_grid_refresh(self.hass, connection, {"id": 4}))

        self.assertEqual(connection.results[-1][1], {
            "success": False,
            "provider": "eon",
            "error": "reauth_required",
        })


if __name__ == "__main__":
    unittest.main()
