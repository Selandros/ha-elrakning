"""Canonical external input frame producers."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from .canonical_storage import DATASET_VERSION, SCHEMA_VERSION, CanonicalStorage


def build_nord_pool_frame(
    data: Any,
    binding: dict[str, Any],
    captured_at: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Normalize one real Nord Pool response into a global immutable frame."""
    if not data.periods or not binding.get("config_entry_id") or not data.area or not data.currency:
        raise ValueError("nord_pool_frame_inputs_missing")
    captured_at = captured_at.astimezone(timezone.utc)
    entry_id = str(binding["config_entry_id"])
    area = str(data.area)
    currency = str(data.currency)
    identity_key = f"nord_pool|{entry_id}|{area}|{currency}"
    generation_id = "np-" + hashlib.sha256(identity_key.encode()).hexdigest()[:32]
    semantic_key = f"global|market.price.energy|{identity_key}|{data.date.isoformat()}"
    valid_from = min(period.start for period in data.periods).astimezone(timezone.utc)
    valid_to = max(period.end for period in data.periods).astimezone(timezone.utc)
    frame_id = "frame-" + hashlib.sha256(
        (
            f"{semantic_key}|" +
            "|".join(f"{p.start.isoformat()}={p.price:.12g}" for p in data.periods)
        ).encode()
    ).hexdigest()[:32]
    frame = {
        "frame_id": frame_id,
        "schema_version": SCHEMA_VERSION,
        "dataset_version": DATASET_VERSION,
        "semantic_key": semantic_key,
        "revision": 1,
        "source_generation_id": generation_id,
        "source_scope": "global",
        "site_id": None,
        "logical_role": "market.price.energy",
        "classification": "published",
        "published_at": None,
        "fetched_at": captured_at,
        "known_at": captured_at,
        "captured_at": captured_at,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "quality_status": "good",
        "quality": {"status": "good", "period_count": len(data.periods)},
        "provenance": {
            "origin_type": "home_assistant_nord_pool_service",
            "config_entry_id": entry_id,
            "area": area,
            "currency": currency,
            "requested_date": data.date.isoformat(),
            "resolution_minutes": 15,
        },
        "payload_schema": "nord_pool.price_periods.v1",
    }
    points = [
        {
            "point_id": f"{frame_id}-p{index:03d}",
            "point_key": period.start.astimezone(timezone.utc).isoformat(),
            "valid_at": period.start.astimezone(timezone.utc),
            "value": period.price,
            "unit": f"{currency}/kWh",
            "quality_status": "good",
            "point": {"start": period.start.astimezone(timezone.utc).isoformat(), "end": period.end.astimezone(timezone.utc).isoformat()},
        }
        for index, period in enumerate(data.periods)
    ]
    return frame, points


def persist_nord_pool_frame(storage: CanonicalStorage, data: Any, binding: dict[str, Any], captured_at: datetime) -> bool:
    """Persist one real Nord Pool frame without changing price semantics."""
    frame, points = build_nord_pool_frame(data, binding, captured_at)
    storage.ensure_global_source_generation(
        {
            "generation_id": frame["source_generation_id"],
            "logical_role": frame["logical_role"],
            "source_identity": {
                "identity_key": f"nord_pool|{binding['config_entry_id']}|{data.area}|{data.currency}",
                "identity_strength": "strong",
                "identity_provenance": "home_assistant_config_entry_and_area",
            },
            "source_resolution_kind": "native_bucket",
            "source_resolution_seconds": 900,
            "timezone_state": "verified",
        },
        captured_at,
    )
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
            frame["frame_id"] = "frame-" + hashlib.sha256(
                (
                    f"{frame['semantic_key']}|{frame['revision']}|" +
                    "|".join(point["point_key"] + f"={point['value']:.12g}" for point in points)
                ).encode()
            ).hexdigest()[:32]
    return storage.insert_external_frame(frame, points)
