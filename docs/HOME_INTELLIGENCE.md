# Pilot Home Intelligence v1

Pilot Core maintains a read-only, normalized copy of Home Assistant state so the
assistant and clients can discover the whole home without placing thousands of
raw entities in an LLM prompt. Home Assistant remains the control boundary.
Music Assistant remains the music and queue authority.

## Safety boundary

- State synchronization uses only `GET /api/states`.
- Floors, areas, devices, entity aliases, and stable registry identity are read
  through Home Assistant's authenticated WebSocket registry-list commands.
- Catalogue tools can search, read, summarize areas, and read normalized energy.
- Catalogue tools cannot call a Home Assistant service or alter state.
- Pilot's pre-existing `control_home` tool remains a separate, explicit path
  through Home Assistant Assist.
- Entity names, states, and attributes are untrusted data, not instructions.
- An action tool cannot run later in the same reasoning request after the model
  has read untrusted catalogue output. This prevents an entity name or attribute
  from escalating a read into a home or media action.
- Only an allowlist of useful attributes is retained. Credentials, coordinates,
  camera URLs, arbitrary nested values, and unknown attributes are discarded.
- Strings, lists, snapshot size, search results, and tool output are bounded.
- A failed synchronization preserves the last successful snapshot and marks it
  stale; it never replaces good data with an empty catalogue.

## Persistence and identity

`home_entities` stores current normalized state. The Home Assistant `entity_id`
is the fallback stable identifier. Registry `unique_id`, `area_id`, `device_id`,
aliases, and device-to-area relationships take precedence when Home Assistant
provides them, without changing the public entity shape.

Entities missing from a later snapshot are retained with `missing=true`. This
supports diagnostics and avoids silently erasing a previously known entity.
`home_catalog_syncs` records successful and failed synchronization attempts.

When registry metadata is temporarily unavailable, the adapter may infer a room
only when an entity ID or friendly name contains exactly one configured Pilot
room name. Entities that cannot be safely assigned remain in the catalogue with
`area_id=null`; Pilot does not guess.

## Configuration

The following optional `[integrations]` settings control synchronization:

```toml
home_catalog_sync_interval_seconds = 300
home_catalog_stale_after_seconds = 900
home_catalog_max_entities = 20000
```

An unsupported registry command is recorded as partial metadata. A registry
connection failure falls back to the state snapshot and preserves metadata from
the last successful registry read.

When Home Assistant URL and credentials are configured, Pilot Core performs an
initial synchronization at startup and repeats it at the configured interval.
Administrators can also request a snapshot synchronously.

The existing configured energy entity IDs are preferred:

```toml
energy_solar_power_entity_id = "sensor.pv_power_mqtt_abs"
energy_grid_power_entity_id = "sensor.saj_ct_grid_power_total"
energy_battery_power_entity_id = "sensor.saj_battery_power_2"
energy_battery_soc_entity_id = "sensor.saj_battery_1_soc"
energy_home_load_entity_id = "sensor.saj_home_load"
```

Known local sensor IDs are used as read-only fallbacks when a field is not
configured. Power is normalized to watts and state of charge to percent. The
grid convention is positive import and negative export. The battery convention
is positive discharge and negative charge.

## Administrator API

All endpoints require the Pilot Core administrator bearer token and return
`Cache-Control: no-store`.

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/v1/home/sync` | Fetch and atomically store a state snapshot |
| `GET` | `/v1/home/sync` | Read latest attempt and last-success freshness |
| `GET` | `/v1/home/catalog` | Filter the normalized catalogue |
| `GET` | `/v1/home/catalog/{entity_id}` | Read one known entity |
| `GET` | `/v1/home/search?q=...` | Ranked natural-name/entity search |
| `GET` | `/v1/home/coverage` | Domain, area, availability, stale, and missing coverage |
| `GET` | `/v1/home/areas` | Area summaries for clients |
| `GET` | `/v1/home/floors` | Floor hierarchy and coverage |
| `GET` | `/v1/home/devices` | Safe device metadata and entity counts |
| `GET` | `/v1/home/energy` | Normalized local energy snapshot |

Catalogue filters are `q`, `domain`, `area_id`, `availability`,
`include_missing`, and `limit`. Search never silently chooses between tied
friendly names; it reports `ambiguous=true`. The typed assistant resolver rejects
the same ambiguity unless an exact entity ID or uniquely ranked result is given.

Normalized entity responses contain:

```json
{
  "entity_id": "sensor.bedroom_temperature",
  "stable_id": "sensor.bedroom_temperature",
  "domain": "sensor",
  "name": "Bedroom Temperature",
  "state": "22.4",
  "attributes": {
    "unit_of_measurement": "C",
    "device_class": "temperature"
  },
  "area_id": "bedroom",
  "device_id": null,
  "aliases": ["Bedroom Temperature", "bedroom temperature"],
  "availability": "available",
  "unavailable": false,
  "stale": false,
  "missing": false,
  "observed_at": "2026-07-20T01:02:03+00:00",
  "synced_at": "2026-07-20T01:02:04+00:00"
}
```

## Assistant tools

The Home Intelligence tool set is deliberately read-only:

- `search_home_entities`
- `read_home_entity`
- `get_home_area_summary`
- `get_energy_snapshot`

Tool results carry entity IDs, timestamps, and stale/availability flags so an
answer can state its provenance and uncertainty.

## Validation and rollback

Tests cover:

- More than 2,000 entities in one snapshot.
- Ranked search and duplicate friendly-name ambiguity.
- Invalid entity IDs, malicious names, secret attributes, and oversized values.
- Missing entities across snapshots.
- Home Assistant outage and stale-state behavior.
- Energy units and direction.
- Administrator authentication and no-store headers.
- A read-only Home Assistant synchronization request.
- Registry authentication, registry-list commands, device-area inheritance,
  and unsupported-command fallback.

Rollback requires only reverting the Pilot Core release. The new tables are
additive and older releases ignore them. No Home Assistant configuration or
entity state is modified. The SQLite database should still be included in the
normal Pilot Core backup before a release change.
