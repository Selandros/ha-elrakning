"""Read-only E.ON API client."""

from __future__ import annotations

from datetime import date
from typing import Any

from .eon_auth import EonAppSession, EonSession

COMMON_USER_URL = "https://eoncommonapiapirun.azurewebsites.net/api/neo/api/cj/cv/v1/rest/v2/user"
CONSUMPTION_URL = "https://eonmycoapirun.azurewebsites.net/api/consumption"
MIDDLELAYER_BASE = "https://eonappapimrun.azure-api.net/middlelayer"
CONTRACT_ACCOUNTS_URL = f"{MIDDLELAYER_BASE}/v2/ContractAccounts"
LOCATIONS_URL = f"{MIDDLELAYER_BASE}/Locations"
MONTHLY_TRANSFER_URL = f"{MIDDLELAYER_BASE}/energy/transfer/ELECTRICITY/MONTH"
TREND_URL = f"{MIDDLELAYER_BASE}/energy/trend"
OUTAGES_URL = f"{MIDDLELAYER_BASE}/OutagesV2"
GROUPED_CONTRACTS_URL = "https://api.mobile-apps.eon.se/middlelayer/contracts/grouped"


class EonClient:
    """Fetch only the verified E.ON profile and Monthly consumption endpoints."""

    def __init__(self, session: EonSession) -> None:
        self.session = session

    async def async_get_user(self, customer_id: str) -> Any:
        return await self.session.request_json(
            "GET",
            COMMON_USER_URL,
            params={"readMeterChange": "true", "customerId": customer_id},
        )

    async def async_get_monthly_consumption(self, point_of_delivery_number: str, year: int) -> Any:
        return await self.session.request_json(
            "POST",
            CONSUMPTION_URL,
            json={
                "startDate": f"{year:04d}-01-01",
                "endDate": f"{year + 1:04d}-01-01",
                "resolution": "Monthly",
                "pointOfDeliveryNumber": point_of_delivery_number,
                "consumptionType": "Electricity",
            },
        )


class EonAppClient:
    """Access only the verified E.ON middlelayer endpoints."""

    def __init__(self, session: EonAppSession) -> None:
        self.session = session

    async def async_get_contract_accounts(self) -> Any:
        return await self.session.request_json("GET", CONTRACT_ACCOUNTS_URL)

    async def async_get_locations(self) -> Any:
        return await self.session.request_json(
            "GET", LOCATIONS_URL, params={"includeFullElnaStatus": "true"}
        )

    async def async_get_monthly_transfer(
        self,
        installation_identifier: str,
        from_timestamp: str,
        to_timestamp: str,
        production: bool,
        street: str,
        city: str,
        postal_code: str,
    ) -> Any:
        return await self.async_get_transfer(
            "MONTH",
            installation_identifier,
            from_timestamp,
            to_timestamp,
            production,
            street,
            city,
            postal_code,
        )

    async def async_get_transfer(
        self,
        aggregation: str,
        installation_identifier: str,
        from_timestamp: str,
        to_timestamp: str,
        production: bool,
        street: str,
        city: str,
        postal_code: str,
    ) -> Any:
        if aggregation not in {"MONTH", "DAY", "HOUR", "QUARTER_HOUR"}:
            raise ValueError("unsupported_transfer_aggregation")
        return await self.session.request_json(
            "GET",
            f"{MIDDLELAYER_BASE}/energy/transfer/ELECTRICITY/{aggregation}",
            params={
                "includeReference": "true",
                "includeTotal": "true",
                "installations": f"{installation_identifier}:ELECTRICITY:GRID:{str(production).lower()}",
                "from": from_timestamp,
                "to": to_timestamp,
                "locationStreet": street,
                "locationCity": city,
                "locationPostalCode": postal_code,
                "limelightActivationDate": "",
                "language": "sv",
            },
        )

    async def async_get_hourly_transfer(
        self,
        installation_identifier: str,
        from_timestamp: str,
        to_timestamp: str,
        production: bool,
        street: str,
        city: str,
        postal_code: str,
    ) -> Any:
        return await self.async_get_transfer(
            "HOUR",
            installation_identifier,
            from_timestamp,
            to_timestamp,
            production,
            street,
            city,
            postal_code,
        )

    async def async_get_daily_transfer(
        self,
        installation_identifier: str,
        from_timestamp: str,
        to_timestamp: str,
        production: bool,
        street: str,
        city: str,
        postal_code: str,
    ) -> Any:
        return await self.async_get_transfer(
            "DAY",
            installation_identifier,
            from_timestamp,
            to_timestamp,
            production,
            street,
            city,
            postal_code,
        )

    async def async_get_quarter_hour_transfer(
        self,
        installation_identifier: str,
        from_timestamp: str,
        to_timestamp: str,
        production: bool,
        street: str,
        city: str,
        postal_code: str,
    ) -> Any:
        return await self.async_get_transfer(
            "QUARTER_HOUR",
            installation_identifier,
            from_timestamp,
            to_timestamp,
            production,
            street,
            city,
            postal_code,
        )

    async def async_get_outages(self, point_of_delivery_number: str) -> Any:
        return await self.session.request_json(
            "GET", OUTAGES_URL, params={"podIds": point_of_delivery_number}
        )

    async def async_get_trend(self, installation_identifier: str) -> Any:
        return await self.session.request_json(
            "GET",
            TREND_URL,
            params={
                "installations": f"{installation_identifier}:ELECTRICITY:GRID:false",
                "includeElectricityCost": "true",
                "language": "sv",
            },
        )

    async def async_get_grouped_contracts(
        self, private_installation_ids: list[str], sme_installation_ids: list[str]
    ) -> Any:
        """Fetch grouped contracts for the classified electricity-grid installations."""
        params: dict[str, list[str]] = {}
        if private_installation_ids:
            params["privateInstallationIds"] = private_installation_ids
        if sme_installation_ids:
            params["smeInstallationIds"] = sme_installation_ids
        return await self.session.request_json("GET", GROUPED_CONTRACTS_URL, params=params)
