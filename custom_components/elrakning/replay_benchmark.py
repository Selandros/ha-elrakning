"""Causal, site-scoped replay foundation for Step 9.

This module is deliberately pure: it reads caller-supplied immutable frames and
outcomes, performs no Home Assistant I/O, and exposes no execution path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Iterable, Protocol


SCHEMA = "ella_replay_benchmark.v1"
MODEL_VERSION = "causal-replay-foundation-v1"
UTC = timezone.utc
QUALIFIED_QUALITY = {"good", "valid", "complete"}
BAD_GAP_STATES = {"gap", "gapped", "missing", "stale", "ambiguous"}
SINGLETON_ROLES = {
    "house.consumption",
    "grid.power/import",
    "battery.power",
    "battery.soc",
}


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value.astimezone(UTC).isoformat()
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(UTC).isoformat() if parsed.tzinfo else None
    return None


def _moment(value: Any) -> datetime | None:
    normalized = _iso(value)
    if normalized is None:
        return None
    return datetime.fromisoformat(normalized)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _qualified(row: dict[str, Any]) -> bool:
    coverage = _number(row.get("coverage_ratio"))
    return (
        row.get("quality_status") in QUALIFIED_QUALITY
        and coverage is not None
        and coverage >= 0.9
        and row.get("gap_status") not in BAD_GAP_STATES
    )


def _frame_qualified(frame: dict[str, Any]) -> bool:
    return (
        frame.get("quality_status") in QUALIFIED_QUALITY
        and frame.get("gap_status") not in BAD_GAP_STATES
        and frame.get("status") not in BAD_GAP_STATES
    )


def select_causal_frames(
    frames: Iterable[dict[str, Any]],
    *,
    site_id: str,
    decision_at: datetime,
) -> dict[str, Any]:
    """Select the latest immutable frame revision visible at one decision time."""
    if not isinstance(site_id, str) or not site_id or decision_at.tzinfo is None:
        return {"available": False, "frames": [], "reasons": ["site_or_decision_time_missing"]}
    selected: dict[str, dict[str, Any]] = {}
    ambiguous: set[str] = set()
    future_count = 0
    wrong_site_count = 0
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        frame_site = frame.get("site_id")
        source_scope = frame.get("source_scope")
        if frame_site not in (site_id, None) or (frame_site is None and source_scope != "global"):
            wrong_site_count += 1
            continue
        known_at = _moment(frame.get("known_at"))
        if known_at is None:
            continue
        if known_at > decision_at.astimezone(UTC):
            future_count += 1
            continue
        semantic_key = frame.get("semantic_key") or frame.get("frame_id")
        if not isinstance(semantic_key, str) or not semantic_key:
            continue
        revision = int(frame.get("revision") or 0)
        candidate = selected.get(semantic_key)
        if candidate is not None:
            candidate_key = (_moment(candidate.get("known_at")), int(candidate.get("revision") or 0))
            current_key = (known_at, revision)
            if current_key == candidate_key and candidate.get("frame_id") != frame.get("frame_id"):
                ambiguous.add(semantic_key)
            if current_key <= candidate_key:
                continue
        selected[semantic_key] = frame
    for semantic_key in ambiguous:
        selected.pop(semantic_key, None)
    reasons: list[str] = []
    if ambiguous:
        reasons.append("ambiguous_frame_revision")
    return {
        "available": not ambiguous,
        "frames": [selected[key] for key in sorted(selected)],
        "reasons": reasons,
        "future_frame_count": future_count,
        "wrong_site_frame_count": wrong_site_count,
    }


def _frame_identity(frame: dict[str, Any]) -> dict[str, Any]:
    return {
        "frame_id": frame.get("frame_id"),
        "semantic_key": frame.get("semantic_key"),
        "revision": frame.get("revision"),
        "source_generation_id": frame.get("source_generation_id"),
        "schema_version": frame.get("schema_version"),
        "dataset_version": frame.get("dataset_version"),
        "known_at": _iso(frame.get("known_at")),
        "model_version": (frame.get("provenance") or {}).get("model_version"),
        "calibration_version": (frame.get("provenance") or {}).get("calibration_version"),
    }


@dataclass(frozen=True)
class ESSReplayLimits:
    """Verified physical values needed only by the self-consumption baseline."""

    capacity_kwh: float
    reserve_soc_fraction: float
    max_charge_kw: float
    max_discharge_kw: float
    charge_efficiency: float
    discharge_efficiency: float
    initial_soc_fraction: float


class ReplayBaseline(Protocol):
    name: str

    def simulate(self, slots: list[dict[str, Any]], ess: ESSReplayLimits | None) -> list[dict[str, Any]]:
        ...


class NoBatteryBaseline:
    """Counterfactual with no battery flow and canonical grid balance."""

    name = "no_battery"

    def simulate(self, slots: list[dict[str, Any]], ess: ESSReplayLimits | None = None) -> list[dict[str, Any]]:
        result = []
        for slot in slots:
            load = float(slot["load_kw"])
            solar = float(slot["solar_kw"])
            grid = load - solar
            result.append({
                "valid_at": slot["valid_at"],
                "battery_signed_kw": 0.0,
                "charge_kw": 0.0,
                "discharge_kw": 0.0,
                "grid_import_kw": max(0.0, grid),
                "grid_export_kw": max(0.0, -grid),
                "energy_kwh": None,
            })
        return result


class SelfConsumptionBaseline:
    """Deterministic PV-surplus charging and load-covering discharge baseline."""

    name = "self_consumption_only"

    def simulate(self, slots: list[dict[str, Any]], ess: ESSReplayLimits | None) -> list[dict[str, Any]]:
        if ess is None:
            raise ValueError("ess_limits_missing")
        energy = ess.initial_soc_fraction * ess.capacity_kwh
        result = []
        for slot in slots:
            load = float(slot["load_kw"])
            solar = float(slot["solar_kw"])
            dt_hours = float(slot.get("duration_hours", 0.25))
            surplus = solar - load
            charge = min(max(0.0, surplus), ess.max_charge_kw)
            available_charge = max(0.0, (ess.capacity_kwh - energy) / (dt_hours * ess.charge_efficiency))
            charge = min(charge, available_charge)
            deficit = max(0.0, -surplus)
            available_discharge = max(0.0, (energy - ess.reserve_soc_fraction * ess.capacity_kwh) * ess.discharge_efficiency / dt_hours)
            discharge = min(deficit, ess.max_discharge_kw, available_discharge)
            energy = energy + charge * dt_hours * ess.charge_efficiency - discharge * dt_hours / ess.discharge_efficiency
            grid = load - solar + charge - discharge
            result.append({
                "valid_at": slot["valid_at"],
                "battery_signed_kw": discharge - charge,
                "charge_kw": charge,
                "discharge_kw": discharge,
                "grid_import_kw": max(0.0, grid),
                "grid_export_kw": max(0.0, -grid),
                "energy_kwh": energy,
            })
        return result


def _simulate_battery_actions(slots: list[dict[str, Any]], ess: ESSReplayLimits | None, actions: dict[str, str]) -> list[dict[str, Any]]:
    if ess is None:
        raise ValueError("ess_limits_missing")
    energy = ess.initial_soc_fraction * ess.capacity_kwh
    result = []
    for slot in slots:
        dt_hours = float(slot.get("duration_hours", 0.25))
        action = actions.get(slot["valid_at"], "idle")
        charge = float(slot.get("charge_kw", 0.0)) if action == "charge" else 0.0
        discharge = float(slot.get("discharge_kw", 0.0)) if action == "discharge" else 0.0
        charge = min(max(0.0, charge), ess.max_charge_kw,
                     max(0.0, (ess.capacity_kwh - energy) / (dt_hours * ess.charge_efficiency)))
        discharge = min(max(0.0, discharge), ess.max_discharge_kw,
                         max(0.0, (energy - ess.reserve_soc_fraction * ess.capacity_kwh) * ess.discharge_efficiency / dt_hours))
        energy = energy + charge * dt_hours * ess.charge_efficiency - discharge * dt_hours / ess.discharge_efficiency
        grid = float(slot["load_kw"]) - float(slot["solar_kw"]) + charge - discharge
        result.append({
            "valid_at": slot["valid_at"], "battery_signed_kw": discharge - charge,
            "charge_kw": charge, "discharge_kw": discharge,
            "grid_import_kw": max(0.0, grid), "grid_export_kw": max(0.0, -grid),
            "energy_kwh": energy,
        })
    return result


class FixedBatteryBaseline:
    """Explicit fixed schedule; missing actions remain idle."""

    name = "fixed"

    def __init__(self, actions: dict[str, str], *, charge_kw: float, discharge_kw: float):
        self.actions = dict(actions)
        self.charge_kw = float(charge_kw)
        self.discharge_kw = float(discharge_kw)

    def simulate(self, slots: list[dict[str, Any]], ess: ESSReplayLimits | None) -> list[dict[str, Any]]:
        actions = {key: value for key, value in self.actions.items() if value in {"idle", "charge", "discharge"}}
        enriched = [dict(slot, charge_kw=self.charge_kw, discharge_kw=self.discharge_kw) for slot in slots]
        return _simulate_battery_actions(enriched, ess, actions)


class CheapestPriceBaseline:
    """Deterministic price-ranked schedule with explicit slot counts."""

    name = "cheapest"

    def __init__(self, *, charge_slot_count: int, discharge_slot_count: int, charge_kw: float, discharge_kw: float):
        self.charge_slot_count = int(charge_slot_count)
        self.discharge_slot_count = int(discharge_slot_count)
        self.charge_kw = float(charge_kw)
        self.discharge_kw = float(discharge_kw)

    def simulate(self, slots: list[dict[str, Any]], ess: ESSReplayLimits | None) -> list[dict[str, Any]]:
        if any(_number(slot.get("import_price_sek_per_kwh")) is None for slot in slots):
            raise ValueError("price_input_missing")
        ordered = sorted(slots, key=lambda slot: (float(slot["import_price_sek_per_kwh"]), slot["valid_at"]))
        charge = {slot["valid_at"] for slot in ordered[:max(0, self.charge_slot_count)]}
        discharge = {slot["valid_at"] for slot in sorted(ordered, key=lambda slot: (-float(slot["import_price_sek_per_kwh"]), slot["valid_at"]))[:max(0, self.discharge_slot_count)]}
        actions = {key: "charge" for key in charge}
        actions.update({key: "discharge" for key in discharge if key not in actions})
        enriched = [dict(slot, charge_kw=self.charge_kw, discharge_kw=self.discharge_kw) for slot in slots]
        return _simulate_battery_actions(enriched, ess, actions)


class ThresholdBaseline:
    """Deterministic price thresholds supplied by the benchmark scenario."""

    name = "threshold"

    def __init__(self, *, charge_below_sek_per_kwh: float, discharge_above_sek_per_kwh: float, charge_kw: float, discharge_kw: float):
        self.charge_below = float(charge_below_sek_per_kwh)
        self.discharge_above = float(discharge_above_sek_per_kwh)
        self.charge_kw = float(charge_kw)
        self.discharge_kw = float(discharge_kw)

    def simulate(self, slots: list[dict[str, Any]], ess: ESSReplayLimits | None) -> list[dict[str, Any]]:
        if any(_number(slot.get("import_price_sek_per_kwh")) is None for slot in slots):
            raise ValueError("price_input_missing")
        actions = {}
        for slot in slots:
            price = float(slot["import_price_sek_per_kwh"])
            if price < self.charge_below:
                actions[slot["valid_at"]] = "charge"
            elif price > self.discharge_above:
                actions[slot["valid_at"]] = "discharge"
        enriched = [dict(slot, charge_kw=self.charge_kw, discharge_kw=self.discharge_kw) for slot in slots]
        return _simulate_battery_actions(enriched, ess, actions)


class EconomicOptimizerBaseline:
    """Read-only adapter for the Step 8 optimizer; never exposes execution."""

    name = "optimizer"

    def __init__(self, *, site_id: str, decision_at: datetime, economics: dict[str, Any], resource_id: str):
        self.site_id = site_id
        self.decision_at = decision_at
        self.economics = dict(economics)
        self.resource_id = resource_id

    def simulate(self, slots: list[dict[str, Any]], ess: ESSReplayLimits | None) -> list[dict[str, Any]]:
        if ess is None:
            raise ValueError("ess_limits_missing")
        from .economic_optimizer import build_economic_plan

        inputs = {
            "site_id": self.site_id,
            "known_at": self.decision_at,
            "slots": slots,
            "economics": self.economics,
            "replanning": None,
            "ess": {
                "soc_fraction": ess.initial_soc_fraction,
                "capacity_kwh": ess.capacity_kwh,
                "reserve_soc_fraction": ess.reserve_soc_fraction,
                "max_charge_kw": ess.max_charge_kw,
                "max_discharge_kw": ess.max_discharge_kw,
                "charge_efficiency": ess.charge_efficiency,
                "discharge_efficiency": ess.discharge_efficiency,
                "resource_identity": {
                    "available": True,
                    "site_id": self.site_id,
                    "resource_id": self.resource_id,
                    "method": "strong_registry_config_entry_and_device_identity",
                },
            },
        }
        plan = build_economic_plan(inputs)
        if plan.get("available") is not True:
            raise ValueError(str(plan.get("reason") or "optimizer_unavailable"))
        return [{
            "valid_at": point["valid_at"],
            "battery_signed_kw": point["discharge_kw"] - point["charge_kw"],
            "charge_kw": point["charge_kw"],
            "discharge_kw": point["discharge_kw"],
            "grid_import_kw": point["import_kw"],
            "grid_export_kw": point["export_kw"],
            "energy_kwh": point["energy_kwh"],
        } for point in plan["points"]]


def compute_regret(candidate_scorecard: dict[str, Any], reference_scorecard: dict[str, Any], *, reference_kind: str) -> dict[str, Any]:
    """Compare evaluation scorecards without making the reference a decision input."""
    candidate_cost = _number(candidate_scorecard.get("cost_sek"))
    reference_cost = _number(reference_scorecard.get("cost_sek"))
    return {
        "available": candidate_cost is not None and reference_cost is not None,
        "candidate_cost_sek": candidate_cost,
        "reference_cost_sek": reference_cost,
        "cost_regret_sek": None if candidate_cost is None or reference_cost is None else round(candidate_cost - reference_cost, 9),
        "reference_kind": reference_kind,
        "evaluation_only": True,
        "hindsight_used_for_decision": False,
    }


def build_hindsight_oracle(
    *,
    site_id: str,
    decision_at: datetime,
    slots: list[dict[str, Any]],
    actual_rows: Iterable[dict[str, Any]],
    economics: dict[str, Any],
    ess: ESSReplayLimits | None,
    resource_id: str,
) -> dict[str, Any]:
    """Build an evaluation-only oracle from matured actual load/solar data.

    The oracle is intentionally a separate artifact. Its post-decision actuals
    are never passed to the replay decision or optimizer baseline.
    """
    actual_by_time: dict[str, dict[str, float]] = {}
    for row in actual_rows:
        if not isinstance(row, dict) or row.get("site_id") != site_id or not _qualified(row):
            continue
        start = _iso(row.get("interval_start"))
        value = _number(row.get("value"))
        if start is None or value is None:
            continue
        if row.get("logical_role") == "house.consumption":
            actual_by_time.setdefault(start, {})["load_kw"] = value / 1000.0
        elif row.get("logical_role") == "solar.production":
            actual_by_time.setdefault(start, {})["solar_kw"] = value / 1000.0
    oracle_slots = []
    for slot in slots:
        values = actual_by_time.get(_iso(slot.get("valid_at")) or "")
        if not values or "load_kw" not in values or "solar_kw" not in values:
            return {
                "available": False,
                "reason": "hindsight_actual_load_or_solar_missing",
                "evaluation_only": True,
                "hindsight_used_for_decision": False,
                "provenance": {"source": "matured_actual_outcomes", "decision_at": _iso(decision_at)},
            }
        oracle_slots.append({**slot, **values})
    try:
        points = EconomicOptimizerBaseline(
            site_id=site_id,
            decision_at=decision_at,
            economics=economics,
            resource_id=resource_id,
        ).simulate(oracle_slots, ess)
    except ValueError as error:
        return {
            "available": False,
            "reason": str(error),
            "evaluation_only": True,
            "hindsight_used_for_decision": False,
            "provenance": {"source": "matured_actual_outcomes", "decision_at": _iso(decision_at)},
        }
    return {
        "available": True,
        "evaluation_only": True,
        "hindsight_used_for_decision": False,
        "provenance": {
            "source": "matured_actual_outcomes",
            "decision_at": _iso(decision_at),
            "hindsight": True,
            "model_kind": "evaluation_only_oracle",
        },
        "points": points,
        "scorecard": _score(points, oracle_slots, ess),
    }


def build_actual_evaluation_scorecard(
    *, site_id: str, slots: list[dict[str, Any]], actual_rows: Iterable[dict[str, Any]], ess: ESSReplayLimits | None
) -> dict[str, Any]:
    """Score matured actual outcomes only; never feeds them into a decision."""
    actual_by_time: dict[str, dict[str, float]] = {}
    for row in actual_rows:
        if not isinstance(row, dict) or row.get("site_id") != site_id or not _qualified(row):
            continue
        start = _iso(row.get("interval_start"))
        value = _number(row.get("value"))
        if start is None or value is None:
            continue
        role = row.get("logical_role")
        if role == "house.consumption":
            actual_by_time.setdefault(start, {})["load_kw"] = value / 1000.0
        elif role == "solar.production":
            actual_by_time.setdefault(start, {})["solar_kw"] = value / 1000.0
        elif role == "grid.power/import":
            actual_by_time.setdefault(start, {})["grid_kw"] = value / 1000.0
        elif role == "battery.power":
            actual_by_time.setdefault(start, {})["battery_kw"] = value / 1000.0
        elif role == "battery.soc":
            actual_by_time.setdefault(start, {})["soc_fraction"] = value / 100.0
    if any(_iso(slot.get("valid_at")) not in actual_by_time for slot in slots):
        return {
            "available": False,
            "reason": "actual_outcome_coverage_incomplete",
            "provenance": {"source": "matured_actual_outcomes", "site_id": site_id},
        }
    import_kwh = export_kwh = throughput_kwh = 0.0
    cost = 0.0
    peak_kw = 0.0
    reserve_violations = 0
    missing_price = False
    for slot in slots:
        values = actual_by_time[_iso(slot["valid_at"])]
        grid_kw = values.get("grid_kw")
        if grid_kw is None:
            return {"available": False, "reason": "actual_grid_power_missing", "provenance": {"source": "matured_actual_outcomes", "site_id": site_id}}
        dt_hours = float(slot.get("duration_hours", 0.25))
        import_kw = max(0.0, grid_kw)
        export_kw = max(0.0, -grid_kw)
        import_kwh += import_kw * dt_hours
        export_kwh += export_kw * dt_hours
        peak_kw = max(peak_kw, import_kw)
        battery_kw = values.get("battery_kw")
        if battery_kw is not None:
            throughput_kwh += abs(battery_kw) * dt_hours
        if ess is not None and values.get("soc_fraction") is not None and values["soc_fraction"] < ess.reserve_soc_fraction - 1e-9:
            reserve_violations += 1
        price = _number(slot.get("import_price_sek_per_kwh"))
        export_value = _number(slot.get("export_value_sek_per_kwh"))
        if price is None or export_value is None:
            missing_price = True
        else:
            cost += import_kw * dt_hours * price - export_kw * dt_hours * export_value
    return {
        "available": True,
        "cost_sek": None if missing_price else round(cost, 9),
        "cost_status": "unavailable_missing_price" if missing_price else "qualified",
        "import_kwh": round(import_kwh, 9),
        "export_kwh": round(export_kwh, 9),
        "peak_import_kw": round(peak_kw, 9),
        "throughput_kwh": round(throughput_kwh, 9),
        "efc": round(throughput_kwh / (2 * ess.capacity_kwh), 9) if ess else None,
        "reserve_violation_count": reserve_violations,
        "degradation": {"available": False, "reason": "verified_degradation_evidence_missing", "source": "none"},
        "provenance": {"source": "matured_actual_outcomes", "site_id": site_id, "evaluation_only": True},
    }


def evaluate_plan_against_actual(
    *, site_id: str, plan_points: list[dict[str, Any]], slots: list[dict[str, Any]], actual_rows: Iterable[dict[str, Any]], ess: ESSReplayLimits | None
) -> dict[str, Any]:
    """Apply a causal plan's battery actions to matured actual load/solar."""
    actual_by_time: dict[str, dict[str, float]] = {}
    for row in actual_rows:
        if not isinstance(row, dict) or row.get("site_id") != site_id or not _qualified(row):
            continue
        start = _iso(row.get("interval_start")); value = _number(row.get("value"))
        if start is None or value is None:
            continue
        if row.get("logical_role") == "house.consumption": actual_by_time.setdefault(start, {})["load_kw"] = value / 1000.0
        elif row.get("logical_role") == "solar.production": actual_by_time.setdefault(start, {})["solar_kw"] = value / 1000.0
    if any(_iso(slot.get("valid_at")) not in actual_by_time for slot in slots):
        return {"available": False, "reason": "actual_load_solar_coverage_incomplete", "evaluation_only": True}
    evaluated = []
    for plan, slot in zip(plan_points, slots):
        values = actual_by_time[_iso(slot["valid_at"])]
        evaluated.append({
            "valid_at": slot["valid_at"], "load_kw": values["load_kw"], "solar_kw": values["solar_kw"],
            "charge_kw": float(plan.get("charge_kw", 0.0)), "discharge_kw": float(plan.get("discharge_kw", 0.0)),
            "grid_import_kw": max(0.0, values["load_kw"] - values["solar_kw"] + float(plan.get("charge_kw", 0.0)) - float(plan.get("discharge_kw", 0.0))),
            "grid_export_kw": max(0.0, -(values["load_kw"] - values["solar_kw"] + float(plan.get("charge_kw", 0.0)) - float(plan.get("discharge_kw", 0.0)))),
            "energy_kwh": plan.get("energy_kwh"),
        })
    scorecard = _score(evaluated, slots, ess)
    scorecard["peak_import_kw"] = round(max((point["grid_import_kw"] for point in evaluated), default=0.0), 9)
    scorecard["degradation"] = {"available": False, "reason": "verified_degradation_evidence_missing", "source": "none"}
    scorecard["provenance"] = {"source": "matured_actual_outcomes", "site_id": site_id, "evaluation_only": True}
    return {"available": True, "scorecard": scorecard, "points": evaluated, "evaluation_only": True}


