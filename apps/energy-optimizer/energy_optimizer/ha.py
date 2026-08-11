from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx


class HomeAssistantClient:
    def __init__(self, base_url: str, token_file: Path, timeout: float = 20.0):
        token = token_file.read_text().strip()
        if not token:
            raise RuntimeError(f"Home Assistant token file is empty: {token_file}")
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def states(self) -> list[dict[str, Any]]:
        response = await self._client.get("/api/states")
        response.raise_for_status()
        return response.json()

    async def publish_state(self, entity_id: str, state: str | float, attributes: dict[str, Any]) -> None:
        response = await self._client.post(
            f"/api/states/{entity_id}",
            json={"state": state, "attributes": attributes},
        )
        response.raise_for_status()
