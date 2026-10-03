"""Greenely provider operations backed by the existing API client."""

from __future__ import annotations

from datetime import date
from typing import Any

from ...const import GREENELY_EMAIL, GREENELY_FACILITY_ID, GREENELY_PASSWORD
from .greenely_consumption import (
    greenely_consumption_payload_shape,
    normalize_greenely_consumption,
    summarize_greenely_consumption,
)
from .greenely_source import sanitize_greenely_source
from .greenely_client import GreenelyClient, GreenelyError
from .greenely_invoice import GreenelyInvoiceError, GreenelyInvoiceProcessor
from .greenely_insights import normalize_consumption_cost, normalize_cost_distribution, normalize_spot_price


class GreenelyProvider:
    """Delegate Greenely API operations without changing their behavior."""

    def __init__(self, hass) -> None:
        self._client = GreenelyClient(hass)

    @staticmethod
    def validate_credentials(email: str, password: str) -> None:
        """Validate the credentials required by the Greenely API."""
        if not isinstance(email, str) or not email.strip():
            raise GreenelyError("invalid_auth")
        if not isinstance(password, str) or not password:
            raise GreenelyError("invalid_auth")

    @staticmethod
    def has_credentials(config: dict[str, Any]) -> bool:
        return all(
            isinstance(config.get(key), str) and bool(config.get(key))
            for key in (GREENELY_EMAIL, GREENELY_PASSWORD)
        )

    @classmethod
    def is_configured(cls, config: dict[str, Any]) -> bool:
        return cls.has_credentials(config) and isinstance(
            config.get(GREENELY_FACILITY_ID), str
        ) and bool(config.get(GREENELY_FACILITY_ID))

    @staticmethod
    def facility_id(config: dict[str, Any]) -> str | None:
        value = config.get(GREENELY_FACILITY_ID)
        return value if isinstance(value, str) and value else None

    async def async_login(self, email: str, password: str) -> None:
        self.validate_credentials(email, password)
        await self._client.async_login(email, password)

    @staticmethod
    def select_facility(facilities: list[dict[str, Any]], facility_id: str) -> dict[str, Any]:
        """Select one configured facility from the API response."""
        if not isinstance(facility_id, str) or not facility_id:
            raise GreenelyError("unexpected_response")
        selected = next(
            (item for item in facilities if str(item.get("id")) == facility_id),
            None,
        )
        if selected is None:
            raise GreenelyError("unexpected_response")
        return selected

    async def async_create_config(
        self,
        email: str,
        password: str,
        facility_id: str,
    ) -> dict[str, Any]:
        """Authenticate and return the existing Greenely config payload."""
        self.validate_credentials(email, password)
        await self.async_login(email, password)
        facilities = await self.async_get_facilities()
        selected = self.select_facility(facilities, facility_id)
        return {
            "config": {
                "email": email,
                "password": password,
                "facility_id": facility_id,
            },
            "facility": selected,
        }

    async def async_get_refresh_data(self, config: dict[str, Any]) -> dict[str, Any]:
        """Load and sanitize the facility data used by the manager refresh."""
        if not self.is_configured(config):
            raise GreenelyError("invalid_auth")
        facility_id = self.facility_id(config)
        await self.async_login(config[GREENELY_EMAIL], config[GREENELY_PASSWORD])
        facilities = await self.async_get_facilities()
        selected = self.select_facility(facilities, facility_id)
        data = await self.async_get_facility_invoices(facility_id)
        return {
            "facility_id": facility_id,
            "facility": sanitize_greenely_source(selected),
            "contracts": sanitize_greenely_source(data.get("contracts", [])),
            "invoices": sanitize_greenely_source(data.get("invoices", [])),
            "failed_contracts": data.get("failed_contracts", []),
        }

    async def async_get_consumption_data(
        self,
        config: dict[str, Any],
        start_date: date,
        end_date: date,
        month: str,
    ) -> dict[str, Any]:
        """Load and normalize Greenely consumption for the manager."""
        if not self.is_configured(config):
            raise GreenelyError("invalid_auth")
        facility_id = self.facility_id(config)
        await self.async_login(config[GREENELY_EMAIL], config[GREENELY_PASSWORD])
        payload = await self.async_get_consumption(facility_id, start_date, end_date)
        samples = [
            sample for sample in normalize_greenely_consumption(payload)
            if sample.get("localtime", "")[:7] == month
            and sample.get("localtime", "")[:10] < end_date.isoformat()
        ]
        summary = summarize_greenely_consumption(payload, month, end_date)
        if summary is None:
            raise GreenelyError(
                "no_consumption",
                greenely_consumption_payload_shape(payload, month),
            )
        analysis: dict[str, Any] = {}
        try:
            currency_payload = await self.async_get_consumption(
                facility_id, start_date, end_date, resolution="hourly", unit="currency"
            )
            analysis["consumption_cost"] = normalize_consumption_cost(
                currency_payload,
                start_date,
                end_date,
                summary.get("month_to_date_kwh"),
                month,
            )
        except GreenelyError as err:
            analysis["consumption_cost"] = {
                "schema": "greenely.consumption_cost.v1",
                "available": False,
                "status": "unavailable",
                "source": "greenely_consumption_currency",
                "error": err.code,
                "period": {"from": start_date.isoformat(), "to": end_date.isoformat(), "resolution": "hourly"},
            }
        for key, fetch, normalize in (
            ("cost_distribution", getattr(self._client, "async_get_cost_distribution", None), normalize_cost_distribution),
            ("spot_price", getattr(self._client, "async_get_spot_price", None), normalize_spot_price),
        ):
            if fetch is None:
                continue
            try:
                analysis[key] = normalize(
                    await fetch(facility_id, start_date, end_date), start_date, end_date
                )
            except GreenelyError as err:
                analysis[key] = {
                    "schema": f"greenely.{key}.v1",
                    "available": False,
                    "status": "unavailable",
                    "error": err.code,
                    "period": {"from": start_date.isoformat(), "to": end_date.isoformat(), "resolution": "daily"},
                }
        return {"samples": samples, "summary": summary, "analysis": analysis}

    async def async_process_invoice(
        self,
        config: dict[str, Any],
        contract_id: str,
        invoice_key: str,
        amount_due_sek: float | None,
        installation_id: str | None = None,
    ) -> dict[str, Any]:
        """Authenticate and process one Greenely invoice."""
        if not self.has_credentials(config):
            raise GreenelyError("invalid_auth")
        await self.async_login(config[GREENELY_EMAIL], config[GREENELY_PASSWORD])
        try:
            return await GreenelyInvoiceProcessor(self).async_process(
                contract_id, invoice_key, amount_due_sek, installation_id
            )
        except GreenelyError as err:
            raise GreenelyInvoiceError(err.code, "pdf_download") from err

    async def async_get_facilities(self) -> list[dict[str, Any]]:
        return await self._client.async_get_facilities()

    async def async_get_electricity_contracts(self, facility_id: str) -> list[dict[str, Any]]:
        return await self._client.async_get_electricity_contracts(facility_id)

    async def async_get_invoices(self, contract_id: str) -> list[dict[str, Any]]:
        return await self._client.async_get_invoices(contract_id)

    async def async_get_facility_invoices(self, facility_id: str) -> dict[str, Any]:
        return await self._client.async_get_facility_invoices(facility_id)

    async def async_get_consumption(
        self,
        facility_id: str,
        start_date: date,
        end_date: date,
        resolution: str = "hourly",
        unit: str = "usage",
    ) -> Any:
        return await self._client.async_get_consumption(
            facility_id,
            start_date,
            end_date,
            resolution,
            unit,
        )

    async def async_get_invoice_pdf(self, contract_id: str, invoice_key: str) -> bytes:
        return await self._client.async_get_invoice_pdf(contract_id, invoice_key)
