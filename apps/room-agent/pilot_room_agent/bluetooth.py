from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, Lock, Thread
from typing import Any

from .config import Settings


@dataclass(frozen=True)
class BluetoothSource:
    name: str
    state: str

    @property
    def active(self) -> bool:
        return self.state.lower() == "running"


def parse_bluetooth_sources(payload: str) -> tuple[BluetoothSource, ...]:
    try:
        values = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return ()
    if not isinstance(values, list):
        return ()
    sources: list[BluetoothSource] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        name = str(value.get("name") or "")
        properties = value.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        is_bluetooth = (
            name.startswith("bluez_input.")
            or str(properties.get("device.api") or "").lower() == "bluez5"
            or "api.bluez5.address" in properties
        )
        if not is_bluetooth:
            continue
        sources.append(
            BluetoothSource(name=name, state=str(value.get("state") or "unknown"))
        )
    return tuple(sorted(sources, key=lambda item: item.name))


def parse_loopback_modules(payload: str) -> dict[str, int]:
    modules: dict[str, int] = {}
    for line in payload.splitlines():
        fields = line.split("\t", 2)
        if (
            len(fields) < 3
            or fields[1] != "module-loopback"
            or "application.name=PilotBluetooth" not in fields[2]
        ):
            continue
        source = next(
            (
                value.removeprefix("source=")
                for value in fields[2].split()
                if value.startswith("source=bluez_input.")
            ),
            "",
        )
        if not source:
            continue
        try:
            modules[source] = int(fields[0])
        except ValueError:
            continue
    return modules


class BluetoothBridge:
    """Route connected A2DP sources into Pilot's accepted PipeWire sink."""

    def __init__(
        self,
        settings: Settings,
        runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.settings = settings
        self.runner = runner or self._run
        self.stop_event = Event()
        self.thread = Thread(
            target=self._loop,
            name="pilot-bluetooth-bridge",
            daemon=True,
        )
        self.lock = Lock()
        self.loopbacks: dict[str, int] = {}
        self.sources: tuple[BluetoothSource, ...] = ()
        self.last_error = ""
        self.available = False

    @staticmethod
    def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=5)
        for module_id in tuple(self.loopbacks.values()):
            self.runner(["pactl", "unload-module", str(module_id)])
        self.loopbacks.clear()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "available": self.available,
                "ok": self.available and not self.last_error,
                "active": any(source.active for source in self.sources),
                "connected": bool(self.sources),
                "connected_sources": len(self.sources),
                "running_sources": sum(source.active for source in self.sources),
                "loopbacks": len(self.loopbacks),
                "last_error": self.last_error,
            }

    def reconcile_once(self) -> None:
        source_result = self.runner(["pactl", "--format=json", "list", "sources"])
        if source_result.returncode != 0:
            detail = (source_result.stderr or source_result.stdout).strip()
            with self.lock:
                self.available = False
                self.last_error = detail or "unable to inspect PipeWire sources"
            return

        sources = parse_bluetooth_sources(source_result.stdout)
        available_names = {source.name for source in sources}
        module_result = self.runner(["pactl", "list", "short", "modules"])
        existing = (
            parse_loopback_modules(module_result.stdout)
            if module_result.returncode == 0
            else {}
        )
        self.loopbacks.update(
            {
                source: module_id
                for source, module_id in existing.items()
                if source in available_names
            }
        )

        error = ""
        for source in sources:
            if source.name in self.loopbacks:
                continue
            command = [
                "pactl",
                "load-module",
                "module-loopback",
                f"source={source.name}",
                f"sink={self.settings.speaker_node or '@DEFAULT_SINK@'}",
                f"latency_msec={self.settings.bluetooth_loopback_latency_ms}",
                "sink_input_properties=application.name=PilotBluetooth",
            ]
            result = self.runner(command)
            try:
                module_id = int(result.stdout.strip())
            except ValueError:
                detail = (result.stderr or result.stdout).strip()
                error = detail or f"unable to bridge {source.name}"
            else:
                self.loopbacks[source.name] = module_id

        for source, module_id in tuple(self.loopbacks.items()):
            if source in available_names:
                continue
            self.runner(["pactl", "unload-module", str(module_id)])
            self.loopbacks.pop(source, None)

        with self.lock:
            self.available = True
            self.sources = sources
            self.last_error = error

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.reconcile_once()
            except (OSError, subprocess.SubprocessError, ValueError) as error:
                with self.lock:
                    self.available = False
                    self.last_error = str(error)
            self.stop_event.wait(max(self.settings.audio_focus_interval_seconds, 1))
