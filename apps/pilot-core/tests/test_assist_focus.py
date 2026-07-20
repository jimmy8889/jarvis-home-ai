from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from pilot_core.assist_focus import AssistFocusBridge, focus_commands
from pilot_core.config import IntegrationSettings, Room


class AssistFocusTests(unittest.IsolatedAsyncioTestCase):
    def test_state_mapping_has_expiring_active_commands(self) -> None:
        self.assertEqual(
            focus_commands("idle", "listening"),
            (
                {"action": "assistant_end"},
                {"action": "start_listening", "ttl_seconds": 45},
            ),
        )
        self.assertEqual(
            focus_commands("processing", "responding"),
            (
                {"action": "stop_listening"},
                {"action": "assistant_start", "ttl_seconds": 120},
            ),
        )
        self.assertEqual(
            focus_commands("responding", "idle"),
            ({"action": "stop_listening"}, {"action": "assistant_end"}),
        )

    async def test_bridge_routes_only_configured_satellite(self) -> None:
        sender = AsyncMock()
        room = Room(
            id="office",
            name="Office",
            response_player_id="office-response",
            default_music_player_id="office-music",
            default_device_id="pilot-office",
            assist_satellite_entity_id="assist_satellite.pilot_office",
        )
        bridge = AssistFocusBridge(IntegrationSettings(), (room,), sender)
        await bridge.handle_message(
            {
                "event": {
                    "data": {
                        "entity_id": "assist_satellite.pilot_office",
                        "new_state": {"state": "listening"},
                    }
                }
            }
        )
        self.assertEqual(sender.await_count, 2)
        self.assertEqual(sender.await_args_list[1].args[0], "pilot-office")
        self.assertEqual(
            sender.await_args_list[1].args[1]["action"], "start_listening"
        )

        await bridge.handle_message(
            {
                "event": {
                    "data": {
                        "entity_id": "assist_satellite.somewhere_else",
                        "new_state": {"state": "responding"},
                    }
                }
            }
        )
        self.assertEqual(sender.await_count, 2)
