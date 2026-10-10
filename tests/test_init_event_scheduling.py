import ast
import asyncio
import concurrent.futures
from pathlib import Path
import threading
from types import SimpleNamespace


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


def test_pending_clean_reset_precedes_frontend_and_heavy_setup():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    setup_start = source.index("async def async_setup_entry")
    preflight = source.index("await _async_apply_pending_clean_install(hass, entry)", setup_start)
    frontend = source.index("await _await_setup_step(\"setup_entry.frontend_register\"", setup_start)
    heavy = source.index("await _await_setup_step(\"setup.manager_load\"", setup_start)
    assert preflight < frontend < heavy


def test_staged_start_boundaries_are_ordered_and_normal_setup_remains_default():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")

    assert 'DIAGNOSTIC_STAGE_OPTION = "diagnostic_stage"' in (
        Path(__file__).parents[1] / "custom_components" / "elrakning" / "const.py"
    ).read_text(encoding="utf-8")
    assert "diagnostic_stage = _diagnostic_stage(entry)" in source
    assert 'if diagnostic_stage == 0:' in source
    for stage in range(1, 14):
        assert f'if _diagnostic_pause_at(hass, {stage}, stage_started_at)' in source
    assert 'if _diagnostic_pause_at(hass, 14, stage_started_at)' not in source
    assert 'DIAGNOSTIC_STAGE_MAX = 15' in (
        Path(__file__).parents[1] / "custom_components" / "elrakning" / "const.py"
    ).read_text(encoding="utf-8")
    assert 'diagnostic_stage is None' in source
    assert 'highspy_diagnostic_mode=True' in source

    setup_start = source.index("async def async_setup_entry")
    preflight = source.index("await _async_apply_pending_clean_install(hass, entry)", setup_start)
    stage_option = source.index("diagnostic_stage = _diagnostic_stage(entry)", setup_start)
    stage_zero = source.index('if diagnostic_stage == 0:', setup_start)
    heavy = source.index('await _await_setup_step("setup.manager_load"', setup_start)
    assert preflight < stage_option < stage_zero < heavy


def test_disabled_stages_do_not_create_shadow_client_or_highspy_path():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    assert 'frontend_data["app_shadow_client"] = None' in source
    assert 'if diagnostic_stage is None:' in source
    assert "HIGHSPY_DIAGNOSTIC_MODE = True" in (
        Path(__file__).parents[1] / "custom_components" / "elrakning" / "economic_optimizer.py"
    ).read_text(encoding="utf-8")


def test_staged_boundaries_keep_heavy_subsystems_separate():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    labels = [
        "frontend",
        "websocket",
        "identity_shell",
        "runtime_shell",
        "provider_bindings",
        "canonical_collector",
        "canonical_prepare",
        "forecast_resources",
        "forecast_baselines",
        "load_forecast",
        "canonical_captures",
        "provider_recovery",
        "runtime_bindings",
        "replay",
        "app_shadow",
    ]
    positions = [source.index(f'_diagnostic_stage_start({index}, "{label}")') for index, label in enumerate(labels, start=1)]
    assert positions == sorted(positions)
    assert source.index('"setup.canonical_collector_start"') < source.index(
        '"setup.eon_cached_import_recovery"'
    )
    assert source.index('"setup.eon_cached_import_recovery"') < source.index(
        '"replay_scheduler_registered"'
    )


def test_stage_zero_requires_a_completed_clean_install_receipt():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    assert 'if diagnostic_stage == 0 and not _has_clean_install_receipt(entry):' in source
    assert 'raise ValueError("diagnostic_stage_zero_requires_clean_install_receipt")' in source


