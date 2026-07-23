"""Config flow for Pilot Core Conversation."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_CORE_URL,
    CONF_DEVICE_ID,
    CONF_DEVICE_TOKEN,
    CONF_ROOM_ID,
    DEFAULT_CORE_URL,
    DEFAULT_DEVICE_ID,
    DEFAULT_ROOM_ID,
    DOMAIN,
)


def _valid_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise vol.Invalid("Enter a valid Pilot Core HTTP or HTTPS URL")
    return normalized


class PilotConversationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a Pilot Core conversation agent."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Create a Pilot Core conversation entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = {
                CONF_NAME: str(user_input.get(CONF_NAME, "Pilot Core")).strip(),
                CONF_CORE_URL: str(
                    user_input.get(CONF_CORE_URL, DEFAULT_CORE_URL)
                ).strip(),
                CONF_DEVICE_ID: str(
                    user_input.get(CONF_DEVICE_ID, DEFAULT_DEVICE_ID)
                ).strip(),
                CONF_DEVICE_TOKEN: str(
                    user_input.get(CONF_DEVICE_TOKEN, "")
                ).strip(),
                CONF_ROOM_ID: str(
                    user_input.get(CONF_ROOM_ID, DEFAULT_ROOM_ID)
                ).strip(),
            }
            try:
                user_input[CONF_CORE_URL] = _valid_url(
                    str(user_input[CONF_CORE_URL])
                )
            except vol.Invalid:
                errors[CONF_CORE_URL] = "invalid_url"
            for key in (CONF_NAME, CONF_DEVICE_ID, CONF_DEVICE_TOKEN, CONF_ROOM_ID):
                if not user_input[key]:
                    errors[key] = "required"
            if not errors:
                await self.async_set_unique_id(str(user_input[CONF_DEVICE_ID]))
                self._abort_if_unique_id_configured()
            session = async_get_clientsession(self.hass)
            if not errors:
                try:
                    async with session.get(
                        f"{user_input[CONF_CORE_URL]}/readyz",
                        timeout=5,
                    ) as response:
                        if response.status != 200:
                            errors["base"] = "cannot_connect"
                        else:
                            payload = await response.json()
                            if payload.get("ready") is not True:
                                errors["base"] = "cannot_connect"
                except Exception:  # Home Assistant converts this to a user-facing error.
                    errors["base"] = "cannot_connect"
            if not errors:
                return self.async_create_entry(
                    title=str(user_input[CONF_NAME]),
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default="Pilot Core"): TextSelector(),
                vol.Optional(
                    CONF_CORE_URL, default=DEFAULT_CORE_URL
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
                vol.Optional(
                    CONF_DEVICE_ID, default=DEFAULT_DEVICE_ID
                ): TextSelector(),
                vol.Optional(CONF_DEVICE_TOKEN): TextSelector(
                    TextSelectorConfig(
                        type=TextSelectorType.PASSWORD,
                        autocomplete="current-password",
                    )
                ),
                vol.Optional(
                    CONF_ROOM_ID, default=DEFAULT_ROOM_ID
                ): TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
