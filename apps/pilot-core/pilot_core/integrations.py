from __future__ import annotations

import asyncio
import re
import time
from typing import Any
from uuid import uuid4

import httpx

from .config import IntegrationSettings
from .secret_values import read_secret


class IntegrationUnavailable(RuntimeError):
    pass


class IntegrationRequestFailed(RuntimeError):
    pass


_ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


class Integrations:
    def __init__(
        self,
        settings: IntegrationSettings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    async def music_assistant(
        self, command: str, args: dict[str, Any]
    ) -> Any:
        if not self.settings.music_assistant_url:
            raise IntegrationUnavailable("Music Assistant URL is not configured")
        token = read_secret(self.settings.music_assistant_token_env)
        if not token:
            raise IntegrationUnavailable("Music Assistant token is not configured")
        payload = {"message_id": str(uuid4()), "command": command, "args": args}
        try:
            async with httpx.AsyncClient(
                timeout=10, transport=self.transport, follow_redirects=False
            ) as client:
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
        token = read_secret(self.settings.home_assistant_token_env)
        if not token:
            raise IntegrationUnavailable("Home Assistant token is not configured")
        payload: dict[str, Any] = {"text": text, "language": language}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        try:
            async with httpx.AsyncClient(
                timeout=30, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.post(
                    f"{self.settings.home_assistant_url}/api/conversation/process",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise IntegrationRequestFailed(f"Home Assistant request failed: {error}") from error

    async def home_assistant_state(self, entity_id: str) -> dict[str, Any]:
        if not _ENTITY_ID.fullmatch(entity_id):
            raise IntegrationRequestFailed("Home Assistant entity ID is invalid")
        if not self.settings.home_assistant_url:
            raise IntegrationUnavailable("Home Assistant URL is not configured")
        token = read_secret(self.settings.home_assistant_token_env)
        if not token:
            raise IntegrationUnavailable("Home Assistant token is not configured")
        try:
            async with httpx.AsyncClient(
                timeout=10, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.get(
                    f"{self.settings.home_assistant_url}/api/states/{entity_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("state response is not an object")
                return payload
        except (httpx.HTTPError, ValueError) as error:
            raise IntegrationRequestFailed(
                f"Home Assistant state request failed: {error}"
            ) from error

    async def diagnostics(self) -> dict[str, Any]:
        """Run read-only provider checks without returning URLs or credentials."""

        home_assistant, music_assistant = await asyncio.gather(
            self._home_assistant_diagnostic(),
            self._music_assistant_diagnostic(),
        )
        return {
            "home_assistant": home_assistant,
            "music_assistant": music_assistant,
        }

    async def _home_assistant_diagnostic(self) -> dict[str, Any]:
        url = self.settings.home_assistant_url
        token = read_secret(self.settings.home_assistant_token_env)
        return await self._diagnostic_request(
            "home_assistant",
            bool(url),
            bool(token),
            "GET",
            f"{url}/api/" if url else "",
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )

    async def _music_assistant_diagnostic(self) -> dict[str, Any]:
        url = self.settings.music_assistant_url
        token = read_secret(self.settings.music_assistant_token_env)
        return await self._diagnostic_request(
            "music_assistant",
            bool(url),
            bool(token),
            "POST",
            f"{url}/api" if url else "",
            headers={"Authorization": f"Bearer {token}"} if token else {},
            json={
                "message_id": str(uuid4()),
                "command": "players/all",
                "args": {},
            },
        )

    async def _diagnostic_request(
        self,
        provider: str,
        configured: bool,
        credential_configured: bool,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "provider": provider,
            "configured": configured,
            "credential_configured": credential_configured,
            "reachable": False,
            "latency_ms": None,
            "status": "not_configured",
        }
        if not configured or not credential_configured:
            if configured:
                result["status"] = "credential_missing"
            return result
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=10, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
            result["reachable"] = True
            result["status"] = "ok"
        except httpx.HTTPStatusError as error:
            result["status"] = "http_error"
            result["http_status"] = error.response.status_code
        except httpx.HTTPError:
            result["status"] = "connection_error"
        finally:
            result["latency_ms"] = round((time.monotonic() - started) * 1000)
        return result
