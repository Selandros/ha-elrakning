import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub


install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.app_shadow import (  # noqa: E402
    AppShadowManager,
    build_snapshot_from_canonical_frame,
)


class _Bus:
    def __init__(self):
        self.listeners = {}

    def async_listen(self, event_type, callback):
        self.listeners.setdefault(event_type, []).append(callback)

        def unsubscribe():
            self.listeners[event_type].remove(callback)

        return unsubscribe


class _Hass:
    def __init__(self):
        self.bus = _Bus()
        self.tasks = []

    async def async_add_executor_job(self, function, *args):
        return function(*args)

    def async_create_background_task(self, coroutine, *, name):
        task = asyncio.create_task(coroutine, name=name)
        self.tasks.append(task)
        return task


class _Client:
    def __init__(self, *, enabled=True, ready=True):
        self.enabled = enabled
        self.ready = ready
        self.health_calls = 0
        self.snapshots = []
        self.token = "never-expose-this"
        self.configured_host = "elrakning-app"
        self.effective_host = "092cd02c-elrakning-app"
        self.resolution_source = "supervisor_discovery"

    async def async_health(self):
        self.health_calls += 1
        if not self.ready:
            return {"available": False, "reason": "app_unavailable"}
        return {"available": True, "ready": {"ready": True}}

    async def async_submit_snapshot(self, snapshot):
        self.snapshots.append(snapshot)
        return {"accepted": True}


class _Identity:
    def __init__(self, configs):
        self.configs = configs

    def collection_site_configs(self):
        return self.configs


class _Storage:
    def __init__(self, frames):
        self.frames = frames

    def read_external_input_frames(self, *_args, **_kwargs):
        return self.frames


def _frame(*, with_observed=True, with_sign=True):
    provenance = {
        "source_identity_key": "source-key",
        "origin_type": "test-frame",
        "provider": "test",
    }
    if with_observed:
        provenance["observed_at"] = "2026-10-10T09:59:00+00:00"
    point_context = {}
    if with_sign:
        point_context["sign_convention"] = "positive_import"
    return {
        "frame_id": "frame-a",
        "revision": 1,
        "semantic_key": "test|site-a|frame-a",
        "source_generation_id": "generation-a",
        "site_id": "site-a",
        "captured_at": datetime(2026, 10, 10, 10, 1, tzinfo=timezone.utc),
        "known_at": datetime(2026, 10, 10, 10, 0, 30, tzinfo=timezone.utc),
        "quality": {"status": "good"},
        "provenance": provenance,
        "payload_schema": "test.frame.v1",
        "points": [{
            "point_id": "point-a",
            "valid_at": datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc),
            "value": 1.25,
            "unit": "kW",
            "quality_status": "good",
            "point": point_context,
        }],
    }


def test_frame_adapter_is_fail_closed_without_observed_or_sign_semantics():
    assert build_snapshot_from_canonical_frame(_frame(), _frame()["points"][0])
    assert build_snapshot_from_canonical_frame(
        _frame(with_observed=False), _frame(with_observed=False)["points"][0]
    ) is None
    assert build_snapshot_from_canonical_frame(
        _frame(with_sign=False), _frame(with_sign=False)["points"][0]
    ) is None


def test_disabled_shadow_has_no_health_or_event_transport():
    async def run():
        hass = _Hass()
        client = _Client(enabled=False)
        manager = AppShadowManager(
            hass, client, _Identity({"site-a": {}}),
            SimpleNamespace(storage=_Storage([_frame()])),
        )
        await manager.async_start()
        assert client.health_calls == 0
        assert not hass.bus.listeners

    asyncio.run(run())


def test_empty_clean_room_sends_no_snapshot():
    async def run():
        hass = _Hass()
        client = _Client()
        manager = AppShadowManager(
            hass, client, _Identity({}), SimpleNamespace(storage=_Storage([_frame()]))
        )
        await manager.async_start()
        callback = hass.bus.listeners["elrakning_electricity_provider_update"][0]
        await callback(SimpleNamespace(data={}))
        await asyncio.sleep(0)
        assert client.snapshots == []

    asyncio.run(run())


def test_valid_canonical_frame_is_submitted_once_per_site_event_burst():
    async def run():
        hass = _Hass()
        client = _Client()
        manager = AppShadowManager(
            hass, client, _Identity({"site-a": {}}),
            SimpleNamespace(storage=_Storage([_frame()])),
        )
        await manager.async_start()
        callback = hass.bus.listeners["elrakning_load_forecast_update"][0]
        event = SimpleNamespace(data={"site_id": "site-a"})
        await callback(event)
        await callback(event)
        await asyncio.sleep(0)
        await asyncio.gather(*hass.tasks)
        assert len(client.snapshots) == 1
        assert client.snapshots[0]["site_id"] == "site-a"
        assert client.snapshots[0]["contract_version"] == 1
        assert client.snapshots[0]["known_at"] <= client.snapshots[0]["decision_context"]["decision_at"]

    asyncio.run(run())


def test_health_failure_is_fail_closed_and_unload_cleans_listeners():
    async def run():
        hass = _Hass()
        client = _Client(ready=False)
        manager = AppShadowManager(
            hass, client, _Identity({"site-a": {}}),
            SimpleNamespace(storage=_Storage([_frame()])),
        )
        await manager.async_start()
        callback = hass.bus.listeners["elrakning_eon_grid_update"][0]
        await callback(SimpleNamespace(data={"site_id": "site-a"}))
        assert client.snapshots == []
        public_state = manager.public_state()
        assert public_state["configured_host"] == "elrakning-app"
        assert public_state["effective_host"] == "092cd02c-elrakning-app"
        assert public_state["resolution_source"] == "supervisor_discovery"
        assert "never-expose-this" not in str(public_state)
        await manager.async_shutdown()
        assert all(not callbacks for callbacks in hass.bus.listeners.values())
        assert "token" not in str(manager.public_state()).lower()

    asyncio.run(run())
