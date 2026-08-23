"""Config flow for the Elräkning integration."""

import voluptuous as vol
from homeassistant import config_entries

from .const import DOMAIN


class ElrakningConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Elräkning."""

    VERSION = 1

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
