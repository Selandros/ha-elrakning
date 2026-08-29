"""Pure E.ON response normalizers and cost calculations."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping


def normalize_user_profile(payload: Any, customer_id: str) -> dict[str, Any]:
    """Normalize the verified E.ON profile shape without exposing identifiers."""
    if not isinstance(payload, Mapping) or payload.get("customerIdentifier") != customer_id:
        raise ValueError("customer_id_mismatch")
    accounts = []
    for key in ("privateContractAccounts", "smeContractAccounts"):
        values = payload.get(key)
        if isinstance(values, list):
            accounts.extend(item for item in values if isinstance(item, Mapping))
    contracts = []
    for account in accounts:
        delivery_contracts = account.get("deliveryContracts")
        if not isinstance(delivery_contracts, list):
            continue
        for contract in delivery_contracts:
            if not isinstance(contract, Mapping):
                continue
            installation = contract.get("installation")
            engagements = contract.get("engagements")
            if not isinstance(installation, Mapping) or not isinstance(engagements, list):
                continue
            grid_engagements = [
                item for item in engagements
                if isinstance(item, Mapping) and item.get("engagementType") == "ELECTRICITY_GRID"
            ]
            if not grid_engagements:
                continue
            engagement = _select_engagement(grid_engagements)
            grid_area = installation.get("gridArea")
            fuse = installation.get("fuse")
            contracts.append({
                "agreement": {
                    "status": agreement_status(engagement.get("engagementStatus"), engagement.get("startDate"), engagement.get("endDate")),
                    "type": engagement.get("engagementType"),
                    "description": engagement.get("description"),
                    "start_date": engagement.get("startDate"),
                    "end_date": engagement.get("endDate"),
                },
                "facility": {
                    "installation_identifier": installation.get("installationIdentifier"),
                    "point_of_delivery_number": installation.get("pointOfDeliveryNumber"),
                    "price_area": grid_area.get("priceArea") if isinstance(grid_area, Mapping) else None,
                    "fuse_ampere": fuse.get("size") if isinstance(fuse, Mapping) else None,
                },
                "tariff": normalize_tariff(engagement.get("prices"), engagement.get("estimatedYearlyCost")),
            })
    if not contracts:
        return {"agreement": None, "facility": None, "tariff": None}
    return contracts[0]


def normalize_tariff(prices: Any, estimated_yearly_cost: Any) -> dict[str, Any]:
    """Read gross private-customer tariff fields from an engagement."""
    prices = prices if isinstance(prices, Mapping) else {}
    estimated_yearly_cost = estimated_yearly_cost if isinstance(estimated_yearly_cost, Mapping) else {}
    return {
        "subscription_fee_sek_per_month": _gross_amount(prices.get("subscriptionFee")),
        "transfer_fee_ore_per_kwh": _gross_amount(prices.get("transferFee")),
        "energy_tax_ore_per_kwh": _gross_amount(prices.get("energyTax")),
        "estimated_yearly_cost_sek": _first_number(
            estimated_yearly_cost.get("costInclVAT"),
            estimated_yearly_cost.get("grossAmount"),
        ),
    }


def parse_monthly_consumption(payload: Any, year: int, month: int) -> dict[str, Any]:
    """Parse only the verified Monthly energy response contract."""
    if not isinstance(payload, Mapping):
        return {"status": "unsupported", "resolution": "Monthly"}
    if payload.get("hasNoValues") is True:
        return {"status": "missing", "reason": "no_values", "resolution": "Monthly"}
    block = next(
        (
            value for value in payload.values()
            if isinstance(value, Mapping)
            and value.get("subType") == "energy"
            and value.get("resolution") == "Monthly"
        ),
        None,
    )
    if block is None:
        return {"status": "unsupported", "resolution": "Monthly"}
    year_data = block.get(str(year))
    months = year_data.get("months") if isinstance(year_data, Mapping) else None
    if not isinstance(months, list) or not 1 <= month <= len(months):
        return {"status": "missing", "reason": "month_missing", "resolution": "Monthly", "year": year}
    value = months[month - 1]
    if value is None:
        return {"status": "missing", "reason": "month_missing", "resolution": "Monthly", "year": year, "month": month}
    if not _is_number(value):
        return {"status": "unsupported", "resolution": "Monthly", "year": year, "month": month}
    return {"status": "ok", "resolution": "Monthly", "year": year, "month": month, "consumption_kwh": float(value)}


def calculate_eon_cost(consumption_kwh: Any, tariff: Mapping[str, Any] | None) -> dict[str, float] | None:
    """Calculate gross E.ON grid cost from normalized tariff units."""
    if not _is_number(consumption_kwh) or not isinstance(tariff, Mapping):
        return None
    fixed = tariff.get("subscription_fee_sek_per_month")
    transfer = tariff.get("transfer_fee_ore_per_kwh")
    tax = tariff.get("energy_tax_ore_per_kwh")
    if not all(_is_number(value) for value in (fixed, transfer, tax)):
        return None
    variable = float(consumption_kwh) * (float(transfer) + float(tax)) / 100
    return {
        "subscription_fee_sek": float(fixed),
        "transfer_cost_sek": float(consumption_kwh) * float(transfer) / 100,
        "energy_tax_sek": float(consumption_kwh) * float(tax) / 100,
        "total_sek": float(fixed) + variable,
    }


def agreement_status(raw_status: Any, start_date: Any, end_date: Any) -> str:
    """Keep future agreements distinct from active and ended agreements."""
    today = date.today()
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if start and start > today:
        return "future"
    if end and end < today:
        return "ended"
    if raw_status in {"ACTIVE", "FUTURE", "INACTIVE"}:
        return {"ACTIVE": "active", "FUTURE": "future", "INACTIVE": "ended"}[raw_status]
    return "configured"


def _select_engagement(engagements: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    return next((item for item in engagements if item.get("engagementStatus") in {"ACTIVE", "FUTURE"}), engagements[0])


def _gross_amount(value: Any) -> float | None:
    return _first_number(value.get("grossAmount") if isinstance(value, Mapping) else None)


def _first_number(*values: Any) -> float | None:
    return next((float(value) for value in values if _is_number(value)), None)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None
