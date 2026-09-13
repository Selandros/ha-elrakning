"""Private pseudonymization domain for immutable provider occurrence identities."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from typing import Any

from homeassistant.helpers.storage import Store

from .canonical_storage import HISTORY_FOUND, HISTORY_NONE, HISTORY_UNKNOWN


STORE_VERSION = 1
STORE_KEY = "elrakning.greenely_invoice_identity"
IDENTITY_VERSION = "greenely-invoice-occurrence-v1"


class PseudonymizationDomain:
    """Load or create one durable HMAC key for one config-entry identity domain."""

    def __init__(self, hass, identity_domain_id: str, storage) -> None:
        self.hass = hass
        self.identity_domain_id = identity_domain_id
        self.storage = storage
        self.store = Store(hass, STORE_VERSION, f"{STORE_KEY}.{identity_domain_id}", private=True, atomic_writes=True)
        self.key_id: str | None = None
        self._key: bytes | None = None

    async def async_initialize(self) -> str:
        cached = await self.store.async_load()
        if cached is not None:
            if not isinstance(cached, dict) or cached.get("schema_version") != STORE_VERSION:
                raise RuntimeError("key_unavailable")
            key_hex = cached.get("key_material")
            if not isinstance(key_hex, str) or len(key_hex) != 64:
                raise RuntimeError("key_unavailable")
            try:
                self._key = bytes.fromhex(key_hex)
            except ValueError as err:
                raise RuntimeError("key_unavailable") from err
            if len(self._key) != 32 or cached.get("identity_domain_id") != self.identity_domain_id:
                raise RuntimeError("key_unavailable")
            self.key_id = cached.get("key_id")
            if not isinstance(self.key_id, str) or not self.key_id:
                raise RuntimeError("key_unavailable")
            return self.key_id
        try:
            history = await self.hass.async_add_executor_job(
                self.storage.external_history_status_for_identity_domain,
                "greenely.invoice_economics.v1",
                self.identity_domain_id,
            )
        except Exception as err:
            raise RuntimeError("key_history_unknown") from err
        if history != HISTORY_NONE:
            if history == HISTORY_UNKNOWN:
                raise RuntimeError("key_history_unknown")
            raise RuntimeError("key_missing_with_history")
        candidate_key = secrets.token_bytes(32)
        candidate_key_id = hashlib.sha256(candidate_key).hexdigest()
        await self.store.async_save({
            "schema_version": STORE_VERSION,
            "key_material": candidate_key.hex(),
            "key_id": candidate_key_id,
            "identity_domain_id": self.identity_domain_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        self._key = candidate_key
        self.key_id = candidate_key_id
        return candidate_key_id

    def occurrence_identity(self, contract_identity: str, occurrence_reference: str) -> str:
        if self._key is None or not self.key_id:
            raise RuntimeError("key_unavailable")
        payload = {
            "identity_version": IDENTITY_VERSION,
            "provider_namespace": "greenely",
            "identity_domain_id": self.identity_domain_id,
            "contract_identity": contract_identity,
            "provider_invoice_occurrence_reference": occurrence_reference,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hmac.new(self._key, encoded, hashlib.sha256).hexdigest()
