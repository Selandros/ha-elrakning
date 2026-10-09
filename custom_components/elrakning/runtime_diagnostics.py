"""Bounded runtime diagnostics for setup and event-loop responsiveness."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import threading
import time
from typing import Any


_LOGGER = logging.getLogger(__name__)
_MAX_FIELD_LENGTH = 160


def _safe_field(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str):
            return value[:_MAX_FIELD_LENGTH]
        return value
    return str(value)[:_MAX_FIELD_LENGTH]


def runtime_checkpoint(
    label: str,
    *,
    phase: str = "setup",
    started_at: float | None = None,
    level: int = logging.INFO,
    **fields: Any,
) -> float:
    """Emit one bounded checkpoint and return a monotonic start marker."""
    now = time.monotonic()
    payload = {
        "label": label,
        "phase": phase,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "thread": threading.current_thread().name,
        "duration_ms": round((now - started_at) * 1000, 3) if started_at is not None else None,
    }
    payload.update({key: _safe_field(value) for key, value in fields.items()})
    _LOGGER.log(level, "runtime_checkpoint %s", json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return now


async def async_event_loop_lag_heartbeat(
    *,
    interval_seconds: float = 1.0,
    warning_threshold_seconds: float = 0.25,
) -> None:
    """Report only material event-loop gaps and keep normal operation quiet."""
    expected = time.monotonic() + interval_seconds
    while True:
        await asyncio.sleep(interval_seconds)
        now = time.monotonic()
        lag = max(0.0, now - expected)
        if lag >= warning_threshold_seconds:
            runtime_checkpoint(
                "event_loop_lag",
                phase="heartbeat",
                level=logging.WARNING,
                lag_ms=round(lag * 1000, 3),
            )
        expected = now + interval_seconds
