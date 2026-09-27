"""Bounded, site-scoped Stage 5 evaluation and calibration state."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.helpers.storage import Store

from .ella_learning_governance import build_learning_governance


SCHEMA = "ella_learning_state.v1"
STORE_KEY = "elrakning.ella_learning"
STORE_VERSION = 1
MAX_RECORDS_PER_SITE = 512
POWER_EVIDENCE_SCHEMA = "ella_power_forecast_learning.v2"
POWER_CALIBRATION_VERSION = "battery-behavior-profile-v2-error-calibration-v1"
MAX_POWER_FORECASTS_PER_SITE = 256
MAX_POWER_RECORDS_PER_SITE = 4096
MAX_MONTHLY_FORECASTS_PER_SITE = 96
MAX_MONTHLY_EVALUATIONS_PER_SITE = 512
POWER_CALIBRATION_MIN_SUPPORT = 3
POWER_CALIBRATION_MIN_PREDICTED_W = 100.0
POWER_CALIBRATION_MIN_FACTOR = 0.8
POWER_CALIBRATION_MAX_FACTOR = 1.2


class EllaLearningStore:
    """Persist evaluation evidence without sharing calibration between sites."""

    def __init__(self, hass) -> None:
        self.store = Store(hass, STORE_VERSION, STORE_KEY)
        self.state: dict[str, Any] = {"schema": SCHEMA, "version": 1, "sites": {}}

    async def async_load(self) -> None:
        cached = await self.store.async_load()
        if isinstance(cached, dict) and cached.get("schema") == SCHEMA and isinstance(cached.get("sites"), dict):
            self.state = {"schema": SCHEMA, "version": 1, "sites": cached["sites"]}
            self._drop_legacy_power_records()

    def _drop_legacy_power_records(self) -> None:
        """Discard pre-v2 per-series power records without touching load learning."""
        for site in self.state.get("sites", {}).values():
            if not isinstance(site, dict):
                continue
            records = site.get("power_records")
            if isinstance(records, list):
                site["power_records"] = [
                    record for record in records
                    if isinstance(record, dict) and isinstance(record.get("series"), dict)
                ]

    async def async_record(self, site_id: str, evaluation: dict[str, Any], calibration: dict[str, Any] | None = None) -> None:
        if not isinstance(site_id, str) or not site_id.strip():
            return
        site = self.state.setdefault("sites", {}).setdefault(site_id, {"records": [], "latest": {}})
        existing = {
            (item.get("frame_id"), item.get("revision"), item.get("valid_at")): item
            for item in site.get("records", []) if isinstance(item, dict)
        }
        for item in evaluation.get("records") or []:
            if isinstance(item, dict):
                key = (item.get("frame_id"), item.get("revision"), item.get("valid_at"))
                existing[key] = item
        records = sorted(existing.values(), key=lambda item: (
            item.get("valid_at") or "", item.get("frame_id") or "", item.get("revision") or 0,
        ))[-MAX_RECORDS_PER_SITE:]
        site["records"] = records
        site["latest"] = {"evaluation": evaluation, "calibration": calibration or {}}
        await self.store.async_save(self.state)

    async def async_record_monthly_forecast(self, site_id: str, forecast: dict[str, Any]) -> dict[str, Any]:
        """Persist one immutable monthly forecast by deterministic fingerprint."""
        if not isinstance(site_id, str) or not site_id.strip() or forecast.get("site_id") != site_id:
            return {"written": False, "reason": "site_scope_invalid"}
        fingerprint = forecast.get("fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            return {"written": False, "reason": "forecast_fingerprint_missing"}
        site = self.state.setdefault("sites", {}).setdefault(site_id, {"records": [], "latest": {}})
        snapshots = site.setdefault("monthly_forecasts", [])
        if any(item.get("fingerprint") == fingerprint for item in snapshots if isinstance(item, dict)):
            return {"written": False, "reason": "duplicate_fingerprint"}
        snapshots.append(json.loads(json.dumps(forecast, sort_keys=True, default=str)))
        snapshots[:] = sorted(snapshots, key=lambda item: (str(item.get("decision_at") or ""), str(item.get("fingerprint") or "")))[-MAX_MONTHLY_FORECASTS_PER_SITE:]
        await self.store.async_save(self.state)
        return {"written": True, "fingerprint": fingerprint}

    async def async_record_monthly_evaluation(self, site_id: str, evaluation: dict[str, Any]) -> dict[str, Any]:
        """Persist matured monthly cost evaluation without mutating forecasts."""
        if not isinstance(site_id, str) or not site_id.strip() or evaluation.get("site_id") != site_id:
            return {"written": False, "reason": "site_scope_invalid"}
        key = (evaluation.get("forecast_fingerprint"), evaluation.get("actual_month"))
        if not key[0] or not key[1]:
            return {"written": False, "reason": "evaluation_identity_missing"}
        site = self.state.setdefault("sites", {}).setdefault(site_id, {"records": [], "latest": {}})
        evaluations = site.setdefault("monthly_evaluations", [])
        if any((item.get("forecast_fingerprint"), item.get("actual_month")) == key for item in evaluations if isinstance(item, dict)):
            return {"written": False, "reason": "duplicate_evaluation"}
        evaluations.append(json.loads(json.dumps(evaluation, sort_keys=True, default=str)))
        evaluations[:] = sorted(evaluations, key=lambda item: (str(item.get("actual_month") or ""), str(item.get("forecast_fingerprint") or "")))[-MAX_MONTHLY_EVALUATIONS_PER_SITE:]
        await self.store.async_save(self.state)
        return {"written": True, "evaluation_key": key}

    def monthly_forecast_state(self, site_id: str) -> dict[str, Any]:
        site = self.state.get("sites", {}).get(site_id)
        if not isinstance(site, dict):
            return {"schema": "ella_monthly_cost_forecast.v1", "site_id": site_id, "available": False, "reason": "no_monthly_forecast"}
        snapshots = list(site.get("monthly_forecasts") or [])
        evaluations = list(site.get("monthly_evaluations") or [])
        return {
            "schema": "ella_monthly_cost_forecast.v1",
            "site_id": site_id,
            "available": bool(snapshots),
            "latest": snapshots[-1] if snapshots else None,
            "forecast_count": len(snapshots),
            "evaluation_count": len(evaluations),
            "evaluations": evaluations,
        }

    @staticmethod
    def _power_actual_qualified(row: dict[str, Any], site_id: str, now: datetime) -> bool:
        if row.get("site_id") != site_id or row.get("unit") != "W":
            return False
        start = row.get("interval_start")
        end = row.get("interval_end")
        try:
            value = float(row.get("value"))
            coverage = float(row.get("coverage_ratio"))
        except (TypeError, ValueError):
            return False
        return (
            isinstance(start, datetime) and isinstance(end, datetime)
            and start.tzinfo is not None and end.tzinfo is not None
            and end <= now and end > start
            and math.isfinite(value) and math.isfinite(coverage)
            and coverage >= 0.9
            and row.get("quality_status") in {"good", "partial"}
            and row.get("gap_status") not in {"unavailable", "stale", "unknown"}
        )

    @staticmethod
    def _power_forecast_id(site_id: str, forecast: dict[str, Any]) -> str:
        identity = {
            "schema": POWER_EVIDENCE_SCHEMA,
            "site_id": site_id,
            "known_at": forecast.get("known_at"),
            "horizon": forecast.get("horizon"),
            "series": {},
        }
        for series_name, series in sorted((forecast.get("series") or {}).items()):
            points = []
            for point in series.get("forecast_points") or []:
                points.append({
                    "valid_at": point.get("valid_at"),
                    "end_at": point.get("end_at"),
                    "value_w": point.get("value_w"),
                    "provenance": point.get("provenance") or {},
                })
            identity["series"][series_name] = points
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        return f"power-forecast-{digest[:32]}"

    @staticmethod
    def _power_actuals(
        actual_rows: list[dict[str, Any]],
        site_id: str,
        now: datetime,
        active_generations: dict[str, set[str]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        grouped: dict[str, dict[str, list[float]]] = {}
        quality_by_slot: dict[str, list[tuple[str, float]]] = {}
        active_generations = active_generations or {}
        solar_generations = set(active_generations.get("solar.production") or ())
        if not solar_generations:
            solar_generations = {
                str(row.get("source_generation_id")) for row in actual_rows
                if row.get("site_id") == site_id and row.get("logical_role") == "solar.production"
                and row.get("source_generation_id")
            }
        solar_by_slot: dict[str, set[str]] = {}
        ends_by_slot: dict[str, dict[str, datetime]] = {}
        singleton_roles = {"battery.power", "house.consumption", "grid.power/import"}
        for row in actual_rows:
            if not EllaLearningStore._power_actual_qualified(row, site_id, now):
                continue
            key = row["interval_start"].astimezone(timezone.utc).isoformat()
            role = row.get("logical_role")
            allowed = active_generations.get(str(role))
            if str(role) in singleton_roles and allowed and len(allowed) > 1:
                continue
            if allowed and str(row.get("source_generation_id")) not in allowed:
                continue
            quality_by_slot.setdefault(key, []).append((str(row.get("quality_status")), float(row.get("coverage_ratio"))))
            if role == "solar.production":
                solar_by_slot.setdefault(key, set()).add(str(row.get("source_generation_id")))
            grouped.setdefault(key, {}).setdefault(str(role), []).append(float(row["value"]))
            ends_by_slot.setdefault(key, {})[str(role)] = row["interval_end"].astimezone(timezone.utc)
        result: dict[str, dict[str, float]] = {}
        for key, roles in grouped.items():
            values: dict[str, float] = {}
            for role, items in roles.items():
                if role == "solar.production":
                    if solar_generations and solar_by_slot.get(key) != solar_generations:
                        continue
                    values["solar"] = sum(items)
                elif role == "house.consumption":
                    values["load"] = items[-1]
                elif role == "battery.power":
                    values["battery"] = items[-1]
                elif role == "grid.power/import":
                    values["grid"] = items[-1]
            if "grid" in values:
                values["import"] = max(0.0, values["grid"])
                values["export"] = max(0.0, -values["grid"])
            quality = quality_by_slot.get(key, [])
            values["_coverage_ratio"] = min((item[1] for item in quality), default=0.0)
            values["_quality_status"] = "partial" if any(item[0] == "partial" for item in quality) else "good"
            values["_ends"] = ends_by_slot.get(key, {})
            result[key] = values
        return result

    @staticmethod
    def _power_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
        by_series: dict[str, list[dict[str, Any]]] = {}
        by_context: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("series"), dict):
                continue
            for series, item in (record.get("series") or {}).items():
                if not isinstance(item, dict) or item.get("signed_error_w") is None:
                    continue
                entry = {**item, "series": series}
                by_series.setdefault(series, []).append(entry)
                context = record.get("battery_context_level") if series == "battery" else None
                if context:
                    by_context.setdefault(context, []).append(entry)

        def score(items: list[dict[str, Any]]) -> dict[str, Any]:
            errors = [float(item["signed_error_w"]) for item in items]
            actual_total = sum(abs(float(item["actual_w"])) for item in items)
            return {
                "support_count": len(items),
                "mean_signed_bias_w": sum(errors) / len(errors) if errors else None,
                "median_signed_bias_w": median(errors) if errors else None,
                "mae_w": sum(abs(error) for error in errors) / len(errors) if errors else None,
                "wape": sum(abs(error) for error in errors) / actual_total if actual_total > 1 else None,
            }

        return {
            "by_series": {key: score(items) for key, items in sorted(by_series.items())},
            "battery_by_context": {key: score(items) for key, items in sorted(by_context.items())},
            "support_count": len(records),
        }

    @classmethod
    def _power_calibration(cls, records: list[dict[str, Any]], known_at: datetime) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            battery = (record.get("series") or {}).get("battery")
            context = record.get("battery_context_level")
            if not isinstance(battery, dict) or not context or not str(context).startswith(("net_load_ratio", "near_zero_")):
                continue
            predicted = float(battery.get("predicted_w", 0.0))
            actual = float(battery.get("actual_w", 0.0))
            if abs(predicted) < POWER_CALIBRATION_MIN_PREDICTED_W or predicted * actual <= 0:
                continue
            grouped.setdefault(str(context), []).append(battery)
        by_context = {}
        for context, items in sorted(grouped.items()):
            ratios = [float(item["actual_w"]) / float(item["predicted_w"]) for item in items]
            raw = median(ratios)
            support = len(ratios)
            shrink = min(0.75, (support - 2) / 8) if support >= POWER_CALIBRATION_MIN_SUPPORT else 0.0
            factor = min(POWER_CALIBRATION_MAX_FACTOR, max(POWER_CALIBRATION_MIN_FACTOR, 1.0 + (raw - 1.0) * shrink))
            by_context[context] = {
                "factor": factor if support >= POWER_CALIBRATION_MIN_SUPPORT else 1.0,
                "raw_ratio_median": raw,
                "support_count": support,
                "prior_mae_w": sum(abs(float(item["signed_error_w"])) for item in items) / support,
                "prior_bias_w": sum(float(item["signed_error_w"]) for item in items) / support,
                "reason": "supported" if support >= POWER_CALIBRATION_MIN_SUPPORT else "insufficient_support",
                "model_version": POWER_CALIBRATION_VERSION,
            }
        return {"version": POWER_CALIBRATION_VERSION, "known_at": known_at.astimezone(timezone.utc).isoformat(), "by_context": by_context}

    async def async_record_power_forecast(
        self,
        site_id: str,
        forecast: dict[str, Any],
        actual_rows: list[dict[str, Any]],
        now: datetime,
        active_generations: dict[str, set[str]] | None = None,
    ) -> dict[str, Any]:
        """Persist causal forecast evidence and evaluate only matured observations."""
        if not site_id or forecast.get("site_id") != site_id or not forecast.get("known_at"):
            return {"written": False, "evaluated": 0, "calibration": self.persistent_power_calibration(site_id)}
        site = self.state.setdefault("sites", {}).setdefault(site_id, {"records": [], "latest": {}})
        self._drop_legacy_power_records()
        snapshots = site.setdefault("power_forecasts", [])
        forecast_id = self._power_forecast_id(site_id, forecast)
        snapshot = next((item for item in snapshots if item.get("forecast_id") == forecast_id), None)
        new_snapshot = snapshot is None
        if snapshot is None:
            snapshot = {
                "schema": POWER_EVIDENCE_SCHEMA,
                "forecast_id": forecast_id,
                "site_id": site_id,
                "model_version": (forecast.get("battery") or {}).get("model_version"),
                "model_kind": (forecast.get("battery") or {}).get("model_kind"),
                "known_at": forecast.get("known_at"),
                "horizon": forecast.get("horizon"),
                "execution_eligible": False,
                "actuator_writes_enabled": False,
                "points": {},
            }
            forecast_series = dict(forecast.get("series") or {})
            forecast_series["battery"] = forecast.get("battery") or {}
            for series_name, series in sorted(forecast_series.items()):
                for point in series.get("forecast_points") or []:
                    valid_at = point.get("valid_at")
                    try:
                        valid_dt = datetime.fromisoformat(str(valid_at).replace("Z", "+00:00"))
                        known_dt = datetime.fromisoformat(str(forecast.get("known_at")).replace("Z", "+00:00"))
                    except (TypeError, ValueError):
                        continue
                    if valid_dt.tzinfo is None or known_dt.tzinfo is None or known_dt >= valid_dt:
                        continue
                    slot_key = valid_dt.astimezone(timezone.utc).isoformat()
                    snapshot["points"].setdefault(slot_key, {})[series_name] = {
                            "predicted_w": float(point.get("value_w")),
                            "end_at": point.get("end_at"),
                            "provenance": point.get("provenance") or {},
                        }
            snapshots.append(snapshot)
        actuals = self._power_actuals(actual_rows, site_id, now, active_generations)
        records = site.setdefault("power_records", [])
        existing_keys = {item.get("valid_at") for item in records if isinstance(item, dict)}
        candidates: dict[str, tuple[datetime, str, dict[str, Any], dict[str, Any]]] = {}
        for retained in snapshots:
            try:
                retained_known_at = datetime.fromisoformat(str(retained.get("known_at")).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            for valid_at, point_series in (retained.get("points") or {}).items():
                try:
                    valid_dt = datetime.fromisoformat(str(valid_at).replace("Z", "+00:00"))
                except ValueError:
                    continue
                if retained_known_at >= valid_dt or valid_dt + timedelta(minutes=15) > now:
                    continue
                valid_key = valid_dt.astimezone(timezone.utc).isoformat()
                current = candidates.get(valid_key)
                candidate_key = (retained_known_at, str(retained.get("forecast_id") or ""))
                if current is None or candidate_key > (current[0], current[1]):
                    candidates[valid_key] = (retained_known_at, str(retained.get("forecast_id") or ""), retained, point_series)

        new_records = []
        for valid_at, (forecast_known_at, forecast_id, retained, point_series) in sorted(candidates.items()):
            if valid_at in existing_keys or valid_at not in actuals:
                continue
            try:
                valid_dt = datetime.fromisoformat(str(valid_at).replace("Z", "+00:00"))
            except ValueError:
                continue
            actual_values = actuals[valid_at]
            target_end = valid_dt + timedelta(minutes=15)
            series_results: dict[str, dict[str, Any]] = {}
            for series, predicted_point in point_series.items():
                actual_key = {"consumption": "load", "solar": "solar", "charging": None, "discharging": None}.get(series, series)
                if series == "battery":
                    actual_value = actual_values.get("battery")
                elif series in {"charging", "discharging"}:
                    signed = actual_values.get("battery")
                    actual_value = max(0.0, -signed) if series == "charging" and signed is not None else (max(0.0, signed) if signed is not None else None)
                else:
                    actual_value = actual_values.get(actual_key)
                actual_role = {"consumption": "house.consumption", "solar": "solar.production", "battery": "battery.power", "charging": "battery.power", "discharging": "battery.power", "import": "grid.power/import", "export": "grid.power/import"}.get(series, actual_key)
                actual_end = (actual_values.get("_ends") or {}).get(actual_role)
                if actual_value is None or actual_end != target_end:
                    continue
                predicted = float(predicted_point["predicted_w"])
                error = float(actual_value) - predicted
                provenance = predicted_point.get("provenance") or {}
                series_results[series] = {
                    "predicted_w": predicted,
                    "actual_w": float(actual_value),
                    "signed_error_w": error,
                    "absolute_error_w": abs(error),
                    "relative_error": abs(error) / abs(float(actual_value)) if abs(float(actual_value)) > 1 else None,
                    "provenance": provenance,
                }
            if series_results:
                battery_provenance = (series_results.get("battery") or {}).get("provenance") or {}
                new_records.append({
                    "schema": POWER_EVIDENCE_SCHEMA, "site_id": site_id,
                    "valid_at": valid_at, "end_at": target_end.isoformat(),
                    "forecast_id": forecast_id, "forecast_known_at": forecast_known_at.isoformat(),
                    "lead_seconds": int((valid_dt - forecast_known_at).total_seconds()),
                    "battery_context_level": battery_provenance.get("context_level"),
                    "series": series_results,
                    "actual_quality": {"quality_status": actual_values.get("_quality_status"), "coverage_ratio": actual_values.get("_coverage_ratio")},
                    "learning_eligible": True, "learning_reason": "qualified_canonical_actual",
                })
                existing_keys.add(valid_at)
        records.extend(new_records)
        records[:] = sorted(records, key=lambda item: (str(item.get("valid_at") or ""), item.get("forecast_id") or ""))[-MAX_POWER_RECORDS_PER_SITE:]
        pending_snapshots = []
        completed_snapshots = []
        for item in snapshots:
            future_target = False
            for valid_at in (item.get("points") or {}):
                try:
                    point_end = datetime.fromisoformat(str(valid_at).replace("Z", "+00:00")) + timedelta(minutes=15)
                except ValueError:
                    continue
                if point_end > now:
                    future_target = True
                    break
            (pending_snapshots if future_target else completed_snapshots).append(item)
        keep_completed = max(0, MAX_POWER_FORECASTS_PER_SITE - len(pending_snapshots))
        snapshots[:] = sorted(
            pending_snapshots + sorted(completed_snapshots, key=lambda item: (str(item.get("known_at") or ""), item.get("forecast_id") or ""))[-keep_completed:],
            key=lambda item: (str(item.get("known_at") or ""), item.get("forecast_id") or ""),
        )
        calibration = self._power_calibration(records, now)
        previous_calibration = site.get("power_calibration") or {}
        changed = json.dumps(previous_calibration, sort_keys=True) != json.dumps(calibration, sort_keys=True)
        site["power_calibration"] = calibration
        governance = build_learning_governance(site_id, records, calibration)
        site["learning_governance"] = governance
        site["power_latest"] = {
            "schema": POWER_EVIDENCE_SCHEMA, "site_id": site_id, "available": bool(records),
            "forecast_count": len(snapshots), "evaluation_count": len(records),
            "metrics": self._power_metrics(records), "calibration": calibration,
            "governance": governance,
        }
        await self.store.async_save(self.state)
        return {"written": new_snapshot, "evaluated": len(new_records), "calibration": calibration, "calibration_changed": changed, "forecast_id": forecast_id}

    def persistent_power_calibration(self, site_id: str, known_at: datetime | None = None) -> dict[str, Any]:
        site = self.state.get("sites", {}).get(site_id)
        if not isinstance(site, dict):
            return {"version": POWER_CALIBRATION_VERSION, "by_context": {}, "support_count": 0}
        return dict(site.get("power_calibration") or {"version": POWER_CALIBRATION_VERSION, "by_context": {}, "support_count": 0})

    def public_state(self, site_id: str, *, include_records: bool = False) -> dict[str, Any]:
        site = self.state.get("sites", {}).get(site_id)
        if not isinstance(site, dict):
            return {"schema": "ella_forecast_evaluation.v1", "site_id": site_id,
                    "available": False, "reason": "no_evaluation_history", "records": [],
                    "power_forecast": {"schema": POWER_EVIDENCE_SCHEMA, "site_id": site_id,
                                       "available": False, "reason": "no_power_forecast_evidence"}}
        latest = site.get("latest") if isinstance(site.get("latest"), dict) else {}
        evaluation = latest.get("evaluation") if isinstance(latest.get("evaluation"), dict) else {}
        result = dict(evaluation)
        power_latest = dict(site.get("power_latest") or {
            "schema": POWER_EVIDENCE_SCHEMA, "site_id": site_id, "available": False,
            "reason": "no_power_forecast_evidence",
        })
        if include_records:
            power_latest["records"] = list(site.get("power_records") or [])
        result.update({"schema": "ella_forecast_evaluation.v1", "site_id": site_id,
                       "available": bool(site.get("records")), "records": list(site.get("records") or []) if include_records else [],
                       "calibration": latest.get("calibration") or {},
                       "learning_governance": site.get("learning_governance") or {"schema": "ella_learning_governance.v1", "available": False, "reason": "no_learning_evidence"},
                       "power_forecast": power_latest})
        return result

    def persistent_calibration(self, site_id: str, timezone_name: str, known_at: datetime) -> dict[str, Any]:
        """Derive bounded prior-day bias factors without sharing sites."""
        site = self.state.get("sites", {}).get(site_id)
        if not isinstance(site, dict):
            return {"version": "load-profile-v2-cross-day-v1", "by_slot": {}, "sample_count": 0}
        try:
            zone = ZoneInfo(timezone_name)
        except Exception:
            return {"version": "load-profile-v2-cross-day-v1", "by_slot": {}, "sample_count": 0, "reason": "timezone_unavailable"}
        current_day = known_at.astimezone(zone).date()
        ratios: dict[str, list[float]] = {}
        for record in site.get("records", []):
            if not isinstance(record, dict) or record.get("learning_eligible") is not True:
                continue
            try:
                valid_at = datetime.fromisoformat(str(record["valid_at"]).replace("Z", "+00:00"))
                actual = float(record["actual_w"])
                baseline = float(record["baseline_w"])
            except (KeyError, TypeError, ValueError):
                continue
            if valid_at.tzinfo is None or valid_at.astimezone(zone).date() == current_day or baseline <= 1 or actual < 0:
                continue
            if not all(value == value and abs(value) != float("inf") for value in (actual, baseline)):
                continue
            local = valid_at.astimezone(zone)
            key = f"{local.weekday()}:{local.hour * 4 + local.minute // 15}"
            ratios.setdefault(key, []).append(actual / baseline)
        by_slot: dict[str, dict[str, Any]] = {}
        for key, values in sorted(ratios.items()):
            if len(values) < 3:
                continue
            raw_ratio = median(values)
            shrink = min(0.5, (len(values) - 2) / 8)
            factor = min(1.15, max(0.85, 1.0 + (raw_ratio - 1.0) * shrink))
            if abs(factor - 1.0) < 0.03:
                factor = 1.0
            by_slot[key] = {
                "factor": factor, "raw_ratio_median": raw_ratio,
                "evidence_count": len(values), "method": "prior_day_median_ratio",
            }
        return {
            "version": "load-profile-v2-cross-day-v1", "by_slot": by_slot,
            "sample_count": sum(item["evidence_count"] for item in by_slot.values()),
            "known_at": known_at.astimezone(timezone.utc).isoformat(),
        }
