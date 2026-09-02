"""Bounded forecast snapshots and a non-user-visible solar candidate model."""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
from statistics import median
from typing import Any

from homeassistant.core import Event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util


STORE_KEY = "elrakning.solar_shadow"
UPDATE_EVENT = "elrakning_solar_shadow_update"
RETENTION_DAYS = 30
MAX_SNAPSHOTS = RETENTION_DAYS * 96 * 2
MIN_CAPTURE_INTERVAL_SECONDS = 15 * 60


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _bounded(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _copy_forecast(forecast: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "today_kwh", "remaining_today_kwh", "tomorrow_kwh", "this_hour_kwh",
        "next_hour_kwh", "power_now_kw", "power_next_hour_kw",
        "power_next_12_hours_kw", "power_next_24_hours_kw",
        "peak_time_today", "peak_time_tomorrow",
    )
    return {key: forecast.get(key) for key in fields}


def _copy_weather(weather: dict[str, Any]) -> dict[str, Any]:
    current = weather.get("current") if isinstance(weather.get("current"), dict) else {}
    current_keys = (
        "condition", "cloud_coverage", "cloud_total", "cloud_low", "cloud_medium",
        "cloud_high", "temperature", "precipitation", "precipitation_probability",
    )
    hourly = []
    for item in weather.get("hourly_forecast", []) if isinstance(weather.get("hourly_forecast"), list) else []:
        if not isinstance(item, dict):
            continue
        hourly.append({key: item[key] for key in (
            "datetime", "condition", "cloud_coverage", "cloud_total", "cloud_low",
            "cloud_medium", "cloud_high", "temperature", "precipitation",
            "precipitation_probability",
        ) if key in item})
    return {
        "available": bool(weather.get("available")),
        "status": weather.get("status"),
        "current": {key: current[key] for key in current_keys if key in current},
        "hourly_forecast": hourly,
    }


def _copy_sun(sun: dict[str, Any]) -> dict[str, Any]:
    return {key: sun.get(key) for key in (
        "available", "state", "elevation", "azimuth", "rising", "next_rising",
        "next_setting", "next_dawn", "next_dusk", "next_noon", "next_midnight",
    ) if key in sun}


def _cloud_factor(item: dict[str, Any]) -> float | None:
    weighted = []
    for key, weight in (("cloud_low", 0.25), ("cloud_medium", 0.55), ("cloud_high", 0.85)):
        value = _number(item.get(key))
        if value is not None:
            weighted.append((value, weight))
    if weighted:
        return sum(value * weight for value, weight in weighted) / sum(weight for _, weight in weighted)
    return _number(item.get("cloud_total", item.get("cloud_coverage")))


def _weather_adjustment(weather: dict[str, Any]) -> tuple[float, str, float]:
    """Return a conservative weather estimate and its confidence."""
    hourly = weather.get("hourly_forecast") if isinstance(weather.get("hourly_forecast"), list) else []
    clouds = [_cloud_factor(item) for item in hourly if isinstance(item, dict)]
    clouds = [value for value in clouds if value is not None]
    current = weather.get("current") if isinstance(weather.get("current"), dict) else {}
    if not clouds:
        cloud = _cloud_factor(current)
        if cloud is None:
            return 1.0, "weather_unavailable", 0.0
        clouds = [cloud]
        method = "total_cloud_fallback"
    else:
        method = "layered_hourly_cloud"
    cloud = _bounded(sum(clouds) / len(clouds), 0.0, 100.0) / 100
    precipitation = _number(current.get("precipitation_probability"))
    precipitation_factor = 0.0 if precipitation is None else _bounded(precipitation, 0.0, 100.0) / 100
    reduction = _bounded(cloud * 0.18 + precipitation_factor * 0.08, 0.0, 0.22)
    confidence = _bounded(0.35 + min(len(clouds), 12) / 24, 0.0, 0.85)
    return 1.0 - reduction, method, confidence


def _site_multiplier(calibration: list[dict[str, Any]] | None) -> tuple[float, str, float]:
    ratios = []
    for item in calibration or []:
        if not isinstance(item, dict) or item.get("quality") != "valid":
            continue
        raw = _number(item.get("raw_forecast_kwh"))
        actual = _number(item.get("actual_final_kwh"))
        if raw is not None and actual is not None and raw > 0:
            ratios.append(_bounded(actual / raw, 0.5, 1.5))
    if not ratios:
        return 1.0, "site_calibration_unavailable", 0.0
    ratio = _bounded(float(median(ratios)), 0.9, 1.1)
    strength = _bounded(len(ratios) / 8, 0.0, 1.0)
    return 1.0 + (ratio - 1.0) * 0.25 * strength, "previous_valid_days_median", strength


def build_candidate_forecast(
    raw_forecast_kwh: float | None,
    weather: dict[str, Any] | None = None,
    calibration: list[dict[str, Any]] | None = None,
    actual_so_far_kwh: float | None = None,
    expected_so_far_kwh: float | None = None,
    remaining_forecast_kwh: float | None = None,
) -> dict[str, Any]:
    """Build a deterministic, conservative shadow forecast."""
    raw = _number(raw_forecast_kwh)
    if raw is None or raw < 0:
        return {
            "candidate_forecast_kwh": None, "weather_component": 1.0,
            "site_bias": 1.0, "intraday_bias": 1.0, "confidence": 0.0,
            "reasons": ["raw_forecast_unavailable"],
        }
    weather_factor, weather_method, weather_confidence = _weather_adjustment(weather or {})
    site_factor, site_method, site_confidence = _site_multiplier(calibration)
    weather_candidate = raw * weather_factor
    blended = raw * 0.8 + weather_candidate * 0.2
    calibrated = blended * (1.0 + (site_factor - 1.0) * 0.5)
    intraday_factor = 1.0
    reasons = [weather_method, site_method]
    actual = _number(actual_so_far_kwh)
    expected = _number(expected_so_far_kwh)
    remaining = _number(remaining_forecast_kwh)
    if actual is not None and expected is not None and remaining is not None and expected >= 1 and remaining >= 0:
        intraday_factor = _bounded(actual / expected, 0.75, 1.25)
        completed = max(0.0, calibrated - remaining)
        calibrated = completed + remaining * (0.85 + 0.15 * intraday_factor)
        reasons.append("bounded_actual_so_far")
    confidence = _bounded(0.25 + weather_confidence * 0.35 + site_confidence * 0.25 + (0.15 if intraday_factor != 1.0 else 0), 0.0, 0.95)
    return {
        "candidate_forecast_kwh": max(0.0, calibrated),
        "weather_component": weather_factor,
        "site_bias": site_factor,
        "intraday_bias": intraday_factor,
        "confidence": confidence,
        "reasons": reasons,
    }


class SolarShadowManager:
    """Persist immutable forecast inputs and candidate outputs for later replay."""

    def __init__(self, hass, forecast_manager, weather_manager, power_manager, pvgis_manager=None) -> None:
        self.hass = hass
        self.forecast_manager = forecast_manager
        self.weather_manager = weather_manager
        self.power_manager = power_manager
        self.pvgis_manager = pvgis_manager
        self.store = Store(hass, 1, STORE_KEY)
        self._snapshots: list[dict[str, Any]] = []
        self._last_capture_at = None
        self._last_input_signature = None
        self._capture_lock = None
        self._last_enrichment_date = None
        self._frames = {"forecast": {}, "weather": {}, "sun": {}, "pvgis": {}}
        self._unsubs = [
            hass.bus.async_listen("elrakning_solar_forecast_update", self._async_trigger),
            hass.bus.async_listen("elrakning_solar_weather_update", self._async_trigger),
            hass.bus.async_listen("elrakning_power_update", self._async_trigger),
        ]

    async def async_load(self) -> None:
        cached = await self.store.async_load()
        if isinstance(cached, dict) and isinstance(cached.get("snapshots"), list):
            self._snapshots = [item for item in cached["snapshots"] if isinstance(item, dict)]
            frames = cached.get("frames")
            if isinstance(frames, dict):
                self._frames = {
                    kind: dict(frames.get(kind, {})) if isinstance(frames.get(kind), dict) else {}
                    for kind in ("forecast", "weather", "sun")
                }
        await self._capture("startup")

    async def async_shutdown(self) -> None:
        for unsubscribe in self._unsubs:
            unsubscribe()
        self._unsubs.clear()

    async def async_enrich_completed_day(self, target_date: str, actual_final_kwh: float, quality: str) -> int:
        """Attach ground truth to snapshots without changing captured inputs."""
        actual = _number(actual_final_kwh)
        if actual is None or quality not in {"valid", "insufficient_data", "possible_curtailment", "possible_outage", "unknown_quality"}:
            return 0
        changed = 0
        for snapshot in self._snapshots:
            if snapshot.get("target_date") != target_date:
                continue
            materialized = self._materialize(snapshot)
            raw = _number((materialized.get("forecast_solar") or {}).get("today_kwh"))
            candidate = _number((snapshot.get("model") or {}).get("candidate_forecast_kwh"))
            snapshot["actual_final_kwh"] = actual
            snapshot["raw_error_kwh"] = abs(actual - raw) if raw is not None else None
            snapshot["candidate_error_kwh"] = abs(actual - candidate) if candidate is not None else None
            snapshot["quality"] = quality
            changed += 1
        if changed:
            await self.store.async_save({"frames": self._frames, "snapshots": self._snapshots})
            self.hass.bus.async_fire(UPDATE_EVENT)
        return changed

    async def _async_trigger(self, _event: Event) -> None:
        await self._capture("event")

    async def _capture(self, trigger: str) -> None:
        if self._capture_lock is None:
            import asyncio
            self._capture_lock = asyncio.Lock()
        async with self._capture_lock:
            now = dt_util.now()
            forecast = self.forecast_manager.public_state()
            weather = self.weather_manager.public_state()
            sun = self._sun_state()
            pvgis_manager = getattr(self, "pvgis_manager", None)
            pvgis_context = pvgis_manager.public_state() if pvgis_manager else {"available": False}
            signature = repr((forecast, weather, pvgis_context.get("installation", {}).get("fingerprint")))
            if self._last_capture_at is not None and (
                now - self._last_capture_at
            ).total_seconds() < MIN_CAPTURE_INTERVAL_SECONDS:
                return
            actual_so_far, expected_so_far, remaining = await self._actual_context()
            today = dt_util.as_local(now).date()
            if self._last_enrichment_date != today:
                await self._enrich_completed_days(today)
                self._last_enrichment_date = today
            targets = [(today, "intraday"), (today + timedelta(days=1), "day_ahead")]
            added = False
            for target_date, capture_type in targets:
                raw = forecast.get("today_kwh" if target_date == today else "tomorrow_kwh")
                candidate = build_candidate_forecast(
                    raw, weather, self._calibration_before(target_date),
                    actual_so_far if target_date == today else None,
                    expected_so_far if target_date == today else None,
                    remaining if target_date == today else None,
                )
                frame_ids = {
                    "forecast": self._store_frame("forecast", _copy_forecast(forecast)),
                    "weather": self._store_frame("weather", _copy_weather(weather)),
                    "sun": self._store_frame("sun", _copy_sun(sun)),
                }
                pvgis = pvgis_manager.public_state(target_date) if pvgis_manager else {"available": False}
                if pvgis.get("available"):
                    frame_ids["pvgis"] = self._store_frame("pvgis", pvgis)
                snapshot = {
                    "timestamp": now.isoformat(),
                    "target_date": target_date.isoformat(),
                    "capture_type": capture_type,
                    "forecast_frame": frame_ids["forecast"],
                    "weather_frame": frame_ids["weather"],
                    "sun_frame": frame_ids["sun"],
                    "pvgis_frame": frame_ids.get("pvgis"),
                    "pv": {"actual_so_far_kwh": actual_so_far if target_date == today else None},
                    "model": {**candidate, "input_availability": {
                        "forecast": raw is not None,
                        "weather": bool(weather.get("available")),
                        "actual_so_far": actual_so_far is not None if target_date == today else False,
                    }},
                    "actual_final_kwh": None,
                    "raw_error_kwh": None,
                    "candidate_error_kwh": None,
                    "quality": "unknown_quality",
                    "trigger": trigger,
                }
                if not self._is_duplicate(snapshot):
                    self._snapshots.append(snapshot)
                    added = True
            self._trim(today)
            if added:
                self._last_capture_at = now
                self._last_input_signature = signature
                await self.store.async_save({"frames": self._frames, "snapshots": self._snapshots})
                self.hass.bus.async_fire(UPDATE_EVENT)

    def _store_frame(self, kind: str, payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        frame_id = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
        self._frames.setdefault(kind, {}).setdefault(frame_id, payload)
        return frame_id

    def _materialize(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        result = dict(snapshot)
        if "forecast_frame" in snapshot:
            result["forecast_solar"] = dict(self._frames["forecast"].get(snapshot["forecast_frame"], {}))
            result["smhi"] = dict(self._frames["weather"].get(snapshot.get("weather_frame"), {}))
            result["sun"] = dict(self._frames["sun"].get(snapshot.get("sun_frame"), {}))
            result["pvgis"] = dict(self._frames.get("pvgis", {}).get(snapshot.get("pvgis_frame"), {}))
        return result

    async def _enrich_completed_days(self, today: date) -> None:
        if not self._snapshots:
            return
        try:
            history = await self.power_manager.async_history(7)
            points = history.get("series", {}).get("solar", {}).get("points", [])
        except Exception:
            return
        totals: dict[str, float] = {}
        points_by_day: dict[date, list[tuple[Any, float]]] = {}
        parsed = []
        for point in points if isinstance(points, list) else []:
            timestamp = dt_util.parse_datetime(point.get("timestamp")) if isinstance(point, dict) else None
            value = _number(point.get("value_kw")) if isinstance(point, dict) else None
            if timestamp is not None and value is not None:
                local_timestamp = dt_util.as_local(timestamp)
                parsed.append((local_timestamp, value))
                points_by_day.setdefault(local_timestamp.date(), []).append((local_timestamp, value))
        parsed.sort(key=lambda item: item[0])
        for (left_time, left_value), (right_time, right_value) in zip(parsed, parsed[1:]):
            day = left_time.date()
            if day >= today:
                continue
            day_end = left_time.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            segment_end = min(right_time, day_end)
            duration = (segment_end - left_time).total_seconds() / 3600
            if 0 < duration <= 1:
                totals[day.isoformat()] = totals.get(day.isoformat(), 0.0) + (left_value + right_value) / 2 * duration
        for target_date, actual in totals.items():
            quality = "valid" if _day_has_complete_history(points_by_day.get(date.fromisoformat(target_date), []), date.fromisoformat(target_date)) else "insufficient_data"
            await self.async_enrich_completed_day(target_date, actual, quality)

    async def _actual_context(self) -> tuple[float | None, float | None, float | None]:
        try:
            history = await self.power_manager.async_history(1)
            analysis = history.get("solar_analysis", {}).get("intraday", {})
            return (
                _number(analysis.get("actual_so_far_kwh")),
                _number(analysis.get("raw_expected_so_far_kwh")),
                _number(analysis.get("raw_day_forecast_kwh")) - _number(analysis.get("raw_expected_so_far_kwh"))
                if _number(analysis.get("raw_day_forecast_kwh")) is not None and _number(analysis.get("raw_expected_so_far_kwh")) is not None else None,
            )
        except Exception:
            return None, None, None

    def _sun_state(self) -> dict[str, Any]:
        state = self.hass.states.get("sun.sun")
        if state is None:
            return {"available": False}
        attributes = getattr(state, "attributes", {})
        return {"available": True, "state": getattr(state, "state", None), **{
            key: attributes.get(key) for key in (
                "elevation", "azimuth", "rising", "next_rising", "next_setting",
                "next_dawn", "next_dusk", "next_noon", "next_midnight",
            ) if attributes.get(key) is not None
        }}

    def _calibration_before(self, target_date: date) -> list[dict[str, Any]]:
        return [item for item in self._snapshots if item.get("quality") == "valid" and item.get("target_date", "") < target_date.isoformat()]

    def _public_day_records(self) -> list[dict[str, Any]]:
        """Expose raw baselines without implying that they are shadow captures."""
        forecast_state = self.forecast_manager.public_state()
        today = dt_util.as_local(dt_util.now()).date()
        remaining_today = _number(forecast_state.get("remaining_today_kwh"))
        candidate_by_date: dict[str, float] = {}
        replay_by_date: dict[str, float] = {}
        actual_by_date: set[str] = set()
        metadata_by_date: dict[str, dict[str, Any]] = {}
        for snapshot in self._snapshots:
            target_date = snapshot.get("target_date")
            if not isinstance(target_date, str):
                continue
            candidate = _number((snapshot.get("model") or {}).get("candidate_forecast_kwh"))
            if candidate is not None:
                replay_by_date[target_date] = candidate
            snapshot_date = date.fromisoformat(target_date) if len(target_date) == 10 else None
            captured_at = dt_util.parse_datetime(snapshot.get("timestamp"))
            if (
                candidate is not None
                and snapshot.get("capture_type") == "day_ahead"
                and snapshot_date is not None
                and captured_at is not None
                and dt_util.as_local(captured_at).date() < snapshot_date
            ):
                candidate_by_date[target_date] = candidate
            actual_final = _number(snapshot.get("actual_final_kwh"))
            actual_so_far = _number((snapshot.get("pv") or {}).get("actual_so_far_kwh"))
            if actual_final is not None or (
                actual_so_far is not None
                and snapshot_date is not None
                and (
                    snapshot_date < today
                    or (snapshot_date == today and remaining_today is not None and remaining_today <= 0.001)
                )
            ):
                actual_by_date.add(target_date)
            metadata_by_date[target_date] = {
                "capture_type": snapshot.get("capture_type"),
                "actual_final_kwh": snapshot.get("actual_final_kwh"),
                "quality": snapshot.get("quality"),
            }
        records = {
            target_date: {
                "target_date": target_date,
                "raw_forecast_kwh": value,
                "candidate_forecast_kwh": None,
                "candidate_replay_available": False,
                "candidate_comparison_available": False,
                "shadow_data_status": "historical_inputs_missing",
            }
            for target_date, value in (forecast_state.get("baselines") or {}).items()
            if isinstance(target_date, str)
        }
        for snapshot in self._snapshots:
            target_date = snapshot.get("target_date")
            if not isinstance(target_date, str):
                continue
            materialized = self._materialize(snapshot)
            forecast = materialized.get("forecast_solar") or {}
            raw_key = "tomorrow_kwh" if snapshot.get("capture_type") == "day_ahead" else "today_kwh"
            raw = _number(forecast.get(raw_key))
            record = records.setdefault(target_date, {"target_date": target_date})
            if raw is not None:
                record["raw_forecast_kwh"] = raw
        for target_date, record in records.items():
            candidate = candidate_by_date.get(target_date, replay_by_date.get(target_date))
            comparison_available = target_date in candidate_by_date and target_date in actual_by_date
            record.update({
                "candidate_forecast_kwh": candidate,
                "candidate_replay_available": candidate is not None,
                "candidate_comparison_available": comparison_available,
                "shadow_data_status": "complete" if comparison_available else (
                    "captured_without_candidate" if candidate is not None else record.get("shadow_data_status", "historical_inputs_missing")
                ),
                **metadata_by_date.get(target_date, {}),
            })
        return [records[key] for key in sorted(records)]

    def _is_duplicate(self, snapshot: dict[str, Any]) -> bool:
        key = (snapshot.get("target_date"), snapshot.get("forecast_frame"), snapshot.get("weather_frame"), snapshot.get("sun_frame"), snapshot.get("pvgis_frame"), snapshot.get("pv"))
        return any((item.get("target_date"), item.get("forecast_frame"), item.get("weather_frame"), item.get("sun_frame"), item.get("pvgis_frame"), item.get("pv")) == key for item in self._snapshots[-4:])

    def _trim(self, today: date) -> None:
        minimum = today - timedelta(days=RETENTION_DAYS - 1)
        self._snapshots = [item for item in self._snapshots if item.get("target_date", "") >= minimum.isoformat()]
        self._snapshots = self._snapshots[-MAX_SNAPSHOTS:]
        for kind in ("forecast", "weather", "sun", "pvgis"):
            referenced = {item.get(f"{kind}_frame") for item in self._snapshots}
            self._frames[kind] = {key: value for key, value in self._frames.get(kind, {}).items() if key in referenced}

    def public_state(self) -> dict[str, Any]:
        return {
            "available": True,
            "store_key": STORE_KEY,
            "retention_days": RETENTION_DAYS,
            "snapshot_count": len(self._snapshots),
            "frames": {kind: dict(values) for kind, values in self._frames.items()},
            "snapshots": [self._materialize(item) for item in self._snapshots],
            "days": self._public_day_records(),
        }


def _day_has_complete_history(points: list[tuple[Any, float]], target_date: date) -> bool:
    if len(points) < 3:
        return False
    points = sorted(points, key=lambda item: item[0])
    day_start = points[0][0].replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    if points[0][0] > day_start + timedelta(hours=1) or points[-1][0] < day_end - timedelta(hours=1):
        return False
    gaps = [(right[0] - left[0]).total_seconds() / 3600 for left, right in zip(points, points[1:])]
    return points[0][0].date() == target_date and max(gaps, default=999) <= 2
