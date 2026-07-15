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
    audio_focus_enabled: bool = False
    audio_focus_duck_gain: float = 0.2
    audio_focus_interval_seconds: int = 1


def load_settings(path: str | Path) -> Settings:
    config_path = Path(path)
    if not config_path.exists():
        return Settings()
    with config_path.open("rb") as handle:
        values = tomllib.load(handle)
    allowed = {field for field in Settings.__dataclass_fields__}
    return Settings(**{key: value for key, value in values.items() if key in allowed})