def test_load_forecast_cadence_uses_thread_safe_create_task_from_worker_thread():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    names = {
        "_ReplayTaskProxy",
        "_LoadForecastTaskOwner",
        "_get_load_forecast_task_owner",
        "_schedule_load_forecast_capture",
    }
    nodes = [
        node for node in tree.body
        if (isinstance(node, ast.ClassDef) and node.name in names)
        or (isinstance(node, ast.FunctionDef) and node.name in names)
    ]
    namespace = {
        "asyncio": asyncio,
        "concurrent": concurrent,
        "threading": threading,
        "DOMAIN": "elrakning",
        "_stage10_trace_start": lambda *_args: None,
        "_stage10_trace_complete": lambda *_args, **_kwargs: None,
        "_create_background_task_on_ha_loop": _load_background_task_helper(),
    }

    async def capture(*_args):
        return None

    namespace["_async_capture_load_forecasts"] = capture
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source_path), "exec"), namespace)

    class ThreadSafeHass:
        def __init__(self):
            self.loop = asyncio.get_running_loop()
            self.data = {"elrakning": {}}
            self.async_create_task_called = False
            self.created = []

        def async_create_task(self, _coroutine):
            self.async_create_task_called = True
            raise AssertionError("worker callback used async_create_task")

        def async_create_background_task(self, coroutine, *, name):
            assert asyncio.get_running_loop() is self.loop
            task = asyncio.create_task(coroutine, name=name)
            self.created.append(task)
            return task

    async def exercise():
        hass = ThreadSafeHass()
        task = await asyncio.to_thread(
            namespace["_schedule_load_forecast_capture"], hass, object(), object()
        )
        await task
        assert hass.async_create_task_called is False
        assert hass.created[0].get_name() == "elrakning_load_forecast"

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
        "_stage10_trace_start": lambda *_args: None,
        "_stage10_trace_complete": lambda *_args, **_kwargs: None,
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


def test_clean_room_load_forecast_callback_does_no_executor_work():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_async_capture_load_forecasts"
    )
    executor_calls = []
    namespace = {
        "timezone": __import__("datetime").timezone,
        "dt_util": type("Dt", (), {"now": staticmethod(lambda: __import__("datetime").datetime(2026, 9, 20))}),
        "build_site_load_forecast": lambda *_args: None,
        "_stage10_trace_start": lambda *_args: None,
        "_stage10_trace_complete": lambda *_args, **_kwargs: None,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source_path), "exec"), namespace)

    class Hass:
        data = {"elrakning": {}}

        async def async_add_executor_job(self, fn, *args):
            executor_calls.append((fn, args))
            raise AssertionError("clean-room forecast callback must not use the executor")

    class EmptyManager:
        def collection_site_configs(self):
            return {}

        def collection_targets(self):
            return []

    asyncio.run(
        namespace["_async_capture_load_forecasts"](
            Hass(), EmptyManager(), type("Collector", (), {"storage": object()})()
        )
    )
    assert executor_calls == []


def test_stage10_trace_separates_registration_schedule_and_callback():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    assert '"cadence_registration"' in source
    assert '"load_forecast_schedule"' in source
    assert '"load_forecast_callback_targets"' in source
    assert '"load_forecast_callback"' in source
    assert '"monthly_forecast_schedule"' in source
    assert '"monthly_forecast_callback_targets"' in source


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
    assert '"setup.solar_forecast_capture_baselines"' in source
    assert 'frontend_data["solar_evidence_startup_task"] = hass.async_create_task(' in source
    assert "solar_evidence_manager.async_startup_catch_up()" in source


def test_stage12_has_bounded_warning_tracing_for_each_recovery_path():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")

    assert "def _stage12_trace_event" in source
    assert "level=logging.WARNING" in source
    assert '"diagnostic.stage_12.startup_catch_up.registration"' in source
    assert '"diagnostic.stage_12.backfill.registration"' in source
    assert '"diagnostic.stage_12.eon_handoff_registration"' in source
    assert '"diagnostic.stage_12.eon_cached_import_recovery"' in source
    assert '"diagnostic.stage_12.quality_recovery.registration"' in (
        Path(__file__).parents[1] / "custom_components" / "elrakning" / "solar_evidence.py"
    ).read_text(encoding="utf-8")


