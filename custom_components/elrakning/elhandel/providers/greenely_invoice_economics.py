"""Site-independent Greenely invoice economics producer."""

from __future__ import annotations

import hashlib
import json
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall

from .greenely_client import GreenelyClient, GreenelyError, _invoice_key
from .greenely_invoice_parser import extract_pdf_text, parse_greenely_invoice_text
from ...canonical_storage import CanonicalStorage
from ...pseudonymization import PseudonymizationDomain
from ...site_identity import SiteIdentityManager


DATASET = "greenely.invoice_economics.v1"
PROVIDER_ADAPTER_VERSION = "greenely-invoice-economics-v1"
PARSER_VERSION = "greenely-invoice-parser-v3"
NORMALIZATION_VERSION = "greenely-invoice-economics-normalizer-v1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _source_generation(target: dict[str, Any], proof: dict[str, Any], domain_id: str, contract_identity: str) -> tuple[str, dict[str, Any]]:
    identity = {
        "provider_adapter_version": PROVIDER_ADAPTER_VERSION,
        "config_entry_identity": SiteIdentityManager.identity_fingerprint({"config_entry_id": target["binding"]["config_entry_id"]}),
        "site_binding_identity": target["binding"]["binding_fingerprint"],
        "facility_identity": SiteIdentityManager.identity_fingerprint({"facility_id": target["binding"]["facility_id"]}),
        "contract_identity_scope": contract_identity,
        "dataset_identity": DATASET,
        "parser_version": PARSER_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "vat_semantics": "ex_vat",
        "unit_semantics": "SEK_native_component_unit",
        "verified_timezone_identity_and_state": target["timezone"],
        "proof_semantic_identity_state_version": proof["proof_semantic_identity"],
        "pseudonymization_key_id_identity_domain_id": domain_id,
    }
    key = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(key.encode()).hexdigest(), identity


