from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import ClimateEntityFeature, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from .const import DOMAIN
from .entity import EnergyManagerTeslaEntity


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities([JamesTeslaClimate(hass.data[DOMAIN])])


class JamesTeslaClimate(EnergyManagerTeslaEntity, ClimateEntity):
    _attr_name = "Climate"
    _attr_unique_id = "energy_manager_james_tesla_climate"
    _attr_suggested_object_id = "james_tesla_climate"
    _attr_icon = "mdi:car-seat-cooler"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 15
    _attr_max_temp = 28
    _attr_target_temperature_step = 1
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT_COOL]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF

    @property
    def current_temperature(self) -> float | None:
        return self.coordinator.data.get("interior_temperature_c")

    @property
    def target_temperature(self) -> float | None:
        return self.coordinator.data.get("climate_target_c")

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT_COOL if self.coordinator.data.get("climate_on") else HVACMode.OFF

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self.coordinator.control("climate_off" if hvac_mode == HVACMode.OFF else "climate_on")

    async def async_turn_on(self) -> None:
        await self.coordinator.control("climate_on")

    async def async_turn_off(self) -> None:
        await self.coordinator.control("climate_off")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self.coordinator.control("set_climate_temperature", float(temperature))