def test_replay_artifact_generation_is_background_work_outside_startup_barrier():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")

    assert "async_create_background_task" in source
    assert "_create_replay_background_task" in source
    assert '"elrakning_replay_artifact_startup"' in source
    assert '"elrakning_replay_artifact_event"' in source
    assert "_run_replay_artifact_background" in source
    assert "Background work must not poison startup" in source
    assert "replay_scheduler_registered" in source
    assert "replay_task_started" in source
    assert "replay_task_completed" in source
    assert "replay_task_cancelled" in source
    assert "replay_task_failed" in source
    assert "replay_trigger_coalesced" in source
    assert "replay_active_task" in source
    assert "replay_pending_site_ids" in source
    assert '"run_id": run_id' in source
    assert '"elrakning_replay_artifact_coalesced"' in source
    assert "call_soon_threadsafe(create_on_loop)" in source
    assert "elrakning_replay_trigger_diagnostic" in source
    assert "_replay_trigger_identity" in source
    assert "replay_active_trigger_keys" in source
    assert "replay_pending_trigger_keys" in source
    assert "_ReplaySiteTaskRegistry" in source
    assert "replay_site_task_registry" in source
    assert "replay_site_timeout" in source
    assert "asyncio.gather" in source
    assert "asyncio.shield" in source
    assert 'frontend_data["replay_artifact_startup_task"] = hass.async_create_task' not in source
    assert "replay_refresh_task = hass.create_task(_generate_replay_artifact" not in source


def test_replay_trigger_identity_is_stable_for_duplicate_source_events():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_replay_trigger_identity")
    namespace = {"json": __import__("json")}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source_path), "exec"), namespace)
    _replay_trigger_identity = namespace["_replay_trigger_identity"]

    event = SimpleNamespace(
        event_type="elrakning_load_forecast_update",
        data={"site_id": "site-a", "frame_id": "frame-1", "forecast_id": "forecast-1"},
    )
    duplicate = SimpleNamespace(
        event_type=event.event_type,
        data={"forecast_id": "forecast-1", "frame_id": "frame-1", "site_id": "site-a"},
    )
    changed = SimpleNamespace(
        event_type=event.event_type,
        data={"site_id": "site-a", "frame_id": "frame-2", "forecast_id": "forecast-2"},
    )
    assert _replay_trigger_identity(event) == _replay_trigger_identity(duplicate)
    assert _replay_trigger_identity(event) != _replay_trigger_identity(changed)


def _load_replay_scheduler():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        and node.name in {
            "_ReplayTaskProxy",
            "_ReplaySiteTaskRegistry",
            "_create_background_task_on_ha_loop",
            "_create_replay_background_task",
        }
    ]
    namespace = {
        "asyncio": asyncio,
        "concurrent": concurrent,
        "threading": threading,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source_path), "exec"), namespace)
    return namespace["_create_replay_background_task"]


def _load_replay_site_registry():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_ReplaySiteTaskRegistry")
    namespace = {"asyncio": asyncio}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source_path), "exec"), namespace)
    return namespace["_ReplaySiteTaskRegistry"]


def test_replay_site_timeout_keeps_single_flight_and_does_not_cancel_work():
    registry_class = _load_replay_site_registry()

    async def exercise():
        registry = registry_class()
        started = asyncio.Event()
        release = asyncio.Event()
        cancelled = []

        async def stuck():
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        first = await registry.run("site-a", lambda: stuck(), 0.001, "replay-site-a")
        assert first["reason"] == "replay_timeout"
        assert first["task_active"] is True
        assert started.is_set()
        second = await registry.run("site-a", lambda: (_ for _ in ()).throw(AssertionError("duplicate")), 0.001, "replay-site-a-duplicate")
        assert second["reason"] == "site_replay_active"
        assert cancelled == []
        await registry.async_close()
        assert cancelled == [True]

    asyncio.run(exercise())


def test_replay_site_timeout_does_not_block_another_site():
    registry_class = _load_replay_site_registry()

    async def exercise():
        registry = registry_class()
        release = asyncio.Event()

        async def stuck():
            await release.wait()

        async def healthy():
            return {"accepted": True, "site_id": "site-b"}

        first = await registry.run("site-a", lambda: stuck(), 0.001, "replay-site-a")
        assert first["reason"] == "replay_timeout"
        second = await registry.run("site-b", lambda: healthy(), 0.1, "replay-site-b")
        assert second == {"accepted": True, "site_id": "site-b"}
        await registry.async_close()

    asyncio.run(exercise())


class _ReplaySchedulerHass:
    def __init__(self):
        self.loop = asyncio.get_running_loop()
        self.created = []

    def async_create_background_task(self, coroutine, *, name):
        assert asyncio.get_running_loop() is self.loop
        task = asyncio.create_task(coroutine, name=name)
        self.created.append(task)
        return task

    def async_create_task(self, coroutine):
        assert asyncio.get_running_loop() is self.loop
        task = asyncio.create_task(coroutine)
        self.created.append(task)
        return task


