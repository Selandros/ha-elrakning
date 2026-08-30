"""E.ON grid manager with app-login and cookie fallback."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import secrets
import time
from typing import Any

from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store

from ..const import DOMAIN, EON_GRID_CONFIG_KEY, EON_GRID_PROVIDER, EON_GRID_UPDATE_EVENT, GRID_CONFIG_KEY
from .eon_auth import EonAppSession, EonAuthError, EonSession
from .eon_client import EonAppClient, EonClient
from .eon_models import (
    calculate_eon_cost,
    normalize_locations,
    normalize_grouped_contracts,
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
        self._pending_web_handoff: dict[str, Any] | None = None
        self._app_session: EonAppSession | None = None
        self._web_session: EonSession | None = None
        self._app_source_snapshot: dict[str, Any] | None = None

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
        return await self._activate_web_session(session, customer_id)

    async def async_start_web_handoff(self, user_id: str) -> dict[str, Any]:
        """Create one short-lived browser handoff bound to one HA user."""
        self._pending_web_handoff = {
            "user_id": user_id,
            "state": secrets.token_urlsafe(32),
            "expires_at": time.monotonic() + 300,
        }
        return {
            "status": "waiting_for_login",
            "url": "https://www.eon.se/mitt-e-on/",
            "state": self._pending_web_handoff["state"],
        }

    async def async_complete_web_handoff(
        self, state: str, cookies: dict[str, str]
    ) -> dict[str, Any]:
        pending = self._pending_web_handoff
        if not pending:
            raise EonAuthError("pending_missing")
        if pending["expires_at"] <= time.monotonic():
            self._pending_web_handoff = None
            raise EonAuthError("handoff_expired")
        if not isinstance(state, str) or not secrets.compare_digest(state, pending["state"]):
            raise EonAuthError("handoff_rejected")
        # Consume the capability before network work so it cannot be replayed.
        self._pending_web_handoff = None
        session = EonSession(self.hass)
        customer_id = await session.bootstrap_cookies(cookies)
        return await self._activate_web_session(session, customer_id)

    async def _activate_web_session(self, session: EonSession, customer_id: str) -> dict[str, Any]:
        """Verify and activate a bootstrapped web session."""
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

    async def async_login(self, auth_method: str, account_id: str, password: str) -> dict[str, Any]:
        """Handle E.ON provider authentication without provider logic in GridManager."""
        if auth_method == "app":
            return await self.async_save_app_credentials(account_id, password)
        return {"status": "unsupported_auth_method", "error": "unsupported_auth_method"}

    async def async_fetch_app_sources(self) -> dict[str, Any]:
        """Fetch all verified read-only App sources without changing normalized state."""
        config = self._config()
        session = await self._get_app_session(config)
        client = EonAppClient(session)
        sources: dict[str, Any] = {
            "contract_accounts": None,
            "locations": None,
            "grouped_contracts": None,
            "monthly_transfer": [],
            "outages": [],
            "source_status": {},
        }

        async def fetch(name: str, request):
            try:
                payload = await request()
            except EonAuthError:
                raise
            except Exception:
                sources["source_status"][name] = {"status": "failed", "error": "api_error"}
                return None
            sources["source_status"][name] = {"status": "ok"}
            return payload

        sources["contract_accounts"] = await fetch("contract_accounts", client.async_get_contract_accounts)
        sources["locations"] = await fetch("locations", client.async_get_locations)
        try:
            locations = normalize_locations(sources["locations"])
        except (TypeError, ValueError):
            locations = []
        private_ids, sme_ids = _grouped_contract_installation_ids(sources["locations"])
        if private_ids or sme_ids:
            sources["grouped_contracts"] = await fetch(
                "grouped_contracts",
                lambda: client.async_get_grouped_contracts(private_ids, sme_ids),
            )
        else:
            sources["source_status"]["grouped_contracts"] = {"status": "skipped", "error": "installation_ids_missing"}

        now = date.today()
        month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        month_end = datetime(
            now.year + (1 if now.month == 12 else 0),
            1 if now.month == 12 else now.month + 1,
            1,
            tzinfo=timezone.utc,
        )
        monthly_status = []
        outage_status = []
        for installation in locations:
            installation_id = installation["installation_identifier"]
            try:
                monthly = await client.async_get_monthly_transfer(
                    installation_id,
                    month_start.isoformat(),
                    month_end.isoformat(),
                    installation["production"],
                    installation["street"],
                    installation["city"],
                    installation["postal_code"],
                )
                sources["monthly_transfer"].append({"installation_id": installation_id, "payload": monthly})
                monthly_status.append({"status": "ok"})
            except EonAuthError:
                raise
            except Exception:
                monthly_status.append({"status": "failed", "error": "api_error"})
            pod = installation["point_of_delivery_number"]
            try:
                outage = await client.async_get_outages(pod)
                sources["outages"].append({"installation_id": installation_id, "payload": outage})
                outage_status.append({"status": "ok"})
            except EonAuthError:
                raise
            except Exception:
                outage_status.append({"status": "failed", "error": "api_error"})
        sources["source_status"]["monthly_transfer"] = monthly_status or [{"status": "skipped"}]
        sources["source_status"]["outages"] = outage_status or [{"status": "skipped"}]
        self._app_source_snapshot = sources
        return sources

    async def async_save_web_credentials(self, account_id: str, password: str) -> dict[str, Any]:
        """Report the unsupported browser-bound web login without changing app state."""
        if not account_id.strip() or not password:
            return {"status": "invalid_input", "error": "invalid_input"}
        return {"status": "browser_attestation_required", "error": "browser_attestation_required"}

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
            await self._get_app_session(config, session)
            sources = await self.async_fetch_app_sources()
            locations = normalize_locations(sources.get("locations"))
            if not locations:
                raise ValueError("location_missing")
            state = self._build_app_state(sources, locations)
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

    def _build_app_state(self, sources: dict[str, Any], locations: list[dict[str, Any]]) -> dict[str, Any]:
        """Build public-safe app state from the collector snapshot."""
        now = date.today()
        installation_ids = {item["installation_identifier"] for item in locations}
        contracts = normalize_grouped_contracts(sources.get("grouped_contracts"), installation_ids)
        by_installation: dict[str, list[dict[str, Any]]] = {}
        for contract in contracts:
            by_installation.setdefault(contract["installation_identifier"], []).append(contract)
        installation = next(
            (
                item for item in locations
                if any(contract["agreement"]["status"] == "active" for contract in by_installation.get(item["installation_identifier"], []))
            ),
            next(
                (
                    item for item in locations
                    if any(contract["agreement"]["status"] == "future" for contract in by_installation.get(item["installation_identifier"], []))
                ),
                locations[0],
            ),
        )
        candidates = by_installation.get(installation["installation_identifier"], [])
        current = next((item for item in candidates if item["agreement"]["status"] == "active"), None)
        selected = current or next((item for item in candidates if item["agreement"]["status"] == "future"), None)
        monthly = next((item["payload"] for item in sources.get("monthly_transfer", []) if item.get("installation_id") == installation["installation_identifier"]), None)
        outage_payload = next((item["payload"] for item in sources.get("outages", []) if item.get("installation_id") == installation["installation_identifier"]), None)
        consumption = parse_monthly_transfer(monthly, now.year, now.month) if monthly is not None else {"status": "missing", "resolution": "Monthly"}
        agreement = selected["agreement"] if selected else {
            "status": "future" if installation.get("is_future") is True else "configured",
            "type": "ELECTRICITY_CONS_GRID",
        }
        tariff = selected.get("tariff") if selected else None
        amount = consumption.get("consumption_kwh") if consumption.get("status") == "ok" else None
        cost = calculate_eon_cost(amount, tariff) if agreement.get("status") == "active" else None
        return {
            "agreement": agreement,
            "facility": {
                "address": {
                    "street": installation.get("street"),
                    "city": installation.get("city"),
                    "postal_code": installation.get("postal_code"),
                },
                "price_area": installation.get("price_area"),
                "grid_area": (selected or {}).get("facility", {}).get("grid_area"),
                "fuse_ampere": (selected or {}).get("facility", {}).get("fuse_ampere"),
            },
            "tariff": tariff,
            "consumption": consumption,
            "cost": cost,
            "outage": normalize_outage(outage_payload) if outage_payload is not None else None,
            "app_authenticated": True,
            "reauth_required": False,
            "error": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

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
            sources = await self.async_fetch_app_sources()
            return {
                "provider": "eon",
                "provider_name": "E.ON",
                "auth_mode": "app",
                "contract_accounts": _redact_source_data(sources["contract_accounts"]),
                "locations": _redact_source_data(sources["locations"]),
                "grouped_contracts": _redact_source_data(sources["grouped_contracts"]),
                "monthly_transfer": _redact_source_data(sources["monthly_transfer"]),
                "outages": _redact_source_data(sources["outages"]),
                "source_status": sources["source_status"],
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
        public_facility = {
            key: facility[key]
            for key in ("address", "price_area", "grid_area", "fuse_ampere")
            if facility.get(key) is not None
        }
        return {
            "configured": self.configured,
            "provider": "eon",
            "provider_name": "E.ON",
            "auth_mode": auth_mode,
            "auth_method": auth_mode,
            "reauth_required": self.state.get("reauth_required", False),
            "agreement": self.state.get("agreement"),
            "facility": public_facility or None,
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
        self._pending_web_handoff = None
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


def _grouped_contract_installation_ids(payload: Any) -> tuple[list[str], list[str]]:
    """Collect only explicitly classified private or SME installation IDs."""
    private_ids: list[str] = []
    sme_ids: list[str] = []
    if not isinstance(payload, list):
        return private_ids, sme_ids
    for location in payload:
        if not isinstance(location, dict) or not isinstance(location.get("installations"), list):
            continue
        for installation in location["installations"]:
            if not isinstance(installation, dict):
                continue
            if installation.get("productType") != "ELECTRICITY" or installation.get("serviceType") != "GRID":
                continue
            identifier = installation.get("id")
            if not isinstance(identifier, str) or not identifier.strip():
                continue
            if installation.get("isSme") is False:
                private_ids.append(identifier)
            elif installation.get("isSme") is True:
                sme_ids.append(identifier)
    return private_ids, sme_ids
