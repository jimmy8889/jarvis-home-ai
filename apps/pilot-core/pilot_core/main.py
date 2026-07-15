from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from urllib.parse import urlsplit

from .config import load_settings
from .registry import Registry


class Handler(BaseHTTPRequestHandler):
    registry: Registry

    def _respond(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path.rstrip("/") or "/"
        if path == "/healthz":
            self._respond(HTTPStatus.OK, {"status": "ok"})
            return
        if path == "/readyz":
            self._respond(
                HTTPStatus.OK,
                {
                    "ready": True,
                    "registry_revision": self.registry.revision,
                    "room_count": len(self.registry.rooms),
                    "player_count": len(self.registry.players),
                },
            )
            return
        if path == "/v1/rooms":
            self._respond(HTTPStatus.OK, {"rooms": self.registry.list_rooms()})
            return
        if path == "/v1/players":
            self._respond(HTTPStatus.OK, {"players": self.registry.list_players()})
            return

        segments = path.strip("/").split("/")
        if len(segments) == 3 and segments[:2] == ["v1", "rooms"]:
            room_id = segments[2]
            if room_id not in self.registry.rooms:
                self._respond(HTTPStatus.NOT_FOUND, {"error": "room not found"})
                return
            self._respond(HTTPStatus.OK, self.registry.room_view(room_id))
            return
        if len(segments) == 4 and segments[:2] == ["v1", "rooms"] and segments[3] == "players":
            room_id = segments[2]
            if room_id not in self.registry.rooms:
                self._respond(HTTPStatus.NOT_FOUND, {"error": "room not found"})
                return
            self._respond(
                HTTPStatus.OK,
                {"room_id": room_id, "players": self.registry.list_players(room_id)},
            )
            return
        if len(segments) == 3 and segments[:2] == ["v1", "players"]:
            player = self.registry.players.get(segments[2])
            if player is None:
                self._respond(HTTPStatus.NOT_FOUND, {"error": "player not found"})
                return
            self._respond(HTTPStatus.OK, player.as_dict())
            return

        self._respond(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def log_message(self, format: str, *args: object) -> None:
        print(f"pilot-core: {self.address_string()} {format % args}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pilot Core room/player registry")
    parser.add_argument(
        "--config",
        default=os.environ.get("PILOT_CORE_CONFIG", "/etc/pilot/core.toml"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    Handler.registry = Registry.from_settings(settings)
    server = ThreadingHTTPServer(
        (settings.server.listen_host, settings.server.listen_port), Handler
    )
    print(
        f"Pilot Core listening on {settings.server.listen_host}:"
        f"{settings.server.listen_port}; registry {Handler.registry.revision}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
