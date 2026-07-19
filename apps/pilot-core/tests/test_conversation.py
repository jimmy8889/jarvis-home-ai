from __future__ import annotations

import json
import os
import unittest
from unittest.mock import AsyncMock

from pilot_core.config import (
    IntegrationSettings,
    Player,
    Room,
    ServerSettings,
    Settings,
)
from pilot_core.conversation import (
    AssistantTools,
    ConversationEngine,
    OpenAICompatibleLLM,
)
from pilot_core.integrations import Integrations
from pilot_core.media_state import MediaStateReader
from pilot_core.orchestration import RoomOrchestrator
from pilot_core.registry import Registry
from pilot_core.storage import Store


def test_settings(llm: bool = False) -> Settings:
    integrations = IntegrationSettings(
        home_assistant_url="http://ha.local:8123",
        indoor_temperature_entity_id="sensor.bedroom_temperature",
        outdoor_temperature_entity_id="sensor.outdoor_temperature",
        llm_provider="openai" if llm else "",
        llm_url="http://rtx.local:11434/v1" if llm else "",
        llm_model="qwen3:8b" if llm else "",
    )
    return Settings(
        server=ServerSettings(database_path=":memory:"),
        integrations=integrations,
        rooms=(
            Room(
                id="bedroom",
                name="Bedroom",
                response_player_id="bedroom-response",
                default_music_player_id="bedroom-music",
            ),
        ),
        players=(
            Player(
                id="bedroom-response",
                room_id="bedroom",
                name="Bedroom Response",
                protocol="pilot",
                kind="response",
            ),
            Player(
                id="bedroom-music",
                room_id="bedroom",
                name="Bedroom Music",
                protocol="future",
                kind="music",
                control_enabled=False,
            ),
        ),
    )


class ConversationEngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        os.environ["HOME_ASSISTANT_TOKEN"] = "ha-token"

    async def asyncTearDown(self) -> None:
        os.environ.pop("HOME_ASSISTANT_TOKEN", None)

    def engine(self, settings: Settings):
        store = Store(":memory:", settings)
        registry = Registry.from_settings(settings)
        integrations = Integrations(settings.integrations)
        media_states = MediaStateReader(registry, integrations)
        tools = AssistantTools(
            registry,
            RoomOrchestrator(registry, store),
            integrations,
            media_states,
            store,
        )
        llm = OpenAICompatibleLLM(settings.integrations)
        return (
            ConversationEngine(store, registry, tools, integrations, llm),
            store,
            integrations,
            llm,
        )

    async def test_deterministic_commands_reuse_pilot_and_ha_sessions(self) -> None:
        engine, store, integrations, _ = self.engine(test_settings())
        integrations.home_assistant_conversation = AsyncMock(
            side_effect=[
                {
                    "conversation_id": "ha-1",
                    "response": {
                        "response_type": "action_done",
                        "speech": {"plain": {"speech": "The light is on."}},
                    },
                },
                {
                    "conversation_id": "ha-1",
                    "response": {
                        "response_type": "query_answer",
                        "speech": {"plain": {"speech": "It is at 50 percent."}},
                    },
                },
            ]
        )
        first = await engine.respond(
            "Turn on the light",
            "bedroom",
            device_id="bedroom-display",
        )
        second = await engine.respond(
            "What brightness is it?",
            "bedroom",
            session_id=first.session_id,
            device_id="bedroom-display",
        )
        self.assertEqual(second.session_id, first.session_id)
        self.assertEqual(second.provider, "home_assistant")
        self.assertEqual(
            integrations.home_assistant_conversation.await_args_list[0].kwargs[
                "agent_id"
            ],
            "conversation.home_assistant",
        )
        self.assertEqual(
            integrations.home_assistant_conversation.await_args_list[1].args[2],
            "ha-1",
        )
        self.assertEqual(
            [turn["role"] for turn in store.conversation_turns(first.session_id)],
            ["user", "assistant", "user", "assistant"],
        )
        store.close()

    async def test_no_intent_falls_back_to_local_llm_and_typed_tool(self) -> None:
        engine, store, integrations, llm = self.engine(test_settings(llm=True))
        integrations.home_assistant_conversation = AsyncMock(
            return_value={
                "conversation_id": "ha-2",
                "response": {
                    "response_type": "error",
                    "data": {"code": "no_intent_match"},
                    "speech": {"plain": {"speech": "Sorry, I couldn't understand."}},
                },
            }
        )
        integrations.home_assistant_state = AsyncMock(
            return_value={
                "entity_id": "sensor.bedroom_temperature",
                "state": "22.4",
                "attributes": {"unit_of_measurement": "°C"},
            }
        )
        llm.chat = AsyncMock(
            side_effect=[
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "get_temperature",
                                "arguments": json.dumps({"location": "inside"}),
                            },
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "content": "The bedroom is 22.4 degrees.",
                },
            ]
        )
        result = await engine.respond(
            "Is it warmer in here than before?",
            "bedroom",
            device_id="bedroom-display",
        )
        self.assertEqual(result.provider, "pilot_llm")
        self.assertEqual(result.response_text, "The bedroom is 22.4 degrees.")
        self.assertEqual(result.tool_calls[0]["name"], "get_temperature")
        turns = store.conversation_turns(result.session_id)
        self.assertEqual(
            [turn["role"] for turn in turns],
            ["user", "tool", "assistant"],
        )
        self.assertEqual(turns[1]["metadata"]["name"], "get_temperature")
        store.close()

    async def test_play_music_rejects_uri_not_returned_by_search(self) -> None:
        engine, store, integrations, llm = self.engine(test_settings(llm=True))
        integrations.home_assistant_conversation = AsyncMock(
            return_value={
                "conversation_id": "ha-3",
                "response": {
                    "response_type": "error",
                    "data": {"code": "no_intent_match"},
                    "speech": {"plain": {"speech": "Sorry, I couldn't understand."}},
                },
            }
        )
        integrations.music_assistant = AsyncMock()
        llm.chat = AsyncMock(
            side_effect=[
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-untrusted",
                            "type": "function",
                            "function": {
                                "name": "play_music",
                                "arguments": json.dumps(
                                    {"media_uri": "http://untrusted.invalid/audio"}
                                ),
                            },
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "content": "I couldn't safely play that.",
                },
            ]
        )

        result = await engine.respond(
            "Play this link",
            "bedroom",
            device_id="bedroom-display",
        )

        integrations.music_assistant.assert_not_awaited()
        self.assertFalse(result.tool_calls[0]["output"]["success"])
        self.assertIn("search_music", result.tool_calls[0]["output"]["error"])
        store.close()


if __name__ == "__main__":
    unittest.main()
