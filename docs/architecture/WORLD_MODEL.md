# Pilot World Model

Status: Proposed

## Purpose

The world model is Pilot's live, queryable representation of people, rooms, devices, services, media sessions, tasks, meetings, and relevant environmental state. It is not a replacement for Home Assistant; it adds meaning, relationships, confidence, time, and provenance over raw state.

## Design goals

- Represent current state and recent changes.
- Distinguish facts, estimates, preferences, and inferences.
- Preserve provenance and confidence.
- Remain room-aware and user-aware.
- Expose deterministic queries to skills and planners.
- Avoid giving the LLM unrestricted access to raw infrastructure.

## Core entities

- Person
- Room
- Device
- Service
- MediaSession
- ConversationSession
- Meeting
- Task
- Project
- Vehicle
- EnergyAsset
- Alert
- PresenceObservation

## Relationships

Examples:

```text
James --present_in--> Office
Office --contains--> office_n150
office_n150 --can_output_to--> office_speakers
media_room --contains--> denon_x8500h
meeting_123 --produced--> task_456
battery --supplies--> home
```

Every relationship contains timestamps, source, confidence, and expiry policy.

## State record

```json
{
  "subject": "person:james",
  "predicate": "present_in",
  "object": "room:office",
  "observed_at": "2026-07-16T08:00:00+10:00",
  "source": "home_assistant.binary_sensor.office_presence",
  "confidence": 0.94,
  "valid_until": "2026-07-16T08:02:00+10:00",
  "kind": "observation"
}
```

## Fact classes

- **Authoritative**: explicit configuration or trusted system state.
- **Observed**: sensor or client observation.
- **Inferred**: derived from multiple observations.
- **Preferred**: learned or explicitly stated user preference.
- **Planned**: future intended state from a project or automation.

Inferred state must never silently overwrite authoritative state.

## Initial data sources

- Pilot room and player registry
- Home Assistant entities and areas
- Music Assistant players and queues
- Room-agent capability and health events
- Denon and Shield state
- Calendar and meeting records
- macOS and iOS client presence
- Energy-system sensors and forecasts

## Query examples

```text
who_is_in(room:office)
preferred_output(person:james, room:office)
active_media_sessions()
healthy_capabilities(room:media_room)
why_is(device:battery, state:charging)
next_relevant_event(person:james)
```

## Storage

Use PostgreSQL for canonical entities and relationships, plus an append-only event log for history. Derived current state should be materialised for low-latency reads. Vector search is supplementary and must not be the source of truth for live state.

## Safety

- Sensitive person and presence records use explicit retention limits.
- Skills receive filtered views based on permissions.
- The planner may propose world changes but tools perform them.
- Every inference must be inspectable and explainable.
