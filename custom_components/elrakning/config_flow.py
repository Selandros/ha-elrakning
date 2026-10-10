"""Config flow for the Elräkning integration."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .app_client import DEFAULT_APP_URL
from .const import (
    APP_SHADOW_ENABLED,
    APP_SHADOW_TOKEN,
    APP_SHADOW_URL,
    CLEAN_INSTALL_ARCHIVE_REFERENCE_OPTION,
    CLEAN_INSTALL_CONFIRM_OPTION,
    CLEAN_INSTALL_PENDING_OPTION,
    DIAGNOSTIC_STAGE_MAX,
    DIAGNOSTIC_STAGE_OPTION,
    DOMAIN,
)


def build_options(
    existing: dict,
    *,
    archive_reference: str,
    confirm: bool,
    diagnostic_stage: int | None = None,
) -> dict:
    """Build bounded options without touching persistent site stores."""
    options = dict(existing or {})
    reference = archive_reference.strip() if isinstance(archive_reference, str) else ""
    if confirm:
        if not reference or len(reference) > 256:
            raise ValueError("archive_reference_invalid")
        options[CLEAN_INSTALL_PENDING_OPTION] = {
            "archive_reference": reference,
            "confirm": True,
        }
    else:
        options.pop(CLEAN_INSTALL_PENDING_OPTION, None)
    if diagnostic_stage is not None:
        if (
            isinstance(diagnostic_stage, bool)
            or not isinstance(diagnostic_stage, int)
            or not 0 <= diagnostic_stage <= DIAGNOSTIC_STAGE_MAX
        ):
            raise ValueError("diagnostic_stage_invalid")
        options[DIAGNOSTIC_STAGE_OPTION] = diagnostic_stage
    return options


class ElrakningConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Elräkning."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ElrakningOptionsFlow()

    async def async_step_user(self, user_input: dict[str, str] | None = None):
        """Create a clean-room entry without touching runtime stores."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors = {}
        if user_input is not None:
            if not user_input.get(CLEAN_INSTALL_CONFIRM_OPTION, False):
                errors["base"] = "clean_install_confirmation_required"
            elif user_input.get(DIAGNOSTIC_STAGE_OPTION, 0) != 0:
                errors["base"] = "diagnostic_stage_zero_required"
            else:
                try:
                    options = build_options(
                        {},
                        archive_reference=user_input.get(
                            CLEAN_INSTALL_ARCHIVE_REFERENCE_OPTION, ""
                        ),
                        confirm=True,
                        diagnostic_stage=0,
                    )
                except ValueError as error:
                    errors["base"] = str(error)
                else:
                    return self.async_create_entry(
                        title="Elräkning",
                        data={},
                        options=options,
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CLEAN_INSTALL_ARCHIVE_REFERENCE_OPTION,
                    ): vol.All(str, vol.Length(max=256)),
                    vol.Required(
                        CLEAN_INSTALL_CONFIRM_OPTION,
                        default=False,
                    ): bool,
                    vol.Required(
                        DIAGNOSTIC_STAGE_OPTION,
                        default=0,
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=DIAGNOSTIC_STAGE_MAX)),
                }
            ),
            errors=errors,
        )


class ElrakningOptionsFlow(config_entries.OptionsFlow):
    """Configure the optional, read-only shadow App boundary."""

    async def async_step_init(self, user_input: dict | None = None):
        if user_input is not None:
            options = build_options(
                self.config_entry.options,
                archive_reference=user_input.get(CLEAN_INSTALL_ARCHIVE_REFERENCE_OPTION, ""),
                confirm=user_input.get(CLEAN_INSTALL_CONFIRM_OPTION, False),
                diagnostic_stage=user_input.get(DIAGNOSTIC_STAGE_OPTION),
            )
            for key in (APP_SHADOW_ENABLED, APP_SHADOW_URL, APP_SHADOW_TOKEN):
                if key in user_input:
                    options[key] = user_input[key]
            if DIAGNOSTIC_STAGE_OPTION in user_input:
                stage = user_input[DIAGNOSTIC_STAGE_OPTION]
                if stage is None:
                    options.pop(DIAGNOSTIC_STAGE_OPTION, None)
                else:
                    options[DIAGNOSTIC_STAGE_OPTION] = stage
            return self.async_create_entry(title="", data=options)

        options = self.config_entry.options
        pending = options.get(CLEAN_INSTALL_PENDING_OPTION, {})
        if not isinstance(pending, dict):
            pending = {}
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
                vol.Optional(
                    CLEAN_INSTALL_ARCHIVE_REFERENCE_OPTION,
                    default=pending.get("archive_reference", ""),
                ): vol.All(str, vol.Length(max=256)),
                vol.Optional(
                    CLEAN_INSTALL_CONFIRM_OPTION,
                    default=pending.get("confirm", False) is True,
                ): bool,
                vol.Optional(DIAGNOSTIC_STAGE_OPTION): vol.All(
                    vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=0, max=DIAGNOSTIC_STAGE_MAX))),
                ),
            }),
        )
