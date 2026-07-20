from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class ServerSettings:
    listen_host: str = "127.0.0.1"
    listen_port: int = 8770
    database_path: str = "/var/lib/pilot-core/pilot.db"
    audio_asset_path: str = "/var/lib/pilot-core/audio"
    audio_asset_max_bytes: int = 20_000_000
    audio_asset_retention_seconds: int = 3600
    meeting_asset_path: str = "/var/lib/pilot-core/meetings"
    meeting_asset_max_bytes: int = 2_000_000_000
    firmware_asset_path: str = "/var/lib/pilot-core/firmware"
    firmware_asset_max_bytes: int = 8_000_000
    voice_audio_max_bytes: int = 1_000_000
    conversation_session_ttl_seconds: int = 900
    conversation_max_turns: int = 20
    admin_token_env: str = "PILOT_CORE_ADMIN_TOKEN"
    bootstrap_token_env: str = "PILOT_CORE_BOOTSTRAP_TOKEN"
    legacy_bootstrap_enabled: bool = True


@dataclass(frozen=True)
class IntegrationSettings:
    music_assistant_url: str = ""
    music_assistant_token_env: str = "MUSIC_ASSISTANT_TOKEN"
    home_assistant_url: str = ""
    home_assistant_token_env: str = "HOME_ASSISTANT_TOKEN"
    home_assistant_assist_pipeline_id: str = ""
    home_assistant_assist_language: str = "en"
    home_assistant_assist_timeout_seconds: int = 60
    weather_entity_id: str = ""
    outdoor_temperature_entity_id: str = ""
    indoor_temperature_entity_id: str = ""
    temperature_history_hours: int = 24
    energy_solar_power_entity_id: str = ""
    energy_grid_power_entity_id: str = ""
    energy_battery_power_entity_id: str = ""
    energy_battery_soc_entity_id: str = ""
    energy_home_load_entity_id: str = ""
    home_catalog_sync_interval_seconds: int = 300
    home_catalog_stale_after_seconds: int = 900
    home_catalog_max_entities: int = 20_000
    tts_provider: str = ""
    tts_url: str = ""
    tts_token_env: str = "PILOT_TTS_TOKEN"
    tts_engine_id: str = ""
    tts_model: str = "tts-1"
    tts_voice: str = "default"
    tts_format: str = "wav"
    tts_language: str = "en"
    tts_sample_rate: int = 16000
    tts_sample_channels: int = 1
    tts_sample_bytes: int = 2
    tts_timeout_seconds: int = 60
    llm_provider: str = ""
    llm_url: str = ""
    llm_token_env: str = "PILOT_LLM_TOKEN"
    llm_model: str = ""
    llm_reasoning_effort: str = ""
    llm_timeout_seconds: int = 60
    llm_max_tool_rounds: int = 4
    llm_context_turns: int = 12


@dataclass(frozen=True)
class Room:
    id: str
    name: str
    response_player_id: str
    default_music_player_id: str
    default_device_id: str = ""
    agent_url: str = ""
    assist_satellite_entity_id: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "response_player_id": self.response_player_id,
            "default_music_player_id": self.default_music_player_id,
            "default_device_id": self.default_device_id,
            "agent_url": self.agent_url,
            "assist_satellite_entity_id": self.assist_satellite_entity_id,
        }


@dataclass(frozen=True)
class Player:
    id: str
    room_id: str
    name: str
    protocol: str
    kind: str
    endpoint: str = ""
    control_endpoint: str = ""
    external_id: str = ""
    enabled: bool = True
    control_enabled: bool = True

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "id": self.id,
            "room_id": self.room_id,
            "name": self.name,
            "protocol": self.protocol,
            "kind": self.kind,
            "endpoint": self.endpoint,
            "control_endpoint": self.control_endpoint,
            "external_id": self.external_id,
            "enabled": self.enabled,
            "control_enabled": self.control_enabled,
        }


