from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import shlex
import time
from typing import Any

from .config import Settings


@dataclass
class NutPowerState:
    measured_at: datetime | None = None
    available: bool = False
    ups_name: str | None = None
    raw_real_power_w: float | None = None
    server_rack_power_w: float | None = None
    efficiency_pct: float | None = None
    legacy_80_power_w: float | None = None
    confidence: str = "unavailable"
    load_pct: float | None = None
    battery_charge_pct: float | None = None
    battery_runtime_seconds: float | None = None
    input_voltage_v: float | None = None
    output_voltage_v: float | None = None
    status: str | None = None
    error: str | None = None
    consecutive_failures: int = 0
    sample_sequence: int = 0
    poll_duration_ms: float | None = None
    variables: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["measured_at"] = self.measured_at.isoformat() if self.measured_at else None
        result["age_seconds"] = max(0.0, (datetime.now(UTC) - self.measured_at).total_seconds()) if self.measured_at else None
        return result


def parse_ups_lines(lines: list[str]) -> list[str]:
    names: list[str] = []
    for line in lines:
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if len(parts) >= 2 and parts[0] == "UPS":
            names.append(parts[1])
    return names


def parse_var_lines(lines: list[str], ups_name: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if len(parts) >= 4 and parts[0] == "VAR" and parts[1] == ups_name:
            values[parts[2]] = parts[3]
    return values


class NutCollector:
    """Small read-only client for the public Network UPS Tools protocol."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.state = NutPowerState()
        self._consecutive_failures = 0
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._ups_name: str | None = None
        self._sample_sequence = 0

    async def _connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if self._reader is not None and self._writer is not None and not self._writer.is_closing():
            return self._reader, self._writer
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.settings.nut_host, self.settings.nut_port),
            timeout=3,
        )
        return self._reader, self._writer

    async def close(self) -> None:
        writer, self._reader, self._writer = self._writer, None, None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _list(self, command: str, end_marker: str) -> list[str]:
        reader, writer = await self._connect()
        try:
            writer.write((command + "\n").encode("ascii"))
            await writer.drain()
            lines: list[str] = []
            while True:
                raw = await asyncio.wait_for(reader.readline(), timeout=3)
                if not raw:
                    raise ConnectionError("NUT connection closed before list completed")
                line = raw.decode("utf-8", errors="replace").strip()
                if line.startswith("ERR "):
                    raise RuntimeError(f"NUT {line}")
                if line == end_marker:
                    return lines
                if not line.startswith("BEGIN LIST "):
                    lines.append(line)
        except Exception:
            await self.close()
            raise

    async def poll(self) -> NutPowerState:
        started = time.perf_counter()
        try:
            configured = self.settings.nut_ups_name.strip()
            if configured:
                ups_name = configured
            elif self._ups_name:
                ups_name = self._ups_name
            else:
                lines = await self._list("LIST UPS", "END LIST UPS")
                names = parse_ups_lines(lines)
                if not names:
                    raise RuntimeError("NUT returned no UPS devices")
                ups_name = names[0]
                self._ups_name = ups_name
            lines = await self._list(f"LIST VAR {ups_name}", f"END LIST VAR {ups_name}")
            values = parse_var_lines(lines, ups_name)
            if "ups.realpower" not in values:
                raise RuntimeError("NUT ups.realpower is unavailable")
            raw_power = max(0.0, float(values["ups.realpower"]))
            try:
                efficiency_pct = float(values["ups.efficiency"])
            except (KeyError, TypeError, ValueError):
                efficiency_pct = 0.0
            efficiency_valid = 1.0 <= efficiency_pct <= 100.0
            server_power = raw_power / (efficiency_pct / 100.0) if efficiency_valid else raw_power
            load_pct = float(values["ups.load"]) if "ups.load" in values else None
            def optional_float(name: str) -> float | None:
                try:
                    return float(values[name])
                except (KeyError, TypeError, ValueError):
                    return None

            self._consecutive_failures = 0
            self._sample_sequence += 1
            self.state = NutPowerState(
                measured_at=datetime.now(UTC),
                available=True,
                ups_name=ups_name,
                raw_real_power_w=raw_power,
                server_rack_power_w=server_power,
                efficiency_pct=efficiency_pct if efficiency_valid else None,
                legacy_80_power_w=raw_power / 0.80,
                confidence="live_efficiency" if efficiency_valid else "degraded_raw_output",
                load_pct=load_pct,
                battery_charge_pct=optional_float("battery.charge"),
                battery_runtime_seconds=optional_float("battery.runtime"),
                input_voltage_v=optional_float("input.voltage"),
                output_voltage_v=optional_float("output.voltage"),
                status=values.get("ups.status"),
                error=None,
                consecutive_failures=0,
                sample_sequence=self._sample_sequence,
                poll_duration_ms=(time.perf_counter() - started) * 1000,
                variables=values,
            )
        except Exception as exc:
            self._consecutive_failures += 1
            self.state = NutPowerState(
                measured_at=self.state.measured_at,
                available=self.state.measured_at is not None and self._consecutive_failures < 3,
                ups_name=self.state.ups_name,
                raw_real_power_w=self.state.raw_real_power_w,
                server_rack_power_w=self.state.server_rack_power_w,
                efficiency_pct=self.state.efficiency_pct,
                legacy_80_power_w=self.state.legacy_80_power_w,
                confidence="stale_last_good" if self._consecutive_failures < 3 and self.state.measured_at else "unavailable",
                load_pct=self.state.load_pct,
                battery_charge_pct=self.state.battery_charge_pct,
                battery_runtime_seconds=self.state.battery_runtime_seconds,
                input_voltage_v=self.state.input_voltage_v,
                output_voltage_v=self.state.output_voltage_v,
                status=self.state.status,
                error=f"{type(exc).__name__}: {exc}",
                consecutive_failures=self._consecutive_failures,
                sample_sequence=self.state.sample_sequence,
                poll_duration_ms=(time.perf_counter() - started) * 1000,
                variables=dict(self.state.variables),
            )
        return self.state
