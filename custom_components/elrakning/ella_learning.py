"""Bounded, site-scoped Stage 5 evaluation and calibration state."""

from __future__ import annotations

from typing import Any

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
