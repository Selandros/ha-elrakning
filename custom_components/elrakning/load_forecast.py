"""Deterministic, read-only load forecast frames for ELLA and billing UI."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from .canonical_storage import CanonicalStorage


DATASET = "load_forecast.v1"
PAYLOAD_SCHEMA = "load_forecast.v1"
LOGICAL_ROLE = "load.forecast"
MODEL_VERSION = "load-profile-v2"
TRAINING_DATASET_VERSION = "canonical-house-consumption-60d-v1"
PARAMETER_CONFIG_VERSION = "load-forecast-parameters-v1"
MIN_DISTINCT_DAYS = 7
SLOT_SECONDS = 900
SEGMENT_SCHEMA = "ella_forecast_segment_metrics.v1"
SEGMENT_CLASSIFIER_VERSION = "weekday-weekend-facets-v1"


def _quarter_start(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc).replace(second=0, microsecond=0)
    return value - timedelta(minutes=value.minute % 15)


def _generation_id(site_id: str, source_generations: set[str], calibration: dict[str, Any] | None = None) -> str:
    identity = {"dataset": DATASET, "model_version": MODEL_VERSION, "site_id": site_id,
                "source_generations": sorted(source_generations), "calibration": calibration or {}}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]
    return f"load-{digest}"


def _parameter_config_hash(horizon_hours: int) -> str:
    payload = {
        "parameter_config_version": PARAMETER_CONFIG_VERSION,
        "model_version": MODEL_VERSION,
        "training_dataset_version": TRAINING_DATASET_VERSION,
        "horizon_hours": horizon_hours,
        "slot_seconds": SLOT_SECONDS,
        "min_distinct_days": MIN_DISTINCT_DAYS,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _profile_buckets(history: list[dict[str, Any]], timezone_name: str):
    """Build the shared weekday/time-of-day profile used by load forecasts."""
    try:
        zone = ZoneInfo(timezone_name)
    except Exception:
        return None
    rows = []
    for row in history:
        if row.get("logical_role") != "house.consumption" or row.get("value") is None:
            continue
        if row.get("quality_status") not in {"good", "partial"}:
            continue
        interval_start = row.get("interval_start")
        if not isinstance(interval_start, datetime) or interval_start.tzinfo is None:
            continue
        try:
            value = float(row["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if value < 0 or not math.isfinite(value):
            continue
        rows.append((row, interval_start.astimezone(zone), value))
    if not rows:
        return None
    by_weekday_slot: dict[tuple[int, int], list[tuple[float, dict[str, Any]]]] = defaultdict(list)
    by_slot: dict[int, list[tuple[float, dict[str, Any]]]] = defaultdict(list)
    for row, local, value in rows:
        slot = local.hour * 4 + local.minute // 15
        by_weekday_slot[(local.weekday(), slot)].append((value, row))
        by_slot[slot].append((value, row))
    return zone, by_weekday_slot, by_slot


def _baseline_point(profile, local_time: datetime) -> tuple[float | None, str, int]:
    """Return the deterministic historical baseline for one local slot."""
    _zone, by_weekday_slot, by_slot = profile
    slot = local_time.hour * 4 + local_time.minute // 15
    candidates = by_weekday_slot.get((local_time.weekday(), slot), [])
    support = "weekday_slot"
    if not candidates:
        candidates = by_slot.get(slot, [])
        support = "all_weekdays_slot"
    if not candidates:
        return None, support, 0
    return sum(value for value, _row in candidates) / len(candidates), support, len(candidates)


def _qualified_actual(row: dict[str, Any], decision_at: datetime) -> bool:
    """Accept completed, well-covered canonical observations for learning."""
    coverage = row.get("coverage_ratio")
    return (
        row.get("logical_role") == "house.consumption"
        and row.get("unit") == "W"
        and row.get("quality_status") in {"good", "partial"}
        and isinstance(row.get("interval_start"), datetime)
        and isinstance(row.get("interval_end"), datetime)
        and row["interval_end"] <= decision_at
        and isinstance(coverage, (int, float))
        and math.isfinite(float(coverage))
        and float(coverage) >= 0.9
        and isinstance(row.get("value"), (int, float))
        and math.isfinite(float(row["value"]))
        and float(row["value"]) >= 0
    )


def _intraday_calibration(history: list[dict[str, Any]], timezone_name: str, known_at: datetime) -> dict[str, Any]:
    """Estimate a bounded same-day correction from completed qualified slots."""
    try:
        zone = ZoneInfo(timezone_name)
    except Exception:
        return {"factor": 1.0, "evidence_count": 0, "confidence": "low_confidence", "reason": "timezone_unavailable", "evidence": []}
    today = known_at.astimezone(zone).date()
    baseline_history = [
        row for row in history
        if isinstance(row.get("interval_start"), datetime)
        and row["interval_start"].astimezone(zone).date() != today
    ]
    profile = _profile_buckets(baseline_history, timezone_name)
    evidence = []
    if profile is not None:
        for row in history:
            start = row.get("interval_start")
            if not _qualified_actual(row, known_at) or start.astimezone(zone).date() != today:
                continue
            baseline, support_method, support = _baseline_point(profile, start.astimezone(zone))
            actual = float(row["value"])
            if baseline is None or baseline <= 1:
                continue
            evidence.append({
                "valid_at": start.astimezone(timezone.utc).isoformat(),
                "actual_w": actual,
                "baseline_w": baseline,
                "ratio": actual / baseline,
                "quality_status": row.get("quality_status"),
                "learning_eligible": True,
                "qualification_reason": (
                    "partial_high_coverage" if row.get("quality_status") == "partial"
                    else "good_high_coverage"
                ),
                "support_method": support_method,
                "sample_support": support,
                "coverage_ratio": float(row["coverage_ratio"]),
                "source_generation_id": row.get("source_generation_id"),
            })
    evidence = sorted(evidence, key=lambda item: item["valid_at"])[-8:]
    ratios = [item["ratio"] for item in evidence]
    if len(ratios) < 3:
        return {"factor": 1.0, "evidence_count": len(ratios), "confidence": "low_confidence", "reason": "insufficient_support", "evidence": evidence}
    robust_ratio = median(ratios)
    shrink = min(0.75, (len(ratios) - 2) / 6)
    factor = min(1.45, max(0.55, 1.0 + (robust_ratio - 1.0) * shrink))
    if abs(factor - 1.0) < 0.05:
        return {
            "factor": 1.0, "raw_ratio_median": robust_ratio, "evidence_count": len(ratios),
            "confidence": "medium_confidence", "reason": "below_materiality_threshold", "evidence": evidence,
        }
    classification = "within_expected_error"
    if robust_ratio < 0.85:
        classification = "systematic_overprediction"
    elif robust_ratio > 1.15:
        classification = "systematic_underprediction"
    return {
        "factor": factor,
        "raw_ratio_median": robust_ratio,
        "evidence_count": len(ratios),
        "confidence": "good" if len(ratios) >= 6 else "medium_confidence",
        "reason": classification,
        "evidence": evidence,
    }


def _parse_evaluation_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _segment_metric(
    name: str,
    records: list[dict[str, Any]],
    provenance: dict[str, Any],
    timezone_name: str | None,
) -> dict[str, Any]:
    result = {
        "schema": SEGMENT_SCHEMA,
        "classifier_version": SEGMENT_CLASSIFIER_VERSION,
        "segment": name,
        "model_version": provenance.get("model_version"),
        "training_dataset_version": provenance.get("training_dataset_version"),
        "parameter_config_version": provenance.get("parameter_config_version"),
        "parameter_config_hash": provenance.get("parameter_config_hash"),
        "site_calibration_version": provenance.get("site_calibration_version"),
        "support_count": 0,
        "eligible_count": 0,
        "coverage": 0.0,
        "mae_w": None,
        "bias_w": None,
        "wape": None,
        "unavailable_reason": None,
    }
    if name == "weekend":
        if not timezone_name:
            result["unavailable_reason"] = "timezone_unavailable"
            return result
        try:
            zone = ZoneInfo(timezone_name)
        except Exception:
            result["unavailable_reason"] = "timezone_unavailable"
            return result
        selected = [
            record for record in records
            if (timestamp := _parse_evaluation_timestamp(record.get("valid_at"))) is not None
            and timestamp.astimezone(zone).weekday() >= 5
        ]
    elif name == "cold":
        result["unavailable_reason"] = "temperature_input_missing"
        return result
    elif name == "anomaly":
        result["unavailable_reason"] = "explicit_anomaly_classification_missing"
        return result
    else:
        result["unavailable_reason"] = "normal_classifier_contract_missing"
        return result
    result["support_count"] = len(selected)
    result["eligible_count"] = len(selected)
    result["coverage"] = len(selected) / len(records) if records else 0.0
    if not selected:
        result["unavailable_reason"] = "no_matured_observations"
        return result
    errors = [float(record["signed_error_w"]) for record in selected]
    actual_total = sum(float(record["actual_w"]) for record in selected)
    result["mae_w"] = sum(abs(error) for error in errors) / len(errors)
    result["bias_w"] = sum(errors) / len(errors)
    if actual_total > 1:
        result["wape"] = sum(abs(error) for error in errors) / actual_total
    else:
        result["unavailable_reason"] = "zero_or_near_zero_actual_denominator"
    return result


def build_forecast_evaluation(
    frames: list[dict[str, Any]], actual_rows: list[dict[str, Any]], decision_at: datetime, site_id: str,
    timezone_name: str | None = None, provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score frozen forecast revisions only against later qualified actuals."""
    scoped_actuals = {
        row["interval_start"]: row for row in actual_rows
        if row.get("site_id") in {None, site_id}
        and row.get("logical_role") == "house.consumption"
        and isinstance(row.get("interval_start"), datetime)
    }
    actual_by_start = {key: row for key, row in scoped_actuals.items() if _qualified_actual(row, decision_at)}
    records = []
    matured_count = 0
    no_observation_count = 0
    ineligible_actual_count = 0
    hindsight_count = 0
    for frame in frames:
        if frame.get("site_id") != site_id or frame.get("payload_schema") != PAYLOAD_SCHEMA:
            continue
        frame_known_at = frame.get("known_at")
        for point in frame.get("points") or []:
            valid_at = point.get("valid_at")
            if not isinstance(valid_at, datetime) or valid_at >= decision_at:
                continue
            if not isinstance(frame_known_at, datetime) or frame_known_at >= valid_at:
                hindsight_count += 1
                continue
            matured_count += 1
            actual = actual_by_start.get(valid_at)
            if actual is None:
                if valid_at not in scoped_actuals:
                    no_observation_count += 1
                else:
                    ineligible_actual_count += 1
                continue
            detail = point.get("point") or {}
            predicted = float(detail.get("corrected_forecast_w", point.get("value")))
            actual_value = float(actual["value"])
            signed_error = actual_value - predicted
            relative = abs(signed_error) / actual_value if actual_value > 1 else None
            if relative is None:
                classification = "within_expected_error" if abs(signed_error) <= 100 else "isolated_spike_or_event"
            elif relative <= 0.15:
                classification = "within_expected_error"
            elif signed_error < 0:
                classification = "systematic_overprediction"
            else:
                classification = "systematic_underprediction"
            records.append({
                "site_id": site_id, "frame_id": frame.get("frame_id"), "revision": frame.get("revision"),
                "forecast_known_at": frame.get("known_at").isoformat() if isinstance(frame.get("known_at"), datetime) else frame.get("known_at"),
                "valid_at": valid_at.isoformat(), "model_version": detail.get("model_version") or frame.get("quality", {}).get("model_version"),
                "source_method": detail.get("support_method"), "sample_support": detail.get("sample_support"),
                "predicted_w": predicted, "predicted_energy_kwh": predicted * 0.25 / 1000.0,
                "baseline_w": detail.get("baseline_w"), "corrected_forecast_w": predicted,
                "actual_w": actual_value, "actual_energy_kwh": actual_value * 0.25 / 1000.0,
                "signed_error_w": signed_error,
                "absolute_error_w": abs(signed_error), "relative_error": relative,
                "actual_quality": {
                    "quality_status": actual.get("quality_status"),
                    "coverage_ratio": actual.get("coverage_ratio"),
                    "gap_status": actual.get("gap_status"),
                    "anomaly_classification": actual.get("anomaly_classification"),
                },
                "learning_eligible": True, "learning_reason": "qualified_actual_observed", "error_classification": classification,
            })
    records = sorted(records, key=lambda item: (item["valid_at"], item["frame_id"] or "", item["revision"] or 0))[-256:]
    errors = [item["signed_error_w"] for item in records]
    actual_total = sum(item["actual_w"] for item in records)
    def scorecard(prediction_key: str, selected: list[dict[str, Any]]) -> dict[str, Any]:
        usable = [item for item in selected if isinstance(item.get(prediction_key), (int, float))]
        selected_errors = [item["actual_w"] - item[prediction_key] for item in usable]
        denominator = sum(item["actual_w"] for item in usable)
        return {
            "count": len(usable),
            "mean_signed_bias_w": sum(selected_errors) / len(selected_errors) if selected_errors else None,
            "median_signed_bias_w": median(selected_errors) if selected_errors else None,
            "mae_w": sum(abs(error) for error in selected_errors) / len(selected_errors) if selected_errors else None,
            "wape": sum(abs(error) for error in selected_errors) / denominator if denominator > 1 else None,
        }
    recent_records = records[-32:]
    frame_provenance = provenance or {}
    evaluation_provenance = {
        "model_version": frame_provenance.get("model_version") or MODEL_VERSION,
        "training_dataset_version": frame_provenance.get("training_dataset_version") or TRAINING_DATASET_VERSION,
        "parameter_config_version": frame_provenance.get("parameter_config_version") or PARAMETER_CONFIG_VERSION,
        "parameter_config_hash": frame_provenance.get("parameter_config_hash"),
        "site_calibration_version": frame_provenance.get("site_calibration_version"),
    }
    segments = {
        name: _segment_metric(name, records, evaluation_provenance, timezone_name)
        for name in ("weekend", "cold", "anomaly", "normal")
    }
    return {
        "schema": "ella_forecast_evaluation.v1", "site_id": site_id,
        "model_version": evaluation_provenance["model_version"], "known_at": decision_at.isoformat(),
        "segment_contract": {"schema": SEGMENT_SCHEMA, "classifier_version": SEGMENT_CLASSIFIER_VERSION},
        "provenance": evaluation_provenance,
        "summary": {
            "count": len(records), "matured_count": matured_count,
            "learning_eligible_count": len(records), "ineligible_actual_count": ineligible_actual_count,
            "mean_signed_bias_w": sum(errors) / len(errors) if errors else None,
            "median_signed_bias_w": median(errors) if errors else None,
            "mae_w": sum(abs(error) for error in errors) / len(errors) if errors else None,
            "wape": sum(abs(error) for error in errors) / actual_total if actual_total > 1 else None,
            "no_observation_count": no_observation_count,
            "hindsight_excluded_count": hindsight_count,
        },
        "baseline_scorecard": scorecard("baseline_w", records),
        "corrected_scorecard": scorecard("corrected_forecast_w", records),
        "recent_scorecard": scorecard("corrected_forecast_w", recent_records),
        "segments": segments,
        "records": records,
        "learning_eligibility": {"forecast": bool(records), "reason": "qualified_actual_observed" if records else ("no_observation" if no_observation_count else "insufficient_actual_quality")},
        "planner_quality": {"status": "not_evaluable", "reason": "no_stage5_counterfactual_or_execution_evidence"},
        "execution_quality": {"status": "NOT_APPLICABLE", "reason": "no_actuator_execution_in_stage_5"},
        "counterfactual": {
            "schema": "ella_counterfactual_evaluation.v1", "status": "counterfactual_unavailable",
            "eligible": False, "actual_observed": True, "simulated_plan_followed": None,
            "missing_reasons": ["no_configured_individual_loads", "ess_policy_constraints_incomplete"],
        },
    }


