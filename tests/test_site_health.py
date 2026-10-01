from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.site_health import site_action_attention


def _configured_site():
    return {"collection_enabled": True, "power": {"power_entity": "sensor.site_power"}, "meter": {}}


def test_unconfigured_site_has_no_cross_site_attention():
    assert site_action_attention(
        site_id="fiskvik",
        site_name="Fiskvik",
        config={"collection_enabled": True, "power": {}, "meter": {}},
        provider_states=[{"reauth_required": True, "error": "reauth_required"}],
    ) is None


def test_healthy_background_site_has_no_attention():
    assert site_action_attention(
        site_id="vikarbodarna",
        site_name="Vikarbodarna",
        config=_configured_site(),
        provider_states=[{"reauth_required": False, "error": None}],
    ) is None


def test_explicit_provider_reauth_exposes_safe_action_metadata_only():
    result = site_action_attention(
        site_id="vikarbodarna",
        site_name="Vikarbodarna",
        config=_configured_site(),
        provider_states=[{"reauth_required": True, "error": "reauth_required", "facility_id": "secret"}],
    )
    assert result["status"] == "action_required"
    assert result["reason_code"] == "provider_reauth_required"
    assert set(result) == {
        "schema", "site_id", "site_name", "status", "severity", "reason_code",
        "component", "first_seen", "last_seen", "details_safe_for_ui", "action_kind", "action_route",
    }
    assert "facility_id" not in result


def test_wrong_site_provider_state_cannot_populate_attention():
    assert site_action_attention(
        site_id="vikarbodarna",
        site_name="Vikarbodarna",
        config=_configured_site(),
        provider_states=[{"site_id": "fiskvik", "reauth_required": True}],
    ) is None
