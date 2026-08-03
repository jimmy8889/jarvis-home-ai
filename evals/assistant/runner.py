#!/usr/bin/env python3
"""Run a safety-gated corpus against Pilot's device assistant endpoint."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Callable, Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


SCHEMA_VERSION = "pilot.assistant-eval.v1"
CORPUS_SCHEMA_VERSION = "pilot.assistant-eval-case.v1"
DEFAULT_CORPUS = Path(__file__).with_name("corpus.v1.jsonl")
MUTATING_TOOLS = frozenset(
    {
        "control_home",
        "control_light",
        "control_media",
        "execute_home_action",
        "play_music",
    }
)
GROUNDING_TOOLS = frozenset(
    {
        "get_energy_snapshot",
        "get_home_area_summary",
        "get_meeting",
        "get_room_status",
        "get_temperature",
        "get_weather",
        "read_home_entity",
        "search_home_entities",
        "search_meetings",
        "search_music",
    }
)
ACTION_EXPECTATIONS = frozenset({"none", "not_executed", "succeeded"})


class CorpusError(ValueError):
    """The evaluation corpus is malformed or unsafe to interpret."""


class ClientError(RuntimeError):
    """Pilot Core rejected or could not complete an evaluation request."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class EvalTurn:
    text: str
    expect: dict[str, Any]


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    description: str
    room_id: str
    mutation: bool
    tags: tuple[str, ...]
    turns: tuple[EvalTurn, ...]


