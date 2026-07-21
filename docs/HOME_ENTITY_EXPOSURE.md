# Home entity exposure policy

Pilot Core deliberately separates the complete Home Assistant inventory from
the user-facing home model.

The complete catalogue remains administrator-only. It supports coverage,
diagnosis, deterministic entity resolution, and future exposure review. Mobile,
wall-display, voice, and LLM search surfaces receive only the curated projection.

## Included by default

- lighting, climate, covers, fans, locks, alarms, scenes, switches and useful
  helpers;
- cameras, media players, vacuums, people and weather;
- environmental, safety, occupancy, security, battery, energy and power sensors;
- explicitly configured Pilot weather, temperature and energy entities.

## Excluded by default

- entity-registry entries marked hidden or disabled;
- Home Assistant `diagnostic` and `config` entity categories;
- firmware, identify, restart, uptime, last-seen, RSSI, LQI and link-quality
  internals;
- update, automation, script, button, number, text, select, time and other
  implementation-oriented domains until a product surface explicitly governs
  them;
- entities without a recognized user-facing domain, device class, measurement
  unit, or explicit Pilot configuration.

The policy is evaluated centrally by `HomeIntelligence.is_relevant`. This keeps
the iOS, Android, display and LLM views consistent. `HomeActions` applies the
same policy before returning room projections, while action authorization still
requires an exact entity ID, room membership, capability and typed action.

The filter is intentionally conservative. A later administrator exposure editor
can add explicit per-entity include/exclude overrides without placing Home
Assistant credentials or raw registries on clients.
