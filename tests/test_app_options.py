from types import SimpleNamespace

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)


install_homeassistant_stubs()
install_elrakning_package_stub()
install_optional_dependency_stubs()

from homeassistant import config_entries


class _ConfigFlow:
    def __init_subclass__(cls, **_kwargs):
        return super().__init_subclass__()


config_entries.ConfigFlow = _ConfigFlow


class _ReadOnlyOptionsFlow:
    @property
    def config_entry(self):
        return None


config_entries.OptionsFlow = _ReadOnlyOptionsFlow

from custom_components.elrakning.config_flow import (
    ElrakningConfigFlow,
    ElrakningOptionsFlow,
    build_options,
)
from custom_components.elrakning.const import (
    APP_SHADOW_ENABLED,
    APP_SHADOW_URL,
    CLEAN_INSTALL_PENDING_OPTION,
    DIAGNOSTIC_STAGE_OPTION,
)


def test_options_flow_is_the_supported_shadow_configuration_path():
    entry = SimpleNamespace(options={})
    flow = ElrakningConfigFlow.async_get_options_flow(entry)
    assert isinstance(flow, ElrakningOptionsFlow)
    assert flow.config_entry is None


def test_options_flow_builds_bounded_pending_reset_without_mutating_site_state():
    options = build_options(
        {APP_SHADOW_ENABLED: False, APP_SHADOW_URL: "http://127.0.0.1:8099"},
        archive_reference=" /config/elrakning/legacy-bundles/test ",
        confirm=True,
    )

    assert options[APP_SHADOW_ENABLED] is False
    assert options[APP_SHADOW_URL] == "http://127.0.0.1:8099"
    assert options[CLEAN_INSTALL_PENDING_OPTION] == {
        "archive_reference": "/config/elrakning/legacy-bundles/test",
        "confirm": True,
    }


def test_options_flow_confirm_false_clears_pending_marker():
    options = build_options(
        {CLEAN_INSTALL_PENDING_OPTION: {"archive_reference": "bundle", "confirm": True}},
        archive_reference="",
        confirm=False,
    )

    assert CLEAN_INSTALL_PENDING_OPTION not in options


def test_options_flow_stores_bounded_diagnostic_stage_without_touching_site_state():
    options = build_options(
        {APP_SHADOW_ENABLED: False},
        archive_reference="",
        confirm=False,
        diagnostic_stage=0,
    )

    assert options[DIAGNOSTIC_STAGE_OPTION] == 0


def test_options_flow_rejects_invalid_diagnostic_stage():
    for stage in (-1, 10, True, "2"):
        try:
            build_options({}, archive_reference="", confirm=False, diagnostic_stage=stage)
        except ValueError as error:
            assert str(error) == "diagnostic_stage_invalid"
        else:
            raise AssertionError(f"stage {stage!r} was accepted")
