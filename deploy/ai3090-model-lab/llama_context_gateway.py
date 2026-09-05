#!/usr/bin/env python3
"""Authenticated model-ID selector for the single-resident 35B llama.cpp server."""
from __future__ import annotations

import http.client
import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UPSTREAM_HOST = "127.0.0.1"
UPSTREAM_PORT = 8000
TOKEN = os.environ.get("VLLM_API_KEY", "")
STATE_DIR = Path("/var/lib/llama-context-gateway")
STATE_FILE = STATE_DIR / "active-context"
PROFILES = {
    "qwen35b-8k": 8192,
    "qwen35b-16k": 16384,
    "qwen35b-32k": 32768,
    "qwen35b-64k": 65536,
    "qwen35b-128k": 131072,
}
DEFAULT_ID = "qwen35b-8k"
LOCK = threading.Lock()


def service_for(context: int) -> str:
    return f"llama-35b@{context}.service"


def active_context() -> int:
    try:
        value = int(STATE_FILE.read_text().strip())
        if value in PROFILES.values():
            return value
    except (OSError, ValueError):
        pass
    return 8192


def run_systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["/usr/bin/systemctl", *args], check=check, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def wait_healthy(timeout: int = 90) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            conn = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=2)
            conn.request("GET", "/health")
            result = conn.getresponse()
            result.read()
            conn.close()
            if 200 <= result.status < 300:
                return True
        except OSError:
            pass
        time.sleep(1)
    return False


def activate(context: int) -> None:
    previous = active_context()
    if previous == context and wait_healthy(2):
        return
    run_systemctl("stop", service_for(previous), check=False)
    try:
        run_systemctl("start", service_for(context))
        if not wait_healthy():
            raise RuntimeError(f"{service_for(context)} did not become healthy")
        STATE_DIR.mkdir(mode=0o750, parents=True, exist_ok=True)
        STATE_FILE.write_text(f"{context}\n")
    except Exception as exc:
        run_systemctl("stop", service_for(context), check=False)
        if previous != context:
            run_systemctl("start", service_for(previous), check=False)
            if wait_healthy():
                STATE_DIR.mkdir(mode=0o750, parents=True, exist_ok=True)
                STATE_FILE.write_text(f"{previous}\n")
        raise RuntimeError(str(exc)) from exc


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        print("%s - %s" % (self.address_string(), format % args), flush=True)

    def authorized(self) -> bool:
        return bool(TOKEN) and self.headers.get("Authorization", "") == f"Bearer {TOKEN}"

    def send_json(self, status: int, payload: object) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def require_auth(self) -> bool:
        if self.authorized():
            return True
        self.send_json(401, {"error": {"message": "Unauthorized", "type": "authentication_error"}})
        return False

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(200, {"status": "ok", "active_context": active_context()})
            return
        if self.path == "/v1/models":
            if not self.require_auth():
                return
            self.send_json(200, {"object": "list", "data": [
                {"id": model, "object": "model", "owned_by": "ai3090"}
                for model in PROFILES
            ]})
            return
        if self.path.startswith("/v1/models/"):
            if not self.require_auth():
                return
            model = self.path.rsplit("/", 1)[-1]
            if model == "primary":
                model = DEFAULT_ID
            if model in PROFILES:
                self.send_json(200, {"id": model, "object": "model", "owned_by": "ai3090"})
                return
        self.send_json(404, {"error": {"message": "Not found"}})

    def read_body(self) -> bytes:
        """Accept both ordinary and chunked OpenAI-client request bodies."""
        if self.headers.get("Transfer-Encoding", "").lower() != "chunked":
            return self.rfile.read(int(self.headers.get("Content-Length", "0")))
        parts = []
        while True:
            line = self.rfile.readline().strip()
            size = int(line.split(b";", 1)[0], 16)
            if size == 0:
                self.rfile.readline()
                return b"".join(parts)
            parts.append(self.rfile.read(size))
            self.rfile.read(2)

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            # Hermes probes several Ollama endpoints before selecting its
            # OpenAI transport. Consume a request body before replying so a
            # persistent HTTP connection remains in sync.
            try:
                self.read_body()
            except (OSError, ValueError):
                pass
            self.send_json(404, {"error": {"message": "Not found"}})
            return
        if not self.require_auth():
            return
        try:
            body = self.read_body()
            request = json.loads(body)
            model = request.get("model", DEFAULT_ID)
            # Hermes may qualify a custom-provider model as
            # "provider-id/model-id" on the wire.
            if isinstance(model, str) and "/" in model:
                model = model.rsplit("/", 1)[-1]
            if model == "primary":  # Retain compatibility with existing Pilot clients.
                model = DEFAULT_ID
            context = PROFILES[model]
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            self.log_message("invalid chat selection: %s", exc)
            self.send_json(400, {"error": {"message": "Use one of: " + ", ".join(PROFILES)}})
            return

        with LOCK:
            try:
                activate(context)
                conn = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=720)
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
                conn.request("POST", "/v1/chat/completions", body=body, headers=headers)
                response = conn.getresponse()
                streaming = bool(request.get("stream"))
                self.send_response(response.status)
                for name, value in response.getheaders():
                    # BaseHTTPRequestHandler writes its own Server and Date
                    # headers. Forwarding llama.cpp's copies makes strict
                    # clients (notably SurfSense/aiohttp) reject the response.
                    if name.lower() not in {"connection", "transfer-encoding", "content-length", "server", "date"}:
                        self.send_header(name, value)
                if streaming:
                    self.send_header("Connection", "close")
                    self.close_connection = True
                else:
                    response_body = response.read()
                    self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                if streaming:
                    while chunk := response.read(8192):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                else:
                    self.wfile.write(response_body)
                conn.close()
            except (OSError, RuntimeError, http.client.HTTPException) as exc:
                self.send_json(503, {"error": {"message": f"Context server unavailable: {exc}", "type": "server_error"}})


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("VLLM_API_KEY is required")
    ThreadingHTTPServer(("0.0.0.0", 8001), Handler).serve_forever()
