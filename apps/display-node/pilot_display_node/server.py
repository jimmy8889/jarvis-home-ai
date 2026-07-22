from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import tempfile
from threading import Lock
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from . import __version__


STATIC_ROOT = Path(__file__).with_name("static")
MAX_CORE_RESPONSE_BYTES = 256_000
MAX_CLIENT_REQUEST_BYTES = 64_000
DEFAULT_ARTWORK_HOSTS = ("resources.tidal.com",)
DEFAULT_ARTWORK_CACHE = Path("/var/lib/pilot-display/artwork")
MAX_ARTWORK_BYTES = 5_000_000
DEFAULT_ARTWORK_CACHE_MAX_BYTES = 64_000_000
DEFAULT_ARTWORK_CACHE_MAX_ITEMS = 256
DEFAULT_ARTWORK_CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
_ARTWORK_CACHE_LOCK = Lock()


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


def _artwork_url_allowed(remote_url: str, allowed_hosts: tuple[str, ...]) -> bool:
    parsed = urlsplit(remote_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        return False
    return any(
        host == allowed or host.endswith(f".{allowed}")
        for allowed in allowed_hosts
        if allowed
    )


def _image_content_type(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _prune_artwork_cache(
    cache_root: Path,
    *,
    max_bytes: int = DEFAULT_ARTWORK_CACHE_MAX_BYTES,
    max_items: int = DEFAULT_ARTWORK_CACHE_MAX_ITEMS,
    max_age_seconds: int = DEFAULT_ARTWORK_CACHE_MAX_AGE_SECONDS,
    now: float | None = None,
) -> None:
    try:
        candidates = list(cache_root.iterdir())
    except OSError:
        return
    current_time = time.time() if now is None else now
    cutoff = current_time - max(0, max_age_seconds)
    entries: list[tuple[Path, os.stat_result]] = []
    for path in candidates:
        try:
            details = path.stat(follow_symlinks=False)
        except OSError:
            continue
        if not stat.S_ISREG(details.st_mode):
            continue
        if details.st_mtime < cutoff:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        entries.append((path, details))

    entries.sort(key=lambda item: (item[1].st_mtime, item[0].name))
    total_bytes = sum(details.st_size for _, details in entries)
    while entries and (len(entries) > max(0, max_items) or total_bytes > max(0, max_bytes)):
        path, details = entries.pop(0)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue
        total_bytes -= details.st_size


def _cached_artwork(
    remote_url: str,
    cache_root: Path,
    allowed_hosts: tuple[str, ...],
    *,
    max_cache_bytes: int = DEFAULT_ARTWORK_CACHE_MAX_BYTES,
    max_cache_items: int = DEFAULT_ARTWORK_CACHE_MAX_ITEMS,
    max_cache_age_seconds: int = DEFAULT_ARTWORK_CACHE_MAX_AGE_SECONDS,
) -> tuple[bytes, str]:
    if not _artwork_url_allowed(remote_url, allowed_hosts):
        raise ValueError("artwork host is not allowed")
    cache_key = hashlib.sha256(remote_url.encode()).hexdigest()
    cache_path = cache_root / cache_key
    with _ARTWORK_CACHE_LOCK:
        cache_root.mkdir(parents=True, exist_ok=True)
        _prune_artwork_cache(
            cache_root,
            max_bytes=max_cache_bytes,
            max_items=max_cache_items,
            max_age_seconds=max_cache_age_seconds,
        )
        try:
            cached = cache_path.read_bytes()
        except OSError:
            cached = b""
        cached_type = _image_content_type(cached)
        if cached_type:
            try:
                os.utime(cache_path, None, follow_symlinks=False)
            except OSError:
                pass
            return cached, cached_type
        if cached:
            cache_path.unlink(missing_ok=True)

    request = Request(
        remote_url,
        headers={
            "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif",
            "User-Agent": "pilot-display-node",
        },
    )
    with urlopen(request, timeout=8) as response:  # noqa: S310
        final_url = response.geturl()
        if not _artwork_url_allowed(final_url, allowed_hosts):
            raise ValueError("artwork redirect host is not allowed")
        content = response.read(MAX_ARTWORK_BYTES + 1)
    if len(content) > MAX_ARTWORK_BYTES:
        raise ValueError("artwork response is too large")
    content_type = _image_content_type(content)
    if content_type is None:
        raise ValueError("artwork response is not a supported image")

    with _ARTWORK_CACHE_LOCK:
        cache_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cache_root, delete=False) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        try:
            os.replace(temporary_path, cache_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        _prune_artwork_cache(
            cache_root,
            max_bytes=max_cache_bytes,
            max_items=max_cache_items,
            max_age_seconds=max_cache_age_seconds,
        )
    return content, content_type


def _static_cache_control(path: str) -> str:
    if path.startswith("/assets/"):
        return "public, max-age=0, must-revalidate"
    return "no-cache"


def _positive_environment_integer(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


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
        cache_control: str = "no-store",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", cache_control)
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
        cache_control: str = "no-store",
    ) -> None:
        self._headers(content_type, len(content), status, cache_control)
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
        if path == "/api/artwork":
            values = parse_qs(parsed_path.query)
            remote_url = values.get("url", [""])[0]
            if not remote_url or len(remote_url) > 4096:
                self._send_json(
                    {"detail": "an artwork URL is required"},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            try:
                content, content_type = _cached_artwork(  # type: ignore[attr-defined]
                    remote_url,
                    self.server.artwork_cache_root,
                    self.server.artwork_hosts,
                    max_cache_bytes=self.server.artwork_cache_max_bytes,
                    max_cache_items=self.server.artwork_cache_max_items,
                    max_cache_age_seconds=self.server.artwork_cache_max_age_seconds,
                )
            except ValueError as error:
                self._send_json({"detail": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            except (HTTPError, URLError, TimeoutError, OSError) as error:
                self._send_json(
                    {"detail": f"artwork unavailable: {str(error)[:160]}"},
                    HTTPStatus.BAD_GATEWAY,
                )
                return
            self._send(
                content,
                content_type,
                cache_control="public, max-age=86400, stale-if-error=604800",
            )
            return
        assets = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/assets/house-day.png": ("assets/house-day.png", "image/png"),
            "/assets/house-day-tesla.png": (
                "assets/house-day-tesla.png",
                "image/png",
            ),
            "/assets/house-night.png": ("assets/house-night.png", "image/png"),
            "/assets/house-night-tesla.png": (
                "assets/house-night-tesla.png",
                "image/png",
            ),
            "/assets/house-energy.png": ("assets/house-energy.png", "image/png"),
            "/assets/house-no-car.png": ("assets/house-no-car.png", "image/png"),
            "/assets/server-rack.png": ("assets/server-rack.png", "image/png"),
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
        self._send(content, content_type, cache_control=_static_cache_control(path))

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
        artwork_cache_root: Path = DEFAULT_ARTWORK_CACHE,
        artwork_hosts: tuple[str, ...] = DEFAULT_ARTWORK_HOSTS,
        artwork_cache_max_bytes: int = DEFAULT_ARTWORK_CACHE_MAX_BYTES,
        artwork_cache_max_items: int = DEFAULT_ARTWORK_CACHE_MAX_ITEMS,
        artwork_cache_max_age_seconds: int = DEFAULT_ARTWORK_CACHE_MAX_AGE_SECONDS,
    ) -> None:
        super().__init__(address, DisplayHandler)
        self.core_url = core_url
        self.device_id = device_id
        self.device_token_file = device_token_file
        self.mode = mode
        self.artwork_cache_root = artwork_cache_root
        self.artwork_hosts = artwork_hosts
        self.artwork_cache_max_bytes = artwork_cache_max_bytes
        self.artwork_cache_max_items = artwork_cache_max_items
        self.artwork_cache_max_age_seconds = artwork_cache_max_age_seconds


def main() -> None:
    host = os.environ.get("PILOT_DISPLAY_HOST", "127.0.0.1")
    port = int(os.environ.get("PILOT_DISPLAY_PORT", "8780"))
    core_url = os.environ.get("PILOT_CORE_URL", "http://127.0.0.1:8770")
    device_id = os.environ.get("PILOT_DEVICE_ID", "")
    device_token_file = os.environ.get(
        "PILOT_DEVICE_TOKEN_FILE", "/etc/pilot-display/device-token"
    )
    mode = os.environ.get("PILOT_DISPLAY_MODE", "display")
    artwork_cache_root = Path(
        os.environ.get("PILOT_ARTWORK_CACHE_DIR", str(DEFAULT_ARTWORK_CACHE))
    )
    artwork_hosts = tuple(
        host.strip().lower().rstrip(".")
        for host in os.environ.get(
            "PILOT_ARTWORK_HOSTS", ",".join(DEFAULT_ARTWORK_HOSTS)
        ).split(",")
        if host.strip()
    )
    artwork_cache_max_bytes = _positive_environment_integer(
        "PILOT_ARTWORK_CACHE_MAX_BYTES", DEFAULT_ARTWORK_CACHE_MAX_BYTES
    )
    artwork_cache_max_items = _positive_environment_integer(
        "PILOT_ARTWORK_CACHE_MAX_ITEMS", DEFAULT_ARTWORK_CACHE_MAX_ITEMS
    )
    artwork_cache_max_age_seconds = _positive_environment_integer(
        "PILOT_ARTWORK_CACHE_MAX_AGE_SECONDS",
        DEFAULT_ARTWORK_CACHE_MAX_AGE_SECONDS,
    )
    server = DisplayServer(
        (host, port),
        core_url,
        device_id,
        device_token_file,
        mode,
        artwork_cache_root,
        artwork_hosts,
        artwork_cache_max_bytes,
        artwork_cache_max_items,
        artwork_cache_max_age_seconds,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