def test_replay_scheduler_uses_background_api_on_active_loop():
    scheduler = _load_replay_scheduler()

    async def exercise():
        hass = _ReplaySchedulerHass()
        factory_calls = []

        async def work():
            factory_calls.append(asyncio.get_running_loop())
            return "ok"

        task = scheduler(hass, lambda: work(), "replay-test")
        assert task is hass.created[0]
        assert await task == "ok"
        assert factory_calls == [hass.loop]

    asyncio.run(exercise())


def test_replay_work_has_bounded_timeout():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_replay_with_timeout"
    ]
    namespace = {"asyncio": asyncio, "REPLAY_RUN_TIMEOUT_SECONDS": 20 * 60}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source_path), "exec"), namespace)

    async def exercise():
        async def stuck():
            await asyncio.sleep(10)

        try:
            await namespace["_run_replay_with_timeout"](stuck(), timeout_seconds=0.001)
        except asyncio.TimeoutError:
            return
        raise AssertionError("replay timeout did not terminalize")

    asyncio.run(exercise())


def test_replay_scheduler_marshals_worker_thread_without_loop_mismatch():
    scheduler = _load_replay_scheduler()

    async def exercise():
        hass = _ReplaySchedulerHass()
        factory_calls = []
        release = asyncio.Event()

        async def work():
            factory_calls.append(asyncio.get_running_loop())
            await release.wait()
            return "worker-ok"

        task = await asyncio.to_thread(scheduler, hass, lambda: work(), "replay-worker-test")
        assert not task.done()
        release.set()
        assert await task == "worker-ok"
        assert factory_calls == [hass.loop]
        assert len(hass.created) == 1

    asyncio.run(exercise())


def test_replay_scheduler_proxy_propagates_scheduling_error_without_orphan_task():
    scheduler = _load_replay_scheduler()

    async def exercise():
        hass = _ReplaySchedulerHass()

        def factory():
            raise RuntimeError("scheduler-failed")

        task = await asyncio.to_thread(scheduler, hass, factory, "replay-error-test")
        try:
            await task
        except RuntimeError as error:
            assert str(error) == "scheduler-failed"
        else:
            raise AssertionError("scheduler error was not propagated")
        assert hass.created == []

    asyncio.run(exercise())


def test_baseline_capture_precedes_evidence_startup_catch_up():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    coordinator_source = source_path.with_name("coordinator.py").read_text(encoding="utf-8")

    baseline = source.index('"setup.solar_forecast_capture_baselines"')
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
    assert '"setup.coordinator_first_refresh"' in source
    assert '"setup.manager_load"' in source
    assert '"setup.meter_manager_load"' in source
    assert '"setup.power_manager_load"' in source
    assert "async_register_websocket_commands(hass)" in source
    assert "hass.bus.async_fire(INTEGRATION_READY_EVENT)" in source
    assert source.index("async_register_websocket_commands(hass)") < source.index("hass.bus.async_fire(INTEGRATION_READY_EVENT)")


def test_control_plane_is_registered_before_risky_runtime_initialization():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")

    assert 'frontend_data["runtime_status"] = "initializing"' in source
    assert 'frontend_data["runtime_status"] = "failed"' in source
    assert 'frontend_data["runtime_status"] = "ready"' in source
    assert source.index("async_register_websocket_commands(hass)") < source.index('"setup.manager_load"')
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
    startup = source.index('owner = _get_monthly_forecast_task_owner(hass, entry)')
    assert listeners < startup
    assert 'hass.bus.async_listen("elrakning_load_forecast_update"' in source[listeners:startup]
    assert 'hass.bus.async_listen(ELECTRICITY_PROVIDER_UPDATE_EVENT' in source[listeners:startup]
    assert 'hass.bus.async_listen(EON_GRID_UPDATE_EVENT' in source[listeners:startup]


def test_monthly_forecast_capture_persists_fail_closed_builder_errors():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    wrapper = source.index("async def _async_capture_monthly_forecast(hass)")
    implementation = source.index("async def _async_capture_monthly_forecast_impl(hass, requested_site_id")
    assert wrapper < implementation
    assert 'reason="monthly_forecast_input_builder_failed"' in source[wrapper:implementation]
    assert "manager.async_record_unavailable" in source[wrapper:implementation]


