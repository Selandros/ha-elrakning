"""Temporary source-agnostic cadence audit for configured logical roles."""

from __future__ import annotations

import hashlib
import math
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.helpers import event as event_helper
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORE_KEY = "elrakning.cadence_audit"
STORE_VERSION = 1
AUDIT_DURATION = timedelta(hours=24)
CHECKPOINT_SECONDS = 60
UNAVAILABLE_STATES = {"unknown", "unavailable"}

# Stable logical roles are architecture keys. Concrete entities/providers are
# resolved from SiteIdentity at audit start and are never hardcoded here.
AUDITED_LOGICAL_ROLES = frozenset(
    {
        "house.consumption",
        "solar.production",
        "grid.power/import",
        "battery.power",
        "battery.soc",
    }
)

STATE_COMMAND = f"{DOMAIN}/cadence_audit_state"
START_COMMAND = f"{DOMAIN}/cadence_audit_start"
STOP_COMMAND = f"{DOMAIN}/cadence_audit_stop"
CLEANUP_COMMAND = f"{DOMAIN}/cadence_audit_cleanup"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value is not None else None


def _parse(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _seconds_between(start: str | None, end: str | None) -> float | None:
    start_dt = _parse(start)
    end_dt = _parse(end)
    if start_dt is None or end_dt is None:
        return None
    return max(0.0, (end_dt - start_dt).total_seconds())


def _quantile(values: list[float], fraction: float) -> float | None:
    clean = sorted(value for value in values if isinstance(value, (int, float)) and math.isfinite(value))
    if not clean:
        return None
    if len(clean) == 1:
        return float(clean[0])
    position = (len(clean) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(clean[lower])
    weight = position - lower
    return float(clean[lower] + (clean[upper] - clean[lower]) * weight)


def _distribution(values: list[float]) -> dict[str, Any]:
    clean = sorted(value for value in values if isinstance(value, (int, float)) and math.isfinite(value))
    return {
        "count": len(clean),
        "min": float(clean[0]) if clean else None,
        "median": _quantile(clean, 0.5),
        "p95": _quantile(clean, 0.95),
        "p99": _quantile(clean, 0.99),
        "max": float(clean[-1]) if clean else None,
        "unit": "seconds",
    }


def _state_timestamp(state: Any, attribute: str) -> str | None:
    value = getattr(state, attribute, None)
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, str):
        return value
    return None


def _identity_fingerprint(identity: dict[str, Any] | None) -> str | None:
    if not isinstance(identity, dict):
        return None
    key = identity.get("identity_key")
    if not isinstance(key, str) or not key:
        return None
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _empty_signal_metrics() -> dict[str, Any]:
    return {
        "report_count": 0,
        "state_reported_count": 0,
        "state_changed_count": 0,
        "state_value_change_count": 0,
        "same_value_report_count": 0,
        "event_gaps_seconds": [],
        "last_event_at": None,
        "last_reported": None,
        "last_updated": None,
        "last_changed": None,
        "event_minus_last_reported_seconds": [],
        "event_minus_last_updated_seconds": [],
        "event_minus_last_changed_seconds": [],
        "unavailable_periods": [],
        "open_unavailable": None,
    }


class CadenceAuditManager:
    """Observe configured source generations without polling or control writes."""

    def __init__(self, hass, site_identity_manager) -> None:
        self.hass = hass
        self.site_identity_manager = site_identity_manager
        self.store = Store(hass, STORE_VERSION, STORE_KEY)
        self.state: dict[str, Any] = self._empty_state()
        self._event_unsubs: list[Any] = []
        self._finish_unsub = None
        self._checkpoint_unsub = None
        self._signal_ids_by_entity: dict[str, list[str]] = {}

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "status": "idle",
            "audit_id": None,
            "site_id": None,
            "site_name": None,
            "started_at": None,
            "planned_end_at": None,
            "completed_at": None,
            "last_checkpoint_at": None,
            "restart_count": 0,
            "runtime_gaps": [],
            "signals": {},
            "missing_roles": [],
            "scope": {
                "duration_seconds": int(AUDIT_DURATION.total_seconds()),
                "logical_roles": sorted(AUDITED_LOGICAL_ROLES),
                "source_agnostic": True,
                "polling": False,
                "physical_writes": False,
                "canonical_storage": False,
                "stale_after_seconds": None,
            },
        }

    async def async_load(self) -> None:
        cached = await self.store.async_load()
        if isinstance(cached, dict) and cached.get("status") in {
            "idle",
            "running",
            "completed",
            "completed_with_runtime_gap",
            "cancelled",
            "error",
        }:
            self.state = cached
        else:
            self.state = self._empty_state()

        if self.state.get("status") != "running":
            return

        now = _utcnow()
        last_checkpoint = _parse(self.state.get("last_checkpoint_at"))
        if last_checkpoint is not None and now > last_checkpoint:
            self.state.setdefault("runtime_gaps", []).append(
                {
                    "started_at": _iso(last_checkpoint),
                    "ended_at": _iso(now),
                    "duration_seconds": (now - last_checkpoint).total_seconds(),
                    "reason": "ha_restart_or_runtime_unavailable",
                    "basis": "last_persisted_checkpoint",
                }
            )
            self.state["restart_count"] = int(self.state.get("restart_count", 0)) + 1

        planned_end = _parse(self.state.get("planned_end_at"))
        if planned_end is None:
            self.state["status"] = "error"
            self.state["completed_at"] = _iso(now)
            await self.store.async_save(self.state)
            return
        if now >= planned_end:
            await self._async_finalize(now)
            return

        self._subscribe()
        self._schedule_finish()
        self._schedule_checkpoint()
        self.state["last_checkpoint_at"] = _iso(now)
        await self.store.async_save(self.state)

    def _build_source_snapshot(self) -> tuple[dict[str, Any], list[str], str | None, str | None]:
        public_state = self.site_identity_manager.public_state()
        site_id = public_state.get("site_id")
        current_site = public_state.get("current_site") or public_state.get("site") or {}
        site_name = current_site.get("name") if isinstance(current_site, dict) else None
        logical_roles = public_state.get("logical_roles")
        entries = logical_roles if isinstance(logical_roles, list) else []

        signals: dict[str, Any] = {}
        observed_roles: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            role = entry.get("logical_role")
            entity_id = entry.get("entity_id")
            generation_id = entry.get("generation_id")
            if role not in AUDITED_LOGICAL_ROLES:
                continue
            if not isinstance(entity_id, str) or not entity_id or not isinstance(generation_id, str) or not generation_id:
                continue
            identity = entry.get("source_identity") if isinstance(entry.get("source_identity"), dict) else {}
            signals[generation_id] = {
                "signal_id": generation_id,
                "logical_role": role,
                "source_generation_id": generation_id,
                "entity_id": entity_id,
                "source_identity": {
                    "fingerprint": _identity_fingerprint(identity),
                    "identity_strength": identity.get("identity_strength"),
                    "identity_provenance": identity.get("identity_provenance"),
                    "platform": identity.get("platform"),
                },
                "metrics": _empty_signal_metrics(),
            }
            observed_roles.add(role)

        missing_roles = sorted(AUDITED_LOGICAL_ROLES - observed_roles)
        return signals, missing_roles, site_id, site_name

    async def async_start(self) -> dict[str, Any]:
        if self.state.get("status") == "running":
            raise ValueError("audit_already_running")

        signals, missing_roles, site_id, site_name = self._build_source_snapshot()
        if not signals:
            raise ValueError("no_auditable_sources")

        now = _utcnow()
        end = now + AUDIT_DURATION
        self.state = self._empty_state()
        self.state.update(
            {
                "status": "running",
                "audit_id": str(uuid.uuid4()),
                "site_id": site_id,
                "site_name": site_name,
                "started_at": _iso(now),
                "planned_end_at": _iso(end),
                "last_checkpoint_at": _iso(now),
                "signals": signals,
                "missing_roles": missing_roles,
            }
        )
        self._seed_initial_unavailable(now)
        self._subscribe()
        self._schedule_finish()
        self._schedule_checkpoint()
        await self.store.async_save(self.state)
        return await self.async_state()

    def _seed_initial_unavailable(self, started_at: datetime) -> None:
        for signal in self.state.get("signals", {}).values():
            entity_id = signal.get("entity_id")
            state = self.hass.states.get(entity_id) if isinstance(entity_id, str) else None
            if state is None:
                continue
            value = str(getattr(state, "state", "")).lower()
            if value in UNAVAILABLE_STATES:
                signal["metrics"]["open_unavailable"] = {
                    "state": value,
                    "started_at": _iso(started_at),
                    "started_before_observation": True,
                    "exact_start_unknown": True,
                }

    def _subscribe(self) -> None:
        self._unsubscribe_events()
        signals = self.state.get("signals", {})
        self._signal_ids_by_entity = {}
        for signal_id, signal in signals.items():
            entity_id = signal.get("entity_id")
            if isinstance(entity_id, str) and entity_id:
                self._signal_ids_by_entity.setdefault(entity_id, []).append(signal_id)
        entity_ids = sorted(self._signal_ids_by_entity)
        if not entity_ids:
            return
        self._event_unsubs = [
            event_helper.async_track_state_report_event(self.hass, entity_ids, self._on_state_reported),
            event_helper.async_track_state_change_event(self.hass, entity_ids, self._on_state_changed),
        ]

    def _unsubscribe_events(self) -> None:
        while self._event_unsubs:
            unsubscribe = self._event_unsubs.pop()
            try:
                unsubscribe()
            except Exception:
                pass

    def _cancel_timers(self) -> None:
        for attribute in ("_finish_unsub", "_checkpoint_unsub"):
            unsubscribe = getattr(self, attribute)
            if unsubscribe:
                try:
                    unsubscribe()
                except Exception:
                    pass
            setattr(self, attribute, None)

    def _schedule_finish(self) -> None:
        if self._finish_unsub:
            self._finish_unsub()
        planned_end = _parse(self.state.get("planned_end_at"))
        if planned_end is None:
            return
        delay = max(0.0, (planned_end - _utcnow()).total_seconds())
        self._finish_unsub = event_helper.async_call_later(self.hass, delay, self._finish_timer)

    def _schedule_checkpoint(self) -> None:
        if self._checkpoint_unsub:
            self._checkpoint_unsub()
        self._checkpoint_unsub = event_helper.async_call_later(
            self.hass, CHECKPOINT_SECONDS, self._checkpoint_timer
        )

    async def _finish_timer(self, _now) -> None:
        self._finish_unsub = None
        if self.state.get("status") == "running":
            await self._async_finalize(_utcnow())

    async def _checkpoint_timer(self, _now) -> None:
        self._checkpoint_unsub = None
        if self.state.get("status") != "running":
            return
        self.state["last_checkpoint_at"] = _iso(_utcnow())
        await self.store.async_save(self.state)
        self._schedule_checkpoint()

    def _event_time(self, event) -> datetime:
        value = getattr(event, "time_fired", None)
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc)
        timestamp = getattr(event, "time_fired_timestamp", None)
        if isinstance(timestamp, (int, float)) and math.isfinite(timestamp):
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        return _utcnow()

    def _on_state_reported(self, event) -> None:
        self._record_event(event, "state_reported")

    def _on_state_changed(self, event) -> None:
        self._record_event(event, "state_changed")

    def _record_event(self, event, event_kind: str) -> None:
        if self.state.get("status") != "running":
            return
        event_time = self._event_time(event)
        planned_end = _parse(self.state.get("planned_end_at"))
        if planned_end is not None and event_time > planned_end:
            return
        data = getattr(event, "data", None) or {}
        entity_id = data.get("entity_id")
        signal_ids = self._signal_ids_by_entity.get(entity_id, [])
        if not signal_ids:
            return
        new_state = data.get("new_state")
        old_state = data.get("old_state")
        for signal_id in signal_ids:
            signal = self.state.get("signals", {}).get(signal_id)
            if not isinstance(signal, dict):
                continue
            metrics = signal.get("metrics")
            if not isinstance(metrics, dict):
                continue
            self._record_signal_event(metrics, event_time, event_kind, old_state, new_state)

    def _record_signal_event(self, metrics: dict[str, Any], event_time: datetime, event_kind: str, old_state, new_state) -> None:
        event_iso = _iso(event_time)
        previous = _parse(metrics.get("last_event_at"))
        if previous is not None and event_time >= previous:
            metrics.setdefault("event_gaps_seconds", []).append((event_time - previous).total_seconds())
        metrics["last_event_at"] = event_iso
        metrics["report_count"] = int(metrics.get("report_count", 0)) + 1

        if event_kind == "state_reported":
            metrics["state_reported_count"] = int(metrics.get("state_reported_count", 0)) + 1
            metrics["same_value_report_count"] = int(metrics.get("same_value_report_count", 0)) + 1
        else:
            metrics["state_changed_count"] = int(metrics.get("state_changed_count", 0)) + 1
            old_value = getattr(old_state, "state", None)
            new_value = getattr(new_state, "state", None)
            if old_state is not None and new_state is not None and old_value != new_value:
                metrics["state_value_change_count"] = int(metrics.get("state_value_change_count", 0)) + 1

        for attribute, output_field in (
            ("last_reported", "event_minus_last_reported_seconds"),
            ("last_updated", "event_minus_last_updated_seconds"),
            ("last_changed", "event_minus_last_changed_seconds"),
        ):
            timestamp = _state_timestamp(new_state, attribute)
            metrics[attribute] = timestamp
            parsed = _parse(timestamp)
            if parsed is not None:
                metrics.setdefault(output_field, []).append((event_time - parsed).total_seconds())

        self._update_unavailable(metrics, event_iso, new_state)

    @staticmethod
    def _update_unavailable(metrics: dict[str, Any], event_iso: str | None, new_state) -> None:
        if event_iso is None or new_state is None:
            return
        value = str(getattr(new_state, "state", "")).lower()
        open_period = metrics.get("open_unavailable")
        if value in UNAVAILABLE_STATES:
            if not isinstance(open_period, dict):
                metrics["open_unavailable"] = {
                    "state": value,
                    "started_at": event_iso,
                    "started_before_observation": False,
                    "exact_start_unknown": False,
                }
            return
        if isinstance(open_period, dict):
            metrics.setdefault("unavailable_periods", []).append(
                {
                    **open_period,
                    "ended_at": event_iso,
                    "duration_seconds": _seconds_between(open_period.get("started_at"), event_iso),
                }
            )
            metrics["open_unavailable"] = None

    async def _async_finalize(self, now: datetime) -> None:
        if self.state.get("status") != "running":
            return
        planned_end = _parse(self.state.get("planned_end_at"))
        effective_end = planned_end if planned_end is not None and now >= planned_end else now
        end_iso = _iso(effective_end)
        for signal in self.state.get("signals", {}).values():
            metrics = signal.get("metrics") if isinstance(signal, dict) else None
            if isinstance(metrics, dict) and isinstance(metrics.get("open_unavailable"), dict):
                open_period = metrics["open_unavailable"]
                metrics.setdefault("unavailable_periods", []).append(
                    {
                        **open_period,
                        "ended_at": end_iso,
                        "duration_seconds": _seconds_between(open_period.get("started_at"), end_iso),
                        "open_at_end": True,
                    }
                )
                metrics["open_unavailable"] = None
        self._unsubscribe_events()
        self._cancel_timers()
        self.state["completed_at"] = end_iso
        self.state["last_checkpoint_at"] = _iso(now)
        self.state["status"] = (
            "completed_with_runtime_gap" if self.state.get("runtime_gaps") else "completed"
        )
        await self.store.async_save(self.state)

    async def async_stop(self) -> dict[str, Any]:
        if self.state.get("status") != "running":
            return await self.async_state()
        now = _utcnow()
        self._unsubscribe_events()
        self._cancel_timers()
        self.state["status"] = "cancelled"
        self.state["completed_at"] = _iso(now)
        self.state["last_checkpoint_at"] = _iso(now)
        await self.store.async_save(self.state)
        return await self.async_state()

    async def async_cleanup(self) -> dict[str, Any]:
        if self.state.get("status") == "running":
            raise ValueError("audit_running")
        self._unsubscribe_events()
        self._cancel_timers()
        self.state = self._empty_state()
        remover = getattr(self.store, "async_remove", None)
        if remover is not None:
            await remover()
        else:
            await self.store.async_save(self.state)
        return await self.async_state()

    async def async_shutdown(self) -> None:
        if self.state.get("status") == "running":
            self.state["last_checkpoint_at"] = _iso(_utcnow())
            await self.store.async_save(self.state)
        self._unsubscribe_events()
        self._cancel_timers()

    def _signal_public_state(self, signal: dict[str, Any], end_at: str) -> dict[str, Any]:
        metrics = signal.get("metrics", {}) if isinstance(signal, dict) else {}
        periods = deepcopy(metrics.get("unavailable_periods", []))
        open_period = metrics.get("open_unavailable")
        if isinstance(open_period, dict):
            periods.append(
                {
                    **deepcopy(open_period),
                    "ended_at": end_at,
                    "duration_seconds": _seconds_between(open_period.get("started_at"), end_at),
                    "open_at_export": True,
                }
            )
        unavailable_seconds = sum(
            float(period.get("duration_seconds") or 0)
            for period in periods
            if isinstance(period, dict)
        )
        return {
            "signal_id": signal.get("signal_id"),
            "logical_role": signal.get("logical_role"),
            "source_generation_id": signal.get("source_generation_id"),
            "entity_id": signal.get("entity_id"),
            "source_identity": deepcopy(signal.get("source_identity", {})),
            "report_count": int(metrics.get("report_count", 0)),
            "state_reported_count": int(metrics.get("state_reported_count", 0)),
            "state_changed_count": int(metrics.get("state_changed_count", 0)),
            "state_value_change_count": int(metrics.get("state_value_change_count", 0)),
            "same_value_report_count": int(metrics.get("same_value_report_count", 0)),
            "cadence": {
                "observed_event_gap_seconds": _distribution(metrics.get("event_gaps_seconds", [])),
                "classification": "observed_source_generation_only",
                "universal_cadence_assumed": False,
            },
            "timestamp_basis": {
                "last_reported": metrics.get("last_reported"),
                "last_updated": metrics.get("last_updated"),
                "last_changed": metrics.get("last_changed"),
                "event_minus_last_reported": _distribution(metrics.get("event_minus_last_reported_seconds", [])),
                "event_minus_last_updated": _distribution(metrics.get("event_minus_last_updated_seconds", [])),
                "event_minus_last_changed": _distribution(metrics.get("event_minus_last_changed_seconds", [])),
            },
            "unavailable": {
                "period_count": len(periods),
                "duration_seconds": unavailable_seconds,
                "periods": periods,
            },
            "stale": {
                "status": "not_classified",
                "stale_after_seconds": None,
                "reason": "No universal stale threshold is assumed; this audit measures the current source generation.",
            },
        }

    async def async_state(self) -> dict[str, Any]:
        now = _utcnow()
        planned_end = _parse(self.state.get("planned_end_at"))
        if self.state.get("status") == "running" and planned_end is not None and now >= planned_end:
            await self._async_finalize(now)
        end_at = self.state.get("completed_at") or _iso(now)
        started = _parse(self.state.get("started_at"))
        effective_end = _parse(end_at)
        observed_seconds = (
            max(0.0, (effective_end - started).total_seconds())
            if started is not None and effective_end is not None
            else 0.0
        )
        remaining_seconds = (
            max(0.0, (planned_end - now).total_seconds())
            if self.state.get("status") == "running" and planned_end is not None
            else 0.0
        )
        runtime_gap_seconds = sum(
            float(item.get("duration_seconds") or 0)
            for item in self.state.get("runtime_gaps", [])
            if isinstance(item, dict)
        )
        signals = [
            self._signal_public_state(signal, end_at)
            for signal in self.state.get("signals", {}).values()
            if isinstance(signal, dict)
        ]
        return {
            "success": True,
            "status": self.state.get("status", "idle"),
            "audit_id": self.state.get("audit_id"),
            "site_id": self.state.get("site_id"),
            "site_name": self.state.get("site_name"),
            "started_at": self.state.get("started_at"),
            "planned_end_at": self.state.get("planned_end_at"),
            "completed_at": self.state.get("completed_at"),
            "remaining_seconds": remaining_seconds,
            "observed_window_seconds": observed_seconds,
            "minimum_24h_window_met": observed_seconds >= AUDIT_DURATION.total_seconds(),
            "restart_count": int(self.state.get("restart_count", 0)),
            "runtime_gap_seconds": runtime_gap_seconds,
            "runtime_gaps": deepcopy(self.state.get("runtime_gaps", [])),
            "network_reconnects": {
                "applicable": False,
                "reason": "Collector runs in-process on the Home Assistant event bus.",
            },
            "missing_roles": list(self.state.get("missing_roles", [])),
            "signals": signals,
            "scope": deepcopy(self.state.get("scope", {})),
            "temporary_store": {
                "key": STORE_KEY,
                "permanent_model_data": False,
                "cleanup_supported": True,
            },
        }


