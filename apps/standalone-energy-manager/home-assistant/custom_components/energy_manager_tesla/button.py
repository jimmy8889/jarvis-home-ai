from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription

from .const import DOMAIN
from .entity import EnergyManagerTeslaEntity


@dataclass(frozen=True, kw_only=True)
class TeslaButtonDescription(ButtonEntityDescription):
    action: str


BUTTONS = (
    TeslaButtonDescription(key="unlock_car", name="Unlock car", icon="mdi:car-door-lock-open", action="unlock"),
    TeslaButtonDescription(key="unlock_charge_port", name="Unlock charge port", icon="mdi:ev-plug-ccs2", action="unlock_charge_port"),
    TeslaButtonDescription(key="wake", name="Wake car", icon="mdi:sleep-off", action="wake"),
    TeslaButtonDescription(key="flash_lights", name="Flash lights", icon="mdi:car-light-high", action="flash_lights"),
    TeslaButtonDescription(key="sound_horn", name="Sound horn", icon="mdi:bugle", action="sound_horn"),
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities([JamesTeslaButton(hass.data[DOMAIN], description) for description in BUTTONS])


class JamesTeslaButton(EnergyManagerTeslaEntity, ButtonEntity):
    entity_description: TeslaButtonDescription

    def __init__(self, coordinator, description):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"energy_manager_james_tesla_{description.key}"
        self._attr_suggested_object_id = f"james_tesla_{description.key}"

    async def async_press(self):
        await self.coordinator.control(self.entity_description.action)
