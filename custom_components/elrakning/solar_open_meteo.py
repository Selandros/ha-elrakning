"""Cached Open-Meteo tilted-plane irradiance forecasts for solar shadowing."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .site_context import async_load_site_store

from .solar_pvgis import _sections, build_installation


OPEN_METEO_SOURCE = "open_meteo_global_tilted_irradiance"
OPEN_METEO_MODEL = "metno"
OPEN_METEO_ENDPOINT = "https://api.open-meteo.com/v1/metno"
OPEN_METEO_DATASET = "open_meteo.manager_forecast.v1"
OPEN_METEO_CONTRACT_VERSION = 1
OPEN_METEO_ADAPTER_VERSION = 1
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


def _valid_timezone(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        ZoneInfo(value)
    except Exception:
        return None
    return value


def _location_fingerprint(latitude: float, longitude: float, timezone_name: str) -> str:
    payload = {"latitude": latitude, "longitude": longitude, "timezone": timezone_name}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _request_identity(target: dict[str, Any]) -> dict[str, Any]:
    """Return only source-defining request semantics."""
    return {
        "dataset": OPEN_METEO_DATASET,
        "adapter_contract_version": OPEN_METEO_CONTRACT_VERSION,
        "adapter_version": OPEN_METEO_ADAPTER_VERSION,
        "endpoint": OPEN_METEO_ENDPOINT,
        "provider": "open-meteo",
        "model": OPEN_METEO_MODEL,
        "variables": ["global_tilted_irradiance"],
        "forecast_days": 3,
        "timezone_request": "auto",
        "site_timezone": target["timezone"],
        "site_id": target["site_id"],
        "latitude": target["latitude"],
        "longitude": target["longitude"],
        "tilt_deg": target["tilt_deg"],
        "open_meteo_azimuth_deg": target["open_meteo_azimuth_deg"],
    }


def section_request_fingerprint(target: dict[str, Any]) -> str:
    encoded = json.dumps(_request_identity(target), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def source_generation_id(target: dict[str, Any]) -> str:
    return "om-" + hashlib.sha256(
        json.dumps(_request_identity(target), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]


def build_open_meteo_targets(site_configs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Build immutable-capture targets from a site configuration snapshot."""
    targets: list[dict[str, Any]] = []
    for site_id in sorted(site_configs):
        config = site_configs[site_id]
        if config.get("collection_enabled", True) is not True:
            continue
        location = config.get("location")
        if not isinstance(location, dict) or location.get("verification_state") != "verified":
            continue
        latitude = _number(location.get("latitude"))
        longitude = _number(location.get("longitude"))
        timezone_name = _valid_timezone(location.get("timezone"))
        if (
            not isinstance(location.get("provenance"), str)
            or not location["provenance"].strip()
            or not isinstance(location.get("location_fingerprint"), str)
            or location["location_fingerprint"] != _location_fingerprint(latitude, longitude, timezone_name)
        ):
            continue
        bindings = config.get("bindings")
        binding = bindings.get("open_meteo") if isinstance(bindings, dict) else None
        if (
            latitude is None
            or longitude is None
            or timezone_name is None
            or not isinstance(binding, dict)
            or binding.get("source") != OPEN_METEO_SOURCE
        ):
            continue
        sections = _sections(config.get("power", {}))
        for section in sections:
            azimuth = compass_to_open_meteo_azimuth(section.get("azimuth_deg"))
            if azimuth is None:
                continue
            target = {
                "site_id": site_id,
                "latitude": latitude,
                "longitude": longitude,
                "timezone": timezone_name,
                "tilt_deg": round(float(section["tilt_deg"]), 6),
                "open_meteo_azimuth_deg": round(float(azimuth), 6),
                "source_strings": sorted(section.get("source_strings", [])),
                "peak_power_kwp": float(section["peak_power_kwp"]),
                "binding": dict(binding),
            }
            target["section_request_fingerprint"] = section_request_fingerprint(target)
            target["generation_id"] = source_generation_id(target)
            targets.append(target)
    return targets


