from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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
    public_upload_base_url: str = ""
    public_client_base_url: str = ""
    firmware_asset_path: str = "/var/lib/pilot-core/firmware"
    firmware_asset_max_bytes: int = 8_000_000
    vehicle_asset_path: str = "/var/lib/pilot-core/vehicle-assets"
    vehicle_asset_max_bytes: int = 10_000_000
    # A 45 second, 16 kHz, signed 16-bit mono utterance is 1,440,000 bytes.
    # Retain a small envelope above that fixed client contract while keeping
    # voice uploads tightly bounded.
    voice_audio_max_bytes: int = 1_600_000
    conversation_session_ttl_seconds: int = 900
    conversation_max_turns: int = 20
    admin_token_env: str = "PILOT_CORE_ADMIN_TOKEN"
    bootstrap_token_env: str = "PILOT_CORE_BOOTSTRAP_TOKEN"
    legacy_bootstrap_enabled: bool = True


@dataclass(frozen=True)
class LLMBackend:
    id: str
    url: str
    model: str
    token_env: str = "PILOT_LLM_TOKEN"
    roles: tuple[str, ...] = ("assistant",)
    priority: int = 100
    reasoning_effort: str = ""
    max_output_tokens: int = 1024
    timeout_seconds: int = 60


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
    sun_entity_id: str = ""
    outdoor_temperature_entity_id: str = ""
    indoor_temperature_entity_id: str = ""
    temperature_history_hours: int = 24
    home_timezone: str = "Australia/Brisbane"
    energy_solar_power_entity_id: str = ""
    energy_grid_power_entity_id: str = ""
    energy_battery_power_entity_id: str = ""
    energy_battery_soc_entity_id: str = ""
    energy_home_load_entity_id: str = ""
    energy_server_power_entity_id: str = ""
    energy_vehicle_connected_entity_id: str = ""
    energy_vehicle_power_entity_id: str = ""
    energy_vehicle_soc_entity_id: str = ""
    energy_solar_today_entity_ids: tuple[str, ...] = ()
    energy_home_today_entity_id: str = ""
    energy_grid_export_today_entity_id: str = ""
    energy_history_hours: int = 24
    amber_import_price_entity_id: str = ""
    amber_feed_in_price_entity_id: str = ""
    amber_feed_in_forecast_entity_id: str = ""
    tesla_charging_mode_entity_id: str = ""
    teslamate_adapter_url: str = ""
    teslamate_adapter_token_env: str = "PILOT_TESLAMATE_ADAPTER_TOKEN"
    media_room_mode_on_script_id: str = ""
    media_room_mode_off_script_id: str = ""
    temperature_office_entity_id: str = ""
    temperature_tv_room_entity_id: str = ""
    temperature_bedroom_entity_id: str = ""
    temperature_media_room_entity_id: str = ""
    proxmox_url: str = ""
    proxmox_token_id: str = ""
    proxmox_token_secret_env: str = "PROXMOX_TOKEN_SECRET"
    proxmox_migration_token_id: str = ""
    proxmox_migration_token_secret_env: str = "PROXMOX_MIGRATION_TOKEN_SECRET"
    proxmox_verify_tls: bool = True
    truenas_url: str = ""
    truenas_token_env: str = "TRUENAS_API_KEY"
    truenas_verify_tls: bool = True
    homelab_cache_seconds: int = 15
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
    llm_max_output_tokens: int = 1024
    llm_max_tool_rounds: int = 4
    llm_context_turns: int = 12
    llm_backends: tuple[LLMBackend, ...] = ()
    meeting_stt_url: str = ""
    meeting_stt_token_env: str = "PILOT_MEETING_STT_TOKEN"
    meeting_stt_model: str = "whisper-1"
    meeting_stt_timeout_seconds: int = 600
    meeting_analysis_model: str = ""
    meeting_transcript_max_characters: int = 500_000


