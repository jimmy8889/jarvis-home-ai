# TeslaMate and Pilot Drive deployment — 2026-08-03

## Result

- TeslaMate host: `10.0.1.192`
- Adapter endpoint: `http://10.0.1.192:8781`
- Docker network: `root_default`
- Image: `jarvis-home-ai/pilot-teslamate-adapter:0.1.0`
- Database access: dedicated `pilot_teslamate_reader` login with SELECT-only
  table grants, read-only transactions, and a five-second statement timeout
- Pilot Core target: `0.30.2` on apps01

The adapter returned one configured car and bounded recent drive, charge, and
battery-health projections during deployment validation. No TeslaMate schema
or application-owned data was modified.

## Secrets and access

The adapter bearer token is shared only between Pilot Core and the adapter.
The PostgreSQL reader password exists only in the adapter DSN secret. Both
files live below the root-only adapter secrets directory and are mounted into
the unprivileged container.

## Rollback

1. Stop `teslamate-adapter-pilot-teslamate-adapter-1`.
2. Restore the previous immutable Pilot Core image and config on apps01.
3. If permanent removal is required, revoke `pilot_teslamate_reader` after
   confirming no adapter process remains.

Stopping the adapter only removes Pilot Drive history; live Home Assistant
vehicle state remains available by design.
