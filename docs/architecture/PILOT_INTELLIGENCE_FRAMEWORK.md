# Pilot Intelligence Framework

Version 0.5 proposal

## Objective

This framework extends Pilot from a reliable local voice and media platform into a governed personal intelligence system. It adds live environmental understanding, durable relationships, persistent projects, user identity, unified search, and event-driven coordination without allowing an LLM to become the source of truth or bypass safety controls.

## Architecture

```text
Room agents · macOS · iOS · Shield · integrations
                         │
                    Event Bus
                         │
        ┌────────────────┼────────────────┐
        │                │                │
   World Model      Knowledge/Search   Memory
        │                │                │
        └──────────── Context API ────────┘
                         │
                Conversation Router
                         │
                 Planning Engine
                         │
               Execution Policy
                         │
                   Skill Runtime
                         │
 Home Assistant · Music Assistant · Denon · Shield · GitHub
```

## Core boundaries

- **World model:** live state and recent observations.
- **Knowledge/search:** durable entities, relationships, and evidence.
- **Memory:** governed personal and conversational retention.
- **Planning:** projects, milestones, dependencies, and proposed actions.
- **Execution:** permissioned tools operating on real systems.
- **Event bus:** versioned change propagation and tracing.
- **Identity:** authenticated clients, optional voice profiles, and least privilege.

## First implementation slice

The first useful slice should avoid premature microservices:

1. Add a versioned event envelope package.
2. Emit room-agent health and player-state events.
3. Materialise a small world model inside Pilot Core.
4. Add deterministic queries for room presence, player choice, and capabilities.
5. Add persistent projects and tasks for the Pilot roadmap.
6. Index Pilot documentation, ADRs, GitHub issues, and meeting transcripts.
7. Add a privacy view for facts, memories, plans, and tool activity.

These may begin as modules in Pilot Core while preserving service boundaries.

## Acceptance journey

A successful v0.5 demonstration:

> “What should I work on next for Pilot?”

Pilot should:

1. Authenticate the requesting client.
2. Query active projects and GitHub issue state.
3. Read current room and system capabilities.
4. Identify blocking dependencies.
5. Return the highest-value next action with supporting evidence.
6. Offer—but not execute—an implementation workflow.

A second demonstration:

> “Move the music to whichever room I’m in.”

Pilot should use presence and player capabilities from the world model, execute through the controlled media skill, and record the outcome as events.

## Documentation

- [World Model](WORLD_MODEL.md)
- [Planning Engine](PLANNING_ENGINE.md)
- [Event Bus](EVENT_BUS.md)
- [Knowledge and Search](KNOWLEDGE_AND_SEARCH.md)
- [Identity and Learning](IDENTITY_AND_LEARNING.md)
- [ADR-005](../adr/ADR-005-intelligence-services-and-world-state.md)
- [Event schema](../../packages/event-schema/pilot-event-v1.schema.json)
