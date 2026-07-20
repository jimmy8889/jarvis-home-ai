# Pilot Home Digital Twin

Pilot's home interface is an app-first representation of Home Assistant rather
than a wrapper around Lovelace. It presents the house as a shared interactive
3D digital twin on iPhone, iPad, and a wall-mounted Android tablet.

## Product experience

The default view shows the complete house with live room state. A user can:

- rotate, pan, zoom, isolate a floor, or enter a room;
- tap a room to open its lighting, climate, blind, media, security, and scene
  controls;
- tap a represented device to operate that device directly;
- see light state and colour reflected in the model;
- view room temperature, occupancy, doors, windows, media, alerts, and energy
  as optional overlays;
- run room scenes and whole-home actions without navigating Home Assistant's
  entity hierarchy;
- switch between a free 3D camera and named, predictable room/floor views.

The wall-tablet mode adds an always-on overview, large touch targets, kiosk
recovery, configurable screen dimming, and prominent alarm or doorbell states.

## Authority and security boundary

```text
iPhone / Android tablet
        |
        | device-authenticated Pilot APIs and event stream
        v
Pilot Core
  - model and room projection
  - identity, permissions and confirmations
  - action validation and audit records
  - normalized live state
        |
        v
Home Assistant
  - authoritative entity state
  - deterministic service execution
```

Clients do not receive a Home Assistant administrator token and do not call
arbitrary Home Assistant services. Pilot Core maps model objects to allowlisted
entities and actions, applies device/user permissions, and keeps Home Assistant
as the deterministic home-control boundary.

## Shared model package

The house is authored once and exported as a versioned package:

```text
home-model/
  house.glb
  manifest.json
  thumbnails/
  textures/
```

The manifest supplies stable identifiers independent of Home Assistant entity
names:

```json
{
  "model_version": "1",
  "floors": [{"id": "ground", "node": "Floor_Ground"}],
  "rooms": [
    {
      "id": "office",
      "node": "Room_Office",
      "camera": "Camera_Office",
      "entities": {
        "temperature": "sensor.office_temperature",
        "lights": ["light.office"]
      }
    }
  ]
}
```

Model geometry, room identifiers, entity mappings, camera presets, and
interaction anchors are validated before publication. Home Assistant entity
renames therefore require a mapping update rather than a new application
release.

## Pilot Core additions

The digital twin requires device-authenticated interfaces for:

- model manifest and immutable asset discovery;
- bounded room and device state snapshots;
- a reconnect-safe WebSocket event stream;
- typed actions for lights, scenes, climate, blinds, locks, media, and other
  explicitly enabled domains;
- action confirmations for security-sensitive operations;
- per-user favourites, camera positions, overlay settings, and tablet layouts;
- audit history and model-version compatibility.

The first release should support lights, room scenes, climate, occupancy,
temperature, doors/windows, and media state. Locks, garage doors, alarms, and
other security-sensitive actions remain read-only until confirmations,
permissions, and audit history are accepted.

## Client implementations

### Apple

The existing Pilot SwiftUI application gains the 3D home surface, shared room
and entity controls, model caching, event updates, and phone/tablet layouts.
Music Assistant, voice, and home controls remain parts of one Pilot app.

### Android wall tablet

A native Android application uses the same Pilot Core schemas, model package,
device-pairing flow, and permission system. Its primary mode is a resilient
landscape wall console with automatic launch, full-screen recovery, screen
dimming, and large controls. It is not a WebView of Home Assistant.

## Ordered delivery

1. Inventory floors, rooms, controllable entities, scenes, and security
   classifications.
2. Produce the first optimized GLB model and stable manifest.
3. Add Pilot Core model, state, action, event, permission, and audit APIs.
4. Add a simple 2D room-list fallback using the same state/action contracts.
5. Build the iOS 3D viewer, room selection, live lighting, and basic controls.
6. Build the Android client from the same contracts and accept wall-tablet
   lifecycle behavior.
7. Add climate, blinds, media, occupancy, environmental, and energy overlays.
8. Add confirmation-gated security controls and user-specific layouts.
9. Add editing/calibration tools so room/entity mappings can evolve without
   hand-editing JSON.

## Acceptance

- Both clients load the same signed model version and resolve identical rooms.
- State changes made in Home Assistant appear in the model promptly.
- A light or room-scene action updates Home Assistant and reconciles back from
  authoritative state rather than assuming success.
- Disconnects show stale/offline state and recover without duplicate actions.
- A fixed wall tablet cannot use APIs outside its assigned permissions.
- Security-sensitive actions are unavailable until the confirmation and audit
  path has been explicitly enabled and tested.
- The Android tablet recovers from reboot, app termination, network loss, and
  Pilot Core restart without manual intervention.
