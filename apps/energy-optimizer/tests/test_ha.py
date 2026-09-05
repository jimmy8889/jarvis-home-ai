from __future__ import annotations

import asyncio
from collections import deque
import json
from pathlib import Path

from energy_optimizer.ha import HomeAssistantClient


def test_authenticated_state_change_subscription_filters_entities(tmp_path: Path) -> None:
    token_file = tmp_path / "ha-token"
    token_file.write_text("secret-token")

    class FakeSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []
            self.received = deque([
                {"type": "auth_required"},
                {"type": "auth_ok"},
                {"id": 1, "type": "result", "success": True},
                {
                    "type": "event",
                    "event": {
                        "data": {
                            "entity_id": "sensor.unrelated",
                            "old_state": {"state": "1"},
                            "new_state": {"state": "2"},
                        }
                    },
                },
                {
                    "type": "event",
                    "event": {
                        "time_fired": "2026-08-11T01:00:00+00:00",
                        "data": {
                            "entity_id": "sensor.amber_fit",
                            "old_state": {"state": "0.01"},
                            "new_state": {"state": "0.91"},
                        },
                    },
                },
            ])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def recv(self) -> str:
            return json.dumps(self.received.popleft())

        async def send(self, message: str) -> None:
            self.sent.append(json.loads(message))

    socket = FakeSocket()
    connection: dict[str, object] = {}

    def factory(url: str, **kwargs):
        connection["url"] = url
        connection["kwargs"] = kwargs
        return socket

    subscribed: list[bool] = []

    async def scenario() -> None:
        client = HomeAssistantClient(
            "http://ha.local:8123",
            token_file,
            websocket_factory=factory,
        )
        stream = client.state_changes(
            {"sensor.amber_fit"},
            on_subscribed=lambda: subscribed.append(True),
        )
        event = await anext(stream)
        await stream.aclose()
        await client.close()
        assert event["entity_id"] == "sensor.amber_fit"
        assert event["old_state"]["state"] == "0.01"
        assert event["new_state"]["state"] == "0.91"

    asyncio.run(scenario())

    assert connection["url"] == "ws://ha.local:8123/api/websocket"
    assert subscribed == [True]
    assert socket.sent[0] == {"type": "auth", "access_token": "secret-token"}
    assert socket.sent[1] == {
        "id": 1,
        "type": "subscribe_events",
        "event_type": "state_changed",
    }


def test_hot_water_rescue_bypasses_economic_off_dwell() -> None:
    path = (
        Path(__file__).parents[1]
        / "home-assistant"
        / "energy-optimizer-hot-water-actuator.yaml"
    )
    text = path.read_text()
    rescue_branch = text.split("Service rescue is coordinated", 1)[1].split(
        "Ordinary starts wait", 1
    )[0]

    assert "rescue_authorized | bool and runtime_due | bool and guarantee_due | bool" in rescue_branch
    assert "off_dwell_complete" not in rescue_branch
