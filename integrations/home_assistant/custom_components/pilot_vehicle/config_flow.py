"""Config flow for Pilot Vehicle."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN


class PilotVehicleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create the single local Pilot Vehicle service entry."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Install the service integration."""
        del user_input
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Pilot Vehicle", data={})
