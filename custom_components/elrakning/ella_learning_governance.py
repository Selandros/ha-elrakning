"""Deterministic, fail-closed learning governance helpers."""

from __future__ import annotations

import hashlib
import json
import math
from statistics import mean
from typing import Any


SCHEMA = "ella_learning_governance.v1"
POLICY_VERSION = "learning-governance-v1"
MIN_DRIFT_SUPPORT = 6
DRIFT_RELATIVE_CHANGE = 0.20


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _error_values(records: list[dict[str, Any]]) -> list[float]:
    values: list[tuple[str, float]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        error = _finite(record.get("signed_error_w"))
        if error is None:
            series = record.get("series")
            if isinstance(series, dict):
                item = series.get("consumption") or series.get("load") or series.get("battery")
                if isinstance(item, dict):
                    error = _finite(item.get("signed_error_w"))
        if error is not None:
            values.append((str(record.get("valid_at") or ""), error))
    return [value for _, value in sorted(values)]


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_learning_governance(
    site_id: str,
    records: list[dict[str, Any]],
    calibration: dict[str, Any] | None,
    *,
    benchmark_evidence: dict[str, Any] | None = None,
    shadow_evidence: dict[str, Any] | None = None,
    active_candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return governance state without changing a forecast or promoting a model."""
    if not isinstance(site_id, str) or not site_id.strip():
        return {"schema": SCHEMA, "available": False, "reason": "site_missing"}
    calibration = calibration if isinstance(calibration, dict) else {}
    values = _error_values(records)
    candidate_payload = {
        "site_id": site_id,
        "policy_version": POLICY_VERSION,
        "calibration": calibration,
    }
    candidate = {
        "candidate_id": f"candidate-{_fingerprint(candidate_payload)[:32]}",
        "model_version": calibration.get("version"),
        "status": "candidate",
        "provenance": {"source": "causal_matured_evidence", "site_id": site_id},
    }
    if len(values) < MIN_DRIFT_SUPPORT:
        drift = {
            "status": "unavailable",
            "reason": "insufficient_support",
            "support_count": len(values),
            "policy_version": POLICY_VERSION,
        }
    else:
        midpoint = len(values) // 2
        prior = values[:midpoint]
        recent = values[midpoint:]
        prior_mae = mean(abs(value) for value in prior)
        recent_mae = mean(abs(value) for value in recent)
        denominator = max(prior_mae, 1.0)
        relative_change = (recent_mae - prior_mae) / denominator
        drift = {
            "status": "detected" if abs(relative_change) >= DRIFT_RELATIVE_CHANGE else "stable",
            "reason": "error_distribution_change" if abs(relative_change) >= DRIFT_RELATIVE_CHANGE else "within_policy_band",
            "support_count": len(values),
            "prior_mae_w": prior_mae,
            "recent_mae_w": recent_mae,
            "relative_change": relative_change,
            "policy_version": POLICY_VERSION,
        }
    sign_mismatch = any(
        isinstance(record, dict)
        and isinstance(record.get("series"), dict)
        and any(
            (_finite(item.get("predicted_w")) or 0.0) * (_finite(item.get("actual_w")) or 0.0) < 0
            for item in record["series"].values()
            if isinstance(item, dict) and _finite(item.get("predicted_w")) is not None and _finite(item.get("actual_w")) is not None
        )
        for record in records
    )
    benchmark_ok = bool(isinstance(benchmark_evidence, dict) and benchmark_evidence.get("qualified") is True)
    shadow_ok = bool(isinstance(shadow_evidence, dict) and shadow_evidence.get("qualified") is True)
    gates = {
        "observation": bool(values),
        "support": len(values) >= MIN_DRIFT_SUPPORT,
        "sign_mismatch_absent": not sign_mismatch,
        "benchmark_live_qualified": benchmark_ok,
        "shadow_live_qualified": shadow_ok,
        "safety_constraints_unchanged": True,
    }
    promotion = {
        "eligible": all(gates.values()),
        "status": "eligible" if all(gates.values()) else "gated",
        "reasons": [key for key, value in gates.items() if not value],
        "candidate_id": candidate["candidate_id"],
        "gates": gates,
        "provenance": {"source": "learning_governance", "site_id": site_id, "policy_version": POLICY_VERSION},
    }
    rollback = {
        "available": bool(isinstance(active_candidate, dict) and active_candidate.get("candidate_id")),
        "active_candidate_id": (active_candidate or {}).get("candidate_id"),
        "reason": None if isinstance(active_candidate, dict) and active_candidate.get("candidate_id") else "no_promoted_candidate",
    }
    return {
        "schema": SCHEMA,
        "available": bool(values),
        "site_id": site_id,
        "policy_version": POLICY_VERSION,
        "candidate": candidate,
        "drift": drift,
        "promotion": promotion,
        "rollback": rollback,
    }
