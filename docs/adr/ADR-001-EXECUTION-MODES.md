# ADR-001: Controlled, Smart, and Agent Execution Modes

Status: Proposed

## Context

Pilot handles requests ranging from harmless information queries to locks, HVAC, media, and energy controls. Sending every request directly to an LLM creates unpredictable behaviour and weakens safety boundaries.

## Decision

Every request is assigned one execution mode:

- **Controlled:** one deterministic action path using approved schemas and tools.
- **Smart:** router chooses deterministic handling, retrieval, or a bounded LLM tool call.
- **Agent:** planner may execute multiple tool steps within declared limits.

Every action declares risk, confirmation policy, permitted modes, timeout, and maximum steps.

```yaml
execution_policy:
  permitted_modes: [controlled, smart]
  risk: medium
  confirmation: contextual
  timeout_seconds: 10
  max_steps: 1
```

Locks, alarms, physical access, destructive actions, and high-impact energy controls default to controlled mode and explicit confirmation.

## Consequences

- Safer and more testable household control.
- Predictable offline behaviour.
- More implementation work in the router and skill manifests.
- Agent mode remains useful without becoming the default.

## Alternatives considered

- LLM-first routing for all requests: rejected due to latency and unpredictability.
- Deterministic-only assistant: rejected because it limits natural multi-step workflows.

## Security and privacy impact

The policy engine becomes a mandatory enforcement boundary and must not be overridable by personas or prompts.

## Operational impact

Logs and traces must record the selected mode and policy decision for every request.