def normalize_source_timestamp(value: Any, timezone_name: str) -> datetime | None:
    """Normalize provider timestamps to aware UTC and reject ambiguous local time."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc)
    try:
        zone = ZoneInfo(timezone_name)
    except Exception:
        return None
    first = parsed.replace(tzinfo=zone, fold=0)
    second = parsed.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset():
        return None
    return first.astimezone(timezone.utc)


def _timestamp_candidates(value: str, timezone_name: str) -> list[datetime]:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        return [parsed.astimezone(timezone.utc)]
    zone = ZoneInfo(timezone_name)
    candidates = []
    for fold in (0, 1):
        local = parsed.replace(tzinfo=zone, fold=fold)
        utc = local.astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None) == parsed:
            candidates.append(utc)
    return sorted(set(candidates))


def _resolve_timestamp_sequence(times: list[Any], timezone_name: str) -> tuple[list[datetime | None], list[dict[str, Any]]]:
    """Resolve local timestamps only when the complete sequence is unambiguous."""
    candidate_sets: list[list[datetime]] = []
    gaps: list[dict[str, Any]] = []
    for index, value in enumerate(times):
        if not isinstance(value, str):
            candidate_sets.append([])
            gaps.append({"index": index, "source_timestamp": value, "reason": "malformed_timestamp"})
            continue
        try:
            candidates = _timestamp_candidates(value, timezone_name)
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            candidates = []
        candidate_sets.append(candidates)
        if not candidates:
            gaps.append({"index": index, "source_timestamp": value, "reason": "invalid_or_nonexistent_timestamp"})

    def solve(index: int, previous: datetime | None, memo: dict[tuple[int, datetime | None], list[tuple[datetime | None, ...]]]):
        key = (index, previous)
        if key in memo:
            return memo[key]
        if index == len(candidate_sets):
            return [()]
        candidates = candidate_sets[index]
        choices = [None] if not candidates else [candidate for candidate in candidates if previous is None or candidate > previous]
        if candidates and not choices:
            choices = [None]
        solutions: list[tuple[datetime | None, ...]] = []
        for choice in choices:
            for suffix in solve(index + 1, choice or previous, memo):
                solutions.append((choice,) + suffix)
                if len(solutions) >= 2:
                    break
            if len(solutions) >= 2:
                break
        memo[key] = solutions
        return solutions

    solutions = solve(0, None, {})
    if len(solutions) > 1:
        best_count = max(sum(value is not None for value in solution) for solution in solutions)
        solutions = [solution for solution in solutions if sum(value is not None for value in solution) == best_count]
    if len(solutions) == 1:
        resolved = list(solutions[0])
    else:
        resolved = [None] * len(times)
        if solutions:
            for index, values in enumerate(zip(*solutions)):
                if len(set(values)) == 1:
                    resolved[index] = values[0]
                elif candidate_sets[index]:
                    gaps.append({"index": index, "source_timestamp": times[index], "reason": "ambiguous_timestamp"})
        else:
            for index, candidates in enumerate(candidate_sets):
                if candidates:
                    gaps.append({"index": index, "source_timestamp": times[index], "reason": "nonmonotonic_timestamp_sequence"})
    existing_gap_indices = {gap.get("index") for gap in gaps}
    for index, candidates in enumerate(candidate_sets):
        if candidates and resolved[index] is None and index not in existing_gap_indices:
            gaps.append({
                "index": index,
                "source_timestamp": times[index],
                "reason": "nonmonotonic_timestamp_sequence",
            })
    return resolved, gaps


def build_open_meteo_request(target: dict[str, Any]) -> dict[str, str]:
    return {
        "latitude": str(target["latitude"]),
        "longitude": str(target["longitude"]),
        "hourly": "global_tilted_irradiance",
        "tilt": str(target["tilt_deg"]),
        "azimuth": str(target["open_meteo_azimuth_deg"]),
        "timezone": "auto",
        "forecast_days": "3",
    }


def normalize_open_meteo_payload(payload: dict[str, Any], target: dict[str, Any]) -> dict[str, Any] | None:
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    times = hourly.get("time") if isinstance(hourly, dict) else None
    values = hourly.get("global_tilted_irradiance") if isinstance(hourly, dict) else None
    if not isinstance(times, list) or not isinstance(values, list):
        return None
    api_timezone = _valid_timezone(payload.get("timezone")) or target["timezone"]
    points = []
    quality_gaps = []
    resolved, timestamp_gaps = _resolve_timestamp_sequence(times, api_timezone)
    quality_gaps.extend(timestamp_gaps)
    previous = None
    pair_count = min(len(times), len(values))
    if len(times) != len(values):
        quality_gaps.append({"reason": "array_length_mismatch", "time_count": len(times), "value_count": len(values)})
    for index in range(pair_count):
        source_timestamp = times[index]
        value = values[index]
        valid_at = resolved[index]
        number = _number(value)
        if valid_at is not None and previous is not None and valid_at - previous != timedelta(hours=1):
            quality_gaps.append({"index": index, "source_timestamp": source_timestamp, "reason": "cadence_gap", "previous_valid_at": previous.isoformat(), "valid_at": valid_at.isoformat()})
        if valid_at is None or number is None:
            quality_gaps.append({"index": index, "source_timestamp": source_timestamp, "reason": "invalid_timestamp_or_value"})
            continue
        previous = valid_at
        points.append({
            "source_timestamp": source_timestamp,
            "valid_at": valid_at,
            "value": number,
            "unit": "W/m²",
            "quality_status": "good",
        })
    valid_times = [value for value in resolved if value is not None]
    source_valid_from = min(valid_times) if valid_times else None
    source_valid_to = max(valid_times) + timedelta(hours=1) if valid_times else None
    quality_status = "good" if not quality_gaps and points else "partial" if points else "invalid"
    return {
        "points": points,
        "quality_status": quality_status,
        "quality": {"status": quality_status, "gaps": quality_gaps},
        "source_valid_from": source_valid_from,
        "source_valid_to": source_valid_to,
            "api_metadata": {
            key: payload[key] for key in ("model", "timezone", "utc_offset_seconds", "generationtime_ms")
            if payload.get(key) is not None
        },
    }


async def async_fetch_open_meteo_target(hass, target: dict[str, Any]) -> tuple[dict[str, Any], datetime]:
    """Fetch one raw provider response without applying manager transformations."""
    session = async_get_clientsession(hass)
    request = build_open_meteo_request(target)
    async with session.get(OPEN_METEO_ENDPOINT, params=request, timeout=30) as response:
        if response.status != 200:
            raise ValueError(f"http_{response.status}")
        payload = await response.json()
    if not isinstance(payload, dict):
        raise ValueError("invalid_response")
    fetched_at = dt_util.now().astimezone(timezone.utc)
    return payload, fetched_at


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
        self._site_id: str | None = None
        self._context_generation = 0
        self._request_generation = 0

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

    def discovered_binding(self) -> dict[str, Any] | None:
        """Return the current installation fingerprint for explicit site binding."""
        if not isinstance(self._installation, dict) or not self._installation.get("fingerprint"):
            return None
        return {
            "source": OPEN_METEO_SOURCE,
            "installation_fingerprint": self._installation["fingerprint"],
        }

    async def async_migrate_site_locations(self, site_identity_manager) -> int:
        """Seed only the existing same-site location with verified legacy evidence."""
        snapshot = getattr(site_identity_manager, "collection_site_configs", lambda: {})()
        migrated = 0
        for site_id, config in snapshot.items():
            if isinstance(config.get("location"), dict):
                continue
            binding = (config.get("bindings") or {}).get("open_meteo")
            if not isinstance(binding, dict):
                continue
            store, cached = await async_load_site_store(self.hass, STORE_KEY, 1, site_id)
            del store
            if not isinstance(cached, dict):
                continue
            installation = cached.get("installation")
            state = cached.get("state")
            frame = cached.get("frame")
            if not isinstance(installation, dict) or not isinstance(state, dict):
                continue
            if binding.get("installation_fingerprint") != installation.get("fingerprint"):
                continue
            latitude = _number(installation.get("latitude"))
            longitude = _number(installation.get("longitude"))
            api_metadata = frame.get("api_metadata", {}) if isinstance(frame, dict) else {}
            timezone_name = _valid_timezone(api_metadata.get("timezone"))
            if latitude is None or longitude is None or timezone_name is None:
                continue
            location_payload = {
                "latitude": latitude,
                "longitude": longitude,
                "timezone": timezone_name,
                "provenance": "open_meteo_namespaced_store_and_binding",
                "verification_state": "verified",
                "location_fingerprint": _location_fingerprint(latitude, longitude, timezone_name),
            }
            try:
                migrated += int(await site_identity_manager.async_set_site_location(site_id, location_payload))
            except ValueError:
                continue
        return migrated

    async def async_apply_site_context(self, site_id: str, binding: dict[str, Any] | None) -> None:
        """Switch the Open-Meteo frame to one site namespace."""
        self._context_generation += 1
        self._request_generation += 1
        self._site_id = site_id if isinstance(binding, dict) else None
        self._installation = None
        self._frame = None
        self._frame_id = None
        self._state = {"available": False, "source": OPEN_METEO_SOURCE, "model": OPEN_METEO_MODEL}
        if self._site_id is None:
            self._state = {"available": False, "source": OPEN_METEO_SOURCE, "model": OPEN_METEO_MODEL, "reason": "site_unconfigured"}
            return
        self.store, cached = await async_load_site_store(self.hass, STORE_KEY, 1, self._site_id)
        if isinstance(cached, dict):
            self._installation = cached.get("installation") if isinstance(cached.get("installation"), dict) else None
            self._frame = cached.get("frame") if isinstance(cached.get("frame"), dict) else None
            self._frame_id = cached.get("frame_id") if isinstance(cached.get("frame_id"), str) else None
            self._state = cached.get("state") if isinstance(cached.get("state"), dict) else self._state
        self._state["site_id"] = self._site_id

    async def async_refresh_for_power_state(self, power_state: dict[str, Any]) -> None:
        if self._site_id is None:
            return
        context_generation = self._context_generation
        request_generation = self._request_generation = self._request_generation + 1
        context = {
            "site_id": self._site_id,
            "context_generation": context_generation,
            "request_generation": request_generation,
            "store": self.store,
        }
        installation = build_installation(self.hass, power_state)
        if installation is None:
            if context_generation != self._context_generation or context["site_id"] != self._site_id:
                return
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
        await self._async_fetch(installation, context)

    async def _async_fetch(self, installation: dict[str, Any], context: dict[str, Any]) -> None:
        sections = []
        for section in installation["sections"]:
            target = {
                "site_id": context["site_id"],
                "latitude": str(installation["latitude"]),
                "longitude": str(installation["longitude"]),
                "tilt_deg": section["tilt_deg"],
                "open_meteo_azimuth_deg": compass_to_open_meteo_azimuth(section["azimuth_deg"]),
            }
            try:
                payload, _fetched_at = await async_fetch_open_meteo_target(self.hass, target)
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
        if (
            context["context_generation"] != self._context_generation
            or context["request_generation"] != self._request_generation
            or context["site_id"] != self._site_id
        ):
            return
        self._installation = installation
        self._frame = frame
        self._frame_id = _frame_id(frame)
        self._state = {
            "available": True, "source": OPEN_METEO_SOURCE, "provider": "open-meteo",
            "model": OPEN_METEO_MODEL, "fetched_at": fetched_at,
            "frame_id": self._frame_id, "installation": installation,
            "energy_semantics": "unadjusted_dc_potential",
        }
        await context["store"].async_save({
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
