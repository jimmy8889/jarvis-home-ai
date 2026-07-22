from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Player
from .registry import Registry
from .storage import Store


class ResolutionError(LookupError):
    pass


@dataclass(frozen=True)
class DeviceTarget:
    id: str
    room_id: str
    connected: bool
    capabilities: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "room_id": self.room_id,
            "connected": self.connected,
            "capabilities": list(self.capabilities),
        }


class RoomOrchestrator:
    def __init__(self, registry: Registry, store: Store) -> None:
        self.registry = registry
        self.store = store

    def require_room(self, room_id: str) -> None:
        if room_id not in self.registry.rooms:
            raise ResolutionError(f"unknown room: {room_id}")

    def music_player(self, room_id: str, player_id: str | None = None) -> Player:
        self.require_room(room_id)
        room = self.registry.rooms[room_id]
        if not room.music_enabled:
            raise ResolutionError(f"music is disabled in room {room_id}")
        selected_id = player_id or room.default_music_player_id
        player = self.registry.players.get(selected_id)
        if player is None:
            raise ResolutionError(f"unknown player: {selected_id}")
        if player.room_id != room_id:
            raise ResolutionError(
                f"player {selected_id} does not belong to room {room_id}"
            )
        if not player.enabled:
            raise ResolutionError(f"player {selected_id} is disabled")
        if player.kind != "music":
            raise ResolutionError(f"player {selected_id} is not a music output")
        return player

    def response_player(self, room_id: str) -> Player:
        self.require_room(room_id)
        player_id = self.registry.rooms[room_id].response_player_id
        player = self.registry.players.get(player_id)
        if player is None or not player.enabled:
            raise ResolutionError(f"response player {player_id} is unavailable")
        if player.kind != "response":
            raise ResolutionError(f"player {player_id} is not a response output")
        return player

    def device(
        self,
        room_id: str,
        connected_ids: set[str],
        capability: str = "audio",
        device_id: str | None = None,
    ) -> DeviceTarget:
        self.require_room(room_id)
        candidates = self.store.list_devices(room_id)
        if device_id is not None:
            candidates = [item for item in candidates if item["id"] == device_id]
            if not candidates:
                raise ResolutionError(
                    f"device {device_id} is not registered in room {room_id}"
                )
        capable = [item for item in candidates if capability in item["capabilities"]]
        if not capable:
            raise ResolutionError(
                f"room {room_id} has no device with capability {capability}"
            )
        default_device_id = self.registry.rooms[room_id].default_device_id
        selected = min(
            capable,
            key=lambda item: (
                item["id"] not in connected_ids,
                item["id"] != default_device_id,
                item["id"],
            ),
        )
        return DeviceTarget(
            id=selected["id"],
            room_id=selected["room_id"],
            connected=selected["id"] in connected_ids,
            capabilities=tuple(selected["capabilities"]),
        )

    def room_state(self, room_id: str, connected_ids: set[str]) -> dict[str, Any]:
        self.require_room(room_id)
        room = self.registry.room_view(room_id)
        devices = self.store.list_devices(room_id)
        for device in devices:
            device["connected"] = device["id"] in connected_ids
            device["health"] = self.store.latest_device_health(device["id"])
        try:
            endpoint_device = self.device(room_id, connected_ids).as_dict()
        except ResolutionError:
            endpoint_device = None
        try:
            default_music_player = self.music_player(room_id).as_dict()
        except ResolutionError:
            default_music_player = None
        return {
            "room": room,
            "sources": self.store.room_source_state(room_id),
            "focus": self.store.room_focus(room_id),
            "devices": devices,
            "targets": {
                "response_player": self.response_player(room_id).as_dict(),
                "default_music_player": default_music_player,
                "endpoint_device": endpoint_device,
            },
        }
