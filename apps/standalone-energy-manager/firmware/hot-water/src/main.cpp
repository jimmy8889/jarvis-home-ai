#include <Arduino.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include <ESP8266WebServer.h>
#include <ESP8266WiFi.h>
#include <LittleFS.h>
#include <sys/time.h>
#include <time.h>

#ifndef WIFI_SSID
#error WIFI_SSID must be supplied as a protected build environment variable
#endif
#ifndef WIFI_PASSWORD
#error WIFI_PASSWORD must be supplied as a protected build environment variable
#endif
#ifndef API_TOKEN
#error API_TOKEN must be supplied as a protected build environment variable
#endif

constexpr uint8_t BUTTON_PIN = 0;
constexpr uint8_t RELAY_PIN = 12;
constexpr uint32_t TARGET_SECONDS = 3UL * 3600UL + 3UL * 60UL;
constexpr int DEADLINE_HOUR = 16;
// The manager retains authoritative confirmed runtime in SQLite. Checkpoint
// meaningful local state at most every 15 minutes instead of wearing flash
// with minute-by-minute writes.
constexpr uint32_t PERSIST_INTERVAL_MS = 15UL * 60UL * 1000UL;
constexpr uint32_t BUTTON_DEBOUNCE_MS = 50;

ESP8266WebServer server(80);
bool relayOn = false;
bool controllerLease = false;
bool manualOverride = false;
uint32_t leaseExpiresMillis = 0;
uint32_t relayStartedMillis = 0;
uint32_t runtimeSeconds = 0;
uint32_t relayProxySeconds = 0;
uint32_t lastPersistMillis = 0;
int storedYday = -1;
bool persistDirty = false;

bool authorized() {
  return server.hasHeader("Authorization") && server.header("Authorization") == String("Bearer ") + API_TOKEN;
}

void applyRelay(bool on) {
  if (relayOn == on) return;
  if (relayOn) relayProxySeconds += (millis() - relayStartedMillis) / 1000;
  relayOn = on;
  digitalWrite(RELAY_PIN, relayOn ? HIGH : LOW);
  if (relayOn) relayStartedMillis = millis();
  persistDirty = true;
}

uint32_t currentRuntime() {
  return runtimeSeconds;
}

uint32_t currentRelayProxy() {
  return relayProxySeconds + (relayOn ? (millis() - relayStartedMillis) / 1000 : 0);
}

bool leaseValid() {
  return controllerLease && static_cast<int32_t>(leaseExpiresMillis - millis()) > 0;
}

uint32_t leaseRemainingSeconds() {
  if (!leaseValid()) return 0;
  return (leaseExpiresMillis - millis() + 999) / 1000;
}

void persist() {
  JsonDocument doc;
  doc["yday"] = storedYday;
  doc["runtime"] = currentRuntime();
  doc["relay_proxy"] = currentRelayProxy();
  File file = LittleFS.open("/runtime.json.tmp", "w");
  serializeJson(doc, file);
  file.close();
  LittleFS.remove("/runtime.json");
  LittleFS.rename("/runtime.json.tmp", "/runtime.json");
  relayProxySeconds = currentRelayProxy();
  if (relayOn) relayStartedMillis = millis();
  persistDirty = false;
  lastPersistMillis = millis();
}

void stateResponse() {
  if (!authorized()) {
    server.send(401, "application/json", "{\"error\":\"unauthorized\"}");
    return;
  }
  JsonDocument doc;
  doc["firmware"] = HOT_WATER_FIRMWARE_VERSION;
  doc["relay_on"] = relayOn;
  doc["runtime_seconds"] = currentRuntime();
  doc["relay_proxy_seconds"] = currentRelayProxy();
  doc["target_seconds"] = TARGET_SECONDS;
  const bool activeLease = leaseValid();
  const time_t now = time(nullptr);
  doc["controller_lease"] = activeLease;
  doc["manual_override"] = manualOverride;
  doc["lease_expires_at"] = activeLease && now > 1700000000 ? now + leaseRemainingSeconds() : 0;
  doc["fallback_active"] = relayOn && !activeLease && !manualOverride;
  String body;
  serializeJson(doc, body);
  server.send(200, "application/json", body);
}

