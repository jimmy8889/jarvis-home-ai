from pathlib import Path


ROOT = Path("/opt/jarvis-home-ai")


def replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise SystemExit(f"missing expected configuration line: {old}")
    return text.replace(old, new, 1)


config = ROOT / "config/core.container.toml"
value = config.read_text(encoding="utf-8")
for old, new in (
    ('tts_provider = "home_assistant"', 'tts_provider = "openai"'),
    ('tts_url = ""', 'tts_url = "http://10.0.1.43:8030/v1/audio/speech"'),
    ('tts_engine_id = "tts.piper"', 'tts_engine_id = ""'),
    ('tts_model = "tts-1"', 'tts_model = "tts"'),
    ('tts_voice = "en_US-amy-low"', 'tts_voice = "serena"'),
    ("tts_timeout_seconds = 60", "tts_timeout_seconds = 30"),
):
    value = replace_once(value, old, new)
if "voice_stt_url =" not in value:
    value = value.replace(
        "tts_timeout_seconds = 30\n",
        "tts_timeout_seconds = 30\n"
        'voice_stt_url = "http://10.0.1.43:8031/v1"\n'
        'voice_stt_token_env = "PILOT_VOICE_STT_TOKEN"\n'
        'voice_stt_model = "small.en"\n'
        "voice_stt_timeout_seconds = 20\n",
        1,
    )
config.write_text(value, encoding="utf-8")

compose = ROOT / "infra/docker-compose.yml"
value = compose.read_text(encoding="utf-8")
if "PILOT_VOICE_STT_TOKEN_FILE" not in value:
    value = value.replace(
        "      PILOT_TTS_TOKEN_FILE: /run/secrets/tts_token\n",
        "      PILOT_TTS_TOKEN_FILE: /run/secrets/tts_token\n"
        "      PILOT_VOICE_STT_TOKEN_FILE: /run/secrets/voice_stt_token\n",
        1,
    )
    value = value.replace(
        "      - tts_token\n", "      - tts_token\n      - voice_stt_token\n", 1
    )
    value = value.replace(
        "  tts_token:\n    file: ./secrets/tts_token\n",
        "  tts_token:\n    file: ./secrets/tts_token\n"
        "  voice_stt_token:\n    file: ./secrets/voice_stt_token\n",
        1,
    )
compose.write_text(value, encoding="utf-8")
