from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from . import __version__


STATIC_ROOT = Path(__file__).with_name("static")
MAX_CORE_RESPONSE_BYTES = 256_000
MAX_CLIENT_REQUEST_BYTES = 64_000


def _bounded_text(path: Path, limit: int = 4096) -> str:
    try:
        return path.read_text(encoding="utf-8")[:limit].strip()
    except OSError:
        return ""


def _memory_status() -> dict[str, int | None]:
    values: dict[str, int] = {}
    for line in _bounded_text(Path("/proc/meminfo")).splitlines():
        key, _, raw = line.partition(":")
        if not raw:
            continue
        try:
            values[key] = int(raw.strip().split()[0]) * 1024
        except (IndexError, ValueError):
            continue
    return {
        "total_bytes": values.get("MemTotal"),
        "available_bytes": values.get("MemAvailable"),
    }


def _temperature() -> float | None:
    raw = _bounded_text(Path("/sys/class/thermal/thermal_zone0/temp"), 32)
    try:
        return round(int(raw) / 1000, 1)
    except ValueError:
        return None


def _local_ip(core_url: str) -> str | None:
    parsed = urlsplit(core_url)
    if not parsed.hostname:
        return None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect((parsed.hostname, parsed.port or 80))
            return str(connection.getsockname()[0])
    except OSError:
        return None


def _core_status(core_url: str) -> dict[str, Any]:
    if urlsplit(core_url).scheme not in {"http", "https"}:
        return {"connected": False, "error": "invalid Pilot Core URL"}
    request = Request(
        f"{core_url.rstrip('/')}/readyz",
        headers={"Accept": "application/json", "User-Agent": "pilot-display-node"},
    )
    try:
        with urlopen(request, timeout=3) as response:  # noqa: S310
            if response.status != HTTPStatus.OK:
                raise HTTPError(
                    request.full_url,
                    response.status,
                    "unexpected status",
                    response.headers,
                    None,
                )
            body = response.read(MAX_CORE_RESPONSE_BYTES + 1)
            if len(body) > MAX_CORE_RESPONSE_BYTES:
                raise ValueError("Pilot Core response is too large")
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("Pilot Core response is not an object")
            return {
                "connected": bool(payload.get("ready")),
                "registry_revision": payload.get("registry_revision"),
                "room_count": payload.get("room_count"),
                "player_count": payload.get("player_count"),
                "tts_configured": payload.get("tts_configured"),
                "assistant": payload.get("assistant"),
            }
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
        return {"connected": False, "error": str(error)[:240]}


def _core_surface(
    core_url: str,
    device_id: str,
    device_token_file: str,
) -> dict[str, Any]:
    if urlsplit(core_url).scheme not in {"http", "https"}:
        return {"status": "unavailable", "error": "invalid Pilot Core URL"}
    token = _bounded_text(Path(device_token_file), 4096)
    if not device_id or not token:
        return {"status": "not_configured"}
    request = Request(
        f"{core_url.rstrip('/')}/v1/devices/{device_id}/surface",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Pilot-Device-ID": device_id,
            "User-Agent": "pilot-display-node",
        },
    )
    try:
        with urlopen(request, timeout=5) as response:  # noqa: S310
            if response.status != HTTPStatus.OK:
                raise HTTPError(
                    request.full_url,
                    response.status,
                    "unexpected status",
                    response.headers,
                    None,
                )
            body = response.read(MAX_CORE_RESPONSE_BYTES + 1)
            if len(body) > MAX_CORE_RESPONSE_BYTES:
                raise ValueError("Pilot Core response is too large")
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("Pilot Core surface response is not an object")
            return payload
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
        return {"status": "unavailable", "error": str(error)[:240]}


