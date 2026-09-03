"""Cached PVGIS physical site-potential reference."""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from typing import Any

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

try:
    from .site_context import async_load_site_store
except ImportError:  # pragma: no cover - supports direct helper-module loading
    async def async_load_site_store(hass, store_key, version, site_id, legacy_data=None):
        """Load a site store when this module is tested outside its package."""
        store = Store(hass, version, f"{store_key}.{site_id}")
        cached = await store.async_load()
        if cached is None and isinstance(legacy_data, dict):
            await store.async_save(legacy_data)
            cached = legacy_data
        return store, cached if isinstance(cached, dict) else None


PVGIS_API_VERSION = "6"
PVGIS_SOURCE = "jrc_pvgis_power_broadband_multiple_surfaces"
PVGIS_ENDPOINT = "https://photovoltaic-geographic-information-system.ec.europa.eu/api/v6/power/broadband-multiple-surfaces"
PVGIS_YEAR = 2024
STORE_KEY = "elrakning.solar_pvgis"
_CACHE_VERSION = 1


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _sections(power_state: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = power_state.get("solar_array_metadata")
    entities = power_state.get("solar_entities")
    if not isinstance(metadata, dict) or not isinstance(entities, list):
        return []
    grouped: dict[tuple[float, float], dict[str, Any]] = {}
    for entity_id in entities:
        item = metadata.get(entity_id)
        if not isinstance(item, dict):
            continue
        capacity = _number(item.get("capacity_kwp"))
        tilt = _number(item.get("tilt_deg"))
        azimuth = _number(item.get("azimuth_deg"))
        if capacity is None or capacity <= 0 or tilt is None or azimuth is None:
            continue
        key = (round(tilt, 6), round(azimuth, 6))
        section = grouped.setdefault(key, {
            "source_strings": [], "peak_power_kwp": 0.0,
            "tilt_deg": tilt, "azimuth_deg": azimuth,
        })
        section["source_strings"].append(entity_id)
        section["peak_power_kwp"] += capacity
    return [grouped[key] for key in sorted(grouped)]


def build_installation(hass, power_state: dict[str, Any]) -> dict[str, Any] | None:
    """Build PVGIS sections from the existing PV-card configuration."""
    latitude = _number(getattr(hass.config, "latitude", None))
    longitude = _number(getattr(hass.config, "longitude", None))
    sections = _sections(power_state)
    if latitude is None or longitude is None or not sections:
        return None
    result = {
        "latitude": latitude,
        "longitude": longitude,
        "sections": sections,
        "total_peak_power_kwp": sum(item["peak_power_kwp"] for item in sections),
        "optional_inputs": {
            "photovoltaic_module": "PVGIS default (installation technology not configured)",
            "system_loss": "PVGIS default (installation loss not configured)",
            "horizon": "PVGIS digital horizon",
        },
    }
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"))
    result["fingerprint"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return result


def normalize_response(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize the PVGIS 6 hourly power response into a compact profile."""
    timestamps = payload.get("timestamps")
    powers = payload.get("power")
    if not isinstance(timestamps, list) or not isinstance(powers, list) or len(timestamps) != len(powers):
        return None
    buckets: dict[tuple[int, int], list[float]] = {}
    for timestamp, power in zip(timestamps, powers):
        value = _number(power)
        if value is None or not isinstance(timestamp, str):
            continue
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        buckets.setdefault((parsed.month, parsed.hour), []).append(max(0.0, value) / 1000.0)
    if len(buckets) < 12 * 12:
        return None
    monthly_profile = {
        str(month): {
            str(hour): sum(values) / len(values)
            for (bucket_month, hour), values in buckets.items()
            if bucket_month == month
        }
        for month in range(1, 13)
    }
    return {
        "unit": "kW",
        "reference_year": PVGIS_YEAR,
        "hourly_profile": monthly_profile,
    }


def profile_for_date(profile: dict[str, Any], target_date: date) -> dict[str, Any] | None:
    monthly = profile.get("hourly_profile") if isinstance(profile, dict) else None
    hours = monthly.get(str(target_date.month)) if isinstance(monthly, dict) else None
    if not isinstance(hours, dict) or not all(str(hour) in hours for hour in range(24)):
        return None
    values = [float(hours[str(hour)]) for hour in range(24)]
    return {
        "target_date": target_date.isoformat(),
        "unit": "kW",
        "hourly_profile": values,
        "potential_kwh": sum(values),
        "reference_year": profile.get("reference_year"),
    }


class SolarPvgisManager:
    """Fetch and cache a compact, installation-specific PVGIS reference."""

    def __init__(self, hass, power_manager) -> None:
        self.hass = hass
        self.power_manager = power_manager
        self.store = Store(hass, 1, STORE_KEY)
        self._state: dict[str, Any] = {"available": False, "source": PVGIS_SOURCE, "api_version": PVGIS_API_VERSION}
        self._profile: dict[str, Any] | None = None
        self._site_id: str | None = None

    async def async_load(self) -> None:
        power_state = await self.power_manager.async_state()
        installation = build_installation(self.hass, power_state)
        if installation is None:
            self._state = {"available": False, "source": PVGIS_SOURCE, "api_version": PVGIS_API_VERSION, "reason": "installation_inputs_missing"}
            return
        cached = await self.store.async_load()
        if (
            isinstance(cached, dict)
            and cached.get("cache_version") == _CACHE_VERSION
            and cached.get("installation", {}).get("fingerprint") == installation["fingerprint"]
            and isinstance(cached.get("profile"), dict)
        ):
            self._profile = cached["profile"]
            self._state = {**cached.get("state", {}), "available": True, "installation": installation}
            return
        await self._async_fetch(installation)

    def discovered_binding(self) -> dict[str, Any] | None:
        """Return the current installation fingerprint for explicit site binding."""
        installation = self._state.get("installation")
        if not isinstance(installation, dict) or not installation.get("fingerprint"):
            return None
        return {
            "source": PVGIS_SOURCE,
            "installation_fingerprint": installation["fingerprint"],
        }

    async def async_apply_site_context(self, site_id: str, binding: dict[str, Any] | None) -> None:
        """Switch the PVGIS cache to one site namespace."""
        self._site_id = site_id if isinstance(binding, dict) else None
        if self._site_id is None:
            self._profile = None
            self._state = {"available": False, "source": PVGIS_SOURCE, "api_version": PVGIS_API_VERSION, "reason": "site_unconfigured"}
            return
        legacy = {"cache_version": _CACHE_VERSION, "state": self._state, "installation": self._state.get("installation"), "profile": self._profile}
        self.store, cached = await async_load_site_store(self.hass, STORE_KEY, 1, self._site_id, legacy)
        if not cached:
            return
        self._profile = cached.get("profile") if isinstance(cached.get("profile"), dict) else None
        self._state = cached.get("state") if isinstance(cached.get("state"), dict) else self._state
        self._state["site_id"] = self._site_id

    async def _async_fetch(self, installation: dict[str, Any]) -> None:
        params: list[tuple[str, str]] = [
            ("latitude", str(installation["latitude"])),
            ("longitude", str(installation["longitude"])),
            ("start_time", f"{PVGIS_YEAR}-01-01T00:00:00"),
            ("end_time", f"{PVGIS_YEAR}-12-31T23:00:00"),
            ("frequency", "Hourly"), ("timezone", "UTC"),
            ("outputformat", "json"), ("verbose", "1"),
        ]
        for section in installation["sections"]:
            params.extend([
                ("surface_orientation", str(section["azimuth_deg"])),
                ("surface_tilt", str(section["tilt_deg"])),
                ("peak-power", str(section["peak_power_kwp"])),
            ])
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(PVGIS_ENDPOINT, params=params, timeout=30) as response:
                if response.status != 200:
                    raise ValueError(f"http_{response.status}")
                payload = await response.json()
            profile = normalize_response(payload)
            if profile is None:
                raise ValueError("invalid_response")
        except Exception as err:
            self._state = {
                "available": False, "source": PVGIS_SOURCE, "api_version": PVGIS_API_VERSION,
                "installation": installation, "reason": "fetch_failed", "error_type": type(err).__name__,
            }
            return
        self._profile = profile
        fetched_at = dt_util.now().isoformat()
        state = {
            "available": True, "source": PVGIS_SOURCE, "api_version": PVGIS_API_VERSION,
            "fetched_at": fetched_at, "installation": installation,
        }
        self._state = state
        await self.store.async_save({"cache_version": _CACHE_VERSION, "state": state, "installation": installation, "profile": profile})

    async def async_refresh_for_power_state(self, power_state: dict[str, Any]) -> None:
        """Refresh only when the PV-card installation fingerprint changes."""
        if self._site_id is None:
            return
        installation = build_installation(self.hass, power_state)
        current = self._state.get("installation", {}).get("fingerprint")
        if installation is None:
            self._profile = None
            self._state = {"available": False, "source": PVGIS_SOURCE, "api_version": PVGIS_API_VERSION, "reason": "installation_inputs_missing"}
            return
        if installation["fingerprint"] != current:
            await self._async_fetch(installation)

    def public_state(self, target_date: date | None = None) -> dict[str, Any]:
        result = dict(self._state)
        if self._profile is not None:
            result["profile"] = profile_for_date(self._profile, target_date or dt_util.as_local(dt_util.now()).date())
        return result

    async def async_shutdown(self) -> None:
        return None
