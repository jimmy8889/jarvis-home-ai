from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time
from typing import Any

from .activation import ActivationGate
from .config import Settings


STARTED_AT = time.monotonic()


def _command_status(command: list[str], timeout: float = 3.0) -> dict[str, Any]:
    executable = shutil.which(command[0])
    if executable is None:
        return {"available": False, "ok": False, "detail": "command not installed"}
    try:
        result = subprocess.run(
            [executable, *command[1:]],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"available": True, "ok": False, "detail": str(error)}
    detail = (result.stdout or result.stderr).strip()
    return {
        "available": True,
        "ok": result.returncode == 0,
        "detail": detail[-4000:],
    }


def _tcp_port_status(
    port: int,
    proc_paths: tuple[str, ...] = ("/proc/net/tcp", "/proc/net/tcp6"),
) -> dict[str, Any]:
    listening = False
    established = 0
    available = False
    target_port = f"{port:04X}"

    for proc_path in proc_paths:
        try:
            lines = Path(proc_path).read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            continue
        available = True
        for line in lines:
            fields = line.split()
            if len(fields) < 4:
                continue
            local_address = fields[1]
            state = fields[3]
            try:
                local_port = local_address.rsplit(":", 1)[1]
            except IndexError:
                continue
            if local_port.upper() != target_port:
                continue
            if state == "0A":
                listening = True
            elif state == "01":
                established += 1

    connected = established > 0
    return {
        "available": available,
        "ok": available and listening,
        "listening": listening,
        "client_connected": connected,
        "connection_count": established,
        "port": port,
    }


def _tcp_remote_port_status(
    port: int,
    proc_paths: tuple[str, ...] = ("/proc/net/tcp", "/proc/net/tcp6"),
) -> dict[str, Any]:
    established = 0
    available = False
    target_port = f"{port:04X}"

    for proc_path in proc_paths:
        try:
            lines = Path(proc_path).read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            continue
        available = True
        for line in lines:
            fields = line.split()
            if len(fields) < 4:
                continue
            remote_address = fields[2]
            state = fields[3]
            try:
                remote_port = remote_address.rsplit(":", 1)[1]
            except IndexError:
                continue
            if remote_port.upper() == target_port and state == "01":
                established += 1

    connected = established > 0
    return {
        "available": available,
        "ok": available and connected,
        "connected": connected,
        "connection_count": established,
        "server_port": port,
    }


def _mpris_playback_status(bus_name: str) -> dict[str, Any]:
    base_command = [
        "busctl",
        "--user",
        "get-property",
        bus_name,
        "/org/mpris/MediaPlayer2",
        "org.mpris.MediaPlayer2.Player",
    ]
    playback = _command_status([*base_command, "PlaybackStatus"])
    volume = _command_status([*base_command, "Volume"])

    state = "Unavailable"
    if playback["ok"]:
        fields = shlex.split(playback["detail"])
        if len(fields) >= 2:
            state = fields[1]

    parsed_volume: float | None = None
    if volume["ok"]:
        fields = shlex.split(volume["detail"])
        if len(fields) >= 2:
            try:
                parsed_volume = float(fields[1])
            except ValueError:
                pass

    return {
        "available": playback["available"],
        "ok": playback["ok"],
        "state": state,
        "volume": parsed_volume,
    }


def _sendspin_bus_name() -> str | None:
    listing = _command_status(["busctl", "--user", "list"])
    if not listing["ok"]:
        return None
    for line in listing["detail"].splitlines():
        name = line.split(maxsplit=1)[0] if line.split() else ""
        if name.startswith("org.mpris.MediaPlayer2.Sendspin."):
            return name
    return None


def _airplay_bus_name() -> str | None:
    target = "org.mpris.MediaPlayer2.ShairportSync"
    listing = _command_status(["busctl", "--user", "list"])
    if not listing["ok"]:
        return None
    for line in listing["detail"].splitlines():
        name = line.split(maxsplit=1)[0] if line.split() else ""
        if name == target:
            return target
    return None


