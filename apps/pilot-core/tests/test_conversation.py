from __future__ import annotations

from dataclasses import replace
import json
import os
from datetime import UTC, datetime
import unittest
from unittest.mock import AsyncMock, MagicMock

import httpx

from pilot_core.config import (
    IntegrationSettings,
    LLMBackend,
    Player,
    Room,
    ServerSettings,
    Settings,
)
from pilot_core.conversation import (
    AssistantTools,
    ConversationEngine,
    LLMRequestFailed,
    OpenAICompatibleLLM,
    _required_action_tool,
)
from pilot_core.home_intelligence import HomeResolutionError
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
        llm_reasoning_effort="none" if llm else "",
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

    def test_read_only_light_capability_question_never_forces_action(self) -> None:
        self.assertIsNone(
            _required_action_tool(
                "Which office lights can change colour? Do not change anything."
            )
        )
        self.assertIsNone(
            _required_action_tool("What lights are available without changing them?")
        )

    def test_unsafe_light_phrases_never_force_action(self) -> None:
        for text in (
            "Don't turn off the lights.",
            "Never dim the bedroom lights.",
            "What if I turned off the lights?",
            "How do I change the light colour?",
            "Turn every light in the whole house off.",
        ):
            with self.subTest(text=text):
                self.assertIsNone(_required_action_tool(text))

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
            "Turn on the fan",
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

    async def test_governed_light_llm_outage_never_falls_back_to_ha(self) -> None:
        engine, store, integrations, llm = self.engine(test_settings(llm=True))
        integrations.home_assistant_conversation = AsyncMock()
        llm.chat = AsyncMock(side_effect=LLMRequestFailed("inference offline"))

        result = await engine.respond(
            "Turn off the bedroom light",
            "bedroom",
            device_id="bedroom-display",
        )

        self.assertEqual(result.provider, "pilot_guardrail")
        self.assertEqual(result.result["status"], "not_executed")
        integrations.home_assistant_conversation.assert_not_awaited()
        store.close()

    async def test_successful_light_action_survives_response_llm_outage(self) -> None:
        engine, store, integrations, llm = self.engine(test_settings(llm=True))
        integrations.home_assistant_conversation = AsyncMock()
        engine.tools.execute = AsyncMock(
            return_value={
                "success": True,
                "status": "succeeded",
                "room_id": "bedroom",
                "entity_id": "light.bedroom_main",
                "action": "turn_off",
                "audit_id": "audit-1",
            }
        )
        llm.chat = AsyncMock(
            side_effect=[
                {
                    "tool_calls": [
                        {
                            "id": "light-1",
                            "function": {
                                "name": "control_light",
                                "arguments": json.dumps(
                                    {
                                        "entity": "Bedroom light",
                                        "action": "turn_off",
                                    }
                                ),
                            },
                        }
                    ]
                },
                LLMRequestFailed("response model unavailable"),
            ]
        )

        result = await engine.respond(
            "Turn off the bedroom light",
            "bedroom",
            device_id="bedroom-display",
        )

        self.assertEqual(result.provider, "pilot_core")
        self.assertIn("is off", result.response_text)
        self.assertEqual(len(result.tool_calls), 1)
        engine.tools.execute.assert_awaited_once()
        integrations.home_assistant_conversation.assert_not_awaited()
        store.close()

    async def test_only_one_light_mutation_executes_per_turn(self) -> None:
        engine, store, integrations, llm = self.engine(test_settings(llm=True))
        integrations.home_assistant_conversation = AsyncMock()
        engine.tools.execute = AsyncMock(
            return_value={
                "success": True,
                "status": "succeeded",
                "room_id": "bedroom",
                "entity_id": "light.bedroom_main",
                "action": "turn_off",
                "audit_id": "audit-1",
            }
        )
        call_payload = {
            "function": {
                "name": "control_light",
                "arguments": json.dumps(
                    {"entity": "Bedroom light", "action": "turn_off"}
                ),
            }
        }
        llm.chat = AsyncMock(
            side_effect=[
                {
                    "tool_calls": [
                        {"id": "light-1", **call_payload},
                        {"id": "light-2", **call_payload},
                    ]
                },
                {"content": "The bedroom light is off."},
            ]
        )

        result = await engine.respond(
            "Turn off the bedroom light",
            "bedroom",
            device_id="bedroom-display",
        )

        engine.tools.execute.assert_awaited_once()
        self.assertEqual(len(result.tool_calls), 2)
        self.assertFalse(result.tool_calls[1]["output"]["success"])
        self.assertIn("only one", result.tool_calls[1]["output"]["error"])
        integrations.home_assistant_conversation.assert_not_awaited()
        store.close()

    async def test_guarded_unsafe_requests_never_reach_ha(self) -> None:
        for text in (
            "Don't turn off the lights.",
            "What if I turned off the lights?",
            "Turn every light in the whole house off.",
            "Unlock the front door.",
            "Open the garage door.",
        ):
            with self.subTest(text=text):
                engine, store, integrations, _ = self.engine(test_settings())
                integrations.home_assistant_conversation = AsyncMock()
                result = await engine.respond(text, "bedroom")
                self.assertEqual(result.provider, "pilot_guardrail")
                self.assertEqual(result.result["status"], "not_executed")
                integrations.home_assistant_conversation.assert_not_awaited()
                store.close()

    async def test_cross_room_light_target_must_be_named_by_user(self) -> None:
        base = test_settings(llm=True)
        media_room = Room(
            id="media-room",
            name="Media Room",
            response_player_id="media-response",
            default_music_player_id="media-music",
        )
        multi_room = replace(
            base,
            rooms=(*base.rooms, media_room),
            players=(
                *base.players,
                Player(
                    id="media-response",
                    room_id="media-room",
                    name="Media response",
                    protocol="pilot",
                    kind="response",
                ),
                Player(
                    id="media-music",
                    room_id="media-room",
                    name="Media music",
                    protocol="future",
                    kind="music",
                    control_enabled=False,
                ),
            ),
        )
        engine, store, _, _ = self.engine(multi_room)
        store.register_device(
            "pilot-phone",
            "bedroom",
            "Pilot Phone",
            ["voice", "home-control", "portable-client"],
        )
        engine.tools.home_intelligence = MagicMock()
        engine.tools.home_actions = MagicMock()
        engine.tools.home_actions.authorize_room.return_value = "media-room"
        engine.tools.home_actions.prepare.return_value = {
            "id": "action-1",
            "confirmation_required": False,
        }
        engine.tools.home_actions.execute = AsyncMock(
            return_value={"id": "action-1", "status": "succeeded", "result": {}}
        )
        engine.tools._resolve_light = MagicMock(
            return_value={"entity_id": "light.media_room"}
        )

        with self.assertRaisesRegex(HomeResolutionError, "cross-room"):
            await engine.tools.execute(
                "control_light",
                {
                    "entity": "Media Room lights",
                    "room": "media-room",
                    "action": "turn_off",
                },
                room_id="bedroom",
                language="en",
                provider_conversation_id=None,
                device_id="pilot-phone",
                user_text="Turn the bedroom lights off",
            )
        engine.tools.home_actions.authorize_room.assert_not_called()

        result = await engine.tools.execute(
            "control_light",
            {
                "entity": "Media Room lights",
                "room": "media-room",
                "action": "turn_off",
            },
            room_id="bedroom",
            language="en",
            provider_conversation_id=None,
            device_id="pilot-phone",
            user_text="Turn the media room lights off",
        )
        self.assertTrue(result["success"])
        engine.tools.home_actions.execute.assert_awaited_once()
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
        first_call = llm.chat.await_args_list[0]
        self.assertEqual(
            first_call.kwargs["tool_choice"]["function"]["name"],
            "get_temperature",
        )
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

    async def test_openai_client_sends_configured_reasoning_effort(self) -> None:
        observed: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            observed.update(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"role": "assistant", "content": "Brief answer."}}
                    ]
                },
            )

        settings = test_settings(llm=True)
        llm = OpenAICompatibleLLM(
            settings.integrations,
            httpx.MockTransport(handler),
        )
        await llm.chat([{"role": "user", "content": "Hello"}], [])
        self.assertEqual(observed["reasoning_effort"], "none")
        self.assertEqual(observed["tool_choice"], "auto")
        self.assertEqual(observed["max_tokens"], 1024)

    async def test_vllm_pool_fails_over_and_reports_active_backend(self) -> None:
        requested_hosts: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested_hosts.append(request.url.host or "")
            if request.url.host == "ai3090":
                return httpx.Response(503, json={"error": "busy"})
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"role": "assistant", "content": "Fallback."}}
                    ]
                },
            )

        settings = IntegrationSettings(
            llm_provider="vllm",
            llm_backends=(
                LLMBackend(
                    id="ai3090-primary",
                    url="http://ai3090:8000/v1",
                    model="primary",
                    roles=("assistant", "meeting"),
                    priority=10,
                ),
                LLMBackend(
                    id="ai3080-verifier",
                    url="http://ai3080:8000/v1",
                    model="verifier",
                    roles=("assistant", "verification"),
                    priority=100,
                ),
            ),
        )
        llm = OpenAICompatibleLLM(settings, httpx.MockTransport(handler))
        message = await llm.chat([{"role": "user", "content": "Hello"}], [])

        self.assertEqual(message["content"], "Fallback.")
        self.assertEqual(requested_hosts, ["ai3090", "ai3080"])
        self.assertEqual(llm.status()["active_backend"], "ai3080-verifier")
        self.assertEqual(llm.status()["backend_count"], 2)

    async def test_meeting_question_forces_evidence_search_tool(self) -> None:
        engine, store, integrations, llm = self.engine(test_settings(llm=True))
        meeting = store.create_meeting(
            "Release planning",
            "en-AU",
            datetime.now(UTC).isoformat(),
            None,
        )
        stored = store.replace_transcript(
            meeting["id"],
            [
                {
                    "speaker_label": "James",
                    "start_ms": 1000,
                    "end_ms": 3000,
                    "text": "I will prepare the proposal by Friday.",
                    "confidence": 0.95,
                }
            ],
        )
        segment_id = stored["transcript"][0]["id"]
        store.replace_meeting_analysis(
            meeting["id"],
            "James agreed to prepare the proposal.",
            [],
            [
                {
                    "task": "Prepare the proposal",
                    "owner": "James",
                    "due_at": None,
                    "confidence": 0.95,
                    "segment_ids": [segment_id],
                }
            ],
        )
        integrations.home_assistant_conversation = AsyncMock(
            return_value={
                "response": {
                    "response_type": "error",
                    "data": {"code": "no_intent_match"},
                    "speech": {"plain": {"speech": "I couldn't understand."}},
                }
            }
        )
        llm.chat = AsyncMock(
            side_effect=[
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "meeting-search",
                            "type": "function",
                            "function": {
                                "name": "search_meetings",
                                "arguments": json.dumps(
                                    {"query": "proposal Friday", "limit": 5}
                                ),
                            },
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "content": (
                        "You agreed to prepare the proposal by Friday in "
                        "Release planning."
                    ),
                },
            ]
        )
        response = await engine.respond(
            "What did I agree to in the meeting about the proposal?",
            "bedroom",
            device_id="bedroom-display",
        )
        self.assertEqual(response.provider, "pilot_llm")
        self.assertEqual(response.tool_calls[0]["name"], "search_meetings")
        evidence = response.tool_calls[0]["output"]["meetings"][0]["matching_segments"]
        self.assertEqual(evidence[0]["id"], segment_id)
        self.assertEqual(
            llm.chat.await_args_list[0].kwargs["tool_choice"]["function"]["name"],
            "search_meetings",
        )
        store.close()


if __name__ == "__main__":
    unittest.main()
