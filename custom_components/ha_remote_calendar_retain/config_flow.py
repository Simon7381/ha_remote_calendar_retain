"""Setup, settings cog and reconfiguration for Remote Calendar Retain."""

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import callback
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from httpx import HTTPError, InvalidURL, TimeoutException

from .client import get_calendar
from .const import CONF_CALENDAR_NAME, CONF_RETAIN_EVENTS, DOMAIN
from .ics import InvalidIcsException, parse_calendar


def _schema(values: dict[str, Any]) -> vol.Schema:
    """Show the same settings at setup and when editing an existing entry."""
    return vol.Schema(
        {
            vol.Required(
                CONF_CALENDAR_NAME, default=values.get(CONF_CALENDAR_NAME, "")
            ): str,
            vol.Required(CONF_URL, default=values.get(CONF_URL, "")): str,
            vol.Required(
                CONF_RETAIN_EVENTS, default=values.get(CONF_RETAIN_EVENTS, False)
            ): bool,
            vol.Required(
                CONF_VERIFY_SSL, default=values.get(CONF_VERIFY_SSL, True)
            ): bool,
            vol.Optional(CONF_USERNAME, default=values.get(CONF_USERNAME, "")): str,
            vol.Optional(
                CONF_PASSWORD, default=values.get(CONF_PASSWORD, "")
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
        }
    )


async def _validate(hass, data: dict[str, Any]) -> str | None:
    """Validate without logging feed URLs, which can contain secret tokens."""
    client = get_async_client(hass, verify_ssl=data[CONF_VERIFY_SSL])
    try:
        response = await get_calendar(
            client,
            data[CONF_URL],
            username=data.get(CONF_USERNAME) or None,
            password=data.get(CONF_PASSWORD, ""),
        )
        if response.status_code == 401:
            return "invalid_auth"
        if response.status_code == 403:
            return "forbidden"
        response.raise_for_status()
        await parse_calendar(hass, response.text)
    except TimeoutException:
        return "timeout_connect"
    except HTTPError, InvalidURL:
        return "cannot_connect"
    except InvalidIcsException:
        return "invalid_ics_file"
    return None


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    data = dict(user_input)
    data[CONF_CALENDAR_NAME] = data[CONF_CALENDAR_NAME].strip()
    url = data[CONF_URL].strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://") :]
    data[CONF_URL] = url
    return data


class SettingsMixin:
    """Share validation between setup, reconfigure and the settings cog."""

    async def _async_settings(self, step_id, user_input, entry=None):
        errors = {}
        values = dict(entry.data) if entry else {}
        if user_input is not None:
            values.update(_normalize(user_input))
            if not values[CONF_CALENDAR_NAME]:
                errors[CONF_CALENDAR_NAME] = "required"
            elif not values[CONF_URL].lower().startswith(("http://", "https://")):
                errors[CONF_URL] = "invalid_url"
            else:
                self._async_abort_entries_match({CONF_URL: values[CONF_URL]})
                self._async_abort_entries_match(
                    {CONF_CALENDAR_NAME: values[CONF_CALENDAR_NAME]}
                )
                if error := await _validate(self.hass, values):
                    errors["base"] = error
                elif entry is None:
                    return self.async_create_entry(
                        title=values[CONF_CALENDAR_NAME], data=values
                    )
                elif isinstance(self, ConfigFlow):
                    return self.async_update_reload_and_abort(
                        entry, title=values[CONF_CALENDAR_NAME], data=values
                    )
                else:
                    self.hass.config_entries.async_update_entry(
                        entry, title=values[CONF_CALENDAR_NAME], data=values
                    )
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
                    return self.async_create_entry(title="", data={})
        return self.async_show_form(
            step_id=step_id, data_schema=_schema(values), errors=errors
        )


class RemoteCalendarRetainConfigFlow(SettingsMixin, ConfigFlow, domain=DOMAIN):
    """Handle setup and Home Assistant's Reconfigure action."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        return await self._async_settings("user", user_input)

    async def async_step_reconfigure(self, user_input=None) -> ConfigFlowResult:
        return await self._async_settings(
            "reconfigure", user_input, self._get_reconfigure_entry()
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Expose the settings cog."""
        return RemoteCalendarRetainOptionsFlow()


class RemoteCalendarRetainOptionsFlow(SettingsMixin, OptionsFlow):
    """Edit URL, credentials and retention from the settings cog."""

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        return await self._async_settings("init", user_input, self.config_entry)
