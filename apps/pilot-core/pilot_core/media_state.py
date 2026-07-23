from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .config import Player
from .integrations import (
    IntegrationRequestFailed,
    IntegrationUnavailable,
    Integrations,
)
from .registry import Registry


class MediaStateReader:
    """Build a read-only, provider-neutral view of configured media players."""

    def __init__(self, registry: Registry, integrations: Integrations) -> None:
        self.registry = registry
        self.integrations = integrations

    async def snapshot(self, room_id: str | None = None) -> dict[str, Any]:
        players = [
            player
            for player in self.registry.players.values()
            if player.enabled and (room_id is None or player.room_id == room_id)
        ]
        music_assistant_required = any(player.external_id for player in players)
        entities = sorted(
            {
                player.endpoint
                for player in players
                if player.endpoint.startswith("media_player.")
            }
        )

        music_task = (
            asyncio.create_task(self.integrations.music_assistant("players/all", {}))
            if music_assistant_required
            else None
        )
        entity_tasks = {
            entity_id: asyncio.create_task(
                self.integrations.home_assistant_state(entity_id)
            )
            for entity_id in entities
        }

        music_rows: list[dict[str, Any]] = []
        provider_status: dict[str, dict[str, Any]] = {
            "music_assistant": {
                "status": "not_required",
                "player_count": 0,
            },
            "home_assistant": {
                "status": "not_required",
                "entity_count": 0,
            },
        }
        if music_task is not None:
            try:
                raw_music = await music_task
                if not isinstance(raw_music, list):
                    raise IntegrationRequestFailed(
                        "Music Assistant player inventory is not a list"
                    )
                music_rows = [row for row in raw_music if isinstance(row, dict)]
                provider_status["music_assistant"] = {
                    "status": "ok",
                    "player_count": len(music_rows),
                }
            except IntegrationUnavailable:
                provider_status["music_assistant"] = {
                    "status": "not_configured",
                    "player_count": 0,
                }
            except IntegrationRequestFailed:
                provider_status["music_assistant"] = {
                    "status": "error",
                    "player_count": 0,
                }

        home_states: dict[str, dict[str, Any]] = {}
        if entity_tasks:
            results = await asyncio.gather(
                *entity_tasks.values(), return_exceptions=True
            )
            errors = 0
            for entity_id, result in zip(entity_tasks, results, strict=True):
                if isinstance(result, dict):
                    home_states[entity_id] = result
                else:
                    errors += 1
            provider_status["home_assistant"] = {
                "status": "ok" if errors == 0 else "partial",
                "entity_count": len(home_states),
                "error_count": errors,
            }

        by_external_id = {
            str(row.get("player_id")): row
            for row in music_rows
            if row.get("player_id") is not None
        }
        by_name = {
            str(row.get("name", "")).casefold(): row
            for row in music_rows
            if row.get("name")
        }
        states = {
            player.id: self._player_state(
                player,
                by_external_id.get(player.external_id)
                or by_name.get(player.name.casefold()),
                home_states.get(player.endpoint),
            )
            for player in sorted(players, key=lambda item: item.id)
        }
        return {
            "schema_version": "pilot.media.v1",
            "observed_at": datetime.now(UTC).isoformat(),
            "room_id": room_id,
            "providers": provider_status,
            "players": states,
        }

    async def now_playing(self) -> dict[str, Any]:
        """Return a small, read-only view of every active Music Assistant player."""

        observed_at = datetime.now(UTC).isoformat()
        try:
            raw = await self.integrations.music_assistant("players/all", {})
        except IntegrationUnavailable:
            return {
                "status": "not_configured",
                "observed_at": observed_at,
                "items": [],
            }
        except IntegrationRequestFailed:
            return {"status": "unavailable", "observed_at": observed_at, "items": []}
        if not isinstance(raw, list):
            return {"status": "unavailable", "observed_at": observed_at, "items": []}

        items: list[dict[str, Any]] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            state = str(row.get("state") or "unknown").lower()
            media = row.get("current_media")
            if state not in {"playing", "paused"} or not isinstance(media, dict):
                continue
            duration = media.get("duration")
            elapsed = row.get("elapsed_time")
            volume = row.get("volume_level")
            items.append(
                {
                    "player_id": str(row.get("player_id") or "")[:200],
                    "player_name": str(
                        row.get("display_name") or row.get("name") or "Unknown player"
                    )[:200],
                    "state": state,
                    "volume_percent": (
                        int(round(volume))
                        if isinstance(volume, (int, float))
                        else None
                    ),
                    "title": str(media.get("title") or "Unknown title")[:300],
                    "artist": str(media.get("artist") or "")[:300] or None,
                    "album": str(media.get("album") or "")[:300] or None,
                    "media_type": str(media.get("media_type") or "")[:50] or None,
                    "duration_seconds": (
                        round(float(duration), 1)
                        if isinstance(duration, (int, float))
                        else None
                    ),
                    "elapsed_seconds": (
                        round(float(elapsed), 1)
                        if isinstance(elapsed, (int, float))
                        else None
                    ),
                    "position_seconds": (
                        round(float(elapsed), 1)
                        if isinstance(elapsed, (int, float))
                        else None
                    ),
                    "artwork": self._artwork(media, "music_assistant"),
                }
            )
        return {
            "status": "ok",
            "observed_at": observed_at,
            "items": items[:8],
        }

    def _player_state(
        self,
        player: Player,
        music_row: dict[str, Any] | None,
        home_state: dict[str, Any] | None,
    ) -> dict[str, Any]:
        music = self._music_assistant_view(player, music_row)
        home = self._home_assistant_view(player, home_state)
        available = (
            music["available"]
            if music is not None
            else home is not None and home["state"] != "unavailable"
        )
        powered = (
            music["powered"]
            if music is not None
            else home is not None and home["state"] not in {"off", "unavailable"}
        )
        playback_state = (
            music.get("state")
            if music is not None
            else home.get("state")
            if home is not None
            else "unknown"
        )
        volume_percent: int | None = None
        muted: bool | None = None
        source: str | None = None
        media: dict[str, Any] | None = None
        position_seconds: float | None = None
        duration_seconds: float | None = None
        queue: dict[str, Any] = {
            "status": "not_loaded",
            "index": None,
            "items": [],
            "truncated": False,
        }
        if music is not None and isinstance(music.get("volume_percent"), int):
            volume_percent = music["volume_percent"]
        if music is not None:
            media = music.get("media")
            position_seconds = music.get("position_seconds")
            duration_seconds = music.get("duration_seconds")
            queue = music["queue"]
        if home is not None:
            if isinstance(home.get("volume_percent"), int):
                volume_percent = home["volume_percent"]
            muted = home.get("muted")
            source = home.get("source")
            media = media or home.get("media")
            position_seconds = (
                position_seconds
                if position_seconds is not None
                else home.get("position_seconds")
            )
            duration_seconds = (
                duration_seconds
                if duration_seconds is not None
                else home.get("duration_seconds")
            )

        actions = (
            [
                "play",
                "pause",
                "stop",
                "set_volume",
                "play_media",
                "transfer",
                "next",
                "previous",
                "seek",
                "mute",
            ]
            if player.control_enabled
            else []
        )
        if actions and music is not None and music.get("grouping_supported"):
            actions.extend(["group", "ungroup"])
        artwork = media.get("artwork") if isinstance(media, dict) else None

        return {
            "player": player.as_dict(),
            "status": "ok" if music is not None or home is not None else "unresolved",
            "effective": {
                "available": available,
                "powered": powered,
                "playback_state": playback_state,
                "volume_percent": volume_percent,
                "muted": muted,
                "source": source,
                "media": media,
                "position_seconds": position_seconds,
                "duration_seconds": duration_seconds,
                "artwork_url": (
                    artwork.get("proxy_url") or artwork.get("source_url")
                    if isinstance(artwork, dict)
                    else None
                ),
                "queue": queue,
            },
            "capabilities": {
                "actions": actions,
                "transport": bool(actions),
                "volume": "set_volume" in actions,
                "seek": "seek" in actions,
                "transfer": "transfer" in actions,
                "grouping": bool(
                    music is not None and music.get("grouping_supported")
                ),
            },
            "music_assistant": music,
            "home_assistant": home,
        }

    @staticmethod
    def _music_assistant_view(
        player: Player, row: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        device = row.get("device_info")
        if not isinstance(device, dict):
            device = {}
        volume = row.get("volume_level")
        current_media = row.get("current_media")
        media = (
            MediaStateReader._media_item(current_media, "music_assistant")
            if isinstance(current_media, dict)
            else None
        )
        duration = current_media.get("duration") if isinstance(current_media, dict) else None
        position = row.get("elapsed_time")
        raw_queue = row.get("queue_items")
        queue_items = (
            [
                MediaStateReader._media_item(item, "music_assistant")
                for item in raw_queue[:10]
                if isinstance(item, dict)
            ]
            if isinstance(raw_queue, list)
            else []
        )
        return {
            "player_id": row.get("player_id"),
            "configured_external_id": player.external_id or None,
            "matched_by": (
                "external_id"
                if str(row.get("player_id")) == player.external_id
                else "name"
            ),
            "provider": row.get("provider"),
            "available": bool(row.get("available")),
            "powered": bool(row.get("powered")),
            "state": row.get("state") or "unknown",
            "volume_percent": (
                int(round(volume)) if isinstance(volume, (int, float)) else None
            ),
            "active_source": row.get("active_source"),
            "group_members": list(row.get("group_childs") or []),
            "grouping_supported": bool(
                row.get("can_group_with") or row.get("group_childs")
            ),
            "media": media,
            "position_seconds": MediaStateReader._number(position),
            "duration_seconds": MediaStateReader._number(duration),
            "queue": {
                "status": "ok" if isinstance(raw_queue, list) else "not_loaded",
                "index": (
                    int(row["current_index"])
                    if isinstance(row.get("current_index"), int)
                    else None
                ),
                "items": queue_items,
                "truncated": isinstance(raw_queue, list) and len(raw_queue) > 10,
            },
            "device": {
                "manufacturer": device.get("manufacturer"),
                "model": device.get("model"),
                "software_version": device.get("software_version"),
                "ip_address": device.get("ip_address"),
            },
        }

    @staticmethod
    def _home_assistant_view(
        player: Player, state: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if state is None:
            return None
        attributes = state.get("attributes")
        if not isinstance(attributes, dict):
            attributes = {}
        raw_volume = attributes.get("volume_level")
        media: dict[str, Any] | None = {
            "content_id": attributes.get("media_content_id"),
            "content_type": attributes.get("media_content_type"),
            "title": attributes.get("media_title"),
            "artist": attributes.get("media_artist"),
            "album": attributes.get("media_album_name"),
        }
        if not any(value is not None for value in media.values()):
            media = None
        else:
            media["artwork"] = MediaStateReader._artwork(
                {
                    "image_url": attributes.get("entity_picture"),
                    "title": attributes.get("media_title"),
                },
                "home_assistant",
            )
        return {
            "entity_id": player.endpoint,
            "state": state.get("state") or "unknown",
            "last_changed": state.get("last_changed"),
            "friendly_name": attributes.get("friendly_name"),
            "volume_percent": (
                int(round(raw_volume * 100))
                if isinstance(raw_volume, (int, float))
                else None
            ),
            "muted": attributes.get("is_volume_muted"),
            "source": attributes.get("source"),
            "media": media,
            "position_seconds": MediaStateReader._number(
                attributes.get("media_position")
            ),
            "duration_seconds": MediaStateReader._number(
                attributes.get("media_duration")
            ),
            "supported_features": attributes.get("supported_features"),
        }

    @staticmethod
    def _number(value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        selected = float(value)
        return round(selected, 3) if selected >= 0 else None

    @staticmethod
    def _media_item(raw: dict[str, Any], source: str) -> dict[str, Any]:
        duration = MediaStateReader._number(raw.get("duration"))
        raw_id = raw.get("item_id") or raw.get("media_item_id")
        if raw_id is None and raw.get("uri") is not None:
            raw_id = "media_" + sha256(str(raw["uri"]).encode()).hexdigest()[:24]
        if raw_id is None:
            raw_id = raw.get("title") or "unknown"
        return {
            "id": str(raw_id)[:500],
            "media_type": str(raw.get("media_type") or "unknown")[:64],
            "title": str(raw.get("title") or "Unknown title")[:300],
            "artist": str(raw.get("artist") or "")[:300] or None,
            "album": str(raw.get("album") or "")[:300] or None,
            "duration_seconds": duration,
            "artwork": MediaStateReader._artwork(raw, source),
        }

    @staticmethod
    def _artwork(raw: dict[str, Any], source: str) -> dict[str, Any]:
        candidate = raw.get("image_url") or raw.get("image") or raw.get("artwork_url")
        safe_url: str | None = None
        if isinstance(candidate, str) and len(candidate) <= 2000:
            parsed = urlsplit(candidate)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                safe_url = urlunsplit(
                    (parsed.scheme, parsed.netloc, parsed.path, "", "")
                )
            elif candidate.startswith("/") and not candidate.startswith("//"):
                safe_url = candidate.split("?", 1)[0]
        cache_key = sha256(safe_url.encode()).hexdigest()[:24] if safe_url else None
        return {
            "available": safe_url is not None,
            "source": source,
            "source_url": safe_url,
            "proxy_url": None,
            "cache_key": cache_key,
            "cache_status": "not_cached" if safe_url else "unavailable",
        }
