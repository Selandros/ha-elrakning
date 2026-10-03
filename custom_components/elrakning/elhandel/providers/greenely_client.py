"""Greenely API client and provider-specific response helpers."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import date
from typing import Any

from aiohttp import ClientError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .greenely_source import sanitize_greenely_source

LOGIN_URL = "https://api2.greenely.com/v1/login"
CHECKAUTH_URL = "https://api2.greenely.com/v1/checkauth"
FACILITIES_URL = "https://api2.greenely.com/v1/facilities/"
BACKEND_BASE_URL = "https://backend.greenely.com/v1"


class GreenelyError(Exception):
    """A normalized Greenely request error with optional non-sensitive diagnostics."""

    def __init__(self, code: str, diagnostics: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.diagnostics = dict(diagnostics) if isinstance(diagnostics, dict) else None


class GreenelyClient:
    """Async client for the read-only Greenely discovery request."""

    def __init__(self, hass) -> None:
        self._session = async_get_clientsession(hass)
        self._jwt: str | None = None

    async def async_login(self, email: str, password: str) -> None:
        try:
            async with self._session.post(
                LOGIN_URL,
                json={"email": email, "password": password},
                timeout=15,
            ) as response:
                if response.status in (401, 403):
                    raise GreenelyError("invalid_auth")
                if response.status >= 400:
                    raise GreenelyError("unexpected_response")
                payload = await response.json(content_type=None)
        except asyncio.TimeoutError as err:
            raise GreenelyError("timeout") from err
        except ClientError as err:
            raise GreenelyError("connection_error") from err
        except (TypeError, ValueError) as err:
            raise GreenelyError("unexpected_response") from err

        jwt = payload.get("jwt") if isinstance(payload, dict) else None
        if not isinstance(jwt, str) or not jwt.strip():
            raise GreenelyError("unexpected_response")
        self._jwt = jwt.strip()

    async def async_get_facilities(self) -> list[dict[str, Any]]:
        if not self._jwt:
            raise GreenelyError("invalid_auth")
        try:
            async with self._session.get(
                FACILITIES_URL,
                headers={"Authorization": f"JWT {self._jwt}"},
                timeout=15,
            ) as response:
                if response.status in (401, 403):
                    raise GreenelyError("invalid_auth")
                if response.status >= 400:
                    raise GreenelyError("unexpected_response")
                payload = await response.json(content_type=None)
        except asyncio.TimeoutError as err:
            raise GreenelyError("timeout") from err
        except ClientError as err:
            raise GreenelyError("connection_error") from err
        except (TypeError, ValueError) as err:
            raise GreenelyError("unexpected_response") from err

        facilities = _extract_facilities(payload)
        if facilities is None:
            raise GreenelyError("unexpected_response")
        return facilities

    async def async_get_consumption(
        self,
        facility_id: str,
        start_date: date,
        end_date: date,
        resolution: str = "hourly",
        unit: str = "usage",
    ) -> Any:
        """Fetch a small read-only consumption discovery response."""
        if not self._jwt:
            raise GreenelyError("invalid_auth")
        url = f"{FACILITIES_URL}{facility_id}/consumption"
        try:
            async with self._session.get(
                url,
                headers={"Authorization": f"JWT {self._jwt}"},
                params={
                    "from": start_date.isoformat(),
                    "to": end_date.isoformat(),
                    "resolution": resolution,
                    "unit": unit,
                },
                timeout=15,
            ) as response:
                if response.status in (401, 403):
                    raise GreenelyError("invalid_auth")
                if response.status >= 400:
                    raise GreenelyError("unexpected_response")
                return await response.json(content_type=None)
        except asyncio.TimeoutError as err:
            raise GreenelyError("timeout") from err
        except ClientError as err:
            raise GreenelyError("connection_error") from err
        except (TypeError, ValueError) as err:
            raise GreenelyError("unexpected_response") from err

    async def async_get_electricity_contracts(self, facility_id: str) -> list[dict[str, Any]]:
        """Fetch all electricity contracts for one facility."""
        payload = await self._async_get_json(
            f"{BACKEND_BASE_URL}/facilities/{facility_id}/retail/electricity-contracts"
        )
        contracts = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(contracts, list) or not all(isinstance(item, dict) for item in contracts):
            raise GreenelyError("unexpected_response")
        return contracts

    async def async_get_invoices(self, contract_id: str) -> list[dict[str, Any]]:
        """Fetch all invoices for one electricity contract."""
        payload = await self._async_get_json(
            f"{BACKEND_BASE_URL}/retail/electricity-contracts/{contract_id}/invoices"
        )
        invoices = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(invoices, list) or not all(isinstance(item, dict) for item in invoices):
            raise GreenelyError("unexpected_response")
        return invoices

    async def async_get_invoice_pdf(self, contract_id: str, invoice_key: str) -> bytes:
        """Fetch one fresh presigned invoice PDF into memory."""
        invoices = await self.async_get_invoices(contract_id)
        invoice = next(
            (item for item in invoices if _invoice_key(contract_id, item) == invoice_key),
            None,
        )
        if not isinstance(invoice, dict):
            raise GreenelyError("invoice_not_found")
        pdf_url = invoice.get("pdf_url")
        if not isinstance(pdf_url, str) or not pdf_url.startswith("https://"):
            raise GreenelyError("pdf_not_found")
        try:
            async with self._session.get(pdf_url, timeout=30) as response:
                if response.status != 200:
                    raise GreenelyError("pdf_download_failed")
                if response.content_length and response.content_length > 10 * 1024 * 1024:
                    raise GreenelyError("pdf_too_large")
                data = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    data.extend(chunk)
                    if len(data) > 10 * 1024 * 1024:
                        raise GreenelyError("pdf_too_large")
                if not bytes(data).startswith(b"%PDF-"):
                    raise GreenelyError("invalid_pdf")
                return bytes(data)
        except GreenelyError:
            raise
        except asyncio.TimeoutError as err:
            raise GreenelyError("timeout") from err
        except ClientError as err:
            raise GreenelyError("connection_error") from err

    async def async_get_facility_invoices(self, facility_id: str) -> dict[str, Any]:
        """Fetch and sanitize invoices from every contract of one facility."""
        contracts = await self.async_get_electricity_contracts(facility_id)
        contract_results: list[dict[str, Any]] = []
        invoices: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for contract in contracts:
            contract_id = contract.get("id")
            if not isinstance(contract_id, (str, int)) or isinstance(contract_id, bool):
                continue
            contract_id = str(contract_id)
            contract_result = _sanitize_contract(contract)
            try:
                raw_invoices = await self.async_get_invoices(contract_id)
            except GreenelyError as err:
                if err.code == "invalid_auth":
                    raise
                errors.append({"_contract_id": contract_id, "error": err.code})
                contract_result["invoice_count"] = 0
                contract_results.append(contract_result)
                continue
            sanitized = [_sanitize_invoice(item, contract_id, contract) for item in raw_invoices]
            contract_result["invoice_count"] = len(sanitized)
            contract_results.append(contract_result)
            invoices.extend(sanitized)
        invoices.sort(key=lambda item: item.get("invoice_date") or "", reverse=True)
        return {"contracts": contract_results, "invoices": invoices, "failed_contracts": errors}

    async def async_get_cost_distribution(
        self, facility_id: str, start_date: date, end_date: date
    ) -> Any:
        """Fetch provider analysis data without treating it as billing."""
        return await self._async_get_json(
            f"{BACKEND_BASE_URL}/facilities/{facility_id}/consumption-cost-distribution",
            {"from": start_date.isoformat(), "to": end_date.isoformat(), "resolution": "daily"},
        )

    async def async_get_spot_price(
        self, facility_id: str, start_date: date, end_date: date
    ) -> Any:
        """Fetch provider spot observations without assigning a local price unit."""
        return await self._async_get_json(
            f"{BACKEND_BASE_URL}/facilities/{facility_id}/spot-price",
            {"from": start_date.isoformat(), "to": end_date.isoformat(), "resolution": "daily"},
        )

    async def _async_get_json(self, url: str, params: dict[str, str] | None = None) -> Any:
        """GET JSON from Greenely's backend using the in-memory JWT."""
        if not self._jwt:
            raise GreenelyError("invalid_auth")
        try:
            async with self._session.get(
                url,
                headers={"Authorization": f"JWT {self._jwt}"},
                params=params,
                timeout=15,
            ) as response:
                if response.status in (401, 403):
                    raise GreenelyError("invalid_auth")
                if response.status >= 400:
                    raise GreenelyError("unexpected_response")
                return await response.json(content_type=None)
        except asyncio.TimeoutError as err:
            raise GreenelyError("timeout") from err
        except ClientError as err:
            raise GreenelyError("connection_error") from err
        except (TypeError, ValueError) as err:
            raise GreenelyError("unexpected_response") from err


