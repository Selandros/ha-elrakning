"""Cached Open-Meteo tilted-plane irradiance forecasts for solar shadowing."""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
from typing import Any

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .solar_pvgis import build_installation


OPEN_METEO_SOURCE = "open_meteo_global_tilted_irradiance"
OPEN_METEO_MODEL = "metno"
OPEN_METEO_ENDPOINT = "https://api.open-meteo.com/v1/metno"
STORE_KEY = "elrakning.solar_open_meteo"
_CACHE_VERSION = 1
_CACHE_TTL = timedelta(hours=1)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _parse_fetched_at(value: Any):
    """Return a parsed cache timestamp, or a cache miss for invalid input."""
    if not isinstance(value, str):
        return None
    try:
        return dt_util.parse_datetime(value)
    except (TypeError, ValueError):
        return None


def compass_to_open_meteo_azimuth(compass_azimuth: Any) -> float | None:
    """Convert compass azimuth (north=0, clockwise) to Open-Meteo azimuth."""
    value = _number(compass_azimuth)
    if value is None:
        return None
    converted = (value - 180.0) % 360.0
    return converted - 360.0 if converted > 180.0 else converted


def _parse_hourly(payload: dict[str, Any], section: dict[str, Any]) -> dict[str, Any] | None:
    hourly = payload.get("hourly")
    times = hourly.get("time") if isinstance(hourly, dict) else None
    values = hourly.get("global_tilted_irradiance") if isinstance(hourly, dict) else None
    if not isinstance(times, list) or not isinstance(values, list) or len(times) != len(values):
        return None
    points = []
    irradiance_kwh_m2 = 0.0
    for timestamp, value in zip(times, values):
        numeric = _number(value)
        if not isinstance(timestamp, str) or numeric is None:
            continue
        numeric = max(0.0, numeric)
        points.append({"timestamp": timestamp, "gti_w_m2": numeric})
        irradiance_kwh_m2 += numeric / 1000.0
    if not points:
        return None
    return {
        "source_strings": list(section["source_strings"]),
        "peak_power_kwp": section["peak_power_kwp"],
        "tilt_deg": section["tilt_deg"],
        "azimuth_deg": section["azimuth_deg"],
        "open_meteo_azimuth_deg": compass_to_open_meteo_azimuth(section["azimuth_deg"]),
        "hourly": points,
        "irradiance_kwh_m2": irradiance_kwh_m2,
        "potential_dc_kwh": irradiance_kwh_m2 * section["peak_power_kwp"],
        "api_metadata": {
            key: payload[key] for key in ("model", "timezone", "utc_offset_seconds", "generationtime_ms")
            if payload.get(key) is not None
        },
    }


