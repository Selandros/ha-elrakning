"""Bounded, read-only Core-to-App shadow transport."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import time
from typing import Any

from .app_client import AppShadowClient
from .app_contract import AppContractError, validate_state_snapshot
from .const import EON_GRID_UPDATE_EVENT, ELECTRICITY_PROVIDER_UPDATE_EVENT
from .runtime_diagnostics import runtime_checkpoint


_MAX_PENDING_SITES = 8
_HEALTH_RETRY_SECONDS = 60.0
_SHADOW_EVENTS = (
    "elrakning_load_forecast_update",
    ELECTRICITY_PROVIDER_UPDATE_EVENT,
    EON_GRID_UPDATE_EVENT,
)


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat()
    return None


def build_snapshot_from_canonical_frame(
    frame: dict[str, Any], point: dict[str, Any],
) -> dict[str, Any] | None:
    """Adapt one complete immutable frame without filling missing semantics."""
    if not isinstance(frame, dict) or not isinstance(point, dict):
        return None
    site_id = frame.get("site_id")
    generation_id = frame.get("source_generation_id")
    captured_at = _iso(frame.get("captured_at"))
    known_at = _iso(frame.get("known_at"))
    provenance = frame.get("provenance")
    point_context = point.get("point")
    if not isinstance(provenance, dict) or not isinstance(point_context, dict):
        return None
    observed_at = _iso(provenance.get("observed_at") or point_context.get("observed_at"))
    unit = point.get("unit")
    sign_convention = point_context.get("sign_convention")
    if not all(isinstance(value, str) and value for value in (
        site_id, generation_id, captured_at, known_at, observed_at, unit, sign_convention,
    )):
        return None
    source_identity = {
        key: provenance[key]
        for key in (
            "source_identity_key", "origin_type", "provider", "config_entry_id",
            "entity_id", "entity", "binding_fingerprint", "site_id",
        )
        if key in provenance and isinstance(provenance[key], (str, int, float, bool))
    }
    if not source_identity:
        return None
    status = "available" if point.get("value") is not None else "unavailable"
    decision_at = known_at
    snapshot = {
        "contract_version": 1,
        "site_id": site_id,
        "source_generation_id": generation_id,
        "captured_at": captured_at,
        "decision_context": {
            "decision_at": decision_at,
            "frame_id": frame.get("frame_id"),
            "revision": frame.get("revision"),
        },
        "entity_source_identity": source_identity,
        "value": point.get("value"),
        "unit": unit,
        "sign_convention": sign_convention,
        "observed_at": observed_at,
        "known_at": known_at,
        "quality": {
            "frame": deepcopy(frame.get("quality") or {}),
            "point_status": point.get("quality_status"),
        },
        "status": status,
        "provenance": {
            "frame_id": frame.get("frame_id"),
            "revision": frame.get("revision"),
            "semantic_key": frame.get("semantic_key"),
            "payload_schema": frame.get("payload_schema"),
            "source": deepcopy(provenance),
        },
    }
    try:
        return validate_state_snapshot(snapshot)
    except AppContractError:
        return None


class AppShadowManager:
    """Run optional, read-only shadow transport without affecting HA behavior."""

    def __init__(self, hass: Any, client: AppShadowClient, identity: Any, collector: Any) -> None:
        self.hass = hass
        self.client = client
        self.identity = identity
        self.collector = collector
        self._closed = False
        self._unsubs: list[Any] = []
        self._pending_sites: set[str] = set()
        self._active_task: asyncio.Task | None = None
        self._health_lock = asyncio.Lock()
        self._last_health_monotonic = 0.0
        self._status: dict[str, Any] = {
            "enabled": client.enabled,
            "configured": bool(client.enabled),
            "health": "disabled" if not client.enabled else "unknown",
            "last_health_attempt": None,
            "last_health_success": None,
            "snapshot_attempts": 0,
            "snapshot_accepted": 0,
            "snapshot_rejected": 0,
            "snapshot_skipped": 0,
            "last_site_id": None,
            "last_error": None,
            "configured_host": getattr(client, "configured_host", None) or None,
            "effective_host": getattr(client, "effective_host", None),
            "resolution_source": getattr(client, "resolution_source", "unknown"),
            "queue_depth": 0,
            "inflight": 0,
            "physical_control": False,
            "source_of_truth": "core",
        }

    def public_state(self) -> dict[str, Any]:
        return deepcopy({**self._status, "queue_depth": len(self._pending_sites), "inflight": int(self._active_task is not None and not self._active_task.done())})

    async def async_start(self) -> None:
        if not self.client.enabled:
            return
        await self._async_health(force=True)
        if self._closed:
            return
        for event_type in _SHADOW_EVENTS:
            self._unsubs.append(self.hass.bus.async_listen(event_type, self._async_event))

    async def _async_health(self, *, force: bool = False) -> bool:
        if self._closed or not self.client.enabled:
            return False
        now = time.monotonic()
        if not force and now - self._last_health_monotonic < _HEALTH_RETRY_SECONDS:
            return self._status["health"] == "ready"
        async with self._health_lock:
            now = time.monotonic()
            if not force and now - self._last_health_monotonic < _HEALTH_RETRY_SECONDS:
                return self._status["health"] == "ready"
            self._last_health_monotonic = now
            self._status["last_health_attempt"] = datetime.now(timezone.utc).isoformat()
            result = await self.client.async_health()
        ready = result.get("ready") if isinstance(result, dict) else None
        is_ready = isinstance(result, dict) and result.get("available") is True
        self._status["health"] = "ready" if is_ready else "unavailable"
        self._status["last_error"] = None if is_ready else str(result.get("reason") or (ready or {}).get("reason") or "health_unavailable")[:80]
        if is_ready:
            self._status["last_health_success"] = datetime.now(timezone.utc).isoformat()
        runtime_checkpoint(
            "app_shadow.health",
            phase="app_shadow",
            outcome="ready" if is_ready else "unavailable",
        )
        return is_ready

    def _site_ids(self, event: Any) -> list[str]:
        data = getattr(event, "data", None) or {}
        site_id = data.get("site_id") if isinstance(data, dict) else None
        configs = self.identity.collection_site_configs()
        if not isinstance(configs, dict):
            return []
        if isinstance(site_id, str) and site_id in configs:
            return [site_id]
        return sorted(str(value) for value in configs if value)

    async def _async_event(self, event: Any) -> None:
        if self._closed or not await self._async_health():
            return
        for site_id in self._site_ids(event):
            if site_id in self._pending_sites:
                continue
            if self._active_task is not None and not self._active_task.done() and len(self._pending_sites) >= _MAX_PENDING_SITES:
                self._status["snapshot_skipped"] += 1
                self._status["last_error"] = "shadow_backpressure"
                continue
            self._pending_sites.add(site_id)
        self._ensure_drain_task()

    def _ensure_drain_task(self) -> None:
        if self._closed or not self._pending_sites:
            return
        if self._active_task is not None and not self._active_task.done():
            return
        creator = getattr(self.hass, "async_create_background_task", None)
        if callable(creator):
            self._active_task = creator(self._drain(), name="elrakning_app_shadow")
        else:
            self._active_task = self.hass.async_create_task(self._drain())

    async def _drain(self) -> None:
        while self._pending_sites and not self._closed:
            site_id = self._pending_sites.pop()
            snapshot = await self.hass.async_add_executor_job(
                self._read_latest_snapshot, site_id
            )
            if snapshot is None:
                self._status["snapshot_skipped"] += 1
                continue
            self._status["snapshot_attempts"] += 1
            result = await self.client.async_submit_snapshot(snapshot)
            if result.get("accepted") is True:
                self._status["snapshot_accepted"] += 1
                self._status["last_site_id"] = site_id
                self._status["last_error"] = None
            else:
                self._status["snapshot_rejected"] += 1
                self._status["last_error"] = str(result.get("reason") or "snapshot_rejected")[:80]
        self._active_task = None

    def _read_latest_snapshot(self, site_id: str) -> dict[str, Any] | None:
        storage = getattr(self.collector, "storage", None)
        if storage is None:
            return None
        now = datetime.now(timezone.utc)
        frames = storage.read_external_input_frames(now, source_scope="site", site_id=site_id)
        candidates = []
        for frame in frames:
            for point in frame.get("points") or []:
                snapshot = build_snapshot_from_canonical_frame(frame, point)
                if snapshot is not None:
                    candidates.append((snapshot.get("known_at", ""), snapshot))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

    async def async_shutdown(self) -> None:
        self._closed = True
        for unsubscribe in self._unsubs:
            unsubscribe()
        self._unsubs.clear()
        self._pending_sites.clear()
        if self._active_task is not None:
            self._active_task.cancel()
            try:
                await self._active_task
            except asyncio.CancelledError:
                pass
            self._active_task = None
        self._status["health"] = "closed"
