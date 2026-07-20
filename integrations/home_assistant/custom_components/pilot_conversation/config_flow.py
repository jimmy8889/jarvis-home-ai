"""Config flow for Pilot Core Conversation."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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
            try:
                user_input[CONF_CORE_URL] = _valid_url(
                    str(user_input[CONF_CORE_URL])
                )
            except vol.Invalid:
                errors[CONF_CORE_URL] = "invalid_url"
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
                vol.Required(CONF_NAME, default="Pilot Core"): str,
                vol.Required(CONF_CORE_URL, default=DEFAULT_CORE_URL): str,
                vol.Required(CONF_DEVICE_ID, default=DEFAULT_DEVICE_ID): str,
                vol.Required(CONF_DEVICE_TOKEN): str,
                vol.Required(CONF_ROOM_ID, default=DEFAULT_ROOM_ID): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
