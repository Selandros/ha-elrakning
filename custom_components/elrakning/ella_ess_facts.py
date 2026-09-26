"""Auditable, site-scoped ESS facts for read-only planning eligibility."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
from typing import Any

try:
    from homeassistant.helpers.storage import Store
except ModuleNotFoundError:  # pragma: no cover - lightweight contract tests
    class Store:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass


SCHEMA = "ella_ess_facts.v1"
STORE_KEY = "elrakning.ella_ess_facts"
STORE_VERSION = 1

SOURCE_PRIORITY = {
    "runtime_device_config": 500,
    "configured_device_policy": 400,
    "manufacturer_rated_specification": 300,
    "conservative_calibration_planning_assumption": 100,
    "product_policy_default": 100,
}


def _timestamp(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat() if value.tzinfo else None
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else None
    return None


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_fact(fact: Any) -> dict[str, Any] | None:
    """Validate one imported fact without accepting opaque provider payloads."""
    if not isinstance(fact, dict):
        return None
    site_id = fact.get("site_id")
    resource_id = fact.get("resource_id")
    key = fact.get("key")
    unit = fact.get("unit")
    source_type = fact.get("source_type")
    value = _finite(fact.get("value"))
    verified_at = _timestamp(fact.get("verified_at") or fact.get("observed_at"))
    if not all(isinstance(item, str) and item.strip() for item in (site_id, resource_id, key, unit, source_type)):
        return None
    if value is None or verified_at is None or source_type not in SOURCE_PRIORITY:
        return None
    result = {
        "site_id": site_id,
        "resource_id": resource_id,
        "key": key,
        "value": value,
        "unit": unit,
        "source_type": source_type,
        "source_priority": SOURCE_PRIORITY[source_type],
        "verified_at": verified_at,
    }
    for field in ("observed_at", "evidence_note", "evidence_reference", "manufacturer_model_family", "spec_revision"):
        if field in fact and isinstance(fact[field], (str, int, float, bool)):
            result[field] = fact[field]
    return result


class EllaEssFactsStore:
    """Persist append/update facts without embedding site values in the package."""

    def __init__(self, hass: Any) -> None:
        self.store = Store(hass, STORE_VERSION, STORE_KEY)
        self.state: dict[str, Any] = {"schema": SCHEMA, "version": 1, "sites": {}}

    async def async_load(self) -> None:
        cached = await self.store.async_load()
        if isinstance(cached, dict) and cached.get("schema") == SCHEMA and isinstance(cached.get("sites"), dict):
            self.state = {"schema": SCHEMA, "version": 1, "sites": cached["sites"]}

    async def async_upsert(self, facts: list[Any]) -> int:
        changed = 0
        for raw in facts:
            fact = normalize_fact(raw)
            if fact is None:
                continue
            site = self.state.setdefault("sites", {}).setdefault(fact["site_id"], {"facts": []})
            records = [item for item in site.get("facts", []) if isinstance(item, dict)]
            identity = (fact["resource_id"], fact["key"], fact["source_type"])
            replaced = False
            for index, current in enumerate(records):
                if (current.get("resource_id"), current.get("key"), current.get("source_type")) == identity:
                    if current == fact:
                        replaced = True
                        break
                    if fact["verified_at"] >= str(current.get("verified_at", "")):
                        records[index] = fact
                        changed += 1
                    replaced = True
                    break
            if not replaced:
                records.append(fact)
                changed += 1
            site["facts"] = records
        if changed:
            await self.store.async_save(self.state)
        return changed

    def resolve(self, site_id: str, resource_id: str) -> dict[str, dict[str, Any]]:
        """Return the highest-priority latest fact for this exact site/resource."""
        selected: dict[str, dict[str, Any]] = {}
        site = self.state.get("sites", {}).get(site_id, {})
        for fact in site.get("facts", []):
            if not isinstance(fact, dict) or fact.get("resource_id") != resource_id:
                continue
            key = fact.get("key")
            if not isinstance(key, str):
                continue
            current = selected.get(key)
            rank = (int(fact.get("source_priority", -1)), str(fact.get("verified_at", "")))
            current_rank = (int(current.get("source_priority", -1)), str(current.get("verified_at", ""))) if current else None
            if current is None or rank > current_rank:
                selected[key] = deepcopy(fact)
        return selected

    def list_site(self, site_id: str) -> list[dict[str, Any]]:
        site = self.state.get("sites", {}).get(site_id, {})
        return deepcopy([item for item in site.get("facts", []) if isinstance(item, dict)])

    def apply_to_optimizer_inputs(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Overlay exact-resource facts only where an input did not already provide one."""
        result = deepcopy(inputs)
        site_id = result.get("site_id")
        ess = result.get("ess")
        identity = ess.get("resource_identity") if isinstance(ess, dict) else None
        resource_id = identity.get("resource_id") if isinstance(identity, dict) else None
        if (
            not isinstance(site_id, str)
            or not isinstance(resource_id, str)
            or not isinstance(ess, dict)
            or not isinstance(identity, dict)
            or identity.get("available") is not True
            or identity.get("site_id") != site_id
            or identity.get("method") != "strong_registry_config_entry_and_device_identity"
        ):
            return result
        resolved = self.resolve(site_id, resource_id)
        key_map = {
            "capacity_kwh": "capacity_kwh",
            "reserve_soc_fraction": "reserve_soc_fraction",
            "min_soc_fraction": "reserve_soc_fraction",
            "max_charge_kw": "max_charge_kw",
            "max_discharge_kw": "max_discharge_kw",
        }
        provenance = {}
        for fact_key, target in key_map.items():
            fact = resolved.get(fact_key)
            if fact is not None and target not in ess:
                ess[target] = fact["value"]
                provenance[target] = {
                    "source_type": fact["source_type"],
                    "verified_at": fact["verified_at"],
                    "resource_id": resource_id,
                }
        if "planning_efficiency" not in ess:
            charge = resolved.get("planning_charge_efficiency")
            discharge = resolved.get("planning_discharge_efficiency")
            if charge is not None and discharge is not None:
                source_type = charge["source_type"]
                if source_type == discharge["source_type"]:
                    ess["planning_efficiency"] = {
                        "charge_efficiency": charge["value"],
                        "discharge_efficiency": discharge["value"],
                        "source_type": source_type,
                        "uncertainty": "bounded_planning_only",
                    }
                    provenance["planning_efficiency"] = {
                        "source_type": source_type,
                        "resource_id": resource_id,
                    }
        if provenance:
            ess["verified_fact_provenance"] = provenance
        result["ess"] = ess
        return result
