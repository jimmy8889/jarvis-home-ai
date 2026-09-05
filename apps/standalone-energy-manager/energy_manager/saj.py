from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import logging
import struct
import time
from typing import Iterable
from zoneinfo import ZoneInfo

from pymodbus.client import AsyncModbusTcpClient

from .config import Settings
from .models import Command, Telemetry

LOG = logging.getLogger(__name__)

DEVICE_STATUSES = {
    0: "initialization", 1: "waiting", 2: "running", 3: "off_grid",
    4: "on_grid", 5: "fault", 6: "updating", 7: "test",
    8: "self_checking", 9: "reset",
}

# Validated against stanus74/home-assistant-saj-h2-modbus. Unknown set bits are
# deliberately preserved instead of being silently discarded.
FAULT_MESSAGES: tuple[dict[int, str], ...] = (
    {
        0x00000001: "Lost communication H-M", 0x00000002: "Meter communication lost",
        0x00000004: "HMI EEPROM error", 0x00000008: "HMI RTC error",
        0x00000010: "BMS device error", 0x00000020: "BMS communication warning",
        0x00000800: "R phase voltage high", 0x00001000: "R phase voltage low",
        0x00002000: "S phase voltage high", 0x00004000: "S phase voltage low",
        0x00008000: "T phase voltage high", 0x00010000: "T phase voltage low",
        0x00020000: "Grid frequency high", 0x00040000: "Grid frequency low",
        0x00800000: "No grid", 0x01000000: "PV input mode fault",
        0x02000000: "PV current high", 0x04000000: "PV voltage fault",
        0x08000000: "Bus voltage high",
    },
    {
        0x00000001: "Master bus voltage high", 0x00000002: "Master bus voltage low",
        0x00000004: "Master grid phase error", 0x00000008: "Master PV voltage high",
        0x00000010: "Master islanding error", 0x00000040: "Master PV input error",
        0x00000080: "DSP-PC communication lost", 0x00000100: "Hardware bus voltage high",
        0x00000200: "Hardware PV current high", 0x00000800: "Hardware inverter current high",
        0x00004000: "Grid neutral-earth voltage error", 0x00008000: "DRM0 error",
        0x00010000: "Fan 1 error", 0x00020000: "Fan 2 error",
        0x00040000: "Fan 3 error", 0x00080000: "Fan 4 error",
        0x00100000: "Arc error", 0x00200000: "Software PV current high",
        0x00400000: "Battery voltage high", 0x00800000: "Battery current high",
        0x01000000: "Battery charge voltage high", 0x02000000: "Battery overload",
        0x04000000: "Battery soft-connect timeout", 0x08000000: "Output overload",
        0x10000000: "Battery open circuit", 0x20000000: "Battery discharge voltage low",
        0x40000000: "Authority expired", 0x80000000: "Control communication lost",
    },
    {
        0x80000000: "Bus voltage balance error", 0x40000000: "Isolation error",
        0x20000000: "Phase 3 DCI error", 0x10000000: "Phase 2 DCI error",
        0x08000000: "Phase 1 DCI error", 0x04000000: "GFCI error",
        0x00800000: "No grid error", 0x00400000: "Phase 3 DC component error",
        0x00200000: "Phase 2 DC component error", 0x00100000: "Phase 1 DC component error",
        0x00040000: "Grid frequency low", 0x00020000: "Grid frequency high",
        0x00008000: "Off-grid voltage low", 0x00004000: "Ten-minute grid overvoltage",
        0x00002000: "Phase 3 voltage low", 0x00001000: "Phase 3 voltage high",
        0x00000800: "Phase 2 voltage low", 0x00000400: "Phase 2 voltage high",
        0x00000200: "Phase 1 voltage low", 0x00000100: "Phase 1 voltage high",
        0x00000080: "Current sensor error", 0x00000040: "DCI device error",
        0x00000020: "GFCI device error", 0x00000010: "Master-slave communication error",
        0x00000008: "Temperature low", 0x00000004: "Temperature high",
        0x00000002: "EEPROM error", 0x00000001: "Relay error",
    },
)


