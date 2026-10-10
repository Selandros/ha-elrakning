import json
import asyncio
from types import SimpleNamespace
from pathlib import Path

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
        return getattr(self, "_config_entry", None)

    def async_create_entry(self, *, title, data):
        return {"type": "create_entry", "title": title, "data": data}


class _ReadOnlyOptionsFlowWithReload(_ReadOnlyOptionsFlow):
    pass


config_entries.OptionsFlow = _ReadOnlyOptionsFlow
config_entries.OptionsFlowWithReload = _ReadOnlyOptionsFlowWithReload

from custom_components.elrakning.config_flow import (
    ElrakningConfigFlow,
    ElrakningOptionsFlow,
    build_options,
)
from custom_components.elrakning.const import (
    APP_SHADOW_ENABLED,
    APP_SHADOW_URL,
    CLEAN_INSTALL_ARCHIVE_REFERENCE_OPTION,
    CLEAN_INSTALL_CONFIRM_OPTION,
    CLEAN_INSTALL_PENDING_OPTION,
    DIAGNOSTIC_STAGE_OPTION,
)


def test_config_flow_handler_contract_supports_add_and_options_routes():
    manifest_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["config_flow"] is True
    assert ElrakningConfigFlow.VERSION == 1
    assert hasattr(ElrakningConfigFlow, "async_step_user")
    flow = ElrakningConfigFlow.async_get_options_flow(SimpleNamespace(options={}))
    assert isinstance(flow, ElrakningOptionsFlow)


def test_options_flow_is_the_supported_shadow_configuration_path():
    entry = SimpleNamespace(options={})
    flow = ElrakningConfigFlow.async_get_options_flow(entry)
    assert isinstance(flow, ElrakningOptionsFlow)
    assert flow.config_entry is None


def test_options_flow_uses_home_assistant_reload_base():
    assert issubclass(ElrakningOptionsFlow, _ReadOnlyOptionsFlowWithReload)
    assert ElrakningOptionsFlow.__mro__[1] is _ReadOnlyOptionsFlowWithReload


def test_options_flow_submit_stage_change_returns_one_reloadable_entry_result():
    entry = SimpleNamespace(options={DIAGNOSTIC_STAGE_OPTION: 12})
    flow = ElrakningConfigFlow.async_get_options_flow(entry)
    flow._config_entry = entry
    result = asyncio.run(
        flow.async_step_init({
            CLEAN_INSTALL_ARCHIVE_REFERENCE_OPTION: "",
            CLEAN_INSTALL_CONFIRM_OPTION: False,
            DIAGNOSTIC_STAGE_OPTION: 13,
        })
    )
    assert result["type"] == "create_entry"
    assert result["data"][DIAGNOSTIC_STAGE_OPTION] == 13


def test_options_flow_has_no_custom_reload_listener_or_snapshot():
    source = (
        Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    ).read_text(encoding="utf-8")
    assert "_async_options_update_listener" not in source
    assert "options_update_unsub" not in source
    assert "options_snapshot" not in source


def test_all_diagnostic_stages_use_official_flow_reload_without_runtime_listener():
    source = (
        Path(__file__).parents[1] / "custom_components" / "elrakning" / "__init__.py"
    ).read_text(encoding="utf-8")
    assert "if diagnostic_stage == 0:" in source
    for stage in (11, 12, 13):
        assert f"_diagnostic_pause_at(hass, {stage}" in source
    assert "add_update_listener" not in source
    assert "async_reload(entry.entry_id)" not in source


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
    for stage in (-1, 16, True, "2"):
        try:
            build_options({}, archive_reference="", confirm=False, diagnostic_stage=stage)
        except ValueError as error:
            assert str(error) == "diagnostic_stage_invalid"
        else:
            raise AssertionError(f"stage {stage!r} was accepted")


def _new_config_flow():
    flow = object.__new__(ElrakningConfigFlow)

    async def _set_unique_id(*_args):
        return None

    def _abort_if_unique_id_configured(*_args):
        return None

    def _show_form(*_args, **kwargs):
        return {"type": "form", **kwargs}

    def _create_entry(*_args, **kwargs):
        return {"type": "create_entry", **kwargs}

    flow.async_set_unique_id = _set_unique_id
    flow._abort_if_unique_id_configured = _abort_if_unique_id_configured
    flow.async_show_form = _show_form
    flow.async_create_entry = _create_entry
    return flow


def test_new_config_flow_exposes_clean_room_fields_and_stage_zero_default():
    result = asyncio.run(ElrakningConfigFlow.async_step_user(_new_config_flow()))

    assert result["type"] == "form"
    assert CLEAN_INSTALL_ARCHIVE_REFERENCE_OPTION in result["data_schema"]
    assert CLEAN_INSTALL_CONFIRM_OPTION in result["data_schema"]
    assert DIAGNOSTIC_STAGE_OPTION in result["data_schema"]


def test_new_config_flow_creates_pending_reset_options_without_setup():
    flow = _new_config_flow()
    result = asyncio.run(
        ElrakningConfigFlow.async_step_user(
            flow,
            {
                CLEAN_INSTALL_ARCHIVE_REFERENCE_OPTION: "/config/elrakning/legacy-bundles/test",
                CLEAN_INSTALL_CONFIRM_OPTION: True,
                DIAGNOSTIC_STAGE_OPTION: 0,
            },
        )
    )

    assert result["type"] == "create_entry"
    assert result["data"] == {}
    assert result["options"][DIAGNOSTIC_STAGE_OPTION] == 0
    assert result["options"][CLEAN_INSTALL_PENDING_OPTION] == {
        "archive_reference": "/config/elrakning/legacy-bundles/test",
        "confirm": True,
    }


def test_new_config_flow_rejects_unconfirmed_or_nonzero_stage():
    unconfirmed = asyncio.run(
        ElrakningConfigFlow.async_step_user(
            _new_config_flow(),
            {
                CLEAN_INSTALL_ARCHIVE_REFERENCE_OPTION: "bundle",
                CLEAN_INSTALL_CONFIRM_OPTION: False,
                DIAGNOSTIC_STAGE_OPTION: 0,
            },
        )
    )
    assert unconfirmed["errors"]["base"] == "clean_install_confirmation_required"

    nonzero = asyncio.run(
        ElrakningConfigFlow.async_step_user(
            _new_config_flow(),
            {
                CLEAN_INSTALL_ARCHIVE_REFERENCE_OPTION: "bundle",
                CLEAN_INSTALL_CONFIRM_OPTION: True,
                DIAGNOSTIC_STAGE_OPTION: 1,
            },
        )
    )
    assert nonzero["errors"]["base"] == "diagnostic_stage_zero_required"
