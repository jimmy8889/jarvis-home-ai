from homeassistant.components.lock import LockEntity

from .const import DOMAIN
from .entity import EnergyManagerTeslaEntity


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities([JamesTeslaLock(hass.data[DOMAIN])])


class JamesTeslaLock(EnergyManagerTeslaEntity, LockEntity):
    _attr_name = "Vehicle lock"
    _attr_unique_id = "energy_manager_james_tesla_lock"
    _attr_suggested_object_id = "james_tesla_vehicle_lock"

    @property
    def is_locked(self):
        return self.coordinator.data.get("locked")

    async def async_lock(self, **kwargs):
        await self.coordinator.control("lock")

    async def async_unlock(self, **kwargs):
        await self.coordinator.control("unlock")
