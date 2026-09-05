from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, discovery
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_URL, DOMAIN, PLATFORMS


CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {vol.Optional(CONF_URL, default=DEFAULT_URL): cv.url}
        )
    },
    extra=vol.ALLOW_EXTRA,
)


class EnergyManagerTeslaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, url: str) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name="Energy Manager Tesla BLE",
            update_interval=timedelta(seconds=5),
        )
        self.url = url.rstrip("/")
        self.session = async_get_clientsession(hass)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            async with self.session.get(f"{self.url}/api/v1/vehicle", timeout=5) as response:
                response.raise_for_status()
                return await response.json()
        except Exception as exc:
            raise UpdateFailed(f"Energy Manager Tesla state unavailable: {exc}") from exc

    async def control(self, action: str, value: Any = None) -> None:
        payload: dict[str, Any] = {"action": action}
        if value is not None:
            payload["value"] = value
        async with self.session.post(
            f"{self.url}/api/v1/vehicle/control", json=payload, timeout=10
        ) as response:
            if response.status >= 400:
                detail = (await response.text())[:300]
                raise RuntimeError(f"Tesla BLE command failed ({response.status}): {detail}")
        await self.async_request_refresh()


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    if DOMAIN not in config:
        return True
    coordinator = EnergyManagerTeslaCoordinator(hass, config[DOMAIN][CONF_URL])
    # This integration is loaded from the existing YAML package rather than a
    # config entry. A normal refresh starts the coordinator and permits the
    # entities to remain unavailable/retry if the manager is temporarily down.
    await coordinator.async_refresh()
    hass.data[DOMAIN] = coordinator
    for platform in PLATFORMS:
        hass.async_create_task(
            discovery.async_load_platform(hass, platform, DOMAIN, {}, config)
        )
    return True
