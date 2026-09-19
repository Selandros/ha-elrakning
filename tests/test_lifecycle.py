import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import threading
import unittest

_MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "elrakning" / "elhandel" / "lifecycle.py"
_SPEC = spec_from_file_location("elrakning_lifecycle", _MODULE_PATH)
_MODULE = module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
LifecycleManager = _MODULE.LifecycleManager


class _Hass:
    def __init__(self):
        self.loop = asyncio.get_running_loop()

    @staticmethod
    def async_create_task(coroutine):
        return asyncio.create_task(coroutine)

    def create_task(self, coroutine):
        if threading.get_ident() == self.loop._thread_id:
            return asyncio.create_task(coroutine)
        result = {}
        completed = threading.Event()

        def schedule():
            result["task"] = asyncio.create_task(coroutine)
            completed.set()

        self.loop.call_soon_threadsafe(schedule)
        if not completed.wait(1):
            raise AssertionError("thread-safe task scheduling timed out")
        return result["task"]


class LifecycleManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_task_uses_thread_safe_task_api_from_worker(self):
        hass = _Hass()
        lifecycle = LifecycleManager(hass)
        received = []

        async def callback(generation):
            received.append(generation)

        task = await asyncio.to_thread(lifecycle.start_refresh, callback)
        await task

        self.assertEqual(received, [0])

    async def test_refresh_task_starts_once_until_complete(self):
        lifecycle = LifecycleManager(_Hass())
        started = asyncio.Event()
        release = asyncio.Event()

        async def callback(generation):
            self.assertEqual(generation, 0)
            started.set()
            await release.wait()

        first = lifecycle.start_refresh(callback)
        second = lifecycle.start_refresh(callback)
        await started.wait()

        self.assertIs(first, second)
        release.set()
        await first

    async def test_consumption_task_starts(self):
        lifecycle = LifecycleManager(_Hass())
        received = []

        async def callback(generation):
            received.append(generation)

        task = lifecycle.start_consumption_refresh(callback)
        await task

        self.assertEqual(received, [0])

    async def test_cancel_tasks_cancels_tasks_and_unsubscribes(self):
        lifecycle = LifecycleManager(_Hass())
        release = asyncio.Event()
        unsubscribed = []

        async def callback(generation):
            await release.wait()

        lifecycle.set_refresh_unsubscribe(lambda: unsubscribed.append("refresh"))
        lifecycle.set_consumption_unsubscribe(lambda: unsubscribed.append("consumption"))
        refresh_task = lifecycle.start_refresh(callback)
        consumption_task = lifecycle.start_consumption_refresh(callback)
        await asyncio.sleep(0)

        lifecycle.cancel_tasks()
        await asyncio.gather(refresh_task, consumption_task, return_exceptions=True)
        self.assertTrue(refresh_task.cancelled())
        self.assertTrue(consumption_task.cancelled())
        self.assertEqual(unsubscribed, ["refresh", "consumption"])

    async def test_invalidate_generation_rejects_old_callback(self):
        lifecycle = LifecycleManager(_Hass())
        seen = []

        async def callback(generation):
            lifecycle.invalidate_generation()
            seen.append(lifecycle.is_current(generation))

        task = lifecycle.start_refresh(callback)
        await task

        self.assertEqual(seen, [False])

    async def test_shutdown_cancels_tasks_and_unsubscribes(self):
        lifecycle = LifecycleManager(_Hass())
        release = asyncio.Event()
        unsubscribed = []

        async def callback(generation):
            await release.wait()

        lifecycle.set_refresh_unsubscribe(lambda: unsubscribed.append("refresh"))
        task = lifecycle.start_refresh(callback)
        await asyncio.sleep(0)

        await lifecycle.async_shutdown()
        await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(task.cancelled())
        self.assertEqual(unsubscribed, ["refresh"])
