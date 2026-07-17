from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
                    default_device_id TEXT NOT NULL DEFAULT '',
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
                CREATE TABLE IF NOT EXISTS bootstrap_grants (
                    id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    device_id TEXT NOT NULL,
                    room_id TEXT NOT NULL REFERENCES rooms(id),
                    name TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                );
                CREATE INDEX IF NOT EXISTS bootstrap_grants_expiry
                    ON bootstrap_grants(expires_at);
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
                CREATE TABLE IF NOT EXISTS device_commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL REFERENCES devices(id),
                    room_id TEXT NOT NULL REFERENCES rooms(id),
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT,
                    completed_at TEXT,
                    expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS commands_device_created
                    ON device_commands(device_id, id DESC);
                CREATE TABLE IF NOT EXISTS audio_assets (
                    id TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL REFERENCES rooms(id),
                    kind TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS audio_assets_room_created
                    ON audio_assets(room_id, created_at DESC);
                """
            )
            room_columns = {
                row["name"]
                for row in self._connection.execute("PRAGMA table_info(rooms)")
            }
            if "default_device_id" not in room_columns:
                self._connection.execute(
                    """ALTER TABLE rooms ADD COLUMN default_device_id
                       TEXT NOT NULL DEFAULT ''"""
                )

    def sync_registry(self, settings: Settings) -> None:
        with self._lock, self._connection:
            for room in settings.rooms:
                self._connection.execute(
                    """INSERT INTO rooms
                       (id, name, response_player_id, default_music_player_id,
                        default_device_id, agent_url)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                         name=excluded.name,
                         response_player_id=excluded.response_player_id,
                         default_music_player_id=excluded.default_music_player_id,
                         default_device_id=excluded.default_device_id,
                         agent_url=excluded.agent_url""",
                    (
                        room.id,
                        room.name,
                        room.response_player_id,
                        room.default_music_player_id,
                        room.default_device_id,
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

    def create_bootstrap_grant(
        self,
        device_id: str,
        room_id: str,
        name: str,
        capabilities: list[str],
        ttl_seconds: int,
    ) -> dict[str, Any]:
        grant_id = secrets.token_hex(16)
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        with self._lock, self._connection:
            if not self._connection.execute(
                "SELECT 1 FROM rooms WHERE id = ?", (room_id,)
            ).fetchone():
                raise KeyError(room_id)
            self._connection.execute(
                """UPDATE bootstrap_grants SET used_at = ?
                   WHERE device_id = ? AND used_at IS NULL""",
                (now.isoformat(), device_id),
            )
            self._connection.execute(
                """INSERT INTO bootstrap_grants
                   (id, token_hash, device_id, room_id, name,
                    capabilities_json, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    grant_id,
                    _token_hash(token),
                    device_id,
                    room_id,
                    name,
                    json.dumps(sorted(set(capabilities))),
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
        return {
            "id": grant_id,
            "bootstrap_token": token,
            "device_id": device_id,
            "room_id": room_id,
            "name": name,
            "capabilities": sorted(set(capabilities)),
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }

    def redeem_bootstrap_grant(self, token: str) -> dict[str, str]:
        now = datetime.now(UTC)
        device_token = secrets.token_urlsafe(32)
        with self._lock, self._connection:
            grant = self._connection.execute(
                "SELECT * FROM bootstrap_grants WHERE token_hash = ?",
                (_token_hash(token),),
            ).fetchone()
            if (
                grant is None
                or grant["used_at"] is not None
                or datetime.fromisoformat(grant["expires_at"]) <= now
            ):
                raise PermissionError("invalid or expired bootstrap grant")
            cursor = self._connection.execute(
                """UPDATE bootstrap_grants SET used_at = ?
                   WHERE id = ? AND used_at IS NULL AND expires_at > ?""",
                (now.isoformat(), grant["id"], now.isoformat()),
            )
            if cursor.rowcount != 1:
                raise PermissionError("invalid or expired bootstrap grant")
            self._connection.execute(
                """INSERT INTO devices
                   (id, room_id, name, token_hash, capabilities_json,
                    created_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     room_id=excluded.room_id,
                     name=excluded.name,
                     token_hash=excluded.token_hash,
                     capabilities_json=excluded.capabilities_json,
                     last_seen_at=excluded.last_seen_at""",
                (
                    grant["device_id"],
                    grant["room_id"],
                    grant["name"],
                    _token_hash(device_token),
                    grant["capabilities_json"],
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return {
            "device_id": str(grant["device_id"]),
            "device_token": device_token,
        }

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

    def list_devices(self, room_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if room_id is None:
                rows = self._connection.execute(
                    """SELECT id, room_id, name, capabilities_json,
                              created_at, last_seen_at
                       FROM devices ORDER BY id"""
                ).fetchall()
            else:
                rows = self._connection.execute(
                    """SELECT id, room_id, name, capabilities_json,
                              created_at, last_seen_at
                       FROM devices WHERE room_id = ? ORDER BY id""",
                    (room_id,),
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

    def create_audio_asset(
        self,
        asset_id: str,
        room_id: str,
        kind: str,
        filename: str,
        content_type: str,
        digest: str,
        size_bytes: int,
        path: str,
        expires_at: str,
    ) -> dict[str, Any]:
        now = _now()
        with self._lock, self._connection:
            if not self._connection.execute(
                "SELECT 1 FROM rooms WHERE id = ?", (room_id,)
            ).fetchone():
                raise KeyError(room_id)
            self._connection.execute(
                """INSERT INTO audio_assets
                   (id, room_id, kind, filename, content_type, sha256,
                    size_bytes, path, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    asset_id,
                    room_id,
                    kind,
                    filename,
                    content_type,
                    digest,
                    size_bytes,
                    path,
                    now,
                    expires_at,
                ),
            )
        asset = self.get_audio_asset(asset_id)
        assert asset is not None
        return asset

    def get_audio_asset(self, asset_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM audio_assets WHERE id = ?", (asset_id,)
            ).fetchone()
        return self._audio_asset_view(row) if row else None

    def list_audio_assets(
        self, room_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self._lock:
            if room_id is None:
                rows = self._connection.execute(
                    "SELECT * FROM audio_assets ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = self._connection.execute(
                    """SELECT * FROM audio_assets WHERE room_id = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (room_id, limit),
                ).fetchall()
        return [self._audio_asset_view(row) for row in rows]

    def delete_audio_asset(self, asset_id: str) -> str | None:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT path FROM audio_assets WHERE id = ?", (asset_id,)
            ).fetchone()
            if row:
                self._connection.execute(
                    "DELETE FROM audio_assets WHERE id = ?", (asset_id,)
                )
        return str(row["path"]) if row else None

    def purge_expired_audio_assets(self) -> list[str]:
        now = _now()
        with self._lock, self._connection:
            rows = self._connection.execute(
                "SELECT path FROM audio_assets WHERE expires_at <= ?", (now,)
            ).fetchall()
            self._connection.execute(
                "DELETE FROM audio_assets WHERE expires_at <= ?", (now,)
            )
        return [str(row["path"]) for row in rows]

    def room_source_state(self, room_id: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT source, active, updated_at FROM source_state
                   WHERE room_id = ? ORDER BY source""",
                (room_id,),
            ).fetchall()
        return {
            row["source"]: {
                "active": bool(row["active"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        }

    def latest_device_health(self, device_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT payload_json, created_at FROM events
                   WHERE device_id = ? AND event_type = 'health'
                   ORDER BY id DESC LIMIT 1""",
                (device_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "payload": json.loads(row["payload_json"]),
            "updated_at": row["created_at"],
        }

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

    def create_command(
        self,
        device_id: str,
        payload: dict[str, Any],
        ttl_seconds: int,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        with self._lock, self._connection:
            device = self._connection.execute(
                "SELECT room_id FROM devices WHERE id = ?", (device_id,)
            ).fetchone()
            if not device:
                raise KeyError(device_id)
            cursor = self._connection.execute(
                """INSERT INTO device_commands
                   (device_id, room_id, payload_json, status, created_at, expires_at)
                   VALUES (?, ?, ?, 'queued', ?, ?)""",
                (
                    device_id,
                    device["room_id"],
                    json.dumps(payload, separators=(",", ":")),
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
            command_id = int(cursor.lastrowid)
        command = self.get_command(command_id)
        assert command is not None
        return command

    def get_command(self, command_id: int) -> dict[str, Any] | None:
        with self._lock, self._connection:
            self._expire_commands_locked()
            row = self._connection.execute(
                "SELECT * FROM device_commands WHERE id = ?", (command_id,)
            ).fetchone()
        return self._command_view(row) if row else None

    def list_commands(
        self, device_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self._lock, self._connection:
            self._expire_commands_locked()
            if device_id is None:
                rows = self._connection.execute(
                    "SELECT * FROM device_commands ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = self._connection.execute(
                    """SELECT * FROM device_commands
                       WHERE device_id = ? ORDER BY id DESC LIMIT ?""",
                    (device_id, limit),
                ).fetchall()
        return [self._command_view(row) for row in rows]

    def pending_commands(self, device_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connection:
            self._expire_commands_locked()
            rows = self._connection.execute(
                """SELECT * FROM device_commands
                   WHERE device_id = ? AND status IN ('queued', 'delivered')
                   ORDER BY id""",
                (device_id,),
            ).fetchall()
        return [self._command_view(row) for row in rows]

    def mark_command_delivered(self, command_id: int, device_id: str) -> bool:
        with self._lock, self._connection:
            self._expire_commands_locked()
            cursor = self._connection.execute(
                """UPDATE device_commands
                   SET status = 'delivered', delivered_at = ?
                   WHERE id = ? AND device_id = ?
                     AND status IN ('queued', 'delivered')""",
                (_now(), command_id, device_id),
            )
        return cursor.rowcount == 1

    def complete_command(
        self,
        command_id: int,
        device_id: str,
        status: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        if status not in {"succeeded", "failed"}:
            raise ValueError("command status must be succeeded or failed")
        with self._lock, self._connection:
            self._expire_commands_locked()
            existing = self._connection.execute(
                "SELECT * FROM device_commands WHERE id = ? AND device_id = ?",
                (command_id, device_id),
            ).fetchone()
            if not existing or existing["status"] == "expired":
                raise KeyError(command_id)
            if existing["status"] in {"succeeded", "failed"}:
                return self._command_view(existing)
            cursor = self._connection.execute(
                """UPDATE device_commands
                   SET status = ?, result_json = ?, completed_at = ?
                   WHERE id = ? AND device_id = ?
                     AND status IN ('queued', 'delivered')""",
                (
                    status,
                    json.dumps(result, separators=(",", ":")),
                    _now(),
                    command_id,
                    device_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(command_id)
        command = self.get_command(command_id)
        assert command is not None
        return command

    def _expire_commands_locked(self) -> None:
        self._connection.execute(
            """UPDATE device_commands
               SET status = 'expired', completed_at = ?
               WHERE status IN ('queued', 'delivered') AND expires_at <= ?""",
            (_now(), _now()),
        )

    @staticmethod
    def _command_view(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "device_id": row["device_id"],
            "room_id": row["room_id"],
            "payload": json.loads(row["payload_json"]),
            "status": row["status"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "created_at": row["created_at"],
            "delivered_at": row["delivered_at"],
            "completed_at": row["completed_at"],
            "expires_at": row["expires_at"],
        }

    @staticmethod
    def _audio_asset_view(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "room_id": row["room_id"],
            "kind": row["kind"],
            "filename": row["filename"],
            "content_type": row["content_type"],
            "sha256": row["sha256"],
            "size_bytes": row["size_bytes"],
            "path": row["path"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }
