"""Read-only E.ON API client."""

from __future__ import annotations

from datetime import date
from typing import Any

from .eon_auth import EonSession

COMMON_USER_URL = "https://eoncommonapiapirun.azurewebsites.net/api/neo/api/cj/cv/v1/rest/v2/user"
CONSUMPTION_URL = "https://eonmycoapirun.azurewebsites.net/api/consumption"


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