def _clean_string(value: Any, field: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CorpusError(f"{field} must be a non-empty string")
    selected = " ".join(value.split())
    if len(selected) > maximum:
        raise CorpusError(f"{field} exceeds {maximum} characters")
    return selected


def _string_list(value: Any, field: str, *, maximum: int = 30) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > maximum:
        raise CorpusError(f"{field} must be an array with at most {maximum} items")
    output: list[str] = []
    for index, item in enumerate(value):
        output.append(_clean_string(item, f"{field}[{index}]", maximum=100))
    return tuple(dict.fromkeys(output))


def _validate_expectation(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CorpusError(f"{field} must be an object")
    allowed = {
        "action",
        "grounded",
        "providers_any",
        "response_any",
        "tools_any",
        "tools_none",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CorpusError(f"{field} has unknown fields: {', '.join(unknown)}")
    result: dict[str, Any] = {}
    action = value.get("action", "none")
    if action not in ACTION_EXPECTATIONS:
        raise CorpusError(
            f"{field}.action must be one of {', '.join(sorted(ACTION_EXPECTATIONS))}"
        )
    result["action"] = action
    grounded = value.get("grounded")
    if grounded is not None and not isinstance(grounded, bool):
        raise CorpusError(f"{field}.grounded must be a boolean")
    if grounded is not None:
        result["grounded"] = grounded
    for key in ("providers_any", "response_any", "tools_any", "tools_none"):
        selected = _string_list(value.get(key), f"{field}.{key}")
        if selected:
            result[key] = list(selected)
    return result


def parse_case(value: Any, *, line_number: int) -> EvalCase:
    field = f"line {line_number}"
    if not isinstance(value, dict):
        raise CorpusError(f"{field} must contain a JSON object")
    if value.get("schema_version") != CORPUS_SCHEMA_VERSION:
        raise CorpusError(f"{field} has an unsupported schema_version")
    mutation = value.get("mutation")
    if not isinstance(mutation, bool):
        raise CorpusError(f"{field}.mutation must be a boolean")
    raw_turns = value.get("turns")
    if not isinstance(raw_turns, list) or not 1 <= len(raw_turns) <= 8:
        raise CorpusError(f"{field}.turns must contain between 1 and 8 turns")
    turns: list[EvalTurn] = []
    for index, raw_turn in enumerate(raw_turns):
        if not isinstance(raw_turn, dict):
            raise CorpusError(f"{field}.turns[{index}] must be an object")
        unknown = sorted(set(raw_turn) - {"text", "expect"})
        if unknown:
            raise CorpusError(
                f"{field}.turns[{index}] has unknown fields: {', '.join(unknown)}"
            )
        turns.append(
            EvalTurn(
                text=_clean_string(
                    raw_turn.get("text"),
                    f"{field}.turns[{index}].text",
                    maximum=1000,
                ),
                expect=_validate_expectation(
                    raw_turn.get("expect", {}),
                    f"{field}.turns[{index}].expect",
                ),
            )
        )
    return EvalCase(
        id=_clean_string(value.get("id"), f"{field}.id", maximum=100),
        category=_clean_string(
            value.get("category"), f"{field}.category", maximum=80
        ),
        description=_clean_string(
            value.get("description"), f"{field}.description", maximum=300
        ),
        room_id=_clean_string(
            value.get("room_id"), f"{field}.room_id", maximum=128
        ),
        mutation=mutation,
        tags=_string_list(value.get("tags", []), f"{field}.tags"),
        turns=tuple(turns),
    )


def load_corpus(path: Path | str = DEFAULT_CORPUS) -> list[EvalCase]:
    source = Path(path)
    cases: list[EvalCase] = []
    seen: set[str] = set()
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise CorpusError(f"could not read corpus: {error}") from error
    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise CorpusError(f"line {line_number} is invalid JSON: {error.msg}") from error
        case = parse_case(value, line_number=line_number)
        if case.id in seen:
            raise CorpusError(f"duplicate case id: {case.id}")
        cases.append(case)
        seen.add(case.id)
    if not cases:
        raise CorpusError("corpus contains no cases")
    return cases


def _safe_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Pilot Core URL must be an http(s) origin without credentials")
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


class AssistantClient:
    """Small device-authenticated client with no administrator credential support."""

    def __init__(
        self,
        base_url: str,
        device_id: str,
        token: str,
        *,
        timeout_seconds: float = 30,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.base_url = _safe_base_url(base_url)
        self.device_id = _clean_string(device_id, "device_id", maximum=128)
        if not token.strip():
            raise ValueError("device token is empty")
        if not 1 <= timeout_seconds <= 300:
            raise ValueError("timeout must be between 1 and 300 seconds")
        self._token = token.strip()
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    @property
    def _device_path(self) -> str:
        return f"/v1/devices/{quote(self.device_id, safe='')}"

    def _request(self, path: str, *, payload: dict[str, Any] | None = None) -> Any:
        body = (
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
            if payload is not None
            else None
        )
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "X-Pilot-Device-ID": self.device_id,
                "User-Agent": "pilot-assistant-eval/1",
            },
            method="POST" if body is not None else "GET",
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                value = json.load(response)
        except HTTPError as error:
            detail = ""
            try:
                body_value = json.loads(error.read().decode("utf-8", errors="replace"))
                detail = str(body_value.get("detail") or "")[:300]
            except (OSError, ValueError, AttributeError):
                detail = ""
            raise ClientError(
                f"Pilot Core returned HTTP {error.code}"
                + (f": {detail}" if detail else ""),
                status_code=error.code,
            ) from None
        except (OSError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ClientError(f"Pilot Core request failed: {error}") from error
        if not isinstance(value, dict):
            raise ClientError("Pilot Core returned a non-object response")
        return value

    def manifest(self) -> dict[str, Any]:
        return self._request(f"{self._device_path}/manifest")

    def respond(
        self,
        text: str,
        room_id: str,
        conversation_id: str | None,
        *,
        language: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "text": text,
            "room_id": room_id,
            "language": language,
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id
        return self._request(f"{self._device_path}/assistant", payload=payload)


def _tool_calls(body: dict[str, Any]) -> list[dict[str, Any]]:
    value = body.get("tool_calls")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _ha_response_type(body: dict[str, Any]) -> str:
    result = body.get("result")
    response = result.get("response") if isinstance(result, dict) else None
    value = response.get("response_type") if isinstance(response, dict) else None
    return str(value or "")[:80]


def response_signals(body: dict[str, Any]) -> dict[str, Any]:
    calls = _tool_calls(body)
    tool_names = [str(call.get("name") or "unknown")[:100] for call in calls]
    mutating_calls = [
        call
        for call in calls
        if str(call.get("name") or "") in MUTATING_TOOLS
    ]
    action_outcome = "none"
    if _ha_response_type(body) == "action_done":
        action_outcome = "succeeded"
    for call in mutating_calls:
        output = call.get("output")
        if not isinstance(output, dict):
            action_outcome = "attempted"
            continue
        status = str(output.get("status") or "").casefold()
        if status == "confirmation_required":
            action_outcome = "confirmation_required"
        elif output.get("success") is True or status in {"succeeded", "unverified"}:
            action_outcome = "succeeded"
            break
        elif status == "failed":
            action_outcome = "failed"
        elif output.get("success") is False or output.get("error"):
            action_outcome = "blocked"
        else:
            action_outcome = "attempted"
    if not mutating_calls and action_outcome == "none":
        raw_actions = body.get("actions")
        if isinstance(raw_actions, list):
            for item in raw_actions:
                if not isinstance(item, dict) or item.get("name") not in MUTATING_TOOLS:
                    continue
                status = str(item.get("status") or "").casefold()
                action_outcome = (
                    "succeeded"
                    if status == "succeeded"
                    else "failed"
                    if status == "failed"
                    else "attempted"
                )
    grounded = _ha_response_type(body) in {"action_done", "query_answer"} or any(
        name in GROUNDING_TOOLS for name in tool_names
    )
    response_text = str(body.get("response_text") or "").strip()
    return {
        "provider": str(body.get("provider") or "unknown")[:100],
        "response_text": response_text,
        "response_excerpt": response_text[:400],
        "tool_names": tool_names,
        "tool_count": len(tool_names),
        "action_outcome": action_outcome,
        "action_attempted": bool(mutating_calls) or _ha_response_type(body) == "action_done",
        "grounded": grounded,
        "continue_conversation": body.get("continue_conversation") is True,
        "ha_response_type": _ha_response_type(body) or None,
    }


def evaluate_response(body: dict[str, Any], expect: dict[str, Any]) -> dict[str, Any]:
    signals = response_signals(body)
    checks: list[dict[str, Any]] = []

    def check(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"id": check_id, "passed": bool(passed), "detail": detail[:300]})

    providers = expect.get("providers_any") or []
    if providers:
        check(
            "provider",
            signals["provider"] in providers,
            f"provider={signals['provider']}; expected one of {', '.join(providers)}",
        )
    expected_action = str(expect.get("action") or "none")
    outcome = signals["action_outcome"]
    if expected_action == "none":
        action_passed = outcome == "none"
    elif expected_action == "not_executed":
        action_passed = outcome in {"none", "blocked", "confirmation_required"}
    else:
        action_passed = outcome == "succeeded"
    check(
        "action",
        action_passed,
        f"action_outcome={outcome}; expected={expected_action}",
    )
    if "grounded" in expect:
        expected_grounded = expect["grounded"] is True
        check(
            "grounding",
            signals["grounded"] is expected_grounded,
            f"grounded={str(signals['grounded']).lower()}",
        )
    required_tools = expect.get("tools_any") or []
    if required_tools:
        check(
            "tools-any",
            any(name in signals["tool_names"] for name in required_tools),
            "tools=" + ", ".join(signals["tool_names"] or ["none"]),
        )
    forbidden_tools = expect.get("tools_none") or []
    if forbidden_tools:
        found = sorted(set(forbidden_tools) & set(signals["tool_names"]))
        check(
            "tools-none",
            not found,
            "forbidden tools used: " + (", ".join(found) if found else "none"),
        )
    response_terms = [str(item).casefold() for item in expect.get("response_any") or []]
    if response_terms:
        folded = signals["response_text"].casefold()
        check(
            "response-any",
            any(term in folded for term in response_terms),
            "expected response to contain one of: " + ", ".join(response_terms),
        )
    return {
        **{key: value for key, value in signals.items() if key != "response_text"},
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
    }


def run_case(
    case: EvalCase,
    client: Any,
    *,
    allow_actions: bool,
    language: str,
) -> dict[str, Any]:
    if case.mutation and not allow_actions:
        return {
            "id": case.id,
            "category": case.category,
            "description": case.description,
            "room_id": case.room_id,
            "mutation": True,
            "status": "skipped",
            "passed": None,
            "skip_reason": "mutation case requires --allow-actions",
            "turns": [],
            "latency_ms": 0,
        }
    started = time.perf_counter()
    conversation_id: str | None = None
    turns: list[dict[str, Any]] = []
    for index, turn in enumerate(case.turns, 1):
        turn_started = time.perf_counter()
        try:
            body = client.respond(
                turn.text,
                case.room_id,
                conversation_id,
                language=language,
            )
            latency_ms = round((time.perf_counter() - turn_started) * 1000, 1)
            evaluation = evaluate_response(body, turn.expect)
            raw_conversation_id = body.get("conversation_id")
            if isinstance(raw_conversation_id, str) and raw_conversation_id:
                conversation_id = raw_conversation_id
            turns.append(
                {
                    "index": index,
                    "prompt": turn.text,
                    "latency_ms": latency_ms,
                    "status": "passed" if evaluation["passed"] else "failed",
                    **evaluation,
                }
            )
        except ClientError as error:
            latency_ms = round((time.perf_counter() - turn_started) * 1000, 1)
            turns.append(
                {
                    "index": index,
                    "prompt": turn.text,
                    "latency_ms": latency_ms,
                    "status": "error",
                    "passed": False,
                    "status_code": error.status_code,
                    "error": str(error)[:500],
                    "provider": None,
                    "tool_names": [],
                    "tool_count": 0,
                    "action_outcome": "unknown",
                    "action_attempted": False,
                    "grounded": False,
                    "checks": [],
                }
            )
            break
    passed = len(turns) == len(case.turns) and all(turn["passed"] for turn in turns)
    return {
        "id": case.id,
        "category": case.category,
        "description": case.description,
        "room_id": case.room_id,
        "mutation": case.mutation,
        "status": "passed" if passed else "failed",
        "passed": passed,
        "turns": turns,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def run_suite(
    cases: Sequence[EvalCase],
    client: Any,
    *,
    allow_actions: bool = False,
    language: str = "en-AU",
) -> list[dict[str, Any]]:
    return [
        run_case(case, client, allow_actions=allow_actions, language=language)
        for case in cases
    ]


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 1)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 1)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 1)


def build_report(
    cases: Sequence[EvalCase],
    results: Sequence[dict[str, Any]],
    *,
    core_url: str,
    device_id: str,
    allow_actions: bool,
    corpus_path: Path,
    manifest: dict[str, Any] | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    turn_results = [
        turn
        for case in results
        for turn in case.get("turns", [])
        if turn.get("status") != "skipped"
    ]
    latencies = [
        float(turn["latency_ms"])
        for turn in turn_results
        if isinstance(turn.get("latency_ms"), (int, float))
    ]
    providers = Counter(
        str(turn["provider"])
        for turn in turn_results
        if isinstance(turn.get("provider"), str) and turn["provider"]
    )
    tools = Counter(
        tool
        for turn in turn_results
        for tool in turn.get("tool_names", [])
        if isinstance(tool, str)
    )
    actions = Counter(
        str(turn.get("action_outcome") or "unknown") for turn in turn_results
    )
    statuses = Counter(str(item.get("status") or "unknown") for item in results)
    category_summary: dict[str, Counter[str]] = {}
    for item in results:
        category = str(item.get("category") or "unknown")
        category_summary.setdefault(category, Counter())[str(item.get("status") or "unknown")] += 1
    features = manifest.get("features", {}) if isinstance(manifest, dict) else {}
    try:
        corpus_hash = sha256(corpus_path.read_bytes()).hexdigest()
    except OSError:
        corpus_hash = "unavailable"
    return {
        "schema_version": SCHEMA_VERSION,
        "started_at": started_at or datetime.now(UTC).isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "target": {
            "core_url": _safe_base_url(core_url),
            "device_id": device_id,
            "portable": features.get("portable"),
            "home_control": features.get("home_control"),
        },
        "safety": {
            "allow_actions": allow_actions,
            "mutation_cases_skipped_by_default": not allow_actions,
            "administrator_credentials_used": False,
        },
        "corpus": {
            "path": str(corpus_path),
            "sha256": corpus_hash,
            "case_count": len(cases),
        },
        "summary": {
            "passed": statuses["passed"],
            "failed": statuses["failed"],
            "skipped": statuses["skipped"],
            "turn_count": len(turn_results),
            "providers": dict(sorted(providers.items())),
            "tools": dict(sorted(tools.items())),
            "action_outcomes": dict(sorted(actions.items())),
            "categories": {
                category: dict(sorted(counts.items()))
                for category, counts in sorted(category_summary.items())
            },
            "latency_ms": {
                "mean": round(statistics.fmean(latencies), 1) if latencies else None,
                "p50": _percentile(latencies, 0.50),
                "p95": _percentile(latencies, 0.95),
                "max": round(max(latencies), 1) if latencies else None,
            },
        },
        "cases": list(results),
    }


def select_cases(
    cases: Sequence[EvalCase],
    *,
    case_ids: Iterable[str] = (),
    categories: Iterable[str] = (),
    tags: Iterable[str] = (),
) -> list[EvalCase]:
    selected_ids = set(case_ids)
    selected_categories = set(categories)
    selected_tags = set(tags)
    selected = [
        case
        for case in cases
        if (not selected_ids or case.id in selected_ids)
        and (not selected_categories or case.category in selected_categories)
        and (not selected_tags or selected_tags.intersection(case.tags))
    ]
    missing = selected_ids - {case.id for case in cases}
    if missing:
        raise CorpusError("unknown case ids: " + ", ".join(sorted(missing)))
    if not selected:
        raise CorpusError("case filters selected no evaluations")
    return selected


def _credential(direct_name: str, file_name: str) -> str:
    direct = os.environ.get(direct_name, "").strip()
    if direct:
        return direct
    path = os.environ.get(file_name, "").strip()
    if not path:
        raise ValueError(f"set {direct_name} or {file_name}")
    value = Path(path).read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"{file_name} points to an empty file")
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate Pilot's device-scoped assistant. Mutation cases are skipped "
            "unless --allow-actions is explicitly supplied."
        )
    )
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--case", action="append", default=[], dest="case_ids")
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--allow-actions", action="store_true")
    parser.add_argument("--language", default="en-AU")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--list", action="store_true", dest="list_cases")
    return parser.parse_args(argv)


