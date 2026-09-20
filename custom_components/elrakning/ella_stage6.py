"""Conservative, site-scoped Stage 6 solar and ESS enrichment."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from statistics import median
from typing import Any

from homeassistant.helpers.storage import Store


SCHEMA = "ella_stage6_state.v1"
STORE_SCHEMA = "ella_stage6_calibration_store.v1"
STORE_KEY = "elrakning.ella_stage6_calibration"
STORE_VERSION = 1
CALIBRATION_VERSION = "solar-calibration-v1"
ESS_PHYSICAL_VERSION = "ess-physical-v1"
MIN_SOLAR_SUPPORT = 3
MAX_SOLAR_EVIDENCE_PER_RESOURCE = 256
ACTUAL_COVERAGE_GATE = 0.9
SOLAR_FACTOR_MIN = 0.85
SOLAR_FACTOR_MAX = 1.15


def _stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else None
    return None


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _resource_key(value: dict[str, Any]) -> str | None:
    resource_id = value.get("resource_id")
    generation_id = value.get("source_generation_id") or value.get("generation_id")
    if isinstance(resource_id, str) and resource_id.strip():
        return resource_id
    if isinstance(generation_id, str) and generation_id.strip():
        return generation_id
    return None


def _actual_solar(rows: list[dict[str, Any]], site_id: str) -> dict[tuple[str, datetime], dict[str, Any]]:
    result: dict[tuple[str, datetime], dict[str, Any]] = {}
    for row in rows:
        if row.get("site_id") not in {None, site_id} or row.get("logical_role") != "solar.production":
            continue
        if row.get("unit") != "W" or row.get("quality_status") not in {"good", "partial"}:
            continue
        coverage = _number(row.get("coverage_ratio"))
        value = _number(row.get("value"))
        start = _datetime(row.get("interval_start"))
        end = _datetime(row.get("interval_end"))
        resource = _resource_key(row)
        if coverage is None or coverage < ACTUAL_COVERAGE_GATE or value is None or value < 0 or not start or not end or not resource:
            continue
        result[(resource, start.astimezone(timezone.utc))] = {
            "value_w": value, "unit": "W", "valid_at": _iso(start),
            "coverage_ratio": coverage, "quality_status": row.get("quality_status"),
            "source_generation_id": row.get("source_generation_id"),
            "resource_id": row.get("resource_id"),
        }
    return result


def _forecast_solar(frames: list[dict[str, Any]], site_id: str, decision_at: datetime) -> dict[tuple[str, datetime], dict[str, Any]]:
    result: dict[tuple[str, datetime], dict[str, Any]] = {}
    for frame in frames:
        if frame.get("site_id") != site_id or frame.get("classification") != "forecast":
            continue
        frame_known = _datetime(frame.get("known_at"))
        if not frame_known or frame_known > decision_at:
            continue
        frame_resource = _resource_key(frame)
        for point in frame.get("points") or []:
            if not isinstance(point, dict) or point.get("unit") != "W":
                continue
            valid_at = _datetime(point.get("valid_at"))
            value = _number(point.get("value"))
            if not valid_at or value is None or value < 0 or not frame_resource:
                continue
            if frame_known > valid_at:
                continue
            result[(frame_resource, valid_at.astimezone(timezone.utc))] = {
                "value_w": value, "unit": "W", "valid_at": _iso(valid_at),
                "frame_id": frame.get("frame_id"), "revision": frame.get("revision"),
                "known_at": _iso(frame_known), "source_generation_id": frame.get("source_generation_id"),
                "resource_id": frame.get("resource_id"),
            }
    return result


def _evidence(actual_rows: list[dict[str, Any]], forecast_frames: list[dict[str, Any]], site_id: str, decision_at: datetime) -> dict[str, list[dict[str, Any]]]:
    actual = _actual_solar(actual_rows, site_id)
    forecast = _forecast_solar(forecast_frames, site_id, decision_at)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for key, predicted in forecast.items():
        observed = actual.get(key)
        if not observed:
            continue
        predicted_w = predicted["value_w"]
        actual_w = observed["value_w"]
        evidence_key = _stable({"site_id": site_id, "resource": key[0], "valid_at": predicted["valid_at"], "frame_id": predicted.get("frame_id"), "revision": predicted.get("revision")})
        evidence = {
            "evidence_id": "solar-evidence-" + hashlib.sha256(evidence_key.encode()).hexdigest()[:32],
            "site_id": site_id, "resource_id": observed.get("resource_id") or predicted.get("resource_id"),
            "source_generation_id": observed.get("source_generation_id") or predicted.get("source_generation_id"),
            "frame_id": predicted.get("frame_id"), "revision": predicted.get("revision"),
            "valid_at": predicted["valid_at"], "known_at": predicted["known_at"],
            "predicted_w": predicted_w, "actual_w": actual_w,
            "signed_error_w": actual_w - predicted_w,
            "actual_quality_status": observed.get("quality_status"),
            "actual_coverage_ratio": observed.get("coverage_ratio"),
            "learning_eligible": True, "qualification_reason": "good_high_coverage_overlap",
        }
        grouped.setdefault(key[0], []).append(evidence)
    for resource in grouped:
        grouped[resource] = sorted(grouped[resource], key=lambda item: (item["valid_at"], item.get("evidence_id", "")))[-MAX_SOLAR_EVIDENCE_PER_RESOURCE:]
    return grouped


def _solar_resource_calibration(resource: str, evidence: list[dict[str, Any]], prior: dict[str, Any] | None = None) -> dict[str, Any]:
    ratios = [item["actual_w"] / item["predicted_w"] for item in evidence if item.get("predicted_w", 0) >= 25 and item.get("actual_w", 0) >= 0]
    support = len(evidence)
    if len(ratios) < MIN_SOLAR_SUPPORT:
        return {
            "resource_id": resource, "calibration_version": CALIBRATION_VERSION,
            "factor": 1.0, "bias_w": 0.0, "support_count": support,
            "uncertainty": "insufficient_support", "quality": "low_confidence",
            "reason": "insufficient_support", "last_evidence_at": evidence[-1].get("valid_at") if evidence else None,
            "evidence": evidence, "prior": prior or {},
        }
    raw = median(ratios)
    factor = min(SOLAR_FACTOR_MAX, max(SOLAR_FACTOR_MIN, raw))
    residuals = [item["signed_error_w"] for item in evidence]
    mean_abs = sum(abs(value) for value in residuals) / len(residuals)
    return {
        "resource_id": resource, "calibration_version": CALIBRATION_VERSION,
        "factor": factor, "bias_w": median(residuals), "support_count": support,
        "uncertainty": "bounded_median_ratio", "quality": "calibrated",
        "reason": "support_sufficient", "last_evidence_at": evidence[-1].get("valid_at"),
        "mae_w": mean_abs, "evidence": evidence, "prior": prior or {},
    }


def build_solar_calibration(site_id: str, actual_rows: list[dict[str, Any]], forecast_frames: list[dict[str, Any]], decision_at: datetime, prior: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a deterministic calibration only from compatible slot-resolved overlap."""
    grouped = _evidence(actual_rows, forecast_frames, site_id, decision_at)
    prior_resources = (prior or {}).get("resources", {}) if isinstance(prior, dict) else {}
    for resource, item in prior_resources.items():
        if not isinstance(item, dict):
            continue
        existing = {entry.get("evidence_id"): entry for entry in grouped.get(resource, []) if entry.get("evidence_id")}
        for entry in item.get("evidence") or []:
            if isinstance(entry, dict) and entry.get("evidence_id"):
                existing[entry["evidence_id"]] = deepcopy(entry)
        if existing:
            grouped[resource] = sorted(existing.values(), key=lambda value: (value.get("valid_at") or "", value.get("evidence_id") or ""))[-MAX_SOLAR_EVIDENCE_PER_RESOURCE:]
    resources = {resource: _solar_resource_calibration(resource, items, prior_resources.get(resource)) for resource, items in sorted(grouped.items())}
    if not resources:
        reason = "no_slot_resolved_forecast_overlap" if forecast_frames else "solar_forecast_unavailable"
        return {"schema": "ella_solar_calibration.v1", "site_id": site_id, "calibration_version": CALIBRATION_VERSION, "available": False, "factor": 1.0, "support_count": 0, "uncertainty": "unknown", "reason": reason, "resources": {}}
    return {"schema": "ella_solar_calibration.v1", "site_id": site_id, "calibration_version": CALIBRATION_VERSION, "available": True, "resources": resources, "support_count": sum(item["support_count"] for item in resources.values()), "known_at": _iso(decision_at)}


