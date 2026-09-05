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

    def test_navigation_service_is_fixed_to_native_bridge_and_bounded_coordinates(self) -> None:
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
                "pilot_vehicle",
                "send_navigation",
                device_id="native-tesla-device-id",
                service_data={"latitude": -27.4, "longitude": 153.0, "order": 0},
            )
        )

        self.assertTrue(result["accepted"])
        self.assertEqual(captured["path"], "/api/services/pilot_vehicle/send_navigation")
        self.assertEqual(
            captured["payload"],  # type: ignore[comparison-overlap]
            {
                "device_id": "native-tesla-device-id",
                "latitude": -27.4,
                "longitude": 153.0,
                "order": 0,
            },
        )

    def test_navigation_requires_exact_bounded_payload(self) -> None:
        integrations = Integrations(
            IntegrationSettings(home_assistant_url="http://ha.test:8123"),
            transport=httpx.MockTransport(
                lambda _request: self.fail("network must not be reached")
            ),
        )

        with self.assertRaises(IntegrationRequestFailed):
            asyncio.run(
                integrations.home_assistant_vehicle_action(
                    "pilot_vehicle",
                    "send_navigation",
                    device_id="native-tesla-device-id",
                    service_data={"latitude": -91, "longitude": 153, "order": 0},
                )
            )

        with self.assertRaises(IntegrationRequestFailed):
            asyncio.run(
                integrations.home_assistant_vehicle_action(
                    "pilot_vehicle",
                    "send_navigation",
                    device_id="native-tesla-device-id",
                    service_data={
                        "latitude": -27.4,
                        "longitude": 153.0,
                        "order": 0,
                        "command": "REMOTE_START",
                    },
                )
            )

    def test_hvac_mode_is_bounded_and_forwarded(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json=[])

        integrations = Integrations(
            IntegrationSettings(home_assistant_url="http://ha.test:8123"),
            transport=httpx.MockTransport(handler),
        )
        asyncio.run(
            integrations.home_assistant_vehicle_action(
                "climate",
                "set_hvac_mode",
                entity_id="climate.jarvis_hvac_climate_system",
                service_data={"hvac_mode": "heat_cool"},
            )
        )
        self.assertEqual(captured["path"], "/api/services/climate/set_hvac_mode")
        self.assertEqual(
            captured["payload"],
            {
                "entity_id": "climate.jarvis_hvac_climate_system",
                "hvac_mode": "heat_cool",
            },
        )

    def test_native_bridge_preserves_actionable_home_assistant_error(self) -> None:
        integrations = Integrations(
            IntegrationSettings(home_assistant_url="http://ha.test:8123"),
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    401, json={"message": "Tesla Fleet rejected navigation; verify key enrollment"}
                )
            ),
        )
        with self.assertRaisesRegex(IntegrationRequestFailed, "verify key enrollment"):
            asyncio.run(
                integrations.home_assistant_vehicle_action(
                    "pilot_vehicle",
                    "send_navigation",
                    device_id="native-tesla-device-id",
                    service_data={"latitude": -27.4, "longitude": 153.0, "order": 0},
                )
            )


if __name__ == "__main__":
    unittest.main()
