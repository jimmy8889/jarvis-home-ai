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
        self._conversation_ttl_seconds = (
            settings.server.conversation_session_ttl_seconds
        )
        self._conversation_max_turns = settings.server.conversation_max_turns
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
                    control_endpoint TEXT NOT NULL DEFAULT '',
                    external_id TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    control_enabled INTEGER NOT NULL DEFAULT 1
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
                CREATE TABLE IF NOT EXISTS conversation_sessions (
                    id TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL REFERENCES rooms(id),
                    device_id TEXT,
                    user_id TEXT,
                    provider_conversation_id TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS conversation_sessions_room_updated
                    ON conversation_sessions(room_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS conversation_sessions_expiry
                    ON conversation_sessions(status, expires_at);
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES conversation_sessions(id)
                        ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS conversation_turns_session
                    ON conversation_turns(session_id, id);
                CREATE TABLE IF NOT EXISTS meetings (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    language TEXT NOT NULL,
                    source_device_id TEXT,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL,
                    summary TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS meetings_started
                    ON meetings(started_at DESC);
                CREATE TABLE IF NOT EXISTS meeting_recordings (
                    meeting_id TEXT PRIMARY KEY REFERENCES meetings(id)
                        ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meeting_participants (
                    id TEXT PRIMARY KEY,
                    meeting_id TEXT NOT NULL REFERENCES meetings(id)
                        ON DELETE CASCADE,
                    display_name TEXT,
                    speaker_label TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(meeting_id, speaker_label)
                );
                CREATE TABLE IF NOT EXISTS transcript_segments (
                    id TEXT PRIMARY KEY,
                    meeting_id TEXT NOT NULL REFERENCES meetings(id)
                        ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    speaker_label TEXT,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    confidence REAL,
                    created_at TEXT NOT NULL,
                    UNIQUE(meeting_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS transcript_meeting_sequence
                    ON transcript_segments(meeting_id, sequence);
                CREATE TABLE IF NOT EXISTS meeting_decisions (
                    id TEXT PRIMARY KEY,
                    meeting_id TEXT NOT NULL REFERENCES meetings(id)
                        ON DELETE CASCADE,
                    summary TEXT NOT NULL,
                    segment_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meeting_action_items (
                    id TEXT PRIMARY KEY,
                    meeting_id TEXT NOT NULL REFERENCES meetings(id)
                        ON DELETE CASCADE,
                    task TEXT NOT NULL,
                    owner TEXT,
                    due_at TEXT,
                    status TEXT NOT NULL,
                    confidence REAL,
                    segment_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS home_catalog_syncs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    entity_count INTEGER NOT NULL DEFAULT 0,
                    upserted_count INTEGER NOT NULL DEFAULT 0,
                    missing_count INTEGER NOT NULL DEFAULT 0,
                    metadata_status TEXT NOT NULL DEFAULT 'not_attempted',
                    metadata_error TEXT,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS home_catalog_syncs_started
                    ON home_catalog_syncs(started_at DESC);
                CREATE TABLE IF NOT EXISTS home_entities (
                    entity_id TEXT PRIMARY KEY,
                    stable_id TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    name TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attributes_json TEXT NOT NULL,
                    area_id TEXT,
                    device_id TEXT,
                    aliases_json TEXT NOT NULL,
                    availability TEXT NOT NULL,
                    observed_at TEXT,
                    synced_at TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    missing INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS home_entities_domain
                    ON home_entities(domain);
                CREATE INDEX IF NOT EXISTS home_entities_area
                    ON home_entities(area_id);
                CREATE INDEX IF NOT EXISTS home_entities_availability
                    ON home_entities(availability, missing);
                CREATE INDEX IF NOT EXISTS home_entities_name
                    ON home_entities(name COLLATE NOCASE);
                CREATE TABLE IF NOT EXISTS home_floors (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    level INTEGER,
                    synced_at TEXT NOT NULL,
                    missing INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS home_areas (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    floor_id TEXT,
                    synced_at TEXT NOT NULL,
                    missing INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS home_areas_floor
                    ON home_areas(floor_id);
                CREATE TABLE IF NOT EXISTS home_devices (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    area_id TEXT,
                    manufacturer TEXT,
                    model TEXT,
                    synced_at TEXT NOT NULL,
                    missing INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS home_devices_area
                    ON home_devices(area_id);
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
            player_columns = {
                row["name"]
                for row in self._connection.execute("PRAGMA table_info(players)")
            }
            if "control_enabled" not in player_columns:
                self._connection.execute(
                    """ALTER TABLE players ADD COLUMN control_enabled
                       INTEGER NOT NULL DEFAULT 1"""
                )
            if "control_endpoint" not in player_columns:
                self._connection.execute(
                    """ALTER TABLE players ADD COLUMN control_endpoint
                       TEXT NOT NULL DEFAULT ''"""
                )
            sync_columns = {
                row["name"]
                for row in self._connection.execute(
                    "PRAGMA table_info(home_catalog_syncs)"
                )
            }
            if "metadata_status" not in sync_columns:
                self._connection.execute(
                    """ALTER TABLE home_catalog_syncs ADD COLUMN metadata_status
                       TEXT NOT NULL DEFAULT 'not_attempted'"""
                )
            if "metadata_error" not in sync_columns:
                self._connection.execute(
                    """ALTER TABLE home_catalog_syncs ADD COLUMN metadata_error TEXT"""
                )

    def resolve_conversation_session(
        self,
        room_id: str,
        session_id: str | None = None,
        device_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self._conversation_ttl_seconds)
        with self._lock, self._connection:
            self._expire_conversations_locked(now)
            if session_id:
                row = self._connection.execute(
                    """SELECT * FROM conversation_sessions
                       WHERE id = ? AND room_id = ? AND status = 'active'
                         AND expires_at > ?""",
                    (session_id, room_id, now.isoformat()),
                ).fetchone()
                if row is not None:
                    if device_id and row["device_id"] not in {None, "", device_id}:
                        row = None
                    if (
                        user_id
                        and row is not None
                        and row["user_id"]
                        not in {
                            None,
                            "",
                            user_id,
                        }
                    ):
                        row = None
                if row is not None:
                    self._connection.execute(
                        """UPDATE conversation_sessions
                           SET updated_at = ?, expires_at = ? WHERE id = ?""",
                        (now.isoformat(), expires_at.isoformat(), row["id"]),
                    )
                    refreshed = self._connection.execute(
                        "SELECT * FROM conversation_sessions WHERE id = ?",
                        (row["id"],),
                    ).fetchone()
                    assert refreshed is not None
                    return self._conversation_session_view(refreshed)

            if not self._connection.execute(
                "SELECT 1 FROM rooms WHERE id = ?", (room_id,)
            ).fetchone():
                raise KeyError(room_id)
            new_id = secrets.token_hex(16)
            self._connection.execute(
                """INSERT INTO conversation_sessions
                   (id, room_id, device_id, user_id, provider_conversation_id,
                    status, created_at, updated_at, expires_at)
                   VALUES (?, ?, ?, ?, NULL, 'active', ?, ?, ?)""",
                (
                    new_id,
                    room_id,
                    device_id,
                    user_id,
                    now.isoformat(),
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
            row = self._connection.execute(
                "SELECT * FROM conversation_sessions WHERE id = ?", (new_id,)
            ).fetchone()
        assert row is not None
        return self._conversation_session_view(row)

    def get_conversation_session(
        self,
        session_id: str,
        include_turns: bool = False,
    ) -> dict[str, Any] | None:
        with self._lock, self._connection:
            self._expire_conversations_locked(datetime.now(UTC))
            row = self._connection.execute(
                "SELECT * FROM conversation_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return None
            result = self._conversation_session_view(row)
            if include_turns:
                result["turns"] = self._conversation_turns_locked(session_id, None)
            return result

    def list_conversation_sessions(
        self,
        room_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if status is not None and status not in {"active", "ended", "expired"}:
            raise ValueError("invalid conversation status")
        clauses: list[str] = []
        values: list[Any] = []
        if room_id is not None:
            clauses.append("room_id = ?")
            values.append(room_id)
        if status is not None:
            clauses.append("status = ?")
            values.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(limit)
        with self._lock, self._connection:
            self._expire_conversations_locked(datetime.now(UTC))
            rows = self._connection.execute(
                f"""SELECT conversation_sessions.*,
                           (SELECT COUNT(*) FROM conversation_turns
                            WHERE session_id = conversation_sessions.id)
                              AS turn_count
                    FROM conversation_sessions{where}
                    ORDER BY updated_at DESC LIMIT ?""",
                values,
            ).fetchall()
        return [
            {
                **self._conversation_session_view(row),
                "turn_count": int(row["turn_count"]),
            }
            for row in rows
        ]

    def conversation_turns(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            return self._conversation_turns_locked(session_id, limit)

    def append_conversation_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if role not in {"user", "assistant", "tool"}:
            raise ValueError("invalid conversation role")
        normalized = content.strip()
        if not normalized:
            raise ValueError("conversation content must not be empty")
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self._conversation_ttl_seconds)
        with self._lock, self._connection:
            session = self._connection.execute(
                """SELECT 1 FROM conversation_sessions
                   WHERE id = ? AND status = 'active'""",
                (session_id,),
            ).fetchone()
            if session is None:
                raise KeyError(session_id)
            cursor = self._connection.execute(
                """INSERT INTO conversation_turns
                   (session_id, role, content, metadata_json, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    session_id,
                    role,
                    normalized,
                    json.dumps(metadata or {}, separators=(",", ":")),
                    now.isoformat(),
                ),
            )
            self._connection.execute(
                """UPDATE conversation_sessions
                   SET updated_at = ?, expires_at = ? WHERE id = ?""",
                (now.isoformat(), expires_at.isoformat(), session_id),
            )
            self._connection.execute(
                """DELETE FROM conversation_turns
                   WHERE session_id = ? AND id NOT IN (
                     SELECT id FROM conversation_turns WHERE session_id = ?
                     ORDER BY id DESC LIMIT ?
                   )""",
                (session_id, session_id, self._conversation_max_turns),
            )
            row = self._connection.execute(
                "SELECT * FROM conversation_turns WHERE id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()
        assert row is not None
        return self._conversation_turn_view(row)

    def update_conversation_provider_id(
        self,
        session_id: str,
        provider_conversation_id: str | None,
    ) -> None:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """UPDATE conversation_sessions
                   SET provider_conversation_id = ?, updated_at = ?
                   WHERE id = ? AND status = 'active'""",
                (provider_conversation_id, _now(), session_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(session_id)

    def end_conversation_session(self, session_id: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """UPDATE conversation_sessions
                   SET status = 'ended', updated_at = ?
                   WHERE id = ? AND status = 'active'""",
                (_now(), session_id),
            )
        return cursor.rowcount == 1

    def _expire_conversations_locked(self, now: datetime) -> None:
        self._connection.execute(
            """UPDATE conversation_sessions
               SET status = 'expired', updated_at = ?
               WHERE status = 'active' AND expires_at <= ?""",
            (now.isoformat(), now.isoformat()),
        )

    def _conversation_turns_locked(
        self,
        session_id: str,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        if limit is None:
            rows = self._connection.execute(
                """SELECT * FROM conversation_turns
                   WHERE session_id = ? ORDER BY id""",
                (session_id,),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """SELECT * FROM (
                     SELECT * FROM conversation_turns
                     WHERE session_id = ? ORDER BY id DESC LIMIT ?
                   ) ORDER BY id""",
                (session_id, limit),
            ).fetchall()
        return [self._conversation_turn_view(row) for row in rows]

    @staticmethod
    def _conversation_session_view(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "room_id": row["room_id"],
            "device_id": row["device_id"],
            "user_id": row["user_id"],
            "provider_conversation_id": row["provider_conversation_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "expires_at": row["expires_at"],
        }

    @staticmethod
    def _conversation_turn_view(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "role": row["role"],
            "content": row["content"],
            "metadata": json.loads(row["metadata_json"]),
            "created_at": row["created_at"],
        }

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
                       (id, room_id, name, protocol, kind, endpoint,
                        control_endpoint, external_id, enabled, control_enabled)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                         room_id=excluded.room_id,
                         name=excluded.name,
                         protocol=excluded.protocol,
                         kind=excluded.kind,
                         endpoint=excluded.endpoint,
                         control_endpoint=excluded.control_endpoint,
                         external_id=excluded.external_id,
                         enabled=excluded.enabled,
                         control_enabled=excluded.control_enabled""",
                    (
                        player.id,
                        player.room_id,
                        player.name,
                        player.protocol,
                        player.kind,
                        player.endpoint,
                        player.control_endpoint,
                        player.external_id,
                        int(player.enabled),
                        int(player.control_enabled),
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
            valid = bool(
                row and secrets.compare_digest(row["token_hash"], _token_hash(token))
            )
            if valid:
                self._connection.execute(
                    "UPDATE devices SET last_seen_at = ? WHERE id = ?",
                    (_now(), device_id),
                )
            return valid

    def update_device_capabilities(
        self, device_id: str, capabilities: list[str]
    ) -> dict[str, Any]:
        normalized = sorted(set(capabilities))
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE devices SET capabilities_json = ? WHERE id = ?",
                (json.dumps(normalized), device_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(device_id)
        return next(
            device for device in self.list_devices() if device["id"] == device_id
        )

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

    def create_meeting(
        self,
        title: str,
        language: str,
        started_at: str,
        source_device_id: str | None,
    ) -> dict[str, Any]:
        meeting_id = secrets.token_hex(16)
        now = _now()
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO meetings
                   (id, title, language, source_device_id, started_at, status,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'created', ?, ?)""",
                (
                    meeting_id,
                    title,
                    language,
                    source_device_id,
                    started_at,
                    now,
                    now,
                ),
            )
        meeting = self.get_meeting(meeting_id)
        assert meeting is not None
        return meeting

    def list_meetings(
        self, limit: int = 50, status: str | None = None
    ) -> list[dict[str, Any]]:
        query = """
            SELECT m.*,
                   EXISTS(
                     SELECT 1 FROM meeting_recordings r
                     WHERE r.meeting_id = m.id
                   ) AS has_recording,
                   (
                     SELECT COUNT(*) FROM transcript_segments s
                     WHERE s.meeting_id = m.id
                   ) AS transcript_segment_count,
                   (
                     SELECT COUNT(*) FROM meeting_action_items a
                     WHERE a.meeting_id = m.id
                   ) AS action_item_count
            FROM meetings m
        """
        params: list[Any] = []
        if status is not None:
            query += " WHERE m.status = ?"
            params.append(status)
        query += " ORDER BY m.started_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._meeting_summary(row) for row in rows]

    def get_meeting(self, meeting_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM meetings WHERE id = ?", (meeting_id,)
            ).fetchone()
            if row is None:
                return None
            recording = self._connection.execute(
                """SELECT * FROM meeting_recordings
                   WHERE meeting_id = ?""",
                (meeting_id,),
            ).fetchone()
            participants = self._connection.execute(
                """SELECT id, display_name, speaker_label, created_at
                   FROM meeting_participants
                   WHERE meeting_id = ? ORDER BY speaker_label""",
                (meeting_id,),
            ).fetchall()
            segments = self._connection.execute(
                """SELECT id, sequence, speaker_label, start_ms, end_ms, text,
                          confidence, created_at
                   FROM transcript_segments
                   WHERE meeting_id = ? ORDER BY sequence""",
                (meeting_id,),
            ).fetchall()
            decisions = self._connection.execute(
                """SELECT id, summary, segment_ids_json, created_at
                   FROM meeting_decisions
                   WHERE meeting_id = ? ORDER BY created_at, id""",
                (meeting_id,),
            ).fetchall()
            actions = self._connection.execute(
                """SELECT id, task, owner, due_at, status, confidence,
                          segment_ids_json, created_at, updated_at
                   FROM meeting_action_items
                   WHERE meeting_id = ? ORDER BY created_at, id""",
                (meeting_id,),
            ).fetchall()
        return {
            **self._meeting_row(row),
            "recording": self._recording_view(recording) if recording else None,
            "participants": [dict(item) for item in participants],
            "transcript": [dict(item) for item in segments],
            "decisions": [
                {
                    "id": item["id"],
                    "summary": item["summary"],
                    "segment_ids": json.loads(item["segment_ids_json"]),
                    "created_at": item["created_at"],
                }
                for item in decisions
            ],
            "action_items": [
                {
                    "id": item["id"],
                    "task": item["task"],
                    "owner": item["owner"],
                    "due_at": item["due_at"],
                    "status": item["status"],
                    "confidence": item["confidence"],
                    "segment_ids": json.loads(item["segment_ids_json"]),
                    "created_at": item["created_at"],
                    "updated_at": item["updated_at"],
                }
                for item in actions
            ],
        }

    def get_meeting_recording(self, meeting_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT * FROM meeting_recordings
                   WHERE meeting_id = ?""",
                (meeting_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            **self._recording_view(row),
            "path": row["path"],
        }

    def set_meeting_recording(
        self,
        meeting_id: str,
        filename: str,
        content_type: str,
        digest: str,
        size_bytes: int,
        path: str,
    ) -> dict[str, Any]:
        now = _now()
        with self._lock, self._connection:
            if not self._connection.execute(
                "SELECT 1 FROM meetings WHERE id = ?", (meeting_id,)
            ).fetchone():
                raise KeyError(meeting_id)
            self._connection.execute(
                """INSERT INTO meeting_recordings
                   (meeting_id, filename, content_type, sha256, size_bytes,
                    path, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(meeting_id) DO UPDATE SET
                     filename=excluded.filename,
                     content_type=excluded.content_type,
                     sha256=excluded.sha256,
                     size_bytes=excluded.size_bytes,
                     path=excluded.path,
                     created_at=excluded.created_at""",
                (
                    meeting_id,
                    filename,
                    content_type,
                    digest,
                    size_bytes,
                    path,
                    now,
                ),
            )
            self._connection.execute(
                """UPDATE meetings SET status = 'recorded', updated_at = ?
                   WHERE id = ?""",
                (now, meeting_id),
            )
        meeting = self.get_meeting(meeting_id)
        assert meeting is not None and meeting["recording"] is not None
        return meeting["recording"]

    def replace_transcript(
        self, meeting_id: str, segments: list[dict[str, Any]]
    ) -> dict[str, Any]:
        now = _now()
        with self._lock, self._connection:
            if not self._connection.execute(
                "SELECT 1 FROM meetings WHERE id = ?", (meeting_id,)
            ).fetchone():
                raise KeyError(meeting_id)
            self._connection.execute(
                "DELETE FROM transcript_segments WHERE meeting_id = ?",
                (meeting_id,),
            )
            for sequence, segment in enumerate(segments):
                self._connection.execute(
                    """INSERT INTO transcript_segments
                       (id, meeting_id, sequence, speaker_label, start_ms,
                        end_ms, text, confidence, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        secrets.token_hex(16),
                        meeting_id,
                        sequence,
                        segment.get("speaker_label"),
                        segment["start_ms"],
                        segment["end_ms"],
                        segment["text"],
                        segment.get("confidence"),
                        now,
                    ),
                )
            self._connection.execute(
                """UPDATE meetings SET status = 'transcribed', updated_at = ?
                   WHERE id = ?""",
                (now, meeting_id),
            )
        meeting = self.get_meeting(meeting_id)
        assert meeting is not None
        return meeting

    def replace_meeting_analysis(
        self,
        meeting_id: str,
        summary: str,
        decisions: list[dict[str, Any]],
        action_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        now = _now()
        with self._lock, self._connection:
            if not self._connection.execute(
                "SELECT 1 FROM meetings WHERE id = ?", (meeting_id,)
            ).fetchone():
                raise KeyError(meeting_id)
            self._connection.execute(
                "DELETE FROM meeting_decisions WHERE meeting_id = ?",
                (meeting_id,),
            )
            self._connection.execute(
                "DELETE FROM meeting_action_items WHERE meeting_id = ?",
                (meeting_id,),
            )
            for decision in decisions:
                self._connection.execute(
                    """INSERT INTO meeting_decisions
                       (id, meeting_id, summary, segment_ids_json, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        secrets.token_hex(16),
                        meeting_id,
                        decision["summary"],
                        json.dumps(decision.get("segment_ids") or []),
                        now,
                    ),
                )
            for action in action_items:
                self._connection.execute(
                    """INSERT INTO meeting_action_items
                       (id, meeting_id, task, owner, due_at, status, confidence,
                        segment_ids_json, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)""",
                    (
                        secrets.token_hex(16),
                        meeting_id,
                        action["task"],
                        action.get("owner"),
                        action.get("due_at"),
                        action.get("confidence"),
                        json.dumps(action.get("segment_ids") or []),
                        now,
                        now,
                    ),
                )
            self._connection.execute(
                """UPDATE meetings
                   SET summary = ?, status = 'ready', updated_at = ?
                   WHERE id = ?""",
                (summary, now, meeting_id),
            )
        meeting = self.get_meeting(meeting_id)
        assert meeting is not None
        return meeting

    def begin_home_catalog_sync(self) -> int:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """INSERT INTO home_catalog_syncs (started_at, status)
                   VALUES (?, 'running')""",
                (_now(),),
            )
        return int(cursor.lastrowid)

    def fail_home_catalog_sync(self, sync_id: int, error: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """UPDATE home_catalog_syncs
                   SET completed_at = ?, status = 'failed', error = ?
                   WHERE id = ? AND status = 'running'""",
                (_now(), error[:500], sync_id),
            )

    def replace_home_catalog(
        self,
        sync_id: int,
        records: list[dict[str, Any]],
        registry: dict[str, Any] | None = None,
        *,
        metadata_status: str = "not_attempted",
        metadata_error: str | None = None,
        preserve_entity_metadata: bool = False,
    ) -> dict[str, Any]:
        now = _now()
        entity_ids = {record["entity_id"] for record in records}
        if len(entity_ids) != len(records):
            raise ValueError("home catalogue contains duplicate entity IDs")
        with self._lock, self._connection:
            sync = self._connection.execute(
                """SELECT 1 FROM home_catalog_syncs
                   WHERE id = ? AND status = 'running'""",
                (sync_id,),
            ).fetchone()
            if sync is None:
                raise KeyError(sync_id)
            self._connection.execute("UPDATE home_entities SET missing = 1")
            for record in records:
                metadata_updates = (
                    """stable_id=home_entities.stable_id,
                       area_id=COALESCE(home_entities.area_id, excluded.area_id),
                       device_id=COALESCE(home_entities.device_id, excluded.device_id),
                       aliases_json=CASE
                         WHEN home_entities.aliases_json != '[]'
                         THEN home_entities.aliases_json
                         ELSE excluded.aliases_json
                       END,"""
                    if preserve_entity_metadata
                    else
                    """stable_id=excluded.stable_id,
                       area_id=excluded.area_id,
                       device_id=excluded.device_id,
                       aliases_json=excluded.aliases_json,"""
                )
                self._connection.execute(
                    f"""INSERT INTO home_entities
                       (entity_id, stable_id, domain, name, state,
                        attributes_json, area_id, device_id, aliases_json,
                        availability, observed_at, synced_at, first_seen_at,
                        last_seen_at, missing)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                       ON CONFLICT(entity_id) DO UPDATE SET
                         {metadata_updates}
                         domain=excluded.domain,
                         name=excluded.name,
                         state=excluded.state,
                         attributes_json=excluded.attributes_json,
                         availability=excluded.availability,
                         observed_at=excluded.observed_at,
                         synced_at=excluded.synced_at,
                         last_seen_at=excluded.last_seen_at,
                         missing=0""",
                    (
                        record["entity_id"],
                        record["stable_id"],
                        record["domain"],
                        record["name"],
                        record["state"],
                        json.dumps(
                            record["attributes"],
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ),
                        record.get("area_id"),
                        record.get("device_id"),
                        json.dumps(
                            record["aliases"],
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ),
                        record["availability"],
                        record.get("observed_at"),
                        record["synced_at"],
                        now,
                        now,
                    ),
                )
            if registry is not None:
                self._replace_home_registry_locked(registry, now)
            missing_count = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM home_entities WHERE missing = 1"
                ).fetchone()[0]
            )
            self._connection.execute(
                """UPDATE home_catalog_syncs
                   SET completed_at = ?, status = 'succeeded',
                       entity_count = ?, upserted_count = ?,
                       missing_count = ?, metadata_status = ?,
                       metadata_error = ?, error = NULL
                   WHERE id = ?""",
                (
                    now,
                    len(records),
                    len(records),
                    missing_count,
                    metadata_status,
                    metadata_error[:500] if metadata_error else None,
                    sync_id,
                ),
            )
        return self.home_catalog_sync_status()

    def _replace_home_registry_locked(
        self,
        registry: dict[str, Any],
        synced_at: str,
    ) -> None:
        sections = (
            (
                "floors",
                "home_floors",
                ("id", "name", "level"),
            ),
            (
                "areas",
                "home_areas",
                ("id", "name", "floor_id"),
            ),
            (
                "devices",
                "home_devices",
                ("id", "name", "area_id", "manufacturer", "model"),
            ),
        )
        for section, table, columns in sections:
            rows = registry.get(section)
            if rows is None:
                continue
            self._connection.execute(f"UPDATE {table} SET missing = 1")
            placeholders = ", ".join("?" for _ in range(len(columns) + 2))
            update_columns = ", ".join(
                f"{column}=excluded.{column}" for column in columns if column != "id"
            )
            update_columns += (
                ", synced_at=excluded.synced_at, missing=excluded.missing"
            )
            column_sql = ", ".join((*columns, "synced_at", "missing"))
            for row in rows:
                self._connection.execute(
                    f"""INSERT INTO {table} ({column_sql})
                        VALUES ({placeholders})
                        ON CONFLICT(id) DO UPDATE SET {update_columns}""",
                    (
                        *(row.get(column) for column in columns),
                        synced_at,
                        0,
                    ),
                )

    def home_catalog_sync_status(
        self,
        stale_after_seconds: int = 900,
    ) -> dict[str, Any]:
        with self._lock:
            latest = self._connection.execute(
                "SELECT * FROM home_catalog_syncs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            last_success = self._connection.execute(
                """SELECT * FROM home_catalog_syncs
                   WHERE status = 'succeeded' ORDER BY id DESC LIMIT 1"""
            ).fetchone()
            entity_count = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM home_entities WHERE missing = 0"
                ).fetchone()[0]
            )
            missing_count = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM home_entities WHERE missing = 1"
                ).fetchone()[0]
            )

        last_success_at = last_success["completed_at"] if last_success else None
        stale = True
        if last_success_at:
            try:
                completed = datetime.fromisoformat(last_success_at)
                if completed.tzinfo is None:
                    completed = completed.replace(tzinfo=UTC)
                stale = datetime.now(UTC) - completed.astimezone(UTC) > timedelta(
                    seconds=stale_after_seconds
                )
            except ValueError:
                stale = True
        return {
            "status": latest["status"] if latest else "never_synced",
            "started_at": latest["started_at"] if latest else None,
            "completed_at": latest["completed_at"] if latest else None,
            "last_success_at": last_success_at,
            "entity_count": entity_count,
            "missing_count": missing_count,
            "stale": stale,
            "metadata_status": (
                latest["metadata_status"]
                if latest and "metadata_status" in latest.keys()
                else "not_attempted"
            ),
            "metadata_error": (
                latest["metadata_error"]
                if latest and "metadata_error" in latest.keys()
                else None
            ),
            "error": latest["error"] if latest else None,
        }

    def search_home_entities(
        self,
        *,
        query: str | None = None,
        domain: str | None = None,
        area_id: str | None = None,
        availability: str | None = None,
        include_missing: bool = False,
        limit: int = 100,
        stale_after_seconds: int = 900,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        values: list[Any] = []
        normalized_query = " ".join((query or "").split())[:200]
        if normalized_query:
            escaped = (
                normalized_query.casefold()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            for token in escaped.split()[:8]:
                pattern = f"%{token}%"
                clauses.append(
                    """(lower(entity_id) LIKE ? ESCAPE '\\'
                        OR lower(name) LIKE ? ESCAPE '\\'
                        OR lower(aliases_json) LIKE ? ESCAPE '\\')"""
                )
                values.extend((pattern, pattern, pattern))
        if domain:
            clauses.append("domain = ?")
            values.append(domain)
        if area_id:
            clauses.append("area_id = ?")
            values.append(area_id)
        if availability:
            clauses.append("availability = ?")
            values.append(availability)
        if not include_missing:
            clauses.append("missing = 0")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        bounded_limit = min(max(int(limit), 1), 500)
        with self._lock:
            total = int(
                self._connection.execute(
                    f"SELECT COUNT(*) FROM home_entities{where}",
                    values,
                ).fetchone()[0]
            )
            rows = self._connection.execute(
                f"""SELECT * FROM home_entities{where}
                    ORDER BY missing, name COLLATE NOCASE, entity_id
                    LIMIT ?""",
                [*values, bounded_limit],
            ).fetchall()
        return {
            "entities": [
                self._home_entity_view(row, stale_after_seconds) for row in rows
            ],
            "count": len(rows),
            "total": total,
        }

    def get_home_entity(
        self,
        entity_id: str,
        stale_after_seconds: int = 900,
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM home_entities WHERE entity_id = ?",
                (entity_id,),
            ).fetchone()
        return (
            self._home_entity_view(row, stale_after_seconds)
            if row is not None
            else None
        )

    def home_catalog_coverage(
        self,
        stale_after_seconds: int = 900,
    ) -> dict[str, Any]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT domain, area_id, availability, missing,
                          COUNT(*) AS count, MIN(synced_at) AS oldest_sync
                   FROM home_entities
                   GROUP BY domain, area_id, availability, missing"""
            ).fetchall()
        by_domain: dict[str, int] = {}
        by_area: dict[str, int] = {}
        availability: dict[str, int] = {}
        total = 0
        missing = 0
        unassigned = 0
        stale = 0
        cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
        for row in rows:
            count = int(row["count"])
            total += count
            by_domain[row["domain"]] = by_domain.get(row["domain"], 0) + count
            area = row["area_id"] or "unassigned"
            by_area[area] = by_area.get(area, 0) + count
            availability[row["availability"]] = (
                availability.get(row["availability"], 0) + count
            )
            if row["missing"]:
                missing += count
            if not row["area_id"]:
                unassigned += count
            try:
                synced = datetime.fromisoformat(row["oldest_sync"])
                if synced.tzinfo is None:
                    synced = synced.replace(tzinfo=UTC)
                if synced.astimezone(UTC) < cutoff:
                    stale += count
            except (TypeError, ValueError):
                stale += count
        active_total = total - missing
        return {
            "total": total,
            "active": active_total,
            "missing": missing,
            "stale": stale,
            "unassigned_area": unassigned,
            "readable": active_total,
            "excluded": 0,
            "by_domain": dict(sorted(by_domain.items())),
            "by_area": dict(sorted(by_area.items())),
            "by_availability": dict(sorted(availability.items())),
            "sync": self.home_catalog_sync_status(stale_after_seconds),
        }

    def home_area_summaries(
        self,
        stale_after_seconds: int = 900,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT * FROM home_entities
                   WHERE missing = 0
                   ORDER BY area_id, name COLLATE NOCASE"""
            ).fetchall()
        entities = [
            self._home_entity_view(row, stale_after_seconds) for row in rows
        ]
        areas: dict[str, dict[str, Any]] = {}
        for entity in entities:
            area_id = entity["area_id"] or "unassigned"
            area = areas.setdefault(
                area_id,
                {
                    "id": area_id,
                    "name": (
                        "Unassigned"
                        if area_id == "unassigned"
                        else area_id.replace("_", " ").replace("-", " ").title()
                    ),
                    "entity_count": 0,
                    "available_count": 0,
                    "unavailable_count": 0,
                    "stale_count": 0,
                },
            )
            area["entity_count"] += 1
            if entity["unavailable"]:
                area["unavailable_count"] += 1
            else:
                area["available_count"] += 1
            if entity["stale"]:
                area["stale_count"] += 1
        with self._lock:
            metadata_rows = self._connection.execute(
                """SELECT home_areas.id, home_areas.name, home_areas.floor_id,
                          home_floors.name AS floor_name
                   FROM home_areas
                   LEFT JOIN home_floors
                     ON home_floors.id = home_areas.floor_id
                    AND home_floors.missing = 0
                   WHERE home_areas.missing = 0"""
            ).fetchall()
        for row in metadata_rows:
            area = areas.setdefault(
                row["id"],
                {
                    "id": row["id"],
                    "name": row["name"],
                    "entity_count": 0,
                    "available_count": 0,
                    "unavailable_count": 0,
                    "stale_count": 0,
                },
            )
            area["name"] = row["name"]
            area["floor_id"] = row["floor_id"]
            area["floor_name"] = row["floor_name"]
        return sorted(areas.values(), key=lambda item: item["name"].casefold())

    def home_floor_summaries(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT home_floors.*,
                          COUNT(DISTINCT home_areas.id) AS area_count,
                          COUNT(DISTINCT home_entities.entity_id) AS entity_count
                   FROM home_floors
                   LEFT JOIN home_areas
                     ON home_areas.floor_id = home_floors.id
                    AND home_areas.missing = 0
                   LEFT JOIN home_entities
                     ON home_entities.area_id = home_areas.id
                    AND home_entities.missing = 0
                   WHERE home_floors.missing = 0
                   GROUP BY home_floors.id
                   ORDER BY home_floors.level, home_floors.name COLLATE NOCASE"""
            ).fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "level": row["level"],
                "area_count": int(row["area_count"]),
                "entity_count": int(row["entity_count"]),
            }
            for row in rows
        ]

    def home_device_summaries(
        self,
        *,
        area_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        where = "WHERE home_devices.missing = 0"
        values: list[Any] = []
        if area_id:
            where += " AND home_devices.area_id = ?"
            values.append(area_id)
        values.append(min(max(limit, 1), 1000))
        with self._lock:
            rows = self._connection.execute(
                f"""SELECT home_devices.*,
                           home_areas.name AS area_name,
                           COUNT(home_entities.entity_id) AS entity_count
                    FROM home_devices
                    LEFT JOIN home_areas
                      ON home_areas.id = home_devices.area_id
                     AND home_areas.missing = 0
                    LEFT JOIN home_entities
                      ON home_entities.device_id = home_devices.id
                     AND home_entities.missing = 0
                    {where}
                    GROUP BY home_devices.id
                    ORDER BY home_devices.name COLLATE NOCASE
                    LIMIT ?""",
                values,
            ).fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "area_id": row["area_id"],
                "area_name": row["area_name"],
                "manufacturer": row["manufacturer"],
                "model": row["model"],
                "entity_count": int(row["entity_count"]),
            }
            for row in rows
        ]

    @staticmethod
    def _home_entity_view(
        row: sqlite3.Row,
        stale_after_seconds: int,
    ) -> dict[str, Any]:
        stale = bool(row["missing"])
        try:
            synced_at = datetime.fromisoformat(row["synced_at"])
            if synced_at.tzinfo is None:
                synced_at = synced_at.replace(tzinfo=UTC)
            stale = stale or (
                datetime.now(UTC) - synced_at.astimezone(UTC)
                > timedelta(seconds=stale_after_seconds)
            )
        except ValueError:
            stale = True
        return {
            "entity_id": row["entity_id"],
            "stable_id": row["stable_id"],
            "domain": row["domain"],
            "name": row["name"],
            "state": row["state"],
            "attributes": json.loads(row["attributes_json"]),
            "area_id": row["area_id"],
            "device_id": row["device_id"],
            "aliases": json.loads(row["aliases_json"]),
            "availability": row["availability"],
            "unavailable": row["availability"] == "unavailable",
            "stale": stale,
            "missing": bool(row["missing"]),
            "observed_at": row["observed_at"],
            "synced_at": row["synced_at"],
        }

    @staticmethod
    def _meeting_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "language": row["language"],
            "source_device_id": row["source_device_id"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "status": row["status"],
            "summary": row["summary"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @classmethod
    def _meeting_summary(cls, row: sqlite3.Row) -> dict[str, Any]:
        return {
            **cls._meeting_row(row),
            "has_recording": bool(row["has_recording"]),
            "transcript_segment_count": row["transcript_segment_count"],
            "action_item_count": row["action_item_count"],
        }

    @staticmethod
    def _recording_view(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "filename": row["filename"],
            "content_type": row["content_type"],
            "sha256": row["sha256"],
            "size_bytes": row["size_bytes"],
            "created_at": row["created_at"],
        }

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
