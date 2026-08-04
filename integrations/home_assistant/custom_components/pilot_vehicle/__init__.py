"""Pilot Vehicle services for Home Assistant's native Tesla Fleet runtime."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, SERVICE_SEND_NAVIGATION

_LOGGER = logging.getLogger(__name__)

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("latitude"): vol.All(vol.Coerce(float), vol.Range(min=-90, max=90)),
        vol.Required("longitude"): vol.All(
            vol.Coerce(float), vol.Range(min=-180, max=180)
        ),
        vol.Required("order", default=0): vol.All(vol.Coerce(int), vol.In([0])),
    },
    extra=vol.PREVENT_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Pilot Vehicle integration."""
    del config

    async def send_navigation(call: ServiceCall) -> None:
        """Send a bounded navigation coordinate through native Tesla Fleet."""
        device_id = str(call.data["device_id"])
        latitude = float(call.data["latitude"])
        longitude = float(call.data["longitude"])
        order = int(call.data["order"])
        vehicle = _resolve_vehicle(hass, device_id)
        try:
            await asyncio.wait_for(
                _send_navigation(vehicle, latitude, longitude),
                timeout=30,
            )
        except _tesla_fleet_error_type() as error:
            status = getattr(error, "status", None)
            try:
                status = int(status)
            except (TypeError, ValueError):
                pass
            _LOGGER.error("Tesla Fleet navigation failed (status=%s)", status)
            raise HomeAssistantError(_fleet_error_message(status)) from error
        except asyncio.TimeoutError as error:
            raise HomeAssistantError("Tesla Fleet navigation timed out") from error
        except Exception as error:  # noqa: BLE001 - provider SDK errors vary by version
            _LOGGER.exception("Tesla Fleet navigation failed")
            raise HomeAssistantError("Tesla Fleet navigation failed") from error

    if not hass.services.has_service(DOMAIN, SERVICE_SEND_NAVIGATION):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_NAVIGATION,
            send_navigation,
            schema=SERVICE_SCHEMA,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Pilot Vehicle config entry."""
    del entry
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the Pilot Vehicle config entry."""
    remaining = [
        item
        for item in hass.config_entries.async_entries(DOMAIN)
        if item.entry_id != entry.entry_id
    ]
    if not remaining:
        hass.services.async_remove(DOMAIN, SERVICE_SEND_NAVIGATION)
    return True


def _resolve_vehicle(hass: HomeAssistant, device_id: str) -> Any:
    """Resolve a native Tesla Fleet vehicle without accepting VINs or provider IDs."""
    registry = dr.async_get(hass)
    registered = registry.async_get(device_id)
    if registered is None:
        raise HomeAssistantError("Pilot navigation device target is not registered")
    registered_identifiers = {
        (str(domain), str(identifier))
        for domain, identifier in registered.identifiers
    }
    registered_names = {
        str(name).strip().casefold()
        for name in (registered.name, registered.name_by_user)
        if name
    }

    for entry in hass.config_entries.async_entries("tesla_fleet"):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        runtime = getattr(entry, "runtime_data", None)
        vehicles = getattr(runtime, "vehicles", ())
        if isinstance(vehicles, dict):
            vehicles = vehicles.values()
        for vehicle in vehicles:
            native_device = getattr(vehicle, "device", None)
            if isinstance(native_device, dict):
                native_id = native_device.get("id")
                identifiers = native_device.get("identifiers", ())
                native_names_source = (
                    native_device.get("name"),
                    native_device.get("name_by_user"),
                    getattr(vehicle, "name", None),
                )
            else:
                native_id = getattr(native_device, "id", None)
                identifiers = getattr(native_device, "identifiers", ())
                native_names_source = (
                    getattr(native_device, "name", None),
                    getattr(native_device, "name_by_user", None),
                    getattr(vehicle, "name", None),
                )
            if native_id == device_id:
                return vehicle
            native_identifiers = {
                (str(domain), str(identifier))
                for domain, identifier in identifiers
            }
            if registered_identifiers & native_identifiers:
                return vehicle
            native_names = {
                str(name).strip().casefold()
                for name in native_names_source
                if name
            }
            if registered_names & native_names:
                return vehicle
    raise HomeAssistantError(
        "Tesla Fleet is not loaded for the configured navigation vehicle; "
        "complete Fleet setup and key enrollment first"
    )


async def _send_navigation(vehicle: Any, latitude: float, longitude: float) -> Any:
    """Send the signed navigation request around the SDK enum-wrapper bug."""
    from tesla_fleet_api.tesla.vehicle.proto.car_server_pb2 import (
        Action,
        NavigationGpsRequest,
        VehicleAction,
    )

    request = NavigationGpsRequest(lat=latitude, lon=longitude, order=0)
    return await vehicle.api._sendInfotainment(  # noqa: SLF001 - SDK bridge
        Action(vehicleAction=VehicleAction(navigationGpsRequest=request))
    )


def _tesla_fleet_error_type() -> type[BaseException]:
    """Load the provider exception lazily so HA can validate this component offline."""
    try:
        from tesla_fleet_api.exceptions import TeslaFleetError
    except ImportError:
        return BaseException
    return TeslaFleetError


def _fleet_error_message(status: Any) -> str:
    """Return an actionable, credential-safe Fleet error."""
    if status in {401, 403, 412}:
        return "Tesla Fleet rejected navigation; verify the public key and virtual-key enrollment"
    if status in {402, 429}:
        return "Tesla Fleet usage or billing limit reached"
    if status in {404, 422}:
        return "Tesla Fleet navigation is unavailable for this vehicle"
    if status in {500, 502, 503, 504}:
        return "Tesla Fleet provider is temporarily unavailable"
    return "Tesla Fleet navigation failed"