def _validate_ess(ess: ESSReplayLimits | None) -> list[str]:
    if ess is None:
        return ["ess_limits_missing"]
    values = (ess.capacity_kwh, ess.reserve_soc_fraction, ess.max_charge_kw,
              ess.max_discharge_kw, ess.charge_efficiency,
              ess.discharge_efficiency, ess.initial_soc_fraction)
    if any(value != value for value in values):
        return ["ess_limits_non_numeric"]
    if not 0 <= ess.reserve_soc_fraction <= ess.initial_soc_fraction <= 1:
        return ["ess_soc_bounds_invalid"]
    if ess.capacity_kwh <= 0 or ess.max_charge_kw < 0 or ess.max_discharge_kw < 0:
        return ["ess_power_or_capacity_invalid"]
    if not 0 < ess.charge_efficiency <= 1 or not 0 < ess.discharge_efficiency <= 1:
        return ["ess_efficiency_invalid"]
    return []


def _actual_by_slot(actual_rows: Iterable[dict[str, Any]], site_id: str) -> tuple[dict[str, dict[str, float]], list[str]]:
    grouped: dict[str, dict[str, float]] = {}
    reasons: list[str] = []
    for row in actual_rows:
        if not isinstance(row, dict) or row.get("site_id") != site_id:
            continue
        if not _qualified(row):
            continue
        start = _iso(row.get("interval_start"))
        value = _number(row.get("value"))
        if start is None or value is None:
            continue
        role = row.get("logical_role")
        if role not in {"grid.power/import", "battery.power", "battery.soc"}:
            continue
        target = grouped.setdefault(start, {})
        key = {"grid.power/import": "grid_kw", "battery.power": "battery_kw", "battery.soc": "soc_fraction"}[role]
        target[key] = value / 1000 if key != "soc_fraction" else value / 100
    return grouped, reasons


