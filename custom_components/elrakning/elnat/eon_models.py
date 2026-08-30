"""Pure E.ON response normalizers and cost calculations."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping


def normalize_user_profile(payload: Any, customer_id: str) -> dict[str, Any]:
    """Normalize the verified E.ON profile shape without exposing identifiers."""
    if not isinstance(payload, Mapping) or payload.get("customerIdentifier") != customer_id:
        raise ValueError("customer_id_mismatch")
    contracts = normalize_user_profiles(payload, customer_id)
    if not contracts:
        return {"agreement": None, "facility": None, "tariff": None}
    return contracts[0]


def normalize_user_profiles(payload: Any, customer_id: str) -> list[dict[str, Any]]:
    """Normalize every compatible web grid contract for hybrid matching."""
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
    return contracts


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


def normalize_grouped_contracts(payload: Any, installation_ids: set[str]) -> list[dict[str, Any]]:
    """Normalize verified electricity-grid contracts from the app response."""
    if not isinstance(payload, list):
        return []
    contracts = []
    for location in payload:
        if not isinstance(location, Mapping) or not isinstance(location.get("contractsByType"), list):
            continue
        for grouped in location["contractsByType"]:
            if not isinstance(grouped, Mapping) or grouped.get("type") != "ELECTRICITY_CONS_GRID":
                continue
            installation_id = grouped.get("installationId")
            if not isinstance(installation_id, str) or installation_id not in installation_ids:
                continue
            premise = grouped.get("premiseInformation")
            premise = premise if isinstance(premise, Mapping) else {}
            grouped_contracts = grouped.get("contracts")
            if not isinstance(grouped_contracts, list):
                continue
            for contract in grouped_contracts:
                if not isinstance(contract, Mapping):
                    continue
                contracts.append({
                    "installation_identifier": installation_id,
                    "agreement": {
                        "status": agreement_status(contract.get("status"), contract.get("startDate"), contract.get("endDate")),
                        "type": grouped.get("type"),
                        "name": contract.get("name"),
                        "start_date": contract.get("startDate"),
                        "end_date": contract.get("endDate"),
                    },
                    "facility": {
                        "fuse_ampere": _fuse_ampere(contract.get("fuseSize")),
                        "price_area": normalize_price_area(premise.get("priceArea")),
                        "grid_area": premise.get("gridArea"),
                    },
                    "tariff": normalize_grouped_tariff(contract),
                })
    return contracts


def normalize_grouped_tariff(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize grouped tariff entries while preserving unknown verified rows."""
    prices = contract.get("prices") if isinstance(contract.get("prices"), Mapping) else {}
    entries = []
    raw_entries = prices.get("entries")
    if isinstance(raw_entries, list):
        for item in raw_entries:
            if not isinstance(item, Mapping):
                continue
            price = item.get("price")
            if not isinstance(price, Mapping):
                continue
            entries.append({
                "key": item.get("name"),
                "label": item.get("name"),
                "value": price.get("value"),
                "number_unit": price.get("numberUnit"),
                "divisor_unit": price.get("divisorUnit"),
            })
    result = {
        "title": prices.get("title"),
        "subtitle": prices.get("subtitle"),
        "entries": entries,
        "subscription_fee_sek_per_month": None,
        "transfer_fee_ore_per_kwh": None,
        "energy_tax_ore_per_kwh": None,
        "estimated_yearly_cost_sek": None,
    }
    for entry in entries:
        units = (entry["number_unit"], entry["divisor_unit"])
        if entry["label"] == "Abonnemangsavgift" and units == ("KR", "MONTH"):
            result["subscription_fee_sek_per_month"] = _number_from(entry["value"])
        elif entry["label"] == "Elöverföringsavgift" and units == ("ORE", "KWH"):
            result["transfer_fee_ore_per_kwh"] = _number_from(entry["value"])
        elif entry["label"] == "Energiskatt" and units == ("ORE", "KWH"):
            result["energy_tax_ore_per_kwh"] = _number_from(entry["value"])
        elif entry["label"] == "Beräknad årskostnad" and units == ("KR", "NONE"):
            result["estimated_yearly_cost_sek"] = _number_from(entry["value"])
    transfer = result["transfer_fee_ore_per_kwh"]
    energy_tax = result["energy_tax_ore_per_kwh"]
    gross = result["subtitle"] == "Samtliga priser är inklusive moms."
    result["grid_price"] = {
        "vat_included": gross,
        "price_basis": "gross" if gross else "unknown",
        "source": "grouped_contracts",
        "source_subtitle": result["subtitle"],
        "fixed_monthly_sek": result["subscription_fee_sek_per_month"],
        "transfer_ore_per_kwh_gross": transfer,
        "energy_tax_ore_per_kwh_gross": energy_tax,
        "variable_total_ore_per_kwh_gross": (
            transfer + energy_tax
            if transfer is not None and energy_tax is not None
            else None
        ),
        "yearly_estimated_sek": result["estimated_yearly_cost_sek"],
    }
    return result


