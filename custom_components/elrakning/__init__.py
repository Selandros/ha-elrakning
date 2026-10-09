"""The Elräkning integration."""

import asyncio
import concurrent.futures
import inspect
import json
import logging
import threading
import time
from functools import partial
from datetime import timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .cadence_audit import CadenceAuditManager, async_register_cadence_audit_websocket
from .app_client import AppShadowClient
from .canonical_collector import CanonicalCollector
from .const import DOMAIN, EON_GRID_UPDATE_EVENT, ELECTRICITY_PROVIDER_UPDATE_EVENT, INTEGRATION_READY_EVENT, SOLAR_WEATHER_UPDATE_EVENT
from .coordinator import ElrakningCoordinator
from .elhandel.manager import ElhandelManager
from .elnat.manager import GridManager
from .elnat.eon_handoff import async_register_eon_handoff_views
from .meter import MeterManager
from .power import PowerManager
from .solar_forecast import SolarForecastManager
from .solar_open_meteo import SolarOpenMeteoManager
from .solar_pvgis import SolarPvgisManager
from .solar_shadow import SolarShadowManager
from .solar_evidence import SolarEvidenceManager
from .solar_weather import SolarWeatherManager
from .load_forecast import build_site_load_forecast
from .ella_load_registry import EllaLoadRegistry
from .ella_debug_snapshot import EllaDebugSnapshotStore
from .ella_learning import EllaLearningStore
from .monthly_forecast_manager import MonthlyForecastManager
from .ella_stage6 import EllaStage6CalibrationStore
from .ella_execution import EllaExecutionStore
from .ella_ess_facts import EllaEssFactsStore
from .ella_economic_policy import EllaEconomicPolicyStore
from .replay_artifact_store import ReplayArtifactStore, async_register_replay_artifact_service
from .replay_runtime import async_generate_artifact
from .runtime_diagnostics import async_event_loop_lag_heartbeat, runtime_checkpoint
from .site_economic_frames import schedule_eon_grid_economic_capture
from .grid_tariff_timeline import resolve_grid_tariff
from .site_identity import SiteIdentityManager
from .energy_history import _power_to_kw
from .websocket import async_register_websocket_commands, clear_forecast_view_caches
from .elhandel.providers.greenely_invoice_economics import GreenelyInvoiceEconomicsProducer, async_register_proof_service

PANEL_PATH = DOMAIN
PANEL_LOADER_PATH = f"/{DOMAIN}/elrakning-loader.js"
PANEL_LOADER_VERSION = json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))["version"]
PANEL_LOADER_URL = f"{PANEL_LOADER_PATH}?v={PANEL_LOADER_VERSION}"
PANEL_RESOURCE_PATH = f"/{DOMAIN}/elrakning-panel.js"
PANEL_CADENCE_AUDIT_PATH = f"/{DOMAIN}/elrakning-cadence-audit.js"
PANEL_MANIFEST_PATH = f"/{DOMAIN}/manifest.json"
REPLAY_RUN_TIMEOUT_SECONDS = 20 * 60
_LOGGER = logging.getLogger(__name__)

runtime_checkpoint(
    "module_imports.complete",
    phase="import",
    highspy_loaded=False,
    highspy_diagnostic_mode=True,
)


async def _run_replay_with_timeout(coroutine, timeout_seconds=REPLAY_RUN_TIMEOUT_SECONDS):
    """Bound one replay task so worker stalls cannot hold the scheduler forever."""
    return await asyncio.wait_for(coroutine, timeout=timeout_seconds)


async def _await_setup_step(label: str, awaitable):
    """Await one setup phase while recording bounded timing metadata."""
    started_at = runtime_checkpoint(f"{label}.start")
    try:
        result = await awaitable
    except BaseException as error:
        runtime_checkpoint(
            f"{label}.error",
            started_at=started_at,
            level=logging.ERROR,
            error_type=type(error).__name__,
        )
        raise
    runtime_checkpoint(f"{label}.complete", started_at=started_at)
    return result


async def _async_cancel_task(task) -> None:
    """Cancel and await one task without leaking its exception."""
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def _start_event_loop_lag_heartbeat(hass):
    """Start one low-overhead heartbeat for the integration lifecycle."""
    data = hass.data.setdefault(DOMAIN, {})
    existing = data.get("event_loop_lag_heartbeat_task")
    if existing is not None and not existing.done():
        return existing
    coroutine = async_event_loop_lag_heartbeat()
    create_task = getattr(hass, "async_create_background_task", None)
    task = (
        create_task(coroutine, name="elrakning_event_loop_lag_heartbeat")
        if callable(create_task)
        else hass.async_create_task(coroutine)
    )
    data["event_loop_lag_heartbeat_task"] = task
    return task


class _ReplaySiteTaskRegistry:
    """Keep timed-out site work single-flight until its executor task really ends."""

    def __init__(self, create_task=None):
        self._tasks = {}
        self._closed = False
        self._create_task = create_task or asyncio.create_task

    def _consume_task_exception(self, task):
        if not task.done() or task.cancelled():
            return
        try:
            task.exception()
        except BaseException:
            pass

    def _cleanup(self, task):
        for site_id, current in tuple(self._tasks.items()):
            if current is task:
                self._tasks.pop(site_id, None)

    async def run(self, site_id, coroutine_factory, timeout_seconds, task_name):
        existing = self._tasks.get(site_id)
        if existing is not None and not existing.done():
            return {"accepted": False, "site_id": site_id, "reason": "site_replay_active"}
        if self._closed:
            return {"accepted": False, "site_id": site_id, "reason": "replay_scheduler_closed"}
        task = self._create_task(coroutine_factory(), name=task_name)
        self._tasks[site_id] = task
        task.add_done_callback(self._cleanup)
        task.add_done_callback(self._consume_task_exception)
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return {
                "accepted": False,
                "site_id": site_id,
                "reason": "replay_timeout",
                "task_active": not task.done(),
            }
        finally:
            if task.done():
                self._cleanup(task)

    async def async_close(self):
        self._closed = True
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


