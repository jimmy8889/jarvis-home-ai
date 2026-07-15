from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import secrets
import sqlite3
from threading import RLock
from typing import Any

from .config import Settings
from .focus import decide_focus


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _token_hash(token: str) -> str:
    return sha256(token.encode()).hexdigest()


class Store:
    def __init__(self, path: str, settings: Settings) -> None:
        db_path = Path(path)
        if path != ":memory:":
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._initialize()
        self.sync_registry(settings)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS rooms (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    response_player_id TEXT NOT NULL,
                    default_music_player_id TEXT NOT NULL,
                    agent_url TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS players (
                    id TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL REFERENCES rooms(id),
                    name TEXT NOT NULL,
                    protocol TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    endpoint TEXT NOT NULL DEFAULT '',
                    external_id TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL REFERENCES rooms(id),
                    name TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_state (
                    room_id TEXT NOT NULL REFERENCES rooms(id),
                    source TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(room_id, source)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id TEXT NOT NULL REFERENCES rooms(id),
                    device_id TEXT NOT NULL REFERENCES devices(id),
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_room_created
                    ON events(room_id, created_at DESC);
                """
            )

    def sync_registry(self, settings: Settings) -> None:
        with self._lock, self._connection:
            for room in settings.rooms:
                self._connection.execute(
                    """INSERT INTO rooms
                       (id, name, response_player_id, default_music_player_id, agent_url)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                         name=excluded.name,
                         response_player_id=excluded.response_player_id,
                         default_music_player_id=excluded.default_music_player_id,
                         agent_url=excluded.agent_url""",
                    (
                        room.id,
                        room.name,
                        room.response_player_id,
                        room.default_music_player_id,
                        room.agent_url,
                    ),
                )
            for player in settings.players:
                self._connection.execute(
                    """INSERT INTO players
                       (id, room_id, name, protocol, kind, endpoint, external_id, enabled)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                         room_id=excluded.room_id,
                         name=excluded.name,
                         protocol=excluded.protocol,
                         kind=excluded.kind,
                         endpoint=excluded.endpoint,
                         external_id=excluded.external_id,
                         enabled=excluded.enabled""",
                    (
                        player.id,
                        player.room_id,
                        player.name,
                        player.protocol,
                        player.kind,
                        player.endpoint,
                        player.external_id,
                        int(player.enabled),
                    ),
                )

    def register_device(
        self, device_id: str, room_id: str, name: str, capabilities: list[str]
    ) -> str:
        token = secrets.token_urlsafe(32)
        now = _now()
        with self._lock, self._connection:
            if not self._connection.execute(
                "SELECT 1 FROM rooms WHERE id = ?", (room_id,)
            ).fetchone():
                raise KeyError(room_id)
            self._connection.execute(
                """INSERT INTO devices
                   (id, room_id, name, token_hash, capabilities_json, created_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     room_id=excluded.room_id,
                     name=excluded.name,
                     token_hash=excluded.token_hash,
                     capabilities_json=excluded.capabilities_json,
                     last_seen_at=excluded.last_seen_at""",
                (
                    device_id,
                    room_id,
                    name,
                    _token_hash(token),
                    json.dumps(sorted(set(capabilities))),
                    now,
                    now,
                ),
            )
        return token

    def authenticate_device(self, device_id: str, token: str) -> bool:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT token_hash FROM devices WHERE id = ?", (device_id,)
            ).fetchone()
            valid = bool(row and secrets.compare_digest(row["token_hash"], _token_hash(token)))
            if valid:
                self._connection.execute(
                    "UPDATE devices SET last_seen_at = ? WHERE id = ?",
                    (_now(), device_id),
                )
            return valid

    def list_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT id, room_id, name, capabilities_json, created_at, last_seen_at
                   FROM devices ORDER BY id"""
            ).fetchall()
        return [
            {
                "id": row["id"],
                "room_id": row["room_id"],
                "name": row["name"],
                "capabilities": json.loads(row["capabilities_json"]),
                "created_at": row["created_at"],
                "last_seen_at": row["last_seen_at"],
            }
            for row in rows
        ]

    def record_event(
        self,
        device_id: str,
        room_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        now = _now()
        with self._lock, self._connection:
            device = self._connection.execute(
                "SELECT room_id FROM devices WHERE id = ?", (device_id,)
            ).fetchone()
            if not device or device["room_id"] != room_id:
                raise PermissionError("device is not assigned to this room")
            cursor = self._connection.execute(
                """INSERT INTO events
                   (room_id, device_id, event_type, payload_json, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (room_id, device_id, event_type, json.dumps(payload), now),
            )
            if event_type == "source_state":
                source = str(payload["source"])
                active = bool(payload["active"])
                self._connection.execute(
                    """INSERT INTO source_state(room_id, source, active, updated_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(room_id, source) DO UPDATE SET
                         active=excluded.active, updated_at=excluded.updated_at""",
                    (room_id, source, int(active), now),
                )
        event = {
            "id": cursor.lastrowid,
            "room_id": room_id,
            "device_id": device_id,
            "type": event_type,
            "payload": payload,
            "created_at": now,
        }
        if event_type == "source_state":
            event["focus"] = self.room_focus(room_id)
        return event

    def room_focus(self, room_id: str) -> dict[str, object]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT source, active FROM source_state WHERE room_id = ?",
                (room_id,),
            ).fetchall()
        active = {row["source"]: bool(row["active"]) for row in rows}
        return decide_focus(active).as_dict()

    def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT id, room_id, device_id, event_type, payload_json, created_at
                   FROM events ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "room_id": row["room_id"],
                "device_id": row["device_id"],
                "type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