@dataclass(frozen=True)
class Room:
    id: str
    name: str
    response_player_id: str
    default_music_player_id: str
    default_device_id: str = ""
    agent_url: str = ""
    assist_satellite_entity_id: str = ""
    home_area_ids: tuple[str, ...] = ()
    music_enabled: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "response_player_id": self.response_player_id,
            "default_music_player_id": self.default_music_player_id,
            "default_device_id": self.default_device_id,
            "agent_url": self.agent_url,
            "assist_satellite_entity_id": self.assist_satellite_entity_id,
            "home_area_ids": list(self.home_area_ids or (self.id,)),
            "music_enabled": self.music_enabled,
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


VEHICLE_TELEMETRY_KEYS = frozenset(
    {
        "state",
        "online",
        "battery_percent",
        "rated_range_km",
        "ideal_range_km",
        "odometer_km",
        "latitude",
        "longitude",
        "location_name",
        "inside_temperature_c",
        "outside_temperature_c",
        "locked",
        "doors",
        "windows",
        "frunk",
        "trunk",
        "software_version",
        "software_update",
        "charging_state",
        "charge_port",
        "charge_limit_percent",
        "charge_rate_kw",
        "time_to_full_hours",
        "energy_added_kwh",
        "tyre_front_left_bar",
        "tyre_front_right_bar",
        "tyre_rear_left_bar",
        "tyre_rear_right_bar",
    }
)

VEHICLE_CONTROL_ACTIONS = frozenset(
    {
        "wake",
        "lock",
        "unlock",
        "open_frunk",
        "open_trunk",
        "close_trunk",
        "vent_windows",
        "close_windows",
        "climate_on",
        "climate_off",
        "set_temperature",
        "set_seat_heat",
        "set_seat_heat_front_left",
        "set_seat_heat_front_right",
        "set_seat_heat_rear_left",
        "set_seat_heat_rear_center",
        "set_seat_heat_rear_right",
        "set_seat_climate",
        "set_seat_climate_front_right",
        "set_steering_heat",
        "start_charging",
        "stop_charging",
        "set_charge_limit",
        "sentry_on",
        "sentry_off",
        "valet_on",
        "valet_off",
        "flash_lights",
        "honk_horn",
        "homelink",
        "remote_start",
        "install_software",
        "send_route",
    }
)


@dataclass(frozen=True)
class VehicleControl:
    action: str
    domain: str
    service: str
    entity_id: str = ""
    device_id: str = ""
    observable_entity_id: str = ""
    provider_vehicle_id_env: str = ""


@dataclass(frozen=True)
class Vehicle:
    id: str
    name: str
    teslamate_car_id: int
    enabled: bool = True
    default_climate_target_c: float = 22.0
    manual_battery_baseline_kwh: float | None = None
    telemetry: tuple[tuple[str, str], ...] = ()
    controls: tuple[VehicleControl, ...] = ()

    def telemetry_map(self) -> dict[str, str]:
        return dict(self.telemetry)

    def controls_map(self) -> dict[str, VehicleControl]:
        return {control.action: control for control in self.controls}


@dataclass(frozen=True)
class Settings:
    server: ServerSettings
    integrations: IntegrationSettings
    rooms: tuple[Room, ...]
    players: tuple[Player, ...]
    vehicles: tuple[Vehicle, ...] = ()


def _require_nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _parse_string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{field} must be an array of strings")
    return tuple(dict.fromkeys(item.strip() for item in value))


def _parse_llm_backend(value: object) -> LLMBackend:
    if not isinstance(value, dict):
        raise ValueError("integrations.llm_backends entries must be TOML tables")
    return LLMBackend(
        id=str(value.get("id", "")).strip(),
        url=str(value.get("url", "")).rstrip("/"),
        model=str(value.get("model", "")).strip(),
        token_env=str(value.get("token_env", "PILOT_LLM_TOKEN")).strip(),
        roles=_parse_string_tuple(value.get("roles", ["assistant"]), "roles"),
        priority=int(value.get("priority", 100)),
        reasoning_effort=str(value.get("reasoning_effort", "")).strip(),
        max_output_tokens=int(value.get("max_output_tokens", 1024)),
        timeout_seconds=int(value.get("timeout_seconds", 60)),
    )