def _replay_trigger_identity(event) -> str:
    """Return a stable identity for one source event without using wall-clock time."""
    data = getattr(event, "data", None)
    if not isinstance(data, dict):
        data = {}
    stable_fields = {
        key: data[key]
        for key in (
            "site_id",
            "frame_id",
            "forecast_id",
            "model_version",
            "source_generation_id",
            "generation_id",
            "known_at",
            "decision_at",
            "request_id",
        )
        if key in data
    }
    if not stable_fields:
        stable_fields = data
    return json.dumps(
        {
            "event_type": getattr(event, "event_type", None) or "unknown",
            "data": stable_fields,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _schedule_price_update(hass: HomeAssistant) -> None:
    """Schedule the existing price update event on Home Assistant's loop."""
    hass.loop.call_soon_threadsafe(hass.bus.async_fire, "elrakning_price_update")


def _schedule_eon_grid_update(hass: HomeAssistant) -> None:
    """Keep the existing price refresh and snapshot verified site economics."""
    _schedule_price_update(hass)
    schedule_eon_grid_economic_capture(hass)


async def _async_midnight_refresh(coordinator: ElrakningCoordinator, _now) -> None:
    """Refresh the coordinator once at the local start of each day."""
    await coordinator.async_request_refresh()
    coordinator.async_schedule_midnight_recovery()


async def _async_capture_load_forecasts(hass, site_identity_manager, canonical_collector) -> None:
    """Persist truthful load-profile forecasts for every eligible site."""
    stage6_store = getattr(hass, "data", {}).get("elrakning", {}).get("ella_stage6_store")
    configs = site_identity_manager.collection_site_configs()
    target_getter = getattr(site_identity_manager, "collection_targets", None)
    targets = target_getter() if callable(target_getter) else []
    site_ids = {target["site_id"] for target in targets
                if isinstance(target, dict) and target.get("logical_role") == "house.consumption"}
    now = dt_util.now().astimezone(timezone.utc)
    for site_id in sorted(site_ids):
        config = configs.get(site_id, {}) if isinstance(configs, dict) else {}
        location = config.get("location", {}) if isinstance(config, dict) else {}
        timezone_name = location.get("timezone") if isinstance(location, dict) else None
        if not isinstance(timezone_name, str) or not timezone_name:
            continue
        try:
            domain = globals().get("DOMAIN", "elrakning")
            learning_store = getattr(hass, "data", {}).get(domain, {}).get("ella_learning_store")
            persistent_calibration = (
                learning_store.persistent_calibration(site_id, timezone_name, now)
                if learning_store else None
            )
            global_prior_calibration = (
                learning_store.global_calibration_prior(now)
                if learning_store else None
            )
            result = await hass.async_add_executor_job(
                build_site_load_forecast, canonical_collector.storage, site_id, timezone_name, now,
                persistent_calibration, global_prior_calibration,
            )
            if learning_store is not None:
                await learning_store.async_record(
                    site_id, result.get("evaluation") or {}, result.get("calibration") or {}, timezone_name
                )
            if stage6_store is not None:
                try:
                    from .ella_stage6 import build_solar_calibration
                    stage6_rows = await hass.async_add_executor_job(
                        canonical_collector.storage.read_site_energy_history,
                        site_id, now - timedelta(days=60), now,
                    )
                    stage6_frames = await hass.async_add_executor_job(
                        canonical_collector.storage.read_external_input_frames,
                        now, source_scope="site", site_id=site_id,
                    )
                    solar_frames = [frame for frame in stage6_frames if str(frame.get("payload_schema", "")).startswith("forecast_solar.")]
                    prior = stage6_store.public_state(site_id)
                    calibration = build_solar_calibration(site_id, stage6_rows, solar_frames, now, prior)
                    await stage6_store.async_record(site_id, calibration)
                except Exception:
                    pass
            if learning_store is not None:
                from .websocket import _async_power_forecast_state
                power_forecast = await _async_power_forecast_state(hass, requested_site_id=site_id)
                if power_forecast.get("available"):
                    power_rows = await hass.async_add_executor_job(
                        canonical_collector.storage.read_site_energy_history,
                        site_id, now - timedelta(days=60), now,
                    )
                    active_power_generations: dict[str, set[str]] = {}
                    for target in site_identity_manager.collection_targets():
                        if target.get("site_id") != site_id or not target.get("generation_id"):
                            continue
                        active_power_generations.setdefault(str(target.get("logical_role")), set()).add(str(target["generation_id"]))
                    power_result = await learning_store.async_record_power_forecast(
                        site_id, power_forecast, power_rows, dt_util.now(), active_power_generations
                    )
                    if power_result.get("written") or power_result.get("calibration_changed"):
                        hass.bus.async_fire("elrakning_load_forecast_update", {
                            "site_id": site_id,
                            "power_forecast": True,
                            "forecast_id": power_result.get("forecast_id"),
                        })
            if result.get("written"):
                hass.bus.async_fire("elrakning_load_forecast_update", {
                    "site_id": site_id, "frame_id": result.get("frame_id"),
                    "model_version": result.get("model_version"),
                })
        except Exception:
            # Forecast availability is fail-closed and must not prevent startup.
            continue


async def _async_capture_monthly_forecast(hass) -> None:
    """Run the producer and persist a fail-closed state if input assembly aborts."""
    data = hass.data.get(DOMAIN, {})
    identity = data.get("site_identity_manager")
    manager = data.get("monthly_forecast_manager")
    if not identity or not manager:
        return
    site_ids = _monthly_forecast_site_ids(identity)
    for site_id in site_ids:
        try:
            await _async_capture_monthly_forecast_impl(hass, requested_site_id=site_id)
        except Exception:
            config = (identity.collection_site_configs().get(site_id) or {})
            timezone_name = ((config.get("location") or {}).get("timezone") if isinstance(config, dict) else None) or "UTC"
            now = dt_util.now().astimezone(timezone.utc)
            target_month = now.astimezone(ZoneInfo(timezone_name)).strftime("%Y-%m")
            await manager.async_record_unavailable(
                site_id=site_id,
                decision_at=now,
                target_month=target_month,
                reason="monthly_forecast_input_builder_failed",
            )


def _monthly_forecast_site_ids(identity) -> list[str]:
    """Return explicit collection sites without using the active UI site."""
    configs = identity.collection_site_configs()
    return sorted(
        str(site_id)
        for site_id, config in configs.items()
        if isinstance(site_id, str)
        and isinstance(config, dict)
        and config.get("collection_enabled", True) is True
    )


async def _async_capture_monthly_forecast_impl(hass, requested_site_id: str | None = None) -> None:
    """Build one bounded monthly forecast from existing runtime readers."""
    data = hass.data.get(DOMAIN, {})
    identity = data.get("site_identity_manager")
    collector = data.get("canonical_collector")
    manager = data.get("monthly_forecast_manager")
    entry = data.get("config_entry")
    if not identity or not collector or not manager or not entry:
        return
    active_site_id = getattr(identity, "state", {}).get("active_site_id")
    site_id = requested_site_id or active_site_id
    if not isinstance(site_id, str) or not site_id:
        return
    config = (identity.collection_site_configs().get(site_id) or {})
    timezone_name = ((config.get("location") or {}).get("timezone") if isinstance(config, dict) else None) or "UTC"
    now = dt_util.now().astimezone(timezone.utc)
    from zoneinfo import ZoneInfo
    from .monthly_forecast import (
        build_actual_priced_cost_to_date,
        build_month_end_slots,
        canonical_spot_price_periods,
        month_window,
    )
    from .websocket import _async_power_forecast_state, _serialize_price_data
    zone = ZoneInfo(timezone_name)
    local_now = now.astimezone(zone)
    target_month = local_now.strftime("%Y-%m")
    window = month_window(target_month, timezone_name)
    if window is None:
        return
    month_start, month_end = window
    rows = await hass.async_add_executor_job(
        collector.storage.read_site_energy_history, site_id, month_start, now
    )
    billing_points = [
        {"timestamp": row["interval_start"].isoformat(), "import_kw": max(0.0, value_kw)}
        for row in rows
        if row.get("logical_role") == "grid.power/import"
        and row.get("quality_status") in {"good", "partial"}
        and (value_kw := _power_to_kw(row.get("value"), row.get("unit"))) is not None
    ]
    coordinator = getattr(entry, "runtime_data", None)
    price_periods = []
    if coordinator is not None:
        cursor = month_start.astimezone(zone).date()
        last = (month_end - timedelta(seconds=1)).astimezone(zone).date()
        while cursor <= last:
            try:
                price_data = await coordinator.async_get_price_data(cursor)
                serialized = _serialize_price_data(hass, price_data)
                price_periods.extend(serialized.get("periods") or [])
            except Exception:
                pass
            cursor += timedelta(days=1)
    price_binding = identity.global_binding("nord_pool") if hasattr(identity, "global_binding") else None
    price_area = price_binding.get("area") if isinstance(price_binding, dict) else None
    price_currency = (price_binding.get("currency") or "SEK") if isinstance(price_binding, dict) else "SEK"
    try:
        canonical_price_frames = await hass.async_add_executor_job(
            partial(
                collector.storage.read_external_input_frames,
                now,
                source_scope="global",
                logical_role="market.price.energy",
            )
        )
    except Exception:
        canonical_price_frames = []
    price_periods.extend(
        canonical_spot_price_periods(
            canonical_price_frames,
            area=price_area,
            currency=price_currency,
        )
    )
    grid_manager = data.get("grid_manager")
    grid_binding = ((config.get("bindings") or {}).get("grid") if isinstance(config, dict) else None)
    grid_state = (
        grid_manager.public_state_for_binding(grid_binding)
        if grid_manager and isinstance(grid_binding, dict)
        else {}
    )
    grid_price = grid_state.get("grid_price") if isinstance(grid_state, dict) else {}
    grid_provider = getattr(grid_manager, "provider", None)
    timeline = getattr(grid_provider, "tariff_timeline", []) if grid_provider else []
    resolved_grid_tariff = resolve_grid_tariff(
        timeline, site_id=site_id, at=now, decision_at=now
    ) if timeline else None
    applicable_grid_price = (
        resolved_grid_tariff.get("grid_price")
        if isinstance(resolved_grid_tariff, dict)
        else None
    )
    if not isinstance(applicable_grid_price, dict) and isinstance(grid_price, dict):
        applicable_grid_price = grid_price
    if not isinstance(applicable_grid_price, dict):
        applicable_grid_price = None
    trade_manager = data.get("elhandel_manager")
    trade_binding = ((config.get("bindings") or {}).get("elhandel") if isinstance(config, dict) else None)
    trade_state = {}
    if trade_manager and isinstance(trade_binding, dict):
        if site_id == active_site_id:
            trade_state = trade_manager.public_state()
        else:
            facility_id = trade_binding.get("facility_id")
            provider = trade_binding.get("provider")
            storage = getattr(trade_manager, "storage", None)
            if storage and facility_id and provider:
                trade_state = await storage.async_load(
                    facility_id=facility_id, provider=provider, use_active_namespace=False
                ) or {}
    trade_tariff = ((trade_state.get("summary") or {}).get("tariff") or {}) if isinstance(trade_state, dict) else {}
    actual = build_actual_priced_cost_to_date(
        points=billing_points,
        price_periods=price_periods,
        month_start=month_start,
        now=now,
        trade_fixed_fee_sek=trade_tariff.get("fixed_fee_incl_vat_per_month"),
        grid_fixed_fee_sek=applicable_grid_price.get("fixed_monthly_sek") if applicable_grid_price else None,
    )
    near_term = []
    for offset in range(3):
        try:
            forecast = await _async_power_forecast_state(hass, requested_date=local_now.date() + timedelta(days=offset), requested_site_id=site_id)
        except Exception:
            forecast = {}
        for point in ((forecast.get("series") or {}).get("import") or {}).get("forecast_points") or []:
            near_term.append({
                "valid_at": point.get("valid_at"), "end_at": point.get("end_at"),
                "import_kw": float(point.get("value_w")) / 1000.0,
                "known_at": forecast.get("known_at"), "provenance": point.get("provenance") or {},
            })
    # Reuse the latest persisted, site-scoped power forecast when the live
    # builder races the power snapshot update during startup.
    learning_store = data.get("ella_learning_store")
    site_state = (getattr(learning_store, "state", {}).get("sites", {}).get(site_id, {})
                  if learning_store else {})
    persisted = sorted(
        [item for item in (site_state.get("power_forecasts") or [])
         if isinstance(item, dict) and item.get("site_id") == site_id],
        key=lambda item: str(item.get("known_at") or ""),
    )[-1:]
    for snapshot in persisted:
        snapshot_known_at = snapshot.get("known_at")
        for valid_at, series in (snapshot.get("points") or {}).items():
            import_point = series.get("import") if isinstance(series, dict) else None
            if not isinstance(import_point, dict):
                continue
            near_term.append({
                "valid_at": valid_at,
                "end_at": import_point.get("end_at"),
                "import_kw": float(import_point.get("predicted_w")) / 1000.0,
                "known_at": snapshot_known_at,
                "provenance": {
                    **(import_point.get("provenance") or {}),
                    "method": "persisted_power_forecast_fallback",
                    "forecast_id": snapshot.get("forecast_id"),
                },
            })
    slots = build_month_end_slots(
        decision_at=now, month_end=month_end, near_term_points=near_term,
        historical_rows=rows, timezone_name=timezone_name, known_price_periods=price_periods,
    )
    result = await manager.async_refresh(
        site_id=site_id, timezone_name=timezone_name, decision_at=now,
        target_month=target_month,
        actual_cost_to_date_sek=actual.get("actual_cost_to_date_sek"),
        actual_import_to_date_kwh=actual.get("actual_import_to_date_kwh"),
        future_points=slots.get("slots") or [], price_periods=price_periods,
        remaining_fixed_cost_sek=0.0,
        source_generations=sorted({
            str(row.get("source_generation_id"))
            for row in rows
            if row.get("source_generation_id")
        } | {
            str(period.get("price_source_generation_id"))
            for period in price_periods
            if period.get("price_source_generation_id")
        }),
        weather={"support_count": 0, "correction_enabled": False, "reason": "temperature_residual_support_missing"},
    )
    actual_by_day = {}
    for row in rows:
        if row.get("logical_role") != "grid.power/import" or row.get("unit") != "W":
            continue
        start = row.get("interval_start")
        if not hasattr(start, "astimezone"):
            continue
        day = start.astimezone(zone).date().isoformat()
        actual_by_day.setdefault(day, []).append(max(0.0, float(row.get("value") or 0.0)) / 1000.0 * float(row.get("resolution_seconds") or 900) / 3600.0)
    await manager.async_evaluate_matured_days(
        site_id, {day: sum(values) for day, values in actual_by_day.items()}
    )
    result["actual_priced_import_to_date_kwh"] = actual.get("priced_import_to_date_kwh")
    result["missing_past_import_kwh"] = actual.get("missing_past_import_kwh")
    result["month_end_coverage"] = {key: slots.get(key) for key in (
        "available", "slot_count", "expected_slot_count", "fallback_slot_count",
        "method_counts", "price_method_counts", "price_missing_slot_count",
        "weather_corrected_slot_count", "weather_support_count", "reason",
    )}


class _LoadForecastTaskOwner:
    """Own one coalesced load-forecast task for the config entry."""

    def __init__(self, hass, site_identity_manager, canonical_collector):
        self.hass = hass
        self.site_identity_manager = site_identity_manager
        self.canonical_collector = canonical_collector
        self.task = None
        self.pending = False
        self.closed = False

    def _create_task(self):
        return _create_background_task_on_ha_loop(
            self.hass,
            lambda: _async_capture_load_forecasts(
                self.hass, self.site_identity_manager, self.canonical_collector
            ),
            "elrakning_load_forecast",
        )

    def schedule(self):
        if self.closed:
            return None
        if self.task is not None and not self.task.done():
            self.pending = True
            return self.task
        self.pending = False
        self.task = self._create_task()
        self.task.add_done_callback(self._task_done)
        self.hass.data.setdefault(DOMAIN, {})["load_forecast_capture_task"] = self.task
        return self.task

    def _task_done(self, task):
        if task is not self.task:
            return
        try:
            if not task.cancelled():
                task.exception()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        self.task = None
        self.hass.data.setdefault(DOMAIN, {})["load_forecast_capture_task"] = None
        if self.closed or not self.pending:
            self.pending = False
            return
        self.pending = False
        self.schedule()

    def close(self):
        self.closed = True
        self.pending = False
        task = self.task
        if task is not None and not task.done():
            task.cancel()
        return task


def _get_load_forecast_task_owner(hass, site_identity_manager=None, canonical_collector=None):
    """Return the shared load-forecast owner for this config entry."""
    data = hass.data.setdefault(DOMAIN, {})
    owner = data.get("load_forecast_task_owner")
    if owner is None or owner.closed:
        owner = _LoadForecastTaskOwner(hass, site_identity_manager, canonical_collector)
        data["load_forecast_task_owner"] = owner
    return owner


def _schedule_load_forecast_capture(hass, site_identity_manager, canonical_collector):
    """Schedule one coalesced load-forecast capture on Home Assistant's loop."""
    return _get_load_forecast_task_owner(
        hass, site_identity_manager, canonical_collector
    ).schedule()


class _MonthlyForecastTaskOwner:
    """Own one coalesced monthly forecast task for the config entry."""

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.task = None
        self.pending = False
        self.closed = False

    def _create_task(self):
        return _create_background_task_on_ha_loop(
            self.hass,
            lambda: _async_capture_monthly_forecast(self.hass),
            "elrakning_monthly_forecast",
        )

    def schedule(self):
        if self.closed:
            return None
        if self.task is not None and not self.task.done():
            self.pending = True
            return self.task
        self.pending = False
        self.task = self._create_task()
        self.task.add_done_callback(self._task_done)
        self.hass.data.setdefault(DOMAIN, {})["monthly_forecast_capture_task"] = self.task
        return self.task

    def _task_done(self, task):
        if task is not self.task:
            return
        self.task = None
        self.hass.data.setdefault(DOMAIN, {})["monthly_forecast_capture_task"] = None
        if self.closed or not self.pending:
            self.pending = False
            return
        self.pending = False
        self.schedule()

    def close(self):
        self.closed = True
        self.pending = False
        task = self.task
        if task is not None and not task.done():
            task.cancel()
        return task


def _get_monthly_forecast_task_owner(hass, entry=None):
    """Return the shared owner, including during setup event races."""
    data = hass.data.setdefault(DOMAIN, {})
    owner = data.get("monthly_forecast_task_owner")
    if owner is None:
        owner = _MonthlyForecastTaskOwner(hass, entry or data.get("config_entry"))
        data["monthly_forecast_task_owner"] = owner
    return owner


def _schedule_monthly_forecast_capture(hass):
    """Schedule one coalesced monthly forecast refresh."""
    return _get_monthly_forecast_task_owner(hass).schedule()


def _schedule_monthly_forecast_capture_on_loop(hass):
    """Marshal event-driven forecast scheduling onto Home Assistant's loop."""
    hass.loop.call_soon_threadsafe(_schedule_monthly_forecast_capture, hass)


class _ReplayTaskProxy:
    """Bridge a task scheduled on HA's loop to a worker-thread caller."""

    def __init__(self) -> None:
        self._completion = concurrent.futures.Future()
        self._lock = threading.Lock()
        self._task = None
        self._cancel_requested = False

    def bind(self, task) -> None:
        with self._lock:
            self._task = task
            cancel_requested = self._cancel_requested
        task.add_done_callback(self._complete)
        if cancel_requested:
            task.cancel()

    def _complete(self, task) -> None:
        if self._completion.done():
            return
        if task.cancelled():
            self._completion.cancel()
            return
        error = task.exception()
        if error is not None:
            self._completion.set_exception(error)
        else:
            self._completion.set_result(task.result())

    def fail(self, error) -> None:
        if not self._completion.done():
            self._completion.set_exception(error)

    def cancel(self) -> bool:
        with self._lock:
            self._cancel_requested = True
            task = self._task
        if task is None:
            return self._completion.cancel()
        return task.cancel()

    def done(self) -> bool:
        return self._completion.done()

    def cancelled(self) -> bool:
        return self._completion.cancelled()

    def result(self, *args, **kwargs):
        return self._completion.result(*args, **kwargs)

    def exception(self, *args, **kwargs):
        return self._completion.exception(*args, **kwargs)

    def add_done_callback(self, callback):
        """Adapt completion callbacks to the proxy task interface."""
        self._completion.add_done_callback(lambda _future: callback(self))

    def __await__(self):
        return asyncio.wrap_future(self._completion).__await__()


def _create_background_task_on_ha_loop(hass, coroutine_factory, name):
    """Create background work on Home Assistant's active loop only."""
    def create_on_loop():
        coroutine = coroutine_factory()
        create_background_task = getattr(hass, "async_create_background_task", None)
        if callable(create_background_task):
            return create_background_task(coroutine, name=name)
        return hass.async_create_task(coroutine)

    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None
    ha_loop = getattr(hass, "loop", None) or running_loop
    if ha_loop is None or running_loop is ha_loop:
        return create_on_loop()

    proxy = _ReplayTaskProxy()

    def schedule_on_loop():
        if proxy.cancelled():
            return
        try:
            proxy.bind(create_on_loop())
        except Exception as error:
            proxy.fail(error)

    ha_loop.call_soon_threadsafe(schedule_on_loop)
    return proxy


def _create_replay_background_task(hass, coroutine_factory, name):
    """Create replay work on Home Assistant's active loop only."""
    return _create_background_task_on_ha_loop(hass, coroutine_factory, name)


async def _async_warm_history(power_manager, meter_manager) -> None:
    """Warm independent history caches without blocking integration startup."""
    jobs = []
    if callable(getattr(power_manager, "async_history", None)):
        jobs.append(power_manager.async_history(7))
    if callable(getattr(meter_manager, "async_power_history", None)):
        jobs.append(meter_manager.async_power_history())
    if jobs:
        await asyncio.gather(*jobs, return_exceptions=True)


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Register the panel before optional runtime initialization can fail."""
    integration_dir = Path(__file__).parent
    frontend_data = hass.data.setdefault(DOMAIN, {})
    if not frontend_data.get("static_path_registered"):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    PANEL_LOADER_PATH,
                    str(integration_dir / "frontend" / "elrakning-loader.js"),
                    cache_headers=False,
                ),
                StaticPathConfig(
                    PANEL_RESOURCE_PATH,
                    str(integration_dir / "frontend" / "elrakning-panel.js"),
                    cache_headers=False,
                ),
                StaticPathConfig(
                    PANEL_CADENCE_AUDIT_PATH,
                    str(integration_dir / "frontend" / "elrakning-cadence-audit.js"),
                    cache_headers=False,
                ),
                StaticPathConfig(
                    PANEL_MANIFEST_PATH,
                    str(integration_dir / "manifest.json"),
                    cache_headers=False,
                ),
            ]
        )
        frontend_data["static_path_registered"] = True
    if not frontend.async_panel_exists(hass, PANEL_PATH):
        frontend.async_register_built_in_panel(
            hass,
            component_name="custom",
            frontend_url_path=PANEL_PATH,
            sidebar_title="Elräkning",
            sidebar_icon="mdi:flash-outline",
            config={
                "_panel_custom": {
                    "name": "elrakning-panel",
                    "js_url": PANEL_LOADER_URL,
                    "embed_iframe": False,
                }
            },
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Elräkning with the control plane available during startup."""
    frontend_data = hass.data.setdefault(DOMAIN, {})
    frontend_data["runtime_status"] = "initializing"
    setup_started_at = runtime_checkpoint(
        "setup_entry.start", phase="setup", entry_id=entry.entry_id
    )
    _start_event_loop_lag_heartbeat(hass)
    try:
        await _await_setup_step("setup_entry.frontend_register", _async_register_frontend(hass))
        runtime_checkpoint("setup_entry.websocket_register.start", phase="setup")
        async_register_websocket_commands(hass)
        async_register_cadence_audit_websocket(hass)
        runtime_checkpoint("setup_entry.websocket_register.complete", phase="setup")
        result = await _async_setup_entry(hass, entry)
        runtime_checkpoint("setup_entry.complete", phase="setup", started_at=setup_started_at)
        return result
    except Exception:
        await _async_cancel_task(frontend_data.pop("event_loop_lag_heartbeat_task", None))
        frontend_data["runtime_status"] = "failed"
        runtime_checkpoint(
            "setup_entry.error", phase="setup", started_at=setup_started_at,
            level=logging.ERROR,
        )
        raise


async def _async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Elräkning from a config entry."""
    frontend_data = hass.data.setdefault(DOMAIN, {})
    frontend_data["config_entry"] = entry
    frontend_data["app_shadow_client"] = AppShadowClient.from_config_entry(hass, entry)
    coordinator = ElrakningCoordinator(hass, entry)
    entry.runtime_data = coordinator
    manager = ElhandelManager(hass, entry)
    await _await_setup_step("setup.manager_load", manager.async_load())
    hass.data.setdefault(DOMAIN, {})["elhandel_manager"] = manager
    meter_manager = MeterManager(hass, manager.async_diagnostic)
    await _await_setup_step("setup.meter_manager_load", meter_manager.async_load())
    hass.data.setdefault(DOMAIN, {})["meter_manager"] = meter_manager
    power_manager = PowerManager(hass, manager.async_diagnostic)
    await _await_setup_step("setup.power_manager_load", power_manager.async_load())
    hass.data.setdefault(DOMAIN, {})["power_manager"] = power_manager
    site_identity_manager = SiteIdentityManager(hass, power_manager, meter_manager)
    await _await_setup_step("setup.site_identity_load", site_identity_manager.async_load())
    await _await_setup_step("setup.site_identity_sync", site_identity_manager.async_sync_from_current())
    power_manager.set_mapping_changed_callback(site_identity_manager.async_sync_from_current)
    meter_manager.set_mapping_changed_callback(site_identity_manager.async_sync_from_current)
    hass.data.setdefault(DOMAIN, {})["site_identity_manager"] = site_identity_manager
    ella_load_registry = EllaLoadRegistry(hass, lambda: dt_util.now().isoformat())
    await _await_setup_step("setup.ella_load_registry_load", ella_load_registry.async_load())
    hass.data.setdefault(DOMAIN, {})["ella_load_registry"] = ella_load_registry
    ella_debug_snapshot_store = EllaDebugSnapshotStore(hass)
    await _await_setup_step("setup.ella_debug_snapshot_store_load", ella_debug_snapshot_store.async_load())
    hass.data.setdefault(DOMAIN, {})["ella_debug_snapshot_store"] = ella_debug_snapshot_store
    ella_learning_store = EllaLearningStore(hass)
    await _await_setup_step("setup.ella_learning_store_load", ella_learning_store.async_load())
    hass.data.setdefault(DOMAIN, {})["ella_learning_store"] = ella_learning_store
    monthly_forecast_manager = MonthlyForecastManager(ella_learning_store)
    hass.data.setdefault(DOMAIN, {})["monthly_forecast_manager"] = monthly_forecast_manager
    ella_stage6_store = EllaStage6CalibrationStore(hass)
    await _await_setup_step("setup.ella_stage6_store_load", ella_stage6_store.async_load())
    hass.data.setdefault(DOMAIN, {})["ella_stage6_store"] = ella_stage6_store
    ella_execution_store = EllaExecutionStore(hass)
    await _await_setup_step("setup.ella_execution_store_load", ella_execution_store.async_load())
    hass.data.setdefault(DOMAIN, {})["ella_execution_store"] = ella_execution_store
    ella_ess_facts_store = EllaEssFactsStore(hass)
    await _await_setup_step("setup.ella_ess_facts_store_load", ella_ess_facts_store.async_load())
    hass.data.setdefault(DOMAIN, {})["ella_ess_facts_store"] = ella_ess_facts_store
    ella_economic_policy_store = EllaEconomicPolicyStore(hass)
    await _await_setup_step("setup.ella_economic_policy_store_load", ella_economic_policy_store.async_load())
    hass.data.setdefault(DOMAIN, {})["ella_economic_policy_store"] = ella_economic_policy_store
    replay_artifact_store = ReplayArtifactStore(hass)
    await _await_setup_step("setup.replay_artifact_store_load", replay_artifact_store.async_load())
    hass.data.setdefault(DOMAIN, {})["replay_artifact_store"] = replay_artifact_store
    await async_register_replay_artifact_service(hass)
    cadence_audit_manager = CadenceAuditManager(hass, site_identity_manager)
    await _await_setup_step("setup.cadence_audit_load", cadence_audit_manager.async_load())
    hass.data.setdefault(DOMAIN, {})["cadence_audit_manager"] = cadence_audit_manager
    grid_manager = GridManager(hass, entry)
    await _await_setup_step("setup.grid_manager_load", grid_manager.async_load())
    hass.data.setdefault(DOMAIN, {})["grid_manager"] = grid_manager
    await _await_setup_step(
        "setup.runtime_bindings_prepare",
        site_identity_manager.async_prepare_runtime_bindings(manager, grid_manager, coordinator),
    )
    canonical_collector = CanonicalCollector(hass, site_identity_manager)
    await _await_setup_step("setup.canonical_collector_start", canonical_collector.async_start())
    hass.data.setdefault(DOMAIN, {})["canonical_collector"] = canonical_collector
    frontend_data["history_warmup_task"] = hass.async_create_task(
        _async_warm_history(power_manager, meter_manager)
    )
    apply_migrations = getattr(site_identity_manager, "async_apply_canonical_source_migrations", None)
    if apply_migrations is not None:
        await _await_setup_step(
            "setup.canonical_source_migrations",
            apply_migrations(canonical_collector.storage),
        )
    await _await_setup_step(
        "setup.proof_service_register",
        async_register_proof_service(hass, site_identity_manager, entry),
    )
    await _await_setup_step(
        "setup.coordinator_first_refresh",
        coordinator.async_config_entry_first_refresh(),
    )
    if manager.state["configured"] and site_identity_manager.active_binding("elhandel"):
        manager.async_start_refresh()
    solar_forecast_manager = SolarForecastManager(
        hass, manager.async_diagnostic, site_identity_manager.forecast_collection_targets
    )
    await _await_setup_step("setup.solar_forecast_load", solar_forecast_manager.async_load())
    hass.data.setdefault(DOMAIN, {})["solar_forecast_manager"] = solar_forecast_manager
    solar_weather_manager = SolarWeatherManager(hass)
    await _await_setup_step("setup.solar_weather_load", solar_weather_manager.async_load())
    hass.data.setdefault(DOMAIN, {})["solar_weather_manager"] = solar_weather_manager
    solar_pvgis_manager = SolarPvgisManager(hass, power_manager)
    await _await_setup_step("setup.solar_pvgis_load", solar_pvgis_manager.async_load())
    hass.data.setdefault(DOMAIN, {})["solar_pvgis_manager"] = solar_pvgis_manager
    solar_open_meteo_manager = SolarOpenMeteoManager(hass, power_manager)
    try:
        await _await_setup_step("setup.solar_open_meteo_load", solar_open_meteo_manager.async_load())
    except Exception:
        # Optional external forecast data must never prevent panel setup.
        pass
    hass.data.setdefault(DOMAIN, {})["solar_open_meteo_manager"] = solar_open_meteo_manager
    solar_shadow_manager = SolarShadowManager(
        hass, solar_forecast_manager, solar_weather_manager, power_manager,
        solar_pvgis_manager, solar_open_meteo_manager,
    )
    await _await_setup_step("setup.solar_shadow_load", solar_shadow_manager.async_load())
    hass.data.setdefault(DOMAIN, {})["solar_shadow_manager"] = solar_shadow_manager
    solar_evidence_manager = SolarEvidenceManager(
        hass, power_manager, solar_forecast_manager, site_identity_manager.collection_site_configs
    )
    await _await_setup_step("setup.solar_evidence_load", solar_evidence_manager.async_load())
    await _await_setup_step(
        "setup.solar_contexts_prepare",
        site_identity_manager.async_prepare_solar_contexts({
            "forecast": solar_forecast_manager,
            "weather": solar_weather_manager,
            "pvgis": solar_pvgis_manager,
            "open_meteo": solar_open_meteo_manager,
            "shadow": solar_shadow_manager,
            "evidence": solar_evidence_manager,
        }),
    )
    await _await_setup_step(
        "setup.solar_open_meteo_migrate_locations",
        solar_open_meteo_manager.async_migrate_site_locations(site_identity_manager),
    )
    greenely_economics = GreenelyInvoiceEconomicsProducer(hass, entry, site_identity_manager, canonical_collector.storage)
    hass.data.setdefault(DOMAIN, {})["greenely_invoice_economics"] = greenely_economics
    greenely_economics.async_schedule_capture()
    if unsubscribe := frontend_data.pop("greenely_economics_unsub", None):
        unsubscribe()
    frontend_data["greenely_economics_unsub"] = async_track_time_change(
        hass, lambda _now: greenely_economics.async_schedule_capture(), hour=0, minute=5, second=0
    )
    await _await_setup_step(
        "setup.solar_forecast_capture_baselines",
        solar_forecast_manager.async_capture_collection_baselines(),
    )
    load_forecast_owner = _get_load_forecast_task_owner(
        hass, site_identity_manager, canonical_collector
    )
    frontend_data["load_forecast_startup_task"] = load_forecast_owner.schedule()
    if unsubscribe := frontend_data.pop("load_forecast_cadence_unsub", None):
        unsubscribe()
    frontend_data["load_forecast_cadence_unsub"] = async_track_time_change(
        hass, lambda _now: _schedule_load_forecast_capture(
            hass, site_identity_manager, canonical_collector
        ), hour=None, minute=[0, 15, 30, 45], second=30
    )
    frontend_data["monthly_forecast_cadence_unsub"] = async_track_time_change(
        hass, lambda _now: _schedule_monthly_forecast_capture(hass), hour=None, minute=5, second=0
    )
    frontend_data["open_meteo_startup_task"] = hass.async_create_task(
        canonical_collector.async_capture_open_meteo(trigger="startup")
    )
    single_run_capture = getattr(canonical_collector, "async_capture_single_run_day_ahead", None)
    if single_run_capture is not None:
        frontend_data["single_run_startup_task"] = hass.async_create_task(
            single_run_capture(trigger="startup")
        )
    frontend_data["weather_startup_task"] = hass.async_create_task(
        canonical_collector.async_capture_weather(trigger="startup")
    )
    await _await_setup_step(
        "setup.canonical_forecast_solar_capture",
        canonical_collector.async_capture_forecast_solar(trigger="startup"),
    )
    hass.data.setdefault(DOMAIN, {})["solar_evidence_manager"] = solar_evidence_manager
    # Evidence catch-up is independent of panel readiness and may perform Recorder/HTTP work.
    # Keep it off the critical startup path so live state and history can hydrate immediately.
    mark_capture_scheduled = getattr(solar_evidence_manager, "mark_capture_scheduled", None)
    if callable(mark_capture_scheduled):
        mark_capture_scheduled("startup")
    frontend_data["solar_evidence_startup_task"] = hass.async_create_task(
        solar_evidence_manager.async_startup_catch_up()
    )
    if callable(mark_capture_scheduled):
        mark_capture_scheduled("backfill")
    solar_evidence_manager._task = hass.async_create_task(solar_evidence_manager.async_backfill())
    async_register_eon_handoff_views(hass)
    cached_import_recovery = getattr(getattr(grid_manager, "provider", None), "async_persist_cached_imports", None)
    if callable(cached_import_recovery):
        await _await_setup_step(
            "setup.eon_cached_import_recovery",
            cached_import_recovery(),
        )
    if grid_manager.configured and site_identity_manager.active_binding("grid"):
        grid_manager.async_start_refresh()

    frontend_data = hass.data.setdefault(DOMAIN, {})
    frontend_data["coordinator_unsub"] = coordinator.async_add_listener(
        lambda: hass.bus.async_fire("elrakning_price_update")
    )
    frontend_data["electricity_provider_price_unsub"] = hass.bus.async_listen(
        ELECTRICITY_PROVIDER_UPDATE_EVENT,
        lambda _: _schedule_price_update(hass),
    )
    frontend_data["eon_grid_unsub"] = hass.bus.async_listen(
        EON_GRID_UPDATE_EVENT,
        lambda _: _schedule_eon_grid_update(hass),
    )
    frontend_data["solar_weather_unsub"] = hass.bus.async_listen(
        SOLAR_WEATHER_UPDATE_EVENT,
        lambda _: _schedule_price_update(hass),
    )
    if unsubscribe := frontend_data.pop("midnight_refresh_unsub", None):
        unsubscribe()
    frontend_data["midnight_refresh_unsub"] = async_track_time_change(
        hass,
        partial(_async_midnight_refresh, coordinator),
        hour=0,
        minute=0,
        second=0,
    )
    frontend_data["runtime_status"] = "ready"
    def _replay_site_ids(event_site_id=None):
        state = site_identity_manager.state
        registered: set[str] = set()
        if isinstance(state, dict):
            for source in (state.get("site_configs"), state.get("sites"), state.get("available_sites")):
                if isinstance(source, dict):
                    registered.update(str(site_id) for site_id in source if site_id)
                elif isinstance(source, list):
                    registered.update(str(item.get("site_id")) for item in source if isinstance(item, dict) and item.get("site_id"))
        active = state.get("active_site_id") or (state.get("site") or {}).get("site_id") if isinstance(state, dict) else None
        site_ids = [active] if isinstance(active, str) and active else []
        site_ids.extend(site_id for site_id in sorted(registered) if site_id not in site_ids)
        if isinstance(event_site_id, str) and event_site_id:
            return [event_site_id] if event_site_id in site_ids else []
        return site_ids

    replay_active_task = None
    replay_pending_all = False
    replay_pending_site_ids = set()
    replay_active_trigger_keys = set()
    replay_pending_trigger_keys = set()
    replay_site_tasks = _ReplaySiteTaskRegistry(
        lambda coroutine, name: hass.async_create_background_task(coroutine, name=name)
    )
    frontend_data["replay_site_task_registry"] = replay_site_tasks
    frontend_data["replay_scheduler_closed"] = False

    async def _generate_replay_artifact(_call=None, event_site_id=None):
        async def _run_site(site_id):
            await _record_replay_diagnostic(
                "INFO",
                "replay_site_started",
                json.dumps({"site_id": site_id}, separators=(",", ":")),
            )
            try:
                result = await replay_site_tasks.run(
                    site_id,
                    lambda: async_generate_artifact(hass, site_id),
                    REPLAY_RUN_TIMEOUT_SECONDS,
                    f"elrakning_replay_site_{site_id}",
                )
            except asyncio.CancelledError:
                raise
            except Exception as err:
                result = {"accepted": False, "site_id": site_id, "reason": type(err).__name__}
                await _record_replay_diagnostic(
                    "ERROR",
                    "replay_site_failed",
                    json.dumps({"site_id": site_id, "error_type": type(err).__name__, "error": str(err)[:200]}, separators=(",", ":")),
                )
            if result.get("reason") == "replay_timeout":
                await _record_replay_diagnostic(
                    "ERROR",
                    "replay_site_timeout",
                    json.dumps({"site_id": site_id, "task_active": result.get("task_active") is True}, separators=(",", ":")),
                )
            hass.bus.async_fire("elrakning_replay_benchmark_evidence_update", {"site_id": site_id, "status": (result.get("evidence") or {}).get("status")})
            if result.get("accepted"):
                hass.bus.async_fire("elrakning_replay_artifact_published", {
                    "schema": "ella_replay_artifact.v1",
                    "site_id": site_id,
                    "artifact_id": result.get("artifact_id"),
                    "readback": result.get("readback") is True,
                    "holdouts": result.get("holdouts"),
                })
            await _record_replay_diagnostic(
                "INFO",
                "replay_site_completed",
                json.dumps({"site_id": site_id, "accepted": result.get("accepted") is True}, separators=(",", ":")),
            )
            return result

        site_ids = _replay_site_ids(event_site_id)
        results = await asyncio.gather(*(_run_site(site_id) for site_id in site_ids))
        if len(results) == 1:
            return results[0]
        return {"accepted": all(result.get("accepted") is True for result in results), "results": results}

    async def _record_replay_diagnostic(level, event, payload):
        """Record one bounded replay lifecycle event when diagnostics are available."""
        diagnostic = getattr(manager, "async_diagnostic", None)
        if not callable(diagnostic):
            return
        result = diagnostic(level, "replay", event, payload)
        if inspect.isawaitable(result):
            await result

    async def _run_replay_artifact_background(source, event_site_id=None):
        """Run replay work off the startup task barrier and consume failures."""
        started_at = dt_util.now().astimezone(timezone.utc)
        site_ids = _replay_site_ids(event_site_id)
        run_id = f"{source}:{started_at.isoformat()}"
        status = {
            "run_id": run_id,
            "source": source,
            "outcome": "running",
            "started_at": started_at.isoformat(),
            "site_ids": site_ids,
        }
        frontend_data["replay_artifact_task_status"] = status
        await _record_replay_diagnostic(
            "INFO",
            "replay_task_started",
            json.dumps({"run_id": run_id, "source": source, "started_at": started_at.isoformat(), "site_ids": site_ids}, separators=(",", ":")),
        )
        started_monotonic = time.monotonic()
        try:
            result = await _generate_replay_artifact(event_site_id=event_site_id)
        except asyncio.CancelledError:
            finished_at = dt_util.now().astimezone(timezone.utc)
            frontend_data["replay_artifact_task_status"] = {
                **status, "outcome": "cancelled", "finished_at": finished_at.isoformat(),
            }
            await _record_replay_diagnostic(
                "INFO",
                "replay_task_cancelled",
                json.dumps({"run_id": run_id, "source": source, "started_at": started_at.isoformat(), "finished_at": finished_at.isoformat(), "duration_ms": round((time.monotonic() - started_monotonic) * 1000, 3), "site_ids": site_ids}, separators=(",", ":")),
            )
            _schedule_pending_replay()
            raise
        except Exception as err:  # Background work must not poison startup.
            finished_at = dt_util.now().astimezone(timezone.utc)
            frontend_data["replay_artifact_task_status"] = {
                **status,
                "outcome": "error",
                "finished_at": finished_at.isoformat(),
                "error_type": type(err).__name__,
                "error": str(err)[:200],
            }
            await _record_replay_diagnostic(
                "ERROR",
                "replay_task_failed",
                json.dumps({"run_id": run_id, "source": source, "started_at": started_at.isoformat(), "finished_at": finished_at.isoformat(), "duration_ms": round((time.monotonic() - started_monotonic) * 1000, 3), "site_ids": site_ids, "error_type": type(err).__name__, "error": str(err)[:200]}, separators=(",", ":")),
            )
            _schedule_pending_replay()
            return None
        finished_at = dt_util.now().astimezone(timezone.utc)
        frontend_data["replay_artifact_task_status"] = {
            **status, "outcome": "success", "finished_at": finished_at.isoformat(),
        }
        await _record_replay_diagnostic(
            "INFO",
            "replay_task_completed",
            json.dumps({"run_id": run_id, "source": source, "started_at": started_at.isoformat(), "finished_at": finished_at.isoformat(), "duration_ms": round((time.monotonic() - started_monotonic) * 1000, 3), "site_ids": site_ids}, separators=(",", ":")),
        )
        _schedule_pending_replay()
        return result

    def _queue_replay_diagnostic(level, event, payload):
        """Queue one bounded diagnostic without blocking an event callback."""
        def create_on_loop():
            coroutine = _record_replay_diagnostic(level, event, payload)
            create_task = getattr(hass, "async_create_background_task", None)
            if callable(create_task):
                create_task(coroutine, name="elrakning_replay_trigger_diagnostic")
            else:
                hass.async_create_task(coroutine)

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        ha_loop = getattr(hass, "loop", None) or running_loop
        if ha_loop is not None and running_loop is not ha_loop:
            ha_loop.call_soon_threadsafe(create_on_loop)
        else:
            create_on_loop()

    def _start_replay(source, event_site_id, trigger_keys):
        nonlocal replay_active_task, replay_active_trigger_keys
        replay_active_trigger_keys = set(trigger_keys)
        task_names = {
            "startup": "elrakning_replay_artifact_startup",
            "event": "elrakning_replay_artifact_event",
            "coalesced": "elrakning_replay_artifact_coalesced",
        }
        replay_active_task = _create_replay_background_task(
            hass,
            lambda: _run_replay_artifact_background(source, event_site_id),
            task_names.get(source, "elrakning_replay_artifact_event"),
        )
        frontend_data["replay_benchmark_refresh_task"] = replay_active_task

    def _schedule_pending_replay():
        nonlocal replay_active_task, replay_pending_all, replay_active_trigger_keys
        if frontend_data.get("replay_scheduler_closed") or replay_active_task is not asyncio.current_task():
            return
        pending_keys = replay_pending_trigger_keys - replay_active_trigger_keys
        if not replay_pending_all and not replay_pending_site_ids and not pending_keys:
            replay_active_task = None
            replay_active_trigger_keys = set()
            return
        event_site_id = None if replay_pending_all or len(replay_pending_site_ids) != 1 else next(iter(replay_pending_site_ids))
        replay_pending_all = False
        replay_pending_site_ids.clear()
        replay_pending_trigger_keys.clear()
        _start_replay("coalesced", event_site_id, pending_keys)

    def _schedule_replay_evidence(event):
        nonlocal replay_active_task, replay_pending_all
        event_site_id = event.data.get("site_id") if getattr(event, "data", None) else None
        event_type = getattr(event, "event_type", None) or "unknown"
        trigger_key = f"{event_site_id or '*'}:{_replay_trigger_identity(event)}"
        if replay_active_task is not None and not replay_active_task.done():
            if trigger_key in replay_active_trigger_keys or trigger_key in replay_pending_trigger_keys:
                _queue_replay_diagnostic(
                    "INFO",
                    "replay_trigger_duplicate",
                    json.dumps({"event_type": event_type, "site_id": event_site_id}, separators=(",", ":")),
                )
                return
            replay_pending_trigger_keys.add(trigger_key)
            if isinstance(event_site_id, str) and event_site_id:
                replay_pending_site_ids.add(event_site_id)
            else:
                replay_pending_all = True
            _queue_replay_diagnostic(
                "INFO",
                "replay_trigger_coalesced",
                json.dumps({"event_type": event_type, "site_id": event_site_id, "active_run": True}, separators=(",", ":")),
            )
            return
        _start_replay("event", event_site_id, {trigger_key})

    hass.services.async_register(DOMAIN, "replay_artifact_generate", _generate_replay_artifact)
    frontend_data["replay_benchmark_event_unsubs"] = [
        hass.bus.async_listen("elrakning_load_forecast_update", _schedule_replay_evidence),
        hass.bus.async_listen(ELECTRICITY_PROVIDER_UPDATE_EVENT, _schedule_replay_evidence),
        hass.bus.async_listen(EON_GRID_UPDATE_EVENT, _schedule_replay_evidence),
    ]
    frontend_data["monthly_forecast_event_unsubs"] = [
        hass.bus.async_listen("elrakning_load_forecast_update", lambda _event: _schedule_monthly_forecast_capture_on_loop(hass)),
        hass.bus.async_listen(ELECTRICITY_PROVIDER_UPDATE_EVENT, lambda _event: _schedule_monthly_forecast_capture_on_loop(hass)),
        hass.bus.async_listen(EON_GRID_UPDATE_EVENT, lambda _event: _schedule_monthly_forecast_capture_on_loop(hass)),
    ]
    frontend_data["forecast_view_cache_unsubs"] = [
        hass.bus.async_listen(
            "elrakning_load_forecast_update",
            lambda event: clear_forecast_view_caches(hass, (event.data or {}).get("site_id")),
        ),
        hass.bus.async_listen(
            ELECTRICITY_PROVIDER_UPDATE_EVENT,
            lambda _event: clear_forecast_view_caches(hass),
        ),
        hass.bus.async_listen(
            EON_GRID_UPDATE_EVENT,
            lambda _event: clear_forecast_view_caches(hass),
        ),
        hass.bus.async_listen(
            SOLAR_WEATHER_UPDATE_EVENT,
            lambda _event: clear_forecast_view_caches(hass),
        ),
    ]
    _start_replay("startup", None, {"startup"})
    frontend_data["replay_artifact_startup_task"] = replay_active_task
    await _record_replay_diagnostic(
        "INFO",
        "replay_scheduler_registered",
        json.dumps({"source": "startup", "scheduled_at": dt_util.now().astimezone(timezone.utc).isoformat()}, separators=(",", ":")),
    )
    hass.bus.async_fire(INTEGRATION_READY_EVENT)
    owner = _get_monthly_forecast_task_owner(hass, entry)
    frontend_data["monthly_forecast_startup_task"] = owner.schedule()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Elräkning from a config entry."""
    frontend_data = hass.data.get(DOMAIN, {})
    frontend_data["replay_scheduler_closed"] = True
    entry_coordinator = getattr(entry, "runtime_data", None)
    frontend_data["runtime_status"] = "unavailable"
    await _async_cancel_task(frontend_data.pop("event_loop_lag_heartbeat_task", None))
    unload_started_at = runtime_checkpoint("unload_entry.start", phase="unload")
    if unsubscribe := frontend_data.pop("coordinator_unsub", None):
        unsubscribe()
    if unsubscribe := frontend_data.pop("electricity_provider_price_unsub", None):
        unsubscribe()
    if unsubscribe := frontend_data.pop("eon_grid_unsub", None):
        unsubscribe()
    if unsubscribe := frontend_data.pop("solar_weather_unsub", None):
        unsubscribe()
    if cadence_audit_manager := frontend_data.pop("cadence_audit_manager", None):
        await cadence_audit_manager.async_shutdown()
    if frontend_data.pop("greenely_proof_service_registered", False):
        hass.services.async_remove("elrakning", "greenely_proof_provision")
    if hass.services.has_service(DOMAIN, "replay_artifact_publish"):
        hass.services.async_remove(DOMAIN, "replay_artifact_publish")
    if hass.services.has_service(DOMAIN, "replay_artifact_generate"):
        hass.services.async_remove(DOMAIN, "replay_artifact_generate")
    for unsubscribe in frontend_data.pop("replay_benchmark_event_unsubs", []):
        unsubscribe()
    for unsubscribe in frontend_data.pop("monthly_forecast_event_unsubs", []):
        unsubscribe()
    for unsubscribe in frontend_data.pop("forecast_view_cache_unsubs", []):
        unsubscribe()
    monthly_forecast_owner = frontend_data.pop("monthly_forecast_task_owner", None)
    monthly_forecast_task = monthly_forecast_owner.close() if monthly_forecast_owner else None
    frontend_data.pop("monthly_forecast_capture_task", None)
    frontend_data.pop("monthly_forecast_startup_task", None)
    if startup_task := monthly_forecast_task:
        try:
            await startup_task
        except asyncio.CancelledError:
            pass
    load_forecast_owner = frontend_data.pop("load_forecast_task_owner", None)
    load_forecast_task = load_forecast_owner.close() if load_forecast_owner else None
    frontend_data.pop("load_forecast_capture_task", None)
    frontend_data.pop("load_forecast_startup_task", None)
    if load_forecast_task:
        try:
            await load_forecast_task
        except asyncio.CancelledError:
            pass
    if refresh_task := frontend_data.pop("replay_benchmark_refresh_task", None):
        refresh_task.cancel()
    if replay_site_tasks := frontend_data.pop("replay_site_task_registry", None):
        await replay_site_tasks.async_close()
    if startup_task := frontend_data.pop("replay_artifact_startup_task", None):
        startup_task.cancel()
        try:
            await startup_task
        except asyncio.CancelledError:
            pass
    frontend_data.pop("config_entry", None)
    frontend_data.pop("app_shadow_client", None)
    if startup_task := frontend_data.pop("open_meteo_startup_task", None):
        startup_task.cancel()
        try:
            await startup_task
        except asyncio.CancelledError:
            pass
    if startup_task := frontend_data.pop("single_run_startup_task", None):
        startup_task.cancel()
        try:
            await startup_task
        except asyncio.CancelledError:
            pass
    if startup_task := frontend_data.pop("weather_startup_task", None):
        startup_task.cancel()
        try:
            await startup_task
        except asyncio.CancelledError:
            pass
    if startup_task := frontend_data.pop("history_warmup_task", None):
        startup_task.cancel()
        try:
            await startup_task
        except asyncio.CancelledError:
            pass
    if startup_task := frontend_data.pop("solar_evidence_startup_task", None):
        startup_task.cancel()
        try:
            await startup_task
        except asyncio.CancelledError:
            pass
    if canonical_collector := frontend_data.pop("canonical_collector", None):
        await canonical_collector.async_shutdown()
    if unsubscribe := frontend_data.pop("greenely_economics_unsub", None):
        unsubscribe()
    if greenely_economics := frontend_data.pop("greenely_invoice_economics", None):
        await greenely_economics.async_shutdown()
    if solar_weather_manager := frontend_data.pop("solar_weather_manager", None):
        await solar_weather_manager.async_shutdown()
    if solar_shadow_manager := frontend_data.pop("solar_shadow_manager", None):
        await solar_shadow_manager.async_shutdown()
    if solar_evidence_manager := frontend_data.pop("solar_evidence_manager", None):
        await solar_evidence_manager.async_shutdown()
    if solar_pvgis_manager := frontend_data.pop("solar_pvgis_manager", None):
        await solar_pvgis_manager.async_shutdown()
    if solar_open_meteo_manager := frontend_data.pop("solar_open_meteo_manager", None):
        await solar_open_meteo_manager.async_shutdown()
    if unsubscribe := frontend_data.pop("midnight_refresh_unsub", None):
        unsubscribe()
    if unsubscribe := frontend_data.pop("load_forecast_cadence_unsub", None):
        unsubscribe()
    if unsubscribe := frontend_data.pop("monthly_forecast_cadence_unsub", None):
        unsubscribe()
    if entry_coordinator is not None:
        entry_coordinator.cancel_midnight_recovery()
    if manager := frontend_data.pop("elhandel_manager", None):
        await manager.async_shutdown()
    if meter_manager := frontend_data.pop("meter_manager", None):
        await meter_manager.async_shutdown()
    if power_manager := frontend_data.pop("power_manager", None):
        await power_manager.async_shutdown()
    frontend_data.pop("site_identity_manager", None)
    if solar_forecast_manager := frontend_data.pop("solar_forecast_manager", None):
        await solar_forecast_manager.async_shutdown()
    if grid_manager := frontend_data.pop("grid_manager", None):
        await grid_manager.async_shutdown()
    if frontend.async_panel_exists(hass, PANEL_PATH):
        frontend.async_remove_panel(hass, PANEL_PATH)
    runtime_checkpoint("unload_entry.complete", phase="unload", started_at=unload_started_at)
    return True
