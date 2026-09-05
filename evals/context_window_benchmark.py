#!/usr/bin/env python3
"""Measure a configured context window with a long-context retrieval probe."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--model", default="primary")
    parser.add_argument("--context-size", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args()

    # This uses a deliberately conservative 75% requested fill. The API usage
    # record below is the authoritative prompt-token count for each model build.
    filler_count = (args.context_size * 3) // 4
    needle = f"CONTEXT-WINDOW-{args.context_size}-RETRIEVAL"
    before = " the" * (filler_count // 2)
    after = " the" * (filler_count - filler_count // 2)
    prompt = (
        "Read the supplied context exactly. "
        + before
        + f"\n\nImportant retrieval marker: {needle}\n\n"
        + after
        + "\n\nWhat is the exact retrieval marker? Reply with only that marker."
    )
    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 32,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    started = time.perf_counter()
    first_token_ms: float | None = None
    text: list[str] = []
    usage: dict[str, object] | None = None
    try:
        request = Request(
            args.url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        )
        with urlopen(request, timeout=args.timeout) as response:
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
                        text.append(delta["content"])
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        content = "".join(text).strip()
        completion_tokens = (usage or {}).get("completion_tokens")
        generation_ms = elapsed_ms - (first_token_ms or elapsed_ms)
        tokens_per_second = None
        if isinstance(completion_tokens, int) and generation_ms > 0:
            tokens_per_second = round(completion_tokens / (generation_ms / 1000), 2)
        result: dict[str, object] = {
            "configured_context_tokens": args.context_size,
            "requested_filler_units": filler_count,
            "prompt_tokens": (usage or {}).get("prompt_tokens"),
            "completion_tokens": completion_tokens,
            "ttft_ms": first_token_ms,
            "elapsed_ms": elapsed_ms,
            "tokens_per_second": tokens_per_second,
            "retrieval_marker": needle,
            "response": content,
            "retrieval_pass": needle in content,
        }
    except Exception as error:
        result = {"configured_context_tokens": args.context_size, "error": str(error)[:1000]}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0 if result.get("retrieval_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
