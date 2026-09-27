"""Bounded immutable Step 9 replay artifacts and holdout qualification."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

try:
    import voluptuous as vol
    from homeassistant.helpers.storage import Store
except ModuleNotFoundError:  # pragma: no cover
    vol = None  # type: ignore[assignment]
    class Store:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass


SCHEMA = "ella_replay_artifact.v1"
STORE_KEY = "elrakning.replay_artifacts"
STORE_VERSION = 1
MAX_ARTIFACTS_PER_SITE = 128
MAX_EVIDENCE_SITES = 64
REQUIRED_HOLDOUTS = {"season", "site", "dst", "gap", "source_generation_change", "publication_cutoff"}
PUBLISH_SERVICE = "replay_artifact_publish"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def normalize_artifact(artifact: Any) -> dict[str, Any] | None:
    if not isinstance(artifact, dict) or artifact.get("schema") != SCHEMA:
        return None
    required = ("site_id", "decision_at", "horizon", "input_identity", "qualification", "scorecards", "artifact_id")
    if any(not artifact.get(key) for key in required):
        return None
    if not isinstance(artifact["site_id"], str) or not isinstance(artifact["scorecards"], dict):
        return None
    payload = {key: value for key, value in artifact.items() if key != "artifact_id"}
    if artifact["artifact_id"] != _fingerprint(payload):
        return None
    result = deepcopy(artifact)
    result["immutable"] = True
    return result


def build_artifact(
    run: dict[str, Any], *, dataset_identity: dict[str, Any], parameter_identity: dict[str, Any], holdouts: list[dict[str, Any]] | None = None
) -> dict[str, Any] | None:
    if not isinstance(run, dict) or not isinstance(dataset_identity, dict) or not isinstance(parameter_identity, dict):
        return None
    if not isinstance(run.get("site_id"), str) or not run.get("decision_at") or not run.get("qualification"):
        return None
    artifact = {
        "schema": SCHEMA,
        "site_id": run["site_id"],
        "decision_at": run["decision_at"],
        "horizon": {"slot_count": max((len(item.get("points", [])) for item in (run.get("baselines") or {}).values() if isinstance(item, dict)), default=0)},
        "run_fingerprint": run.get("run_fingerprint"),
        "dataset_identity": deepcopy(dataset_identity),
        "input_identity": deepcopy(run.get("input_identity") or {}),
        "model_identity": deepcopy((run.get("input_identity") or {}).get("model") or {}),
        "calibration_identity": deepcopy((run.get("input_identity") or {}).get("calibration") or {}),
        "parameter_identity": deepcopy(parameter_identity),
        "qualification": deepcopy(run["qualification"]),
        "scorecards": deepcopy(run.get("baselines") or {}),
        "holdouts": deepcopy(holdouts or []),
        "provenance": {"source": "causal_replay", "hindsight_used_for_decision": False},
    }
    artifact["artifact_id"] = _fingerprint(artifact)
    return artifact


def validate_holdout_matrix(cases: Any) -> dict[str, Any]:
    if not isinstance(cases, list):
        return {"qualified": False, "reasons": ["holdout_matrix_missing"]}
    seen = set()
    reasons = []
    for case in cases:
        if not isinstance(case, dict) or case.get("kind") not in REQUIRED_HOLDOUTS:
            reasons.append("holdout_kind_missing")
            continue
        seen.add(case["kind"])
        if not case.get("run_fingerprint") or case.get("contaminated") or case.get("incomplete"):
            reasons.append(f"holdout_{case['kind']}_unqualified")
    reasons.extend(f"holdout_{kind}_missing" for kind in sorted(REQUIRED_HOLDOUTS - seen))
    return {"qualified": not reasons, "reasons": sorted(set(reasons)), "kinds": sorted(seen)}


class ReplayArtifactStore:
    """Persistent, immutable, exact-site artifact store with bounded retention."""

    def __init__(self, hass: Any) -> None:
        self.store = Store(hass, STORE_VERSION, STORE_KEY)
        self.state: dict[str, Any] = {"schema": SCHEMA, "version": 1, "sites": {}, "evidence": {}, "available": True, "last_attempt": None}

    async def async_load(self) -> None:
        cached = await self.store.async_load()
        if cached is None:
            return
        if not isinstance(cached, dict) or cached.get("schema") != SCHEMA or not isinstance(cached.get("sites"), dict):
            self.state = {"schema": SCHEMA, "version": 1, "sites": {}, "evidence": {}, "available": False, "reason": "artifact_schema_mismatch"}
            return
        evidence = cached.get("evidence")
        self.state = {
            "schema": SCHEMA,
            "version": 1,
            "sites": cached["sites"],
            "evidence": evidence if isinstance(evidence, dict) else {},
            "available": True,
            "last_attempt": cached.get("last_attempt"),
        }

    async def async_record_evidence(self, site_id: str, evidence: dict[str, Any]) -> bool:
        """Persist bounded, site-scoped benchmark readiness evidence."""
        if self.state.get("available") is not True or not isinstance(site_id, str) or not isinstance(evidence, dict):
            return False
        bounded = deepcopy(evidence)
        bounded["schema"] = "ella_replay_benchmark_evidence.v1"
        bounded["site_id"] = site_id
        sites = self.state.setdefault("evidence", {})
        if site_id not in sites and len(sites) >= MAX_EVIDENCE_SITES:
            return False
        sites[site_id] = bounded
        await self.store.async_save(self.state)
        return True

    def public_evidence(self, site_id: str) -> dict[str, Any]:
        """Return only the current exact-site readiness snapshot."""
        evidence = self.state.get("evidence", {}).get(site_id)
        if not isinstance(evidence, dict):
            return {"schema": "ella_replay_benchmark_evidence.v1", "site_id": site_id, "available": False, "status": "unavailable", "blocker": "no_evidence"}
        return deepcopy(evidence)

    async def async_record_attempt(self, result: dict[str, Any]) -> None:
        """Persist one bounded producer outcome for runtime readback diagnostics."""
        self.state["last_attempt"] = deepcopy({key: result.get(key) for key in ("accepted", "site_id", "reason", "artifact_id", "readback", "qualification", "holdouts", "evidence")})
        await self.store.async_save(self.state)

    async def async_append(self, artifact: Any) -> bool:
        normalized = normalize_artifact(artifact)
        if normalized is None or self.state.get("available") is not True:
            return False
        site = normalized["site_id"]
        records = [item for item in self.state.setdefault("sites", {}).setdefault(site, []) if isinstance(item, dict)]
        if any(item.get("artifact_id") == normalized["artifact_id"] for item in records):
            return False
        records.append(normalized)
        records.sort(key=lambda item: (str(item.get("decision_at")), str(item.get("artifact_id"))))
        self.state["sites"][site] = records[-MAX_ARTIFACTS_PER_SITE:]
        await self.store.async_save(self.state)
        return True


async def async_register_replay_artifact_service(hass: Any) -> None:
    """Register the internal benchmark-to-store producer without execution access."""
    if hass.services.has_service("elrakning", PUBLISH_SERVICE):
        return

    async def _publish(call: Any) -> None:
        store = hass.data.get("elrakning", {}).get("replay_artifact_store")
        if not isinstance(store, ReplayArtifactStore):
            return
        artifact = build_artifact(
            call.data.get("run"),
            dataset_identity=call.data.get("dataset_identity") or {},
            parameter_identity=call.data.get("parameter_identity") or {},
            holdouts=call.data.get("holdouts") or [],
        )
        if artifact is None:
            return
        accepted = await store.async_append(artifact)
        if accepted:
            records = store.state.get("sites", {}).get(artifact["site_id"], [])
            hass.bus.async_fire(
                "elrakning_replay_artifact_published",
                {"schema": SCHEMA, "site_id": artifact["site_id"], "artifact_id": artifact["artifact_id"], "record_count": len(records)},
            )

    if vol is None:  # pragma: no cover
        return
    schema = vol.Schema({
        vol.Required("run"): dict,
        vol.Required("dataset_identity"): dict,
        vol.Required("parameter_identity"): dict,
        vol.Required("holdouts"): list,
    })
    hass.services.async_register("elrakning", PUBLISH_SERVICE, _publish, schema=schema)
