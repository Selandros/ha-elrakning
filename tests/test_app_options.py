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

from custom_components.elrakning.config_flow import ElrakningConfigFlow, ElrakningOptionsFlow


def test_options_flow_is_the_supported_shadow_configuration_path():
    entry = SimpleNamespace(options={})
    flow = ElrakningConfigFlow.async_get_options_flow(entry)
    assert isinstance(flow, ElrakningOptionsFlow)
    assert flow.config_entry is None