def collect_status(settings: Settings) -> dict[str, Any]:
    pipewire = _command_status(["wpctl", "status", "--name"])
    capture = _command_status(["arecord", "-l"])
    playback = _command_status(["aplay", "-l"])
    if capture["ok"] and "card " not in capture["detail"]:
        capture["ok"] = False
        capture["detail"] = "no ALSA capture hardware detected"
    if playback["ok"] and "card " not in playback["detail"]:
        playback["ok"] = False
        playback["detail"] = "no ALSA playback hardware detected"
    bluetooth: dict[str, Any]
    if settings.bluetooth_enabled:
        bluetooth = _command_status(["bluetoothctl", "show"])
    else:
        bluetooth = {"enabled": False, "ok": True, "detail": "disabled by room config"}

    voice_satellite: dict[str, Any]
    if settings.voice_satellite_enabled:
        service = _command_status(
            ["systemctl", "is-active", "pilot-linux-voice-assistant.service"]
        )
        socket_status = _tcp_port_status(settings.voice_satellite_port)
        socket_status["home_assistant_connected"] = socket_status[
            "client_connected"
        ]
        voice_satellite = {
            "enabled": True,
            "ok": (
                service["ok"]
                and socket_status["ok"]
                and socket_status["client_connected"]
            ),
            "service": service,
            "api": socket_status,
        }
    else:
        voice_satellite = {
            "enabled": False,
            "ok": True,
            "detail": "disabled by room config",
        }

    airplay: dict[str, Any]
    if settings.airplay_enabled:
        service = _command_status(["systemctl", "is-active", "pilot-airplay.service"])
        socket_status = _tcp_port_status(settings.airplay_port)
        airplay = {
            "enabled": True,
            "ok": service["ok"] and socket_status["ok"],
            "service": service,
            "api": socket_status,
            "playback": _mpris_playback_status(
                "org.mpris.MediaPlayer2.ShairportSync"
            ),
        }
    else:
        airplay = {
            "enabled": False,
            "ok": True,
            "detail": "disabled by room config",
        }

    music_assistant: dict[str, Any]
    if settings.music_assistant_enabled:
        service = _command_status(["systemctl", "is-active", "pilot-sendspin.service"])
        transport = _tcp_remote_port_status(settings.music_assistant_port)
        music_assistant = {
            "enabled": True,
            "ok": service["ok"] and transport["ok"],
            "protocol": settings.music_assistant_protocol,
            "service": service,
            "transport": transport,
            "playback": (
                _mpris_playback_status(sendspin_bus)
                if (sendspin_bus := _sendspin_bus_name())
                else {
                    "available": False,
                    "ok": False,
                    "state": "Unavailable",
                    "volume": None,
                }
            ),
        }
    else:
        music_assistant = {
            "enabled": False,
            "ok": True,
            "detail": "disabled by room config",
        }

    ready = (
        pipewire["ok"]
        and capture["ok"]
        and playback["ok"]
        and bluetooth["ok"]
        and voice_satellite["ok"]
        and airplay["ok"]
        and music_assistant["ok"]
    )
    return {
        "room_id": settings.room_id,
        "ready": ready,
        "uptime_seconds": round(time.monotonic() - STARTED_AT, 3),
        "pid": os.getpid(),
        "audio": {
            "pipewire": pipewire,
            "capture": capture,
            "playback": playback,
            "microphone_description": settings.microphone_description,
            "speaker_description": settings.speaker_description,
            "microphone_node": settings.microphone_node,
            "speaker_node": settings.speaker_node,
            "capture_alsa_device": settings.capture_alsa_device,
            "playback_alsa_device": settings.playback_alsa_device,
        },
        "bluetooth": bluetooth,
        "voice_satellite": voice_satellite,
        "airplay": airplay,
        "music_assistant": music_assistant,
        "audio_activation": ActivationGate(settings).status(),
    }
