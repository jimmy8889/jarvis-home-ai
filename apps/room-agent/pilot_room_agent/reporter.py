from __future__ import annotations

import json
from pathlib import Path
from threading import Event, Thread
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Settings
from .status import collect_status


class EventReporter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stop_event = Event()
        self.thread = Thread(target=self._run, name="pilot-core-reporter", daemon=True)
        self.previous_sources: dict[str, bool] = {}

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
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
    def source_states(status: dict[str, Any]) -> dict[str, bool]:
        airplay_state = status.get("airplay", {}).get("playback", {}).get("state")
        music_state = (
            status.get("music_assistant", {}).get("playback", {}).get("state")
        )
        return {
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
            },
        )
        sources = self.source_states(status)
        for source, active in sources.items():
            if self.previous_sources.get(source) == active:
                continue
            self._post("source_state", {"source": source, "active": active})
        self.previous_sources = sources

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.report_once()
            except (OSError, HTTPError, URLError, RuntimeError, ValueError) as error:
                print(f"room-agent: Pilot Core reporting failed: {error}", flush=True)
            self.stop_event.wait(max(self.settings.core_report_interval_seconds, 5))
