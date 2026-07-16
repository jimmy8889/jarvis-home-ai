# ADR-005: Separate world state, knowledge, memory, planning, and execution

- Status: Proposed
- Date: 2026-07-16

## Context

A capable personal assistant needs live environmental state, durable knowledge, personal memory, plans, and action execution. Combining all of these into an LLM context or one vector database would produce stale state, weak provenance, unsafe actions, and difficult deletion semantics.

## Decision

Pilot will implement five distinct but connected responsibilities:

1. **World model** — live and recently observed state.
2. **Knowledge graph/search** — durable entities, relationships, and evidence retrieval.
3. **Memory service** — governed personal and conversational retention.
4. **Planning engine** — persistent goals, milestones, and proposed actions.
5. **Skill runtime** — policy-enforced execution against real systems.

The event bus synchronises changes between these services. The LLM can query filtered views and propose plans, but it is not the source of truth and cannot execute infrastructure actions directly.

## Consequences

### Positive

- Clear safety boundaries.
- Better provenance and explainability.
- Correct retention and deletion behaviour.
- Deterministic live-state queries.
- Replaceable storage and model implementations.

### Negative

- More services and schemas.
- Eventual consistency between derived views.
- Additional integration and observability work.

## Implementation guidance

Begin as modules within Pilot Core where operationally simpler. Preserve API and event boundaries so high-load services can later be separated without redesigning the contracts.
