"""Persistent, site-scoped individual-load configuration for ELLA."""

from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any, Callable

from homeassistant.helpers.storage import Store


SCHEMA = "ella_load_registry.v1"
STORE_VERSION = 1
STORE_KEY = "elrakning.ella_load_registry"
ENTITY_ID_RE = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z0-9_]+$")
LOAD_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
CRITICALITIES = frozenset({"critical", "high", "normal", "low", "unknown"})
FLEXIBILITIES = frozenset({"fixed", "reducible", "shiftable", "interruptible"})
CONTROL_MODES = frozenset({"observe_only", "recommend_only", "controllable"})


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _iso(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid_{field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"invalid_{field}") from None
    if parsed.tzinfo is None:
        raise ValueError(f"invalid_{field}")
    return parsed.isoformat()


def _entity(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not ENTITY_ID_RE.fullmatch(value):
        raise ValueError(f"invalid_{field}")
    return value


def normalize_load(payload: Any, site_id: str, *, now: str, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate and normalize one load without discovering or touching entities."""
    if not isinstance(payload, dict):
        raise ValueError("invalid_load")
    load_id = payload.get("load_id")
    if not isinstance(load_id, str) or not LOAD_ID_RE.fullmatch(load_id):
        raise ValueError("invalid_load_id")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("invalid_load_name")
    if not isinstance(site_id, str) or not site_id.strip():
        raise ValueError("invalid_site_id")
    criticality = payload.get("criticality", "unknown")
    flexibility = payload.get("flexibility", "fixed")
    control_mode = payload.get("control_mode", "observe_only")
    if criticality not in CRITICALITIES:
        raise ValueError("invalid_criticality")
    if flexibility not in FLEXIBILITIES:
        raise ValueError("invalid_flexibility")
    if control_mode not in CONTROL_MODES:
        raise ValueError("invalid_control_mode")
    enabled = payload.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("invalid_enabled")
    priority = payload.get("priority")
    if priority is not None and (isinstance(priority, bool) or not isinstance(priority, int)):
        raise ValueError("invalid_priority")
    nominal = payload.get("nominal_power_w")
    energy = payload.get("energy_need_kwh")
    if nominal is not None and (isinstance(nominal, bool) or not isinstance(nominal, (int, float)) or nominal < 0):
        raise ValueError("invalid_nominal_power_w")
    if energy is not None and (isinstance(energy, bool) or not isinstance(energy, (int, float)) or energy < 0):
        raise ValueError("invalid_energy_need_kwh")
    windows = payload.get("allowed_windows")
    if windows is not None and not isinstance(windows, list):
        raise ValueError("invalid_allowed_windows")
    constraints = payload.get("constraints", {})
    if not isinstance(constraints, dict):
        raise ValueError("invalid_constraints")
    result = {
        "load_id": load_id,
        "name": name.strip(),
        "site_id": site_id,
        "enabled": enabled,
        "measurement": _entity(payload.get("measurement"), "measurement"),
        "actuator": _entity(payload.get("actuator"), "actuator"),
        "criticality": criticality,
        "flexibility": flexibility,
        "control_mode": control_mode,
        "nominal_power_w": nominal,
        "energy_need_kwh": energy,
        "ready_by": _iso(payload.get("ready_by"), "ready_by"),
        "deadline": _iso(payload.get("deadline"), "deadline"),
        "allowed_windows": _copy(windows) if windows is not None else None,
        "min_runtime_minutes": payload.get("min_runtime_minutes"),
        "min_off_minutes": payload.get("min_off_minutes"),
        "constraints": _copy(constraints),
        "priority": priority,
        "provenance": _copy(payload.get("provenance", {"origin": "explicit_site_config"})),
        "configured_at": (existing or {}).get("configured_at", now),
        "updated_at": now,
    }
    for field in ("min_runtime_minutes", "min_off_minutes"):
        value = result[field]
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise ValueError(f"invalid_{field}")
    return result


class EllaLoadRegistry:
    """Own only persistent load metadata; this class has no execution methods."""

    def __init__(self, hass, now_fn: Callable[[], str]) -> None:
        self.store = Store(hass, STORE_VERSION, STORE_KEY)
        self.now_fn = now_fn
        self.state: dict[str, Any] = {"schema": SCHEMA, "version": 1, "sites": {}}

    async def async_load(self) -> None:
        cached = await self.store.async_load()
        if isinstance(cached, dict) and cached.get("schema") == SCHEMA and isinstance(cached.get("sites"), dict):
            self.state = {"schema": SCHEMA, "version": 1, "sites": _copy(cached["sites"])}

    def list_for_site(self, site_id: str) -> list[dict[str, Any]]:
        rows = self.state.get("sites", {}).get(site_id, [])
        return sorted((_copy(row) for row in rows if isinstance(row, dict)), key=lambda row: row["load_id"])

    async def async_upsert(self, site_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        rows = self.state.setdefault("sites", {}).setdefault(site_id, [])
        existing = next((row for row in rows if row.get("load_id") == payload.get("load_id")), None)
        normalized = normalize_load(payload, site_id, now=self.now_fn(), existing=existing)
        if existing is None:
            rows.append(normalized)
        else:
            rows[rows.index(existing)] = normalized
        rows.sort(key=lambda row: row["load_id"])
        await self.store.async_save(self.state)
        return _copy(normalized)

    async def async_remove(self, site_id: str, load_id: str) -> bool:
        rows = self.state.setdefault("sites", {}).setdefault(site_id, [])
        before = len(rows)
        self.state["sites"][site_id] = [row for row in rows if row.get("load_id") != load_id]
        if len(self.state["sites"][site_id]) == before:
            return False
        await self.store.async_save(self.state)
        return True
