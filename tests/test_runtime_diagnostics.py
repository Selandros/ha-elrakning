import asyncio
import importlib.util
import json
import logging
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "runtime_diagnostics", Path(__file__).parents[1] / "custom_components/elrakning/runtime_diagnostics.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
async_event_loop_lag_heartbeat = MODULE.async_event_loop_lag_heartbeat
runtime_checkpoint = MODULE.runtime_checkpoint


def test_runtime_checkpoint_is_bounded_and_identifies_thread(caplog):
    with caplog.at_level(logging.INFO, logger=MODULE._LOGGER.name):
        runtime_checkpoint("test.checkpoint", phase="test", secret="x" * 500)

    record = next(record for record in reversed(caplog.records) if "runtime_checkpoint" in record.message)
    payload = json.loads(record.message.split("runtime_checkpoint ", 1)[1])
    assert payload["label"] == "test.checkpoint"
    assert payload["phase"] == "test"
    assert payload["thread"]
    assert len(payload["secret"]) == 160


def test_event_loop_heartbeat_is_cancelable_without_orphan_task():
    async def exercise():
        task = asyncio.create_task(
            async_event_loop_lag_heartbeat(interval_seconds=0.01, warning_threshold_seconds=1.0)
        )
        await asyncio.sleep(0.02)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert task.done()
        assert task.cancelled()

    asyncio.run(exercise())
