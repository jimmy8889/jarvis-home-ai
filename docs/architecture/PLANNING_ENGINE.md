# Pilot Planning Engine

Status: Proposed

## Purpose

The planning engine turns goals into bounded, reviewable projects and next actions. It is separate from conversational response generation and cannot bypass execution policy.

## Planning levels

### Immediate plan
A short tool sequence for one request. Maximum steps and timeout are supplied by the execution policy.

### Task plan
A small workflow that may pause for confirmation, external events, or user input.

### Project plan
A persistent goal with milestones, dependencies, owners, deadlines, evidence, and status history.

## Project model

```yaml
id: project-pilot-office-v1
title: Complete Pilot office endpoint
owner: person:james
status: active
objective: Reliable local voice and audio endpoint
success_criteria:
  - Wake request succeeds from three metres
  - Home Assistant action completes
  - Response returns through office output
milestones:
  - id: audio-validation
    status: complete
  - id: hey-pilot-model
    status: planned
next_action: Train and deploy Hey Pilot wake model
```

## Plan lifecycle

```text
CAPTURED
→ CLARIFYING
→ PROPOSED
→ APPROVED
→ ACTIVE
→ WAITING
→ BLOCKED
→ COMPLETED / CANCELLED
```

## Planner responsibilities

- Break goals into milestones and actions.
- Detect missing information and dependencies.
- Estimate risk and request confirmation.
- Select skills through the capability registry.
- Record evidence when actions complete.
- Re-plan when world state materially changes.
- Surface the best next action without becoming noisy.

## Hard boundaries

- Plans never execute tools directly.
- Every action passes through execution policy and the skill runtime.
- High-risk actions require explicit confirmation at execution time even if the project was previously approved.
- The planner must state assumptions and uncertainty.
- Automatic re-planning is bounded by maximum attempts and time.

## Event-driven operation

The planner subscribes to events such as:

- task.completed
- task.blocked
- meeting.action_item.created
- device.capability.changed
- calendar.event.approaching
- presence.changed
- github.issue.closed

## First use cases

1. Pilot builds and manages its own implementation roadmap.
2. Meeting actions become tasks with owners and deadlines.
3. Travel or household projects become persistent checklists.
4. A diagnosed automation fault becomes a repair plan.
5. Media-room deployment tracks hardware, software, and validation dependencies.

## APIs

```text
POST /v1/projects
GET  /v1/projects/{id}
POST /v1/projects/{id}/approve
POST /v1/projects/{id}/pause
POST /v1/projects/{id}/replan
GET  /v1/projects/{id}/next-action
```

## Observability

Every plan revision records:

- initiating user or event
- model and prompt version
- world-model revision
- proposed actions
- policy decisions
- confirmations
- execution evidence
