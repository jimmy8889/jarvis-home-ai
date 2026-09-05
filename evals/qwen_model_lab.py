#!/usr/bin/env python3
"""Small, dependency-free benchmark harness for the approved Qwen candidates.

The harness intentionally talks to an already-running OpenAI-compatible endpoint.
It never starts, stops, or replaces a production model. Use a separate vLLM
profile or an approved temporary runner for each candidate.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


CASES = (
    ("home_read", "What is the current battery state and house load?"),
    ("room_context", "Turn on the office lights, then tell me what is playing here."),
    ("energy_reasoning", "Why might the battery be charging while solar is producing power?"),
    ("vehicle", "How much energy does the Tesla need to reach its charge limit?"),
    ("deep_work", "Create a concise plan to improve the home's energy use this week."),
)


def request(endpoint: str, token: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(endpoint.rstrip("/") + "/chat/completions", data=body, headers=headers)
    started = time.perf_counter()
    with urlopen(req, timeout=timeout) as response:
        result = json.load(response)
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="OpenAI-compatible /v1 endpoint")
    parser.add_argument("--model", required=True)
    parser.add_argument("--token", default=os.environ.get("PILOT_LLM_TOKEN", ""))
    parser.add_argument("--output", type=Path, default=Path(".artifacts/qwen-model-lab.json"))
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument(
        "--no-thinking",
        action="store_true",
        help="Request Qwen chat templates to skip hidden reasoning for latency tests",
    )
    args = parser.parse_args()

    records: list[dict[str, Any]] = []
    for case_id, prompt in CASES:
        try:
            payload = {
                "model": args.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": args.max_tokens,
            }
            if args.no_thinking:
                payload["chat_template_kwargs"] = {"enable_thinking": False}
            result = request(
                args.url,
                args.token,
                payload,
                args.timeout,
            )
            choice = (result.get("choices") or [{}])[0]
            message = choice.get("message") if isinstance(choice, dict) else {}
            records.append(
                {
                    "case": case_id,
                    "prompt": prompt,
                    "elapsed_ms": result.get("elapsed_ms"),
                    "response": (
                        message.get("content") or message.get("reasoning_content")
                        if isinstance(message, dict)
                        else None
                    ),
                    "finish_reason": choice.get("finish_reason") if isinstance(choice, dict) else None,
                    "usage": result.get("usage"),
                }
            )
        except Exception as error:  # benchmark output should include failures
            records.append({"case": case_id, "prompt": prompt, "error": str(error)[:500]})

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "model": args.model,
                "endpoint": args.url,
                "cases": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    failures = sum(1 for record in records if "error" in record)
    print(json.dumps({"model": args.model, "cases": len(records), "failures": failures}))
    return 1 if failures == len(records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
