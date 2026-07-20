from __future__ import annotations

import io
import struct
import unittest
import wave

from pilot_core.tts import SynthesizedAudio
from pilot_core.voice_acceptance import (
    VoiceAcceptanceFailed,
    pcm_from_wave,
    validate_voice_round_trip,
    word_coverage,
)


def wav_bytes(pcm: bytes = b"\x00\x00" * 1600) -> bytes:
    target = io.BytesIO()
    with wave.open(target, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(pcm)
    return target.getvalue()


class FakeTTS:
    async def synthesize(self, phrase: str):
        return SynthesizedAudio(
            content=wav_bytes(),
            content_type="audio/wav",
            filename="speech.wav",
            provider="home_assistant",
            voice="en_US-amy-low",
            model="tts.piper",
            language="en_US",
        )


class FakeSTT:
    def __init__(self, transcript: str) -> None:
        self.transcript = transcript
        self.received = b""

    async def transcribe(self, audio, *, sample_rate: int, language: str | None):
        self.sample_rate = sample_rate
        self.language = language
        async for chunk in audio:
            self.received += chunk
        return self.transcript


class VoiceAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    def test_extracts_normal_and_streaming_length_wav(self) -> None:
        normal = wav_bytes(b"\x01\x02" * 100)
        pcm, rate, channels, width = pcm_from_wave(normal)
        self.assertEqual(pcm, b"\x01\x02" * 100)
        self.assertEqual((rate, channels, width), (16000, 1, 2))

        streaming = bytearray(normal)
        struct.pack_into("<I", streaming, 4, 0xFFFFFFFF)
        data_offset = streaming.index(b"data")
        struct.pack_into("<I", streaming, data_offset + 4, 0xFFFFFFFF)
        pcm, _, _, _ = pcm_from_wave(bytes(streaming))
        self.assertEqual(pcm, b"\x01\x02" * 100)

    def test_word_coverage_ignores_case_and_punctuation(self) -> None:
        self.assertEqual(word_coverage("Pilot local speech", "pilot, LOCAL speech."), 1)

    async def test_round_trip_returns_engine_and_audio_evidence(self) -> None:
        stt = FakeSTT("Pilot local speech recognition validation.")
        result = await validate_voice_round_trip(FakeTTS(), stt)
        self.assertEqual(result.word_coverage, 1)
        self.assertEqual(result.tts_engine, "tts.piper")
        self.assertEqual(stt.sample_rate, 16000)
        self.assertEqual(stt.language, "en_US")
        self.assertTrue(stt.received)

    async def test_round_trip_rejects_bad_transcription(self) -> None:
        with self.assertRaisesRegex(VoiceAcceptanceFailed, "word coverage"):
            await validate_voice_round_trip(FakeTTS(), FakeSTT("unrelated words"))


if __name__ == "__main__":
    unittest.main()
