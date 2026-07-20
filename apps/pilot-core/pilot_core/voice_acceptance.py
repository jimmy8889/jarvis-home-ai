from __future__ import annotations

from collections.abc import AsyncIterable
from dataclasses import dataclass
import io
import re
import wave

from .tts import LocalTTS, TTSRequestFailed
from .voice import HomeAssistantVoicePipeline


ACCEPTANCE_PHRASE = "Pilot local speech recognition validation"
MINIMUM_WORD_COVERAGE = 0.8


class VoiceAcceptanceFailed(RuntimeError):
    """The local speech engines did not pass the synthetic round-trip."""


@dataclass(frozen=True)
class VoiceAcceptanceResult:
    expected: str
    transcript: str
    word_coverage: float
    sample_rate: int
    channels: int
    sample_width: int
    audio_bytes: int
    tts_provider: str
    tts_engine: str
    tts_voice: str

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "expected": self.expected,
            "transcript": self.transcript,
            "word_coverage": round(self.word_coverage, 3),
            "audio": {
                "sample_rate": self.sample_rate,
                "channels": self.channels,
                "sample_width": self.sample_width,
                "bytes": self.audio_bytes,
            },
            "tts": {
                "provider": self.tts_provider,
                "engine": self.tts_engine,
                "voice": self.tts_voice,
            },
            "stt": {"provider": "home_assistant"},
        }


def pcm_from_wave(content: bytes) -> tuple[bytes, int, int, int]:
    """Extract bounded PCM, including Piper WAV files with streaming lengths."""
    try:
        with wave.open(io.BytesIO(content), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            compression = source.getcomptype()
            # The requested frame count is derived from the already-bounded response,
            # not the WAV header. Piper streaming WAVs intentionally use 0xffffffff
            # for RIFF/data sizes and therefore report a sentinel frame count.
            pcm = source.readframes(max(1, len(content) // max(sample_width, 1)))
    except (EOFError, wave.Error) as error:
        raise VoiceAcceptanceFailed(
            f"TTS returned an unreadable WAV: {error}"
        ) from error
    if compression != "NONE":
        raise VoiceAcceptanceFailed("TTS WAV must contain uncompressed PCM")
    if channels != 1 or sample_width != 2:
        raise VoiceAcceptanceFailed("TTS WAV must be 16-bit mono PCM")
    if sample_rate not in {8000, 16000, 24000, 32000, 48000}:
        raise VoiceAcceptanceFailed("TTS WAV has an unsupported sample rate")
    if not pcm or len(pcm) % (channels * sample_width):
        raise VoiceAcceptanceFailed("TTS WAV contains invalid PCM data")
    return pcm, sample_rate, channels, sample_width


def word_coverage(expected: str, observed: str) -> float:
    expected_words = set(re.findall(r"[a-z0-9]+", expected.casefold()))
    observed_words = set(re.findall(r"[a-z0-9]+", observed.casefold()))
    if not expected_words:
        return 0.0
    return len(expected_words & observed_words) / len(expected_words)


async def _pcm_chunks(pcm: bytes, chunk_bytes: int = 3200) -> AsyncIterable[bytes]:
    for offset in range(0, len(pcm), chunk_bytes):
        yield pcm[offset : offset + chunk_bytes]


async def validate_voice_round_trip(
    tts: LocalTTS,
    stt: HomeAssistantVoicePipeline,
    *,
    phrase: str = ACCEPTANCE_PHRASE,
) -> VoiceAcceptanceResult:
    try:
        synthesized = await tts.synthesize(phrase)
    except TTSRequestFailed as error:
        raise VoiceAcceptanceFailed(str(error)) from error
    if synthesized.filename.rsplit(".", 1)[-1].casefold() != "wav":
        raise VoiceAcceptanceFailed("voice acceptance requires WAV TTS output")
    pcm, sample_rate, channels, sample_width = pcm_from_wave(synthesized.content)
    transcript = await stt.transcribe(
        _pcm_chunks(pcm),
        sample_rate=sample_rate,
        language=synthesized.language,
    )
    coverage = word_coverage(phrase, transcript)
    if coverage < MINIMUM_WORD_COVERAGE:
        raise VoiceAcceptanceFailed(
            f"STT word coverage {coverage:.3f} is below {MINIMUM_WORD_COVERAGE:.3f}"
        )
    return VoiceAcceptanceResult(
        expected=phrase,
        transcript=transcript,
        word_coverage=coverage,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        audio_bytes=len(synthesized.content),
        tts_provider=synthesized.provider,
        tts_engine=synthesized.model,
        tts_voice=synthesized.voice,
    )
