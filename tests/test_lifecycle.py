import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import unittest

_MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "elrakning" / "elhandel" / "lifecycle.py"
_SPEC = spec_from_file_location("elrakning_lifecycle", _MODULE_PATH)
_MODULE = module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
LifecycleManager = _MODULE.LifecycleManager


class _Hass:
    @staticmethod
    def async_create_task(coroutine):
        return asyncio.create_task(coroutine)


class LifecycleManagerTests(unittest.IsolatedAsyncioTestCase):
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
