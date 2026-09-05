from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription

from .const import DOMAIN
from .entity import EnergyManagerTeslaEntity


@dataclass(frozen=True, kw_only=True)
class TeslaSwitchDescription(SwitchEntityDescription):
    state_key: str
    on_action: str
    off_action: str


SWITCHES = (
    TeslaSwitchDescription(key="steering_wheel_heat", name="Steering wheel heat", icon="mdi:steering", state_key="steering_heat_on", on_action="steering_heat_on", off_action="steering_heat_off"),
    TeslaSwitchDescription(key="defrost", name="Defrost", icon="mdi:snowflake-melt", state_key="defrost_on", on_action="defrost_on", off_action="defrost_off"),
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities([JamesTeslaSwitch(hass.data[DOMAIN], description) for description in SWITCHES])


class JamesTeslaSwitch(EnergyManagerTeslaEntity, SwitchEntity):
    entity_description: TeslaSwitchDescription

    def __init__(self, coordinator, description):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"energy_manager_james_tesla_{description.key}"
        self._attr_suggested_object_id = f"james_tesla_{description.key}"

    @property
    def is_on(self):
        return self.coordinator.data.get(self.entity_description.state_key)

    async def async_turn_on(self, **kwargs):
        await self.coordinator.control(self.entity_description.on_action)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.control(self.entity_description.off_action)
