from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os

from .config import Settings, load_settings
from .audio_focus import AudioFocusLoop
from .audio_delivery import AudioFetcher, AudioPlayback
from .activation import ActivationGate
from .command_client import CommandClient
from .controls import ControlError, ControlState, RoomController
from .reporter import EventReporter
from .status import collect_status


class Handler(BaseHTTPRequestHandler):
    settings = Settings()
    control_state = ControlState()
    controller = RoomController(control_state)
    command_client: CommandClient | None = None
    audio_playback: AudioPlayback | None = None

    def _respond(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/healthz":
            self._respond(HTTPStatus.OK, {"status": "ok", "room_id": self.settings.room_id})
            return
        if self.path in {"/readyz", "/v1/status"}:
            payload = collect_status(self.settings)
            payload["controls"] = self.control_state.snapshot()
            payload["audio_delivery"] = (
                self.audio_playback.status()
                if self.audio_playback
                else {"active": False, "enabled": False}
            )
            payload["core_commands"] = (
                self.command_client.status()
                if self.command_client
                else {"enabled": False, "connected": False}
            )
            status = HTTPStatus.OK if payload["ready"] else HTTPStatus.SERVICE_UNAVAILABLE
            self._respond(status, payload)
            return
        self._respond(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/v1/control":
            self._respond(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16_384:
                raise ControlError("request body must be between 1 and 16384 bytes")
            payload = json.loads(self.rfile.read(length))
            result = self.controller.execute(payload)
        except (ControlError, json.JSONDecodeError, UnicodeDecodeError) as error:
            self._respond(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})
            return
        self._respond(HTTPStatus.OK, result.as_dict())

    def log_message(self, format: str, *args: object) -> None:
        print(f"room-agent: {self.address_string()} {format % args}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pilot room endpoint agent")
    parser.add_argument(
        "--config",
        default=os.environ.get("PILOT_CONFIG", "/etc/pilot/room.toml"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    control_state = ControlState()
    Handler.settings = settings
    Handler.control_state = control_state
    audio_playback: AudioPlayback | None = None
    if settings.core_commands_enabled:
        audio_playback = AudioPlayback(
            control_state,
            AudioFetcher(settings),
            ActivationGate(settings),
        )
    Handler.audio_playback = audio_playback
    Handler.controller = RoomController(control_state, audio_player=audio_playback)
    Handler.command_client = None
    reporter: EventReporter | None = None
    focus_loop: AudioFocusLoop | None = None
    command_client: CommandClient | None = None
    if settings.core_reporting_enabled:
        reporter = EventReporter(settings, control_state)
        reporter.start()
    if settings.audio_focus_enabled:
        focus_loop = AudioFocusLoop(settings, control_state)
        focus_loop.start()
    if settings.core_commands_enabled:
        command_client = CommandClient(settings, Handler.controller)
        Handler.command_client = command_client
        command_client.start()
    server = ThreadingHTTPServer((settings.listen_host, settings.listen_port), Handler)
    print(
        f"Pilot room-agent for {settings.room_id} listening on "
        f"{settings.listen_host}:{settings.listen_port}",
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        if command_client:
            command_client.stop()
        if audio_playback:
            audio_playback.close()
        if reporter:
            reporter.stop()
        if focus_loop:
            focus_loop.stop()


if __name__ == "__main__":
    main()