def decode_fault_words(words: tuple[int, int, int]) -> tuple[str, ...]:
    active: list[str] = []
    for word_index, word in enumerate(words):
        known = 0
        for mask, message in FAULT_MESSAGES[word_index].items():
            known |= mask
            if word & mask:
                active.append(message)
        unknown = word & ~known & 0xFFFFFFFF
        for bit in range(32):
            if unknown & (1 << bit):
                active.append(f"Unknown fault word {word_index} bit {bit}")
    return tuple(active)


def signed16(value: int) -> int:
    return value - 65536 if value & 0x8000 else value


def uint32(registers: list[int], index: int) -> int:
    return (registers[index] << 16) | registers[index + 1]


def select_site_load(total_kw: float, backup_kw: float, pv_kw: float, battery_kw: float, grid_kw: float) -> tuple[float, str, float]:
    """Select SAJ TotalLoad as whole-house demand; backup is diagnostic only."""
    balanced_kw = max(0.0, pv_kw + battery_kw + grid_kw)
    if 0.0 <= total_kw < 150.0:
        return total_kw, "total_house_load", total_kw - balanced_kw
    return balanced_kw, "power_balance_fallback", 0.0


def forced_discharge_register_target_kw(command: Command) -> float:
    """Translate the site contract to the SAJ forced-discharge register.

    Physical commissioning showed that the SAJ schedule power is the power
    exported beyond local demand: the inverter separately supplies backup
    loads.  Profitable export therefore writes the site-export target, not
    ``site export + house load``.  Load-segregation modes (for example the
    hot-water grid rescue) deliberately publish a zero site target and retain
    their bounded battery-power target as the register target.
    """
    if command.site_export_target_kw > 0.05:
        return command.site_export_target_kw
    return command.battery_target_kw


def semantic_hash(command: Command) -> str:
    physical = {
        "mode": command.mode,
        "forced_power_target_kw": round(
            forced_discharge_register_target_kw(command)
            if command.mode == "export"
            else command.battery_target_kw,
            1,
        ),
        "protected_soc_pct": int(command.protected_soc_pct + 0.999),
        "zero_export": command.zero_export,
        "pv_charge_limit_raw": max(0, min(1100, int(command.pv_charge_limit_raw))),
    }
    if command.mode in {"export", "grid_charge"} and command.expires_at is not None:
        physical["force_interval_start"] = int(command.generated_at.timestamp()) // 300 * 300
        physical["force_interval_end"] = int(command.expires_at.timestamp())
    return hashlib.sha256(json.dumps(physical, sort_keys=True).encode()).hexdigest()[:20]


@dataclass(frozen=True)
class RegisterTarget:
    address: int
    value: int
    label: str