def _latest_physical(rows: list[dict[str, Any]], site_id: str, role: str, decision_at: datetime) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("site_id") not in {None, site_id} or row.get("logical_role") != role or row.get("quality_status") not in {"good", "partial"}:
            continue
        observed = _datetime(row.get("observed_at")) or _datetime(row.get("interval_end"))
        value = _number(row.get("value"))
        resource = _resource_key(row)
        if not observed or observed > decision_at or value is None or not resource:
            continue
        previous = latest.get(resource)
        if previous is None or observed > previous["observed_at"]:
            latest[resource] = {"resource_id": row.get("resource_id"), "source_generation_id": row.get("source_generation_id"), "value": value, "unit": row.get("unit"), "observed_at": observed}
    return [{**item, "observed_at": _iso(item["observed_at"])} for _key, item in sorted(latest.items())]


def build_ess_physical_state(site_id: str, actual_rows: list[dict[str, Any]], decision_at: datetime) -> dict[str, Any]:
    """Expose observed ESS facts without deriving policy or device limits."""
    facts = {role: _latest_physical(actual_rows, site_id, role, decision_at) for role in ("battery.power", "battery.soc", "battery.capacity")}
    ambiguous = any(
        row.get("site_id") in {None, site_id}
        and row.get("logical_role") in {"battery.power", "battery.soc", "battery.capacity"}
        and not _resource_key(row)
        and row.get("quality_status") in {"good", "partial"}
        for row in actual_rows
    )
    resources = sorted({item.get("resource_id") or item.get("source_generation_id") for values in facts.values() for item in values if item.get("resource_id") or item.get("source_generation_id")})
    return {"schema": "ella_ess_physical_state.v1", "version": ESS_PHYSICAL_VERSION, "site_id": site_id, "available": any(facts.values()) and not ambiguous, "reason": "ambiguous_resource_identity" if ambiguous else None, "resources": resources, "facts": facts, "policy": {"available": False, "reason": "missing_verified_ess_policy_constraints", "missing_fields": ["min_soc", "max_soc", "reserve_soc", "max_charge_power", "max_discharge_power", "grid_charge_permission", "efficiency"]}, "execution_eligible": False, "actuator_writes_enabled": False}


