# Home entity exposure and presentation policy

Pilot Core deliberately separates the complete Home Assistant catalogue from
the product-facing home model. The complete catalogue remains
administrator-only for coverage, diagnosis and review. Mobile, wall-display,
TV, voice and model-facing surfaces receive a bounded projection with an
explanation of why each entity is present and what it may do.

## Automatic policy

The default `automatic` policy includes recognized user-facing domains such as
lights, climate, covers, fans, locks, alarms, scenes, switches, cameras, media
players, vacuums, people and weather. It also includes recognized
environmental, safety, occupancy, security, battery, energy and power sensors,
plus explicitly configured Pilot weather, temperature and energy entities.

It excludes:

- registry entries marked hidden or disabled;
- Home Assistant `diagnostic` and `config` entity categories;
- firmware, identify, restart, uptime, last-seen, RSSI, LQI and link-quality
  internals;
- raw hardware identifiers and unsupported implementation-oriented domains;
- sensors and binary sensors without recognized user-facing semantics.

Every result records a stable reason such as `user_facing_domain`,
`configured_or_user_facing_sensor`, `internal_or_diagnostic_name` or
`unsupported_domain`. Coverage reports count both policies and reasons so an
administrator can audit why the projection is smaller than Home Assistant.

## Persistent presentation metadata

`HomeIntelligence.presentation` returns:

```text
exposure_policy   automatic | include | exclude
included          final visibility after policy
reason            automatic or administrator-supplied explanation
category          control, safety, environment, energy or status
priority          product ordering hint
section           product grouping hint
control           semantic renderer hint
supported_actions typed actions known for the entity domain
room              room ID, HA area ID, trust source and authoritative flag
display_name/icon user-facing overrides
canonical_id      stable canonical identity
duplicate_of      canonical entity when this is a duplicate
updated_at        persisted override timestamp
```

Overrides are stored centrally, survive restart and are shared by every
client. An administrator can set `include`, `exclude` or return to
`automatic`; assign a Pilot room; adjust product metadata; and record canonical
or duplicate identity. Provider credentials and raw registries stay server-side.

Administrator APIs:

```text
GET   /v1/home/presentation?q=...&included=...
GET   /v1/home/presentation/{entity_id}
PATCH /v1/home/presentation/{entity_id}
```

The operations dashboard exposes the common **Auto**, **Show** and **Hide**
decisions alongside the reason and room trust. More detailed overrides remain
available through the authenticated API.

## Room trust and mutation safety

Visibility is not authority. Pilot records how an entity reached a room:

- `registry`: Home Assistant registry metadata maps the area to exactly one
  configured Pilot room;
- `explicit`: an administrator assigned the Pilot room;
- `inferred`, `state`, `unassigned` or another non-authoritative source: useful
  for diagnosis and read-only presentation, but not trusted for mutation.

Only `registry` and `explicit` mappings are authoritative. `HomeActions`
rejects a mutation when the entity is excluded, stale, unavailable, outside
the selected room, mapped only by inference, unsupported for the requested
typed action, or beyond the device's capabilities. Sensitive typed actions
retain confirmation and expiry requirements.

This rule is intentional: an entity may be readable while Pilot is still
learning where it belongs, but an LLM or client cannot turn that uncertainty
into a real Home Assistant service call.

## Client contract

Device-scoped room projections include only the curated entities for rooms the
credential may access. Each entity carries its presentation block and a final
`actions` list. Clients should:

1. render the supplied display name, section, priority and control hint;
2. show only the returned actions;
3. never infer a mutation from domain, icon or entity ID alone;
4. handle `202` confirmation responses explicitly;
5. refresh when `pilot.home.presentation.changed.v1` or a related home event
   arrives.

The source release includes persistence and contract tests for explicit
include/room promotion and the fail-closed inferred-room rule. Production
catalogue review remains an operator task: automatic relevance is deliberately
conservative and does not assert that every useful entity is already curated.
