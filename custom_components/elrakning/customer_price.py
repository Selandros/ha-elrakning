"""Build customer prices from spot periods and generic provider data."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable

from .elhandel.models import ProviderData
from .elhandel.provider_registry import provider_data_from_state


VAT_MULTIPLIER = 1.25


def grid_variable_cost_ex_vat(grid_price: dict[str, Any] | None) -> float | None:
    """Convert a verified gross grid variable rate to the price graph basis."""
    if not isinstance(grid_price, dict) or grid_price.get("vat_included") is not True:
        return None
    value = grid_price.get("variable_total_ore_per_kwh_gross")
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value / 100 / VAT_MULTIPLIER if isfinite(value) else None


@dataclass(frozen=True)
class CustomerPricePeriod:
    """One customer-price period in SEK/kWh."""

    start: Any
    end: Any
    spot_price_ex_vat: float
    electricity_cost_ex_vat: float | None
    subtotal_ex_vat: float
    vat: float
    customer_price: float


@dataclass(frozen=True)
class CustomerPriceData:
    """Customer-price periods and the generic adjustment metadata."""

    mode: str
    provider: str | None
    electricity_cost_ex_vat: float | None
    periods: tuple[CustomerPricePeriod, ...]


def build_customer_price_data(
    spot_periods: Iterable[Any], provider_data: ProviderData | dict[str, Any] | None
) -> CustomerPriceData:
    """Apply a valid generic variable electricity cost to spot periods."""
    provider_data = _coerce_provider_data(provider_data)
    electricity_cost_ex_vat = _variable_cost_ex_vat_sek_per_kwh(provider_data)
    periods = tuple(
        _build_period(period, electricity_cost_ex_vat)
        for period in spot_periods
    )
    return CustomerPriceData(
        mode="customer_price" if electricity_cost_ex_vat is not None else "spot_price",
        provider=provider_data.provider if provider_data else None,
        electricity_cost_ex_vat=electricity_cost_ex_vat,
        periods=periods,
    )


def _build_period(
    period: Any, electricity_cost_ex_vat: float | None
) -> CustomerPricePeriod:
    spot_price_ex_vat = float(period.price)
    subtotal_ex_vat = spot_price_ex_vat + (electricity_cost_ex_vat or 0.0)
    vat = subtotal_ex_vat * (VAT_MULTIPLIER - 1)
    customer_price = subtotal_ex_vat + vat
    return CustomerPricePeriod(
        start=period.start,
        end=period.end,
        spot_price_ex_vat=spot_price_ex_vat,
        electricity_cost_ex_vat=electricity_cost_ex_vat,
        subtotal_ex_vat=subtotal_ex_vat,
        vat=vat,
        customer_price=customer_price,
    )


def _coerce_provider_data(
    provider_data: ProviderData | dict[str, Any] | None,
) -> ProviderData | None:
    if isinstance(provider_data, ProviderData):
        return provider_data
    if isinstance(provider_data, dict):
        return provider_data_from_state(provider_data.get("provider"), provider_data)
    return None


def _variable_cost_ex_vat_sek_per_kwh(provider_data: ProviderData | None) -> float | None:
    if provider_data is None or provider_data.active_data.get("configured") is not True:
        return None
    tariff = provider_data.tariff
    value = tariff.get("variable_cost_ore_per_kwh_incl_vat") if isinstance(tariff, dict) else None
    try:
        cost_ore_per_kwh = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(cost_ore_per_kwh):
        return None
    return cost_ore_per_kwh / 100 / VAT_MULTIPLIER
