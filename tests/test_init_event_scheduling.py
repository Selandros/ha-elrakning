import ast
import asyncio
from pathlib import Path


def _load_schedule_price_update():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_schedule_price_update"
    )
    module = ast.Module(body=[function], type_ignores=[])
    namespace = {"HomeAssistant": object}
    exec(compile(module, str(source_path), "exec"), namespace)
    return namespace["_schedule_price_update"]


class _Loop:
    def __init__(self):
        self.calls = []

    def call_soon_threadsafe(self, callback, *args):
        self.calls.append((callback, args))


class _Bus:
    def __init__(self):
        self.events = []

    def async_fire(self, event):
        self.events.append(event)


class _Hass:
    def __init__(self):
        self.loop = _Loop()
        self.bus = _Bus()


def test_price_update_is_scheduled_once_on_home_assistant_loop():
    schedule_price_update = _load_schedule_price_update()
    hass = _Hass()

    schedule_price_update(hass)

    assert len(hass.loop.calls) == 1
    callback, args = hass.loop.calls[0]
    assert callback.__self__ is hass.bus
    assert callback.__func__ is _Bus.async_fire
    assert args == ("elrakning_price_update",)
    assert hass.bus.events == []

    callback(*args)
    assert hass.bus.events == ["elrakning_price_update"]


def _load_midnight_refresh():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_async_midnight_refresh"
    )
    module = ast.Module(body=[function], type_ignores=[])
    namespace = {"ElrakningCoordinator": object}
    exec(compile(module, str(source_path), "exec"), namespace)
    return namespace["_async_midnight_refresh"]


class _Coordinator:
    def __init__(self):
        self.refresh_calls = 0

    async def async_request_refresh(self):
        self.refresh_calls += 1


def test_midnight_callback_requests_one_coordinator_refresh():
    callback = _load_midnight_refresh()
    coordinator = _Coordinator()

    asyncio.run(callback(coordinator, object()))

    assert coordinator.refresh_calls == 1


def test_midnight_schedule_and_lifecycle_contract_are_present():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")

    assert "async_track_time_change(" in source
    assert "hour=0" in source
    assert "minute=0" in source
    assert "second=0" in source
    assert 'frontend_data["midnight_refresh_unsub"]' in source
    assert 'frontend_data.pop("midnight_refresh_unsub", None)' in source
    assert "async_request_refresh" in source
    assert "set_interval" not in source


def test_coordinator_interval_remains_fifteen_minutes():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "coordinator.py"
    source = source_path.read_text(encoding="utf-8")

    assert "update_interval=timedelta(minutes=15)" in source


def test_integration_ready_event_is_fired_after_runtime_components_are_ready():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    assert 'INTEGRATION_READY_EVENT = "elrakning_integration_ready"' in source_path.parents[0].joinpath("const.py").read_text(encoding="utf-8")
    assert "await coordinator.async_config_entry_first_refresh()" in source
    assert "await manager.async_load()" in source
    assert "await meter_manager.async_load()" in source
    assert "await power_manager.async_load()" in source
    assert "async_register_websocket_commands(hass)" in source
    assert "hass.bus.async_fire(INTEGRATION_READY_EVENT)" in source
    assert source.index("async_register_websocket_commands(hass)") < source.index("hass.bus.async_fire(INTEGRATION_READY_EVENT)")
