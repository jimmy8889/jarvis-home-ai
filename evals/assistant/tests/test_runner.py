from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from evals.assistant.runner import (
    CorpusError,
    DEFAULT_CORPUS,
    EvalCase,
    EvalTurn,
    build_report,
    evaluate_response,
    load_corpus,
    run_suite,
)


class FakeClient:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def respond(
        self,
        text: str,
        room_id: str,
        conversation_id: str | None,
        *,
        language: str,
    ) -> dict:
        self.calls.append(
            {
                "text": text,
                "room_id": room_id,
                "conversation_id": conversation_id,
                "language": language,
            }
        )
        return self.responses.pop(0)


def case(*, mutation: bool, turns: tuple[EvalTurn, ...]) -> EvalCase:
    return EvalCase(
        id="sample",
        category="test",
        description="Sample evaluation",
        room_id="office",
        mutation=mutation,
        tags=("test",),
        turns=turns,
    )


class CorpusTests(unittest.TestCase):
    def test_curated_corpus_loads_with_all_required_categories(self) -> None:
        cases = load_corpus(DEFAULT_CORPUS)
        self.assertGreaterEqual(len(cases), 16)
        categories = {item.category for item in cases}
        self.assertTrue(
            {
                "context",
                "home_read",
                "light_control",
                "non_home",
                "safety",
            }.issubset(categories)
        )
        self.assertTrue(any(item.mutation for item in cases))
        self.assertTrue(any(not item.mutation for item in cases))

    def test_duplicate_ids_are_rejected(self) -> None:
        value = {
            "schema_version": "pilot.assistant-eval-case.v1",
            "id": "duplicate",
            "category": "test",
            "description": "Duplicate fixture",
            "room_id": "office",
            "mutation": False,
            "tags": [],
            "turns": [{"text": "Hello", "expect": {}}],
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.jsonl"
            path.write_text(
                json.dumps(value) + "\n" + json.dumps(value) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CorpusError, "duplicate case id"):
                load_corpus(path)


class EvaluationTests(unittest.TestCase):
    def test_home_assistant_action_done_is_a_successful_action(self) -> None:
        result = evaluate_response(
            {
                "provider": "home_assistant",
                "response_text": "The office lights are blue.",
                "result": {"response": {"response_type": "action_done"}},
                "tool_calls": [],
            },
            {"providers_any": ["home_assistant"], "action": "succeeded"},
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["action_outcome"], "succeeded")

    def test_typed_block_is_not_treated_as_executed(self) -> None:
        result = evaluate_response(
            {
                "provider": "pilot_llm",
                "response_text": "Which office light did you mean?",
                "tool_calls": [
                    {
                        "name": "control_light",
                        "output": {"success": False, "error": "ambiguous"},
                    }
                ],
            },
            {
                "providers_any": ["pilot_llm"],
                "action": "not_executed",
                "response_any": ["which"],
            },
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["action_outcome"], "blocked")

    def test_read_answer_requires_grounding_and_no_action(self) -> None:
        result = evaluate_response(
            {
                "provider": "pilot_llm",
                "response_text": "The office lights are off.",
                "tool_calls": [
                    {"name": "get_home_area_summary", "output": {"entities": []}}
                ],
            },
            {"action": "none", "grounded": True},
        )
        self.assertTrue(result["passed"])
        self.assertTrue(result["grounded"])

    def test_mutation_cases_are_never_sent_without_explicit_flag(self) -> None:
        selected = case(
            mutation=True,
            turns=(EvalTurn("Turn on the light", {"action": "succeeded"}),),
        )
        client = FakeClient([])
        results = run_suite([selected], client, allow_actions=False)
        self.assertEqual(results[0]["status"], "skipped")
        self.assertEqual(client.calls, [])

    def test_explicit_action_flag_allows_mutation_case_to_run(self) -> None:
        selected = case(
            mutation=True,
            turns=(EvalTurn("Turn on the light", {"action": "succeeded"}),),
        )
        client = FakeClient(
            [
                {
                    "provider": "home_assistant",
                    "response_text": "The light is on.",
                    "result": {"response": {"response_type": "action_done"}},
                }
            ]
        )
        results = run_suite([selected], client, allow_actions=True)
        self.assertEqual(results[0]["status"], "passed")
        self.assertEqual(len(client.calls), 1)

    def test_conversation_id_is_carried_across_contextual_turns(self) -> None:
        selected = case(
            mutation=False,
            turns=(
                EvalTurn("Which lights are on?", {"action": "none"}),
                EvalTurn("Which of those support colour?", {"action": "none"}),
            ),
        )
        client = FakeClient(
            [
                {
                    "conversation_id": "conversation-1",
                    "provider": "home_assistant",
                    "response_text": "One light is on.",
                    "result": {"response": {"response_type": "query_answer"}},
                },
                {
                    "conversation_id": "conversation-1",
                    "provider": "pilot_llm",
                    "response_text": "That light supports colour.",
                    "tool_calls": [{"name": "read_home_entity", "output": {}}],
                },
            ]
        )
        results = run_suite([selected], client)
        self.assertEqual(client.calls[0]["conversation_id"], None)
        self.assertEqual(client.calls[1]["conversation_id"], "conversation-1")
        self.assertTrue(results[0]["passed"])

    def test_report_contains_aggregate_latency_provider_and_tool_counts(self) -> None:
        selected = case(
            mutation=False,
            turns=(EvalTurn("What is the weather?", {"action": "none"}),),
        )
        result = {
            "id": "sample",
            "category": "test",
            "status": "passed",
            "turns": [
                {
                    "latency_ms": 125.0,
                    "provider": "pilot_llm",
                    "tool_names": ["get_weather"],
                    "action_outcome": "none",
                }
            ],
        }
        report = build_report(
            [selected],
            [result],
            core_url="https://pilot.example.test",
            device_id="eval-device",
            allow_actions=False,
            corpus_path=DEFAULT_CORPUS,
            manifest={"features": {"portable": True, "home_control": False}},
        )
        self.assertEqual(report["summary"]["latency_ms"]["p50"], 125.0)
        self.assertEqual(report["summary"]["providers"], {"pilot_llm": 1})
        self.assertEqual(report["summary"]["tools"], {"get_weather": 1})
        self.assertEqual(report["summary"]["categories"], {"test": {"passed": 1}})
        self.assertFalse(report["safety"]["allow_actions"])


if __name__ == "__main__":
    unittest.main()
