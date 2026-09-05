# Home Assistant Tesla Fleet migration

This runbook moves Jarvis current state and controls from Tesla Custom/HACS to
Home Assistant's native Tesla Fleet integration. TeslaMate remains unchanged
and continues to provide historical drives, charging, efficiency, degradation,
and MQTT synchronisation.

## Before enabling commands

1. Create or open the Tesla Developer application. Grant **Vehicle
   Information**, **Vehicle Location**, and **Vehicle Commands** scopes. Use
   `https://ip.jameshomeautomation.work` as the public origin/key domain.
2. Serve the application public key at the exact path
   `/.well-known/appspecific/com.tesla.3p.public-key.pem`. Validate from an
   external network:

   ```bash
   curl --fail --show-error \
     https://ip.jameshomeautomation.work/.well-known/appspecific/com.tesla.3p.public-key.pem
   ```

3. Add or enable the existing **Tesla Fleet** integration in Home Assistant
   and complete its developer-application authentication. The generated
   `config/tesla_fleet.key` must exist in the Home Assistant configuration
   directory.
4. Complete virtual-key enrollment for Jarvis using
   `https://tesla.com/_ak/ip.jameshomeautomation.work`, then verify the Fleet
   integration reports the vehicle online. This is an interactive Tesla step;
   software tests cannot substitute for it.
5. Enable the native Jarvis odometer and four TPMS entities (and any required
   range diagnostic entity) in the entity registry. Keep unsupported native
   controls hidden.

## Install the signed route bridge

Copy `integrations/home_assistant/custom_components/pilot_vehicle` into
Home Assistant's `/config/custom_components/` directory, restart Home
Assistant, then add **Pilot Vehicle** under Settings → Devices & services.
The service deliberately exposes only:

```yaml
service: pilot_vehicle.send_navigation
data:
  device_id: <native Jarvis HA device id>
  latitude: -27.4
  longitude: 153.0
  order: 0
```

It resolves the loaded native Fleet runtime and calls the signed
`navigation_gps_request` API. It does not accept arbitrary Tesla commands,
VINs, or credentials. Errors distinguish missing enrollment/key, billing or
usage limits, unavailable vehicle commands, and provider outages.

## Switch Core and validate

1. Deploy the updated Core configuration. It maps telemetry and controls to
   the existing native Jarvis entities and sends saved destinations through
   `pilot_vehicle.send_navigation`; the old `PILOT_TESLA_VEHICLE_ID` secret and
   compose wiring are removed.
2. Compare native Fleet state with the current HA/TeslaMate values. Opening
   Pilot Drive must not wake the vehicle.
3. With Jarvis parked and physically observed, validate wake, climate,
   charging, lock, closure, and sentry controls individually.
4. Send one saved destination. Confirm the route arrives on the Tesla
   touchscreen, then verify the Pilot action reaches reconciliation or is
   correctly reported as unverified.
5. Only after those checks pass, disable Tesla Custom to avoid duplicate
   polling. If any prerequisite fails, re-enable Tesla Custom and restore the
   previous Core entity mappings.

Tesla Fleet command billing and developer-account limits are external to this
repository. Keep the existing HACS integration available until physical
acceptance is complete.
