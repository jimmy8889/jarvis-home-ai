from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from threading import Event, Lock, Thread
import time
from typing import Any, Callable
from urllib.parse import quote, urlsplit, urlunsplit

from websockets.sync.client import connect

from .config import Settings
from .controls import ControlError, RoomController


def _now() -> str:
    return datetime.now(UTC).isoformat()


class CommandJournal:
    """Durable command result journal used to make delivery idempotent."""

    def __init__(self, path: str) -> None:
        database_path = Path(path)
        if path != ":memory:":
            database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = Lock()
        with self.connection:
            self.connection.execute(
                """CREATE TABLE IF NOT EXISTS command_results (
                       command_id INTEGER PRIMARY KEY,
                       status TEXT NOT NULL,
                       result_json TEXT NOT NULL,
                       completed_at TEXT NOT NULL
                   )"""
            )

    def close(self) -> None:
        with self.lock:
            self.connection.close()

    def get(self, command_id: int) -> dict[str, Any] | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT * FROM command_results WHERE command_id = ?", (command_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "type": "command_result",
            "command_id": command_id,
            "status": row["status"],
            "result": json.loads(row["result_json"]),
        }

    def record(
        self, command_id: int, status: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        with self.lock, self.connection:
            self.connection.execute(
                """INSERT INTO command_results
                   (command_id, status, result_json, completed_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(command_id) DO NOTHING""",
                (
                    command_id,
                    status,
                    json.dumps(result, separators=(",", ":")),
                    _now(),
                ),
            )
            self.connection.execute(
                """DELETE FROM command_results WHERE command_id NOT IN (
                       SELECT command_id FROM command_results
                       ORDER BY command_id DESC LIMIT 1000
                   )"""
            )
        recorded = self.get(command_id)
        assert recorded is not None
        return recorded


class CommandClient:
    def __init__(
        self,
        settings: Settings,
        controller: RoomController,
        connector: Callable[..., Any] | None = None,
        journal: CommandJournal | None = None,
    ) -> None:
        self.settings = settings
        self.controller = controller
        self.connector = connector or connect
        self.journal = journal or CommandJournal(settings.core_command_journal_path)
        self.stop_event = Event()
        self.thread = Thread(target=self._run, name="pilot-core-commands", daemon=True)
        self.state_lock = Lock()
        self.socket: Any | None = None
        self.connected = False
        self.last_error = ""
        self.last_connected_at: str | None = None
        self.commands_received = 0

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        socket = self.socket
        if socket is not None:
            try:
                socket.close()
            except Exception:
                pass
        self.thread.join(timeout=5)
        self.journal.close()

    def status(self) -> dict[str, Any]:
        with self.state_lock:
            return {
                "enabled": True,
                "connected": self.connected,
                "last_connected_at": self.last_connected_at,
                "last_error": self.last_error,
                "commands_received": self.commands_received,
            }

    def websocket_url(self) -> str:
        parts = urlsplit(self.settings.core_url)
        if parts.scheme not in {"http", "https", "ws", "wss"} or not parts.netloc:
            raise ValueError("core_url must be an absolute HTTP or WebSocket URL")
        scheme = {"http": "ws", "https": "wss"}.get(parts.scheme, parts.scheme)
        base_path = parts.path.rstrip("/")
        path = f"{base_path}/v1/devices/ws"
        query = f"device_id={quote(self.settings.core_device_id, safe='')}"
        return urlunsplit((scheme, parts.netloc, path, query, ""))

    def run_once(self) -> None:
        token = Path(self.settings.core_device_token_file).read_text(
            encoding="utf-8"
        ).strip()
        if not token:
            raise ValueError("Pilot Core device token is empty")
        with self.connector(
            self.websocket_url(),
            additional_headers={"Authorization": f"Bearer {token}"},
            open_timeout=5,
            close_timeout=2,
        ) as socket:
            self.socket = socket
            self._set_connection(True, "")
            next_heartbeat = time.monotonic() + self.settings.core_command_heartbeat_seconds
            try:
                while not self.stop_event.is_set():
                    try:
                        raw = socket.recv(timeout=1)
                    except TimeoutError:
                        raw = None
                    if raw is not None:
                        self._handle_message(socket, raw)
                    if time.monotonic() >= next_heartbeat:
                        socket.send(json.dumps({"type": "heartbeat"}))
                        next_heartbeat = (
                            time.monotonic()
                            + self.settings.core_command_heartbeat_seconds
                        )
            finally:
                self.socket = None
                self._set_connection(False, self.last_error)

    def _run(self) -> None:
        delay = self.settings.core_command_reconnect_min_seconds
        while not self.stop_event.is_set():
            try:
                self.run_once()
                delay = self.settings.core_command_reconnect_min_seconds
            except Exception as error:
                self._set_connection(False, str(error))
            if self.stop_event.wait(delay):
                break
            delay = min(
                delay * 2, self.settings.core_command_reconnect_max_seconds
            )

    def _handle_message(self, socket: Any, raw: str | bytes) -> None:
        try:
            message = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            return
        if not isinstance(message, dict) or message.get("type") != "command":
            return
        command = message.get("command")
        if not isinstance(command, dict):
            return
        command_id = command.get("id")
        payload = command.get("payload")
        if isinstance(command_id, bool) or not isinstance(command_id, int):
            return
        if not isinstance(payload, dict):
            return

        cached = self.journal.get(command_id)
        if cached is not None:
            socket.send(json.dumps(cached, separators=(",", ":")))
            return

        try:
            execution = self.controller.execute(payload).as_dict()
            status = "succeeded"
            result = execution
        except (ControlError, OSError, ValueError) as error:
            status = "failed"
            result = {"ok": False, "error": str(error)}
        recorded = self.journal.record(command_id, status, result)
        with self.state_lock:
            self.commands_received += 1
        socket.send(json.dumps(recorded, separators=(",", ":")))

    def _set_connection(self, connected: bool, error: str) -> None:
        with self.state_lock:
            self.connected = connected
            self.last_error = error
            if connected:
                self.last_connected_at = _now()