def test_monthly_forecast_startup_capture_runs_after_ready_event():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    ready = source.index("hass.bus.async_fire(INTEGRATION_READY_EVENT)")
    return_statement = source.index("    return True", ready)
    startup = source[ready:return_statement]
    assert 'owner = _get_monthly_forecast_task_owner(hass, entry)' in startup
    assert 'frontend_data["monthly_forecast_startup_task"] = owner.schedule()' in startup
    assert "_get_monthly_forecast_task_owner(hass, entry)" in startup


def test_monthly_forecast_startup_capture_is_owned_for_unload_cancellation():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    assert 'frontend_data["monthly_forecast_startup_task"]' in source
    assert 'frontend_data.pop("monthly_forecast_task_owner", None)' in source
    assert "monthly_forecast_owner.close()" in source
    assert 'frontend_data.pop("monthly_forecast_startup_task", None)' in source


def test_monthly_forecast_startup_reuses_owner_created_by_early_event():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        and node.name in {"_MonthlyForecastTaskOwner", "_get_monthly_forecast_task_owner"}
    ]
    namespace = {
        "asyncio": asyncio,
        "DOMAIN": "elrakning",
        "_stage10_trace_start": lambda *_args: None,
        "_stage10_trace_complete": lambda *_args, **_kwargs: None,
        "_async_capture_monthly_forecast": lambda _hass: _capture(),
        "_create_background_task_on_ha_loop": lambda hass, factory, name: hass.async_create_background_task(factory(), name=name),
    }

    async def _capture():
        await asyncio.Event().wait()

    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source_path), "exec"), namespace)
    owner_factory = namespace["_get_monthly_forecast_task_owner"]

    async def exercise():
        hass = _MonthlyForecastHass()
        first = owner_factory(hass, _MonthlyForecastEntry())
        task = first.schedule()
        second = owner_factory(hass, _MonthlyForecastEntry())
        assert second is first
        assert second.task is task
        first.close()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


def _load_monthly_forecast_task_owner(capture, task_helper=None):
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    class_node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_MonthlyForecastTaskOwner")
    namespace = {
        "asyncio": asyncio,
        "DOMAIN": "elrakning",
        "_stage10_trace_start": lambda *_args: None,
        "_stage10_trace_complete": lambda *_args, **_kwargs: None,
        "_async_capture_monthly_forecast": capture,
        "_create_background_task_on_ha_loop": task_helper or (
            lambda hass, factory, name: hass.async_create_background_task(factory(), name=name)
        ),
    }
    exec(compile(ast.Module(body=[class_node], type_ignores=[]), str(source_path), "exec"), namespace)
    return namespace["_MonthlyForecastTaskOwner"]


def _load_background_task_helper():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    nodes = [
        node for node in tree.body
        if (isinstance(node, ast.ClassDef) and node.name == "_ReplayTaskProxy")
        or (isinstance(node, ast.FunctionDef) and node.name == "_create_background_task_on_ha_loop")
    ]
    namespace = {
        "asyncio": asyncio,
        "concurrent": concurrent,
        "threading": threading,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source_path), "exec"), namespace)
    return namespace["_create_background_task_on_ha_loop"]


def _load_load_forecast_task_owner(capture):
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    names = {
        "_ReplayTaskProxy",
        "_LoadForecastTaskOwner",
        "_get_load_forecast_task_owner",
        "_schedule_load_forecast_capture",
    }
    nodes = [
        node for node in tree.body
        if (isinstance(node, ast.ClassDef) and node.name in names)
        or (isinstance(node, ast.FunctionDef) and node.name in names)
    ]
    namespace = {
        "asyncio": asyncio,
        "concurrent": concurrent,
        "threading": threading,
        "DOMAIN": "elrakning",
        "_stage10_trace_start": lambda *_args: None,
        "_stage10_trace_complete": lambda *_args, **_kwargs: None,
        "_async_capture_load_forecasts": capture,
        "_create_background_task_on_ha_loop": _load_background_task_helper(),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source_path), "exec"), namespace)
    return namespace["_LoadForecastTaskOwner"], namespace["_get_load_forecast_task_owner"]


