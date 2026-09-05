from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class EnergyManagerTeslaEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    @property
    def available(self) -> bool:
        return bool(super().available and self.coordinator.data.get("available"))

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "james_tesla_ble_proxy")},
            name="James Tesla",
            manufacturer="Tesla",
            model="Local BLE via Energy Manager",
            configuration_url="http://10.0.1.205:8787/",
        )
