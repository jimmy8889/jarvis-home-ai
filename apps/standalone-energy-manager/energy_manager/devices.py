from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import logging
import time
from typing import Any

from aioesphomeapi import APIClient, LockCommand
import aiohttp

from .config import Settings
from .models import DeviceState

LOG = logging.getLogger(__name__)


def _as_bool(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"true", "on", "1", "online", "charging", "connected"}:
        return True
    if normalized in {"false", "off", "0", "offline", "disconnected", "stopped", "complete"}:
        return False
    return None


class TeslaMateState:
    def __init__(self, state: DeviceState):
        self.state = state
        self.values: dict[str, str] = {}
        self.updated_at: dict[str, datetime] = {}

    async def message(self, topic: str, payload: str) -> None:
        key = topic.rsplit("/", 1)[-1]
        self.values[key] = payload
        self.updated_at[key] = datetime.now(UTC)
        try:
            if key == "battery_level":
                self.state.ev_soc_pct = float(payload)
            elif key == "plugged_in":
                self.state.ev_plugged = _as_bool(payload)
            elif key == "charger_power":
                self.state.ev_power_kw = max(0.0, float(payload))
            elif key == "geofence":
                self.state.ev_home = payload.strip().lower() == "home"
            elif key == "state":
                # TeslaMate publishes charging/online/asleep. Home presence is
                # proven by local BLE, not inferred from this cloud state.
                self.state.ev_charging = payload.strip().lower() == "charging"
        except ValueError:
            LOG.debug("Ignoring invalid TeslaMate %s=%r", key, payload)


