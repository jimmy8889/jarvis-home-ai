from __future__ import annotations

import json
import os
import unittest
from collections import deque

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

    async def test_home_assistant_catalogue_fetch_is_read_only_and_bounded(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json=[
                    {
                        "entity_id": "light.office",
                        "state": "on",
                        "attributes": {"friendly_name": "Office"},
                    }
                ],
            )

        integrations = Integrations(
            IntegrationSettings(
                home_assistant_url="http://ha.local:8123",
                home_catalog_max_entities=100,
            ),
            httpx.MockTransport(handler),
        )
        result = await integrations.home_assistant_states()
        self.assertEqual(result[0]["entity_id"], "light.office")
        self.assertEqual(requests[0].method, "GET")
        self.assertEqual(requests[0].url.path, "/api/states")

    async def test_home_assistant_catalogue_rejects_oversized_entity_count(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {"entity_id": f"sensor.metric_{index}", "state": str(index)}
                    for index in range(101)
                ],
            )

        integrations = Integrations(
            IntegrationSettings(
                home_assistant_url="http://ha.local:8123",
                home_catalog_max_entities=100,
            ),
            httpx.MockTransport(handler),
        )
        with self.assertRaisesRegex(IntegrationRequestFailed, "entity limit"):
            await integrations.home_assistant_states()

    async def test_home_assistant_registry_snapshot_is_read_only_and_tolerates_unsupported_floor(
        self,
    ) -> None:
        class FakeSocket:
            def __init__(self) -> None:
                self.sent: list[dict[str, object]] = []
                self.received = deque(
                    [
                        {"type": "auth_required"},
                        {"type": "auth_ok"},
                        {
                            "id": 1,
                            "type": "result",
                            "success": True,
                            "result": [{"area_id": "office", "name": "Office"}],
                        },
                        {
                            "id": 2,
                            "type": "result",
                            "success": True,
                            "result": [{"id": "device-1", "area_id": "office"}],
                        },
                        {
                            "id": 3,
                            "type": "result",
                            "success": True,
                            "result": [
                                {
                                    "entity_id": "light.office",
                                    "device_id": "device-1",
                                    "unique_id": "stable-light",
                                }
                            ],
                        },
                        {
                            "id": 4,
                            "type": "result",
                            "success": False,
                            "error": {"code": "unknown_command"},
                        },
                    ]
                )

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def recv(self) -> str:
                return json.dumps(self.received.popleft())

            async def send(self, message: str) -> None:
                self.sent.append(json.loads(message))

        socket = FakeSocket()

        def factory(*_args, **_kwargs):
            return socket

        integrations = Integrations(
            IntegrationSettings(home_assistant_url="http://ha.local:8123"),
            websocket_factory=factory,
        )
        result = await integrations.home_assistant_registry_snapshot()
        self.assertEqual(result["areas"][0]["area_id"], "office")
        self.assertEqual(result["entities"][0]["unique_id"], "stable-light")
        self.assertIsNone(result["floors"])
        self.assertFalse(result["supported"]["floors"])
        self.assertEqual(
            [message["type"] for message in socket.sent[1:]],
            [
                "config/area_registry/list",
                "config/device_registry/list",
                "config/entity_registry/list",
                "config/floor_registry/list",
            ],
        )
        self.assertEqual(socket.sent[0]["type"], "auth")

    async def test_media_player_source_command_is_entity_scoped(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "POST")
            self.assertEqual(
                request.url.path,
                "/api/services/media_player/select_source",
            )
            self.assertEqual(dict(request.url.params), {})
            self.assertEqual(
                json.loads(request.content),
                {
                    "entity_id": "media_player.media_room",
                    "source": "Media Room - Media Player",
                },
            )
            return httpx.Response(200, json=[])

        integrations = Integrations(
            IntegrationSettings(home_assistant_url="http://ha.local:8123"),
            httpx.MockTransport(handler),
        )
        result = await integrations.home_assistant_media_player_command(
            "media_player.media_room",
            "select_source",
            source="Media Room - Media Player",
        )
        self.assertEqual(result, {"changed_states": []})

    async def test_denon_command_uses_only_whitelisted_receiver_path(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, text="")

        integrations = Integrations(
            IntegrationSettings(),
            httpx.MockTransport(handler),
        )
        result = await integrations.denon_avr_command(
            "http://10.0.1.150:8080",
            "select_source",
            source="HEOS Music",
        )
        self.assertEqual(result["accepted"], True)
        self.assertEqual(len(requests), 1)
        self.assertEqual(
            requests[0].url.path,
            "/goform/formiPhoneAppDirect.xml",
        )
        self.assertEqual(requests[0].url.query, b"SIHEOS")

    async def test_denon_command_rejects_unknown_source_without_network(self) -> None:
        called = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200)

        integrations = Integrations(
            IntegrationSettings(),
            httpx.MockTransport(handler),
        )
        with self.assertRaisesRegex(IntegrationRequestFailed, "not allowed"):
            await integrations.denon_avr_command(
                "http://10.0.1.150:8080",
                "select_source",
                source="Arbitrary command",
            )
        self.assertFalse(called)

    async def test_weather_reads_current_state_and_daily_forecast(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "entity_id": "weather.home",
                        "state": "sunny",
                        "attributes": {"temperature": 24.0},
                    },
                )
            self.assertEqual(request.url.path, "/api/services/weather/get_forecasts")
            self.assertEqual(request.url.params["return_response"], "")
            self.assertEqual(
                json.loads(request.content),
                {"entity_id": "weather.home", "type": "daily"},
            )
            return httpx.Response(
                200,
                json={
                    "service_response": {
                        "weather.home": {
                            "forecast": [{"temperature": 27, "templow": 17}]
                        }
                    }
                },
            )

        integrations = Integrations(
            IntegrationSettings(
                home_assistant_url="http://ha.local:8123",
                weather_entity_id="weather.home",
            ),
            httpx.MockTransport(handler),
        )
        result = await integrations.home_assistant_weather()
        self.assertEqual(result["current"]["state"], "sunny")
        self.assertEqual(
            result["forecast_response"]["service_response"]["weather.home"]["forecast"][
                0
            ]["temperature"],
            27,
        )
        self.assertEqual(len(requests), 2)

    async def test_temperature_history_is_bounded_to_configured_period(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.startswith("/api/states/"):
                return httpx.Response(
                    200,
                    json={
                        "entity_id": "sensor.outdoor_temperature",
                        "state": "24.5",
                        "last_updated": "2026-07-19T02:00:00+00:00",
                        "attributes": {"unit_of_measurement": "°C"},
                    },
                )
            self.assertTrue(request.url.path.startswith("/api/history/period/"))
            self.assertEqual(
                request.url.params["filter_entity_id"],
                "sensor.outdoor_temperature",
            )
            return httpx.Response(
                200,
                json=[
                    [
                        {
                            "entity_id": "sensor.outdoor_temperature",
                            "state": "17.5",
                            "last_changed": "2026-07-18T02:00:00+00:00",
                        },
                        {
                            "state": "26.0",
                            "last_changed": "2026-07-19T01:00:00+00:00",
                        },
                    ]
                ],
            )

        integrations = Integrations(
            IntegrationSettings(
                home_assistant_url="http://ha.local:8123",
                temperature_history_hours=24,
            ),
            httpx.MockTransport(handler),
        )
        result = await integrations.home_assistant_temperature_history(
            "sensor.outdoor_temperature"
        )
        self.assertEqual(result["period_hours"], 24)
        self.assertEqual(result["current"]["state"], "24.5")
        self.assertEqual(len(result["history"][0]), 2)
        self.assertEqual(len(requests), 2)

    async def test_energy_history_carries_entity_id_across_minimal_response_series(
        self,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "GET")
            self.assertTrue(request.url.path.startswith("/api/history/period/"))
            self.assertEqual(
                request.url.params["filter_entity_id"],
                "sensor.home_load,sensor.solar_power",
            )
            self.assertIn("minimal_response", request.url.params)
            self.assertIn("no_attributes", request.url.params)
            return httpx.Response(
                200,
                json=[
                    [
                        {
                            "entity_id": "sensor.home_load",
                            "state": "1020",
                            "last_changed": "2026-07-21T00:00:00+00:00",
                        },
                        {
                            "state": "1180",
                            "last_changed": "2026-07-21T00:05:00+00:00",
                        },
                        {
                            "state": "1250",
                            "last_changed": "2026-07-21T00:10:00+00:00",
                        },
                    ],
                    [
                        {
                            "entity_id": "sensor.solar_power",
                            "state": "4010",
                            "last_changed": "2026-07-21T00:00:00+00:00",
                        },
                        {
                            "state": "4260",
                            "last_changed": "2026-07-21T00:05:00+00:00",
                        },
                    ],
                ],
            )

        integrations = Integrations(
            IntegrationSettings(home_assistant_url="http://ha.local:8123"),
            httpx.MockTransport(handler),
        )
        result = await integrations.home_assistant_history(
            ("sensor.home_load", "sensor.solar_power"),
            hours=24,
        )
        self.assertEqual(
            [state["state"] for state in result["sensor.home_load"]],
            ["1020", "1180", "1250"],
        )
        self.assertEqual(
            [state["state"] for state in result["sensor.solar_power"]],
            ["4010", "4260"],
        )

    async def test_energy_history_discards_malformed_series_without_cross_assignment(
        self,
    ) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    [
                        {
                            "state": "1000",
                            "last_changed": "2026-07-21T00:00:00+00:00",
                        },
                        {
                            "entity_id": "sensor.home_load",
                            "state": "1100",
                            "last_changed": "2026-07-21T00:05:00+00:00",
                        },
                    ],
                    [
                        {
                            "entity_id": "sensor.home_load",
                            "state": "1200",
                            "last_changed": "2026-07-21T00:10:00+00:00",
                        },
                        {
                            "entity_id": "sensor.solar_power",
                            "state": "4200",
                            "last_changed": "2026-07-21T00:15:00+00:00",
                        },
                    ],
                    [
                        {
                            "entity_id": "sensor.not_requested",
                            "state": "9999",
                            "last_changed": "2026-07-21T00:20:00+00:00",
                        }
                    ],
                    [
                        {
                            "entity_id": "sensor.home_load",
                            "state": "1300",
                            "last_changed": "2026-07-21T00:25:00+00:00",
                        },
                        "not-a-state",
                    ],
                    [
                        {
                            "entity_id": "sensor.solar_power",
                            "state": "4300",
                            "last_changed": "2026-07-21T00:30:00+00:00",
                        },
                        {
                            "state": "4400",
                            "last_changed": "2026-07-21T00:35:00+00:00",
                        },
                    ],
                    {"entity_id": "sensor.home_load"},
                    [],
                ],
            )

        integrations = Integrations(
            IntegrationSettings(home_assistant_url="http://ha.local:8123"),
            httpx.MockTransport(handler),
        )
        result = await integrations.home_assistant_history(
            ("sensor.home_load", "sensor.solar_power"),
            hours=24,
        )
        self.assertEqual(result["sensor.home_load"], [])
        self.assertEqual(
            [state["state"] for state in result["sensor.solar_power"]],
            ["4300", "4400"],
        )


if __name__ == "__main__":
    unittest.main()