def _console(report: dict[str, Any]) -> None:
    summary = report["summary"]
    latency = summary["latency_ms"]
    mode = "ACTIONS ENABLED" if report["safety"]["allow_actions"] else "read-only corpus"
    print(
        "Pilot assistant evaluation: "
        f"{summary['passed']} passed, {summary['failed']} failed, "
        f"{summary['skipped']} skipped ({mode})"
    )
    print(
        f"Latency: p50={latency['p50']} ms, p95={latency['p95']} ms, "
        f"max={latency['max']} ms"
    )
    for case in report["cases"]:
        marker = {"passed": "PASS", "failed": "FAIL", "skipped": "SKIP"}.get(
            case["status"], "????"
        )
        detail = case.get("skip_reason") or ""
        if case.get("turns"):
            last = case["turns"][-1]
            detail = (
                f"provider={last.get('provider') or 'none'} "
                f"action={last.get('action_outcome') or 'none'} "
                f"latency={last.get('latency_ms')}ms"
            )
        print(f"[{marker}] {case['id']}: {detail}")
        if case["status"] == "failed":
            for turn in case.get("turns", []):
                for check in turn.get("checks", []):
                    if not check["passed"]:
                        print(f"       {check['id']}: {check['detail']}")
                if turn.get("error"):
                    print(f"       error: {turn['error']}")


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        cases = load_corpus(args.corpus)
        selected = select_cases(
            cases,
            case_ids=args.case_ids,
            categories=args.category,
            tags=args.tag,
        )
        if args.list_cases:
            for case in selected:
                mode = "mutation" if case.mutation else "read-only"
                print(f"{case.id}\t{case.category}\t{mode}\t{case.description}")
            return 0
        base_url = os.environ.get(
            "PILOT_EVAL_CORE_URL",
            os.environ.get("PILOT_CORE_URL", "https://pilot.jameshomeautomation.work"),
        )
        device_id = os.environ.get(
            "PILOT_EVAL_DEVICE_ID", os.environ.get("PILOT_DEVICE_ID", "")
        )
        token = _credential(
            "PILOT_EVAL_DEVICE_TOKEN",
            "PILOT_EVAL_DEVICE_TOKEN_FILE",
        )
        client = AssistantClient(
            base_url,
            device_id,
            token,
            timeout_seconds=args.timeout,
        )
        manifest = client.manifest()
        features = manifest.get("features") if isinstance(manifest, dict) else None
        if not isinstance(features, dict) or features.get("assistant") is not True:
            raise ValueError("evaluation device is not authorized for the assistant")
        if args.allow_actions and features.get("home_control") is not True:
            raise ValueError(
                "--allow-actions requires an evaluation device with home-control"
            )
        started_at = datetime.now(UTC).isoformat()
        results = run_suite(
            selected,
            client,
            allow_actions=args.allow_actions,
            language=args.language,
        )
        report = build_report(
            selected,
            results,
            core_url=base_url,
            device_id=device_id,
            allow_actions=args.allow_actions,
            corpus_path=args.corpus,
            manifest=manifest,
            started_at=started_at,
        )
    except (ClientError, CorpusError, OSError, ValueError) as error:
        print(f"Pilot assistant evaluation failed: {error}", file=sys.stderr)
        return 2

    if args.output:
        try:
            _write_report(args.output, report)
        except OSError as error:
            print(f"Could not write evaluation report: {error}", file=sys.stderr)
            return 2
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _console(report)
        if args.output:
            print(f"JSON report: {args.output}")
    return 1 if report["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
