from __future__ import annotations

import asyncio
import json
import os
import unittest

import httpx

from pilot_core.config import IntegrationSettings
from pilot_core.integrations import IntegrationRequestFailed, Integrations


class VehicleIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["HOME_ASSISTANT_TOKEN"] = "ha-test"

    def tearDown(self) -> None:
        os.environ.pop("HOME_ASSISTANT_TOKEN", None)

    def test_navigation_service_is_fixed_to_gps_command_and_bounded_coordinates(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json=[])

        integrations = Integrations(
            IntegrationSettings(home_assistant_url="http://ha.test:8123"),
            transport=httpx.MockTransport(handler),
        )
        result = asyncio.run(
            integrations.home_assistant_vehicle_action(
                "tesla_custom",
                "api",
                service_data={
                    "command": "SEND_GPS_TO_VEHICLE",
                    "parameters": {
                        "path_vars": {"vehicle_id": "internal-provider-id"},
                        "lat": -27.4,
                        "lon": 153.0,
                        "order": 0,
                    },
                },
            )
        )

        self.assertTrue(result["accepted"])
        self.assertEqual(captured["path"], "/api/services/tesla_custom/api")
        self.assertEqual(
            captured["payload"]["command"],  # type: ignore[index]
            "SEND_GPS_TO_VEHICLE",
        )

    def test_generic_tesla_commands_are_rejected_before_network(self) -> None:
        integrations = Integrations(
            IntegrationSettings(home_assistant_url="http://ha.test:8123"),
            transport=httpx.MockTransport(
                lambda _request: self.fail("network must not be reached")
            ),
        )

        with self.assertRaises(IntegrationRequestFailed):
            asyncio.run(
                integrations.home_assistant_vehicle_action(
                    "tesla_custom",
                    "api",
                    service_data={
                        "command": "REMOTE_START",
                        "parameters": {
                            "path_vars": {"vehicle_id": "internal-provider-id"},
                            "lat": -27.4,
                            "lon": 153.0,
                            "order": 0,
                        },
                    },
                )
            )


if __name__ == "__main__":
    unittest.main()
