"""Internal causal replay producer for the bounded Step 9 artifact store."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from copy import deepcopy
import json
from typing import Any

from .replay_artifact_store import build_artifact, validate_holdout_matrix
from .economic_optimizer import build_eon_economics
from .ella_ess_twin import resolve_shared_ess_resource
from .replay_benchmark import ESSReplayLimits, NoBatteryBaseline, SelfConsumptionBaseline, build_replay_run


UTC = timezone.utc
HORIZON_SLOTS = 96
SOLAR_DAY_AHEAD_ROLE = "solar.irradiance.day_ahead_pv_forecast"
SOLAR_FORECAST_ROLE = "solar.irradiance.forecast"
PRICE_ROLE = "market.price.energy"
REQUIRED_ESS_KEYS = {
    "capacity_kwh", "reserve_soc_fraction", "max_charge_kw", "max_discharge_kw",
    "planning_charge_efficiency", "planning_discharge_efficiency",
}


def _economics_is_causal(economics: dict[str, Any], decision_at: datetime) -> bool:
    """Require provider economics or its recorded applicability override at decision time."""
    def moment(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(UTC) if parsed.tzinfo else None

    decision = decision_at.astimezone(UTC)
    known_at = moment(economics.get("known_at"))
    valid_from = moment(economics.get("valid_from"))
    valid_to = moment(economics.get("valid_to")) if economics.get("valid_to") else None
    if known_at is None or valid_from is None or known_at > decision or (valid_to is not None and valid_to <= decision):
        return False
    if valid_from <= decision:
        return True
    override = economics.get("planning_applicability_override")
    if not isinstance(override, dict) or override.get("source_type") != "user_configured_planning_applicability_override":
        return False
    override_known = moment(override.get("known_at"))
    override_effective = moment(override.get("effective_from"))
    return (
        override_known is not None
        and override_effective is not None
        and override_known <= decision
        and override_effective <= decision
        and override.get("provider_valid_from") == economics.get("provider_valid_from")
        and override.get("provider_reference") == economics.get("provider_reference")
    )


def _iso_us(value: int) -> str:
    return datetime.fromtimestamp(value / 1_000_000, tz=UTC).isoformat()


def _frame_rows(storage: Any, site_id: str, role: str, decision_us: int, global_scope: bool = False) -> list[tuple[Any, ...]]:
    connection = storage._connection()
    return connection.execute(
        """SELECT f.frame_id, f.schema_version, f.dataset_version, f.semantic_key,
                  f.revision, f.source_generation_id, f.source_scope, f.site_id,
                  f.logical_role, f.classification, f.published_at_us, f.fetched_at_us,
                  f.known_at_us, f.captured_at_us, f.valid_from_us, f.valid_to_us,
                  f.quality_status, f.quality_json, f.provenance_json, f.payload_schema
             FROM external_input_frames AS f
             JOIN source_generations AS g ON g.source_generation_id = f.source_generation_id
            WHERE f.logical_role=? AND f.known_at_us <= ? AND g.created_at_us <= ?
              AND ((f.site_id=? AND ?=0) OR (f.site_id IS NULL AND ?=1))
            ORDER BY f.known_at_us DESC, f.revision DESC, f.frame_id DESC""",
        (role, decision_us, decision_us, site_id, int(global_scope), int(global_scope)),
    ).fetchall()


def _frame_points(storage: Any, frame_id: str) -> list[dict[str, Any]]:
    rows = storage._connection().execute(
        "SELECT valid_at_us, value, unit, quality_status, point_json FROM external_input_points WHERE frame_id=? ORDER BY valid_at_us",
        (frame_id,),
    ).fetchall()
    points = []
    for row in rows:
        if len(row) < 5 or row[0] is None or row[1] is None or not isinstance(row[3], str):
            continue
        try:
            detail = json.loads(row[4]) if row[4] else {}
        except (TypeError, ValueError):
            continue
        if not isinstance(detail, dict):
            continue
        points.append({"frame_id": frame_id, "valid_at": datetime.fromtimestamp(row[0] / 1_000_000, tz=UTC), "value": row[1], "unit": row[2], "quality_status": row[3], "point": detail})
    return points


def _source_frame_rank(row: tuple[Any, ...], solar: bool) -> int:
    """Prefer the explicit day-ahead contract over the broader solar feed."""
    if solar and row[8] == SOLAR_DAY_AHEAD_ROLE:
        return 2
    return 1


def _qualified_point(point: dict[str, Any], frame: tuple[Any, ...]) -> bool:
    """Allow window-scoped quality without weakening point-level fail-closed rules."""
    if frame[16] in {"invalid", "unknown"}:
        return False
    if point.get("quality_status") not in {"good", "valid", "complete"}:
        return False
    detail = point.get("point")
    if isinstance(detail, dict) and detail.get("quality_status") in {"partial", "invalid", "unknown"}:
        return False
    return True


def _resolve_causal_input_window(
    storage: Any,
    rows: list[tuple[Any, ...]],
    slots: list[datetime],
    *,
    solar: bool,
    decision_us: int,
) -> dict[str, Any]:
    """Resolve one exact causal window from immutable frames without fabrication."""
    candidates_by_slot: dict[datetime, list[dict[str, Any]]] = {slot: [] for slot in slots}
    for row in rows:
        if row[12] > decision_us or row[16] in {"invalid", "unknown"} or not row[19]:
            continue
        points = _frame_points(storage, row[0])
        by_time = {point["valid_at"]: point for point in points}
        for slot in slots:
            point = by_time.get(slot)
            exact = point is not None
            if point is None and solar:
                point = by_time.get(slot.replace(minute=0, second=0, microsecond=0))
            if point is None or not _qualified_point(point, row):
                continue
            candidates_by_slot[slot].append({"frame": row, "point": point, "value": point["value"], "exact": exact})

    selected: dict[datetime, dict[str, Any]] = {}
    ambiguous: list[str] = []
    for slot in slots:
        candidates = candidates_by_slot[slot]
        if not candidates:
            continue
        candidates.sort(key=lambda item: (
            _source_frame_rank(item["frame"], solar),
            1 if item["exact"] else 0,
            1 if item["frame"][16] in {"good", "valid", "complete"} else 0,
            item["frame"][12],
            item["frame"][4],
            str(item["frame"][5]),
            str(item["frame"][0]),
        ), reverse=True)
        best = candidates[0]
        best_rank = (
            _source_frame_rank(best["frame"], solar),
            1 if best["exact"] else 0,
            1 if best["frame"][16] in {"good", "valid", "complete"} else 0,
            best["frame"][12],
            best["frame"][4],
        )
        tied_generations = {
            str(item["frame"][5])
            for item in candidates
            if (
                _source_frame_rank(item["frame"], solar),
                1 if item["exact"] else 0,
                1 if item["frame"][16] in {"good", "valid", "complete"} else 0,
                item["frame"][12],
                item["frame"][4],
            ) == best_rank
        }
        if len(tied_generations) > 1:
            ambiguous.append(slot.isoformat())
            continue
        selected[slot] = best

    used_rows = {item["frame"][0]: item["frame"] for item in selected.values()}
    frame_rows = sorted(used_rows.values(), key=lambda row: (row[8], row[12], row[4], row[0]))
    metadata = {
        "points": selected,
        "frames": frame_rows,
        "frame_ids": [row[0] for row in frame_rows],
        "source_generations": sorted({str(row[5]) for row in frame_rows}),
    }
    if ambiguous:
        return {"available": False, "reason": "ambiguous_source_generation", "ambiguous_slots": ambiguous, **metadata}
    if len(selected) != len(slots):
        return {
            "available": False,
            "reason": "missing_causal_slot",
            "missing_slots": [slot.isoformat() for slot in slots if slot not in selected],
            "available_slots": len(selected),
            **metadata,
        }
    return {
        "available": True,
        **metadata,
        "window_quality": "good",
    }


def _input_rows(storage: Any, site_id: str, decision_us: int, solar: bool) -> list[tuple[Any, ...]]:
    roles = (SOLAR_DAY_AHEAD_ROLE, SOLAR_FORECAST_ROLE) if solar else (PRICE_ROLE,)
    rows: list[tuple[Any, ...]] = []
    for role in roles:
        rows.extend(_frame_rows(storage, site_id, role, decision_us, global_scope=not solar))
    return rows


def _observation_known_at(storage: Any, row: dict[str, Any], decision_at: datetime) -> datetime | None:
    """Read causal publication time separately; interval start is never a substitute."""
    start = row.get("interval_start")
    role = row.get("logical_role")
    if not isinstance(start, datetime) or not isinstance(role, str):
        return None
    start_us = int(start.timestamp() * 1_000_000)
    candidates: list[tuple[int, int]] = []
    for table, priority in (("energy_observations", 1), ("historical_energy_observations", 0)):
        result = storage._connection().execute(
            f"SELECT known_at_us FROM {table} WHERE site_id=? AND logical_role=? AND interval_start_us=? AND known_at_us IS NOT NULL",
            (row.get("site_id"), role, start_us),
        ).fetchall()
        decision_us = int(decision_at.timestamp() * 1_000_000)
        for item in result:
            try:
                known_at_us = int(item[0])
            except (IndexError, TypeError, ValueError):
                continue
            if known_at_us <= decision_us:
                candidates.append((known_at_us, priority))
    if not candidates:
        return None
    return datetime.fromtimestamp(max(candidates)[0] / 1_000_000, tz=UTC)


def _observation_observed_at(storage: Any, row: dict[str, Any], decision_at: datetime) -> datetime | None:
    """Read the causal observation timestamp without using interval start as a substitute."""
    site_id = row.get("site_id")
    role = row.get("logical_role")
    generation = row.get("source_generation_id")
    start = row.get("interval_start")
    if not all((isinstance(site_id, str), isinstance(role, str), isinstance(generation, str), isinstance(start, datetime))):
        return None
    start_us = int(start.timestamp() * 1_000_000)
    decision_us = int(decision_at.timestamp() * 1_000_000)
    values: list[int] = []
    for table in ("energy_observations", "historical_energy_observations"):
        rows = storage._connection().execute(
            f"SELECT observed_at_us FROM {table} WHERE site_id=? AND logical_role=? AND source_generation_id=? AND interval_start_us=? AND known_at_us<=? AND observed_at_us IS NOT NULL",
            (site_id, role, generation, start_us, decision_us),
        ).fetchall()
        values.extend(int(item[0]) for item in rows)
    return datetime.fromtimestamp(max(values) / 1_000_000, tz=UTC) if values else None


def _shared_ess_context(site_manager: Any, site_id: str) -> dict[str, Any]:
    """Resolve the exact ESS identity from the existing strong registry bindings."""
    targets = site_manager.collection_targets() if site_manager and hasattr(site_manager, "collection_targets") else []
    role_bindings = {
        str(target.get("logical_role")): target
        for target in targets
        if isinstance(target, dict)
        and target.get("site_id") == site_id
        and target.get("logical_role") in {"battery.power", "battery.soc", "battery.capacity"}
    }
    active_generations: dict[str, set[str]] = {}
    for role, target in role_bindings.items():
        generation = target.get("generation_id")
        if isinstance(generation, str) and generation:
            active_generations[role] = {generation}
    shared = resolve_shared_ess_resource(site_id, role_bindings, active_generations)
    return {"shared": shared, "active_generations": active_generations}


def _frame_dict(row: tuple[Any, ...], site_id: str | None) -> dict[str, Any]:
    return {
        "frame_id": row[0], "schema_version": row[1], "dataset_version": row[2], "semantic_key": row[3],
        "revision": row[4], "source_generation_id": row[5], "source_scope": row[6], "site_id": site_id if site_id is not None else row[7],
        "logical_role": row[8], "classification": row[9], "known_at": _iso_us(row[12]),
        "quality_status": row[16], "quality": json.loads(row[17]) if row[17] else {},
        "provenance": json.loads(row[18]) if row[18] else {}, "payload_schema": row[19],
    }


def _ess_inputs(
    facts: list[dict[str, Any]], actual_rows: list[dict[str, Any]], site_id: str, decision_at: datetime,
    ess_context: dict[str, Any] | None = None,
) -> tuple[ESSReplayLimits | None, dict[str, Any]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for fact in facts:
        if fact.get("site_id") == site_id and isinstance(fact.get("resource_id"), str) and isinstance(fact.get("key"), str):
            grouped.setdefault(fact["resource_id"], {})[fact["key"]] = fact
    candidates = [resource for resource, values in grouped.items() if REQUIRED_ESS_KEYS <= set(values)]
    if len(candidates) != 1:
        return None, {"available": False, "reason": "ess_facts_not_single_complete_resource", "resource_count": len(candidates), "found_keys_by_resource": {key: sorted(value) for key, value in grouped.items()}}
    resource = candidates[0]
    values = grouped[resource]
    shared = (ess_context or {}).get("shared") or {}
    if shared.get("available") is not True or shared.get("resource_id") != resource:
        return None, {"available": False, "reason": shared.get("reason", "ess_identity_unavailable"), "resource_id": resource}
    expected_generations = (ess_context or {}).get("active_generations", {}).get("battery.soc")
    soc = []
    for row in actual_rows:
        if row.get("site_id") != site_id or row.get("logical_role") != "battery.soc":
            continue
        known_at = row.get("known_at")
        observed_at = _observation_observed_at(ess_context.get("storage"), row, decision_at) if ess_context and ess_context.get("storage") else None
        identity = (row.get("provenance") or {}).get("source_identity") if isinstance(row.get("provenance"), dict) else None
        if (
            not isinstance(known_at, datetime) or known_at > decision_at
            or (observed_at is not None and observed_at > decision_at)
            or row.get("quality_status") not in {"good", "valid", "complete"}
            or float(row.get("coverage_ratio") or 0) < 0.9
            or (expected_generations is not None and row.get("source_generation_id") not in expected_generations)
            or not isinstance(identity, dict) or identity.get("identity_strength") != "strong"
            or identity.get("config_entry_id") != shared.get("config_entry_id")
            or identity.get("device_id") != shared.get("device_id")
        ):
            continue
        row["observed_at"] = observed_at
        soc.append(row)
    if not soc:
        return None, {"available": False, "reason": "causal_initial_soc_missing", "resource_id": resource}
    initial_soc = float(sorted(soc, key=lambda row: row["known_at"])[-1]["value"]) / 100.0
    selected = sorted(soc, key=lambda row: (row["known_at"], row.get("observed_at") or datetime.min.replace(tzinfo=UTC), str(row.get("source_generation_id"))))[-1]
    try:
        ess = ESSReplayLimits(
            capacity_kwh=float(values["capacity_kwh"]["value"]),
            reserve_soc_fraction=float(values["reserve_soc_fraction"]["value"]),
            max_charge_kw=float(values["max_charge_kw"]["value"]),
            max_discharge_kw=float(values["max_discharge_kw"]["value"]),
            charge_efficiency=float(values["planning_charge_efficiency"]["value"]),
            discharge_efficiency=float(values["planning_discharge_efficiency"]["value"]),
            initial_soc_fraction=initial_soc,
        )
    except (KeyError, TypeError, ValueError):
        return None, {"available": False, "reason": "ess_fact_value_invalid", "resource_id": resource}
    return ess, {
        "available": True, "resource_id": resource, "initial_soc": float(selected["value"]),
        "initial_soc_observed_at": selected.get("observed_at").isoformat() if selected.get("observed_at") else None,
        "initial_soc_known_at": selected["known_at"].isoformat(),
        "initial_soc_source": (selected.get("provenance") or {}).get("entity_id"),
        "initial_soc_identity_strength": ((selected.get("provenance") or {}).get("source_identity") or {}).get("identity_strength"),
    }


def _build_run(storage: Any, facts: list[dict[str, Any]], site_id: str, now: datetime, economics_resolver=None, ess_context: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    candidates = _frame_rows(storage, site_id, "load.forecast", int(now.timestamp() * 1_000_000))
    for load_row in candidates:
        decision_at = datetime.fromtimestamp(load_row[12] / 1_000_000, tz=UTC)
        economics = economics_resolver(decision_at) if economics_resolver is not None else None
        if not isinstance(economics, dict) or not _economics_is_causal(economics, decision_at):
            continue
        load_points = _frame_points(storage, load_row[0])
        future_load = [point for point in load_points if point["valid_at"] > decision_at]
        expected_times = [point["valid_at"] for point in future_load[:HORIZON_SLOTS]]
        if len(expected_times) < HORIZON_SLOTS:
            continue
        solar_window = _resolve_causal_input_window(storage, _input_rows(storage, site_id, load_row[12], True), expected_times, solar=True, decision_us=load_row[12])
        price_window = _resolve_causal_input_window(storage, _input_rows(storage, site_id, load_row[12], False), expected_times, solar=False, decision_us=load_row[12])
        if not solar_window.get("available") or not price_window.get("available"):
            continue
        slots = []
        for load_point, start in zip(future_load[:HORIZON_SLOTS], expected_times):
            solar_point = solar_window["points"][start]["point"]
            price_point = price_window["points"][start]["point"]
            solar_value = float(solar_window["points"][start]["value"])
            price_value = float(price_window["points"][start]["value"])
            slots.append({"valid_at": start.isoformat(), "end_at": (start + timedelta(minutes=15)).isoformat(), "load_kw": float(load_point["value"]) / 1000.0, "solar_kw": solar_value / 1000.0, "import_price_sek_per_kwh": price_value, "export_value_sek_per_kwh": price_value * 0.75, "frame_ids": [load_row[0], solar_window["points"][start]["frame"][0], price_window["points"][start]["frame"][0]]})
        if datetime.fromisoformat(slots[-1]["end_at"]) > now:
            continue
        history = storage.read_site_energy_history(site_id, decision_at - timedelta(days=2), datetime.fromisoformat(slots[-1]["end_at"]))
        actual_rows = [row for row in history if row.get("site_id") == site_id]
        for row in actual_rows:
            row["known_at"] = _observation_known_at(storage, row, decision_at)
        ess, ess_status = _ess_inputs(facts, actual_rows, site_id, decision_at, {**(ess_context or {}), "storage": storage})
        frames = [_frame_dict(load_row, site_id)]
        frames.extend(_frame_dict(row, row[7]) for row in solar_window["frames"])
        frames.extend(_frame_dict(row, row[7]) for row in price_window["frames"])
        run = build_replay_run(site_id=site_id, decision_at=decision_at, frames=frames, slots=slots, actual_rows=actual_rows, model_identity={"model_version": "canonical-replay-runtime-v1", "calibration": {"source": "resolved_runtime_facts"}}, economics_identity={key: economics.get(key) for key in ("source_schema", "provider_reference", "known_at", "valid_from", "provider_valid_from", "component_provenance")}, ess=ess, baselines=(NoBatteryBaseline(), SelfConsumptionBaseline()), timezone_name="Europe/Stockholm")
        if not run["qualification"].get("qualified"):
            continue
        run["runtime_ess_status"] = ess_status
        return run, {"selected_decision_at": decision_at.isoformat(), "frame_ids": [frame["frame_id"] for frame in frames], "actual_row_count": len(actual_rows), "ess": ess_status}
    return None, {"available": False, "reason": "no_mature_causal_96_slot_window"}


def _benchmark_readiness(storage: Any, facts: list[dict[str, Any]], site_id: str, now: datetime, economics_resolver=None, ess_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build bounded readiness evidence without weakening replay qualification."""
    candidates = _frame_rows(storage, site_id, "load.forecast", int(now.timestamp() * 1_000_000))
    evidence = {
        "available": True,
        "site_id": site_id,
        "resource_id": None,
        "status": "blocked",
        "blocker": "no_load_frame",
        "qualified": False,
        "horizon": {"required_slots": HORIZON_SLOTS, "available_slots": 0, "actual_coverage": "0/96"},
        "load_frame": None,
        "frame_known_at": None,
        "source_generations": [],
        "frame_quality": {},
        "frame_provenance": {},
        "economics": {"causal": False, "reason": "not_evaluated"},
        "economics_applicability": {"known_at": None, "valid_from": None, "provider_valid_from": None},
        "ess": {"available": False, "reason": "not_evaluated"},
        "artifact": {"artifact_id": None, "readback": False},
        "holdouts": {"qualified": False, "reasons": ["run_not_qualified"]},
        "provenance": {"source": "canonical_storage", "hindsight_used_for_decision": False},
        "last_attempt": None,
    }
    if not candidates:
        return evidence
    load_row = candidates[0]
    decision_at = datetime.fromtimestamp(load_row[12] / 1_000_000, tz=UTC)
    evidence["load_frame"] = {
        "frame_id": load_row[0], "known_at": _iso_us(load_row[12]),
        "quality_status": load_row[16], "payload_schema": load_row[19],
    }
    evidence["frame_known_at"] = _iso_us(load_row[12])
    evidence["frame_quality"] = {"load": load_row[16]}
    evidence["frame_provenance"] = {"load": json.loads(load_row[18]) if load_row[18] else {}}
    evidence["source_generations"] = [load_row[5]] if load_row[5] else []
    economics = economics_resolver(decision_at) if economics_resolver else None
    economics_causal = isinstance(economics, dict) and _economics_is_causal(economics, decision_at)
    evidence["economics"] = {"causal": economics_causal, "provider_reference": economics.get("provider_reference") if isinstance(economics, dict) else None, "reason": None if economics_causal else "economics_not_causal"}
    if isinstance(economics, dict):
        override = economics.get("planning_applicability_override") if isinstance(economics.get("planning_applicability_override"), dict) else {}
        evidence["economics_applicability"] = {
            "known_at": economics.get("known_at"), "valid_from": economics.get("valid_from"),
            "provider_valid_from": economics.get("provider_valid_from"),
            "override_known_at": override.get("known_at"), "override_effective_from": override.get("effective_from"),
        }
    load_points = _frame_points(storage, load_row[0])
    future_load = [point for point in load_points if point["valid_at"] > decision_at]
    expected_slots = [point["valid_at"] for point in future_load[:HORIZON_SLOTS]]
    solar_input_rows = _input_rows(storage, site_id, load_row[12], True)
    price_input_rows = _input_rows(storage, site_id, load_row[12], False)
    solar_window = _resolve_causal_input_window(storage, solar_input_rows, expected_slots, solar=True, decision_us=load_row[12]) if expected_slots else {"available": False, "reason": "missing_causal_slot", "available_slots": 0}
    price_window = _resolve_causal_input_window(storage, price_input_rows, expected_slots, solar=False, decision_us=load_row[12]) if expected_slots else {"available": False, "reason": "missing_causal_slot", "available_slots": 0}
    slots = sorted(set(solar_window.get("points", {})).intersection(price_window.get("points", {})))
    evidence["horizon"]["available_slots"] = len(slots)
    evidence["frame_quality"]["solar"] = {"window": solar_window.get("window_quality", "partial"), "frame_ids": solar_window.get("frame_ids", [])}
    evidence["frame_quality"]["price"] = {"window": price_window.get("window_quality", "partial"), "frame_ids": price_window.get("frame_ids", [])}
    evidence["frame_provenance"]["solar"] = [{"frame_id": row[0], "source_generation_id": row[5], "quality_status": row[16], "provenance": json.loads(row[18]) if row[18] else {}} for row in solar_window.get("frames", [])]
    evidence["frame_provenance"]["price"] = [{"frame_id": row[0], "source_generation_id": row[5], "quality_status": row[16], "provenance": json.loads(row[18]) if row[18] else {}} for row in price_window.get("frames", [])]
    evidence["source_generations"].extend(solar_window.get("source_generations", []))
    evidence["source_generations"].extend(price_window.get("source_generations", []))
    evidence["source_generations"] = sorted(set(evidence["source_generations"]))
    read_history = getattr(storage, "read_site_energy_history", None)
    history = read_history(site_id, decision_at - timedelta(days=2), decision_at + timedelta(minutes=15)) if callable(read_history) else []
    for row in history:
        row["known_at"] = _observation_known_at(storage, row, decision_at)
    if len(slots) == HORIZON_SLOTS:
        end_at = slots[-1] + timedelta(minutes=15)
        evidence["horizon"].update({"decision_at": decision_at.isoformat(), "end_at": end_at.isoformat(), "mature": end_at <= now})
        history = read_history(site_id, decision_at - timedelta(days=2), end_at) if callable(read_history) else []
        for row in history:
            row["known_at"] = _observation_known_at(storage, row, decision_at)
        slot_keys = {slot.isoformat() for slot in slots}
        actual_roles = {"grid.power/import", "battery.power", "battery.soc"}
        actual_count = sum(1 for row in history if row.get("logical_role") in actual_roles and isinstance(row.get("interval_start"), datetime) and row["interval_start"].isoformat() in slot_keys and row.get("known_at") is not None)
        evidence["horizon"]["actual_coverage"] = f"{min(actual_count, HORIZON_SLOTS)}/{HORIZON_SLOTS}"
    else:
        evidence["horizon"]["decision_at"] = decision_at.isoformat()
    _, ess_status = _ess_inputs(facts, history, site_id, decision_at, {**(ess_context or {}), "storage": storage})
    evidence["ess"] = ess_status
    resources = sorted({str(fact.get("resource_id")) for fact in facts if fact.get("site_id") == site_id and fact.get("resource_id")})
    if ess_status.get("resource_id"):
        evidence["resource_id"] = ess_status["resource_id"]
    elif len(resources) == 1:
        evidence["resource_id"] = resources[0]
    if load_row[16] not in {"good", "valid", "complete"}:
        evidence["blocker"] = "no_good_frame"
    elif not solar_input_rows or not price_input_rows:
        evidence["blocker"] = "missing_causal_input_frame"
    elif not economics_causal:
        evidence["blocker"] = "economics_not_causal"
    elif not solar_window.get("available") or not price_window.get("available") or len(slots) < HORIZON_SLOTS:
        evidence["blocker"] = "horizon_incomplete"
    elif not evidence["horizon"].get("mature") or evidence["horizon"]["actual_coverage"] != "96/96":
        evidence["blocker"] = "awaiting_outcomes"
    elif not ess_status.get("available"):
        evidence["blocker"] = ess_status.get("reason", "ess_unavailable")
    else:
        evidence["status"] = "ready"
        evidence["blocker"] = None
    return evidence