class EsphomeDevice:
    def __init__(
        self,
        host: str,
        port: int,
        password: str | None = None,
        noise_psk: str | None = None,
        reconnect_backoff_seconds: float = 10.0,
    ):
        self.host = host
        self.port = port
        self.password = password or ""
        self.noise_psk = noise_psk
        self.reconnect_backoff_seconds = reconnect_backoff_seconds
        self.client: APIClient | None = None
        self.entities: dict[str, Any] = {}
        self.entity_list: list[Any] = []
        self.services: dict[str, Any] = {}
        self.states: dict[int, Any] = {}
        self.connected = False
        self._lock = asyncio.Lock()
        self._retry_not_before = 0.0

    @property
    def reconnect_backoff_remaining(self) -> float:
        return max(0.0, self._retry_not_before - time.monotonic())

    @property
    def reconnect_backoff_active(self) -> bool:
        return self.reconnect_backoff_remaining > 0

    def _detach_client(self) -> APIClient | None:
        client = self.client
        self.client = None
        self.connected = False
        self.entities.clear()
        self.entity_list.clear()
        self.services.clear()
        self.states.clear()
        return client

    @staticmethod
    async def _disconnect(client: APIClient | None, *, force: bool) -> None:
        if client is None:
            return
        try:
            async with asyncio.timeout(2):
                await client.disconnect(force=force)
        except Exception:
            # The important containment action is detaching the dead client;
            # a reset peer may no longer accept a graceful close.
            pass

    async def invalidate(self, *, backoff: bool = True) -> None:
        """Detach and close a failed native-API connection before reuse."""

        async with self._lock:
            client = self._detach_client()
            if backoff:
                self._retry_not_before = max(
                    self._retry_not_before,
                    time.monotonic() + self.reconnect_backoff_seconds,
                )
            else:
                self._retry_not_before = 0.0
            await self._disconnect(client, force=True)

    async def connect(self) -> None:
        if self.connected and self.client:
            return
        async with self._lock:
            if self.connected and self.client:
                return
            remaining = self.reconnect_backoff_remaining
            if remaining > 0:
                raise RuntimeError(f"ESPHome reconnect backoff active for {remaining:.1f}s")
            stale_client = self._detach_client()
            await self._disconnect(stale_client, force=True)
            client = APIClient(self.host, self.port, self.password, noise_psk=self.noise_psk, client_info="standalone-energy-manager", keepalive=15)
            try:
                async with asyncio.timeout(8):
                    await client.connect(login=True)
                    entities, services = await client.list_entities_services()
                self.entities = {}
                self.entity_list = list(entities)
                for entity in entities:
                    for candidate in (getattr(entity, "object_id", ""), getattr(entity, "name", ""), getattr(entity, "unique_id", "")):
                        if candidate:
                            self.entities[str(candidate).lower()] = entity
                self.services = {
                    str(getattr(service, "name", "")).lower(): service
                    for service in services
                    if getattr(service, "name", "")
                }
                client.subscribe_states(self._state_callback)
                self.client = client
                self.connected = True
                self._retry_not_before = 0.0
            except Exception:
                self._detach_client()
                self._retry_not_before = time.monotonic() + self.reconnect_backoff_seconds
                await self._disconnect(client, force=True)
                raise

    def _state_callback(self, state: Any) -> None:
        self.states[int(state.key)] = state

    def _find(self, *needles: str, kind: str | None = None) -> Any:
        canon = lambda value: " ".join(str(value).lower().replace("_", " ").replace("-", " ").split())
        normalized = [canon(needle) for needle in needles]
        candidates = self.entity_list or list(dict.fromkeys(self.entities.values()))
        if kind:
            kind_name = canon(kind).replace(" ", "")
            candidates = [
                entity for entity in candidates
                if kind_name in type(entity).__name__.lower().replace("info", "")
            ]
        names = [
            (canon(getattr(entity, candidate, "")), entity)
            for entity in candidates
            for candidate in ("object_id", "name", "unique_id")
            if getattr(entity, candidate, "")
        ]
        exact = [entity for name, entity in names if name in normalized]
        if exact:
            return exact[0]
        for clean_name, entity in names:
            if all(part in clean_name for part in normalized):
                return entity
        raise KeyError(f"ESPHome {kind or 'entity'} not found at {self.host}: {needles}")

    async def switch(self, state: bool, *needles: str) -> None:
        await self.connect()
        entity = self._find(*needles, kind="switch")
        assert self.client
        self.client.switch_command(entity.key, state)

    async def number(self, value: float, *needles: str) -> None:
        await self.connect()
        entity = self._find(*needles, kind="number")
        assert self.client
        self.client.number_command(entity.key, value)

    async def button(self, *needles: str) -> None:
        await self.connect()
        entity = self._find(*needles, kind="button")
        assert self.client
        self.client.button_command(entity.key)

    async def lock(self, locked: bool, *needles: str) -> None:
        await self.connect()
        entity = self._find(*needles, kind="lock")
        assert self.client
        self.client.lock_command(entity.key, LockCommand.LOCK if locked else LockCommand.UNLOCK)

    async def cover(self, opened: bool, *needles: str) -> None:
        await self.connect()
        entity = self._find(*needles, kind="cover")
        assert self.client
        self.client.cover_command(entity.key, position=1.0 if opened else 0.0)

    async def action(self, name: str, data: dict[str, Any]) -> bool:
        await self.connect()
        service = self.services.get(name.lower())
        if service is None:
            return False
        assert self.client
        await self.client.execute_service(service, data)
        return True

    def state_for(self, *needles: str) -> Any | None:
        try:
            entity = self._find(*needles)
        except KeyError:
            return None
        return self.states.get(int(entity.key))

    def state_for_kind(self, kind: str, *needles: str) -> Any | None:
        try:
            entity = self._find(*needles, kind=kind)
        except KeyError:
            return None
        return self.states.get(int(entity.key))

    async def close(self) -> None:
        await self.invalidate(backoff=False)


