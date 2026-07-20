from __future__ import annotations

from dataclasses import dataclass
import json
import re
import subprocess
from threading import Event, Thread
from typing import Callable

from .config import Settings
from .controls import ControlState
from .status import collect_status


PRIORITY = {
    "critical": 100,
    "assistant": 90,
    "bluetooth": 80,
    "airplay": 70,
    "music": 60,
}

STREAM_NAMES = {
    "Shairport Sync": "airplay",
    "Sendspin": "music",
    "sendspin": "music",
    # Sendspin 7.5 opens ALSA through Python. PipeWire exposes the generic ALSA
    # client label rather than the configured renderer name.
    "PipeWire ALSA [python": "music",
    "ALSA Playback [python": "music",
    "linux_voice_assistant": "assistant",
}


@dataclass(frozen=True)
class LocalFocusDecision:
    foreground: str | None
    gains: dict[str, float]
    active: frozenset[str]


def decide(active: dict[str, bool], duck_gain: float) -> LocalFocusDecision:
    enabled = [source for source, value in active.items() if value]
    foreground = max(enabled, key=PRIORITY.__getitem__) if enabled else None
    gains: dict[str, float] = {}
    for source in PRIORITY:
        if not active.get(source, False):
            gains[source] = 0.0
        elif source == foreground:
            gains[source] = 1.0
        elif foreground in {"critical", "assistant"}:
            gains[source] = duck_gain
        else:
            gains[source] = 0.0
    return LocalFocusDecision(foreground, gains, frozenset(enabled))


def parse_stream_nodes(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in text.splitlines():
        match = re.match(r"\s*(\d+)\.\s+(.+?)\s*$", line)
        if not match:
            continue
        node_id = int(match.group(1))
        name = match.group(2).strip()
        for prefix, source in STREAM_NAMES.items():
            if name.startswith(prefix):
                result[source] = node_id
                break
    return result


def parse_pipewire_nodes(text: str) -> dict[str, int]:
    """Resolve actual PipeWire node IDs rather than wpctl's grouped client IDs."""

    try:
        objects = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(objects, list):
        return {}
    result: dict[str, int] = {}
    for item in objects:
        if not isinstance(item, dict) or item.get("type") != "PipeWire:Interface:Node":
            continue
        info = item.get("info")
        props = info.get("props") if isinstance(info, dict) else None
        if not isinstance(props, dict) or props.get("media.class") != "Stream/Output/Audio":
            continue
        labels = " ".join(
            str(props.get(field) or "")
            for field in ("application.name", "node.name", "node.description")
        )
        for prefix, source in STREAM_NAMES.items():
            if prefix in labels:
                node_id = item.get("id")
                if isinstance(node_id, int):
                    result[source] = node_id
                break
    return result


class FocusEnforcer:
    def __init__(self, runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None) -> None:
        self.runner = runner or self._run
        self.baselines: dict[str, float] = {}

    @staticmethod
    def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, capture_output=True, text=True, check=False)

    def _volume(self, node_id: int) -> float | None:
        result = self.runner(["wpctl", "get-volume", str(node_id)])
        if result.returncode != 0:
            return None
        match = re.search(r"Volume:\s+([0-9.]+)", result.stdout)
        return float(match.group(1)) if match else None

    def apply(self, decision: LocalFocusDecision, nodes: dict[str, int]) -> None:
        for source, node_id in nodes.items():
            if source not in decision.active:
                if source in self.baselines:
                    self.runner(
                        [
                            "wpctl",
                            "set-volume",
                            str(node_id),
                            f"{self.baselines.pop(source):.4f}",
                        ]
                    )
                continue
            gain = decision.gains.get(source, 1.0)
            if source not in self.baselines:
                volume = self._volume(node_id)
                if volume is not None:
                    self.baselines[source] = volume
            baseline = self.baselines.get(source)
            if baseline is None:
                continue
            target = baseline if gain == 1.0 else baseline * gain
            self.runner(["wpctl", "set-volume", str(node_id), f"{target:.4f}"])

        for source in tuple(self.baselines):
            if source not in nodes:
                self.baselines.pop(source, None)


class AudioFocusLoop:
    def __init__(self, settings: Settings, control_state: ControlState | None = None) -> None:
        self.settings = settings
        self.control_state = control_state or ControlState()
        self.stop_event = Event()
        self.thread = Thread(target=self._run, name="pilot-audio-focus", daemon=True)
        self.enforcer = FocusEnforcer()

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=5)

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                status = collect_status(self.settings)
                output = subprocess.run(
                    ["pw-dump"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                nodes = parse_pipewire_nodes(output.stdout)
                transient = self.control_state.focus_sources()
                active = {
                    "critical": transient["critical"],
                    "assistant": transient["assistant"],
                    "bluetooth": False,
                    "airplay": status.get("airplay", {})
                    .get("playback", {})
                    .get("state")
                    == "Playing",
                    "music": status.get("music_assistant", {})
                    .get("playback", {})
                    .get("state")
                    == "Playing",
                }
                self.enforcer.apply(
                    decide(active, self.settings.audio_focus_duck_gain), nodes
                )
            except (OSError, ValueError) as error:
                print(f"room-agent: audio focus failed: {error}", flush=True)
            self.stop_event.wait(max(self.settings.audio_focus_interval_seconds, 1))
