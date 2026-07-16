# ADR-003: Skill, Action, and Tool Runtime

Status: Proposed

## Context

Pilot will integrate Home Assistant, Music Assistant, Denon, Shield, Jellyfin, meetings, dictation, timers, and energy systems. Directly embedding every integration into Pilot Core would make permissions, testing, and upgrades difficult.

## Decision

Use the hierarchy:

```text
Skill -> Action -> Tool -> Function / Adapter / Binary
```

Each skill package contains:

```text
skills/<name>/
├── SKILL.md
├── manifest.yaml
├── permissions.yaml
├── actions/
├── tools/
├── schemas/
└── tests/
```

The runtime validates inputs and outputs, checks execution mode and permissions, applies confirmations, enforces timeouts, and emits structured results.

Skills must never receive unrestricted shell or network access by default.

## Consequences

- Integrations become modular, testable, and replaceable.
- The same skill can be used by voice, macOS, iOS, Shield, and automations.
- Requires a versioned manifest and SDK.

## Alternatives considered

- Hard-code integrations in Pilot Core: rejected due to coupling.
- Generic unrestricted agent tools: rejected due to weak safety boundaries.

## Security and privacy impact

Permissions are declarative and enforced outside the LLM. Secrets are referenced by identifier and never stored in manifests.

## Operational impact

Every skill exposes version, dependencies, health, and capability metadata to the capability registry.
