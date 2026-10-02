"""E.ON grid manager with app-login and cookie fallback."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from copy import deepcopy
import secrets
import time
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store

from ..const import DOMAIN, EON_GRID_CONFIG_KEY, EON_GRID_PROVIDER, EON_GRID_UPDATE_EVENT, GRID_CONFIG_KEY
from ..diagnostics import sanitize_source_data
from .eon_auth import EonAppSession, EonAuthError, EonSession
from .eon_client import EonAppClient, EonClient
from .eon_models import (
    calculate_eon_cost,
    normalize_locations,
    normalize_grouped_contracts,
    normalize_outage,
    normalize_user_profile,
    normalize_user_profiles,
    facility_context,
    facility_identity,
    parse_monthly_consumption,
    parse_monthly_transfer,
    parse_provider_trend,
    parse_transfer_points,
    pricing_tariff_for_agreement,
)
from ..grid_tariff_timeline import (
    build_grid_tariff_record,
    build_user_confirmed_grid_tariff_record,
    merge_grid_tariff_record,
    resolve_grid_tariff,
)


USER_CONFIRMED_GRID_TARIFF_FACTS: tuple[dict[str, Any], ...] = (
    {
        "site_id": "76f92eea-5720-4c19-9b43-17028d19a0a4",
        "provider": "eon",
        "product_name": "16 A, upp till 8000 kWh/år. Elnätsområde Nord",
        "source_status": "MANUALLY_VERIFIED",
        "facility": {
            "installation_identifier": "40093679",
            "grid_area": "MEL",
            "price_area": "SE 2",
            "fuse_ampere": 16.0,
        },
        "agreement": {
            "status": "MANUALLY_VERIFIED",
            "source_status": "MANUALLY_VERIFIED",
            "type": "ELECTRICITY_CONS_GRID",
            "name": "16 A, upp till 8000 kWh/år. Elnätsområde Nord",
            "start_date": "2026-09-01",
            "end_date": "2026-10-01",
        },
        "grid_price": {
            "vat_included": True,
            "price_basis": "gross",
            "source": "user_confirmed",
            "fixed_monthly_sek": 226.25,
            "transfer_ore_per_kwh_gross": 97.0,
            "energy_tax_ore_per_kwh_gross": 45.0,
            "variable_grid_ore_per_kwh_gross": 142.0,
            "variable_total_ore_per_kwh_gross": 142.0,
            "contract_source_status": "MANUALLY_VERIFIED",
            "preview_applied": False,
        },
        "provenance": {
            "verification_method": "user_confirmed_manual_fact",
            "verification_scope": "exact_site_provider_product",
            "provider_api_verified": False,
        },
    },
)

EON_BACKFILL_DAYS = 7
EON_BACKFILL_RETRY_HOURS = 6


class EonGridManager:
    """Own E.ON credentials, refreshes, normalized state and update events."""

    def __init__(self, hass, entry) -> None:
        self.hass = hass
        self.entry = entry
        self.store = Store(hass, 1, f"{DOMAIN}.eon_grid_state")
        self.tariff_timeline_store = Store(hass, 1, f"{DOMAIN}.eon_grid_tariff_timeline")
        self.state: dict[str, Any] = self._empty_state()
        self.tariff_timeline: list[dict[str, Any]] = []
        self.facility_states: dict[str, dict[str, Any]] = {}
        self._refresh_unsub = None
        self._web_refresh_unsub = None
        self._pending_web_handoff: dict[str, Any] | None = None
        self._app_session: EonAppSession | None = None
        self._web_session: EonSession | None = None
        self._app_source_snapshot: dict[str, Any] | None = None
        self._active_binding: dict[str, Any] | None = None

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
        timeline = await self.tariff_timeline_store.async_load()
        if isinstance(timeline, dict) and isinstance(timeline.get("records"), list):
            self.tariff_timeline = [item for item in timeline["records"] if isinstance(item, dict)]
        if isinstance(cached, dict):
            self.state.update(cached)
            cached_facilities = cached.get("facility_states")
            if isinstance(cached_facilities, dict):
                self.facility_states = {
                    str(identity): value
                    for identity, value in cached_facilities.items()
                    if isinstance(value, dict)
                }
        if not self.configured:
            self.state = self._empty_state()
            self.facility_states = {}
            # Historical tariff facts remain usable for replay even when the
            # live provider session is currently unset or unavailable.
        await self._async_capture_tariff_fact()

    def _active_site_id(self) -> str | None:
        hass = getattr(self, "hass", None)
        site_manager = hass.data.get(DOMAIN, {}).get("site_identity_manager") if hass else None
        state = getattr(site_manager, "state", {}) if site_manager else {}
        site_id = state.get("active_site_id") if isinstance(state, dict) else None
        return site_id if isinstance(site_id, str) and site_id else None

    async def _async_capture_tariff_fact(self) -> None:
        timeline_store = getattr(self, "tariff_timeline_store", None)
        if timeline_store is None:
            return
        record = build_grid_tariff_record(
            site_id=self._active_site_id(),
            binding=getattr(self, "_active_binding", None),
            state=getattr(self, "state", None),
            captured_at=datetime.now(timezone.utc),
        )
        merged = merge_grid_tariff_record(getattr(self, "tariff_timeline", []), record)
        captured_at = datetime.now(timezone.utc)
        for fact in USER_CONFIRMED_GRID_TARIFF_FACTS:
            manual_record = build_user_confirmed_grid_tariff_record(
                site_id=self._active_site_id(),
                binding=getattr(self, "_active_binding", None),
                state=getattr(self, "state", None),
                fact=fact,
                captured_at=captured_at,
            )
            merged = merge_grid_tariff_record(merged, manual_record)
        if merged == getattr(self, "tariff_timeline", []):
            return
        self.tariff_timeline = merged
        await timeline_store.async_save({"schema": "elrakning.grid_tariff_timeline.v1", "records": merged})

    def resolve_grid_price_at(self, moment: datetime) -> dict[str, Any] | None:
        site_id = self._active_site_id()
        if not site_id:
            return None
        resolved = resolve_grid_tariff(
            getattr(self, "tariff_timeline", []),
            site_id=site_id,
            at=moment,
            decision_at=datetime.now(timezone.utc),
        )
        if not resolved:
            return None
        price = deepcopy(resolved.get("grid_price"))
        if isinstance(price, dict):
            price["_effective_dated_applicable"] = True
        return price

    def public_tariff_timeline(self) -> list[dict[str, Any]]:
        site_id = self._active_site_id()
        return [deepcopy(item) for item in getattr(self, "tariff_timeline", []) if item.get("site_id") == site_id]

    def async_start_refresh(self) -> None:
        if self._refresh_unsub is None:
            self._refresh_unsub = async_track_time_interval(
                self.hass,
                lambda _: self.hass.create_task(self.async_refresh()),
                timedelta(hours=1),
            )
        self.hass.create_task(self.async_refresh())

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
        normalized = normalize_user_profiles(profile, customer_id)
        self._web_session = session
        config = self._config_with_migration()
        config["web"] = {"cookies": session.cookies, "customer_id": customer_id}
        await self._save_config(config)
        if config.get("auth") == "app":
            return await self._refresh_app(self._app_session)
        self.facility_states = await self._build_web_states(normalized, client)
        self.state = {
            **(next(iter(self.facility_states.values()), self._empty_state())),
            "facility_states": self.facility_states,
        }
        await self.store.async_save(self.state)
        await self._async_reconcile_site_bindings()
        self.hass.bus.async_fire(EON_GRID_UPDATE_EVENT)
        return self.public_state()

    async def async_save_app_credentials(self, account_id: str, password: str) -> dict[str, Any]:
        session = EonAppSession(self.hass, self._auth_diagnostic)
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
            "day_transfer": [],
            "hourly_transfer": [],
            "quarter_hour_transfer": [],
            "backfill_transfer": [],
            "backfill_status": [],
            "trend": [],
            "outages": [],
            "source_status": {},
        }

        async def fetch(name: str, request):
            try:
                payload = await request()
            except EonAuthError as err:
                if getattr(err, "code", None) == "reauth_required":
                    raise
                sources["source_status"][name] = {"status": "failed", "error": getattr(err, "code", "api_error")}
                return None
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
        day_status = []
        hourly_status = []
        quarter_hour_status = []
        trend_status = []
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
            except EonAuthError as err:
                if getattr(err, "code", None) == "reauth_required":
                    raise
                monthly_status.append({"status": "failed", "error": getattr(err, "code", "api_error")})
            except Exception:
                monthly_status.append({"status": "failed", "error": "api_error"})
            hourly_request = getattr(client, "async_get_hourly_transfer", None)
            day_request = getattr(client, "async_get_daily_transfer", None)
            quarter_hour_request = getattr(client, "async_get_quarter_hour_transfer", None)
            trend_request = getattr(client, "async_get_trend", None)
            local_day = datetime.now(ZoneInfo("Europe/Stockholm")).date()
            local_start = datetime.combine(local_day, datetime.min.time(), tzinfo=ZoneInfo("Europe/Stockholm"))
            local_end = datetime.combine(local_day + timedelta(days=1), datetime.min.time(), tzinfo=ZoneInfo("Europe/Stockholm")) - timedelta(microseconds=1)
            if hourly_request is not None:
                try:
                    hourly = await hourly_request(
                        installation_id,
                        local_start.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                        local_end.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                        installation["production"],
                        installation["street"],
                        installation["city"],
                        installation["postal_code"],
                    )
                    sources["hourly_transfer"].append({"installation_id": installation_id, "payload": hourly})
                    hourly_status.append({"status": "ok"})
                except EonAuthError as err:
                    if getattr(err, "code", None) == "reauth_required":
                        raise
                    hourly_status.append({"status": "failed", "error": getattr(err, "code", "api_error")})
                except Exception:
                    hourly_status.append({"status": "failed", "error": "api_error"})
            if day_request is not None:
                try:
                    day = await day_request(
                        installation_id,
                        local_start.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                        local_end.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                        installation["production"],
                        installation["street"],
                        installation["city"],
                        installation["postal_code"],
                    )
                    sources["day_transfer"].append({"installation_id": installation_id, "payload": day})
                    day_status.append({"status": "ok"})
                except EonAuthError as err:
                    if getattr(err, "code", None) == "reauth_required":
                        raise
                    day_status.append({"status": "failed", "error": getattr(err, "code", "api_error")})
                except Exception:
                    day_status.append({"status": "failed", "error": "api_error"})
            if quarter_hour_request is not None:
                try:
                    quarter_hour = await quarter_hour_request(
                        installation_id,
                        local_start.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                        local_end.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                        installation["production"],
                        installation["street"],
                        installation["city"],
                        installation["postal_code"],
                    )
                    sources["quarter_hour_transfer"].append({"installation_id": installation_id, "payload": quarter_hour})
                    quarter_hour_status.append({"status": "ok"})
                except EonAuthError as err:
                    if getattr(err, "code", None) == "reauth_required":
                        raise
                    quarter_hour_status.append({"status": "failed", "error": getattr(err, "code", "api_error")})
                except Exception:
                    quarter_hour_status.append({"status": "failed", "error": "api_error"})
            if trend_request is not None:
                try:
                    captured_at = datetime.now(timezone.utc).isoformat()
                    trend = await trend_request(installation_id)
                    sources["trend"].append({
                        "installation_id": installation_id,
                        "payload": trend,
                        "captured_at": captured_at,
                        "known_at": captured_at,
                        "request": {
                            "method": "GET",
                            "path": "/energy/trend",
                            "params": {
                                "installations": f"{installation_id}:ELECTRICITY:GRID:false",
                                "includeElectricityCost": "true",
                                "language": "sv",
                            },
                        },
                    })
                    trend_status.append({"status": "ok"})
                except EonAuthError as err:
                    if getattr(err, "code", None) == "reauth_required":
                        raise
                    trend_status.append({"status": "failed", "error": getattr(err, "code", "api_error")})
                except Exception:
                    trend_status.append({"status": "failed", "error": "api_error"})
            pod = installation["point_of_delivery_number"]
            try:
                outage = await client.async_get_outages(pod)
                sources["outages"].append({"installation_id": installation_id, "payload": outage})
                outage_status.append({"status": "ok"})
            except EonAuthError as err:
                if getattr(err, "code", None) == "reauth_required":
                    raise
                outage_status.append({"status": "failed", "error": getattr(err, "code", "api_error")})
            except Exception:
                outage_status.append({"status": "failed", "error": "api_error"})
        await self._async_fetch_closed_day_backfill(client, locations, sources)
        sources["source_status"]["monthly_transfer"] = monthly_status or [{"status": "skipped"}]
        sources["source_status"]["day_transfer"] = day_status or [{"status": "skipped"}]
        sources["source_status"]["hourly_transfer"] = hourly_status or [{"status": "skipped"}]
        sources["source_status"]["quarter_hour_transfer"] = quarter_hour_status or [{"status": "skipped"}]
        sources["source_status"]["trend"] = trend_status or [{"status": "skipped"}]
        sources["source_status"]["outages"] = outage_status or [{"status": "skipped"}]
        self._app_source_snapshot = sources
        return sources

    async def _async_fetch_closed_day_backfill(
        self, client: EonAppClient, locations: list[dict[str, Any]], sources: dict[str, Any]
    ) -> None:
        """Fetch a bounded rolling window of closed local days without re-fetch spam."""
        now = datetime.now(timezone.utc)
        local_today = now.astimezone(ZoneInfo("Europe/Stockholm")).date()
        metadata = self.state.get("backfill_state") if isinstance(self.state, dict) else None
        metadata = deepcopy(metadata) if isinstance(metadata, dict) else {}
        attempts = metadata.get("attempts") if isinstance(metadata.get("attempts"), dict) else {}
        completed = metadata.get("completed") if isinstance(metadata.get("completed"), dict) else {}
        for age in range(1, EON_BACKFILL_DAYS + 1):
            target_date = local_today - timedelta(days=age)
            target_date_key = target_date.isoformat()
            day_start = datetime.combine(target_date, datetime.min.time(), tzinfo=ZoneInfo("Europe/Stockholm"))
            day_end = datetime.combine(target_date + timedelta(days=1), datetime.min.time(), tzinfo=ZoneInfo("Europe/Stockholm")) - timedelta(microseconds=1)
            for installation in locations:
                installation_id = installation["installation_identifier"]
                date_key = f"{installation_id}|{target_date.isoformat()}"
                previous = attempts.get(date_key) if isinstance(attempts.get(date_key), dict) else {}
                if completed.get(date_key) is True:
                    continue
                last_attempt = previous.get("at")
                if last_attempt:
                    try:
                        if now - datetime.fromisoformat(str(last_attempt).replace("Z", "+00:00")) < timedelta(hours=EON_BACKFILL_RETRY_HOURS):
                            continue
                    except ValueError:
                        pass
                installation_actual = False
                installation_attempted = False
                preferred_actual = False
                for aggregation in ("QUARTER_HOUR", "HOUR", "DAY"):
                    try:
                        payload = await client.async_get_transfer(
                            aggregation,
                            installation_id,
                            day_start.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                            day_end.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                            installation["production"],
                            installation["street"],
                            installation["city"],
                            installation["postal_code"],
                        )
                    except EonAuthError as err:
                        if getattr(err, "code", None) == "reauth_required":
                            raise
                        sources["backfill_status"].append({"date": target_date_key, "installation_id": installation_id, "resolution": aggregation, "status": "failed", "error": getattr(err, "code", "api_error")})
                        continue
                    except Exception:
                        sources["backfill_status"].append({"date": target_date_key, "installation_id": installation_id, "resolution": aggregation, "status": "failed", "error": "api_error"})
                        continue
                    captured_at = datetime.now(timezone.utc).isoformat()
                    parsed = parse_transfer_points(payload, aggregation, target_date)
                    actual_count = int(parsed.get("actual_count") or 0)
                    padded_count = int(parsed.get("padded_count") or 0)
                    installation_attempted = True
                    installation_actual = installation_actual or actual_count > 0
                    if aggregation == "QUARTER_HOUR" and actual_count > 0:
                        preferred_actual = True
                    sources["backfill_transfer"].append({
                        "installation_id": installation_id,
                        "date": target_date_key,
                        "resolution": aggregation,
                        "payload": payload,
                        "captured_at": captured_at,
                        "known_at": captured_at,
                    })
                    sources["backfill_status"].append({
                        "date": target_date_key,
                        "installation_id": installation_id,
                        "resolution": aggregation,
                        "status": parsed.get("status"),
                        "actual_count": actual_count,
                        "padded_count": padded_count,
                    })
                if installation_attempted:
                    attempts[date_key] = {"at": now.isoformat(), "actual": installation_actual, "preferred_actual": preferred_actual}
                    if preferred_actual:
                        completed[date_key] = True
        sources["backfill_state"] = {"attempts": attempts, "completed": completed, "horizon_days": EON_BACKFILL_DAYS}

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
            normalized = normalize_user_profiles(profile, customer_id)
            states = await self._build_web_states(normalized, client)
            self.facility_states = states
            state = next(iter(states.values()), self._empty_state())
            self.state = {**state, "facility_states": states}
            await self.store.async_save(self.state)
            await self._async_persist_provider_imports(states)
            await self._async_capture_tariff_fact()
            await self._async_reconcile_site_bindings()
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
            states = self._build_app_states(sources, locations)
            self.facility_states = states
            state = self._state_for_active_binding(states) or self._build_app_state(sources, locations)
            self.state = {**state, "facility_states": states}
            await self.store.async_save(self.state)
            await self._async_capture_tariff_fact()
            await self._async_reconcile_site_bindings()
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
        states = self._build_app_states(sources, locations)
        ordered = [facility_identity(item) for item in locations]
        selected = next(
            (
                states[identity]
                for identity in ordered
                if identity in states and states[identity].get("agreement", {}).get("status") == "active"
            ),
            next(
                (
                    states[identity]
                    for identity in ordered
                    if identity in states and states[identity].get("agreement", {}).get("status") == "future"
                ),
                next(iter(states.values()), self._empty_state()),
            ),
        )
        return deepcopy(selected)

    def _build_app_states(
        self, sources: dict[str, Any], locations: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Build one independent normalized state for every native facility."""
        now = date.today()
        installation_ids = {item["installation_identifier"] for item in locations}
        contracts = normalize_grouped_contracts(sources.get("grouped_contracts"), installation_ids)
        by_installation: dict[str, list[dict[str, Any]]] = {}
        for contract in contracts:
            by_installation.setdefault(contract["installation_identifier"], []).append(contract)
        states = {}
        for installation in locations:
            installation_id = installation["installation_identifier"]
            candidates = by_installation.get(installation_id, [])
            current = next((item for item in candidates if item["agreement"]["status"] == "active"), None)
            selected = current or next((item for item in candidates if item["agreement"]["status"] == "future"), None)
            monthly = next((item["payload"] for item in sources.get("monthly_transfer", []) if item.get("installation_id") == installation_id), None)
            day = next((item["payload"] for item in sources.get("day_transfer", []) if item.get("installation_id") == installation_id), None)
            hourly = next((item["payload"] for item in sources.get("hourly_transfer", []) if item.get("installation_id") == installation_id), None)
            quarter_hour = next((item["payload"] for item in sources.get("quarter_hour_transfer", []) if item.get("installation_id") == installation_id), None)
            backfill_transfer = [
                item for item in sources.get("backfill_transfer", [])
                if item.get("installation_id") == installation_id
            ]
            trend = next((item for item in sources.get("trend", []) if item.get("installation_id") == installation_id), None)
            outage_payload = next((item["payload"] for item in sources.get("outages", []) if item.get("installation_id") == installation_id), None)
            consumption = parse_monthly_transfer(monthly, now.year, now.month) if monthly is not None else {"status": "missing", "resolution": "Monthly"}
            local_day = datetime.now(ZoneInfo("Europe/Stockholm")).date()
            day_consumption = parse_transfer_points(day, "DAY", local_day) if day is not None else {"status": "missing", "resolution": "DAY", "date": local_day.isoformat(), "reason": "not_fetched"}
            hourly_consumption = parse_transfer_points(hourly, "HOUR", local_day) if hourly is not None else {"status": "missing", "resolution": "HOUR", "date": local_day.isoformat(), "reason": "not_fetched"}
            quarter_hour_consumption = parse_transfer_points(quarter_hour, "QUARTER_HOUR", local_day) if quarter_hour is not None else {"status": "missing", "resolution": "QUARTER_HOUR", "date": local_day.isoformat(), "reason": "not_fetched"}
            provider_trend = parse_provider_trend(
                trend.get("payload") if trend else None,
                trend.get("captured_at") if trend else None,
                trend.get("known_at") if trend else None,
                installation_id,
                trend.get("request") if trend else None,
            )
            agreement = selected["agreement"] if selected else {
                "status": "future" if installation.get("is_future") is True else "configured",
                "type": "ELECTRICITY_CONS_GRID",
            }
            tariff = selected.get("tariff") if selected else None
            pricing_tariff = pricing_tariff_for_agreement(tariff, agreement.get("status"))
            amount = consumption.get("consumption_kwh") if consumption.get("status") == "ok" else None
            cost = calculate_eon_cost(amount, pricing_tariff)
            facility = {
                "installation_identifier": installation.get("installation_identifier"),
                "point_of_delivery_number": installation.get("point_of_delivery_number"),
                "address": {
                    "street": installation.get("street"),
                    "city": installation.get("city"),
                    "postal_code": installation.get("postal_code"),
                },
                "price_area": installation.get("price_area"),
                "grid_area": (selected or {}).get("facility", {}).get("grid_area"),
                "fuse_ampere": (selected or {}).get("facility", {}).get("fuse_ampere"),
            }
            identity = facility_identity(facility)
            if not identity:
                continue
            states[identity] = {
            "agreement": agreement,
            "facility": facility,
            "contract_identity": (selected or {}).get("contract_identity"),
            "tariff": tariff,
            "grid_price": (pricing_tariff or {}).get("grid_price"),
            "consumption": consumption,
            "day_consumption": day_consumption,
            "hourly_consumption": hourly_consumption,
            "quarter_hour_consumption": quarter_hour_consumption,
            "backfill_transfer": [
                {
                    "date": item.get("date"),
                    "resolution": item.get("resolution"),
                    "parsed": parse_transfer_points(item.get("payload"), item.get("resolution"), date.fromisoformat(item["date"])),
                    "captured_at": item.get("captured_at"),
                    "known_at": item.get("known_at"),
                }
                for item in backfill_transfer
                if isinstance(item.get("date"), str)
            ],
            "backfill_state": sources.get("backfill_state") or {},
            "provider_trend": provider_trend,
            "cost": cost,
            "outage": normalize_outage(outage_payload) if outage_payload is not None else None,
            "app_authenticated": True,
            "reauth_required": False,
            "error": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        return states

    async def _async_persist_provider_imports(self, states: dict[str, dict[str, Any]]) -> None:
        """Persist only verified E.ON import buckets for explicitly bound sites."""
        domain_data = self.hass.data.get(DOMAIN, {})
        collector = domain_data.get("canonical_collector")
        site_manager = domain_data.get("site_identity_manager")
        storage = getattr(collector, "storage", None)
        site_state = getattr(site_manager, "state", {}) if site_manager else {}
        configs = site_state.get("site_configs", {}) if isinstance(site_state, dict) else {}
        if storage is None or not isinstance(configs, dict):
            return
        captured_at = datetime.now(timezone.utc)
        for site_id, config in configs.items():
            if not isinstance(config, dict) or config.get("collection_enabled") is not True:
                continue
            binding = (config.get("bindings") or {}).get("grid")
            if not isinstance(binding, dict) or binding.get("provider") != "eon":
                continue
            if binding.get("config_entry_id") != getattr(self.entry, "entry_id", None):
                continue
            facility = binding.get("facility")
            if not isinstance(facility, dict):
                continue
            identity = facility_identity(facility)
            state = states.get(identity) if identity else None
            if not isinstance(state, dict):
                continue
            installation_id = (state.get("facility") or {}).get("installation_identifier")
            if not installation_id:
                continue
            batches = self._provider_import_batches(state)
            if not batches:
                continue
            for resolution, points in batches:
                generation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"eon:grid.energy_import:{site_id}:{installation_id}:{resolution}"))
                first_start = points[0]["start"]
                storage.ensure_source_generation({
                    "generation_id": generation_id,
                    "site_id": str(site_id),
                    "logical_role": "grid.energy_import",
                    "source_identity": {
                        "identity_key": f"eon:{installation_id}:electricity:grid:false",
                        "identity_strength": "strong",
                        "identity_provenance": "eon_provider_installation_binding",
                    },
                    "source_resolution_kind": "native_bucket",
                    "source_resolution_seconds": resolution,
                    "timezone_state": "verified",
                    "effective_from": first_start.isoformat(),
                }, captured_at)
                observations = []
                for item in points:
                    start = item["start"]
                    end = item["end"]
                    row_captured_at = item.get("captured_at") or captured_at
                    row_known_at = item.get("known_at") or row_captured_at
                    semantic_key = f"{site_id}|grid.energy_import|{generation_id}|{start.isoformat()}"
                    observations.append({
                        "record_id": str(uuid.uuid5(uuid.NAMESPACE_URL, semantic_key)),
                        "semantic_key": semantic_key,
                        "site_id": str(site_id),
                        "logical_role": "grid.energy_import",
                        "source_generation_id": generation_id,
                        "interval_start": start,
                        "interval_end": end,
                        "resolution_seconds": resolution,
                        "source_resolution_kind": "native_bucket",
                        "source_resolution_seconds": resolution,
                        "observed_at": start,
                        "captured_at": row_captured_at,
                        "fetched_at": row_captured_at,
                        "known_at": row_known_at,
                        "classification": "measured",
                        "value": item["value"],
                        "unit": "kWh",
                        "sign_convention": "positive_import_energy",
                        "quality_status": "good",
                        "coverage_ratio": 1.0,
                        "gap_status": "none",
                        "quality": {"padded": False, "provider_actual": True},
                        "provenance": {
                            "provider": "eon",
                            "dataset": "energy_transfer",
                            "installation_identifier": installation_id,
                            "point_of_delivery_number": (state.get("facility") or {}).get("point_of_delivery_number"),
                            "resolution": resolution,
                            "site_binding_fingerprint": binding.get("binding_fingerprint"),
                        },
                    })
                storage.insert_historical_observations_atomic(observations)
                storage.reconcile_grid_import(str(site_id), first_start, points[-1]["end"])

    @staticmethod
    def _provider_import_points(state: dict[str, Any]) -> tuple[int, list[dict[str, Any]]] | None:
        """Select one actual provider resolution without disaggregating coarser data."""
        for key, seconds in (("quarter_hour_consumption", 900), ("hourly_consumption", 3600), ("day_consumption", 86400)):
            parsed = state.get(key)
            if isinstance(parsed, dict) and parsed.get("status") == "ok" and parsed.get("actual_points"):
                points = []
                for point in parsed["actual_points"]:
                    try:
                        start = datetime.fromisoformat(str(point["timestamp"]).replace("Z", "+00:00"))
                        value = float(point["consumption_kwh"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if start.tzinfo is None or value < 0 or point.get("padded") is True:
                        continue
                    points.append({"start": start.astimezone(timezone.utc), "end": start.astimezone(timezone.utc) + timedelta(seconds=seconds), "value": value})
                if points:
                    return seconds, sorted(points, key=lambda item: item["start"])
        consumption = state.get("consumption")
        if isinstance(consumption, dict) and consumption.get("status") == "ok":
            try:
                start = datetime(int(consumption["year"]), int(consumption["month"]), 1, tzinfo=timezone.utc)
                end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
                return int((end - start).total_seconds()), [{"start": start, "end": end, "value": float(consumption["consumption_kwh"])}]
            except (KeyError, TypeError, ValueError):
                return None
        return None

    @classmethod
    def _provider_import_batches(cls, state: dict[str, Any]) -> list[tuple[int, list[dict[str, Any]]]]:
        """Return actual backfill batches plus the current-state batch without overlap."""
        batches: list[tuple[int, list[dict[str, Any]]]] = []
        seen_dates: set[str] = set()
        resolution_seconds = {"QUARTER_HOUR": 900, "HOUR": 3600, "DAY": 86400}
        entries = state.get("backfill_transfer") if isinstance(state.get("backfill_transfer"), list) else []
        rank = {"QUARTER_HOUR": 0, "HOUR": 1, "DAY": 2}
        for entry in sorted(entries, key=lambda item: (str(item.get("date") or ""), rank.get(str(item.get("resolution") or "").upper(), 99))):
            parsed = entry.get("parsed") if isinstance(entry, dict) else None
            date_value = entry.get("date") if isinstance(entry, dict) else None
            resolution = str(entry.get("resolution") or "").upper() if isinstance(entry, dict) else ""
            if not isinstance(parsed, dict) or parsed.get("status") != "ok" or not isinstance(date_value, str) or resolution not in resolution_seconds or date_value in seen_dates:
                continue
            points = []
            for point in parsed.get("actual_points") or []:
                try:
                    start = datetime.fromisoformat(str(point["timestamp"]).replace("Z", "+00:00"))
                    value = float(point["consumption_kwh"])
                except (KeyError, TypeError, ValueError):
                    continue
                if start.tzinfo is None or value < 0 or point.get("padded") is True:
                    continue
                points.append({
                    "start": start.astimezone(timezone.utc),
                    "end": start.astimezone(timezone.utc) + timedelta(seconds=resolution_seconds[resolution]),
                    "value": value,
                    "captured_at": entry.get("captured_at"),
                    "known_at": entry.get("known_at"),
                })
            if points:
                batches.append((resolution_seconds[resolution], sorted(points, key=lambda item: item["start"])))
                seen_dates.add(date_value)
        current = cls._provider_import_points(state)
        if current:
            batches.append(current)
        return batches

    def _state_for_active_binding(self, states: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        binding = getattr(self, "_active_binding", None)
        if not isinstance(binding, dict):
            return None
        identity = facility_identity(binding.get("facility"))
        return deepcopy(states.get(identity)) if identity else None

    async def _async_reconcile_site_bindings(self) -> None:
        site_manager = self.hass.data.get(DOMAIN, {}).get("site_identity_manager")
        reconcile = getattr(site_manager, "async_reconcile_grid_bindings", None)
        if reconcile:
            await reconcile(self.hass.data.get(DOMAIN, {}).get("grid_manager"))

    def set_active_binding(self, binding: dict[str, Any] | None) -> None:
        """Track presentation context without changing shared account sources."""
        self._active_binding = deepcopy(binding) if isinstance(binding, dict) else None

    def state_for_facility(self, identity: str | None) -> dict[str, Any] | None:
        """Return only the state explicitly indexed by one native facility identity."""
        if not isinstance(identity, str) or not identity:
            return None
        state = getattr(self, "facility_states", {}).get(identity)
        return deepcopy(state) if isinstance(state, dict) else None

    def resolve_binding(self, binding: dict[str, Any] | None) -> dict[str, Any]:
        """Resolve a binding by native identity or deterministic legacy context."""
        if not isinstance(binding, dict):
            return {"status": "unresolved", "state": None}
        identity = facility_identity(binding.get("facility"))
        if identity and identity in getattr(self, "facility_states", {}):
            return {"status": "strong", "identity": identity, "state": self.state_for_facility(identity)}
        expected = facility_context(binding.get("facility"))
        if expected is None:
            return {"status": "unresolved", "state": None}
        matches = [
            (candidate_identity, state)
            for candidate_identity, state in getattr(self, "facility_states", {}).items()
            if facility_context(state.get("facility")) == expected
        ]
        if len(matches) != 1:
            return {"status": "ambiguous" if len(matches) > 1 else "unresolved", "state": None}
        candidate_identity, state = matches[0]
        return {"status": "legacy_unique", "identity": candidate_identity, "state": deepcopy(state)}

    def binding_reconciliation(self, binding: dict[str, Any] | None) -> dict[str, Any]:
        """Return a binding enriched only after unique native-facility reconciliation."""
        resolved = self.resolve_binding(binding)
        if resolved.get("status") != "legacy_unique" or not isinstance(binding, dict):
            return {**resolved, "binding": deepcopy(binding) if isinstance(binding, dict) else None}
        state = resolved.get("state")
        facility = state.get("facility") if isinstance(state, dict) else None
        enriched = deepcopy(binding)
        if isinstance(facility, dict):
            enriched["facility"] = {**deepcopy(enriched.get("facility") or {}), **deepcopy(facility)}
            enriched["identity_provenance"] = "legacy_context_reconciled_unique"
            enriched["identity_strength"] = "strong"
        return {**resolved, "binding": enriched}

    def state_for_binding(self, binding: dict[str, Any] | None) -> dict[str, Any] | None:
        """Resolve a site binding without consulting the global selected state."""
        return self.resolve_binding(binding).get("state")

    def public_state_for_binding(self, binding: dict[str, Any] | None) -> dict[str, Any]:
        resolved = self.resolve_binding(binding)
        if not isinstance(resolved.get("state"), dict):
            public = self.public_state()
            if isinstance(binding, dict) and binding.get("provider") == EON_GRID_PROVIDER:
                cached = {
                    key: deepcopy(binding.get(key))
                    for key in ("facility", "tariff", "grid_price", "agreement")
                    if isinstance(binding.get(key), dict)
                }
                public = {**public, **cached, "configured": True}
            else:
                public["facility"] = None
            return {**public, "site_status": resolved["status"]}
        previous = self.state
        try:
            self.state = resolved["state"]
            return {**self.public_state(), "site_status": resolved["status"]}
        finally:
            self.state = previous

    async def _get_app_session(
        self, config: dict[str, Any], session: EonAppSession | None = None
    ) -> EonAppSession:
        """Return the cached app session, logging in only when it is absent or expired."""
        session = session or self._app_session or EonAppSession(self.hass, self._auth_diagnostic)
        if not session.is_valid:
            await session.async_login(config["account_id"], config["password"])
        self._app_session = session
        return session

    async def _auth_diagnostic(self, level: str, event: str, message: str) -> None:
        """Forward bounded E.ON auth diagnostics through the existing store."""
        manager = self.hass.data.get(DOMAIN, {}).get("elhandel_manager")
        if manager is not None:
            await manager.async_diagnostic(level, "eon_auth", event, message)

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
        self.facility_states = {}
        await self.store.async_save(self.state)
        self.hass.bus.async_fire(EON_GRID_UPDATE_EVENT)
        return self.public_state()

    async def async_source_data(self) -> dict[str, Any]:
        """Fetch the active E.ON source payload only after an explicit request."""
        config = self._config()
        if config.get("auth") == "app":
            sources = await self.async_fetch_app_sources()
            meter_source = {}
            meter_manager = self.hass.data.get(DOMAIN, {}).get("meter_manager")
            if meter_manager is not None and hasattr(meter_manager, "async_source"):
                meter_source = await meter_manager.async_source()
            return _build_app_source_data(self.state, sources, meter_source)

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
            "grid_price": self.state.get("grid_price"),
            "tariff_timeline": self.public_tariff_timeline(),
            "consumption": self.state.get("consumption"),
            "day_consumption": self.state.get("day_consumption"),
            "hourly_consumption": self.state.get("hourly_consumption"),
            "quarter_hour_consumption": self.state.get("quarter_hour_consumption"),
            "provider_trend": self.state.get("provider_trend"),
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
                "installation_identifier": facility.get("installation_identifier"),
                "point_of_delivery_number": facility.get("point_of_delivery_number"),
                "price_area": facility.get("price_area"),
                "fuse_ampere": facility.get("fuse_ampere"),
            },
            "tariff": normalized.get("tariff"),
            "grid_price": None,
            "consumption": consumption,
            "cost": calculate_eon_cost(amount, normalized.get("tariff")),
            "error": None,
            "reauth_required": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _build_web_states(
        self, normalized: list[dict[str, Any]], client: EonClient
    ) -> dict[str, dict[str, Any]]:
        """Build independent web states for every normalized native facility."""
        states: dict[str, dict[str, Any]] = {}
        for contract in normalized:
            state = await self._build_state(contract, client)
            identity = facility_identity(state.get("facility"))
            if identity:
                state["contract_identity"] = contract.get("contract_identity")
                states[identity] = state
        return states

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
            self.hass.create_task(self.async_refresh())

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
            "grid_price": None,
            "consumption": None,
            "day_consumption": None,
            "hourly_consumption": None,
            "quarter_hour_consumption": None,
            "provider_trend": None,
            "backfill_transfer": [],
            "backfill_state": {"attempts": {}, "completed": {}, "horizon_days": EON_BACKFILL_DAYS},
            "cost": None,
            "reauth_required": False,
            "error": None,
            "outage": None,
            "app_authenticated": False,
            "facility_states": {},
        }


def _redact_source_data(value: Any) -> Any:
    """Redact authentication secrets while preserving provider source semantics."""
    return sanitize_source_data(value)


def _build_app_source_data(
    state: dict[str, Any], sources: dict[str, Any], meter_source: dict[str, Any]
) -> dict[str, Any]:
    """Combine provider responses with the canonical values rendered by the cards."""
    agreement = state.get("agreement") or {}
    facility = state.get("facility") or {}
    tariff = state.get("tariff") or {}
    cost = state.get("cost") or {}
    consumption = state.get("consumption") or {}
    meter_state = meter_source.get("state") if isinstance(meter_source, dict) else {}
    meter_history = meter_source.get("history") if isinstance(meter_source, dict) else {}
    meter_state = meter_state if isinstance(meter_state, dict) else {}
    meter_history = meter_history if isinstance(meter_history, dict) else {}
    daily_max_phase = meter_history.get("daily_max_phase")
    daily_phase_max = meter_history.get("daily_phase_max")
    daily_max_phase = daily_max_phase if isinstance(daily_max_phase, dict) else None
    daily_phase_max = daily_phase_max if isinstance(daily_phase_max, dict) else None
    fuse = facility.get("fuse_ampere")
    max_ampere = daily_max_phase.get("ampere") if daily_max_phase else None
    utilization = (
        float(max_ampere) / float(fuse) * 100
        if _is_number(max_ampere) and _is_number(fuse) and float(fuse) > 0
        else None
    )
    grid_price = tariff.get("grid_price") if isinstance(tariff, dict) else None
    trend = state.get("provider_trend") if isinstance(state.get("provider_trend"), dict) else {}
    source_status = sources.get("source_status") or {}
    return _redact_source_data({
        "provider": "eon",
        "provider_name": "E.ON",
        "auth_mode": "app",
        "card": "grid-provider",
        "contract_accounts": sources.get("contract_accounts"),
        "locations": sources.get("locations"),
        "grouped_contracts": sources.get("grouped_contracts"),
        "monthly_transfer": sources.get("monthly_transfer"),
        "day_transfer": sources.get("day_transfer"),
        "hourly_transfer": sources.get("hourly_transfer"),
        "quarter_hour_transfer": sources.get("quarter_hour_transfer"),
        "trend": sources.get("trend"),
        "outages": sources.get("outages"),
        "source_status": source_status,
        "normalized": {
            "provider": "E.ON",
            "contract_name": agreement.get("name") or agreement.get("description"),
            "contract_start": agreement.get("start_date"),
            "address": facility.get("address"),
            "fuse_ampere": fuse,
            "price_area": facility.get("price_area"),
            "grid_area": facility.get("grid_area"),
            "subscription_sek_per_month": tariff.get("subscription_fee_sek_per_month"),
            "transfer_ore_per_kwh": tariff.get("transfer_fee_ore_per_kwh"),
            "energy_tax_ore_per_kwh": tariff.get("energy_tax_ore_per_kwh"),
            "yearly_cost_sek": tariff.get("estimated_yearly_cost_sek"),
        },
        "phase_metrics": {
            "daily_phase_max": daily_phase_max,
            "daily_max_phase": (
                {**daily_max_phase, "fuse_ampere": fuse, "utilization_percent": utilization}
                if daily_max_phase else None
            ),
            "fuse_utilization_percent": utilization,
            "source_entities": meter_state.get("phase_source_entities"),
            "discovery_method": meter_history.get("phase_discovery_method"),
        },
        "current_month_cost": {
            "total_sek": cost.get("total_sek"),
            "fixed_sek": cost.get("subscription_fee_sek"),
            "variable_sek": (
                cost.get("transfer_cost_sek", 0) + cost.get("energy_tax_sek", 0)
                if _number_pair(cost.get("transfer_cost_sek"), cost.get("energy_tax_sek"))
                else None
            ),
            "imported_kwh": consumption.get("consumption_kwh") if consumption.get("status") == "ok" else None,
            "subscription_sek_per_month": tariff.get("subscription_fee_sek_per_month"),
            "transfer_ore_per_kwh": tariff.get("transfer_fee_ore_per_kwh"),
            "energy_tax_ore_per_kwh": tariff.get("energy_tax_ore_per_kwh"),
            "variable_grid_ore_per_kwh": grid_price.get("variable_total_ore_per_kwh_gross") if isinstance(grid_price, dict) else None,
            "source": "canonical_eon_grid_cost",
        },
        "provider_monthly_estimate": {
            "consumption_kwh": trend.get("estimated_month_consumption_kwh"),
            "status": "ok" if trend.get("estimated_month_consumption_kwh") is not None else "unavailable",
            "reason": trend.get("estimate_unavailable_reason"),
            "provenance": trend.get("estimate_provenance"),
            "cost_status": "unavailable_future_price_not_resolved",
        },
        "provider_monthly_transfer": _monthly_transfer_provenance(
            sources.get("monthly_transfer"), consumption
        ),
        "outage": state.get("outage"),
        "provenance": {
            "contract_tariff": "E.ON grouped_contracts",
            "address_area_fuse": "E.ON Locations plus canonical contract state",
            "phase_max": "Home Assistant meter phase history",
            "current_month_cost": "canonical E.ON grid cost state",
            "outage": "E.ON OutagesV2",
        },
    })


def _monthly_transfer_provenance(value: Any, consumption: dict[str, Any]) -> dict[str, Any]:
    """Expose provider padding without replacing the raw response."""
    for item in value if isinstance(value, list) else []:
        payload = item.get("payload") if isinstance(item, dict) else None
        if not isinstance(payload, dict) or not isinstance(payload.get("transfer"), list):
            continue
        for transfer in payload["transfer"]:
            provider_consumption = transfer.get("consumption") if isinstance(transfer, dict) else None
            if isinstance(provider_consumption, dict):
                return {
                    "value": provider_consumption.get("total"),
                    "padded": provider_consumption.get("padded"),
                    "usable_as_actual_consumption": consumption.get("status") == "ok",
                }
    return {"value": None, "padded": None, "usable_as_actual_consumption": consumption.get("status") == "ok"}


def _number_pair(left: Any, right: Any) -> bool:
    return _is_number(left) and _is_number(right)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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
