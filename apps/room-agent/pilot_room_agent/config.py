from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class Settings:
    room_id: str = "unconfigured"
    listen_host: str = "127.0.0.1"
    listen_port: int = 8765
    bluetooth_enabled: bool = False
    microphone_description: str = ""
    speaker_description: str = ""
    microphone_node: str = ""
    speaker_node: str = ""
    capture_alsa_device: str = "default"
    playback_alsa_device: str = "default"
    voice_satellite_enabled: bool = False
    voice_satellite_port: int = 6053
    airplay_enabled: bool = False
    airplay_port: int = 5000
    music_assistant_enabled: bool = False
    music_assistant_port: int = 8927
    music_assistant_protocol: str = "sendspin"
    core_reporting_enabled: bool = False
    core_url: str = ""
    core_device_id: str = ""
    core_device_token_file: str = "/etc/pilot/device-token"
    core_report_interval_seconds: int = 15
    core_commands_enabled: bool = False
    core_command_journal_path: str = "/var/lib/pilot/commands.db"
    core_command_heartbeat_seconds: int = 20
    core_command_reconnect_min_seconds: int = 2
    core_command_reconnect_max_seconds: int = 30
    audio_cache_path: str = "/var/lib/pilot/audio"
    audio_max_bytes: int = 20_000_000
    audio_download_timeout_seconds: int = 15
    audio_cache_retention_seconds: int = 86_400
    audio_activation_required: bool = True
    audio_activation_state_path: str = "/etc/pilot/audio-activation.json"
    audio_focus_enabled: bool = False
    audio_focus_duck_gain: float = 0.2
    audio_focus_interval_seconds: int = 1
    video_enabled: bool = False
    video_ipc_path: str = "/run/user/1000/pilot-mpv.sock"
    video_media_roots: tuple[str, ...] = ()
    video_wayland_display: str = ""
    # Retained as a compatibility alias for pre-0.7 room.toml files.
    video_display: str = ""
    video_audio_device: str = "auto"
    video_hwdec: str = "auto-safe"
    video_start_timeout_seconds: float = 5


def load_settings(path: str | Path) -> Settings:
    config_path = Path(path)
    if not config_path.exists():
        return Settings()
    with config_path.open("rb") as handle:
        values = tomllib.load(handle)
    allowed = {field for field in Settings.__dataclass_fields__}
    selected = {key: value for key, value in values.items() if key in allowed}
    media_roots = selected.get("video_media_roots", [])
    if not isinstance(media_roots, list) or not all(
        isinstance(item, str) and item.strip() for item in media_roots
    ):
        raise ValueError("video_media_roots must be an array of non-empty paths")
    selected["video_media_roots"] = tuple(item.strip() for item in media_roots)
    return Settings(**selected)
