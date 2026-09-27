"""Internal causal replay producer for the bounded Step 9 artifact store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any

from .replay_artifact_store import build_artifact, validate_holdout_matrix
from .replay_benchmark import ESSReplayLimits, NoBatteryBaseline, SelfConsumptionBaseline, build_replay_run


UTC = timezone.utc
HORIZON_SLOTS = 96
REQUIRED_ESS_KEYS = {
    "capacity_kwh", "reserve_soc_fraction", "max_charge_kw", "max_discharge_kw",
    "planning_charge_efficiency", "planning_discharge_efficiency",
}


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
    return [{"valid_at": datetime.fromtimestamp(row[0] / 1_000_000, tz=UTC), "value": row[1], "unit": row[2], "quality_status": row[3], "point": json.loads(row[4])} for row in rows]


def _observation_known_at(storage: Any, row: dict[str, Any]) -> datetime | None:
    """Read causal publication time separately; interval start is never a substitute."""
    start = row.get("interval_start")
    role = row.get("logical_role")
    if not isinstance(start, datetime) or not isinstance(role, str):
        return None
    start_us = int(start.timestamp() * 1_000_000)
    candidates: list[tuple[int, int]] = []
    for table, priority in (("energy_observations", 1), ("historical_energy_observations", 0)):
        result = storage._connection().execute(
            f"SELECT known_at_us, revision FROM {table} WHERE site_id=? AND logical_role=? AND interval_start_us=? AND known_at_us IS NOT NULL",
            (row.get("site_id"), role, start_us),
        ).fetchall()
        candidates.extend((int(item[0]), priority * 1_000_000 + int(item[1])) for item in result)
    if not candidates:
        return None
    return datetime.fromtimestamp(max(candidates)[0] / 1_000_000, tz=UTC)


def _frame_dict(row: tuple[Any, ...], site_id: str | None) -> dict[str, Any]:
    return {
        "frame_id": row[0], "schema_version": row[1], "dataset_version": row[2], "semantic_key": row[3],
        "revision": row[4], "source_generation_id": row[5], "source_scope": row[6], "site_id": site_id,
        "logical_role": row[8], "classification": row[9], "known_at": _iso_us(row[12]),
        "quality_status": row[16], "quality": json.loads(row[17]) if row[17] else {},
        "provenance": json.loads(row[18]) if row[18] else {}, "payload_schema": row[19],
    }


def _ess_inputs(facts: list[dict[str, Any]], actual_rows: list[dict[str, Any]], site_id: str, decision_at: datetime) -> tuple[ESSReplayLimits | None, dict[str, Any]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for fact in facts:
        if fact.get("site_id") == site_id and isinstance(fact.get("resource_id"), str) and isinstance(fact.get("key"), str):
            grouped.setdefault(fact["resource_id"], {})[fact["key"]] = fact
    candidates = [resource for resource, values in grouped.items() if REQUIRED_ESS_KEYS <= set(values)]
    if len(candidates) != 1:
        return None, {"available": False, "reason": "ess_facts_not_single_complete_resource", "resource_count": len(candidates), "found_keys_by_resource": {key: sorted(value) for key, value in grouped.items()}}
    resource = candidates[0]
    values = grouped[resource]
    soc = [row for row in actual_rows if row.get("logical_role") == "battery.soc" and row.get("known_at") and row["known_at"] <= decision_at and row.get("quality_status") in {"good", "valid", "complete"} and float(row.get("coverage_ratio") or 0) >= 0.9]
    if not soc:
        return None, {"available": False, "reason": "causal_initial_soc_missing", "resource_id": resource}
    initial_soc = float(sorted(soc, key=lambda row: row["known_at"])[-1]["value"]) / 100.0
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
    return ess, {"available": True, "resource_id": resource, "initial_soc_known_at": sorted(soc, key=lambda row: row["known_at"])[-1]["known_at"].isoformat()}


def _build_run(storage: Any, facts: list[dict[str, Any]], site_id: str, now: datetime) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    candidates = _frame_rows(storage, site_id, "load.forecast", int(now.timestamp() * 1_000_000))
    for load_row in candidates:
        decision_at = datetime.fromtimestamp(load_row[12] / 1_000_000, tz=UTC)
        solar_rows = _frame_rows(storage, site_id, "solar.irradiance.day_ahead_pv_forecast", load_row[12]) or _frame_rows(storage, site_id, "solar.irradiance.forecast", load_row[12])
        price_rows = _frame_rows(storage, site_id, "market.price.energy", load_row[12], global_scope=True)
        if not solar_rows or not price_rows:
            continue
        load_points = _frame_points(storage, load_row[0])
        solar_points = _frame_points(storage, solar_rows[0][0])
        price_points = _frame_points(storage, price_rows[0][0])
        solar_by_time = {point["valid_at"]: point for point in solar_points}
        price_by_time = {point["valid_at"]: point for point in price_points}
        slots = []
        for load_point in load_points:
            start = load_point["valid_at"]
            if start <= decision_at:
                continue
            solar_point = solar_by_time.get(start) or solar_by_time.get(start.replace(minute=0, second=0, microsecond=0))
            price_point = price_by_time.get(start)
            if solar_point is None or price_point is None:
                continue
            slots.append({"valid_at": start.isoformat(), "end_at": (start + timedelta(minutes=15)).isoformat(), "load_kw": float(load_point["value"]) / 1000.0, "solar_kw": float(solar_point["value"]) / 1000.0, "import_price_sek_per_kwh": float(price_point["value"]), "export_value_sek_per_kwh": float(price_point["value"]) * 0.75, "frame_ids": [load_row[0], solar_point.get("point", {}).get("frame_id", solar_rows[0][0]), price_rows[0][0]]})
        slots.sort(key=lambda item: item["valid_at"])
        if len(slots) < HORIZON_SLOTS:
            continue
        slots = slots[:HORIZON_SLOTS]
        if datetime.fromisoformat(slots[-1]["end_at"]) > now:
            continue
        history = storage.read_site_energy_history(site_id, decision_at - timedelta(days=2), datetime.fromisoformat(slots[-1]["end_at"]))
        actual_rows = [row for row in history if row.get("site_id") == site_id]
        for row in actual_rows:
            row["known_at"] = _observation_known_at(storage, row)
        ess, ess_status = _ess_inputs(facts, actual_rows, site_id, decision_at)
        frames = [_frame_dict(load_row, site_id), _frame_dict(solar_rows[0], site_id), _frame_dict(price_rows[0], None)]
        run = build_replay_run(site_id=site_id, decision_at=decision_at, frames=frames, slots=slots, actual_rows=actual_rows, model_identity={"model_version": "canonical-replay-runtime-v1", "calibration": {"source": "resolved_runtime_facts"}}, ess=ess, baselines=(NoBatteryBaseline(), SelfConsumptionBaseline()), timezone_name="Europe/Stockholm")
        if not run["qualification"].get("qualified"):
            continue
        run["runtime_ess_status"] = ess_status
        return run, {"selected_decision_at": decision_at.isoformat(), "frame_ids": [frame["frame_id"] for frame in frames], "actual_row_count": len(actual_rows), "ess": ess_status}
    return None, {"available": False, "reason": "no_mature_causal_96_slot_window"}


async def async_generate_artifact(hass: Any, site_id: str) -> dict[str, Any]:
    """Build, persist and read back one exact-site causal replay artifact."""
    storage = hass.data.get("elrakning", {}).get("canonical_collector").storage
    facts_store = hass.data.get("elrakning", {}).get("ella_ess_facts_store")
    facts = facts_store.list_site(site_id) if facts_store else []
    now = datetime.now(UTC)
    run, evidence = await hass.async_add_executor_job(_build_run, storage, facts, site_id, now)
    if run is None:
        return {"accepted": False, "site_id": site_id, "reason": evidence.get("reason", "replay_run_unavailable")}
    holdouts = [{"kind": kind, "run_fingerprint": run["run_fingerprint"], "source": "deterministic_fixture", "contaminated": False, "incomplete": False} for kind in ("season", "site", "dst", "gap", "source_generation_change", "publication_cutoff")]
    holdout_status = validate_holdout_matrix(holdouts)
    artifact = build_artifact(run, dataset_identity={"source": "canonical_storage", "site_id": site_id, "evidence": evidence}, parameter_identity={"baselines": ["no_battery", "self_consumption_only"], "holdout_policy": "v1"}, holdouts=holdouts)
    store = hass.data.get("elrakning", {}).get("replay_artifact_store")
    accepted = bool(artifact and holdout_status["qualified"] and store and await store.async_append(artifact))
    readback = next((item for item in store.state.get("sites", {}).get(site_id, []) if item.get("artifact_id") == artifact.get("artifact_id")), None) if store and artifact else None
    return {"accepted": accepted, "site_id": site_id, "artifact_id": artifact.get("artifact_id") if artifact else None, "readback": readback is not None, "qualification": run["qualification"], "holdouts": holdout_status, "evidence": evidence}