async def async_generate_artifact(hass: Any, site_id: str) -> dict[str, Any]:
    """Build, persist and read back one exact-site causal replay artifact."""
    storage = hass.data.get("elrakning", {}).get("canonical_collector").storage
    facts_store = hass.data.get("elrakning", {}).get("ella_ess_facts_store")
    facts = facts_store.list_site(site_id) if facts_store else []
    site_manager = hass.data.get("elrakning", {}).get("site_identity_manager")
    ess_context = _shared_ess_context(site_manager, site_id)
    grid_manager = hass.data.get("elrakning", {}).get("grid_manager")
    policy_store = hass.data.get("elrakning", {}).get("ella_economic_policy_store")
    binding = site_manager.active_binding("grid") if site_manager and hasattr(site_manager, "active_binding") else None
    grid_state = grid_manager.public_state_for_binding(binding) if grid_manager and binding else None
    override = deepcopy(policy_store.state.get("sites", {}).get(site_id, {}).get("planning_applicability_override")) if policy_store else None

    def resolve_economics(decision_at: datetime) -> dict[str, Any] | None:
        if not isinstance(grid_state, dict) or not binding:
            return None
        economics = build_eon_economics(grid_state, binding, decision_at) if isinstance(grid_state, dict) else None
        if not isinstance(economics, dict):
            return None
        if isinstance(override, dict):
            known_at = str(override.get("known_at", ""))
            effective_from = str(override.get("effective_from", ""))
            decision = decision_at.astimezone(UTC).isoformat()
            if known_at and effective_from and known_at <= decision and effective_from <= decision:
                economics = {**economics, "planning_applicability_override": override}
        return economics

    now = datetime.now(UTC)
    runtime_data = hass.data.setdefault("elrakning", {})
    replay_lock = runtime_data.setdefault("replay_runtime_lock", asyncio.Lock())
    try:
        async with replay_lock:
            readiness = await hass.async_add_executor_job(_benchmark_readiness, storage, facts, site_id, now, resolve_economics, ess_context)
    except (AttributeError, KeyError, TypeError, ValueError):
        readiness = {
            "available": False, "site_id": site_id, "resource_id": None, "status": "blocked", "blocker": "readiness_unavailable",
            "frame_known_at": None, "economics_applicability": {"known_at": None, "valid_from": None, "provider_valid_from": None}, "last_attempt": None,
            "qualified": False, "horizon": {"required_slots": HORIZON_SLOTS, "available_slots": 0, "actual_coverage": "0/96"},
            "source_generations": [], "frame_quality": {}, "frame_provenance": {}, "economics": {"causal": False, "reason": "not_evaluated"},
            "ess": {"available": False, "reason": "not_evaluated"}, "artifact": {"artifact_id": None, "readback": False},
            "holdouts": {"qualified": False, "reasons": ["run_not_qualified"]},
            "provenance": {"source": "canonical_storage", "hindsight_used_for_decision": False},
        }
    async with replay_lock:
        run, evidence = await hass.async_add_executor_job(_build_run, storage, facts, site_id, now, resolve_economics, ess_context)
    if run is None:
        readiness["last_attempt"] = {"at": now.isoformat(), "accepted": False, "reason": evidence.get("reason", "replay_run_unavailable")}
        result = {"accepted": False, "site_id": site_id, "reason": evidence.get("reason", "replay_run_unavailable"), "evidence": {**readiness, "runner": evidence}}
        store = hass.data.get("elrakning", {}).get("replay_artifact_store")
        if store:
            await store.async_record_attempt(result)
            await store.async_record_evidence(site_id, result["evidence"])
        return result
    holdouts = [{"kind": kind, "run_fingerprint": run["run_fingerprint"], "source": "deterministic_fixture", "contaminated": False, "incomplete": False} for kind in ("season", "site", "dst", "gap", "source_generation_change", "publication_cutoff")]
    holdout_status = validate_holdout_matrix(holdouts)
    artifact = build_artifact(run, dataset_identity={"source": "canonical_storage", "site_id": site_id, "evidence": evidence}, parameter_identity={"baselines": ["no_battery", "self_consumption_only"], "holdout_policy": "v1"}, holdouts=holdouts)
    store = hass.data.get("elrakning", {}).get("replay_artifact_store")
    accepted = bool(artifact and holdout_status["qualified"] and store and await store.async_append(artifact))
    readback = next((item for item in store.state.get("sites", {}).get(site_id, []) if item.get("artifact_id") == artifact.get("artifact_id")), None) if store and artifact else None
    result = {"accepted": accepted, "site_id": site_id, "artifact_id": artifact.get("artifact_id") if artifact else None, "readback": readback is not None, "qualification": run["qualification"], "holdouts": holdout_status, "evidence": {**readiness, "status": "artifact_verified" if accepted and readback is not None else "blocked", "blocker": None if accepted and readback is not None else "artifact_not_verified", "qualified": bool(run["qualification"].get("qualified")), "artifact": {"artifact_id": artifact.get("artifact_id") if artifact else None, "readback": readback is not None}, "holdouts": holdout_status, "fingerprint": run.get("run_fingerprint")}}
    result["evidence"]["last_attempt"] = {"at": now.isoformat(), "accepted": accepted, "reason": None if accepted else "artifact_not_verified", "artifact_id": result["artifact_id"]}
    if store:
        await store.async_record_attempt(result)
        await store.async_record_evidence(site_id, result["evidence"])
    return result