def build_historical_model_points(
    history: list[dict[str, Any]],
    timezone_name: str,
    target_start: datetime,
    target_end: datetime,
) -> list[dict[str, Any]]:
    """Return supported model estimates using the canonical forecast profile."""
    profile = _profile_buckets(history, timezone_name)
    if profile is None or target_start.tzinfo is None or target_end.tzinfo is None:
        return []
    zone, by_weekday_slot, by_slot = profile
    points = []
    cursor = _quarter_start(target_start)
    while cursor < target_end:
        local = cursor.astimezone(zone)
        slot = local.hour * 4 + local.minute // 15
        candidates = by_weekday_slot.get((local.weekday(), slot), [])
        support = "weekday_slot"
        if not candidates:
            candidates = by_slot.get(slot, [])
            support = "all_weekdays_slot"
        if candidates:
            values = [value for value, _row in candidates]
            source_generations = sorted({str(row.get("source_generation_id")) for _value, row in candidates if row.get("source_generation_id")})
            points.append({
                "valid_at": cursor,
                "value": sum(values) / len(values),
                "unit": "W",
                "frame_id": None,
                "quality": {"status": "model", "sample_support": len(values), "support_method": support},
                "source_generation_id": source_generations[0] if len(source_generations) == 1 else None,
                "source_generation_ids": source_generations,
                "source": "model",
            })
        cursor += timedelta(seconds=SLOT_SECONDS)
    return points


