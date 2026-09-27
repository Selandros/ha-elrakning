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


def test_load_forecast_cadence_uses_thread_safe_create_task_from_worker_thread():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    start = source.index("def _schedule_load_forecast_capture(")
    end = source.index("\n\nasync def _async_register_frontend", start)
    namespace = {}
    exec(compile(source[start:end], str(source_path), "exec"), namespace)

    async def capture(*_args):
        return None

    class ThreadSafeHass:
        def __init__(self):
            self.loop = asyncio.get_running_loop()
            self.async_create_task_called = False

        def async_create_task(self, _coroutine):
            self.async_create_task_called = True
            raise AssertionError("worker callback used async_create_task")

        def create_task(self, coroutine):
            return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    async def exercise():
        hass = ThreadSafeHass()
        namespace["_async_capture_load_forecasts"] = capture
        task = await asyncio.to_thread(
            namespace["_schedule_load_forecast_capture"], hass, object(), object()
        )
        await asyncio.wrap_future(task)
        assert hass.async_create_task_called is False

    asyncio.run(exercise())


def test_load_forecast_capture_uses_site_scoped_house_role_without_ella_binding():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_async_capture_load_forecasts")
    calls = []
    namespace = {
        "timezone": __import__("datetime").timezone,
        "dt_util": type("Dt", (), {"now": staticmethod(lambda: __import__("datetime").datetime(2026, 9, 20))}),
        "build_site_load_forecast": lambda *args: calls.append(args),
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source_path), "exec"), namespace)

    class Hass:
        async def async_add_executor_job(self, fn, *args):
            fn(*args)

    class Manager:
        def collection_site_configs(self):
            return {"fiskvik": {"location": {"timezone": "Europe/Stockholm"}}, "vik": {"location": {"timezone": "Europe/Stockholm"}}}
        def collection_targets(self):
            return [{"site_id": "fiskvik", "logical_role": "house.consumption"}, {"site_id": "vik", "logical_role": "house.consumption"}]
    asyncio.run(namespace["_async_capture_load_forecasts"](Hass(), Manager(), type("Collector", (), {"storage": object()})()))
    assert [args[1] for args in calls] == ["fiskvik", "vik"]


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

    def async_schedule_midnight_recovery(self):
        pass


def test_midnight_callback_requests_one_coordinator_refresh():
    callback = _load_midnight_refresh()
    coordinator = _Coordinator()

    asyncio.run(callback(coordinator, object()))

    assert coordinator.refresh_calls == 1


def test_midnight_callback_starts_recovery_after_refresh():
    callback = _load_midnight_refresh()

    class RecoveryCoordinator(_Coordinator):
        def __init__(self):
            super().__init__()
            self.recovery_calls = 0

        def async_schedule_midnight_recovery(self):
            self.recovery_calls += 1

    coordinator = RecoveryCoordinator()
    asyncio.run(callback(coordinator, object()))

    assert coordinator.recovery_calls == 1


def test_midnight_schedule_and_lifecycle_contract_are_present():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")

    assert "async_track_time_change(" in source
    assert "hour=0" in source
    assert "minute=0" in source
    assert "second=0" in source
    assert 'frontend_data["midnight_refresh_unsub"]' in source
    assert 'frontend_data.pop("midnight_refresh_unsub", None)' in source
    assert "async_schedule_midnight_recovery" in source
    assert "async_request_refresh" in source
    assert "set_interval" not in source


def test_price_recovery_is_bounded_and_cancelable():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "coordinator.py"
    source = source_path.read_text(encoding="utf-8")
    assert "_price_data_by_date" in source
    assert "_active_price_date" in source
    assert "async_get_price_data" in source
    assert "refresh=True" in source
    assert "_async_fetch_date(target_date)" in source


def test_site_independent_forecast_and_evidence_providers_are_wired():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")

    assert "site_identity_manager.forecast_collection_targets" in source
    assert "site_identity_manager.collection_site_configs" in source
    assert "await solar_forecast_manager.async_capture_collection_baselines()" in source
    assert 'frontend_data["solar_evidence_startup_task"] = hass.async_create_task(' in source
    assert "solar_evidence_manager.async_startup_catch_up()" in source


