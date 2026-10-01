"""Bounded, site-scoped attention metadata for the presentation layer."""

from __future__ import annotations

from typing import Any


ACTION_ERRORS = frozenset({
    "reauth_required",
    "invalid_profile",
    "credential_required",
    "configuration_invalid",
})


def _site_configured(config: Any) -> bool:
    if not isinstance(config, dict):
        return False
    power = config.get("power") if isinstance(config.get("power"), dict) else {}
    meter = config.get("meter") if isinstance(config.get("meter"), dict) else {}
    return bool(
        power.get("solar_entities")
        or any(power.get(key) for key in ("power_entity", "energy_import_entity", "energy_export_entity", "battery_power_entity", "soc_entity"))
        or any(meter.get(key) for key in ("power_entity", "energy_import_entity", "energy_export_entity"))
    )


def site_action_attention(
    *, site_id: Any, site_name: Any, config: Any, provider_states: list[dict[str, Any] | None]
) -> dict[str, Any] | None:
    """Return only explicit manual-action metadata; never telemetry or raw provider data."""
    if not isinstance(site_id, str) or not site_id or not _site_configured(config):
        return None
    for state in provider_states:
        if not isinstance(state, dict):
            continue
        state_site_id = state.get("site_id")
        if state_site_id is not None and state_site_id != site_id:
            continue
        error = state.get("error")
        if state.get("reauth_required") is True or error in ACTION_ERRORS:
            timestamp = state.get("updated_at")
            return {
                "schema": "ella.site_attention.v1",
                "site_id": site_id,
                "site_name": site_name if isinstance(site_name, str) else site_id,
                "status": "action_required",
                "severity": "error",
                "reason_code": "provider_reauth_required" if state.get("reauth_required") is True else "provider_configuration_invalid",
                "component": "provider",
                "first_seen": timestamp,
                "last_seen": timestamp,
                "details_safe_for_ui": "Providern behöver åtgärdas.",
                "action_kind": "site_configuration",
                "action_route": "site_settings",
            }
    return None


async def async_site_attention_state(hass, site_manager) -> list[dict[str, Any]]:
    """Build safe cross-site metadata from persistent, site-bound provider state."""
    data = hass.data.get("elrakning", {})
    state = getattr(site_manager, "state", {}) or {}
    configs = site_manager.collection_site_configs()
    sites = {item.get("site_id"): item for item in state.get("sites", []) if isinstance(item, dict)}
    current_site_id = state.get("active_site_id")
    grid_provider = getattr(getattr(data.get("grid_manager"), "provider", None), "state_for_binding", None)
    trade_manager = data.get("elhandel_manager")
    result: list[dict[str, Any]] = []
    for site_id, config in sorted(configs.items()):
        if site_id == current_site_id or not isinstance(config, dict):
            continue
        bindings = config.get("bindings") if isinstance(config.get("bindings"), dict) else {}
        provider_states: list[dict[str, Any] | None] = []
        grid_binding = bindings.get("grid")
        if callable(grid_provider) and isinstance(grid_binding, dict):
            provider_states.append(grid_provider(grid_binding))
        trade_binding = bindings.get("elhandel")
        if trade_manager and isinstance(trade_binding, dict):
            storage = getattr(trade_manager, "storage", None)
            facility_id = trade_binding.get("facility_id")
            provider = trade_binding.get("provider")
            if storage and facility_id and provider:
                provider_states.append(await storage.async_load(
                    facility_id=facility_id, provider=provider, use_active_namespace=False
                ))
        attention = site_action_attention(
            site_id=site_id,
            site_name=(sites.get(site_id) or {}).get("name"),
            config=config,
            provider_states=provider_states,
        )
        if attention:
            result.append(attention)
    return result
