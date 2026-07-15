from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

import httpx

from .config import IntegrationSettings


class IntegrationUnavailable(RuntimeError):
    pass


class IntegrationRequestFailed(RuntimeError):
    pass


class Integrations:
    def __init__(self, settings: IntegrationSettings) -> None:
        self.settings = settings

    async def music_assistant(
        self, command: str, args: dict[str, Any]
    ) -> Any:
        if not self.settings.music_assistant_url:
            raise IntegrationUnavailable("Music Assistant URL is not configured")
        token = os.environ.get(self.settings.music_assistant_token_env, "")
        if not token:
            raise IntegrationUnavailable("Music Assistant token is not configured")
        payload = {"message_id": str(uuid4()), "command": command, "args": args}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    f"{self.settings.music_assistant_url}/api",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise IntegrationRequestFailed(f"Music Assistant request failed: {error}") from error

    async def home_assistant_conversation(
        self,
        text: str,
        language: str = "en",
        conversation_id: str | None = None,
    ) -> Any:
        if not self.settings.home_assistant_url:
            raise IntegrationUnavailable("Home Assistant URL is not configured")
        token = os.environ.get(self.settings.home_assistant_token_env, "")
        if not token:
            raise IntegrationUnavailable("Home Assistant token is not configured")
        payload: dict[str, Any] = {"text": text, "language": language}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.settings.home_assistant_url}/api/conversation/process",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise IntegrationRequestFailed(f"Home Assistant request failed: {error}") from error
