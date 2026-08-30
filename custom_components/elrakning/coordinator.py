"""Coordinate spot prices from Home Assistant's Nord Pool integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import NORD_POOL_DOMAIN

_LOGGER = logging.getLogger(__name__)
_NEXT_DAY_PREFETCH_START_HOUR = 14


@dataclass(frozen=True)
class PricePeriod:
    """A normalized price period in SEK/kWh."""

    start: datetime
    end: datetime
    price: float


@dataclass(frozen=True)
class PriceData:
    """Normalized daily Nord Pool data."""

    area: str | None
    currency: str | None
    date: date
    periods: tuple[PricePeriod, ...]
    error: str | None = None


class ElrakningCoordinator(DataUpdateCoordinator[PriceData]):
    """Fetch and normalize today's Nord Pool prices."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self._price_data_by_date: dict[date, PriceData] = {}
        self._active_price_date: date | None = None
        self._next_day_last_attempt: tuple[date, datetime] | None = None
        self._midnight_recovery_task: asyncio.Task | None = None
        super().__init__(
            hass,
            logger=_LOGGER,
            config_entry=entry,
            name="elrakning_spotpris",
            update_interval=timedelta(minutes=15),
        )

    async def _async_update_data(self) -> PriceData:
        """Fetch today's periods through the Core Nord Pool service."""
        now = dt_util.now()
        today = now.date()
        cached = self._price_data_by_date.get(today)
        if self._active_price_date != today and cached and cached.periods:
            current = cached
        else:
            current = await self.async_get_price_data(today, refresh=True)
        self._active_price_date = today
        if now.hour >= _NEXT_DAY_PREFETCH_START_HOUR:
            await self._async_maybe_prefetch_next_day(now, today)
        return current

    async def async_get_price_data(self, target_date: date, *, refresh: bool = False) -> PriceData:
        """Return cached data for a local date, fetching it when needed."""
        cached = self._price_data_by_date.get(target_date)
        if cached and cached.periods and not refresh:
            return cached
        data = await self._async_fetch_date(target_date)
        if data.periods:
            self._cache_price_data(data)
        return data

    def _cache_price_data(self, data: PriceData) -> None:
        """Keep current-month periods available for billing without unbounded growth."""
        self._price_data_by_date[data.date] = data
        today = dt_util.now().date()
        keep_dates = {
            target_date
            for target_date in self._price_data_by_date
            if target_date.year == today.year and target_date.month == today.month
        }
        keep_dates.update({today, today + timedelta(days=1), data.date})
        self._price_data_by_date = {
            target_date: cached
            for target_date, cached in self._price_data_by_date.items()
            if target_date in keep_dates
        }

    async def _async_maybe_prefetch_next_day(self, now: datetime, today: date) -> None:
        """Try tomorrow at most once per local hour until it is cached."""
        tomorrow = today + timedelta(days=1)
        cached = self._price_data_by_date.get(tomorrow)
        if cached and cached.periods:
            return
        attempt_hour = now.replace(minute=0, second=0, microsecond=0)
        if self._next_day_last_attempt == (today, attempt_hour):
            return
        self._next_day_last_attempt = (today, attempt_hour)
        await self.async_get_price_data(tomorrow)

    async def _async_fetch_date(self, target_date: date) -> PriceData:
        """Fetch and normalize one local Nord Pool date."""
        nord_pool_entries = self.hass.config_entries.async_entries(NORD_POOL_DOMAIN)
        if not nord_pool_entries:
            return PriceData(None, None, target_date, (), "missing_integration")

        nord_pool_entry = nord_pool_entries[0]
        area = self._get_config_value(nord_pool_entry, "areas")
        if not area:
            area = self._get_config_value(nord_pool_entry, "area")
        currency = self._get_config_value(nord_pool_entry, "currency") or "SEK"
        if isinstance(area, list):
            area = area[0] if area else None
        if not area:
            return PriceData(None, currency, target_date, (), "data_unavailable")

        try:
            response = await self.hass.services.async_call(
                NORD_POOL_DOMAIN,
                "get_price_indices_for_date",
                {
                    "config_entry": nord_pool_entry.entry_id,
                    "areas": [area],
                    "currency": currency,
                    "date": target_date.isoformat(),
                    "resolution": "15",
                },
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError:
            return PriceData(area, currency, target_date, (), "data_unavailable")

        raw_periods = response.get(area, []) if response else []
        periods = tuple(self._normalize_period(period) for period in raw_periods)
        periods = tuple(period for period in periods if period is not None)
        if not periods:
            return PriceData(area, currency, target_date, (), "data_unavailable")
        return PriceData(area, currency, target_date, periods)

    async def async_prefetch_next_day(self) -> None:
        """Cache tomorrow's prices once before the local day changes."""
        target_date = dt_util.now().date() + timedelta(days=1)
        await self.async_get_price_data(target_date)

    def async_schedule_midnight_recovery(self) -> None:
        """Start bounded retries only when the new day is unavailable."""
        today = dt_util.now().date()
        if self.data and self.data.date == today and self.data.periods:
            self.cancel_midnight_recovery()
            return
        if self._midnight_recovery_task and not self._midnight_recovery_task.done():
            return
        self._midnight_recovery_task = self.hass.async_create_task(
            self._async_midnight_recovery(today)
        )

    async def _async_midnight_recovery(self, target_date: date) -> None:
        """Retry a failed rollover a bounded number of times."""
        for delay in (15, 30, 60, 120, 240):
            await asyncio.sleep(delay)
            if dt_util.now().date() != target_date:
                return
            await self.async_request_refresh()
            if self.data and self.data.date == target_date and self.data.periods:
                return

    def cancel_midnight_recovery(self) -> None:
        """Cancel a pending rollover recovery task."""
        if self._midnight_recovery_task and not self._midnight_recovery_task.done():
            self._midnight_recovery_task.cancel()
        self._midnight_recovery_task = None

    @staticmethod
    def _get_config_value(entry: ConfigEntry, key: str) -> Any:
        """Read a Nord Pool setting from entry data or options."""
        return entry.options.get(key, entry.data.get(key))

    @staticmethod
    def _normalize_period(period: dict[str, Any]) -> PricePeriod | None:
        """Convert Nord Pool's SEK/MWh value to SEK/kWh once."""
        try:
            start = dt_util.parse_datetime(period["start"])
            end = dt_util.parse_datetime(period["end"])
            raw_price = float(period["price"])
        except (KeyError, TypeError, ValueError):
            return None
        if start is None or end is None:
            return None
        return PricePeriod(start, end, raw_price / 1000)