def test_load_forecast_startup_uses_background_owner_not_bootstrap_task():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    setup_start = source.index("async def _async_setup_entry")
    setup_end = source.index("\n\nasync def async_unload_entry", setup_start)
    setup = source[setup_start:setup_end]

    assert 'frontend_data["load_forecast_startup_task"] = hass.async_create_task(' not in setup
    assert 'frontend_data["load_forecast_startup_task"] = load_forecast_owner.schedule()' in setup
    assert 'load_forecast_task_owner' in setup
    assert '"elrakning_load_forecast"' in source


def test_load_forecast_owner_starts_after_setup_and_coalesces_triggers():
    async def exercise():
        started = []
        releases = []

        async def capture(*_args):
            started.append(True)
            release = asyncio.Event()
            releases.append(release)
            await release.wait()

        owner_class, _ = _load_load_forecast_task_owner(capture)
        loop = asyncio.get_running_loop()
        hass = SimpleNamespace(
            data={"elrakning": {}},
            loop=loop,
            async_create_background_task=lambda coroutine, name: asyncio.create_task(coroutine, name=name),
        )
        owner = owner_class(hass, object(), object())
        first = owner.schedule()
        assert owner.schedule() is first
        await asyncio.sleep(0)
        assert started == [True]
        assert first.done() is False
        releases[0].set()
        await first
        for _ in range(3):
            await asyncio.sleep(0)
        assert len(started) == 2
        releases[1].set()
        await owner.task
        owner.close()

    asyncio.run(exercise())


def test_load_forecast_owner_close_cancels_background_capture_cleanly():
    async def exercise():
        release = asyncio.Event()

        async def capture(*_args):
            await release.wait()

        owner_class, _ = _load_load_forecast_task_owner(capture)
        loop = asyncio.get_running_loop()
        hass = SimpleNamespace(
            data={"elrakning": {}},
            loop=loop,
            async_create_background_task=lambda coroutine, name: asyncio.create_task(coroutine, name=name),
        )
        owner = owner_class(hass, object(), object())
        task = owner.schedule()
        await asyncio.sleep(0)
        closed_task = owner.close()
        assert closed_task is task
        assert owner.closed is True
        await asyncio.gather(task, return_exceptions=True)
        for _ in range(2):
            await asyncio.sleep(0)
        assert owner.task is None

    asyncio.run(exercise())


def test_load_forecast_owner_consumes_unexpected_capture_exception():
    async def exercise():
        async def capture(*_args):
            raise RuntimeError("capture failure")

        owner_class, _ = _load_load_forecast_task_owner(capture)
        loop = asyncio.get_running_loop()
        hass = SimpleNamespace(
            data={"elrakning": {}},
            loop=loop,
            async_create_background_task=lambda coroutine, name: asyncio.create_task(coroutine, name=name),
        )
        owner = owner_class(hass, object(), object())
        task = owner.schedule()
        try:
            await task
        except RuntimeError:
            pass
        for _ in range(2):
            await asyncio.sleep(0)
        assert owner.task is None
        assert hass.data["elrakning"]["load_forecast_capture_task"] is None
        owner.close()

    asyncio.run(exercise())


class _MonthlyForecastEntry:
    def async_create_background_task(self, _hass, coroutine, *, name):
        return asyncio.create_task(coroutine, name=name)


class _MonthlyForecastHass:
    def __init__(self):
        self.data = {"elrakning": {}}

    def async_create_background_task(self, coroutine, *, name):
        return asyncio.create_task(coroutine, name=name)


def test_monthly_forecast_worker_schedule_uses_ha_loop_and_coalesces():
    async def exercise():
        started = []
        releases = []

        async def capture(_hass):
            started.append(True)
            release = asyncio.Event()
            releases.append(release)
            await release.wait()

        helper = _load_background_task_helper()
        loop = asyncio.get_running_loop()
        hass = SimpleNamespace(
            data={"elrakning": {}},
            loop=loop,
            async_create_background_task=lambda coroutine, name: asyncio.create_task(coroutine, name=name),
        )
        owner_class = _load_monthly_forecast_task_owner(capture, helper)
        owner = owner_class(hass, None)

        first = await asyncio.to_thread(owner.schedule)
        second = await asyncio.to_thread(owner.schedule)
        assert second is first
        await asyncio.sleep(0)
        assert len(started) == 1
        releases[0].set()
        await first
        for _ in range(4):
            await asyncio.sleep(0)
        assert len(started) == 2
        releases[1].set()
        await owner.task
        owner.close()

    asyncio.run(exercise())


