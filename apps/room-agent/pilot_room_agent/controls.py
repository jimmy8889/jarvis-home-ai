from __future__ import annotations

from dataclasses import dataclass
import math
import subprocess
from threading import Lock
import time
from typing import Any, Callable

from .status import _airplay_bus_name, _sendspin_bus_name


MPRIS_PATH = "/org/mpris/MediaPlayer2"
MPRIS_PLAYER = "org.mpris.MediaPlayer2.Player"
TRANSIENT_STATES = {
    "listening",
    "assistant_speaking",
    "announcement_active",
    "critical_announcement",
}


class ControlError(ValueError):
    """A rejected or failed local room control command."""


@dataclass(frozen=True)
class CommandResult:
    action: str
    detail: dict[str, Any]
    state: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "action": self.action,
            "detail": self.detail,
            "state": self.state,
        }


class ControlState:
    """Thread-safe, self-expiring room interaction state.

    Expiry is a safety boundary: if a voice or announcement client disappears,
    the room cannot remain permanently ducked.
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.monotonic
        self._lock = Lock()
        self._values = {name: False for name in TRANSIENT_STATES}
        self._expires_at: dict[str, float | None] = {
            name: None for name in TRANSIENT_STATES
        }
        self._revision = 0

    def set(self, name: str, active: bool, ttl_seconds: float | None = None) -> None:
        if name not in TRANSIENT_STATES:
            raise ControlError(f"unknown transient state: {name}")
        if not isinstance(active, bool):
            raise ControlError("active must be a boolean")
        if active and ttl_seconds is not None:
            if (
                isinstance(ttl_seconds, bool)
                or not isinstance(ttl_seconds, (int, float))
                or not math.isfinite(ttl_seconds)
                or not 1 <= ttl_seconds <= 300
            ):
                raise ControlError("ttl_seconds must be between 1 and 300")

        with self._lock:
            self._expire_locked()
            self._values[name] = active
            self._expires_at[name] = (
                self._clock() + float(ttl_seconds)
                if active and ttl_seconds is not None
                else None
            )
            self._revision += 1

    def clear(self) -> None:
        with self._lock:
            for name in TRANSIENT_STATES:
                self._values[name] = False
                self._expires_at[name] = None
            self._revision += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._expire_locked()
            result: dict[str, Any] = dict(self._values)
            result["revision"] = self._revision
            return result

    def focus_sources(self) -> dict[str, bool]:
        state = self.snapshot()
        return {
            "critical": state["critical_announcement"],
            "assistant": (
                state["listening"]
                or state["assistant_speaking"]
                or state["announcement_active"]
            ),
        }

    def _expire_locked(self) -> None:
        now = self._clock()
        changed = False
        for name, expires_at in self._expires_at.items():
            if expires_at is not None and now >= expires_at:
                self._values[name] = False
                self._expires_at[name] = None
                changed = True
        if changed:
            self._revision += 1


class RoomController:
    def __init__(
        self,
        state: ControlState,
        runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
        sendspin_bus_resolver: Callable[[], str | None] | None = None,
        airplay_bus_resolver: Callable[[], str | None] | None = None,
    ) -> None:
        self.state = state
        self.runner = runner or self._run
        self.sendspin_bus_resolver = sendspin_bus_resolver or _sendspin_bus_name
        self.airplay_bus_resolver = airplay_bus_resolver or _airplay_bus_name

    @staticmethod
    def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    def execute(self, payload: dict[str, Any]) -> CommandResult:
        if not isinstance(payload, dict):
            raise ControlError("request body must be a JSON object")
        action = payload.get("action")
        if not isinstance(action, str) or not action:
            raise ControlError("action is required")

        if action in {"play", "pause", "stop"}:
            detail = self._transport(action, payload.get("source", "all"))
        elif action == "set_volume":
            detail = self._set_volume(
                payload.get("volume"), payload.get("source", "room")
            )
        elif action in {"start_listening", "stop_listening"}:
            active = action == "start_listening"
            self.state.set(
                "listening",
                active,
                self._ttl(payload, 30) if active else None,
            )
            detail = {"listening": active}
        elif action in {"assistant_start", "assistant_end"}:
            active = action == "assistant_start"
            self.state.set(
                "assistant_speaking",
                active,
                self._ttl(payload, 120) if active else None,
            )
            detail = {"assistant_speaking": active}
        elif action in {"announcement_start", "announcement_end"}:
            detail = self._announcement(action, payload)
        elif action == "cancel":
            self.state.clear()
            detail = {"transient_state_cleared": True}
        else:
            raise ControlError(f"unsupported action: {action}")

        return CommandResult(action, detail, self.state.snapshot())

    @staticmethod
    def _ttl(payload: dict[str, Any], default: float) -> float:
        value = payload.get("ttl_seconds", default)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 1 <= value <= 300
        ):
            raise ControlError("ttl_seconds must be between 1 and 300")
        return float(value)

    def _announcement(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        active = action == "announcement_start"
        critical = payload.get("critical", False) if active else False
        if not isinstance(critical, bool):
            raise ControlError("critical must be a boolean")
        ttl = self._ttl(payload, 120) if active else None
        self.state.set("announcement_active", active, ttl)
        self.state.set("critical_announcement", active and critical, ttl)
        return {"announcement_active": active, "critical": active and critical}

    def _transport(self, action: str, source: Any) -> dict[str, Any]:
        if source not in {"airplay", "music", "all"}:
            raise ControlError("source must be airplay, music, or all")
        sources = ("airplay", "music") if source == "all" else (source,)
        method = {"play": "Play", "pause": "Pause", "stop": "Stop"}[action]
        affected: list[str] = []
        unavailable: list[str] = []
        for item in sources:
            bus_name = self._bus_name(item)
            if bus_name is None:
                unavailable.append(item)
                continue
            self._checked(
                ["busctl", "--user", "call", bus_name, MPRIS_PATH, MPRIS_PLAYER, method]
            )
            affected.append(item)
        if not affected and source != "all":
            raise ControlError(f"{source} player is unavailable")
        return {"affected": affected, "unavailable": unavailable}

    def _set_volume(self, volume: Any, source: Any) -> dict[str, Any]:
        if (
            isinstance(volume, bool)
            or not isinstance(volume, (int, float))
            or not math.isfinite(volume)
            or not 0 <= volume <= 1
        ):
            raise ControlError("volume must be between 0 and 1")
        if source not in {"room", "airplay", "music"}:
            raise ControlError("source must be room, airplay, or music")
        value = float(volume)
        if source == "room":
            self._checked(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{value:.4f}"]
            )
        else:
            bus_name = self._bus_name(source)
            if bus_name is None:
                raise ControlError(f"{source} player is unavailable")
            self._checked(
                [
                    "busctl",
                    "--user",
                    "set-property",
                    bus_name,
                    MPRIS_PATH,
                    MPRIS_PLAYER,
                    "Volume",
                    "d",
                    f"{value:.6f}",
                ]
            )
        return {"source": source, "volume": value}

    def _bus_name(self, source: str) -> str | None:
        return (
            self.airplay_bus_resolver()
            if source == "airplay"
            else self.sendspin_bus_resolver()
        )

    def _checked(self, command: list[str]) -> None:
        try:
            result = self.runner(command)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ControlError(f"control command failed: {error}") from error
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise ControlError(detail or "control command failed")
