# Pilot Identity and Preference Learning

Status: Proposed

## Purpose

Pilot should recognise who is interacting, apply the correct permissions and preferences, and improve from explicit corrections without silently profiling household members.

## Identity levels

1. **Authenticated client identity** — strongest: signed macOS, iOS, Shield, or web session.
2. **Physical room context** — device and room that captured the request.
3. **Voice profile match** — optional probability, never sole authority for high-risk actions.
4. **Presence correlation** — optional supporting signal from Home Assistant.
5. **Guest/unknown** — least privilege.

## Voice identification

Speaker recognition is optional and consent-based. It may personalise responses, music, reminders, and meeting labels, but locks, purchases, security changes, and sensitive data require a stronger identity factor.

```json
{
  "candidate_user": "james",
  "confidence": 0.88,
  "signals": ["voice_profile", "office_presence"],
  "authentication_level": "contextual"
}
```

## Preference learning

Pilot may propose a learned preference only after repeated consistent behaviour or an explicit statement.

Examples:

- Preferred office player
- Typical response verbosity
- Music handoff behaviour
- Whether meeting filler words should be removed
- Quiet hours

Learning lifecycle:

```text
OBSERVED
→ CANDIDATE
→ CONFIRMED or REJECTED
→ ACTIVE
→ SUPERSEDED / FORGOTTEN
```

No candidate preference may control a high-risk action.

## Corrections

Users can say:

- “Use the office speakers by default.”
- “Don’t announce calendar events aloud.”
- “Forget that preference.”
- “That was Rachael speaking.”

Corrections create auditable preference or identity events.

## Permission profiles

Each person or guest role declares:

- allowed skills
- sensitive data access
- rooms and devices
- confirmation requirements
- allowed proactive notifications
- media and meeting privacy

## Privacy controls

- Voice profiles remain local.
- Raw enrolment audio is removable after profile generation.
- Users can inspect confidence and contributing signals.
- Unknown speakers remain unknown rather than being forced into the nearest profile.
- Household members can opt out independently.