def normalize_price_area(value: Any) -> str | None:
    """Normalize the verified price-area spelling for neutral UI state."""
    if not isinstance(value, str) or not value.strip():
        return None
    return " ".join(value.strip().replace("_", " ").split())


def _mapping_values(value: Any):
    if isinstance(value, Mapping):
        yield value
        for nested in value.values():
            yield from _mapping_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _mapping_values(nested)


def _nested_value(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _number_from(value: Any) -> float | None:
    return float(value) if _is_number(value) else None


def _fuse_ampere(value: Any) -> float | None:
    """Parse the verified grouped-contract fuse-size representation."""
    if isinstance(value, str):
        value = value.strip().split(" ", 1)[0]
        try:
            return float(value)
        except ValueError:
            return None
    return _number_from(value)


def _price_value(value: Any, number_unit: str, divisor_unit: str) -> float | None:
    if not isinstance(value, Mapping):
        return None
    if value.get("numberUnit") != number_unit or value.get("divisorUnit") != divisor_unit:
        return None
    return _number_from(value.get("value"))


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


def normalize_locations(payload: Any) -> list[dict[str, Any]]:
    """Normalize compatible electricity-grid installations from Locations."""
    if not isinstance(payload, list):
        raise ValueError("locations_unsupported")
    locations: list[dict[str, Any]] = []
    for location in payload:
        if not isinstance(location, Mapping) or not isinstance(location.get("installations"), list):
            continue
        for installation in location["installations"]:
            if not isinstance(installation, Mapping):
                continue
            if installation.get("productType") != "ELECTRICITY" or installation.get("serviceType") != "GRID":
                continue
            address = installation.get("address")
            if not isinstance(address, Mapping):
                raise ValueError("locations_unsupported")
            if (
                not isinstance(installation.get("id"), str)
                or not isinstance(installation.get("podId"), str)
                or not isinstance(installation.get("production"), bool)
            ):
                raise ValueError("locations_unsupported")
            if any(not isinstance(address.get(key), str) or not address[key].strip() for key in ("fullStreet", "city", "postalCode")):
                raise ValueError("locations_unsupported")
            locations.append({
                "installation_identifier": installation["id"],
                "point_of_delivery_number": installation["podId"],
                "street": address["fullStreet"],
                "city": address["city"],
                "postal_code": address["postalCode"],
                "price_area": normalize_price_area(installation.get("priceArea")),
                "production": installation["production"],
                "is_future": installation.get("isFuture"),
                "elna_service_status": installation.get("elnaServiceStatus"),
            })
    return locations


def parse_monthly_transfer(payload: Any, year: int, month: int) -> dict[str, Any]:
    """Parse one month from the verified middlelayer MONTH response."""
    if not isinstance(payload, Mapping) or payload.get("productType") != "ELECTRICITY" or payload.get("aggregation") != "MONTH":
        return {"status": "unsupported", "resolution": "Monthly"}
    transfers = payload.get("transfer")
    if not isinstance(transfers, list):
        return {"status": "unsupported", "resolution": "Monthly"}
    for item in transfers:
        if not isinstance(item, Mapping) or not isinstance(item.get("timestamp"), str):
            continue
        try:
            timestamp = datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if timestamp.year != year or timestamp.month != month:
            continue
        consumption = item.get("consumption")
        if not isinstance(consumption, Mapping):
            return {"status": "missing", "resolution": "Monthly", "year": year, "month": month, "reason": "consumption_missing"}
        if consumption.get("padded") is True:
            return {"status": "missing", "resolution": "Monthly", "year": year, "month": month, "reason": "padded"}
        total = consumption.get("total")
        if not _is_number(total):
            return {"status": "unsupported", "resolution": "Monthly"}
        return {"status": "ok", "resolution": "Monthly", "year": year, "month": month, "consumption_kwh": float(total)}
    return {"status": "missing", "resolution": "Monthly", "year": year, "month": month, "reason": "month_missing"}


def normalize_outage(payload: Any) -> dict[str, Any]:
    """Normalize outage status without assigning semantics to unknown types."""
    items = payload if isinstance(payload, list) else [payload]
    visible = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if item.get("outageType") == "NO_INFO" and item.get("affected") == 0:
            continue
        visible.append({
            "outage_type": item.get("outageType"),
            "affected": item.get("affected"),
            "title": item.get("title"),
            "message": item.get("message") or item.get("messageShort"),
            "planned_arrival": item.get("plannedArrival"),
            "estimate": item.get("estimate"),
        })
    return {"status": "no_known_outage" if not visible else "outage", "outages": visible}


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
