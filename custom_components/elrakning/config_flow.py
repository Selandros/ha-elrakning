"""Config flow for the Elräkning integration."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .app_client import DEFAULT_APP_URL
from .const import APP_SHADOW_ENABLED, APP_SHADOW_TOKEN, APP_SHADOW_URL, DOMAIN


class ElrakningConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Elräkning."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ElrakningOptionsFlow()

    async def async_step_user(self, user_input: dict[str, str] | None = None):
        """Handle the user step."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Elräkning", data={})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
        )


class ElrakningOptionsFlow(config_entries.OptionsFlow):
    """Configure the optional, read-only shadow App boundary."""

    async def async_step_init(self, user_input: dict | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    APP_SHADOW_ENABLED,
                    default=options.get(APP_SHADOW_ENABLED, False),
                ): bool,
                vol.Optional(
                    APP_SHADOW_URL,
                    default=options.get(APP_SHADOW_URL, DEFAULT_APP_URL),
                ): vol.All(str, vol.Length(max=256)),
                vol.Optional(
                    APP_SHADOW_TOKEN,
                    default=options.get(APP_SHADOW_TOKEN, ""),
                ): vol.All(str, vol.Length(max=512)),
            }),
        )