def _sanitize_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Return the minimal safe contract metadata for the UI."""
    result = sanitize_greenely_source(contract) or {}
    if not isinstance(result, dict):
        result = {}
    contract_id = result.pop("id", None)
    if isinstance(contract_id, (str, int)) and not isinstance(contract_id, bool):
        result["_contract_id"] = str(contract_id)
    for key in ("id", "facility_id", "status", "electricity_type"):
        value = contract.get(key)
        if key in ("id", "facility_id") and isinstance(value, (str, int)) and not isinstance(value, bool):
            result["_contract_id" if key == "id" else key] = str(value)
        elif key in ("status", "electricity_type") and isinstance(value, str):
            result[key] = value
    result["invoice_count"] = 0
    return result


def _sanitize_invoice(
    invoice: dict[str, Any], contract_id: str, contract: dict[str, Any]
) -> dict[str, Any]:
    """Return safe invoice display data and retain only internal contract context."""
    result = sanitize_greenely_source(invoice) or {}
    if not isinstance(result, dict):
        result = {}
    result.pop("pdf_url", None)
    result.update({
        "_contract_id": contract_id,
        "_invoice_key": _invoice_key(contract_id, invoice),
    })
    status = contract.get("status")
    if isinstance(status, str):
        result["_contract_status"] = status
    for key in ("invoice_date", "month", "due_date", "state"):
        value = invoice.get(key)
        if isinstance(value, str):
            result[key] = value
    if isinstance(invoice.get("is_paid"), bool):
        result["is_paid"] = invoice["is_paid"]
    cost = invoice.get("cost")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        result["amount_due_ore"] = cost
        result["amount_due_sek"] = cost / 100
    return result


def _invoice_key(contract_id: str, invoice: dict[str, Any]) -> str:
    """Build a stable opaque key without using OCR or signed URLs."""
    value = "|".join(
        [contract_id]
        + [str(invoice.get(key) or "") for key in ("invoice_date", "due_date", "month")]
    )
    return hashlib.sha256(value.encode()).hexdigest()


def _extract_facilities(payload: Any) -> list[dict[str, Any]] | None:
    """Extract a facility list from the supported Greenely response shapes."""
    if isinstance(payload, dict):
        facilities = payload.get("data")
        if facilities is None:
            facilities = payload.get("facilities")
    else:
        facilities = payload
    if not isinstance(facilities, list) or not all(isinstance(item, dict) for item in facilities):
        return None
    return facilities
