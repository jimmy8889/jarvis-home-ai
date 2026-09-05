#!/usr/bin/env python3
"""Repeatable, dependency-free chat and Hermes-oriented local model evaluation."""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a repository file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run a focused test command in the repository.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
]


@dataclass(frozen=True)
class Case:
    id: str
    messages: list[dict[str, Any]]
    expected_tool: str | None = None


CASES = (
    Case("reasoning", [{"role": "user", "content": "A battery has 13.5 kWh usable. It is at 40% and must reach 90%. How many kWh must it gain? Show the arithmetic."}]),
    Case("writing", [{"role": "user", "content": "Write a concise release note for a bug fix that prevents duplicate notifications after reconnecting to a local server."}]),
    Case("multi_turn", [
        {"role": "user", "content": "Remember this code-review constraint: do not change public API names."},
        {"role": "assistant", "content": "I will preserve public API names."},
        {"role": "user", "content": "What constraint must the refactor preserve?"},
    ]),
    Case("repo_comprehension", [{"role": "user", "content": "Given `def total(items): return sum(item.price for item in items)`, explain one likely failure mode and propose a minimal test."}]),
    Case("code_change_plan", [{"role": "user", "content": "Plan a small, reversible change to add a 10-second timeout to an HTTP call. Include the implementation and one regression test."}]),
    Case("tool_selection", [{"role": "user", "content": "Before proposing an edit, inspect src/config.py to find the timeout setting."}], "read_file"),
    Case("tool_command", [{"role": "user", "content": "Run the focused unit tests for the config timeout change before saying it is complete."}], "run_tests"),
    Case("tool_failure_recovery", [
        {"role": "user", "content": "Run tests for the timeout change."},
        {"role": "assistant", "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "run_tests", "arguments": "{\"command\":\"pytest tests/test_config.py\"}"}}]},
        {"role": "tool", "tool_call_id": "call-1", "content": "Command failed: tests/test_config.py does not exist."},
        {"role": "user", "content": "Recover safely: inspect the repository before choosing a replacement command."},
    ], "read_file"),
)


def stream_request(endpoint: str, token: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(endpoint.rstrip("/") + "/chat/completions", data=json.dumps(payload).encode(), headers=headers)
    started = time.perf_counter()
    first_token_ms: float | None = None
    parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    usage: dict[str, Any] | None = None
    with urlopen(request, timeout=timeout) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            event = json.loads(data)
            if first_token_ms is None:
                first_token_ms = round((time.perf_counter() - started) * 1000, 1)
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
            for choice in event.get("choices") or []:
                delta = choice.get("delta") or {}
                if isinstance(delta.get("content"), str):
                    parts.append(delta["content"])
                for item in delta.get("tool_calls") or []:
                    index = item.get("index", len(tool_calls))
                    while len(tool_calls) <= index:
                        tool_calls.append({"function": {"name": "", "arguments": ""}})
                    target = tool_calls[index]
                    if item.get("id"):
                        target["id"] = item["id"]
                    function = item.get("function") or {}
                    target_function = target.setdefault("function", {})
                    target_function["name"] = target_function.get("name", "") + function.get("name", "")
                    target_function["arguments"] = target_function.get("arguments", "") + function.get("arguments", "")
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    completion_tokens = (usage or {}).get("completion_tokens")
    generation_ms = elapsed_ms - (first_token_ms or elapsed_ms)
    tokens_per_second = None
    if isinstance(completion_tokens, int) and generation_ms > 0:
        tokens_per_second = round(completion_tokens / (generation_ms / 1000), 2)
    return {
        "elapsed_ms": elapsed_ms,
        "ttft_ms": first_token_ms,
        "tokens_per_second": tokens_per_second,
        "usage": usage,
        "content": "".join(parts),
        "tool_calls": tool_calls,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="OpenAI-compatible /v1 endpoint")
    parser.add_argument("--model", required=True, help="Explicit profile ID used in result metadata")
    parser.add_argument("--token", default=os.environ.get("PILOT_LLM_TOKEN", ""))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--no-thinking", action="store_true")
    args = parser.parse_args()

    records = []
    for case in CASES:
        payload: dict[str, Any] = {
            "model": args.model,
            "messages": case.messages,
            "tools": TOOLS,
            "temperature": 0.2,
            "max_tokens": args.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if args.no_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        try:
            result = stream_request(args.url, args.token, payload, args.timeout)
            tool_names = [call.get("function", {}).get("name") for call in result["tool_calls"]]
            result.update({
                "case": case.id,
                "expected_tool": case.expected_tool,
                "tool_valid": case.expected_tool is None or case.expected_tool in tool_names,
                "content_chars": len(result.pop("content")),
            })
            records.append(result)
        except Exception as error:
            records.append({"case": case.id, "expected_tool": case.expected_tool, "error": str(error)[:500]})

    successful = sum(1 for record in records if "error" not in record and record.get("tool_valid", False))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"model": args.model, "endpoint": args.url, "cases": records}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"model": args.model, "cases": len(records), "successful": successful, "output": str(args.output)}))
    return 0 if successful == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
