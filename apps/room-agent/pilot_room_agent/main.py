from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os

from .config import Settings, load_settings
from .status import collect_status


class Handler(BaseHTTPRequestHandler):
    settings = Settings()

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
            status = HTTPStatus.OK if payload["ready"] else HTTPStatus.SERVICE_UNAVAILABLE
            self._respond(status, payload)
            return
        self._respond(HTTPStatus.NOT_FOUND, {"error": "not found"})

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
    Handler.settings = settings
    server = ThreadingHTTPServer((settings.listen_host, settings.listen_port), Handler)
    print(
        f"Pilot room-agent for {settings.room_id} listening on "
        f"{settings.listen_host}:{settings.listen_port}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