def _period_bounds(parsed: dict[str, Any], timezone_name: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(timezone_name)
    start = datetime.fromisoformat(str(parsed["period_start"])).replace(tzinfo=zone)
    end = datetime.fromisoformat(str(parsed["period_end"])).replace(tzinfo=zone) + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _parse_invoice_pdf(pdf: bytes) -> tuple[str, Any]:
    """Keep CPU-bound PDF parsing off the Home Assistant event loop."""
    return extract_pdf_text(pdf)


def _latest_invoice(candidates: list[tuple[str, dict[str, Any]]]) -> tuple[str, dict[str, Any]] | None:
    if not candidates:
        return None
    dated = []
    for contract_id, invoice in candidates:
        order = tuple(str(invoice.get(key) or "") for key in ("invoice_date", "due_date", "month"))
        if not any(order):
            continue
        dated.append((order, contract_id, invoice))
    if not dated:
        return None
    dated.sort(reverse=True, key=lambda item: item[0])
    top = dated[0]
    if sum(item[0] == top[0] for item in dated) > 1:
        raise ValueError("contract_ambiguous")
    return top[1], top[2]


class GreenelyInvoiceEconomicsProducer:
    """Capture one prospective invoice per explicit, proven site target."""

    def __init__(self, hass, entry, site_identity: SiteIdentityManager, storage: CanonicalStorage) -> None:
        self.hass = hass
        self.entry = entry
        self.site_identity = site_identity
        self.storage = storage
        self._lock = __import__("asyncio").Lock()
        self._domains: dict[str, PseudonymizationDomain] = {}
        self._capture_task = None
        self._closed = False
        self._lifecycle_generation = 0
        self._persistence_tasks: set[asyncio.Task] = set()

    def _targets(self) -> list[dict[str, Any]]:
        result = []
        for site_id, config in self.site_identity.collection_site_configs().items():
            if config.get("collection_enabled") is not True:
                continue
            binding = config.get("bindings", {}).get("elhandel")
            location = config.get("location")
            if not isinstance(binding, dict) or binding.get("provider") != "greenely":
                continue
            if binding.get("config_entry_id") != self.entry.entry_id or not binding.get("facility_id"):
                continue
            if not isinstance(location, dict) or location.get("verification_state") != "verified":
                continue
            try:
                ZoneInfo(str(location["timezone"]))
            except Exception:
                continue
            if not self.site_identity.validated_greenely_proof(site_id, binding):
                continue
            result.append({"site_id": site_id, "binding": dict(binding), "timezone": str(location["timezone"])})
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for target in result:
            key = (str(target["binding"]["config_entry_id"]), str(target["binding"]["facility_id"]))
            grouped.setdefault(key, []).append(target)
        return [target for targets in grouped.values() if len(targets) == 1 for target in targets]

    @staticmethod
    def _target_token(target: dict[str, Any], proof: dict[str, Any], key_id: str) -> tuple[Any, ...]:
        """Build an immutable pre-fetch ownership token without raw identifiers."""
        return (
            target["site_id"],
            target["binding"].get("config_entry_id"),
            target["binding"].get("binding_fingerprint"),
            target["binding"].get("facility_id"),
            target["timezone"],
            proof.get("proof_fingerprint"),
            key_id,
            DATASET,
        )

    def _target_is_current(self, target: dict[str, Any], proof: dict[str, Any], key_id: str, generation: int | None = None) -> bool:
        if self._closed or (generation is not None and generation != self._lifecycle_generation):
            return False
        current = next((item for item in self._targets() if item["site_id"] == target["site_id"]), None)
        if current is None:
            return False
        current_proof = self.site_identity.validated_greenely_proof(target["site_id"], current["binding"])
        return current_proof is not None and self._target_token(target, proof, key_id) == self._target_token(current, current_proof, key_id)

    async def _domain(self) -> PseudonymizationDomain:
        domain_id = self.entry.entry_id
        domain = self._domains.get(domain_id)
        if domain is None:
            domain = PseudonymizationDomain(self.hass, domain_id, self.storage)
            await domain.async_initialize()
            self._domains[domain_id] = domain
        return domain

    def async_schedule_capture(self) -> None:
        """Schedule at most one owned capture task."""
        if self._closed or (self._capture_task and not self._capture_task.done()):
            return
        self._capture_task = self.hass.async_create_task(self.async_capture())

    async def async_shutdown(self) -> None:
        """Stop future captures and await owned persistence work."""
        self._closed = True
        self._lifecycle_generation += 1
        task = self._capture_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except __import__("asyncio").CancelledError:
                pass
        if self._persistence_tasks:
            await asyncio.gather(*tuple(self._persistence_tasks), return_exceptions=True)

    async def _persist_owned(self, frame: dict[str, Any], points: list[dict[str, Any]]) -> None:
        """Own a persistence executor task until it has completed."""
        task = asyncio.ensure_future(
            self.hass.async_add_executor_job(self.storage.insert_external_frame, frame, points)
        )
        self._persistence_tasks.add(task)
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise
        finally:
            self._persistence_tasks.discard(task)

    async def async_capture(self) -> dict[str, Any]:
        async with self._lock:
            capture_generation = self._lifecycle_generation
            targets = self._targets()
            result = {"target_count": len(targets), "target_site_ids": [item["site_id"] for item in targets], "captured": 0, "deduplicated": 0, "failed": 0}
            if not targets:
                return result
            try:
                domain = await self._domain()
            except Exception:
                result["failed"] = len(targets)
                return result
            config = self.entry.data.get("electricity_provider_config", {})
            for target in targets:
                try:
                    proof = self.site_identity.validated_greenely_proof(target["site_id"], target["binding"])
                    if proof is None:
                        continue
                    target_token = self._target_token(target, proof, domain.key_id or "")
                    client = GreenelyClient(self.hass)
                    await client.async_login(config.get("email"), config.get("password"))
                    contracts = await client.async_get_electricity_contracts(str(target["binding"]["facility_id"]))
                    invoice_candidates = []
                    for contract in contracts:
                        if str(contract.get("facility_id")) != str(target["binding"]["facility_id"]):
                            continue
                        contract_id = str(contract.get("id")) if contract.get("id") is not None else ""
                        if not contract_id:
                            continue
                        for invoice in await client.async_get_invoices(contract_id):
                            invoice_candidates.append((contract_id, invoice))
                    selected = _latest_invoice(invoice_candidates)
                    if selected is None:
                        continue
                    contract_id, invoice = selected
                    contract_identity = self.site_identity.identity_fingerprint({"contract_id": contract_id})
                    if contract_identity != proof["contract_identity_fingerprint"]:
                        continue
                    occurrence = invoice.get("ocr_number")
                    if not isinstance(occurrence, str) or not occurrence.strip():
                        continue
                    occurrences = [item.get("ocr_number") for cid, item in invoice_candidates if cid == contract_id]
                    if occurrences.count(occurrence) > 1:
                        continue
                    occurrence_id = domain.occurrence_identity(contract_id, occurrence)
                    pdf = await client.async_get_invoice_pdf(contract_id, _invoice_key(contract_id, invoice))
                    fetched_at = _utc_now()
                    text, _ = await self.hass.async_add_executor_job(_parse_invoice_pdf, pdf)
                    parsed = await self.hass.async_add_executor_job(parse_greenely_invoice_text, text)
                    sections = parsed.get("installation_sections") or []
                    matches = [section for section in sections if self.site_identity.identity_fingerprint({"installation_id": str(section.get("installation_id"))}) == proof["invoice_installation_identity_fingerprint"]]
                    if len(matches) != 1:
                        continue
                    parsed = await self.hass.async_add_executor_job(
                        parse_greenely_invoice_text, str(matches[0].get("text") or "")
                    )
                    if not parsed.get("period_start") or not parsed.get("period_end"):
                        continue
                    captured_at = _utc_now()
                    valid_from, valid_to = _period_bounds(parsed, target["timezone"])
                    if not self._target_is_current(target, proof, domain.key_id or "", capture_generation):
                        continue
                    fresh_contracts = await client.async_get_electricity_contracts(
                        str(target["binding"]["facility_id"])
                    )
                    relation_matches = [
                        item for item in fresh_contracts
                        if str(item.get("id")) == contract_id
                        and str(item.get("facility_id")) == str(target["binding"]["facility_id"])
                    ]
                    if len(relation_matches) != 1:
                        continue
                    generation_id, identity = _source_generation(target, proof, domain.key_id or self.entry.entry_id, proof["contract_identity_fingerprint"])
                    await self.hass.async_add_executor_job(
                        self.storage.ensure_source_generation,
                        {"site_id": target["site_id"], "logical_role": DATASET, "generation_id": generation_id, "source_identity": {"identity_key": json.dumps(identity, sort_keys=True), "identity_strength": "strong", "identity_provenance": json.dumps({"identity_domain_id": self.entry.entry_id})}, "source_resolution_kind": "native_bucket", "source_resolution_seconds": None, "timezone_state": "verified"},
                        captured_at,
                    )
                    components = []
                    variable = parsed.get("variable_cost", {}).get("rate_ore_per_kwh_ex_vat")
                    fixed = parsed.get("fixed_fee", {}).get("rate_ex_vat_sek_per_month")
                    if variable is not None:
                        components.append(("economic.provider.import.variable", float(Decimal(str(variable)) / Decimal("100")), "SEK/kWh"))
                    if fixed is not None:
                        components.append(("economic.provider.fixed.subscription", float(fixed), "SEK/month"))
                    if not components:
                        continue
                    if not self._target_is_current(target, proof, domain.key_id or "", capture_generation) or target_token != self._target_token(target, proof, domain.key_id or ""):
                        continue
                    for role, value, unit in components:
                        semantic_key = "|".join((DATASET, target["site_id"], generation_id, role, occurrence_id, f"{parsed['period_start']}_{parsed['period_end']}"))
                        previous = await self.hass.async_add_executor_job(self.storage.latest_external_frame_snapshot, semantic_key)
                        revision = int(previous["frame"]["revision"]) + 1 if previous else 1
                        frame_id = hashlib.sha256(f"{semantic_key}|{revision}|{value}".encode()).hexdigest()
                        point_id = f"{frame_id}-p001"
                        provenance = {"identity_domain_id": self.entry.entry_id, "invoice_occurrence_identity": occurrence_id, "binding_fingerprint": target["binding"]["binding_fingerprint"], "attribution_proof_semantic_identity": proof["proof_semantic_identity"]}
                        frame = {"frame_id": frame_id, "semantic_key": semantic_key, "revision": revision, "supersedes_frame_id": previous["frame"]["frame_id"] if previous else None, "source_generation_id": generation_id, "source_scope": "site", "site_id": target["site_id"], "logical_role": DATASET, "classification": "measured", "published_at": None, "fetched_at": fetched_at, "known_at": captured_at, "captured_at": captured_at, "valid_from": valid_from, "valid_to": valid_to, "quality_status": "good", "quality": {}, "provenance": provenance, "payload_schema": DATASET}
                        point = {"point_id": point_id, "point_key": role, "valid_at": valid_from, "value": value, "unit": unit, "quality_status": "good", "point": {"component_role": role}}
                        if previous and previous["points"] and previous["points"][0]["value"] == value and previous["points"][0]["point_json"] == json.dumps({"component_role": role}, sort_keys=True):
                            result["deduplicated"] += 1
                        else:
                            if not self._target_is_current(target, proof, domain.key_id or "", capture_generation):
                                continue
                            if self._closed or capture_generation != self._lifecycle_generation:
                                continue
                            await self._persist_owned(frame, [point])
                            result["captured"] += 1
                except (GreenelyError, ValueError, KeyError, TypeError):
                    result["failed"] += 1
            return result


SERVICE_PROVISION = "greenely_proof_provision"
PROVISION_SCHEMA = vol.Schema({
    vol.Required("site_id"): str,
    vol.Required("expected_binding_fingerprint"): str,
    vol.Required("contract_id"): str,
    vol.Required("facility_meter_id_fingerprint"): str,
    vol.Required("contract_meter_id_fingerprint_or_state"): str,
    vol.Required("invoice_installation_identity_fingerprint"): str,
    vol.Required("verification_method"): str,
    vol.Required("parser_identity"): str,
    vol.Required("normalization_identity"): str,
    vol.Required("evidence_reference"): str,
    vol.Required("evidence_digest"): str,
    vol.Required("evidence_package"): dict,
})


async def async_register_proof_service(hass: HomeAssistant, site_identity: SiteIdentityManager, entry) -> None:
    """Register the privileged, explicit proof provisioning operation."""
    runtime = hass.data.setdefault("elrakning", {})
    if hass.services.has_service("elrakning", SERVICE_PROVISION):
        return

    async def _handle(call: ServiceCall) -> None:
        user_id = getattr(call.context, "user_id", None)
        if not user_id:
            raise PermissionError("admin_user_required")
        user = await hass.auth.async_get_user(user_id)
        if user is None or not user.is_admin:
            raise PermissionError("admin_user_required")
        current_site_identity = hass.data.get("elrakning", {}).get("site_identity_manager", site_identity)
        site_id = call.data.get("site_id")
        config = current_site_identity.collection_site_configs().get(site_id, {})
        binding = config.get("bindings", {}).get("elhandel", {}) if isinstance(config, dict) else {}
        if binding.get("provider") != "greenely" or not binding.get("facility_id"):
            raise ValueError("greenely_binding_required")
        client = GreenelyClient(hass)
        current_entry = hass.data.get("elrakning", {}).get("config_entry", entry)
        provider_config = current_entry.data.get("electricity_provider_config", {})
        await client.async_login(provider_config.get("email"), provider_config.get("password"))
        facilities = await client.async_get_facilities()
        facility_matches = [item for item in facilities if str(item.get("id")) == str(binding["facility_id"])]
        if len(facility_matches) != 1:
            raise ValueError("facility_relation_not_unique")
        contracts = await client.async_get_electricity_contracts(str(binding["facility_id"]))
        requested = str(call.data.get("contract_id"))
        matches = [
            item for item in contracts
            if str(item.get("id")) == requested
            and str(item.get("facility_id")) == str(binding["facility_id"])
        ]
        if len(matches) != 1:
            raise ValueError("contract_relation_not_unique")
        current_config = current_site_identity.collection_site_configs().get(site_id, {})
        current_binding = current_config.get("bindings", {}).get("elhandel", {}) if isinstance(current_config, dict) else {}
        if current_site_identity.binding_fingerprint(current_binding) != call.data.get("expected_binding_fingerprint"):
            raise ValueError("stale_binding")
        contracts_after = await client.async_get_electricity_contracts(str(current_binding["facility_id"]))
        matches_after = [
            item for item in contracts_after
            if str(item.get("id")) == requested
            and str(item.get("facility_id")) == str(current_binding["facility_id"])
        ]
        if len(matches_after) != 1 or matches_after[0] != matches[0]:
            raise ValueError("provider_relation_changed")
        payload = dict(call.data)
        payload["verification_actor"] = user_id
        payload["verification_actor_source"] = "authenticated_home_assistant_service_context"
        await current_site_identity.async_provision_greenely_proof(
            payload, provider_relation=matches[0]
        )

    hass.services.async_register("elrakning", SERVICE_PROVISION, _handle, schema=PROVISION_SCHEMA)
    runtime["greenely_proof_service_registered"] = True