def build_ess_action_eligibility(physical: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy if isinstance(policy, dict) else {}
    physical_available = bool(physical.get("available"))
    required = {"charge_ess": ["soc", "usable_capacity", "max_soc", "max_charge_power", "efficiency"], "grid_charge_ess": ["soc", "usable_capacity", "max_soc", "max_charge_power", "grid_charge_permission", "efficiency"], "discharge_ess": ["soc", "usable_capacity", "min_soc", "reserve_soc", "max_discharge_power", "efficiency"]}
    result = {}
    for action, fields in required.items():
        missing = [field for field in fields if policy.get(field) is None]
        if not physical_available:
            missing = ["physical_state"] + missing
        result[action] = {"eligible": not missing, "missing_fields": sorted(set(missing)), "reason": None if not missing else "missing_verified_ess_policy_constraints", "execution_eligible": False}
    result["hold_ess"] = {"eligible": physical_available, "missing_fields": [] if physical_available else ["physical_state"], "reason": None if physical_available else "missing_verified_ess_physical_state", "execution_eligible": False}
    return result


def build_planned_soc_trajectory(slots: list[dict[str, Any]], physical: dict[str, Any], policy: dict[str, Any] | None = None, actions: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build a bounded planned trajectory only from an explicit normalized ESS policy."""
    policy = policy if isinstance(policy, dict) else {}
    required = ["soc_fraction", "usable_capacity_kwh", "min_soc_fraction", "max_soc_fraction", "reserve_soc_fraction", "max_charge_power_kw", "max_discharge_power_kw", "charge_efficiency", "discharge_efficiency"]
    missing = [field for field in required if policy.get(field) is None]
    if not physical.get("available"):
        missing.insert(0, "physical_state")
    if missing:
        return {"available": False, "reason": "missing_verified_ess_trajectory_inputs", "missing_fields": sorted(set(missing)), "points": [], "execution_eligible": False}
    current = float(policy["soc_fraction"])
    capacity = float(policy["usable_capacity_kwh"])
    minimum = max(float(policy["min_soc_fraction"]), float(policy["reserve_soc_fraction"]))
    maximum = float(policy["max_soc_fraction"])
    charge_efficiency = float(policy["charge_efficiency"])
    discharge_efficiency = float(policy["discharge_efficiency"])
    if not (0 <= minimum <= current <= maximum <= 1 and capacity > 0 and 0 < charge_efficiency <= 1 and 0 < discharge_efficiency <= 1):
        return {"available": False, "reason": "invalid_verified_ess_trajectory_inputs", "missing_fields": [], "points": [], "execution_eligible": False}
    points = []
    for slot in slots:
        start, end = _datetime(slot.get("start")), _datetime(slot.get("end"))
        if not start or not end or end <= start:
            return {"available": False, "reason": "invalid_slot_interval", "missing_fields": [], "points": [], "execution_eligible": False}
        action = (actions or {}).get(slot.get("start"), {})
        code = action.get("code", "hold_ess")
        requested_kw = max(0.0, float(action.get("power_kw", 0.0) or 0.0))
        hours = (end - start).total_seconds() / 3600
        if code == "charge_ess":
            power_kw = min(requested_kw, float(policy["max_charge_power_kw"]))
            next_energy = min(maximum * capacity, current * capacity + power_kw * hours * charge_efficiency)
        elif code == "discharge_ess":
            power_kw = min(requested_kw, float(policy["max_discharge_power_kw"]))
            next_energy = max(minimum * capacity, current * capacity - power_kw * hours / discharge_efficiency)
        elif code == "hold_ess":
            power_kw = 0.0
            next_energy = current * capacity
        else:
            return {"available": False, "reason": "unsupported_ess_action", "missing_fields": [], "points": [], "execution_eligible": False}
        current = next_energy / capacity
        points.append({"start": _iso(start), "end": _iso(end), "action": code, "power_kw": power_kw, "soc_fraction": current, "energy_kwh": next_energy, "semantics": "PLANNED", "provenance": {"policy_version": policy.get("policy_version"), "constraints": required}})
    return {"available": True, "reason": "verified_bounded_trajectory", "missing_fields": [], "points": points, "execution_eligible": False, "actuator_writes_enabled": False}


def build_stage6_state(site_id: str, actual_rows: list[dict[str, Any]], solar_forecast_frames: list[dict[str, Any]], decision_at: datetime, prior_calibration: dict[str, Any] | None = None, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    calibration = build_solar_calibration(site_id, actual_rows, solar_forecast_frames, decision_at, prior_calibration)
    physical = build_ess_physical_state(site_id, actual_rows, decision_at)
    return {"schema": SCHEMA, "site_id": site_id, "known_at": _iso(decision_at), "solar": {"calibration": calibration}, "ess": {"physical": physical, "action_eligibility": build_ess_action_eligibility(physical, policy), "trajectory": build_planned_soc_trajectory([], physical, policy)}, "execution_eligible": False, "actuator_writes_enabled": False}


class EllaStage6CalibrationStore:
    """Persist bounded solar calibration evidence per site and resource."""

    def __init__(self, hass) -> None:
        self.store = Store(hass, STORE_VERSION, STORE_KEY)
        self.state: dict[str, Any] = {"schema": STORE_SCHEMA, "version": 1, "sites": {}}

    async def async_load(self) -> None:
        cached = await self.store.async_load()
        if isinstance(cached, dict) and cached.get("schema") == STORE_SCHEMA and isinstance(cached.get("sites"), dict):
            self.state = {"schema": STORE_SCHEMA, "version": 1, "sites": cached["sites"]}

    async def async_record(self, site_id: str, calibration: dict[str, Any]) -> None:
        if not isinstance(site_id, str) or calibration.get("site_id") != site_id:
            return
        site = self.state.setdefault("sites", {}).setdefault(site_id, {"resources": {}})
        for resource, item in (calibration.get("resources") or {}).items():
            if not isinstance(item, dict):
                continue
            target = site.setdefault("resources", {}).setdefault(resource, {"evidence": []})
            by_id = {entry.get("evidence_id"): entry for entry in target.get("evidence", []) if isinstance(entry, dict) and entry.get("evidence_id")}
            for entry in item.get("evidence") or []:
                if isinstance(entry, dict) and entry.get("evidence_id"):
                    by_id[entry["evidence_id"]] = deepcopy(entry)
            target["evidence"] = sorted(by_id.values(), key=lambda entry: (entry.get("valid_at") or "", entry.get("evidence_id") or ""))[-MAX_SOLAR_EVIDENCE_PER_RESOURCE:]
            target["calibration"] = {key: value for key, value in item.items() if key != "evidence"}
        await self.store.async_save(self.state)

    def public_state(self, site_id: str) -> dict[str, Any]:
        site = self.state.get("sites", {}).get(site_id)
        return {"schema": STORE_SCHEMA, "site_id": site_id, "available": bool(site), "resources": deepcopy(site.get("resources", {})) if isinstance(site, dict) else {}, "execution_eligible": False, "actuator_writes_enabled": False}
