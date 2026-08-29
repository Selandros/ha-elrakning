"""E.ON grid manager with persistent cookie bootstrap."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from ..const import DOMAIN, EON_GRID_CONFIG_KEY, EON_GRID_PROVIDER, EON_GRID_UPDATE_EVENT
from .eon_auth import EonAuthError, EonSession
from .eon_client import EonClient
from .eon_models import calculate_eon_cost, normalize_user_profile, parse_monthly_consumption


class EonGridManager:
    """Own E.ON credentials, refreshes, normalized state and update events."""

    def __init__(self, hass, entry) -> None:
        self.hass = hass
        self.entry = entry
        self.store = Store(hass, 1, f"{DOMAIN}.eon_grid_state")
        self.state: dict[str, Any] = self._empty_state()
        self._refresh_unsub = None

    @property
    def configured(self) -> bool:
        config = self._config()
        return isinstance(config.get("cookies"), dict) and bool(config.get("customer_id"))

    async def async_load(self) -> None:
        cached = await self.store.async_load()
        if isinstance(cached, dict):
            self.state.update(cached)
        if not self.configured:
            self.state = self._empty_state()

    def async_start_refresh(self) -> None:
        if self._refresh_unsub is None:
            self._refresh_unsub = async_track_time_interval(
                self.hass,
                lambda _: self.hass.async_create_task(self.async_refresh()),
                timedelta(hours=1),
            )
        self.hass.async_create_task(self.async_refresh())

    async def async_save_cookie_header(self, cookie_header: str) -> dict[str, Any]:
        session = EonSession(self.hass)
        customer_id = await session.bootstrap(cookie_header)
        client = EonClient(session)
        profile = await client.async_get_user(customer_id)
        normalized = normalize_user_profile(profile, customer_id)
        await self._save_config({"cookies": session.cookies, "customer_id": customer_id})
        self.state = await self._build_state(normalized, client)
        await self.store.async_save(self.state)
        self.hass.bus.async_fire(EON_GRID_UPDATE_EVENT)
        return self.public_state()

    async def async_refresh(self) -> dict[str, Any]:
        config = self._config()
        if not self.configured:
            self.state = self._empty_state()
            return self.public_state()
        session = EonSession(self.hass, config.get("cookies"))
        client = EonClient(session)
        try:
            customer_id = config["customer_id"]
            profile = await client.async_get_user(customer_id)
            normalized = normalize_user_profile(profile, customer_id)
            state = await self._build_state(normalized, client)
            await self._save_config({"cookies": session.cookies, "customer_id": customer_id})
            self.state = state
            await self.store.async_save(self.state)
        except (EonAuthError, ValueError) as err:
            self.state["error"] = "reauth_required" if isinstance(err, EonAuthError) else "invalid_profile"
            self.state["reauth_required"] = isinstance(err, EonAuthError)
            await self.store.async_save(self.state)
        self.hass.bus.async_fire(EON_GRID_UPDATE_EVENT)
        return self.public_state()

    async def async_remove(self) -> dict[str, Any]:
        config = dict(self.entry.data)
        config.pop(EON_GRID_CONFIG_KEY, None)
        self.hass.config_entries.async_update_entry(self.entry, data=config)
        self.state = self._empty_state()
        await self.store.async_save(self.state)
        self.hass.bus.async_fire(EON_GRID_UPDATE_EVENT)
        return self.public_state()

    def public_state(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "provider": EON_GRID_PROVIDER,
            "provider_name": "E.ON",
            "reauth_required": self.state.get("reauth_required", False),
            "agreement": self.state.get("agreement"),
            "facility": self.state.get("facility"),
            "tariff": self.state.get("tariff"),
            "consumption": self.state.get("consumption"),
            "cost": self.state.get("cost"),
            "error": self.state.get("error"),
        }

    async def _build_state(self, normalized: dict[str, Any], client: EonClient) -> dict[str, Any]:
        facility = normalized.get("facility") or {}
        now = date.today()
        consumption = {"status": "missing", "resolution": "Monthly", "year": now.year, "month": now.month}
        if facility.get("point_of_delivery_number") and normalized.get("agreement"):
            payload = await client.async_get_monthly_consumption(facility["point_of_delivery_number"], now.year)
            consumption = parse_monthly_consumption(payload, now.year, now.month)
        amount = consumption.get("consumption_kwh") if consumption.get("status") == "ok" else None
        return {
            "agreement": normalized.get("agreement"),
            "facility": {
                "price_area": facility.get("price_area"),
                "fuse_ampere": facility.get("fuse_ampere"),
            },
            "tariff": normalized.get("tariff"),
            "consumption": consumption,
            "cost": calculate_eon_cost(amount, normalized.get("tariff")),
            "error": None,
            "reauth_required": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _save_config(self, config_data: dict[str, Any]) -> None:
        data = dict(self.entry.data)
        data[EON_GRID_CONFIG_KEY] = config_data
        self.hass.config_entries.async_update_entry(self.entry, data=data)

    def _config(self) -> dict[str, Any]:
        value = self.entry.data.get(EON_GRID_CONFIG_KEY, {})
        return value if isinstance(value, dict) else {}

    async def async_shutdown(self) -> None:
        if self._refresh_unsub:
            self._refresh_unsub()
            self._refresh_unsub = None

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "agreement": None,
            "facility": None,
            "tariff": None,
            "consumption": None,
            "cost": None,
            "reauth_required": False,
            "error": None,
        }
