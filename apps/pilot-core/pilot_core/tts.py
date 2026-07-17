from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from .config import IntegrationSettings
from .secret_values import read_secret


FORMAT_CONTENT_TYPES = {
    "wav": "audio/wav",
    "flac": "audio/flac",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "aac": "audio/aac",
}
CONTENT_TYPE_FORMATS = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/ogg": "ogg",
    "application/ogg": "ogg",
    "audio/aac": "aac",
}


class TTSUnavailable(RuntimeError):
    """Local speech synthesis has not been configured."""


class TTSRequestFailed(RuntimeError):
    """The configured local speech provider rejected or returned invalid audio."""


@dataclass(frozen=True)
class SynthesizedAudio:
    content: bytes
    content_type: str
    filename: str
    provider: str
    voice: str
    model: str
    language: str

    def metadata(self) -> dict[str, str | int]:
        return {
            "provider": self.provider,
            "voice": self.voice,
            "model": self.model,
            "language": self.language,
            "content_type": self.content_type,
            "size_bytes": len(self.content),
        }


class LocalTTS:
    """Bounded adapter for Home Assistant or OpenAI-compatible local TTS."""

    def __init__(
        self,
        settings: IntegrationSettings,
        max_bytes: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.max_bytes = max_bytes
        self.transport = transport

    def status(self) -> dict[str, Any]:
        provider = self.settings.tts_provider
        return {
            "configured": bool(provider),
            "provider": provider or None,
            "engine_id": (
                self.settings.tts_engine_id if provider == "home_assistant" else None
            ),
            "model": self.settings.tts_model if provider == "openai" else None,
            "voice": self.settings.tts_voice or None,
            "format": self.settings.tts_format,
            "language": self.settings.tts_language,
        }

    async def synthesize(
        self,
        text: str,
        language: str | None = None,
        voice: str | None = None,
    ) -> SynthesizedAudio:
        provider = self.settings.tts_provider
        if not provider:
            raise TTSUnavailable("local TTS provider is not configured")
        selected_language = language or self.settings.tts_language
        selected_voice = voice or self.settings.tts_voice
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.tts_timeout_seconds,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                if provider == "home_assistant":
                    return await self._home_assistant(
                        client, text, selected_language, selected_voice
                    )
                if provider == "openai":
                    return await self._openai(
                        client, text, selected_language, selected_voice
                    )
        except TTSRequestFailed:
            raise
        except (httpx.HTTPError, ValueError) as error:
            raise TTSRequestFailed(f"local TTS request failed: {error}") from error
        raise TTSUnavailable(f"unsupported local TTS provider: {provider}")

    async def _home_assistant(
        self,
        client: httpx.AsyncClient,
        text: str,
        language: str,
        voice: str,
    ) -> SynthesizedAudio:
        base_url = self.settings.home_assistant_url.rstrip("/")
        token = read_secret(self.settings.home_assistant_token_env)
        if not base_url or not token or not self.settings.tts_engine_id:
            raise TTSUnavailable(
                "Home Assistant URL, token, and TTS engine are required"
            )
        options: dict[str, Any] = {
            "preferred_format": self.settings.tts_format,
        }
        if voice and voice != "default":
            options["voice"] = voice
        payload = {
            "engine_id": self.settings.tts_engine_id,
            "message": text,
            "cache": False,
            "language": language,
            "options": options,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        response = await client.post(
            f"{base_url}/api/tts_get_url", headers=headers, json=payload
        )
        response.raise_for_status()
        try:
            result = response.json()
            path = result["path"]
        except (KeyError, TypeError, ValueError) as error:
            raise TTSRequestFailed(
                "Home Assistant returned an invalid TTS manifest"
            ) from error
        if not isinstance(path, str):
            raise TTSRequestFailed("Home Assistant returned an invalid TTS path")
        parsed = urlsplit(path)
        decoded_path = unquote(parsed.path).replace("\\", "/")
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.fragment
            or not parsed.path.startswith("/api/tts_proxy/")
            or "\\" in path
            or any(part in {".", ".."} for part in decoded_path.split("/"))
            or not decoded_path.startswith("/api/tts_proxy/")
        ):
            raise TTSRequestFailed("Home Assistant returned an unsafe TTS path")
        download_url = urljoin(base_url + "/", path.lstrip("/"))
        content, content_type, audio_format = await self._download(
            client,
            download_url,
            headers={"Authorization": f"Bearer {token}"},
            expected_format=self.settings.tts_format,
        )
        return SynthesizedAudio(
            content=content,
            content_type=content_type,
            filename=f"speech.{audio_format}",
            provider="home_assistant",
            voice=voice,
            model=self.settings.tts_engine_id,
            language=language,
        )

    async def _openai(
        self,
        client: httpx.AsyncClient,
        text: str,
        language: str,
        voice: str,
    ) -> SynthesizedAudio:
        parsed = urlsplit(self.settings.tts_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise TTSUnavailable("OpenAI-compatible TTS URL is invalid")
        headers = {"Accept": FORMAT_CONTENT_TYPES[self.settings.tts_format]}
        token = read_secret(self.settings.tts_token_env)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        payload = {
            "model": self.settings.tts_model,
            "voice": voice or "default",
            "input": text,
            "response_format": self.settings.tts_format,
        }
        content, content_type, audio_format = await self._download(
            client,
            self.settings.tts_url,
            headers=headers,
            expected_format=self.settings.tts_format,
            method="POST",
            json=payload,
        )
        return SynthesizedAudio(
            content=content,
            content_type=content_type,
            filename=f"speech.{audio_format}",
            provider="openai",
            voice=voice or "default",
            model=self.settings.tts_model,
            language=language,
        )

    async def _download(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        expected_format: str,
        method: str = "GET",
        json: dict[str, Any] | None = None,
    ) -> tuple[bytes, str, str]:
        async with client.stream(method, url, headers=headers, json=json) as response:
            response.raise_for_status()
            declared_length = response.headers.get("content-length")
            if declared_length:
                try:
                    if int(declared_length) > self.max_bytes:
                        raise TTSRequestFailed(
                            "synthesized audio exceeds the size limit"
                        )
                except ValueError:
                    raise TTSRequestFailed(
                        "TTS provider returned an invalid content length"
                    ) from None
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > self.max_bytes:
                    raise TTSRequestFailed("synthesized audio exceeds the size limit")
            raw_type = response.headers.get("content-type", "")
        if not content:
            raise TTSRequestFailed("TTS provider returned empty audio")
        normalized_type = raw_type.partition(";")[0].strip().lower()
        if normalized_type == "application/octet-stream":
            audio_format = expected_format
            normalized_type = FORMAT_CONTENT_TYPES[audio_format]
        else:
            audio_format = CONTENT_TYPE_FORMATS.get(normalized_type, "")
        if not audio_format:
            raise TTSRequestFailed("TTS provider returned an unsupported content type")
        self._validate_signature(bytes(content), audio_format)
        return bytes(content), FORMAT_CONTENT_TYPES[audio_format], audio_format

    @staticmethod
    def _validate_signature(content: bytes, audio_format: str) -> None:
        valid = {
            "wav": len(content) >= 12
            and content.startswith(b"RIFF")
            and content[8:12] == b"WAVE",
            "flac": content.startswith(b"fLaC"),
            "ogg": content.startswith(b"OggS"),
            "mp3": content.startswith(b"ID3")
            or (len(content) >= 2 and content[0] == 0xFF and content[1] & 0xE0 == 0xE0),
            "aac": len(content) >= 2
            and content[0] == 0xFF
            and content[1] & 0xF0 == 0xF0,
        }[audio_format]
        if not valid:
            raise TTSRequestFailed(
                f"TTS provider returned invalid {audio_format} audio"
            )
