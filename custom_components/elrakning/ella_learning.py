"""Bounded, site-scoped Stage 5 evaluation and calibration state."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.helpers.storage import Store


SCHEMA = "ella_learning_state.v1"
STORE_KEY = "elrakning.ella_learning"
STORE_VERSION = 1
MAX_RECORDS_PER_SITE = 512
POWER_EVIDENCE_SCHEMA = "ella_power_forecast_learning.v1"
POWER_CALIBRATION_VERSION = "battery-behavior-profile-v2-error-calibration-v1"
MAX_POWER_FORECASTS_PER_SITE = 256
MAX_POWER_RECORDS_PER_SITE = 1024
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
    def _power_actuals(actual_rows: list[dict[str, Any]], site_id: str, now: datetime) -> dict[str, dict[str, float]]:
        grouped: dict[str, dict[str, list[float]]] = {}
        quality_by_slot: dict[str, list[tuple[str, float]]] = {}
        solar_generations = {
            str(row.get("source_generation_id")) for row in actual_rows
            if row.get("site_id") == site_id and row.get("logical_role") == "solar.production"
            and row.get("source_generation_id")
        }
        solar_by_slot: dict[str, set[str]] = {}
        for row in actual_rows:
            if not EllaLearningStore._power_actual_qualified(row, site_id, now):
                continue
            key = row["interval_start"].astimezone(timezone.utc).isoformat()
            role = row.get("logical_role")
            quality_by_slot.setdefault(key, []).append((str(row.get("quality_status")), float(row.get("coverage_ratio"))))
            if role == "solar.production":
                solar_by_slot.setdefault(key, set()).add(str(row.get("source_generation_id")))
            grouped.setdefault(key, {}).setdefault(str(role), []).append(float(row["value"]))
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
            result[key] = values
        return result

    @staticmethod
    def _power_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
        by_series: dict[str, list[dict[str, Any]]] = {}
        by_context: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            by_series.setdefault(record["series"], []).append(record)
            context = record.get("context_level")
            if record["series"] == "battery" and context:
                by_context.setdefault(context, []).append(record)

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
            context = record.get("context_level")
            if record.get("series") != "battery" or not context or not str(context).startswith(("net_load_ratio", "near_zero_")):
                continue
            predicted = float(record.get("predicted_w", 0.0))
            actual = float(record.get("actual_w", 0.0))
            if abs(predicted) < POWER_CALIBRATION_MIN_PREDICTED_W or predicted * actual <= 0:
                continue
            grouped.setdefault(str(context), []).append(record)
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

    async def async_record_power_forecast(self, site_id: str, forecast: dict[str, Any], actual_rows: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
        """Persist causal forecast evidence and evaluate only matured observations."""
        if not site_id or forecast.get("site_id") != site_id or not forecast.get("known_at"):
            return {"written": False, "evaluated": 0, "calibration": self.persistent_power_calibration(site_id)}
        site = self.state.setdefault("sites", {}).setdefault(site_id, {"records": [], "latest": {}})
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
                    if valid_at and str(valid_at) > str(forecast.get("known_at")):
                        snapshot["points"].setdefault(str(valid_at), {})[series_name] = {
                            "predicted_w": float(point.get("value_w")),
                            "end_at": point.get("end_at"),
                            "provenance": point.get("provenance") or {},
                        }
            snapshots.append(snapshot)
            snapshots[:] = sorted(snapshots, key=lambda item: (str(item.get("known_at") or ""), item.get("forecast_id") or ""))[-MAX_POWER_FORECASTS_PER_SITE:]
        actuals = self._power_actuals(actual_rows, site_id, now)
        records = site.setdefault("power_records", [])
        existing_keys = {(item.get("forecast_id"), item.get("valid_at"), item.get("series")) for item in records}
        for valid_at, point_series in snapshot.get("points", {}).items():
            try:
                valid_dt = datetime.fromisoformat(str(valid_at).replace("Z", "+00:00"))
            except ValueError:
                continue
            if valid_dt >= now or valid_at not in actuals:
                continue
            actual_values = actuals[valid_at]
            for series, predicted_point in point_series.items():
                actual_key = {"consumption": "load", "solar": "solar", "charging": None, "discharging": None}.get(series, series)
                if series == "battery":
                    actual_value = actual_values.get("battery")
                elif series in {"charging", "discharging"}:
                    signed = actual_values.get("battery")
                    actual_value = max(0.0, -signed) if series == "charging" and signed is not None else (max(0.0, signed) if signed is not None else None)
                else:
                    actual_value = actual_values.get(actual_key)
                if actual_value is None:
                    continue
                predicted = float(predicted_point["predicted_w"])
                error = float(actual_value) - predicted
                key = (snapshot["forecast_id"], valid_at, series)
                if key in existing_keys:
                    continue
                provenance = predicted_point.get("provenance") or {}
                records.append({
                    "schema": POWER_EVIDENCE_SCHEMA, "forecast_id": snapshot["forecast_id"], "site_id": site_id,
                    "valid_at": valid_at, "series": series, "context_level": provenance.get("context_level"),
                    "forecast_known_at": snapshot.get("known_at"), "predicted_w": predicted,
                    "actual_w": float(actual_value), "signed_error_w": error, "absolute_error_w": abs(error),
                    "relative_error": abs(error) / abs(float(actual_value)) if abs(float(actual_value)) > 1 else None,
                    "actual_quality": {"quality_status": actual_values.get("_quality_status"), "coverage_ratio": actual_values.get("_coverage_ratio")},
                    "learning_eligible": True, "learning_reason": "qualified_canonical_actual",
                    "provenance": provenance,
                })
                existing_keys.add(key)
        records[:] = sorted(records, key=lambda item: (str(item.get("valid_at") or ""), item.get("forecast_id") or "", item.get("series") or ""))[-MAX_POWER_RECORDS_PER_SITE:]
        calibration = self._power_calibration(records, now)
        previous_calibration = site.get("power_calibration") or {}
        changed = json.dumps(previous_calibration, sort_keys=True) != json.dumps(calibration, sort_keys=True)
        site["power_calibration"] = calibration
        site["power_latest"] = {
            "schema": POWER_EVIDENCE_SCHEMA, "site_id": site_id, "available": bool(records),
            "forecast_count": len(snapshots), "evaluation_count": len(records),
            "metrics": self._power_metrics(records), "calibration": calibration,
        }
        await self.store.async_save(self.state)
        return {"written": new_snapshot, "evaluated": len(records), "calibration": calibration, "calibration_changed": changed, "forecast_id": forecast_id}

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
