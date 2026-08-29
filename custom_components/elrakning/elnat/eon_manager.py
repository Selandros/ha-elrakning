"""E.ON grid manager with app-login and cookie fallback."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store

from ..const import DOMAIN, EON_GRID_CONFIG_KEY, EON_GRID_PROVIDER, EON_GRID_UPDATE_EVENT, GRID_CONFIG_KEY
from .eon_auth import COMMON_API_USER_URL, EonAppSession, EonAuthError, EonSession
from .eon_client import EonAppClient, EonClient
from .eon_models import (
    calculate_eon_cost,
    normalize_locations,
    normalize_outage,
    normalize_user_profile,
    parse_monthly_consumption,
    parse_monthly_transfer,
)


class EonGridManager:
    """Own E.ON credentials, refreshes, normalized state and update events."""

    def __init__(self, hass, entry) -> None:
        self.hass = hass
        self.entry = entry
        self.store = Store(hass, 1, f"{DOMAIN}.eon_grid_state")
        self.state: dict[str, Any] = self._empty_state()
        self._refresh_unsub = None
        self._web_refresh_unsub = None
        self._app_session: EonAppSession | None = None
        self._web_session: EonSession | None = None

    @property
    def configured(self) -> bool:
        config = self._config()
        web = self._web_config(config)
        return (
            isinstance(web.get("cookies"), dict) and bool(web.get("customer_id"))
        ) or (
            config.get("auth") == "app"
            and isinstance(config.get("account_id"), str)
            and bool(config.get("password"))
        )

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
        self._web_session = session
        config = self._config_with_migration()
        config["web"] = {"cookies": session.cookies, "customer_id": customer_id}
        await self._save_config(config)
        if config.get("auth") == "app":
            return await self._refresh_app(self._app_session)
        self.state = await self._build_state(normalized, client)
        await self.store.async_save(self.state)
        self.hass.bus.async_fire(EON_GRID_UPDATE_EVENT)
        return self.public_state()

    async def async_save_app_credentials(self, account_id: str, password: str) -> dict[str, Any]:
        session = EonAppSession(self.hass)
        customer_id = await session.async_login(account_id, password)
        self._cancel_web_refresh()
        self._app_session = session
        config = {
            "auth": "app",
            "account_id": account_id.strip(),
            "password": password,
            "customer_id": customer_id,
        }
        await self._save_config(config)
        return await self._refresh_app(session)

    async def async_save_web_credentials(self, account_id: str, password: str) -> dict[str, Any]:
        """Report the unsupported browser-bound web login without changing app state."""
        if not account_id.strip() or not password:
            return {"status": "invalid_input", "error": "invalid_input"}
        return {"status": "browser_attestation_required", "error": "browser_attestation_required"}

    async def async_common_api_probe(self) -> dict[str, Any]:
        """Check whether the existing app token is accepted by the Common API."""
        config = self._config()
        if config.get("auth") != "app" or self._app_session is None:
            raise EonAuthError("reauth_required")
        customer_id = self._app_session.customer_id or config.get("customer_id")
        if not isinstance(customer_id, str) or not customer_id:
            raise EonAuthError("customer_id_missing")
        result = await self._app_session.async_request_bearer_json(
            "GET",
            COMMON_API_USER_URL,
            params={"readMeterChange": "true", "customerId": customer_id},
        )
        status = result["status"]
        response = {"provider": "eon", "provider_name": "E.ON", "probe": True, "http_status": status}
        if status == 200:
            response["status"] = "ok"
            response["payload"] = _redact_source_data(result.get("payload"))
        elif status in (401, 403):
            response["status"] = f"denied_{status}"
        else:
            response["status"] = "api_error"
        return response

    async def async_refresh(self) -> dict[str, Any]:
        config = self._config()
        if not self.configured:
            self.state = self._empty_state()
            return self.public_state()
        if config.get("auth") == "app":
            return await self._refresh_app(self._app_session)
        session = await self._get_web_session(config)
        client = EonClient(session)
        try:
            web = self._web_config(config)
            customer_id = web["customer_id"]
            profile = await client.async_get_user(customer_id)
            normalized = normalize_user_profile(profile, customer_id)
            state = await self._build_state(normalized, client)
            self.state = state
            await self.store.async_save(self.state)
            await self._persist_web_session(config, session)
            self._schedule_web_refresh(session)
        except (EonAuthError, ValueError) as err:
            self._cancel_web_refresh()
            self.state["error"] = "reauth_required" if isinstance(err, EonAuthError) else "invalid_profile"
            self.state["reauth_required"] = isinstance(err, EonAuthError)
            await self.store.async_save(self.state)
        self.hass.bus.async_fire(EON_GRID_UPDATE_EVENT)
        return self.public_state()

    async def _refresh_app(self, session: EonAppSession | None = None) -> dict[str, Any]:
        config = self._config()
        try:
            session = await self._get_app_session(config, session)
            client = EonAppClient(session)
            await client.async_get_contract_accounts()
            locations = normalize_locations(await client.async_get_locations())
            if not locations:
                raise ValueError("location_missing")
            if len(locations) > 1:
                raise ValueError("location_selection_required")
            installation = locations[0]
            now = date.today()
            month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
            month_end = datetime(
                now.year + (1 if now.month == 12 else 0),
                1 if now.month == 12 else now.month + 1,
                1,
                tzinfo=timezone.utc,
            )
            monthly = await client.async_get_monthly_transfer(
                installation["installation_identifier"],
                month_start.isoformat(),
                month_end.isoformat(),
                installation["production"],
                installation["street"],
                installation["city"],
                installation["postal_code"],
            )
            outage = normalize_outage(await client.async_get_outages(installation["point_of_delivery_number"]))
            state = {
                "agreement": {"status": "future" if installation.get("is_future") is True else "configured", "type": "ELECTRICITY_GRID"},
                "facility": {
                    "installation_identifier": installation.get("installation_identifier"),
                    "point_of_delivery_number": installation.get("point_of_delivery_number"),
                    "price_area": installation.get("price_area"),
                },
                "tariff": None,
                "consumption": parse_monthly_transfer(monthly, now.year, now.month),
                "cost": None,
                "outage": outage,
                "app_authenticated": True,
                "reauth_required": False,
                "error": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self.state = state
            await self.store.async_save(self.state)
        except ValueError as err:
            self.state.update({"app_authenticated": True, "reauth_required": False, "error": str(err)})
            await self.store.async_save(self.state)
        except EonAuthError as err:
            self.state.update({"app_authenticated": False, "reauth_required": True, "error": err.code})
            await self.store.async_save(self.state)
        self.hass.bus.async_fire(EON_GRID_UPDATE_EVENT)
        return self.public_state()

    async def _get_app_session(
        self, config: dict[str, Any], session: EonAppSession | None = None
    ) -> EonAppSession:
        """Return the cached app session, logging in only when it is absent or expired."""
        session = session or self._app_session or EonAppSession(self.hass)
        if not session.is_valid:
            await session.async_login(config["account_id"], config["password"])
        self._app_session = session
        return session

    async def _get_web_session(self, config: dict[str, Any]) -> EonSession:
        """Return the cached web session without rebuilding its cookie jar."""
        web = self._web_config(config)
        if self._web_session is None:
            self._web_session = EonSession(self.hass, web.get("cookies"))
        return self._web_session

    async def async_remove(self) -> dict[str, Any]:
        config = dict(self.entry.data)
        config.pop(EON_GRID_CONFIG_KEY, None)
        config.pop(GRID_CONFIG_KEY, None)
        self.hass.config_entries.async_update_entry(self.entry, data=config)
        self._app_session = None
        self._web_session = None
        self._cancel_web_refresh()
        self.state = self._empty_state()
        await self.store.async_save(self.state)
        self.hass.bus.async_fire(EON_GRID_UPDATE_EVENT)
        return self.public_state()

    async def async_source_data(self) -> dict[str, Any]:
        """Fetch the active E.ON source payload only after an explicit request."""
        config = self._config()
        if config.get("auth") == "app":
            session = await self._get_app_session(config)
            client = EonAppClient(session)
            contract_accounts = await client.async_get_contract_accounts()
            locations = await client.async_get_locations()
            normalized = normalize_locations(locations)
            monthly = {}
            outages: Any = []
            if len(normalized) == 1:
                installation = normalized[0]
                now = date.today()
                month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
                month_end = datetime(
                    now.year + (1 if now.month == 12 else 0),
                    1 if now.month == 12 else now.month + 1,
                    1,
                    tzinfo=timezone.utc,
                )
                monthly = await client.async_get_monthly_transfer(
                    installation["installation_identifier"],
                    month_start.isoformat(),
                    month_end.isoformat(),
                    installation["production"],
                    installation["street"],
                    installation["city"],
                    installation["postal_code"],
                )
                outages = await client.async_get_outages(installation["point_of_delivery_number"])
            return {
                "provider": "eon",
                "provider_name": "E.ON",
                "auth_mode": "app",
                "contract_accounts": _redact_source_data(contract_accounts),
                "locations": _redact_source_data(locations),
                "monthly_transfer": _redact_source_data(monthly),
                "outages": _redact_source_data(outages),
            }

        web = self._web_config(config)
        if isinstance(web.get("cookies"), dict) and web.get("customer_id"):
            session = await self._get_web_session(config)
            client = EonClient(session)
            profile = await client.async_get_user(web["customer_id"])
            normalized = normalize_user_profile(profile, web["customer_id"])
            monthly: Any = {}
            facility = normalized.get("facility") or {}
            if facility.get("point_of_delivery_number"):
                monthly = await client.async_get_monthly_consumption(
                    facility["point_of_delivery_number"], date.today().year
                )
            await self._persist_web_session(config, session)
            self._schedule_web_refresh(session)
            return {
                "provider": "eon",
                "provider_name": "E.ON",
                "auth_mode": "web",
                "user": _redact_source_data(profile),
                "consumption": _redact_source_data(monthly),
                "outages": [],
            }
        raise EonAuthError("not_configured")

    def public_state(self) -> dict[str, Any]:
        facility = self.state.get("facility") or {}
        config = self._config()
        auth_mode = "app" if config.get("auth") == "app" else "web" if self._web_config(config).get("cookies") else None
        return {
            "configured": self.configured,
            "provider": "eon",
            "provider_name": "E.ON",
            "auth_mode": auth_mode,
            "auth_method": auth_mode,
            "reauth_required": self.state.get("reauth_required", False),
            "agreement": self.state.get("agreement"),
            "facility": {
                "price_area": facility.get("price_area"),
                "fuse_ampere": facility.get("fuse_ampere"),
            } if facility else None,
            "tariff": self.state.get("tariff"),
            "consumption": self.state.get("consumption"),
            "cost": self.state.get("cost"),
            "outage": self.state.get("outage"),
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
        data[GRID_CONFIG_KEY] = {
            "provider": "eon",
            "auth_method": "app" if config_data.get("auth") == "app" else "web",
            "provider_config": dict(config_data),
        }
        data.pop(EON_GRID_CONFIG_KEY, None)
        self.hass.config_entries.async_update_entry(self.entry, data=data)

    def _config_with_migration(self) -> dict[str, Any]:
        """Return a copy with legacy flat web credentials represented under web."""
        config = dict(self._config())
        if "web" not in config and isinstance(config.get("cookies"), dict):
            config["web"] = {
                "cookies": config.pop("cookies"),
                "customer_id": config.pop("customer_id", None),
            }
        return config

    def _config(self) -> dict[str, Any]:
        envelope = self.entry.data.get(GRID_CONFIG_KEY)
        value = envelope.get("provider_config", {}) if isinstance(envelope, dict) else self.entry.data.get(EON_GRID_CONFIG_KEY, {})
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _web_config(config: dict[str, Any]) -> dict[str, Any]:
        web = config.get("web")
        if isinstance(web, dict):
            return web
        return config

    async def async_shutdown(self) -> None:
        self._app_session = None
        self._web_session = None
        self._cancel_web_refresh()
        if self._refresh_unsub:
            self._refresh_unsub()
            self._refresh_unsub = None

    def _schedule_web_refresh(self, session: EonSession) -> None:
        """Schedule one refresh shortly before the server-provided expiry."""
        self._cancel_web_refresh()
        seconds = session.seconds_until_expiry
        if seconds <= 0:
            return
        delay = max(1.0, seconds - 30.0)

        def _refresh_callback(_now) -> None:
            self._web_refresh_unsub = None
            self.hass.async_create_task(self.async_refresh())

        self._web_refresh_unsub = async_call_later(self.hass, delay, _refresh_callback)

    def _cancel_web_refresh(self) -> None:
        unsubscribe = getattr(self, "_web_refresh_unsub", None)
        if unsubscribe:
            unsubscribe()
            self._web_refresh_unsub = None

    async def _persist_web_session(self, config: dict[str, Any], session: EonSession) -> None:
        """Persist only the whitelisted web session cookies after a successful refresh."""
        web = self._web_config(config)
        if not web.get("customer_id"):
            return
        merged_config = self._config_with_migration()
        merged_config["web"] = {
            "cookies": session.cookies,
            "customer_id": web["customer_id"],
        }
        await self._save_config(merged_config)

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
            "outage": None,
            "app_authenticated": False,
        }


def _redact_source_data(value: Any) -> Any:
    """Redact credentials and customer-account identifiers from raw source data."""
    sensitive = (
        "accountid", "customeridentifier", "customerid", "contractaccountidentifier",
        "installationidentifier", "pointofdeliverynumber", "podid", "devicenumber",
        "premiseid", "installationids", "allaccountids", "session", "id", "password",
        "token", "secret", "cookie", "authorization",
    )
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_text = str(key).lower()
            result[key] = "[redacted]" if any(word in key_text for word in sensitive) else _redact_source_data(item)
        return result
    if isinstance(value, list):
        return [_redact_source_data(item) for item in value]
    return value