def build_load_forecast_frame(
    site_id: str,
    timezone_name: str,
    history: list[dict[str, Any]],
    known_at: datetime,
    horizon_hours: int = 36,
    persistent_calibration: dict[str, Any] | None = None,
    global_prior_calibration: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Build a 15-minute forecast only from observed canonical load points.

    A target is omitted when no comparable historical support exists. No zero
    values are used as an unknown-data placeholder.
    """
    if not site_id or not isinstance(history, list) or known_at.tzinfo is None:
        return None, []
    try:
        zone = ZoneInfo(timezone_name)
    except Exception:
        return None, []
    rows = [row for row in history if row.get("logical_role") == "house.consumption"
            and row.get("value") is not None and row.get("quality_status") in {"good", "partial"}]
    if not rows:
        return None, []
    observed_days = {row["interval_start"].astimezone(zone).date() for row in rows}
    if len(observed_days) < MIN_DISTINCT_DAYS:
        return None, []
    source_generations = {str(row["source_generation_id"]) for row in rows if row.get("source_generation_id")}
    if not source_generations:
        return None, []
    local_today = known_at.astimezone(zone).date()
    baseline_rows = [
        row for row in rows
        if isinstance(row.get("interval_start"), datetime)
        and row["interval_start"].astimezone(zone).date() != local_today
    ]
    profile = _profile_buckets(baseline_rows, timezone_name)
    if profile is None:
        return None, []
    _zone, by_weekday_slot, by_slot = profile
    target_start = _quarter_start(known_at.astimezone(zone) + timedelta(minutes=15)).astimezone(timezone.utc)
    target_end = target_start + timedelta(hours=horizon_hours)
    calibration = _intraday_calibration(history, timezone_name, known_at)
    points: list[dict[str, Any]] = []
    cursor = target_start
    while cursor < target_end:
        local = cursor.astimezone(zone)
        slot = local.hour * 4 + local.minute // 15
        candidates = by_weekday_slot.get((local.weekday(), slot), [])
        support = "weekday_slot"
        if not candidates:
            candidates = by_slot.get(slot, [])
            support = "all_weekdays_slot"
        if candidates:
            baseline = sum(item[0] for item in candidates) / len(candidates)
            persistent_key = f"{local.weekday()}:{slot}"
            persistent = (persistent_calibration or {}).get("by_slot", {}).get(persistent_key, {})
            global_prior = (global_prior_calibration or {}).get("by_slot", {}).get(
                f"slot:{slot}", {}
            )
            use_site = isinstance(persistent, dict) and int(persistent.get("evidence_count", 0) or 0) >= 3
            selected_calibration = persistent if use_site else (global_prior if isinstance(global_prior, dict) else {})
            persistent_factor = float(selected_calibration.get("factor", 1.0))
            calibration_scope = "site" if use_site else ("global_prior" if selected_calibration else "none")
            value = baseline * persistent_factor * calibration["factor"]
            points.append({
                "point_id": "", "point_key": cursor.isoformat(), "valid_at": cursor,
                "value": value, "unit": "W", "quality_status": "good",
                "point": {"forecast_w": value, "baseline_w": baseline,
                          "corrected_forecast_w": value, "intraday_factor": calibration["factor"],
                          "persistent_factor": persistent_factor,
                          "persistent_calibration_evidence_count": persistent.get("evidence_count", 0) if isinstance(persistent, dict) else 0,
                          "calibration_scope": calibration_scope,
                          "global_prior_evidence_count": global_prior.get("evidence_count", 0) if isinstance(global_prior, dict) and calibration_scope == "global_prior" else 0,
                          "global_prior_fingerprint": (global_prior_calibration or {}).get("provenance", {}).get("fingerprint") if calibration_scope == "global_prior" else None,
                          "correction_evidence_count": calibration["evidence_count"],
                          "confidence_status": calibration["confidence"],
                          "sample_support": len(candidates), "support_method": support,
                          "model_version": MODEL_VERSION, "calibration_reason": calibration["reason"]},
            })
        cursor += timedelta(seconds=SLOT_SECONDS)
    if not points:
        return None, []
    calibration_identity = {
        "factor": calibration["factor"], "evidence_count": calibration["evidence_count"],
        "evidence": [item["valid_at"] for item in calibration.get("evidence", [])],
        "persistent": (persistent_calibration or {}).get("by_slot", {}),
        "global_prior": (global_prior_calibration or {}).get("provenance", {}),
    }
    generation_id = _generation_id(site_id, source_generations, calibration_identity)
    parameter_config_hash = _parameter_config_hash(horizon_hours)
    site_calibration_version = (persistent_calibration or {}).get("version") or "load-profile-v2-cross-day-v1"
    global_prior_provenance = (global_prior_calibration or {}).get("provenance", {})
    training_provenance = {
        "training_dataset_version": TRAINING_DATASET_VERSION,
        "parameter_config_version": PARAMETER_CONFIG_VERSION,
        "parameter_config_hash": parameter_config_hash,
        "model_version": MODEL_VERSION,
        "site_calibration_version": site_calibration_version,
        "global_model_version": (global_prior_calibration or {}).get("version"),
        "global_model_fingerprint": global_prior_provenance.get("fingerprint"),
    }
    semantic_key = f"{DATASET}|site:{site_id}|generation:{generation_id}|target:{target_start.date().isoformat()}"
    # Canonical quality_status is schema-bound; retain confidence detail in
    # the quality object instead of introducing a non-canonical status value.
    quality_status = "good" if all(point["point"]["sample_support"] >= 2 for point in points) else "partial"
    confidence_status = "good" if quality_status == "good" else "low_confidence"
    quality = {
        "status": confidence_status, "model_version": MODEL_VERSION,
        **training_provenance,
        "sample_support_min": min(point["point"]["sample_support"] for point in points),
        "sample_support_max": max(point["point"]["sample_support"] for point in points),
        "observed_days": len(observed_days), "source_generations": sorted(source_generations),
        "intraday_factor": calibration["factor"], "intraday_evidence_count": calibration["evidence_count"],
        "intraday_confidence": calibration["confidence"], "intraday_reason": calibration["reason"],
        "intraday_evidence": calibration.get("evidence", []),
        "persistent_calibration": persistent_calibration or {"version": "load-profile-v2-cross-day-v1", "by_slot": {}, "sample_count": 0},
        "global_prior_calibration": global_prior_calibration or {"version": "load-profile-v2-global-prior-v1", "by_slot": {}, "available": False},
    }
    content = json.dumps([{key: value for key, value in point.items() if key != "point_id"}
                          for point in points], sort_keys=True, default=str, separators=(",", ":"))
    frame_id = "frame-" + hashlib.sha256((semantic_key + "|" + content).encode()).hexdigest()[:32]
    for index, point in enumerate(points, 1):
        point["point_id"] = f"{frame_id}-p{index:03d}"
    frame = {
        "frame_id": frame_id, "schema_version": 1, "dataset_version": 1,
        "semantic_key": semantic_key, "revision": 1, "supersedes_frame_id": None,
        "source_generation_id": generation_id, "source_scope": "site", "site_id": site_id,
        "logical_role": LOGICAL_ROLE, "classification": "forecast", "published_at": None,
        "fetched_at": None, "known_at": known_at.astimezone(timezone.utc),
        "captured_at": known_at.astimezone(timezone.utc), "valid_from": target_start,
        "valid_to": target_end, "quality_status": quality_status, "quality": quality,
        "provenance": {"origin_type": "canonical_energy_observations", "site_id": site_id,
                        "model_version": MODEL_VERSION, "source_generations": sorted(source_generations),
                        "intraday_calibration": calibration,
                        "global_prior": (global_prior_calibration or {}).get("provenance", {}),
                        **training_provenance,
                        "capture_contract": PAYLOAD_SCHEMA}, "payload_schema": PAYLOAD_SCHEMA,
    }
    return frame, points


def persist_load_forecast(storage: CanonicalStorage, frame: dict[str, Any], points: list[dict[str, Any]], captured_at: datetime) -> bool:
    """Persist one immutable forecast revision using existing canonical storage."""
    storage.ensure_source_generation({
        "site_id": frame["site_id"], "logical_role": frame["logical_role"],
        "generation_id": frame["source_generation_id"],
        "source_identity": {"identity_key": frame["source_generation_id"], "identity_strength": "strong",
                             "identity_provenance": "canonical_load_observation_profile"},
        # The storage contract describes the 15-minute source buckets used by
        # this profile; derived provenance is carried separately below.
        "source_resolution_kind": "native_bucket", "source_resolution_seconds": SLOT_SECONDS,
        "timezone_state": "verified",
    }, captured_at)
    latest = storage.latest_external_frame(frame["semantic_key"])
    if latest:
        frame["revision"] = latest[1]
        frame["frame_id"] = latest[0]
        frame["supersedes_frame_id"] = latest[2]
        try:
            return storage.insert_external_frame(frame, points)
        except ValueError as error:
            if str(error) != "canonical_frame_revision_conflict":
                raise
            frame["revision"] = latest[1] + 1
            frame["supersedes_frame_id"] = latest[0]
            digest = hashlib.sha256((frame["semantic_key"] + "|" + str(frame["revision"]) + "|" + json.dumps([point["point"] for point in points], sort_keys=True)).encode()).hexdigest()[:32]
            frame["frame_id"] = "frame-" + digest
            for index, point in enumerate(points, 1):
                point["point_id"] = f"{frame['frame_id']}-p{index:03d}"
            return storage.insert_external_frame(frame, points)
    return storage.insert_external_frame(frame, points)


def build_site_load_forecast(storage: CanonicalStorage, site_id: str, timezone_name: str, now: datetime, persistent_calibration: dict[str, Any] | None = None, global_prior_calibration: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build and persist one site's forecast without active-site dependence."""
    history = storage.read_site_energy_history(site_id, now - timedelta(days=60), now)
    previous_frames = storage.read_external_input_frames(
        now, source_scope="site", site_id=site_id, logical_role=LOGICAL_ROLE,
    )
    frame, points = build_load_forecast_frame(
        site_id, timezone_name, history, now,
        persistent_calibration=persistent_calibration,
        global_prior_calibration=global_prior_calibration,
    )
    if frame is None:
        evaluation = build_forecast_evaluation(previous_frames, history, now, site_id, timezone_name=timezone_name)
        return {"site_id": site_id, "available": False, "reason": "insufficient_historical_support", "point_count": 0, "evaluation": evaluation}
    evaluation = build_forecast_evaluation(
        previous_frames, history, now, site_id, timezone_name=timezone_name,
        provenance=frame.get("quality") or frame.get("provenance"),
    )
    written = persist_load_forecast(storage, frame, points, now)
    return {
        "site_id": site_id, "available": True, "frame_id": frame["frame_id"],
        "semantic_key": frame["semantic_key"], "revision": frame["revision"],
        "point_count": len(points), "quality_status": frame["quality_status"],
        "known_at": frame["known_at"].isoformat(), "written": bool(written),
        "model_version": MODEL_VERSION, "evaluation": evaluation, "calibration": frame["quality"],
    }
