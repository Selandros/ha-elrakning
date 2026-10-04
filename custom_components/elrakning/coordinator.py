"""Coordinate spot prices from Home Assistant's Nord Pool integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import asyncio
import hashlib
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
PRICE_SERVICE_TIMEOUT_SECONDS = 180
PRICE_REQUEST_WAIT_SECONDS = 5


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
    known_at: datetime | None = None
    source_generation_id: str | None = None


class ElrakningCoordinator(DataUpdateCoordinator[PriceData]):
    """Fetch and normalize today's Nord Pool prices."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self._price_data_by_date: dict[date, PriceData] = {}
        self._active_price_date: date | None = None
        self._next_day_last_attempt: tuple[date, datetime] | None = None
        self._midnight_recovery_task: asyncio.Task | None = None
        self._price_fetch_tasks: dict[date, asyncio.Task] = {}
        self._site_binding: dict[str, Any] | None = None
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
        fetch_tasks = getattr(self, "_price_fetch_tasks", None)
        if not isinstance(fetch_tasks, dict):
            fetch_tasks = {}
            self._price_fetch_tasks = fetch_tasks
        task = fetch_tasks.get(target_date)
        if task is None or task.done():
            task = asyncio.create_task(self._async_fetch_date(target_date))
            fetch_tasks[target_date] = task
            task.add_done_callback(lambda completed: self._finish_price_fetch(target_date, completed))
        try:
            data = await asyncio.wait_for(
                asyncio.shield(task),
                timeout=PRICE_REQUEST_WAIT_SECONDS,
            )
        except asyncio.TimeoutError:
            binding = self._site_binding or {}
            return PriceData(
                binding.get("area"),
                binding.get("currency") or "SEK",
                target_date,
                (),
                "data_pending",
            )
        finally:
            if fetch_tasks.get(target_date) is task and task.done():
                fetch_tasks.pop(target_date, None)
        if data.periods:
            self._cache_price_data(data)
        return data

    def _finish_price_fetch(self, target_date: date, task: asyncio.Task) -> None:
        """Cache a completed shared fetch and notify existing coordinator listeners."""
        fetch_tasks = getattr(self, "_price_fetch_tasks", {})
        if fetch_tasks.get(target_date) is task:
            fetch_tasks.pop(target_date, None)
        if task.cancelled():
            return
        try:
            data = task.result()
        except Exception:
            return
        if not data.periods:
            return
        self._cache_price_data(data)
        self.async_set_updated_data(data)

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
        binding = self._site_binding
        if not binding:
            return PriceData(None, None, target_date, (), "site_unconfigured")
        config_entries = getattr(self.hass, "config_entries", None)
        available_entries = config_entries.async_entries(NORD_POOL_DOMAIN) if config_entries else []
        nord_pool_entry = self._resolve_bound_entry(binding)
        if nord_pool_entry is None:
            error = "missing_integration" if not available_entries else "data_unavailable"
            return PriceData(None, None, target_date, (), error)
        area = binding.get("area")
        currency = binding.get("currency") or "SEK"
        if not area:
            return PriceData(None, currency, target_date, (), "data_unavailable")
        service_domain = getattr(nord_pool_entry, "domain", None) or NORD_POOL_DOMAIN

        try:
            response = await asyncio.wait_for(
                self.hass.services.async_call(
                    service_domain,
                    "get_price_indices_for_date",
                    {
                        "config_entry": nord_pool_entry.entry_id,
                        "areas": [area],
                        "currency": currency,
                        "date": target_date.isoformat(),
                        "resolution": 15,
                    },
                    blocking=True,
                    return_response=True,
                ),
                timeout=PRICE_SERVICE_TIMEOUT_SECONDS,
            )
        except (HomeAssistantError, asyncio.TimeoutError):
            return PriceData(area, currency, target_date, (), "data_unavailable")

        raw_periods = response.get(area, []) if response else []
        periods = tuple(self._normalize_period(period) for period in raw_periods)
        periods = tuple(period for period in periods if period is not None)
        if not periods:
            return PriceData(area, currency, target_date, (), "data_unavailable")
        known_at = dt_util.now().astimezone(timezone.utc)
        source_generation_id = "np-" + hashlib.sha256(
            f"nord_pool|{nord_pool_entry.entry_id}|{area}|{currency}".encode()
        ).hexdigest()[:32]
        data = PriceData(area, currency, target_date, periods, None, known_at, source_generation_id)
        collector = getattr(self.hass, "data", {}).get("elrakning", {}).get("canonical_collector")
        if collector is not None:
            try:
                await collector.async_persist_nord_pool_frame(data, binding, dt_util.now())
            except (ValueError, OSError):
                _LOGGER.debug("Unable to persist canonical Nord Pool frame", exc_info=True)
        return data

    def _resolve_bound_entry(self, binding: dict[str, Any]) -> ConfigEntry | None:
        """Resolve the configured source entry without coupling it to site state."""
        entry_id = binding.get("config_entry_id") if isinstance(binding, dict) else None
        if not isinstance(entry_id, str) or not entry_id:
            return None
        config_entries = getattr(self.hass, "config_entries", None)
        lookup = getattr(config_entries, "async_entry_for_id", None)
        if callable(lookup):
            entry = lookup(entry_id)
            if entry is not None:
                return entry
        entries = config_entries.async_entries(NORD_POOL_DOMAIN) if config_entries else []
        return next((entry for entry in entries if entry.entry_id == entry_id), None)

    def discovered_binding(self) -> dict[str, Any] | None:
        """Describe the currently discovered Nord Pool resource for first-site migration."""
        entries = self.hass.config_entries.async_entries(NORD_POOL_DOMAIN)
        if not entries:
            return None
        entry = entries[0]
        area = self._get_config_value(entry, "areas") or self._get_config_value(entry, "area")
        if isinstance(area, list):
            area = area[0] if area else None
        if not area:
            return None
        return {
            "config_entry_id": entry.entry_id,
            "area": area,
            "currency": self._get_config_value(entry, "currency") or "SEK",
            "configured_at": dt_util.now().isoformat(),
        }

    def set_site_binding(self, binding: dict[str, Any] | None) -> None:
        """Switch the explicit price context and invalidate site-local cached data."""
        normalized = dict(binding) if isinstance(binding, dict) else None
        current_fingerprint = self._site_binding.get("binding_fingerprint") if self._site_binding else None
        fingerprint = normalized.get("binding_fingerprint") if normalized else None
        if fingerprint == current_fingerprint and normalized == self._site_binding:
            return
        self._site_binding = normalized
        self._price_data_by_date.clear()
        self._active_price_date = None
        fetch_tasks = getattr(self, "_price_fetch_tasks", {})
        for task in fetch_tasks.values():
            if not task.done():
                task.cancel()
        fetch_tasks.clear()

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
