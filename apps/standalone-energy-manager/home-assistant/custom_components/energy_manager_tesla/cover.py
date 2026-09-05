from dataclasses import dataclass

from homeassistant.components.cover import CoverEntity, CoverEntityDescription, CoverEntityFeature

from .const import DOMAIN
from .entity import EnergyManagerTeslaEntity


@dataclass(frozen=True, kw_only=True)
class TeslaCoverDescription(CoverEntityDescription):
    state_key: str
    open_action: str
    close_action: str


COVERS = (
    TeslaCoverDescription(key="charge_port", name="Charge port door", device_class="door", icon="mdi:ev-plug-tesla", state_key="charge_port_open", open_action="open_charge_port", close_action="close_charge_port"),
    TeslaCoverDescription(key="windows", name="Window vent", device_class="window", icon="mdi:car-door", state_key="windows_open", open_action="vent_windows", close_action="close_windows"),
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities([JamesTeslaCover(hass.data[DOMAIN], description) for description in COVERS])


class JamesTeslaCover(EnergyManagerTeslaEntity, CoverEntity):
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
    entity_description: TeslaCoverDescription

    def __init__(self, coordinator, description):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"energy_manager_james_tesla_{description.key}"
        self._attr_suggested_object_id = f"james_tesla_{description.key}"

    @property
    def is_closed(self):
        state = self.coordinator.data.get(self.entity_description.state_key)
        return None if state is None else not bool(state)

    async def async_open_cover(self, **kwargs):
        await self.coordinator.control(self.entity_description.open_action)

    async def async_close_cover(self, **kwargs):
        await self.coordinator.control(self.entity_description.close_action)
