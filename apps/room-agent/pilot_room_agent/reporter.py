from __future__ import annotations

import json
from pathlib import Path
from threading import Event, Thread
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Settings
from .controls import ControlState
from .status import collect_status


class EventReporter:
    def __init__(
        self, settings: Settings, control_state: ControlState | None = None
    ) -> None:
        self.settings = settings
        self.control_state = control_state or ControlState()
        self.stop_event = Event()
        self.thread = Thread(target=self._run, name="pilot-core-reporter", daemon=True)
        self.previous_sources: dict[str, bool] = {}

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.control_state.wake_waiters()
        self.thread.join(timeout=5)

    def _token(self) -> str:
        return Path(self.settings.core_device_token_file).read_text(
            encoding="utf-8"
        ).strip()

    def _post(self, event_type: str, payload: dict[str, Any]) -> None:
        body = json.dumps(
            {
                "room_id": self.settings.room_id,
                "type": event_type,
                "payload": payload,
            }
        ).encode()
        request = Request(
            f"{self.settings.core_url.rstrip('/')}/v1/events",
            data=body,
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Content-Type": "application/json",
                "X-Pilot-Device-ID": self.settings.core_device_id,
            },
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            if response.status != 200:
                raise RuntimeError(f"Pilot Core returned HTTP {response.status}")

    @staticmethod
    def source_states(
        status: dict[str, Any], transient: dict[str, bool] | None = None
    ) -> dict[str, bool]:
        airplay_state = status.get("airplay", {}).get("playback", {}).get("state")
        music_state = (
            status.get("music_assistant", {}).get("playback", {}).get("state")
        )
        transient = transient or {"critical": False, "assistant": False}
        return {
            "critical": transient.get("critical", False),
            "assistant": transient.get("assistant", False),
            "bluetooth": False,
            "airplay": airplay_state == "Playing",
            "music": music_state == "Playing",
        }

    def report_once(self) -> None:
        status = collect_status(self.settings)
        self._post(
            "health",
            {
                "ready": status["ready"],
                "uptime_seconds": status["uptime_seconds"],
                "audio_activation": status["audio_activation"],
            },
        )
        sources = self.source_states(status, self.control_state.focus_sources())
        for source, active in sources.items():
            if self.previous_sources.get(source) == active:
                continue
            self._post("source_state", {"source": source, "active": active})
        self.previous_sources = sources

    def _run(self) -> None:
        while not self.stop_event.is_set():
            revision = self.control_state.snapshot()["revision"]
            try:
                self.report_once()
            except (OSError, HTTPError, URLError, RuntimeError, ValueError) as error:
                print(f"room-agent: Pilot Core reporting failed: {error}", flush=True)
            wait_seconds = max(self.settings.core_report_interval_seconds, 5)
            if self.stop_event.is_set():
                break
            self.control_state.wait_for_change(revision, wait_seconds)
