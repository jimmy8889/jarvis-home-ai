# ADR-002: Layered Memory with Provenance and Retention

Status: Proposed

## Context

Pilot needs context for conversations, rooms, meetings, preferences, and home topology. A single undifferentiated vector store would mix temporary context with durable personal data and make correction or deletion difficult.

## Decision

Use separate memory scopes:

- turn
- session
- daily context
- durable user preference
- environment/topology
- episodic meeting and assistant history

Each memory record includes source, confidence, timestamps, retention, sensitivity, and deletion state.

```json
{
  "scope": "durable_user",
  "key": "preferred_office_music_output",
  "value": "office_n150",
  "source": "explicit_user_statement",
  "confidence": 1.0,
  "expires_at": null,
  "sensitive": false
}
```

Only explicit statements or high-confidence repeated behaviour may enter durable user memory. Inferences must be labelled as inferred and remain easy to inspect and delete.

## Consequences

- Better privacy and correction controls.
- More accurate context retrieval.
- Clear retention boundaries.
- Requires multiple storage and retrieval policies rather than one generic history table.

## Alternatives considered

- Store all conversation history indefinitely: rejected for privacy and retrieval quality.
- Keep no durable memory: rejected because it prevents useful personalisation and meeting recall.

## Security and privacy impact

Memory APIs must support inspect, export, delete, forget, and retention configuration. Sensitive data should be encrypted at rest where practical.

## Operational impact

Retrieval traces must identify which memory records influenced an answer.