@dataclass(frozen=True)
class Settings:
    server: ServerSettings
    integrations: IntegrationSettings
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
        default_device_id=str(value.get("default_device_id", "")).strip(),
        agent_url=str(value.get("agent_url", "")).strip(),
        assist_satellite_entity_id=str(
            value.get("assist_satellite_entity_id", "")
        ).strip(),
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
        control_endpoint=str(value.get("control_endpoint", "")).strip(),
        external_id=str(value.get("external_id", "")).strip(),
        enabled=bool(value.get("enabled", True)),
        control_enabled=bool(value.get("control_enabled", True)),
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
                raise ValueError(
                    f"room {room.id} {field} references unknown player {player_id}"
                )
            if player.room_id != room.id:
                raise ValueError(
                    f"room {room.id} {field} references player {player_id} "
                    f"owned by room {player.room_id}"
                )
            if not player.enabled:
                raise ValueError(
                    f"room {room.id} {field} references disabled player {player_id}"
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
        database_path=str(
            server_values.get("database_path", "/var/lib/pilot-core/pilot.db")
        ),
        audio_asset_path=str(
            server_values.get("audio_asset_path", "/var/lib/pilot-core/audio")
        ),
        audio_asset_max_bytes=int(
            server_values.get("audio_asset_max_bytes", 20_000_000)
        ),
        audio_asset_retention_seconds=int(
            server_values.get("audio_asset_retention_seconds", 3600)
        ),
        meeting_asset_path=str(
            server_values.get("meeting_asset_path", "/var/lib/pilot-core/meetings")
        ),
        meeting_asset_max_bytes=int(
            server_values.get("meeting_asset_max_bytes", 2_000_000_000)
        ),
        firmware_asset_path=str(
            server_values.get("firmware_asset_path", "/var/lib/pilot-core/firmware")
        ),
        firmware_asset_max_bytes=int(
            server_values.get("firmware_asset_max_bytes", 8_000_000)
        ),
        voice_audio_max_bytes=int(
            server_values.get("voice_audio_max_bytes", 1_000_000)
        ),
        conversation_session_ttl_seconds=int(
            server_values.get("conversation_session_ttl_seconds", 900)
        ),
        conversation_max_turns=int(server_values.get("conversation_max_turns", 20)),
        admin_token_env=str(
            server_values.get("admin_token_env", "PILOT_CORE_ADMIN_TOKEN")
        ),
        bootstrap_token_env=str(
            server_values.get("bootstrap_token_env", "PILOT_CORE_BOOTSTRAP_TOKEN")
        ),
        legacy_bootstrap_enabled=bool(
            server_values.get("legacy_bootstrap_enabled", True)
        ),
    )
    if server.audio_asset_max_bytes < 1:
        raise ValueError("server.audio_asset_max_bytes must be positive")
    if server.meeting_asset_max_bytes < 1:
        raise ValueError("server.meeting_asset_max_bytes must be positive")
    if not 1 <= server.firmware_asset_max_bytes <= 16_000_000:
        raise ValueError(
            "server.firmware_asset_max_bytes must be between 1 and 16000000"
        )
    if not 32_000 <= server.voice_audio_max_bytes <= 10_000_000:
        raise ValueError(
            "server.voice_audio_max_bytes must be between 32000 and 10000000"
        )
    if not 60 <= server.conversation_session_ttl_seconds <= 86_400:
        raise ValueError(
            "server.conversation_session_ttl_seconds must be between 60 and 86400"
        )
    if not 2 <= server.conversation_max_turns <= 100:
        raise ValueError("server.conversation_max_turns must be between 2 and 100")
    if not 60 <= server.audio_asset_retention_seconds <= 86_400:
        raise ValueError(
            "server.audio_asset_retention_seconds must be between 60 and 86400"
        )

    integration_values = values.get("integrations", {})
    if not isinstance(integration_values, dict):
        raise ValueError("integrations must be a TOML table")
    integrations = IntegrationSettings(
        music_assistant_url=str(
            integration_values.get("music_assistant_url", "")
        ).rstrip("/"),
        music_assistant_token_env=str(
            integration_values.get("music_assistant_token_env", "MUSIC_ASSISTANT_TOKEN")
        ),
        home_assistant_url=str(integration_values.get("home_assistant_url", "")).rstrip(
            "/"
        ),
        home_assistant_token_env=str(
            integration_values.get("home_assistant_token_env", "HOME_ASSISTANT_TOKEN")
        ),
        home_assistant_assist_pipeline_id=str(
            integration_values.get("home_assistant_assist_pipeline_id", "")
        ).strip(),
        home_assistant_assist_language=str(
            integration_values.get("home_assistant_assist_language", "en")
        ).strip(),
        home_assistant_assist_timeout_seconds=int(
            integration_values.get("home_assistant_assist_timeout_seconds", 60)
        ),
        weather_entity_id=str(integration_values.get("weather_entity_id", "")).strip(),
        outdoor_temperature_entity_id=str(
            integration_values.get("outdoor_temperature_entity_id", "")
        ).strip(),
        indoor_temperature_entity_id=str(
            integration_values.get("indoor_temperature_entity_id", "")
        ).strip(),
        temperature_history_hours=int(
            integration_values.get("temperature_history_hours", 24)
        ),
        energy_solar_power_entity_id=str(
            integration_values.get("energy_solar_power_entity_id", "")
        ).strip(),
        energy_grid_power_entity_id=str(
            integration_values.get("energy_grid_power_entity_id", "")
        ).strip(),
        energy_battery_power_entity_id=str(
            integration_values.get("energy_battery_power_entity_id", "")
        ).strip(),
        energy_battery_soc_entity_id=str(
            integration_values.get("energy_battery_soc_entity_id", "")
        ).strip(),
        energy_home_load_entity_id=str(
            integration_values.get("energy_home_load_entity_id", "")
        ).strip(),
        home_catalog_sync_interval_seconds=int(
            integration_values.get("home_catalog_sync_interval_seconds", 300)
        ),
        home_catalog_stale_after_seconds=int(
            integration_values.get("home_catalog_stale_after_seconds", 900)
        ),
        home_catalog_max_entities=int(
            integration_values.get("home_catalog_max_entities", 20_000)
        ),
        tts_provider=str(integration_values.get("tts_provider", "")).strip(),
        tts_url=str(integration_values.get("tts_url", "")).rstrip("/"),
        tts_token_env=str(integration_values.get("tts_token_env", "PILOT_TTS_TOKEN")),
        tts_engine_id=str(integration_values.get("tts_engine_id", "")).strip(),
        tts_model=str(integration_values.get("tts_model", "tts-1")).strip(),
        tts_voice=str(integration_values.get("tts_voice", "default")).strip(),
        tts_format=str(integration_values.get("tts_format", "wav")).strip(),
        tts_language=str(integration_values.get("tts_language", "en")).strip(),
        tts_sample_rate=int(integration_values.get("tts_sample_rate", 16000)),
        tts_sample_channels=int(integration_values.get("tts_sample_channels", 1)),
        tts_sample_bytes=int(integration_values.get("tts_sample_bytes", 2)),
        tts_timeout_seconds=int(integration_values.get("tts_timeout_seconds", 60)),
        llm_provider=str(integration_values.get("llm_provider", "")).strip(),
        llm_url=str(integration_values.get("llm_url", "")).rstrip("/"),
        llm_token_env=str(integration_values.get("llm_token_env", "PILOT_LLM_TOKEN")),
        llm_model=str(integration_values.get("llm_model", "")).strip(),
        llm_reasoning_effort=str(
            integration_values.get("llm_reasoning_effort", "")
        ).strip(),
        llm_timeout_seconds=int(integration_values.get("llm_timeout_seconds", 60)),
        llm_max_tool_rounds=int(integration_values.get("llm_max_tool_rounds", 4)),
        llm_context_turns=int(integration_values.get("llm_context_turns", 12)),
    )
    if not 30 <= integrations.home_catalog_sync_interval_seconds <= 86_400:
        raise ValueError(
            "integrations.home_catalog_sync_interval_seconds must be between "
            "30 and 86400"
        )
    if not 60 <= integrations.home_catalog_stale_after_seconds <= 604_800:
        raise ValueError(
            "integrations.home_catalog_stale_after_seconds must be between "
            "60 and 604800"
        )
    if not 100 <= integrations.home_catalog_max_entities <= 100_000:
        raise ValueError(
            "integrations.home_catalog_max_entities must be between 100 and 100000"
        )
    if integrations.tts_provider not in {"", "home_assistant", "openai"}:
        raise ValueError("integrations.tts_provider must be home_assistant or openai")
    if integrations.tts_format not in {"wav", "flac", "mp3", "ogg", "aac"}:
        raise ValueError("integrations.tts_format is unsupported")
    if integrations.tts_sample_rate not in {8000, 16000, 22050, 24000, 44100, 48000}:
        raise ValueError("integrations.tts_sample_rate is unsupported")
    if integrations.tts_sample_channels not in {1, 2}:
        raise ValueError("integrations.tts_sample_channels must be 1 or 2")
    if integrations.tts_sample_bytes != 2:
        raise ValueError("integrations.tts_sample_bytes must be 2")
    if not 1 <= integrations.tts_timeout_seconds <= 300:
        raise ValueError("integrations.tts_timeout_seconds must be between 1 and 300")
    if integrations.llm_provider not in {"", "openai"}:
        raise ValueError("integrations.llm_provider must be openai")
    if integrations.llm_reasoning_effort not in {"", "none", "low", "medium", "high"}:
        raise ValueError(
            "integrations.llm_reasoning_effort must be none, low, medium, or high"
        )
    if not 1 <= integrations.llm_timeout_seconds <= 300:
        raise ValueError("integrations.llm_timeout_seconds must be between 1 and 300")
    if not 1 <= integrations.llm_max_tool_rounds <= 8:
        raise ValueError("integrations.llm_max_tool_rounds must be between 1 and 8")
    if not 2 <= integrations.llm_context_turns <= 40:
        raise ValueError("integrations.llm_context_turns must be between 2 and 40")
    if not 5 <= integrations.home_assistant_assist_timeout_seconds <= 300:
        raise ValueError(
            "integrations.home_assistant_assist_timeout_seconds must be "
            "between 5 and 300"
        )
    if integrations.weather_entity_id and not integrations.weather_entity_id.startswith(
        "weather."
    ):
        raise ValueError("integrations.weather_entity_id must be a weather entity")
    for setting_name, entity_id in (
        ("outdoor_temperature_entity_id", integrations.outdoor_temperature_entity_id),
        ("indoor_temperature_entity_id", integrations.indoor_temperature_entity_id),
        ("energy_solar_power_entity_id", integrations.energy_solar_power_entity_id),
        ("energy_grid_power_entity_id", integrations.energy_grid_power_entity_id),
        ("energy_battery_power_entity_id", integrations.energy_battery_power_entity_id),
        ("energy_battery_soc_entity_id", integrations.energy_battery_soc_entity_id),
        ("energy_home_load_entity_id", integrations.energy_home_load_entity_id),
    ):
        if entity_id and not entity_id.startswith("sensor."):
            raise ValueError(f"integrations.{setting_name} must be a sensor entity")
    if not 1 <= integrations.temperature_history_hours <= 168:
        raise ValueError(
            "integrations.temperature_history_hours must be between 1 and 168"
        )
    if integrations.tts_provider == "home_assistant":
        if not integrations.home_assistant_url:
            raise ValueError(
                "home_assistant_url is required for the Home Assistant TTS provider"
            )
        if not integrations.tts_engine_id:
            raise ValueError(
                "tts_engine_id is required for the Home Assistant TTS provider"
            )
    if integrations.tts_provider == "openai" and not integrations.tts_url:
        raise ValueError("tts_url is required for the OpenAI TTS provider")
    if integrations.llm_provider == "openai":
        if not integrations.llm_url:
            raise ValueError("llm_url is required for the OpenAI LLM provider")
        if not integrations.llm_model:
            raise ValueError("llm_model is required for the OpenAI LLM provider")

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
    return Settings(
        server=server,
        integrations=integrations,
        rooms=rooms,
        players=players,
    )
