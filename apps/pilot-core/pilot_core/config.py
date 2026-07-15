from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class ServerSettings:
    listen_host: str = "127.0.0.1"
    listen_port: int = 8770


@dataclass(frozen=True)
class Room:
    id: str
    name: str
    response_player_id: str
    default_music_player_id: str
    agent_url: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "response_player_id": self.response_player_id,
            "default_music_player_id": self.default_music_player_id,
            "agent_url": self.agent_url,
        }


@dataclass(frozen=True)
class Player:
    id: str
    room_id: str
    name: str
    protocol: str
    kind: str
    endpoint: str = ""
    enabled: bool = True

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "id": self.id,
            "room_id": self.room_id,
            "name": self.name,
            "protocol": self.protocol,
            "kind": self.kind,
            "endpoint": self.endpoint,
            "enabled": self.enabled,
        }


@dataclass(frozen=True)
class Settings:
    server: ServerSettings
    rooms: tuple[Room, ...]
    players: tuple[Player, ...]


def _require_nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _parse_room(value: dict[str, object]) -> Room:
    room_id = _require_nonempty(value.get("id"), "room.id")
    return Room(
        id=room_id,
        name=_require_nonempty(value.get("name"), f"room[{room_id}].name"),
        response_player_id=_require_nonempty(
            value.get("response_player_id"),
            f"room[{room_id}].response_player_id",
        ),
        default_music_player_id=_require_nonempty(
            value.get("default_music_player_id"),
            f"room[{room_id}].default_music_player_id",
        ),
        agent_url=str(value.get("agent_url", "")).strip(),
    )


def _parse_player(value: dict[str, object]) -> Player:
    player_id = _require_nonempty(value.get("id"), "player.id")
    return Player(
        id=player_id,
        room_id=_require_nonempty(value.get("room_id"), f"player[{player_id}].room_id"),
        name=_require_nonempty(value.get("name"), f"player[{player_id}].name"),
        protocol=_require_nonempty(
            value.get("protocol"), f"player[{player_id}].protocol"
        ),
        kind=_require_nonempty(value.get("kind"), f"player[{player_id}].kind"),
        endpoint=str(value.get("endpoint", "")).strip(),
        enabled=bool(value.get("enabled", True)),
    )


def _assert_unique(values: tuple[Room, ...] | tuple[Player, ...], kind: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value.id in seen:
            raise ValueError(f"duplicate {kind} id: {value.id}")
        seen.add(value.id)


def _validate_references(rooms: tuple[Room, ...], players: tuple[Player, ...]) -> None:
    room_ids = {room.id for room in rooms}
    players_by_id = {player.id: player for player in players}

    for player in players:
        if player.room_id not in room_ids:
            raise ValueError(
                f"player {player.id} references unknown room {player.room_id}"
            )

    for room in rooms:
        for field, player_id in (
            ("response_player_id", room.response_player_id),
            ("default_music_player_id", room.default_music_player_id),
        ):
            player = players_by_id.get(player_id)
            if player is None:
                raise ValueError(f"room {room.id} {field} references unknown player {player_id}")
            if player.room_id != room.id:
                raise ValueError(
                    f"room {room.id} {field} references player {player_id} "
                    f"owned by room {player.room_id}"
                )


def load_settings(path: str | Path) -> Settings:
    config_path = Path(path)
    with config_path.open("rb") as handle:
        values = tomllib.load(handle)

    server_values = values.get("server", {})
    if not isinstance(server_values, dict):
        raise ValueError("server must be a TOML table")
    server = ServerSettings(
        listen_host=str(server_values.get("listen_host", "127.0.0.1")),
        listen_port=int(server_values.get("listen_port", 8770)),
    )

    raw_rooms = values.get("rooms", [])
    raw_players = values.get("players", [])
    if not isinstance(raw_rooms, list) or not isinstance(raw_players, list):
        raise ValueError("rooms and players must be TOML table arrays")

    rooms = tuple(_parse_room(value) for value in raw_rooms)
    players = tuple(_parse_player(value) for value in raw_players)
    if not rooms:
        raise ValueError("at least one room must be configured")
    if not players:
        raise ValueError("at least one player must be configured")

    _assert_unique(rooms, "room")
    _assert_unique(players, "player")
    _validate_references(rooms, players)
    return Settings(server=server, rooms=rooms, players=players)
