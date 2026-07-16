# Pilot Event Bus

Status: Proposed

## Purpose

The event bus decouples room agents, clients, skills, media services, the world model, planning, and observability. Events describe what happened; commands request an action. These must remain distinct.

## Event envelope

```json
{
  "specversion": "1.0",
  "id": "01J...",
  "type": "pilot.presence.changed.v1",
  "source": "room-agent/office",
  "subject": "room:office",
  "time": "2026-07-16T08:00:00+10:00",
  "trace_id": "01J...",
  "room_id": "office",
  "user_id": null,
  "privacy": "household",
  "data": {
    "occupied": true,
    "confidence": 0.94
  }
}
```

The envelope should follow CloudEvents concepts while retaining Pilot-specific trace, room, user, and privacy fields.

## Initial event families

### Voice
- wake.detected
- listening.started
- transcription.partial
- transcription.final
- conversation.continued
- assistant.response.started
- assistant.response.finished
- assistant.cancelled

### Audio and media
- player.state.changed
- audio.focus.changed
- bluetooth.connected
- airplay.session.started
- media.handoff.completed
- announcement.requested

### Rooms and devices
- room.presence.changed
- device.discovered
- device.capability.changed
- device.health.changed
- peripheral.button.pressed
- privacy.mute.changed

### Intelligence
- memory.created
- world.fact.changed
- inference.completed
- project.created
- task.blocked
- proactive.opportunity.detected

### Integrations
- home_assistant.state.changed
- meeting.completed
- github.issue.changed
- calendar.event.approaching
- energy.opportunity.changed

## Delivery guarantees

- At-least-once delivery for durable operational events.
- Consumers must be idempotent.
- Ordering is guaranteed only within an entity or aggregate stream.
- Ephemeral high-rate events such as audio meters may use lossy delivery.
- Sensitive payloads must not be persisted unless explicitly configured.

## Transport

Start with a lightweight local broker suitable for the existing stack. NATS with JetStream is the preferred candidate for durable events and request/reply. MQTT remains appropriate for existing home-device interoperability but should not become Pilot's only internal contract.

## Schema management

- JSON Schema for every durable event.
- Version in event type names.
- Backward-compatible additions within a version.
- Contract tests in CI.
- Dead-letter handling for invalid or repeatedly failing events.

## Command separation

Commands use a separate namespace and response contract:

```text
pilot.command.media.play.v1
pilot.command.home.execute.v1
pilot.command.room.speak.v1
```

A command produces accepted/rejected status and eventually one or more outcome events.

## Security

- Per-service credentials and subject permissions.
- Room agents may publish only their own state and consume approved room commands.
- Audit events are immutable.
- Personal and meeting content uses restricted subjects and retention policies.
