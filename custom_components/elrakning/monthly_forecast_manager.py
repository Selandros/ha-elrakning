"""Runtime coordinator for the causal monthly cost forecast contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .monthly_forecast import build_monthly_cost_forecast


class MonthlyForecastManager:
    """Bounded runtime bridge; it never runs from a frontend render."""

    def __init__(self, learning_store) -> None:
        self.learning_store = learning_store
        self._latest: dict[str, dict[str, Any]] = {}
        self._last_fingerprint: dict[str, str] = {}
        self._last_refresh: dict[str, datetime] = {}
        self._last_sources: dict[str, tuple[str, ...]] = {}

    async def async_refresh(
        self,
        *,
        site_id: str,
        timezone_name: str,
        decision_at: datetime,
        target_month: str,
        actual_cost_to_date_sek: float | None,
        actual_import_to_date_kwh: float | None,
        future_points: list[dict[str, Any]],
        price_periods: list[dict[str, Any]],
        remaining_fixed_cost_sek: float = 0.0,
        source_generations: list[str] | None = None,
        calibration: dict[str, Any] | None = None,
        weather: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current_sources = tuple(sorted(str(item) for item in (source_generations or []) if item))
        previous_refresh = self._last_refresh.get(site_id)
        if previous_refresh is not None and decision_at.astimezone(timezone.utc) - previous_refresh < timedelta(hours=1) and current_sources == self._last_sources.get(site_id):
            return dict(self._latest.get(site_id) or self.public_state(site_id))
        result = build_monthly_cost_forecast(
            site_id=site_id,
            timezone_name=timezone_name,
            decision_at=decision_at,
            target_month=target_month,
            actual_cost_to_date_sek=actual_cost_to_date_sek,
            actual_import_to_date_kwh=actual_import_to_date_kwh,
            future_points=future_points,
            price_periods=price_periods,
            remaining_fixed_cost_sek=remaining_fixed_cost_sek,
            source_generations=source_generations,
            calibration=calibration,
            weather=weather,
        )
        result["forecast_method"] = "causal_slotwise_monthly" if result.get("available") else "legacy_explicit_fallback_required"
        result["near_term_slot_count"] = len(future_points)
        result["fallback_slot_count"] = int(result.get("missing_slot_count") or 0)
        result["weather_corrected_slot_count"] = 0
        result["weather_support_count"] = int((weather or {}).get("support_count") or 0)
        result["optimizer_slot_count"] = 0
        result["self_consumption_slot_count"] = 0
        result["uncertainty"] = {"available": False, "reason": "monthly_residual_support_missing"}
        previous = self._latest.get(site_id)
        self._latest[site_id] = result
        self._last_refresh[site_id] = decision_at.astimezone(timezone.utc)
        self._last_sources[site_id] = current_sources
        fingerprint = result.get("fingerprint")
        if fingerprint and fingerprint != self._last_fingerprint.get(site_id):
            await self.learning_store.async_record_monthly_forecast(site_id, result)
            self._last_fingerprint[site_id] = fingerprint
        return result

    def public_state(self, site_id: str) -> dict[str, Any]:
        result = dict(self._latest.get(site_id) or {
            "schema": "ella_monthly_cost_forecast.v1",
            "site_id": site_id,
            "available": False,
            "quality": "unavailable",
            "forecast_method": "legacy_explicit_fallback_required",
            "reasons": ["monthly_forecast_not_run"],
            "execution_eligible": False,
            "actuator_writes_enabled": False,
        })
        result["last_evaluation"] = (self.learning_store.monthly_forecast_state(site_id).get("evaluations") or [])[-1:] or None
        result["snapshot"] = self.learning_store.monthly_forecast_state(site_id).get("latest")
        return result

    async def async_evaluate_matured_days(self, site_id: str, actual_by_day: dict[str, float]) -> dict[str, Any]:
        """Evaluate each matured forecast day once; no calibration without support."""
        state = self.learning_store.monthly_forecast_state(site_id)
        snapshot = state.get("latest") if isinstance(state, dict) else None
        if not isinstance(snapshot, dict):
            return {"evaluated": 0, "reason": "no_monthly_forecast"}
        evaluations = state.get("evaluations") or []
        existing = {(item.get("forecast_fingerprint"), item.get("actual_day")) for item in evaluations if isinstance(item, dict)}
        count = 0
        for day, forecast in (snapshot.get("per_day") or {}).items():
            if day not in actual_by_day or (snapshot.get("fingerprint"), day) in existing:
                continue
            predicted = float(forecast.get("import_kwh"))
            actual = float(actual_by_day[day])
            evaluation = {
                "schema": "ella_monthly_cost_evaluation.v1",
                "site_id": site_id,
                "forecast_fingerprint": snapshot.get("fingerprint"),
                "actual_day": day,
                "predicted_import_kwh": predicted,
                "actual_import_kwh": actual,
                "signed_error_kwh": actual - predicted,
                "absolute_error_kwh": abs(actual - predicted),
                "percentage_error": (actual - predicted) / actual * 100 if actual else None,
                "learning_eligible": False,
                "learning_reason": "monthly_calibration_support_missing",
            }
            await self.learning_store.async_record_monthly_evaluation(site_id, evaluation)
            count += 1
        return {"evaluated": count, "sample_count": len(state.get("evaluations") or [])}