def _score(points: list[dict[str, Any]], slots: list[dict[str, Any]], ess: ESSReplayLimits | None) -> dict[str, Any]:
    by_time = {point["valid_at"]: point for point in points}
    cost = 0.0
    import_kwh = export_kwh = throughput_kwh = 0.0
    missing_prices = False
    reserve_violations = 0
    constraint_violations = 0
    for slot in slots:
        point = by_time[slot["valid_at"]]
        dt_hours = float(slot.get("duration_hours", 0.25))
        import_kwh += point["grid_import_kw"] * dt_hours
        export_kwh += point["grid_export_kw"] * dt_hours
        throughput_kwh += (point["charge_kw"] + point["discharge_kw"]) * dt_hours
        price = _number(slot.get("import_price_sek_per_kwh"))
        export_value = _number(slot.get("export_value_sek_per_kwh"))
        if price is None or export_value is None:
            missing_prices = True
        else:
            cost += point["grid_import_kw"] * dt_hours * price - point["grid_export_kw"] * dt_hours * export_value
        if ess is not None and point["energy_kwh"] is not None and point["energy_kwh"] < ess.reserve_soc_fraction * ess.capacity_kwh - 1e-9:
            reserve_violations += 1
        if point["charge_kw"] < -1e-9 or point["discharge_kw"] < -1e-9:
            constraint_violations += 1
        if ess is not None and (point["charge_kw"] > ess.max_charge_kw + 1e-9 or point["discharge_kw"] > ess.max_discharge_kw + 1e-9):
            constraint_violations += 1
    return {
        "cost_sek": None if missing_prices else round(cost, 9),
        "import_kwh": round(import_kwh, 9),
        "export_kwh": round(export_kwh, 9),
        "throughput_kwh": round(throughput_kwh, 9),
        "efc": round(throughput_kwh / (2 * ess.capacity_kwh), 9) if ess else None,
        "reserve_violation_count": reserve_violations,
        "constraint_violations": constraint_violations,
        "safety_qualified": reserve_violations == 0 and constraint_violations == 0,
        "cost_status": "unavailable_missing_price" if missing_prices else "qualified",
    }


