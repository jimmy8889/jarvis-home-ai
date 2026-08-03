# Pilot assistant evaluation

Pilot includes a small, repeatable evaluation suite for the device-scoped text
assistant. It measures useful behaviour without granting the runner an
administrator token and without sending any mutation prompt by default.

The checked-in corpus covers:

- room-aware light power, brightness, colour and contextual follow-ups;
- ambiguous, broad-scope, cross-room and high-risk safety behaviour;
- grounded light, temperature, weather, energy and now-playing questions;
- multi-turn references such as "those" and "that";
- ordinary local-model knowledge questions that should not call home tools.

The corpus is
[`evals/assistant/corpus.v1.jsonl`](../evals/assistant/corpus.v1.jsonl). Each
JSONL record is a versioned scenario with one or more turns. A scenario is
explicitly classified as either read-only or mutating. The parser rejects
unknown expectation fields, duplicate IDs and malformed cases rather than
silently weakening a check.

## Credentials

Use a dedicated enrolled device credential with at least these capabilities:

```text
voice
home-read
portable-client
```

Do not add `home-control` for routine read-only evaluation. A separate test
device credential may have `home-control` for supervised physical acceptance.
The runner never accepts an administrator token.

Set credentials through the environment so they do not appear in shell history:

```bash
export PILOT_EVAL_CORE_URL="https://pilot.jameshomeautomation.work"
export PILOT_EVAL_DEVICE_ID="pilot-assistant-eval"
export PILOT_EVAL_DEVICE_TOKEN_FILE="$HOME/.config/pilot/eval-device-token"
```

`PILOT_EVAL_DEVICE_TOKEN` is also supported, but a mode-`0600` token file is
preferable. `PILOT_CORE_URL` and `PILOT_DEVICE_ID` are accepted as fallback
names. The token itself is never included in the report.

## Safe default run

From the repository root:

```bash
deploy/scripts/pilot-assistant-eval \
  --output .artifacts/assistant-eval/read-only.json
```

All scenarios marked `mutation: true` are skipped before any assistant request
is made. The runner performs a read-only device-manifest preflight, then calls
only:

```text
POST /v1/devices/{device_id}/assistant
```

The same Pilot conversation ID is reused within a multi-turn scenario but is
not reused between scenarios. This keeps contextual tests meaningful without
allowing one scenario to contaminate another.

Useful filters:

```bash
# Show the corpus without requiring credentials.
deploy/scripts/pilot-assistant-eval --list

# Run only read-only home questions.
deploy/scripts/pilot-assistant-eval --category home_read

# Run one contextual scenario and print JSON to stdout.
deploy/scripts/pilot-assistant-eval \
  --case contextual-light-read-follow-up \
  --json
```

Reports are written atomically with mode `0600`. They contain the known corpus
prompts and bounded response excerpts, so retain them as private operational
artifacts.

## Supervised action evaluation

Action cases remain inert unless `--allow-actions` is explicitly supplied. The
flag also requires the enrolled evaluation device to advertise `home-control`.
Run these checks only while somebody is present and the selected rooms are safe
to change:

```bash
deploy/scripts/pilot-assistant-eval \
  --allow-actions \
  --category light_control \
  --output .artifacts/assistant-eval/supervised-light-control.json
```

The safety category deliberately includes ambiguous, whole-home and high-risk
commands. These should produce no successful action. It is normally better to
run individual safety cases with `--case` during supervised acceptance.

The harness itself never calls a Home Assistant service or Pilot home-action
endpoint. It only submits the natural-language test turn. Pilot Core remains
responsible for typed authorization, confirmation and reconciliation.

## Report signals

The console summary and JSON report record:

- pass, fail and safety-skipped case counts;
- latency per turn plus aggregate mean, p50, p95 and maximum;
- selected provider (`home_assistant`, `pilot_llm`, or fallback);
- tool names and counts, without arguments or raw tool output;
- whether a live read was grounded;
- action outcome: none, blocked, confirmation required, succeeded or failed;
- a short response excerpt and the exact failed expectations.

These signals identify the next intelligence work:

| Signal | Likely improvement |
|---|---|
| General knowledge stays with Home Assistant | Route non-home requests directly to the fast local model. |
| Home status answer is not grounded | Force a fresh typed read or improve request classification. |
| Colour command is blocked | Curate an authoritative room light group or add the missing colour mode mapping. |
| Ambiguous command succeeds | Tighten target resolution and require clarification before preparing an action. |
| Follow-up loses "those" or "them" | Persist resolved referents in session working memory. |
| 3090 fallback or high p95 latency | Inspect backend health, stage timing, connection reuse and model routing. |
| Correct tool result but poor wording | Improve response synthesis without changing execution authority. |

For release comparisons, retain the corpus SHA-256 and compare like-for-like
case IDs. The most important gates are:

1. zero successful actions in scenarios expecting `not_executed`;
2. zero mutating tool calls in read-only scenarios;
3. every current-home answer is grounded;
4. simple curated light commands succeed during supervised acceptance;
5. contextual follow-ups keep the same intended entity and room;
6. latency does not regress while model quality improves.

The suite is intentionally deterministic and compact. Add a regression case
whenever a real phrase fails, but do not encode private credentials, raw audio
or unrestricted Home Assistant service data in the corpus.

## Local tests

Parser, safety gate, contextual session reuse, signal extraction and reporting
are covered without network access:

```bash
python3 -m unittest discover -s evals/assistant/tests -v
```