def _frame_id(frame: dict[str, Any]) -> str:
    encoded = json.dumps(frame, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


class SolarOpenMeteoManager:
    """Fetch and cache site-specific, tilted-plane irradiance forecasts."""

    def __init__(self, hass, power_manager) -> None:
        self.hass = hass
        self.power_manager = power_manager
        self.store = Store(hass, 1, STORE_KEY)
        self._state: dict[str, Any] = {"available": False, "source": OPEN_METEO_SOURCE, "model": OPEN_METEO_MODEL}
        self._installation: dict[str, Any] | None = None
        self._frame: dict[str, Any] | None = None
        self._frame_id: str | None = None

    async def async_load(self) -> None:
        try:
            cached = await self.store.async_load()
        except Exception:
            cached = None
        if isinstance(cached, dict) and cached.get("cache_version") == _CACHE_VERSION:
            self._installation = cached.get("installation") if isinstance(cached.get("installation"), dict) else None
            self._frame = cached.get("frame") if isinstance(cached.get("frame"), dict) else None
            self._frame_id = cached.get("frame_id") if isinstance(cached.get("frame_id"), str) else None
            self._state = cached.get("state") if isinstance(cached.get("state"), dict) else self._state
        try:
            await self.async_refresh_for_power_state(await self.power_manager.async_state())
        except Exception:
            self._state = {
                "available": False,
                "source": OPEN_METEO_SOURCE,
                "model": OPEN_METEO_MODEL,
                "reason": "startup_unavailable",
            }

    async def async_refresh_for_power_state(self, power_state: dict[str, Any]) -> None:
        installation = build_installation(self.hass, power_state)
        if installation is None:
            self._installation = None
            self._frame = None
            self._frame_id = None
            self._state = {"available": False, "source": OPEN_METEO_SOURCE, "model": OPEN_METEO_MODEL, "reason": "installation_inputs_missing"}
            return
        fetched_at = _parse_fetched_at(self._state.get("fetched_at"))
        if (
            self._installation and self._installation.get("fingerprint") == installation["fingerprint"]
            and self._frame and fetched_at and dt_util.now() - fetched_at < _CACHE_TTL
        ):
            return
        await self._async_fetch(installation)

    async def _async_fetch(self, installation: dict[str, Any]) -> None:
        sections = []
        session = async_get_clientsession(self.hass)
        for section in installation["sections"]:
            params = {
                "latitude": str(installation["latitude"]),
                "longitude": str(installation["longitude"]),
                "hourly": "global_tilted_irradiance",
                "tilt": str(section["tilt_deg"]),
                "azimuth": str(compass_to_open_meteo_azimuth(section["azimuth_deg"])),
                "timezone": "auto",
                "forecast_days": "3",
            }
            try:
                async with session.get(OPEN_METEO_ENDPOINT, params=params, timeout=30) as response:
                    if response.status != 200:
                        raise ValueError(f"http_{response.status}")
                    payload = await response.json()
                normalized = _parse_hourly(payload, section)
                if normalized is None:
                    raise ValueError("invalid_response")
                sections.append(normalized)
            except Exception as err:
                self._state = {
                    "available": False, "source": OPEN_METEO_SOURCE, "model": OPEN_METEO_MODEL,
                    "installation": installation, "reason": "fetch_failed", "error_type": type(err).__name__,
                }
                return
        fetched_at = dt_util.now().isoformat()
        frame = {
            "provider": "open-meteo",
            "source": OPEN_METEO_SOURCE,
            "model": OPEN_METEO_MODEL,
            "fetched_at": fetched_at,
            "timezone": "auto",
            "installation_fingerprint": installation["fingerprint"],
            "sections": sections,
            "api_metadata": sections[0].get("api_metadata", {}) if sections else {},
            "energy_semantics": "unadjusted_dc_potential",
        }
        self._installation = installation
        self._frame = frame
        self._frame_id = _frame_id(frame)
        self._state = {
            "available": True, "source": OPEN_METEO_SOURCE, "provider": "open-meteo",
            "model": OPEN_METEO_MODEL, "fetched_at": fetched_at,
            "frame_id": self._frame_id, "installation": installation,
            "energy_semantics": "unadjusted_dc_potential",
        }
        await self.store.async_save({
            "cache_version": _CACHE_VERSION, "state": self._state,
            "installation": installation, "frame_id": self._frame_id, "frame": frame,
        })

    def public_state(self, target_date: date | None = None) -> dict[str, Any]:
        result = dict(self._state)
        if self._frame is None:
            return result
        wanted = target_date or dt_util.as_local(dt_util.now()).date()
        sections = []
        for section in self._frame.get("sections", []):
            points = [item for item in section.get("hourly", []) if isinstance(item, dict) and isinstance(item.get("timestamp"), str)]
            selected = []
            for item in points:
                if item["timestamp"][:10] == wanted.isoformat():
                    selected.append(dict(item))
            if selected:
                energy = sum(item["gti_w_m2"] for item in selected) / 1000.0
                sections.append({
                    "source_strings": list(section["source_strings"]),
                    "peak_power_kwp": section["peak_power_kwp"],
                    "tilt_deg": section["tilt_deg"],
                    "azimuth_deg": section["azimuth_deg"],
                    "open_meteo_azimuth_deg": section["open_meteo_azimuth_deg"],
                    "hourly": selected,
                    "irradiance_kwh_m2": energy,
                    "potential_dc_kwh": energy * section["peak_power_kwp"],
                })
        result["profile"] = {
            "target_date": wanted.isoformat(),
            "frame_id": self._frame_id,
            "sections": sections,
            "potential_dc_kwh": sum(item["potential_dc_kwh"] for item in sections),
            "energy_semantics": "unadjusted_dc_potential",
        }
        return result

    async def async_shutdown(self) -> None:
        return None