void confirmationResponse() {
  if (!authorized()) {
    server.send(401, "application/json", "{\"error\":\"unauthorized\"}");
    return;
  }
  if (!server.hasArg("seconds")) {
    server.send(422, "application/json", "{\"error\":\"seconds is required\"}");
    return;
  }
  const long requested = server.arg("seconds").toInt();
  const uint32_t confirmed = static_cast<uint32_t>(requested > 0 ? requested : 0);
  // The manager sends the absolute confirmed daily total, making retries
  // idempotent. Never move confirmed service backwards within a local day.
  if (confirmed > runtimeSeconds) {
    runtimeSeconds = confirmed;
    persistDirty = true;
  }
  stateResponse();
}

void commandResponse() {
  if (!authorized()) {
    server.send(401, "application/json", "{\"error\":\"unauthorized\"}");
    return;
  }
  const String desired = server.arg("state");
  const uint32_t lease = constrain(server.arg("lease").toInt(), 30, 600);
  if (desired != "on" && desired != "off") {
    server.send(422, "application/json", "{\"error\":\"state must be on or off\"}");
    return;
  }
  controllerLease = true;
  manualOverride = false;
  leaseExpiresMillis = millis() + lease * 1000UL;
  if (server.hasArg("epoch")) {
    const time_t requestedEpoch = static_cast<time_t>(server.arg("epoch").toInt());
    if (requestedEpoch > 1700000000) {
      timeval value{requestedEpoch, 0};
      settimeofday(&value, nullptr);
    }
  }
  applyRelay(desired == "on");
  stateResponse();
}

void setup() {
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  LittleFS.begin();
  File file = LittleFS.open("/runtime.json", "r");
  if (file) {
    JsonDocument doc;
    if (!deserializeJson(doc, file)) {
      storedYday = doc["yday"] | -1;
      runtimeSeconds = doc["runtime"] | 0;
      relayProxySeconds = doc["relay_proxy"] | 0;
    }
  }
  WiFi.mode(WIFI_STA);
  WiFi.hostname("hotwater");
  WiFi.config(IPAddress(10, 0, 2, 237), IPAddress(10, 0, 2, 1), IPAddress(255, 255, 255, 0));
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  configTime(10 * 3600, 0, "10.0.2.1", "pool.ntp.org", "time.cloudflare.com");
  ArduinoOTA.setHostname("hotwater");
  ArduinoOTA.setPassword(API_TOKEN);
  ArduinoOTA.onStart([] { applyRelay(false); persist(); });
  ArduinoOTA.begin();
  server.on("/v1/state", HTTP_GET, stateResponse);
  server.on("/v1/command", HTTP_POST, commandResponse);
  server.on("/v1/confirm", HTTP_POST, confirmationResponse);
  server.on("/healthz", HTTP_GET, [] { server.send(200, "text/plain", "ok\n"); });
  server.begin();
}

void loop() {
  ArduinoOTA.handle();
  server.handleClient();
  static bool rawButton = HIGH;
  static bool stableButton = HIGH;
  static uint32_t buttonChangedAt = 0;
  const bool observedButton = digitalRead(BUTTON_PIN);
  if (observedButton != rawButton) {
    rawButton = observedButton;
    buttonChangedAt = millis();
  }
  if (rawButton != stableButton && millis() - buttonChangedAt >= BUTTON_DEBOUNCE_MS) {
    stableButton = rawButton;
    if (stableButton == LOW) {
      controllerLease = false;
      manualOverride = true;
      applyRelay(!relayOn);
    }
  }

  time_t now = time(nullptr);
  tm local{};
  localtime_r(&now, &local);
  if (local.tm_year > 120 && local.tm_yday != storedYday) {
    runtimeSeconds = 0;
    relayProxySeconds = 0;
    storedYday = local.tm_yday;
    if (relayOn) relayStartedMillis = millis();
    persistDirty = true;
    persist();
  }
  const bool activeLease = leaseValid();
  if (!activeLease && !manualOverride) {
    controllerLease = false;
    // During a controller outage, locally-observed relay time is the only
    // available proxy. Confirmed service from the manager remains distinct in
    // the API and persisted state.
    const uint32_t serviceProxy = max(currentRuntime(), currentRelayProxy());
    const uint32_t remaining = serviceProxy >= TARGET_SECONDS ? 0 : TARGET_SECONDS - serviceProxy;
    const int secondsNow = local.tm_hour * 3600 + local.tm_min * 60 + local.tm_sec;
    const int latestStart = DEADLINE_HOUR * 3600 - static_cast<int>(remaining);
    applyRelay(remaining > 0 && secondsNow >= latestStart && secondsNow < DEADLINE_HOUR * 3600);
  }
  if ((persistDirty || relayOn) && millis() - lastPersistMillis >= PERSIST_INTERVAL_MS) {
    persist();
  }
  delay(20);
}