def _core_device_request(
    core_url: str,
    device_id: str,
    device_token_file: str,
    endpoint: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any] | list[Any]]:
    if urlsplit(core_url).scheme not in {"http", "https"}:
        return HTTPStatus.BAD_GATEWAY, {"detail": "invalid Pilot Core URL"}
    token = _bounded_text(Path(device_token_file), 4096)
    if not device_id or not token:
        return HTTPStatus.SERVICE_UNAVAILABLE, {
            "detail": "display device credentials are not configured"
        }
    body = (
        json.dumps(payload, separators=(",", ":")).encode()
        if payload is not None
        else None
    )
    request = Request(
        f"{core_url.rstrip('/')}/v1/devices/{device_id}/{endpoint}",
        method=method,
        data=body,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Pilot-Device-ID": device_id,
            "User-Agent": "pilot-display-node",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with urlopen(request, timeout=12) as response:  # noqa: S310
            content = response.read(MAX_CORE_RESPONSE_BYTES + 1)
            if len(content) > MAX_CORE_RESPONSE_BYTES:
                raise ValueError("Pilot Core response is too large")
            result = json.loads(content)
            if not isinstance(result, (dict, list)):
                raise ValueError("Pilot Core response is not JSON data")
            return response.status, result
    except HTTPError as error:
        try:
            content = error.read(MAX_CORE_RESPONSE_BYTES + 1)
            result = json.loads(content)
            if isinstance(result, dict):
                return error.code, result
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return error.code, {"detail": f"Pilot Core returned HTTP {error.code}"}
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
        return HTTPStatus.BAD_GATEWAY, {"detail": str(error)[:240]}


def status_payload(
    core_url: str,
    device_id: str = "",
    device_token_file: str = "",
    mode: str = "display",
) -> dict[str, Any]:
    uptime_raw = _bounded_text(Path("/proc/uptime"), 64).partition(" ")[0]
    try:
        uptime_seconds: int | None = int(float(uptime_raw))
    except ValueError:
        uptime_seconds = None
    disk = shutil.disk_usage("/")
    try:
        load = [round(value, 2) for value in os.getloadavg()]
    except OSError:
        load = []
    return {
        "version": __version__,
        "mode": mode if mode in {"display", "media-console"} else "display",
        "generated_at": datetime.now(UTC).isoformat(),
        "hostname": socket.gethostname(),
        "ip_address": _local_ip(core_url),
        "uptime_seconds": uptime_seconds,
        "cpu_temperature_c": _temperature(),
        "load_average": load,
        "memory": _memory_status(),
        "disk": {
            "total_bytes": disk.total,
            "free_bytes": disk.free,
        },
        "core": _core_status(core_url),
        "surface": _core_surface(core_url, device_id, device_token_file),
    }


class DisplayHandler(BaseHTTPRequestHandler):
    server_version = "PilotDisplay/0.1"

    def _headers(
        self,
        content_type: str,
        length: int,
        status: HTTPStatus | int = HTTPStatus.OK,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )
        self.end_headers()

    def _send(
        self,
        content: bytes,
        content_type: str,
        status: HTTPStatus | int = HTTPStatus.OK,
    ) -> None:
        self._headers(content_type, len(content), status)
        self.wfile.write(content)

    def _send_json(
        self,
        payload: dict[str, Any] | list[Any],
        status: HTTPStatus | int = HTTPStatus.OK,
    ) -> None:
        self._send(
            json.dumps(payload, separators=(",", ":")).encode(),
            "application/json",
            status,
        )

    def do_GET(self) -> None:  # noqa: N802
        parsed_path = urlsplit(self.path)
        path = parsed_path.path
        if path == "/healthz":
            self._send(b'{"ok":true}', "application/json")
            return
        if path == "/api/status":
            payload = status_payload(  # type: ignore[attr-defined]
                self.server.core_url,
                self.server.device_id,
                self.server.device_token_file,
                self.server.mode,
            )
            self._send(
                json.dumps(payload, separators=(",", ":")).encode(),
                "application/json",
            )
            return
        if path == "/api/media":
            status, payload = _core_device_request(  # type: ignore[attr-defined]
                self.server.core_url,
                self.server.device_id,
                self.server.device_token_file,
                "media",
            )
            self._send_json(payload, status)
            return
        if path == "/api/dashboard":
            status, payload = _core_device_request(  # type: ignore[attr-defined]
                self.server.core_url,
                self.server.device_id,
                self.server.device_token_file,
                "dashboard",
            )
            self._send_json(payload, status)
            return
        if path == "/api/events/snapshot":
            values = parse_qs(parsed_path.query)
            cursor = values.get("cursor", [""])[0]
            if cursor and (not cursor.isdigit() or len(cursor) > 20):
                self._send_json(
                    {"detail": "invalid event cursor"},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            query = "?" + urlencode({"cursor": cursor}) if cursor else ""
            status, payload = _core_device_request(  # type: ignore[attr-defined]
                self.server.core_url,
                self.server.device_id,
                self.server.device_token_file,
                "events/snapshot" + query,
            )
            self._send_json(payload, status)
            return
        assets = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/assets/house-energy.png": ("assets/house-energy.png", "image/png"),
            "/assets/house-no-car.png": ("assets/house-no-car.png", "image/png"),
        }
        asset = assets.get(path)
        if asset is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        filename, content_type = asset
        try:
            content = (STATIC_ROOT / filename).read_bytes()
        except OSError:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._send(content, content_type)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.partition("?")[0]
        endpoints = {
            "/api/media": "media",
            "/api/media/search": "media/search",
            "/api/media/browse": "media/browse",
            "/api/video": "video",
            "/api/dashboard/actions": "dashboard/actions",
        }
        endpoint = endpoints.get(path)
        if endpoint is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(
                {"detail": "invalid content length"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        if not 0 < content_length <= MAX_CLIENT_REQUEST_BYTES:
            self._send_json(
                {"detail": "request body is empty or too large"},
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
            return
        try:
            payload = json.loads(self.rfile.read(content_length))
        except (UnicodeError, json.JSONDecodeError):
            self._send_json({"detail": "invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        if not isinstance(payload, dict):
            self._send_json(
                {"detail": "request must be a JSON object"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        status, result = _core_device_request(  # type: ignore[attr-defined]
            self.server.core_url,
            self.server.device_id,
            self.server.device_token_file,
            endpoint,
            method="POST",
            payload=payload,
        )
        self._send_json(result, status)

    def log_message(self, format: str, *args: Any) -> None:
        return


class DisplayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        core_url: str,
        device_id: str,
        device_token_file: str,
        mode: str = "display",
    ) -> None:
        super().__init__(address, DisplayHandler)
        self.core_url = core_url
        self.device_id = device_id
        self.device_token_file = device_token_file
        self.mode = mode


def main() -> None:
    host = os.environ.get("PILOT_DISPLAY_HOST", "127.0.0.1")
    port = int(os.environ.get("PILOT_DISPLAY_PORT", "8780"))
    core_url = os.environ.get("PILOT_CORE_URL", "http://127.0.0.1:8770")
    device_id = os.environ.get("PILOT_DEVICE_ID", "")
    device_token_file = os.environ.get(
        "PILOT_DEVICE_TOKEN_FILE", "/etc/pilot-display/device-token"
    )
    mode = os.environ.get("PILOT_DISPLAY_MODE", "display")
    server = DisplayServer(
        (host, port),
        core_url,
        device_id,
        device_token_file,
        mode,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