class FlexibleLoadController:
    def __init__(self, settings: Settings, state: DeviceState):
        self.settings = settings
        self.state = state
        self.tesla = EsphomeDevice(
            settings.ev_host,
            settings.ev_port,
            settings.secret("tesla_esphome_password"),
            settings.secret("tesla_esphome_noise_psk"),
        )
        self.hot_water = EsphomeDevice(
            settings.hot_water_host,
            settings.hot_water_port,
            settings.secret("hot_water_esphome_password"),
            settings.secret("hot_water_esphome_noise_psk"),
        )
        self._last_ev_upward_at: datetime | None = None
        self._last_ev_change_at: datetime | None = None
        self._last_ev_lease_renewal_at: datetime | None = None
        self._ev_stop_ramp_amps: int | None = None
        self._ev_stop_ramp_last_step_at: datetime | None = None
        self._last_hw_command_at: datetime | None = None
        self._last_hw_lease_renewal_at: datetime | None = None
        self._http: aiohttp.ClientSession | None = None
        self._vehicle_control_lock = asyncio.Lock()
        self.hot_water_native = False
        self.ev_error: str | None = None
        self.hot_water_error: str | None = None

    async def _native_hot_water_state(self) -> dict[str, Any] | None:
        if self._http is None or self._http.closed:
            # The ESP8285 HTTP server closes connections aggressively. Avoid a
            # pooled stale socket and retry one idempotent request before
            # declaring the physical controller unavailable.
            self._http = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=4),
                connector=aiohttp.TCPConnector(force_close=True, limit=2),
            )
        token = self.settings.secret("hot_water_api_token")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        for attempt in range(2):
            try:
                async with self._http.get(
                    f"http://{self.settings.hot_water_host}/v1/state",
                    headers=headers,
                ) as response:
                    if response.status != 200:
                        self.hot_water_native = False
                        return None
                    payload = await response.json()
                self.hot_water_native = True
                return payload
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt == 0:
                    await asyncio.sleep(0.1)
                    continue
        self.hot_water_native = False
        return None

    async def refresh(self) -> None:
        # Reaching the fixed ESPHome bridge proves the local BLE controller is
        # available, not that the car is home. Presence comes from its local
        # parking sensor (or retained TeslaMate geofence while away).
        try:
            await self.tesla.connect()
            self.state.ev_ble_available = True
            self.ev_error = None
            presence = self.tesla.state_for("james car home")
            if presence is not None and hasattr(presence, "state"):
                self.state.ev_ble_home = bool(presence.state)
                self.state.ev_home = self.state.ev_ble_home
            garage_preset = self.tesla.state_for("garage preset")
            if garage_preset is not None and hasattr(garage_preset, "state"):
                value = float(garage_preset.state)
                self.state.ev_garage_preset = value if 2 <= value <= 31 else None
            unlocked = self.tesla.state_for_kind("binarysensor", "doors")
            if unlocked is not None and hasattr(unlocked, "state"):
                self.state.ev_car_locked = not bool(unlocked.state)
            charge_port = self.tesla.state_for_kind("binarysensor", "charge flap")
            if charge_port is not None and hasattr(charge_port, "state"):
                self.state.ev_charge_port_open = bool(charge_port.state)
            latch = self.tesla.state_for_kind("textsensor", "charge port latch state")
            if latch is not None and hasattr(latch, "state"):
                self.state.ev_charge_port_latch = str(latch.state)
            climate = self.tesla.state_for_kind("binarysensor", "climate")
            if climate is not None and hasattr(climate, "state"):
                self.state.ev_climate_on = bool(climate.state)
            for names, attr in (
                (("climate temperature",), "ev_climate_target_c"),
                (("interior",), "ev_interior_temp_c"),
                (("exterior",), "ev_exterior_temp_c"),
                (("range",), "ev_range_km"),
                (("minutes to limit",), "ev_minutes_to_limit"),
            ):
                current = self.tesla.state_for_kind("number" if attr == "ev_climate_target_c" else "sensor", *names)
                if current is not None and hasattr(current, "state"):
                    value = float(current.state)
                    if value == value:
                        setattr(self.state, attr, value)
            asleep = self.tesla.state_for_kind("binarysensor", "asleep")
            if asleep is not None and hasattr(asleep, "state"):
                self.state.ev_asleep = bool(asleep.state)
            windows = self.tesla.state_for_kind("binarysensor", "windows")
            if windows is not None and hasattr(windows, "state"):
                self.state.ev_windows_open = bool(windows.state)
            steering = self.tesla.state_for_kind("switch", "steering wheel heat")
            if steering is not None and hasattr(steering, "state"):
                self.state.ev_steering_heat_on = bool(steering.state)
            defrost = self.tesla.state_for_kind("switch", "defrost car")
            if defrost is not None and hasattr(defrost, "state"):
                self.state.ev_defrost_on = bool(defrost.state)
            charging_state = self.tesla.state_for_kind("textsensor", "charging state")
            if charging_state is not None and hasattr(charging_state, "state"):
                self.state.ev_charging_state = str(charging_state.state)
            for names, attr in ((('charging amps',), 'ev_amps'), (('charging limit',), 'ev_limit_pct')):
                current = self.tesla.state_for(*names)
                if current is not None and hasattr(current, "state"):
                    value = int(round(float(current.state)))
                    if attr == "ev_limit_pct":
                        # The Tesla BLE bridge reports 0 until it has obtained
                        # fresh vehicle data. Never let that transient erase the
                        # configured control limit and suppress charging.
                        if 50 <= value <= 100:
                            self.state.ev_limit_pct = value
                    else:
                        self.state.ev_amps = max(0, min(self.settings.ev_max_amps, value))
            charger = self.tesla.state_for("charger")
            if charger is not None and hasattr(charger, "state"):
                self.state.ev_charging = bool(charger.state)
        except Exception as exc:
            self.state.ev_ble_available = False
            for attr in (
                "ev_ble_home", "ev_garage_preset", "ev_car_locked",
                "ev_charge_port_open", "ev_charge_port_latch", "ev_climate_on",
                "ev_climate_target_c", "ev_interior_temp_c", "ev_exterior_temp_c",
                "ev_asleep", "ev_windows_open", "ev_steering_heat_on",
                "ev_defrost_on", "ev_range_km", "ev_minutes_to_limit",
                "ev_charging_state",
            ):
                setattr(self.state, attr, None)
            self.ev_error = f"Tesla BLE unavailable: {exc}"
            if self.tesla.client is not None or self.tesla.connected:
                await self.tesla.invalidate()
            LOG.debug("Tesla BLE unavailable: %s", exc)
        native = await self._native_hot_water_state()
        if native is not None:
            self.state.hot_water_available = True
            self.state.hot_water_on = bool(native.get("relay_on"))
            self.hot_water_error = None
        else:
            try:
                await self.hot_water.connect()
                self.state.hot_water_available = True
                self.hot_water_error = None
                relay = self.hot_water.state_for("hot water")
                if relay is not None and hasattr(relay, "state"):
                    self.state.hot_water_on = bool(relay.state)
            except Exception as exc:
                self.state.hot_water_available = False
                self.hot_water_error = f"hot-water controller unavailable: {exc}"
                if self.hot_water.client is not None or self.hot_water.connected:
                    await self.hot_water.invalidate()
                LOG.warning("Hot-water controller unavailable: %s", exc)

    async def vehicle_control(self, action: str, value: float | bool | None = None) -> str:
        """Apply a supported non-charging Tesla command over the sole BLE link."""

        if not self.state.ev_home or not self.state.ev_ble_available:
            raise RuntimeError("Tesla local BLE control is unavailable or the car is not home")
        async with self._vehicle_control_lock:
            if action == "lock":
                await self.tesla.lock(True, "lock car")
                self.state.ev_car_locked = True
            elif action == "unlock":
                await self.tesla.lock(False, "lock car")
                self.state.ev_car_locked = False
            elif action == "unlock_charge_port":
                await self.tesla.button("unlock charge port")
            elif action == "open_charge_port":
                await self.tesla.cover(True, "charge port")
            elif action == "close_charge_port":
                await self.tesla.cover(False, "charge port")
            elif action == "climate_on":
                await self.tesla.switch(True, "climate")
                self.state.ev_climate_on = True
            elif action == "climate_off":
                await self.tesla.switch(False, "climate")
                self.state.ev_climate_on = False
            elif action == "set_climate_temperature":
                temperature = float(value) if value is not None else 0.0
                if not 15 <= temperature <= 28:
                    raise ValueError("climate temperature must be between 15 and 28 C")
                await self.tesla.number(temperature, "climate temperature")
                self.state.ev_climate_target_c = temperature
            elif action == "steering_heat_on":
                await self.tesla.switch(True, "steering wheel heat")
                self.state.ev_steering_heat_on = True
            elif action == "steering_heat_off":
                await self.tesla.switch(False, "steering wheel heat")
                self.state.ev_steering_heat_on = False
            elif action == "defrost_on":
                await self.tesla.switch(True, "defrost car")
                self.state.ev_defrost_on = True
            elif action == "defrost_off":
                await self.tesla.switch(False, "defrost car")
                self.state.ev_defrost_on = False
            elif action == "vent_windows":
                await self.tesla.cover(True, "vent")
            elif action == "close_windows":
                await self.tesla.cover(False, "vent")
            elif action in {"wake", "flash_lights", "sound_horn"}:
                await self.tesla.button({
                    "wake": "wake up",
                    "flash_lights": "flash light",
                    "sound_horn": "sound horn",
                }[action])
            else:
                raise ValueError(f"unsupported Tesla BLE action: {action}")
        return "applied"

    async def set_ev(
        self,
        on: bool,
        amps: int,
        target_soc_pct: int | None = None,
        safety_reduction: bool = False,
        ramp_before_stop: bool = False,
    ) -> str:
        now = datetime.now(UTC)
        target = max(50, min(100, int(target_soc_pct or self.settings.ev_charge_limit_pct)))
        if self.tesla.reconnect_backoff_active:
            self.state.ev_ble_available = False
            return "actuator_unavailable_backoff"
        if not self.state.ev_home or not self.state.ev_ble_available or not self.state.ev_plugged:
            on = False
        current = int(self.state.ev_amps or 0)
        if ramp_before_stop and not on and self.state.ev_charging:
            if self._ev_stop_ramp_amps is None:
                # Capture a commanded ramp independent of noisy BLE current
                # feedback. The vehicle may report 6/7 A alternately while an
                # earlier command is settling; that must not reset the timer.
                self._ev_stop_ramp_amps = max(
                    self.settings.ev_min_amps,
                    min(self.settings.ev_max_amps, current) - 1,
                )
                self._ev_stop_ramp_last_step_at = now
                on = True
                amps = self._ev_stop_ramp_amps
            elif self._ev_stop_ramp_last_step_at and (now - self._ev_stop_ramp_last_step_at).total_seconds() < 30:
                on = True
                amps = self._ev_stop_ramp_amps
            elif self._ev_stop_ramp_amps > self.settings.ev_min_amps:
                self._ev_stop_ramp_amps -= 1
                self._ev_stop_ramp_last_step_at = now
                on = True
                amps = self._ev_stop_ramp_amps
            else:
                self._ev_stop_ramp_amps = None
                self._ev_stop_ramp_last_step_at = None
        elif on or not self.state.ev_charging:
            self._ev_stop_ramp_amps = None
            self._ev_stop_ramp_last_step_at = None
        amps = max(self.settings.ev_min_amps, min(self.settings.ev_max_amps, int(amps))) if on else 0
        if on and amps > current:
            if self._last_ev_upward_at and (now - self._last_ev_upward_at).total_seconds() < 30:
                amps = current
            else:
                amps = min(amps, current + 1 if current >= self.settings.ev_min_amps else self.settings.ev_min_amps)
                self._last_ev_upward_at = now
        elif on and amps < current:
            amps = max(amps, current - 1) if not safety_reduction else amps
        if self._last_ev_change_at and (now - self._last_ev_change_at).total_seconds() < 30 and not safety_reduction:
            return "held_30s"
        same_target = target == int(self.state.ev_limit_pct or 0)
        try:
            # The charging-current entity retains its configured value while
            # the charger switch is off. Off + same limit is therefore already
            # physically confirmed regardless of that dormant amp setting.
            if not on and not self.state.ev_charging and same_target:
                self.state.ev_lease_until = None
                self.ev_error = None
                return "semantic_noop_confirmed"
            if on == self.state.ev_charging and amps == current and same_target:
                if not on:
                    self.state.ev_lease_until = None
                    self.ev_error = None
                    return "semantic_noop_confirmed"
                self.state.ev_lease_until = now + timedelta(seconds=self.settings.ev_lease_seconds)
                if not self._last_ev_lease_renewal_at or (now - self._last_ev_lease_renewal_at).total_seconds() >= 60:
                    await self.tesla.action(
                        "energy_manager_lease",
                        {"charging": on, "amps": max(self.settings.ev_min_amps, amps), "limit": target},
                    )
                    self._last_ev_lease_renewal_at = now
                    self.state.ev_ble_available = True
                    self.ev_error = None
                    return "lease_renewed"
                self.ev_error = None
                return "semantic_noop_confirmed"
            if on:
                leased = await self.tesla.action(
                    "energy_manager_lease",
                    {"charging": True, "amps": amps, "limit": target},
                )
                if not leased:
                    await self.tesla.number(float(amps), "charging amps")
                    await self.tesla.number(float(target), "charging limit")
                    await self.tesla.switch(True, "charger")
                self.state.ev_lease_until = now + timedelta(seconds=self.settings.ev_lease_seconds)
            else:
                leased = await self.tesla.action(
                    "energy_manager_lease",
                    {"charging": False, "amps": max(self.settings.ev_min_amps, current), "limit": target},
                )
                if not same_target:
                    await self.tesla.number(float(target), "charging limit")
                # A native action acknowledgement means the ESP accepted the
                # service call, not that the BLE charger switch has changed.
                # Always issue the direct local switch-off as the idempotent
                # physical stop command as well. Fleet remains unused.
                await self.tesla.switch(False, "charger")
                self.state.ev_lease_until = None
            self.state.ev_charging = on
            self.state.ev_amps = amps
            self.state.ev_limit_pct = target
            self.state.ev_last_command_at = now
            self._last_ev_change_at = now
            self._last_ev_lease_renewal_at = now if on else None
            self.state.ev_ble_available = True
            self.ev_error = None
            return "applied"
        except Exception as exc:
            self.state.ev_ble_available = False
            self.ev_error = f"Tesla BLE command failed: {exc}"
            await self.tesla.invalidate()
            raise RuntimeError(self.ev_error) from exc

    async def set_hot_water(self, on: bool) -> str:
        if not self.hot_water_native and self.hot_water.reconnect_backoff_active:
            self.state.hot_water_available = False
            return "actuator_unavailable_backoff"
        try:
            if self.state.hot_water_on == on:
                if self.hot_water_native:
                    now = datetime.now(UTC)
                    if not self._last_hw_lease_renewal_at or (now - self._last_hw_lease_renewal_at).total_seconds() >= 60:
                        # OFF is a leased controller decision too. Renewing it
                        # prevents the firmware's outage fallback from fighting a
                        # healthy manager that is deliberately waiting for solar.
                        await self._native_hot_water_command(on)
                        self._last_hw_lease_renewal_at = now
                        self.state.hot_water_available = True
                        self.hot_water_error = None
                        return "lease_renewed"
                self.hot_water_error = None
                return "semantic_noop_confirmed"
            if self.hot_water_native:
                await self._native_hot_water_command(on)
            else:
                await self.hot_water.switch(on, "hot water")
            self.state.hot_water_on = on
            self.state.hot_water_last_transition = datetime.now(UTC)
            self._last_hw_command_at = self.state.hot_water_last_transition
            self._last_hw_lease_renewal_at = self.state.hot_water_last_transition
            self.state.hot_water_available = True
            self.hot_water_error = None
            return "applied"
        except Exception as exc:
            self.state.hot_water_available = False
            self.hot_water_error = f"hot-water command failed: {exc}"
            if not self.hot_water_native:
                await self.hot_water.invalidate()
            raise RuntimeError(self.hot_water_error) from exc

    async def _native_hot_water_command(self, on: bool) -> None:
        token = self.settings.secret("hot_water_api_token")
        if not token:
            raise RuntimeError("hot_water_api_token secret is missing")
        assert self._http
        for attempt in range(2):
            try:
                async with self._http.post(
                    f"http://{self.settings.hot_water_host}/v1/command",
                    params={
                        "state": "on" if on else "off",
                        "lease": "300",
                        "epoch": str(int(datetime.now(UTC).timestamp())),
                    },
                    headers={"Authorization": f"Bearer {token}"},
                ) as response:
                    await response.read()
                    if response.status != 200:
                        raise RuntimeError(f"native hot-water HTTP {response.status}")
                return
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt == 0:
                    await asyncio.sleep(0.1)
                    continue
                raise

    async def set_hot_water_confirmed_seconds(self, seconds: int) -> None:
        if not self.hot_water_native:
            return
        token = self.settings.secret("hot_water_api_token")
        if not token or self._http is None:
            raise RuntimeError("hot-water confirmation endpoint is not authenticated")
        for attempt in range(2):
            try:
                async with self._http.post(
                    f"http://{self.settings.hot_water_host}/v1/confirm",
                    params={"seconds": str(max(0, seconds))},
                    headers={"Authorization": f"Bearer {token}"},
                ) as response:
                    await response.read()
                    if response.status != 200:
                        raise RuntimeError(f"native hot-water confirmation HTTP {response.status}")
                return
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt == 0:
                    await asyncio.sleep(0.1)
                    continue
                raise

    async def expire_ev_lease(self) -> None:
        if self.state.ev_lease_until and datetime.now(UTC) >= self.state.ev_lease_until:
            await self.set_ev(False, 0, safety_reduction=True)

    async def close(self) -> None:
        await asyncio.gather(self.tesla.close(), self.hot_water.close(), return_exceptions=True)
        if self._http:
            await self._http.close()