def test_baseline_capture_precedes_evidence_startup_catch_up():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    coordinator_source = source_path.with_name("coordinator.py").read_text(encoding="utf-8")

    baseline = source.index("await solar_forecast_manager.async_capture_collection_baselines()")
    catch_up = source.index('frontend_data["solar_evidence_startup_task"] = hass.async_create_task(')
    assert baseline < catch_up
    assert "for delay in (15, 30, 60, 120, 240)" in coordinator_source
    assert "cancel_midnight_recovery" in source
    assert "_NEXT_DAY_PREFETCH_START_HOUR = 14" in coordinator_source
    assert "at most once per local hour" in coordinator_source


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


def test_control_plane_is_registered_before_risky_runtime_initialization():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")

    assert 'frontend_data["runtime_status"] = "initializing"' in source
    assert 'frontend_data["runtime_status"] = "failed"' in source
    assert 'frontend_data["runtime_status"] = "ready"' in source
    assert source.index("async_register_websocket_commands(hass)") < source.index("await manager.async_load()")
    assert source.index('frontend_data["runtime_status"] = "ready"') < source.index("hass.bus.async_fire(INTEGRATION_READY_EVENT)")


def test_open_meteo_startup_capture_is_scheduled_and_cancelled_with_unload():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    assert 'frontend_data["open_meteo_startup_task"] = hass.async_create_task(' in source
    assert 'frontend_data.pop("open_meteo_startup_task", None)' in source


def test_monthly_forecast_startup_capture_is_scheduled_after_source_event_listeners():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    listeners = source.index('frontend_data["monthly_forecast_event_unsubs"] = [')
    startup = source.index('frontend_data["monthly_forecast_startup_task"] = hass.async_create_task(')
    assert listeners < startup
    assert 'hass.bus.async_listen("elrakning_load_forecast_update"' in source[listeners:startup]
    assert 'hass.bus.async_listen(ELECTRICITY_PROVIDER_UPDATE_EVENT' in source[listeners:startup]
    assert 'hass.bus.async_listen(EON_GRID_UPDATE_EVENT' in source[listeners:startup]


def test_monthly_forecast_capture_persists_fail_closed_builder_errors():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    wrapper = source.index("async def _async_capture_monthly_forecast(hass)")
    implementation = source.index("async def _async_capture_monthly_forecast_impl(hass)")
    assert wrapper < implementation
    assert 'reason="monthly_forecast_input_builder_failed"' in source[wrapper:implementation]
    assert "manager.async_record_unavailable" in source[wrapper:implementation]


def test_control_plane_state_handlers_have_safe_pre_ready_contract():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "websocket.py"
    source = source_path.read_text(encoding="utf-8")

    assert source.count("if response := _runtime_not_ready(hass):") == 3
    assert '"status": status' in source
    assert '"error": "runtime_not_ready"' in source
    assert '"runtime_status", "unavailable"' in source


def test_forecast_capture_status_websocket_is_read_only_and_registered():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "websocket.py"
    source = source_path.read_text(encoding="utf-8")
    handler_start = source.index("async def websocket_canonical_collector_state")
    handler_end = source.index("async def websocket_frontend_preferences", handler_start)
    handler = source[handler_start:handler_end]
    assert "CANONICAL_COLLECTOR_STATE_COMMAND" in source
    assert "websocket_api.async_register_command(hass, websocket_canonical_collector_state)" in source
    assert "forecast_capture_status()" in handler
    assert "open_meteo_capture_status()" in handler
    assert '"open_meteo": collector.open_meteo_capture_status()' in handler
    assert '"open_meteo": None' not in handler
    assert "async_capture_forecast_solar" not in handler
    assert "persist_forecast_solar_frames" not in handler


def test_canonical_collector_status_contract_includes_read_only_open_meteo_diagnostics():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "websocket.py"
    source = source_path.read_text(encoding="utf-8")
    handler_start = source.index("async def websocket_canonical_collector_state")
    handler_end = source.index("async def websocket_frontend_preferences", handler_start)
    handler = source[handler_start:handler_end]

    assert '"forecast_solar": collector.forecast_capture_status()' in handler
    assert '"open_meteo": collector.open_meteo_capture_status()' in handler
    assert "open_meteo_capture_status()" not in handler.replace(
        '"open_meteo": collector.open_meteo_capture_status()', "", 1
    )


def test_panel_is_registered_before_site_runtime_initialization():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")

    assert "async_register_built_in_panel" in source
    assert source.index("await _async_register_frontend(hass)") < source.index("await manager.async_load()")
    assert source.index("await _async_register_frontend(hass)") < source.index("await site_identity_manager.async_prepare_runtime_bindings")
