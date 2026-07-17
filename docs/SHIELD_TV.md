# Pilot TV for NVIDIA Shield

Pilot TV 0.1 is the first television client for Pilot Core. It is a native
Kotlin and Compose for TV application under `apps/shield-tv`.

## Current capability

The first release is intentionally read only:

- connects directly to Pilot Core on the trusted LAN;
- loads the authenticated `/v1/operations` snapshot every 15 seconds;
- shows central health, safety, integrations, rooms, endpoints, sources,
  media-player state, volume, and now-playing metadata;
- identifies read-only versus control-enabled players;
- supports D-pad focus for connect, refresh, and lock;
- registers as an Android TV launcher application.

It does not power the Denon, start playback, change volume or source, launch
Shield applications, or send Home Assistant actions.

## Authentication and network boundary

The administrator token remains only in process memory. It is not written to
SharedPreferences, logs, a URL, or the Android backup service. Locking the app
or Android terminating the process clears it.

HTTPS is accepted for any valid host. Cleartext HTTP is accepted only for
localhost, `.local` names, and RFC1918 IPv4 addresses. The application manifest
allows cleartext transport because the current Pilot Core deployment is on the
private LAN; the client performs the narrower host check before connecting.
A TLS reverse proxy remains required before access across an untrusted network.

## Build

The project pins Android Gradle Plugin 9.3, Gradle 9.6.1 with a distribution
checksum, Kotlin/Compose compiler 2.3.21, compile SDK 37, Compose BOM
2026.06.00, and Compose for TV 1.1.

```bash
cd apps/shield-tv
./gradlew testDebugUnitTest lintDebug assembleDebug
```

The debug APK is produced at:

```text
apps/shield-tv/app/build/outputs/apk/debug/app-debug.apk
```

Installation and on-device focus/render validation are deferred until the
Shield can be observed locally:

```bash
adb connect SHIELD_IP
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## Next Shield milestones

1. Replace administrator-token entry with a device-bound one-time pairing flow.
2. Add WebSocket-driven assistant overlays.
3. Add Jellyfin and Kodi deep links while leaving Dolby Vision playback in
   those specialized applications.
4. Add explicitly permissioned Home Assistant favourites and camera surfaces.
5. Add media controls only after the corresponding Pilot Core player path has
   passed in-person acceptance.
