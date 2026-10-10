import asyncio
import sys
from types import SimpleNamespace

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub


install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.app_client import AppShadowClient


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
