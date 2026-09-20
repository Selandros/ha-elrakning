"""Bounded, site-scoped Stage 5 evaluation and calibration state."""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.helpers.storage import Store


SCHEMA = "ella_learning_state.v1"
STORE_KEY = "elrakning.ella_learning"
STORE_VERSION = 1
MAX_RECORDS_PER_SITE = 512


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

    def public_state(self, site_id: str, *, include_records: bool = False) -> dict[str, Any]:
        site = self.state.get("sites", {}).get(site_id)
        if not isinstance(site, dict):
            return {"schema": "ella_forecast_evaluation.v1", "site_id": site_id,
                    "available": False, "reason": "no_evaluation_history", "records": []}
        latest = site.get("latest") if isinstance(site.get("latest"), dict) else {}
        evaluation = latest.get("evaluation") if isinstance(latest.get("evaluation"), dict) else {}
        result = dict(evaluation)
        result.update({"schema": "ella_forecast_evaluation.v1", "site_id": site_id,
                       "available": bool(site.get("records")), "records": list(site.get("records") or []) if include_records else [],
                       "calibration": latest.get("calibration") or {}})
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