def test_monthly_forecast_event_listeners_marshal_scheduling_to_ha_loop():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    start = source.index('frontend_data["monthly_forecast_event_unsubs"] = [')
    end = source.index('frontend_data["forecast_view_cache_unsubs"] = [', start)
    listener_source = source[start:end]
    assert listener_source.count("_schedule_monthly_forecast_capture_on_loop(hass)") == 3
    assert "_schedule_monthly_forecast_capture(hass)" not in listener_source


def test_monthly_forecast_single_flight_coalesces_triggers_into_one_rerun():
    async def exercise():
        started = []
        releases = []

        async def capture(_hass):
            started.append(True)
            release = asyncio.Event()
            releases.append(release)
            await release.wait()

        owner_class = _load_monthly_forecast_task_owner(capture)
        hass = _MonthlyForecastHass()
        owner = owner_class(hass, _MonthlyForecastEntry())
        first = owner.schedule()
        assert owner.schedule() is first
        assert owner.schedule() is first
        await asyncio.sleep(0)
        assert len(started) == 1
        releases[0].set()
        await first
        for _ in range(3):
            await asyncio.sleep(0)
        assert len(started) == 2
        releases[1].set()
        for _ in range(3):
            await asyncio.sleep(0)
        assert owner.task is None
        assert owner.pending is False

    asyncio.run(exercise())


def test_monthly_forecast_single_flight_does_not_rerun_without_pending_trigger():
    async def exercise():
        release = asyncio.Event()
        started = 0

        async def capture(_hass):
            nonlocal started
            started += 1
            await release.wait()

        owner_class = _load_monthly_forecast_task_owner(capture)
        hass = _MonthlyForecastHass()
        owner = owner_class(hass, _MonthlyForecastEntry())
        task = owner.schedule()
        await asyncio.sleep(0)
        release.set()
        await task
        await asyncio.sleep(0)
        assert started == 1
        assert owner.task is None

    asyncio.run(exercise())


def test_monthly_forecast_single_flight_close_cancels_task_and_pending_state():
    async def exercise():
        release = asyncio.Event()

        async def capture(_hass):
            await release.wait()

        owner_class = _load_monthly_forecast_task_owner(capture)
        hass = _MonthlyForecastHass()
        owner = owner_class(hass, _MonthlyForecastEntry())
        task = owner.schedule()
        owner.schedule()
        closed_task = owner.close()
        assert closed_task is task
        assert owner.closed is True
        assert owner.pending is False
        assert task.cancelled() is False
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(exercise())


def test_monthly_forecast_uses_persisted_power_snapshot_during_startup_race():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    capture = source.index("async def _async_capture_monthly_forecast_impl(hass, requested_site_id")
    assert "site_state.get(\"power_forecasts\")" in source[capture:]
    assert '"method": "persisted_power_forecast_fallback"' in source[capture:]
    assert 'item.get("site_id") == site_id' in source[capture:]


def test_monthly_forecast_site_selection_is_independent_of_active_ui_site():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_monthly_forecast_site_ids")
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source_path), "exec"), namespace)

    class Identity:
        def collection_site_configs(self):
            return {
                "fiskvik": {"collection_enabled": True},
                "vikarbodarna": {"collection_enabled": True},
                "disabled": {"collection_enabled": False},
            }

    assert namespace["_monthly_forecast_site_ids"](Identity()) == ["fiskvik", "vikarbodarna"]


def test_monthly_forecast_uses_site_bound_provider_state_for_background_sites():
    source_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    source = source_path.read_text(encoding="utf-8")
    capture = source.index("async def _async_capture_monthly_forecast_impl(hass, requested_site_id")
    body = source[capture:source.index("\n\ndef _schedule_load_forecast_capture", capture)]
    assert "site_id = requested_site_id or active_site_id" in body
    assert "public_state_for_binding(grid_binding)" in body
    assert "resolve_grid_tariff(" in body
    assert "use_active_namespace=False" in body
    assert "trade_manager.public_state()" in body


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
    assert source.index('"setup_entry.frontend_register"') < source.index('"setup.manager_load"')
    assert source.index('"setup_entry.frontend_register"') < source.index('"setup.runtime_bindings_prepare"')
