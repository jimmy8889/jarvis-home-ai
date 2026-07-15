from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from .config import Player, Room, Settings


@dataclass(frozen=True)
class Registry:
    rooms: dict[str, Room]
    players: dict[str, Player]
    revision: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "Registry":
        rooms = {room.id: room for room in settings.rooms}
        players = {player.id: player for player in settings.players}
        canonical = {
            "rooms": [rooms[key].as_dict() for key in sorted(rooms)],
            "players": [players[key].as_dict() for key in sorted(players)],
        }
        revision = sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:12]
        return cls(rooms=rooms, players=players, revision=revision)

    def list_rooms(self) -> list[dict[str, object]]:
        return [self.room_view(room_id) for room_id in sorted(self.rooms)]

    def list_players(self, room_id: str | None = None) -> list[dict[str, str | bool]]:
        values = self.players.values()
        if room_id is not None:
            values = (player for player in values if player.room_id == room_id)
        return [player.as_dict() for player in sorted(values, key=lambda item: item.id)]

    def room_view(self, room_id: str) -> dict[str, object]:
        room = self.rooms[room_id]
        payload: dict[str, object] = room.as_dict()
        payload["players"] = self.list_players(room_id)
        return payload