def _parse_room(value: dict[str, object]) -> Room:
    room_id = _require_nonempty(value.get("id"), "room.id")
    area_values = value.get("home_area_ids", [room_id])
    if not isinstance(area_values, list) or not all(
        isinstance(item, str) and item.strip() for item in area_values
    ):
        raise ValueError(f"room[{room_id}].home_area_ids must be an array of strings")
    home_area_ids = tuple(dict.fromkeys(item.strip() for item in area_values))
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
        home_area_ids=home_area_ids,
        music_enabled=bool(value.get("music_enabled", True)),
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


def _parse_vehicle(value: dict[str, object]) -> Vehicle:
    vehicle_id = _require_nonempty(value.get("id"), "vehicle.id")
    raw_telemetry = value.get("telemetry", {})
    raw_controls = value.get("controls", {})
    if not isinstance(raw_telemetry, dict):
        raise ValueError(f"vehicle[{vehicle_id}].telemetry must be a table")
    if not isinstance(raw_controls, dict):
        raise ValueError(f"vehicle[{vehicle_id}].controls must be a table")
    unknown_telemetry = set(raw_telemetry) - VEHICLE_TELEMETRY_KEYS
    if unknown_telemetry:
        raise ValueError(
            f"vehicle[{vehicle_id}] has unsupported telemetry keys: "
            + ", ".join(sorted(unknown_telemetry))
        )
    telemetry: list[tuple[str, str]] = []
    for key, entity_id in raw_telemetry.items():
        telemetry.append(
            (key, _require_nonempty(entity_id, f"vehicle[{vehicle_id}].telemetry.{key}"))
        )
    controls: list[VehicleControl] = []
    for action, raw_control in raw_controls.items():
        if action not in VEHICLE_CONTROL_ACTIONS:
            raise ValueError(f"vehicle[{vehicle_id}] has unsupported control: {action}")
        if not isinstance(raw_control, dict):
            raise ValueError(f"vehicle[{vehicle_id}].controls.{action} must be a table")
        domain = _require_nonempty(
            raw_control.get("domain"), f"vehicle[{vehicle_id}].controls.{action}.domain"
        )
        service = _require_nonempty(
            raw_control.get("service"), f"vehicle[{vehicle_id}].controls.{action}.service"
        )
        controls.append(
            VehicleControl(
                action=action,
                domain=domain,
                service=service,
                entity_id=str(raw_control.get("entity_id", "")).strip(),
                device_id=str(raw_control.get("device_id", "")).strip(),
                observable_entity_id=str(
                    raw_control.get("observable_entity_id", "")
                ).strip(),
                provider_vehicle_id_env=str(
                    raw_control.get("provider_vehicle_id_env", "")
                ).strip(),
            )
        )
    baseline_value = value.get("manual_battery_baseline_kwh")
    baseline = float(baseline_value) if baseline_value is not None else None
    if baseline is not None and not 20 <= baseline <= 200:
        raise ValueError(
            f"vehicle[{vehicle_id}].manual_battery_baseline_kwh must be 20..200"
        )
    climate_target = float(value.get("default_climate_target_c", 22.0))
    if not 15 <= climate_target <= 30:
        raise ValueError(f"vehicle[{vehicle_id}].default_climate_target_c must be 15..30")
    car_id = int(value.get("teslamate_car_id", 0))
    if car_id < 1:
        raise ValueError(f"vehicle[{vehicle_id}].teslamate_car_id must be positive")
    return Vehicle(
        id=vehicle_id,
        name=_require_nonempty(value.get("name"), f"vehicle[{vehicle_id}].name"),
        teslamate_car_id=car_id,
        enabled=bool(value.get("enabled", True)),
        default_climate_target_c=climate_target,
        manual_battery_baseline_kwh=baseline,
        telemetry=tuple(telemetry),
        controls=tuple(controls),
    )


