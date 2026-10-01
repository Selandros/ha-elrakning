"""Deterministic reconciliation of site-scoped grid-import observations."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _is_eon(row: dict[str, Any]) -> bool:
    return (row.get("provenance") or {}).get("provider") == "eon"


def reconcile_grid_import(rows: list[dict[str, Any]], *, tolerance_kwh: float = 0.01) -> list[dict[str, Any]]:
    """Build a derived series without mutating source observations."""
    buckets: dict[tuple[Any, Any, Any, int], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"local": [], "provider": []})
    for row in rows:
        if row.get("logical_role") != "grid.energy_import" or row.get("quality_status") != "good" or row.get("gap_status") != "none":
            continue
        if row.get("value") is None or row.get("interval_start") is None or row.get("interval_end") is None:
            continue
        provenance = row.get("provenance") or {}
        if _is_eon(row) and (provenance.get("padded") is True or provenance.get("provider_actual") is not True):
            continue
        resolution = int(row.get("resolution_seconds") or 0)
        if resolution <= 0:
            continue
        buckets[(row.get("site_id"), row["interval_start"], row["interval_end"], resolution)]["provider" if _is_eon(row) else "local"].append(row)

    result = []
    for (site_id, start, end, resolution), sources in sorted(buckets.items(), key=lambda item: item[0]):
        local_row = sorted(sources["local"], key=lambda row: str(row.get("known_at") or ""))[-1:] or [None]
        provider_row = sorted(sources["provider"], key=lambda row: str(row.get("known_at") or ""))[-1:] or [None]
        local = local_row[0]
        provider = provider_row[0]
        value = None
        status = "unavailable"
        reason = "no_eligible_source"
        if local and provider:
            local_value = float(local["value"])
            provider_value = float(provider["value"])
            if abs(local_value - provider_value) > tolerance_kwh:
                status, reason = "conflict", "provider_discrepancy"
            elif (provider.get("provenance") or {}).get("settlement_authoritative") is True:
                status, reason, value = "provider_reconciled", "provider_reconciliation", provider_value
            else:
                status, reason, value = "local_primary", "within_tolerance", local_value
        elif local:
            status, reason, value = "local_primary", "local_p1", float(local["value"])
        elif provider:
            status, reason, value = "provider_gap_fill", "gap_fill", float(provider["value"])
        result.append({
            "site_id": site_id, "logical_role": "grid.energy_import",
            "interval_start": start, "interval_end": end, "resolution_seconds": resolution,
            "value": value, "unit": "kWh", "source_status": status,
            "correction_reason": reason, "local_record_id": (local or {}).get("record_id"),
            "provider_record_id": (provider or {}).get("record_id"),
            "local_value": float(local["value"]) if local else None,
            "provider_value": float(provider["value"]) if provider else None,
            "known_at": max((row.get("known_at") for row in (local, provider) if row and row.get("known_at")), default=None),
            "provenance": {"schema": "elrakning.grid_import_reconciliation.v1", "tolerance_kwh": tolerance_kwh, "site_id": site_id},
        })
    selected = []
    status_rank = {"conflict": 0, "provider_reconciled": 1, "local_primary": 2, "provider_gap_fill": 3, "unavailable": 4}
    for item in sorted(
        result,
        key=lambda value: (
            status_rank.get(value["source_status"], 9),
            int(value["resolution_seconds"]),
            value["interval_start"],
        ),
    ):
        if any(
            item["site_id"] == existing["site_id"]
            and item["interval_start"] < existing["interval_end"]
            and item["interval_end"] > existing["interval_start"]
            for existing in selected
        ):
            continue
        selected.append(item)
    return sorted(selected, key=lambda value: (value["site_id"], value["interval_start"]))
