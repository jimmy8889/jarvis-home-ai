from __future__ import annotations

import json
import os
import unittest

import httpx

from pilot_core.config import IntegrationSettings
from pilot_core.integrations import IntegrationRequestFailed, Integrations


class IntegrationDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        os.environ["HOME_ASSISTANT_TOKEN"] = "ha-token"
        os.environ["MUSIC_ASSISTANT_TOKEN"] = "ma-token"

    async def asyncTearDown(self) -> None:
        os.environ.pop("HOME_ASSISTANT_TOKEN", None)
        os.environ.pop("MUSIC_ASSISTANT_TOKEN", None)

    async def test_diagnostics_use_only_read_only_provider_calls(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.host == "ha.local":
                self.assertEqual(request.method, "GET")
                self.assertEqual(request.url.path, "/api/")
                return httpx.Response(200, json={"message": "API running"})
            payload = json.loads(request.content)
            self.assertEqual(payload["command"], "players/all")
            self.assertEqual(payload["args"], {})
            return httpx.Response(200, json={"result": []})

        settings = IntegrationSettings(
            home_assistant_url="http://ha.local:8123",
            music_assistant_url="http://ma.local:8095",
        )
        integrations = Integrations(settings, httpx.MockTransport(handler))
        result = await integrations.diagnostics()
        self.assertEqual(result["home_assistant"]["status"], "ok")
        self.assertEqual(result["music_assistant"]["status"], "ok")
        self.assertEqual(len(requests), 2)

    async def test_diagnostics_report_missing_credentials_without_network(self) -> None:
        os.environ.pop("HOME_ASSISTANT_TOKEN")
        os.environ.pop("MUSIC_ASSISTANT_TOKEN")
        called = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(500)

        settings = IntegrationSettings(
            home_assistant_url="http://ha.local:8123",
            music_assistant_url="http://ma.local:8095",
        )
        integrations = Integrations(settings, httpx.MockTransport(handler))
        result = await integrations.diagnostics()
        self.assertEqual(result["home_assistant"]["status"], "credential_missing")
        self.assertEqual(result["music_assistant"]["status"], "credential_missing")
        self.assertFalse(called)

    async def test_home_assistant_state_rejects_invalid_entity_path(self) -> None:
        integrations = Integrations(
            IntegrationSettings(home_assistant_url="http://ha.local:8123")
        )
        with self.assertRaisesRegex(IntegrationRequestFailed, "invalid"):
            await integrations.home_assistant_state(
                "media_player.media_room/../../config"
            )


if __name__ == "__main__":
    unittest.main()
