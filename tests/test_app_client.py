import asyncio
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub


install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.app_client import AppShadowClient


class _HealthResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def json(self, **_kwargs):
        return self.payload


class _HealthSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _HealthResponse(next(self.responses))


class TestAppShadowHealth(unittest.IsolatedAsyncioTestCase):
    async def test_health_uses_live_and_ready_contract_responses(self):
        import custom_components.elrakning.app_client as module

        session = _HealthSession([
            {"live": True, "contract_version": 1},
            {
                "ready": True,
                "shadow_mode": True,
                "writes_enabled": False,
                "physical_control": False,
                "contract_version": 1,
            },
        ])
        client = AppShadowClient(
            object(), base_url="http://app.invalid:8099", token="secret", enabled=True
        )

        with patch.object(module, "async_get_clientsession", return_value=session):
            result = await client.async_health()

        self.assertIs(result["available"], True)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(
            [call[0] for call in session.calls],
            [
                "http://app.invalid:8099/v1/health/live",
                "http://app.invalid:8099/v1/health/ready",
            ],
        )
        self.assertTrue(
            all(
                call[1]["headers"]["Authorization"] == "Bearer secret"
                for call in session.calls
            )
        )

    async def test_health_fails_closed_on_live_contract_mismatch(self):
        import custom_components.elrakning.app_client as module

        session = _HealthSession([{"live": True, "contract_version": 99}])
        client = AppShadowClient(
            object(), base_url="http://app.invalid:8099", token="secret", enabled=True
        )

        with patch.object(module, "async_get_clientsession", return_value=session):
            result = await client.async_health()

        self.assertIs(result["available"], False)
        self.assertEqual(result["reason"], "unsupported_contract_version")
        self.assertEqual(len(session.calls), 1)


def test_shadow_client_is_disabled_without_explicit_enablement():
    async def run():
        entry = type("Entry", (), {"options": {}})()
        client = AppShadowClient.from_config_entry(object(), entry)
        result = await client.async_health()
        assert result["available"] is False
        assert result["live"]["reason"] == "shadow_disabled"
        assert result["ready"]["reason"] == "shadow_disabled"

    asyncio.run(run())


def test_shadow_client_reads_only_explicit_config_entry_options():
    apps = SimpleNamespace(
        get_apps_list=lambda _hass: [{"slug": "092cd02c_elrakning_app"}]
    )

    async def run():
        entry = type("Entry", (), {
            "options": {
                "app_shadow_enabled": True,
                "app_shadow_url": "http://elrakning-app:8099",
                "app_shadow_token": "configured-token",
            },
        })()
        client = AppShadowClient.from_config_entry(object(), entry)
        assert client.enabled is True
        assert client.base_url == "http://092cd02c-elrakning-app:8099"
        assert client.token == "configured-token"
        assert client.configured_host == "elrakning-app"
        assert client.effective_host == "092cd02c-elrakning-app"
        assert client.resolution_source == "supervisor_discovery"
        diagnostics = (client.configured_host, client.effective_host, client.resolution_source)
        assert "configured-token" not in repr(diagnostics)

    previous = sys.modules.get("homeassistant.components.hassio")
    sys.modules["homeassistant.components.hassio"] = apps
    try:
        asyncio.run(run())
    finally:
        if previous is None:
            sys.modules.pop("homeassistant.components.hassio", None)
        else:
            sys.modules["homeassistant.components.hassio"] = previous


def test_shadow_client_discovers_default_url_from_cached_supervisor_apps(monkeypatch):
    import custom_components.elrakning.app_client as module

    monkeypatch.setattr(
        module,
        "_discover_app_url",
        lambda _hass: "http://092cd02c-elrakning-app:8099",
    )
    entry = type("Entry", (), {
        "options": {
            "app_shadow_enabled": True,
            "app_shadow_url": "",
            "app_shadow_token": "configured-token",
        },
    })()
    client = AppShadowClient.from_config_entry(object(), entry)
    assert client.base_url == "http://092cd02c-elrakning-app:8099"
    assert client.resolution_source == "supervisor_discovery"


def test_shadow_client_fails_closed_when_auto_discovery_is_ambiguous(monkeypatch):
    import custom_components.elrakning.app_client as module

    monkeypatch.setattr(module, "_discover_app_url", lambda _hass: "")
    entry = type("Entry", (), {
        "options": {
            "app_shadow_enabled": True,
            "app_shadow_url": "",
            "app_shadow_token": "configured-token",
        },
    })()
    client = AppShadowClient.from_config_entry(object(), entry)
    assert client.enabled is False
    assert client.base_url == ""


def test_shadow_client_rejects_unsafe_url_without_network_access():
    entry = type("Entry", (), {
        "options": {
            "app_shadow_enabled": True,
            "app_shadow_url": "https://user:secret@example.invalid",
            "app_shadow_token": "configured-token",
        },
    })()
    client = AppShadowClient.from_config_entry(object(), entry)
    assert client.enabled is False
    assert client.base_url == ""

def test_shadow_client_fails_closed_when_app_is_unavailable(monkeypatch):
    class UnavailableSession:
        def get(self, *_args, **_kwargs):
            raise asyncio.TimeoutError

    import custom_components.elrakning.app_client as module

    monkeypatch.setattr(module, "async_get_clientsession", lambda _hass: UnavailableSession())

    async def run():
        client = AppShadowClient(object(), base_url="http://app.invalid", token="token", enabled=True)
        result = await client.async_health()
        assert result == {"available": False, "reason": "app_unavailable"}

    asyncio.run(run())