def build_replay_run(
    *,
    site_id: str,
    decision_at: datetime,
    frames: Iterable[dict[str, Any]],
    slots: list[dict[str, Any]],
    actual_rows: Iterable[dict[str, Any]] = (),
    model_identity: dict[str, Any] | None = None,
    economics_identity: dict[str, Any] | None = None,
    ess: ESSReplayLimits | None = None,
    baselines: Iterable[ReplayBaseline] = (NoBatteryBaseline(), SelfConsumptionBaseline()),
    timezone_name: str = "UTC",
) -> dict[str, Any]:
    """Build one deterministic, non-persistent replay/benchmark artifact."""
    selected = select_causal_frames(frames, site_id=site_id, decision_at=decision_at)
    reasons = list(selected["reasons"])
    if not isinstance(model_identity, dict) or not model_identity:
        reasons.append("model_identity_missing")
    if not isinstance(slots, list) or not slots:
        reasons.append("slots_missing")
    previous = None
    frame_ids = {frame.get("frame_id") for frame in selected["frames"]}
    for frame in selected["frames"]:
        if not _frame_qualified(frame):
            reasons.append("frame_quality_unqualified")
    normalized_slots: list[dict[str, Any]] = []
    for slot in slots if isinstance(slots, list) else []:
        valid_at = _moment(slot.get("valid_at")) if isinstance(slot, dict) else None
        end_at = _moment(slot.get("end_at")) if isinstance(slot, dict) else None
        load = _number(slot.get("load_kw")) if isinstance(slot, dict) else None
        solar = _number(slot.get("solar_kw")) if isinstance(slot, dict) else None
        source_frame_ids = slot.get("frame_ids", []) if isinstance(slot, dict) else []
        if valid_at is None or end_at is None or load is None or solar is None or load < 0 or solar < 0:
            reasons.append("slot_input_invalid")
            continue
        if previous is not None and valid_at != previous + timedelta(minutes=15):
            reasons.append("slot_gap_or_misalignment")
        if end_at - valid_at != timedelta(minutes=15):
            reasons.append("slot_duration_invalid")
        if valid_at <= decision_at.astimezone(UTC):
            reasons.append("slot_not_future_at_decision")
        if not isinstance(source_frame_ids, list) or not source_frame_ids or not set(source_frame_ids).issubset(frame_ids):
            reasons.append("slot_frame_provenance_missing")
        previous = valid_at
        normalized_slots.append({
            "valid_at": valid_at.isoformat(),
            "end_at": end_at.isoformat(),
            "duration_hours": 0.25,
            "load_kw": load,
            "solar_kw": solar,
            "import_price_sek_per_kwh": slot.get("import_price_sek_per_kwh"),
            "export_value_sek_per_kwh": slot.get("export_value_sek_per_kwh"),
            "frame_ids": sorted(source_frame_ids),
        })
    if len(normalized_slots) != len(slots):
        reasons.append("incomplete_slot_set")
    ess_reasons = _validate_ess(ess)
    actual_by_slot, _ = _actual_by_slot(actual_rows, site_id)
    replay_slot_keys = {_iso(slot.get("valid_at")) for slot in normalized_slots}
    actual_outcome_count = sum(key in replay_slot_keys for key in actual_by_slot)
    # Irrelevant future or other-site frames are safely excluded. Contamination
    # is reserved for data referenced by the replay that cannot be qualified.
    contamination = "slot_frame_provenance_missing" in reasons or "frame_quality_unqualified" in reasons
    if contamination:
        reasons.append("contaminated_frame_input")
    baseline_results: dict[str, Any] = {}
    for baseline in baselines:
        try:
            points = baseline.simulate(normalized_slots, ess)
        except ValueError as error:
            baseline_results[baseline.name] = {"available": False, "reason": str(error)}
            continue
        baseline_results[baseline.name] = {
            "available": True,
            "points": points,
            "scorecard": _score(points, normalized_slots, ess),
        }
    qualified = not reasons and not ess_reasons and bool(normalized_slots) and all(
        item.get("available") is True for item in baseline_results.values()
    )
    all_reasons = reasons + ess_reasons
    canonical = {
        "schema": SCHEMA,
        "model_version": MODEL_VERSION,
        "site_id": site_id,
        "decision_at": _iso(decision_at),
        "timezone": timezone_name,
        "qualification": {
            "qualified": qualified,
            "reasons": sorted(set(all_reasons)),
            "contaminated": contamination,
            "incomplete": any(reason.startswith(("slot_", "incomplete_")) for reason in all_reasons),
            "actual_outcome_count": actual_outcome_count,
            "hindsight_used_for_decision": False,
        },
        "input_identity": {
            "frame_ids": sorted(frame_ids),
            "frames": [_frame_identity(frame) for frame in selected["frames"]],
            "model": model_identity,
            "calibration": (model_identity or {}).get("calibration"),
            "economics": economics_identity,
            "schema": SCHEMA,
        },
        "baselines": baseline_results,
    }
    canonical["run_fingerprint"] = _fingerprint(canonical)
    return canonical