class SajController:
    """Single-owner, serialized SAJ Modbus reader/writer.

    Register addresses and scaling are derived from the deployed
    stanus74/home-assistant-saj-h2-modbus integration. Schedule mask/power
    registers are always written as complete values, never with a partial
    field update.
    """

    APP_SELF_CONSUME = 0
    APP_FORCE = 1
    REG_CHARGE_ENABLE = 0x3604
    REG_DISCHARGE_ENABLE = 0x3605
    REG_CHARGE_START = 0x3606
    REG_CHARGE_END = 0x3607
    REG_CHARGE_MASK_POWER = 0x3608
    REG_DISCHARGE_START = 0x361B
    REG_DISCHARGE_END = 0x361C
    REG_DISCHARGE_MASK_POWER = 0x361D
    REG_APP_MODE = 0x3647
    REG_RESERVE = 0x3644
    REG_PV_CHARGE_LIMIT = 0x364D
    REG_BATTERY_DISCHARGE_LIMIT = 0x364E
    REG_GRID_DISCHARGE_LIMIT = 0x3650
    REG_EXPORT_LIMIT = 0x365A
    REG_ANTI_REFLUX = 0x365C

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = self._new_client()
        self.lock = asyncio.Lock()
        self.last: Telemetry | None = None
        self.last_applied_hash: str | None = None
        self.last_write_at: datetime | None = None
        self.last_confirmed_at: datetime | None = None
        self.last_protected_reserve_pct = settings.battery_floor_pct
        self._sequence = 0
        self._last_realtime_at = 0.0
        self._last_battery_at = 0.0
        self._last_controls_at = 0.0
        self._last_energy_at = 0.0
        self._last_identity_at = 0.0
        self._realtime: list[int] | None = None
        self._battery: list[int] | None = None
        self._controls: list[int] | None = None
        self._enable: list[int] | None = None
        self._energy: dict[str, float] = {}
        self._identity: dict[str, object] = {}
        self._combined_read_supported: bool | None = None
        self.read_errors = 0
        self.reconnects = 0
        self._last_fault = "none"
        self._grid_candidate = "unknown"
        self._grid_candidate_count = 0
        self._grid_state = "unknown"

    def _new_client(self) -> AsyncModbusTcpClient:
        return AsyncModbusTcpClient(
            self.settings.saj_host,
            port=self.settings.saj_port,
            timeout=3,
            retries=1,
        )

    async def connect(self) -> None:
        if not self.client.connected:
            # Replace interrupted transports rather than accumulating sockets
            # to the inverter inside the single controller process.
            self.client.close()
            self.client = self._new_client()
            if not await self.client.connect():
                raise ConnectionError(f"SAJ unavailable at {self.settings.saj_host}:{self.settings.saj_port}")
            self.reconnects += 1

    async def close(self) -> None:
        self.client.close()

    async def _read(self, address: int, count: int) -> list[int]:
        await self.connect()
        try:
            response = await self.client.read_holding_registers(address=address, count=count, device_id=self.settings.saj_unit)
        except TypeError:
            response = await self.client.read_holding_registers(address=address, count=count, slave=self.settings.saj_unit)
        if response.isError():
            raise IOError(f"SAJ read 0x{address:04x}/{count}: {response}")
        return list(response.registers)

    async def _write(self, target: RegisterTarget) -> None:
        await self.connect()
        try:
            response = await self.client.write_register(address=target.address, value=target.value, device_id=self.settings.saj_unit)
        except TypeError:
            response = await self.client.write_register(address=target.address, value=target.value, slave=self.settings.saj_unit)
        if response.isError():
            raise IOError(f"SAJ write {target.label} 0x{target.address:04x}={target.value}: {response}")

    async def _read_target(self, target: RegisterTarget) -> int:
        return (await self._read(target.address, 1))[0]

    async def _write_and_confirm(self, target: RegisterTarget) -> None:
        """Write once, confirm, then perform one controlled reassertion."""
        await self._write(target)
        await asyncio.sleep(0.05)
        actual = await self._read_target(target)
        if actual == target.value:
            return
        LOG.warning(
            "SAJ confirmation mismatch for %s: requested=%s actual=%s; reasserting once",
            target.label,
            target.value,
            actual,
        )
        await self._write(target)
        await asyncio.sleep(0.1)
        actual = await self._read_target(target)
        if actual != target.value:
            raise IOError(
                f"SAJ confirmation failed for {target.label}: requested={target.value} actual={actual}"
            )

    async def _fast_frame(self) -> tuple[list[int], str]:
        if self._combined_read_supported is not False:
            try:
                registers = await self._read(0x406E, 64)
                self._combined_read_supported = True
                return registers, "combined"
            except Exception:
                if self._combined_read_supported is True:
                    raise
                LOG.warning("SAJ combined fast block unsupported; using bounded split reads")
                self._combined_read_supported = False
        pv = await self._read(0x406E, 15)
        flow = await self._read(0x4095, 25)
        combined = [0] * 64
        combined[:15] = pv
        combined[0x4095 - 0x406E : 0x4095 - 0x406E + 25] = flow
        return combined, "split"

    async def _refresh_slow_blocks(self, now_mono: float) -> None:
        if self._realtime is None or now_mono - self._last_realtime_at >= 5:
            self._realtime = await self._read(0x4004, 19)
            self._last_realtime_at = now_mono
        if self._battery is None or now_mono - self._last_battery_at >= 10:
            self._battery = await self._read(0xA000, 56)
            self._last_battery_at = now_mono
        if self._controls is None or now_mono - self._last_controls_at >= 10:
            self._controls = await self._read(0x3636, 43)
            self._enable = await self._read(0x3604, 2)
            self._last_controls_at = now_mono
        if not self._energy or now_mono - self._last_energy_at >= 60:
            values = await self._read(0x40BF, 64)
            names = (
                "pv_today_kwh", "pv_month_kwh", "pv_year_kwh", "pv_total_kwh",
                "battery_charge_today_kwh", "battery_charge_month_kwh",
                "battery_charge_year_kwh", "battery_charge_total_kwh",
                "battery_discharge_today_kwh", "battery_discharge_month_kwh",
                "battery_discharge_year_kwh", "battery_discharge_total_kwh",
                "inverter_generation_today_kwh", "inverter_generation_month_kwh",
                "inverter_generation_year_kwh", "inverter_generation_total_kwh",
                "total_load_today_kwh", "total_load_month_kwh",
                "total_load_year_kwh", "total_load_total_kwh",
                "backup_load_today_kwh", "backup_load_month_kwh",
                "backup_load_year_kwh", "backup_load_total_kwh",
                "sell_today_kwh", "sell_month_kwh", "sell_year_kwh", "sell_total_kwh",
                "feed_in_today_kwh", "feed_in_month_kwh", "feed_in_year_kwh", "feed_in_total_kwh",
            )
            self._energy = {name: uint32(values, index * 2) * 0.01 for index, name in enumerate(names)}
            phase_values = await self._read(0x4137, 64)
            phase_names = (
                "pv2_today_kwh", "pv2_month_kwh", "pv2_year_kwh", "pv2_total_kwh",
                "pv3_today_kwh", "pv3_month_kwh", "pv3_year_kwh", "pv3_total_kwh",
                "sell_2_today_kwh", "sell_2_month_kwh", "sell_2_year_kwh", "sell_2_total_kwh",
                "sell_3_today_kwh", "sell_3_month_kwh", "sell_3_year_kwh", "sell_3_total_kwh",
                "feed_in_2_today_kwh", "feed_in_2_month_kwh", "feed_in_2_year_kwh", "feed_in_2_total_kwh",
                "feed_in_3_today_kwh", "feed_in_3_month_kwh", "feed_in_3_year_kwh", "feed_in_3_total_kwh",
                "grid_import_today_kwh", "grid_import_month_kwh", "grid_import_year_kwh", "grid_import_total_kwh",
                "grid_export_today_kwh", "grid_export_month_kwh", "grid_export_year_kwh", "grid_export_total_kwh",
            )
            self._energy.update(
                {name: uint32(phase_values, index * 2) * 0.01 for index, name in enumerate(phase_names)}
            )
            self._last_energy_at = now_mono
        if not self._identity or now_mono - self._last_identity_at >= 86400:
            identity = await self._read(0x8F00, 29)

            def ascii10(index: int) -> str:
                raw = b"".join(struct.pack(">H", value) for value in identity[index:index + 10])
                return raw.decode("ascii", errors="replace").replace("\x00", "").strip()

            self._identity = {
                "device_type": identity[0], "sub_type": identity[1],
                "protocol_version": round(identity[2] * 0.001, 3),
                "serial_number": ascii10(3), "product_code": ascii10(13),
                "display_software": round(identity[23] * 0.001, 3),
                "master_software": round(identity[24] * 0.001, 3),
                "slave_software": round(identity[25] * 0.001, 3),
            }
            self._last_identity_at = now_mono

    def _stable_grid_state(self, candidate: str) -> str:
        if candidate == self._grid_candidate:
            self._grid_candidate_count += 1
        else:
            self._grid_candidate = candidate
            self._grid_candidate_count = 1
        if candidate == "unknown" or self._grid_candidate_count >= 2:
            self._grid_state = candidate
        return self._grid_state

    async def poll(self) -> Telemetry:
        sample_started = datetime.now(UTC)
        cycle_started = time.monotonic()
        self._sequence += 1
        try:
            async with self.lock:
                fast, fast_mode = await self._fast_frame()
                fast_completed = datetime.now(UTC)
                meter = await self._read(0xA03D, 18)
                meter_completed = datetime.now(UTC)
                await self._refresh_slow_blocks(time.monotonic())
        except Exception:
            self.read_errors += 1
            raise

        realtime = self._realtime or [0] * 19
        battery = self._battery or [0] * 56
        controls = self._controls or [0] * 43
        enable = self._enable or [0, 0]
        flow_offset = 0x4095 - 0x406E

        fault_words = (uint32(realtime, 1), uint32(realtime, 3), uint32(realtime, 5))
        active_faults = decode_fault_words(fault_words)
        if active_faults:
            self._last_fault = active_faults[-1]

        pv1_w, pv2_w, pv3_w = (float(fast[index]) for index in (5, 8, 11))
        total_load_kw = signed16(fast[flow_offset + 11]) / 1000
        pv_total_kw = signed16(fast[flow_offset + 16]) / 1000
        battery_kw = signed16(fast[flow_offset + 17]) / 1000
        flow_grid_kw = signed16(fast[flow_offset + 18]) / 1000
        inverter_kw = signed16(fast[flow_offset + 20]) / 1000
        backup_raw = fast[flow_offset + 22]
        backup_kw = signed16(backup_raw) / 1000
        backup_valid = backup_raw != 0xFFFF and 0 <= backup_kw < 150

        phase_power = tuple(signed16(meter[index]) / 1000 for index in (2, 8, 14))
        phase_voltage = tuple(float(meter[index]) * 0.1 for index in (0, 6, 12))
        phase_current = tuple(signed16(meter[index]) * 0.01 for index in (1, 7, 13))
        phase_frequency = tuple(float(meter[index]) * 0.01 for index in (5, 11, 17))
        phase_pf = tuple(signed16(meter[index]) * 0.001 for index in (4, 10, 16))
        phase_present = tuple(
            180 <= voltage <= 275 and 45 <= frequency <= 55
            for voltage, frequency in zip(phase_voltage, phase_frequency)
        )
        present_count = sum(phase_present)
        raw_mode = int(realtime[0])
        candidate = "online" if present_count == 3 else "partial" if present_count else "offline"
        if raw_mode == 3:
            candidate = "offline"
        grid_state = self._stable_grid_state(candidate)
        meter_grid_kw = sum(phase_power)
        grid_kw = meter_grid_kw if abs(meter_grid_kw) < 150 else flow_grid_kw
        selected_load_kw, load_source, load_balance_error_kw = select_site_load(
            total_load_kw, backup_kw if backup_valid else 200.0, pv_total_kw, battery_kw, grid_kw
        )

        battery_faults = tuple(int(battery[index]) for index in (2, 4, 6, 8))
        battery_warnings = tuple(int(battery[index]) for index in (3, 5, 7, 9))
        soc = float(battery[12]) * 0.01
        soh = float(battery[13]) * 0.01
        completed = datetime.now(UTC)
        telemetry = Telemetry(
            measured_at=meter_completed,
            pv_kw=max(0.0, pv_total_kw), pv1_kw=max(0.0, pv1_w / 1000),
            pv2_kw=max(0.0, pv2_w / 1000), pv3_kw=max(0.0, pv3_w / 1000),
            pv_north_kw=max(0.0, pv1_w / 1000), pv_south_kw=max(0.0, (pv2_w + pv3_w) / 1000),
            load_kw=selected_load_kw, load_total_kw=max(0.0, total_load_kw),
            load_backup_kw=backup_kw if backup_valid else None, load_source=load_source,
            load_balance_error_kw=load_balance_error_kw, grid_kw=grid_kw,
            flow_grid_kw=flow_grid_kw, meter_phase_power_kw=phase_power,
            meter_phase_voltage_v=phase_voltage, meter_phase_current_a=phase_current,
            meter_phase_frequency_hz=phase_frequency, meter_phase_power_factor=phase_pf,
            grid_state=grid_state, grid_online=grid_state == "online", grid_phase_present=phase_present,
            battery_kw=battery_kw, inverter_kw=inverter_kw, soc_pct=soc, soh_pct=soh,
            battery_temperature_c=signed16(battery[16]) * 0.1,
            battery_voltage_v=float(battery[14]) * 0.1, battery_cycle_count=int(battery[17]),
            inverter_temperature_c=signed16(realtime[12]) * 0.1,
            environment_temperature_c=signed16(realtime[13]) * 0.1,
            gfci_ma=float(realtime[14]),
            isolation_resistance_kohm=tuple(float(realtime[index]) for index in (15, 16, 17, 18)),
            fault_words=fault_words, active_faults=active_faults, fault_count=len(active_faults),
            fault_severity="fault" if active_faults or any(battery_faults) else "warning" if any(battery_warnings) else "none",
            last_fault=self._last_fault, battery_fault_words=battery_faults,
            battery_warning_words=battery_warnings,
            inverter_status=DEVICE_STATUSES.get(raw_mode, f"unknown_{raw_mode}"),
            sample_sequence=self._sequence, sample_started_at=sample_started,
            sample_completed_at=completed,
            sample_skew_ms=max(0.0, (meter_completed - fast_completed).total_seconds() * 1000),
            cycle_duration_ms=max(0.0, (time.monotonic() - cycle_started) * 1000),
            fast_read_mode=fast_mode, modbus_read_errors=self.read_errors,
            modbus_reconnects=self.reconnects, energy_counters=dict(self._energy),
            inverter_identity=dict(self._identity), app_mode=int(controls[17]),
            anti_reflux_mode=int(controls[38]), export_limit=int(controls[36]),
            charge_enabled=bool(enable[0] & 1), discharge_enabled=bool(enable[1] & 1),
        )
        self.last = telemetry
        return telemetry

    async def _read_guarded(self, address: int) -> int:
        async with self.lock:
            return (await self._read(address, 1))[0]

    def _force_window(self, command: Command) -> tuple[int, int] | None:
        if command.expires_at is None:
            return None
        interval_start = datetime.fromtimestamp(int(command.generated_at.timestamp()) // 300 * 300, UTC)
        local_start = interval_start.astimezone(ZoneInfo(self.settings.timezone))
        local_end = command.expires_at.astimezone(ZoneInfo(self.settings.timezone))
        if local_end <= local_start or local_end.date() != local_start.date():
            return None
        if (local_end - local_start).total_seconds() > 10 * 60:
            return None
        return (local_start.hour << 8) | local_start.minute, (local_end.hour << 8) | local_end.minute

    def targets_for(self, command: Command) -> list[RegisterTarget]:
        reserve = max(5, min(100, int(command.protected_soc_pct + 0.999)))
        register_target_kw = (
            forced_discharge_register_target_kw(command)
            if command.mode == "export"
            else command.battery_target_kw
        )
        percent = max(0, min(100, round(abs(register_target_kw) / 30 * 100)))
        force_window = self._force_window(command)
        day_power = (0x7F << 8) | percent

        # Stop forced modes first, then establish safety/export policy, then
        # enable at most one forced direction last.
        result = [
            RegisterTarget(self.REG_CHARGE_ENABLE, 0, "stop charge"),
            RegisterTarget(self.REG_DISCHARGE_ENABLE, 0, "stop discharge"),
            RegisterTarget(self.REG_RESERVE, reserve, "protected reserve"),
            RegisterTarget(self.REG_BATTERY_DISCHARGE_LIMIT, 1100, "battery discharge allowance"),
            RegisterTarget(self.REG_GRID_DISCHARGE_LIMIT, 1100, "grid discharge allowance"),
        ]
        if command.zero_export:
            result.extend((
                RegisterTarget(self.REG_ANTI_REFLUX, 1, "anti reflux"),
                RegisterTarget(self.REG_EXPORT_LIMIT, 0, "zero export"),
            ))
        else:
            result.extend((
                RegisterTarget(self.REG_EXPORT_LIMIT, 1100, "normal export limit"),
                RegisterTarget(self.REG_ANTI_REFLUX, 0, "anti reflux disabled"),
            ))
        result.append(RegisterTarget(
            self.REG_PV_CHARGE_LIMIT,
            max(0, min(1100, int(command.pv_charge_limit_raw))),
            "PV battery charge power limit",
        ))

        if command.mode == "export" and command.battery_target_kw > 0.05 and force_window:
            window_start, window_end = force_window
            result.extend((
                RegisterTarget(self.REG_DISCHARGE_START, window_start, "discharge start"),
                RegisterTarget(self.REG_DISCHARGE_END, window_end, "discharge end"),
                RegisterTarget(self.REG_DISCHARGE_MASK_POWER, day_power, "discharge power"),
                RegisterTarget(self.REG_APP_MODE, self.APP_FORCE, "force mode"),
                RegisterTarget(self.REG_DISCHARGE_ENABLE, 1, "enable discharge"),
            ))
        elif command.mode == "grid_charge" and command.battery_target_kw < -0.05 and force_window:
            window_start, window_end = force_window
            result.extend((
                RegisterTarget(self.REG_CHARGE_START, window_start, "charge start"),
                RegisterTarget(self.REG_CHARGE_END, window_end, "charge end"),
                RegisterTarget(self.REG_CHARGE_MASK_POWER, day_power, "charge power"),
                RegisterTarget(self.REG_APP_MODE, self.APP_FORCE, "force mode"),
                RegisterTarget(self.REG_CHARGE_ENABLE, 1, "enable charge"),
            ))
        else:
            result.append(RegisterTarget(self.REG_APP_MODE, self.APP_SELF_CONSUME, "self consumption"))
        return result

    def final_targets_for(self, command: Command) -> list[RegisterTarget]:
        """Return the final value for each register in an ordered transaction."""
        final: dict[int, RegisterTarget] = {}
        for target in self.targets_for(command):
            final[target.address] = target
        return list(final.values())

    @staticmethod
    def _requires_unexpired_lease(command: Command) -> bool:
        return bool(
            command.mode in {"export", "grid_charge"}
            or command.zero_export
            or command.pv_charge_limit_raw != 1100
        )

    def _assert_command_fresh(self, command: Command) -> None:
        if (
            self._requires_unexpired_lease(command)
            and (command.expires_at is None or command.expires_at <= datetime.now(UTC))
        ):
            raise RuntimeError("refusing expired or unbounded material SAJ command")

    async def apply(self, command: Command, force: bool = False, allow_when_disabled: bool = False) -> str:
        self._assert_command_fresh(command)
        physical_hash = semantic_hash(command)
        command.battery_semantic_hash = physical_hash
        if physical_hash == self.last_applied_hash and not force:
            if not self.settings.control_enabled and not allow_when_disabled:
                return "control_disabled"
            if self.last_confirmed_at and (datetime.now(UTC) - self.last_confirmed_at).total_seconds() < 30:
                return "semantic_noop_confirmed"
            async with self.lock:
                confirmed = True
                for target in self.final_targets_for(command):
                    if await self._read_target(target) != target.value:
                        confirmed = False
                        break
                if confirmed:
                    self.last_confirmed_at = datetime.now(UTC)
                    return "semantic_noop_confirmed"
            force = True
        if not self.settings.control_enabled and not allow_when_disabled:
            return "control_disabled"
        if (self.last is None or not self.last.healthy) and not allow_when_disabled:
            raise RuntimeError("refusing SAJ writes without healthy live telemetry")
        try:
            async with self.lock:
                for target in self.targets_for(command):
                    # The serialized register transaction can straddle a NEM
                    # boundary. Never enable or leave a material command after
                    # its lease has elapsed.
                    self._assert_command_fresh(command)
                    await self._write_and_confirm(target)
                self.last_applied_hash = physical_hash
                self.last_protected_reserve_pct = command.protected_soc_pct
                self.last_write_at = datetime.now(UTC)
                self.last_confirmed_at = self.last_write_at
        except Exception:
            self.last_applied_hash = None
            self.last_confirmed_at = None
            # Do not recurse through apply(): directly restore normal household
            # battery support using only the hard floor.
            fallback = Command(
                mode="self_consume",
                # A failure while applying a live negative-FIT command must
                # not release anti-reflux and start paid export. The service
                # watchdog will release it when the price lease is stale.
                zero_export=command.zero_export,
                protected_soc_pct=self.settings.battery_floor_pct,
                reason="confirmation_failure_safe_state",
            )
            async with self.lock:
                for target in self.targets_for(fallback):
                    await self._write(target)
                    await asyncio.sleep(0.05)
            raise
        return "applied"

    async def safe_state(self, negative_fit: bool = False, emergency: bool = False) -> str:
        now = datetime.now(UTC)
        command = Command(
            mode="self_consume",
            zero_export=negative_fit,
            protected_soc_pct=max(self.settings.battery_floor_pct, self.last_protected_reserve_pct),
            reason="safe_state",
            generated_at=now,
            expires_at=(
                datetime.fromtimestamp(((int(now.timestamp()) // 300) + 1) * 300, UTC)
                if negative_fit else None
            ),
        )
        return await self.apply(command, force=True, allow_when_disabled=emergency)