def _assert_unique(
    values: tuple[Room, ...] | tuple[Player, ...] | tuple[Vehicle, ...],
    kind: str,
) -> None:
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
        public_upload_base_url=str(
            server_values.get("public_upload_base_url", "")
        ).rstrip("/"),
        public_client_base_url=str(
            server_values.get("public_client_base_url", "")
        ).rstrip("/"),
        firmware_asset_path=str(
            server_values.get("firmware_asset_path", "/var/lib/pilot-core/firmware")
        ),
        firmware_asset_max_bytes=int(
            server_values.get("firmware_asset_max_bytes", 8_000_000)
        ),
        vehicle_asset_path=str(
            server_values.get(
                "vehicle_asset_path", "/var/lib/pilot-core/vehicle-assets"
            )
        ),
        vehicle_asset_max_bytes=int(
            server_values.get("vehicle_asset_max_bytes", 10_000_000)
        ),
        voice_audio_max_bytes=int(
            server_values.get("voice_audio_max_bytes", 1_600_000)
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
    if server.public_upload_base_url:
        upload_url = urlparse(server.public_upload_base_url)
        if (
            upload_url.scheme != "https"
            or not upload_url.hostname
            or upload_url.username
            or upload_url.password
            or upload_url.path not in ("", "/")
            or upload_url.params
            or upload_url.query
            or upload_url.fragment
        ):
            raise ValueError(
                "server.public_upload_base_url must be an HTTPS origin without "
                "credentials, a path, query, or fragment"
            )
    if server.public_client_base_url:
        client_url = urlparse(server.public_client_base_url)
        if (
            client_url.scheme != "https"
            or not client_url.hostname
            or client_url.username
            or client_url.password
            or client_url.path not in ("", "/")
            or client_url.params
            or client_url.query
            or client_url.fragment
        ):
            raise ValueError(
                "server.public_client_base_url must be an HTTPS origin without "
                "credentials, a path, query, or fragment"
            )
    if not 1 <= server.firmware_asset_max_bytes <= 16_000_000:
        raise ValueError(
            "server.firmware_asset_max_bytes must be between 1 and 16000000"
        )
    if not 1 <= server.vehicle_asset_max_bytes <= 25_000_000:
        raise ValueError(
            "server.vehicle_asset_max_bytes must be between 1 and 25000000"
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
    raw_llm_backends = integration_values.get("llm_backends", [])
    if not isinstance(raw_llm_backends, list):
        raise ValueError("integrations.llm_backends must be a TOML table array")
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
        sun_entity_id=str(integration_values.get("sun_entity_id", "")).strip(),
        outdoor_temperature_entity_id=str(
            integration_values.get("outdoor_temperature_entity_id", "")
        ).strip(),
        indoor_temperature_entity_id=str(
            integration_values.get("indoor_temperature_entity_id", "")
        ).strip(),
        temperature_history_hours=int(
            integration_values.get("temperature_history_hours", 24)
        ),
        home_timezone=str(
            integration_values.get("home_timezone", "Australia/Brisbane")
        ).strip(),
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
        energy_server_power_entity_id=str(
            integration_values.get("energy_server_power_entity_id", "")
        ).strip(),
        energy_vehicle_connected_entity_id=str(
            integration_values.get("energy_vehicle_connected_entity_id", "")
        ).strip(),
        energy_vehicle_power_entity_id=str(
            integration_values.get("energy_vehicle_power_entity_id", "")
        ).strip(),
        energy_vehicle_soc_entity_id=str(
            integration_values.get("energy_vehicle_soc_entity_id", "")
        ).strip(),
        energy_solar_today_entity_ids=_parse_string_tuple(
            integration_values.get("energy_solar_today_entity_ids", []),
            "integrations.energy_solar_today_entity_ids",
        ),
        energy_home_today_entity_id=str(
            integration_values.get("energy_home_today_entity_id", "")
        ).strip(),
        energy_grid_export_today_entity_id=str(
            integration_values.get("energy_grid_export_today_entity_id", "")
        ).strip(),
        energy_history_hours=int(integration_values.get("energy_history_hours", 24)),
        amber_import_price_entity_id=str(
            integration_values.get("amber_import_price_entity_id", "")
        ).strip(),
        amber_feed_in_price_entity_id=str(
            integration_values.get("amber_feed_in_price_entity_id", "")
        ).strip(),
        amber_feed_in_forecast_entity_id=str(
            integration_values.get("amber_feed_in_forecast_entity_id", "")
        ).strip(),
        tesla_charging_mode_entity_id=str(
            integration_values.get("tesla_charging_mode_entity_id", "")
        ).strip(),
        teslamate_adapter_url=str(
            integration_values.get("teslamate_adapter_url", "")
        ).rstrip("/"),
        teslamate_adapter_token_env=str(
            integration_values.get(
                "teslamate_adapter_token_env", "PILOT_TESLAMATE_ADAPTER_TOKEN"
            )
        ).strip(),
        media_room_mode_on_script_id=str(
            integration_values.get("media_room_mode_on_script_id", "")
        ).strip(),
        media_room_mode_off_script_id=str(
            integration_values.get("media_room_mode_off_script_id", "")
        ).strip(),
        temperature_office_entity_id=str(
            integration_values.get("temperature_office_entity_id", "")
        ).strip(),
        temperature_tv_room_entity_id=str(
            integration_values.get("temperature_tv_room_entity_id", "")
        ).strip(),
        temperature_bedroom_entity_id=str(
            integration_values.get("temperature_bedroom_entity_id", "")
        ).strip(),
        temperature_media_room_entity_id=str(
            integration_values.get("temperature_media_room_entity_id", "")
        ).strip(),
        proxmox_url=str(integration_values.get("proxmox_url", "")).rstrip("/"),
        proxmox_token_id=str(integration_values.get("proxmox_token_id", "")).strip(),
        proxmox_token_secret_env=str(
            integration_values.get(
                "proxmox_token_secret_env", "PROXMOX_TOKEN_SECRET"
            )
        ).strip(),
        proxmox_migration_token_id=str(
            integration_values.get("proxmox_migration_token_id", "")
        ).strip(),
        proxmox_migration_token_secret_env=str(
            integration_values.get(
                "proxmox_migration_token_secret_env", "PROXMOX_MIGRATION_TOKEN_SECRET"
            )
        ).strip(),
        proxmox_verify_tls=bool(
            integration_values.get("proxmox_verify_tls", True)
        ),
        truenas_url=str(integration_values.get("truenas_url", "")).rstrip("/"),
        truenas_token_env=str(
            integration_values.get("truenas_token_env", "TRUENAS_API_KEY")
        ).strip(),
        truenas_verify_tls=bool(
            integration_values.get("truenas_verify_tls", True)
        ),
        homelab_cache_seconds=int(
            integration_values.get("homelab_cache_seconds", 15)
        ),
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
        llm_max_output_tokens=int(
            integration_values.get("llm_max_output_tokens", 1024)
        ),
        llm_max_tool_rounds=int(integration_values.get("llm_max_tool_rounds", 4)),
        llm_context_turns=int(integration_values.get("llm_context_turns", 12)),
        llm_backends=tuple(_parse_llm_backend(item) for item in raw_llm_backends),
        meeting_stt_url=str(integration_values.get("meeting_stt_url", "")).rstrip("/"),
        meeting_stt_token_env=str(
            integration_values.get(
                "meeting_stt_token_env",
                "PILOT_MEETING_STT_TOKEN",
            )
        ),
        meeting_stt_model=str(
            integration_values.get("meeting_stt_model", "whisper-1")
        ).strip(),
        meeting_stt_timeout_seconds=int(
            integration_values.get("meeting_stt_timeout_seconds", 600)
        ),
        meeting_analysis_model=str(
            integration_values.get("meeting_analysis_model", "")
        ).strip(),
        meeting_transcript_max_characters=int(
            integration_values.get("meeting_transcript_max_characters", 500_000)
        ),
    )
    if not 30 <= integrations.home_catalog_sync_interval_seconds <= 86_400:
        raise ValueError(
            "integrations.home_catalog_sync_interval_seconds must be between "
            "30 and 86400"
        )
    if not 5 <= integrations.homelab_cache_seconds <= 300:
        raise ValueError(
            "integrations.homelab_cache_seconds must be between 5 and 300"
        )
    for field, value in (
        ("proxmox_url", integrations.proxmox_url),
        ("truenas_url", integrations.truenas_url),
    ):
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.hostname:
            raise ValueError(f"integrations.{field} must be a valid service URL")
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
    if integrations.llm_provider not in {"", "openai", "vllm"}:
        raise ValueError("integrations.llm_provider must be openai or vllm")
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
    if not 30 <= integrations.meeting_stt_timeout_seconds <= 3600:
        raise ValueError(
            "integrations.meeting_stt_timeout_seconds must be between 30 and 3600"
        )
    if not 64 <= integrations.llm_max_output_tokens <= 8192:
        raise ValueError(
            "integrations.llm_max_output_tokens must be between 64 and 8192"
        )
    backend_ids: set[str] = set()
    allowed_llm_roles = {
        "assistant",
        "reasoning",
        "meeting",
        "verification",
        "vision",
    }
    for backend in integrations.llm_backends:
        if not backend.id or backend.id in backend_ids:
            raise ValueError(
                "integrations.llm_backends IDs must be non-empty and unique"
            )
        backend_ids.add(backend.id)
        parsed_backend_url = urlparse(backend.url)
        if (
            parsed_backend_url.scheme not in {"http", "https"}
            or not parsed_backend_url.netloc
        ):
            raise ValueError(
                f"integrations.llm_backends {backend.id} URL is invalid"
            )
        if not backend.model:
            raise ValueError(
                f"integrations.llm_backends {backend.id} model is required"
            )
        if not backend.roles or not set(backend.roles) <= allowed_llm_roles:
            raise ValueError(
                f"integrations.llm_backends {backend.id} roles are invalid"
            )
        if not 0 <= backend.priority <= 10_000:
            raise ValueError(
                f"integrations.llm_backends {backend.id} priority is invalid"
            )
        if backend.reasoning_effort not in {"", "none", "low", "medium", "high"}:
            raise ValueError(
                f"integrations.llm_backends {backend.id} reasoning_effort is invalid"
            )
        if not 64 <= backend.max_output_tokens <= 8192:
            raise ValueError(
                f"integrations.llm_backends {backend.id} max_output_tokens is invalid"
            )
        if not 5 <= backend.timeout_seconds <= 600:
            raise ValueError(
                f"integrations.llm_backends {backend.id} timeout is invalid"
            )
    if not 10_000 <= integrations.meeting_transcript_max_characters <= 2_000_000:
        raise ValueError(
            "integrations.meeting_transcript_max_characters must be between "
            "10000 and 2000000"
        )
    if not 5 <= integrations.home_assistant_assist_timeout_seconds <= 300:
        raise ValueError(
            "integrations.home_assistant_assist_timeout_seconds must be "
            "between 5 and 300"
        )
    if integrations.weather_entity_id and not integrations.weather_entity_id.startswith(
        "weather."
    ):
        raise ValueError("integrations.weather_entity_id must be a weather entity")
    if integrations.sun_entity_id and not integrations.sun_entity_id.startswith("sun."):
        raise ValueError("integrations.sun_entity_id must be a sun entity")
    for setting_name, entity_id in (
        ("outdoor_temperature_entity_id", integrations.outdoor_temperature_entity_id),
        ("indoor_temperature_entity_id", integrations.indoor_temperature_entity_id),
        ("energy_solar_power_entity_id", integrations.energy_solar_power_entity_id),
        ("energy_grid_power_entity_id", integrations.energy_grid_power_entity_id),
        ("energy_battery_power_entity_id", integrations.energy_battery_power_entity_id),
        ("energy_battery_soc_entity_id", integrations.energy_battery_soc_entity_id),
        ("energy_home_load_entity_id", integrations.energy_home_load_entity_id),
        ("energy_server_power_entity_id", integrations.energy_server_power_entity_id),
        ("energy_vehicle_power_entity_id", integrations.energy_vehicle_power_entity_id),
        ("energy_vehicle_soc_entity_id", integrations.energy_vehicle_soc_entity_id),
        ("energy_home_today_entity_id", integrations.energy_home_today_entity_id),
        ("energy_grid_export_today_entity_id", integrations.energy_grid_export_today_entity_id),
        ("amber_import_price_entity_id", integrations.amber_import_price_entity_id),
        ("amber_feed_in_price_entity_id", integrations.amber_feed_in_price_entity_id),
        ("amber_feed_in_forecast_entity_id", integrations.amber_feed_in_forecast_entity_id),
        ("temperature_office_entity_id", integrations.temperature_office_entity_id),
        ("temperature_tv_room_entity_id", integrations.temperature_tv_room_entity_id),
        ("temperature_bedroom_entity_id", integrations.temperature_bedroom_entity_id),
        ("temperature_media_room_entity_id", integrations.temperature_media_room_entity_id),
        *(
            ("energy_solar_today_entity_ids", entity_id)
            for entity_id in integrations.energy_solar_today_entity_ids
        ),
    ):
        if entity_id and not entity_id.startswith("sensor."):
            raise ValueError(f"integrations.{setting_name} must be a sensor entity")
    if not 1 <= integrations.temperature_history_hours <= 168:
        raise ValueError(
            "integrations.temperature_history_hours must be between 1 and 168"
        )
    if not 1 <= integrations.energy_history_hours <= 168:
        raise ValueError("integrations.energy_history_hours must be between 1 and 168")
    try:
        ZoneInfo(integrations.home_timezone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError("integrations.home_timezone must be a valid IANA timezone") from error
    if (
        integrations.energy_vehicle_connected_entity_id
        and not integrations.energy_vehicle_connected_entity_id.startswith("binary_sensor.")
    ):
        raise ValueError(
            "integrations.energy_vehicle_connected_entity_id must be a binary_sensor entity"
        )
    if (
        integrations.tesla_charging_mode_entity_id
        and not integrations.tesla_charging_mode_entity_id.startswith("input_select.")
    ):
        raise ValueError(
            "integrations.tesla_charging_mode_entity_id must be an input_select entity"
        )
    for setting_name, entity_id in (
        ("media_room_mode_on_script_id", integrations.media_room_mode_on_script_id),
        ("media_room_mode_off_script_id", integrations.media_room_mode_off_script_id),
    ):
        if entity_id and not entity_id.startswith("script."):
            raise ValueError(f"integrations.{setting_name} must be a script entity")
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
    if integrations.llm_provider in {"openai", "vllm"} and not integrations.llm_backends:
        if not integrations.llm_url:
            raise ValueError("llm_url is required for the local LLM provider")
        if not integrations.llm_model:
            raise ValueError("llm_model is required for the local LLM provider")

    raw_rooms = values.get("rooms", [])
    raw_players = values.get("players", [])
    raw_vehicles = values.get("vehicles", [])
    if (
        not isinstance(raw_rooms, list)
        or not isinstance(raw_players, list)
        or not isinstance(raw_vehicles, list)
    ):
        raise ValueError("rooms, players, and vehicles must be TOML table arrays")

    rooms = tuple(_parse_room(value) for value in raw_rooms)
    players = tuple(_parse_player(value) for value in raw_players)
    vehicles = tuple(_parse_vehicle(value) for value in raw_vehicles)
    if not rooms:
        raise ValueError("at least one room must be configured")
    if not players:
        raise ValueError("at least one player must be configured")

    _assert_unique(rooms, "room")
    _assert_unique(players, "player")
    _assert_unique(vehicles, "vehicle")
    _validate_references(rooms, players)
    return Settings(
        server=server,
        integrations=integrations,
        rooms=rooms,
        players=players,
        vehicles=vehicles,
    )