def _audit_manager(hass) -> CadenceAuditManager | None:
    manager = hass.data.get(DOMAIN, {}).get("cadence_audit_manager")
    return manager if isinstance(manager, CadenceAuditManager) else None


def async_register_cadence_audit_websocket(hass) -> None:
    """Register the isolated cadence-audit control plane once."""
    key = f"{DOMAIN}_cadence_audit_websocket_registered"
    if hass.data.get(key):
        return
    websocket_api.async_register_command(hass, websocket_cadence_audit_state)
    websocket_api.async_register_command(hass, websocket_cadence_audit_start)
    websocket_api.async_register_command(hass, websocket_cadence_audit_stop)
    websocket_api.async_register_command(hass, websocket_cadence_audit_cleanup)
    hass.data[key] = True


@websocket_api.websocket_command({vol.Required("type"): STATE_COMMAND})
@websocket_api.async_response
async def websocket_cadence_audit_state(hass, connection, msg):
    manager = _audit_manager(hass)
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "cadence_audit_unavailable"})
        return
    connection.send_result(msg["id"], await manager.async_state())


@websocket_api.websocket_command({vol.Required("type"): START_COMMAND})
@websocket_api.async_response
async def websocket_cadence_audit_start(hass, connection, msg):
    manager = _audit_manager(hass)
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "cadence_audit_unavailable"})
        return
    try:
        result = await manager.async_start()
    except ValueError as err:
        connection.send_result(msg["id"], {"success": False, "error": str(err)})
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({vol.Required("type"): STOP_COMMAND})
@websocket_api.async_response
async def websocket_cadence_audit_stop(hass, connection, msg):
    manager = _audit_manager(hass)
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "cadence_audit_unavailable"})
        return
    connection.send_result(msg["id"], await manager.async_stop())


@websocket_api.websocket_command({vol.Required("type"): CLEANUP_COMMAND})
@websocket_api.async_response
async def websocket_cadence_audit_cleanup(hass, connection, msg):
    manager = _audit_manager(hass)
    if manager is None:
        connection.send_result(msg["id"], {"success": False, "error": "cadence_audit_unavailable"})
        return
    try:
        result = await manager.async_cleanup()
    except ValueError as err:
        connection.send_result(msg["id"], {"success": False, "error": str(err)})
        return
    connection.send_result(msg["id"], result)
