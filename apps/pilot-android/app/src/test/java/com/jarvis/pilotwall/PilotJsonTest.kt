package com.jarvis.pilotwall

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PilotJsonTest {
    @Test
    fun parsesHouseDashboardAndBedroomMusicPolicy() {
        val dashboard = PilotJson.dashboard(
            JSONObject(
                """
                {
                  "status": "ok",
                  "power": {
                    "solar_w": 8820, "grid_w": 15, "battery_w": -3110,
                    "battery_soc_percent": 77, "home_load_w": 5610,
                    "server_rack_w": 312,
                    "directions": {"grid": "exporting", "battery": "charging"},
                    "flow_active": {"grid": false}
                  },
                  "daily": {
                    "solar_generated_kwh": 66.3,
                    "home_used_kwh": 32.9,
                    "grid_exported_kwh": 5.5
                  },
                  "vehicle": {
                    "connected": true, "charging": true,
                    "power_w": 4540, "state_of_charge_percent": 64
                  },
                  "temperatures": [
                    {"id": "bedroom", "label": "Bedroom", "temperature_c": 23.4}
                  ],
                  "history": {
                    "window": "calendar_day",
                    "started_at": "2026-07-22T00:00:00+10:00",
                    "ended_at": "2026-07-23T00:00:00+10:00",
                    "series": [
                      {
                        "id": "solar", "label": "Solar", "color": "#F8C84A",
                        "points": [{"at": "2026-07-22T03:00:00Z", "value": 8820}]
                      },
                      {
                        "id": "home_load", "label": "Home load", "color": "#FF5D6C",
                        "points": [{"at": "2026-07-22T03:00:00Z", "value": -5610}]
                      },
                      {
                        "id": "tesla", "label": "Tesla charging", "color": "#D970FF",
                        "points": [{"at": "2026-07-22T03:00:00Z", "value": -4540}]
                      }
                    ]
                  },
                  "weather": {
                    "condition": "sunny", "temperature_c": 24,
                    "forecast": [{
                      "at": "2026-07-23T00:00:00Z", "condition": "partlycloudy",
                      "high_temperature_c": 26, "low_temperature_c": 15,
                      "precipitation_probability": 10
                    }]
                  },
                  "scene": {"is_day": false},
                  "tariff": {
                    "import_cents_per_kwh": 28.5, "feed_in_cents_per_kwh": 8.2,
                    "feed_in_forecast": [{"at": "2026-07-22T04:00:00Z", "cents_per_kwh": 11.3}]
                  },
                  "controls": {
                    "tesla_charging_mode": {"value": "Solar", "options": ["Grid", "Solar"]},
                    "media_room_mode": {"available": true}
                  }
                }
                """.trimIndent(),
            ),
        )

        assertFalse(dashboard.power.gridFlowActive)
        assertEquals("charging", dashboard.power.batteryDirection)
        assertEquals(312.0, dashboard.power.serverRackW!!, 0.01)
        assertTrue(dashboard.vehicle.connected == true)
        assertTrue(dashboard.vehicle.charging)
        assertEquals("Bedroom", dashboard.temperatures.single().label)
        assertEquals(8820.0, dashboard.history.first().points.single().value, 0.01)
        assertEquals(-5610.0, dashboard.history[1].points.single().value, 0.01)
        assertEquals(-4540.0, dashboard.history[2].points.single().value, 0.01)
        assertEquals("calendar_day", dashboard.historyWindow)
        assertEquals(
            "2026-07-21T14:00:00Z",
            dashboard.historyStartedAt.toString(),
        )
        assertEquals(26.0, dashboard.weather.forecast.single().highC!!, 0.01)
        assertEquals("Solar", dashboard.controls.chargingMode)
        assertTrue(dashboard.controls.mediaRoomAvailable)
        assertFalse(dashboard.sceneIsDay!!)

        val media = PilotJson.media(
            JSONObject(
                """
                {"rooms": [{
                  "id": "bedroom", "name": "Bedroom", "music_enabled": false,
                  "players": []
                }], "media": {"players": {}}}
                """.trimIndent(),
            ),
        )
        assertFalse(media.rooms.single().musicEnabled)
    }

    @Test
    fun parsesDeviceScopedMediaEnvelope() {
        val snapshot = PilotJson.media(
            JSONObject(
                """
                {
                  "rooms": [{
                    "id": "office", "name": "Office",
                    "response_player_id": "office-n150",
                    "default_music_player_id": "office-n150",
                    "players": [{
                      "id": "office-n150", "room_id": "office",
                      "name": "Pilot Office Music", "kind": "audio",
                      "protocol": "sendspin", "enabled": true,
                      "control_enabled": true
                    }]
                  }],
                  "media": {
                    "observed_at": "2026-07-20T09:30:00Z",
                    "players": {"office-n150": {
                      "player": {
                        "id": "office-n150", "room_id": "office",
                        "name": "Pilot Office Music", "kind": "audio",
                        "protocol": "sendspin", "enabled": true,
                        "control_enabled": true
                      },
                      "status": "online",
                      "effective": {
                        "available": true, "powered": true,
                        "playback_state": "playing", "volume_percent": 32,
                        "media": {"title": "Teardrop", "artist": "Massive Attack"}
                      }
                    }}
                  }
                }
                """.trimIndent(),
            ),
        )

        assertEquals("Office", snapshot.rooms.single().name)
        assertEquals("Teardrop", snapshot.players.single().effective.media?.title)
        assertEquals(32, snapshot.players.single().effective.volumePercent)
        assertTrue(snapshot.players.single().effective.available)
    }

    @Test
    fun parsesAndFormatsEnergySurface() {
        val surface = PilotJson.surface(
            JSONObject(
                """
                {
                  "server_time": "2026-07-20T09:30:00Z",
                  "energy": {
                    "status": "ok",
                    "solar": {"value": 8420, "unit": "W"},
                    "grid": {"value": -3180, "unit": "W", "direction": "exporting"},
                    "battery": {"value": 2350, "unit": "W", "direction": "discharging"},
                    "battery_soc": {"value": 82, "unit": "%"},
                    "home_load": {"value": 3140, "unit": "W"}
                  },
                  "now_playing": []
                }
                """.trimIndent(),
            ),
        )

        assertEquals("8.4 kW", surface.energy?.solar?.display())
        assertEquals("82%", surface.energy?.batterySoc?.display())
        assertEquals("exporting", surface.energy?.grid?.direction)
    }

    @Test
    fun flattensNestedSearchAndDeduplicatesUris() {
        val results = PilotJson.search(
            JSONObject(
                """
                {
                  "tracks": [
                    {"uri": "track://1", "name": "One", "artist": "Artist"},
                    {"uri": "track://1", "name": "Duplicate"}
                  ],
                  "albums": [
                    {"media_uri": "album://2", "title": "Two", "media_type": "album"}
                  ]
                }
                """.trimIndent(),
            ),
        )

        assertEquals(2, results.size)
        assertEquals("Artist", results.single { it.uri == "track://1" }.subtitle)
        assertFalse(results.any { it.uri.isBlank() })
    }

    @Test
    fun parsesBoundedHomeProjectionAndConfirmation() {
        val projection = PilotJson.home(
            JSONObject(
                """
                {
                  "selected_room_id": "office",
                  "room": {"id": "office", "name": "Office"},
                  "entities": [{
                    "entity_id": "light.office_lamp",
                    "domain": "light",
                    "name": "Office lamp",
                    "state": "on",
                    "area_id": "james_office",
                    "unavailable": false,
                    "stale": false,
                    "attributes": {"brightness": 128},
                    "actions": ["turn_on", "turn_off", "set_brightness"]
                  }]
                }
                """.trimIndent(),
            ),
        )
        val lamp = projection.entities.single()
        assertEquals("Office", projection.roomName)
        assertTrue(lamp.isOn)
        assertEquals(50f, lamp.brightnessPercent!!, 1f)
        assertTrue("set_brightness" in lamp.actions)

        val confirmation = PilotJson.homeAction(
            JSONObject(
                """
                {"action": {
                  "id": "action-1", "status": "pending",
                  "entity_id": "lock.front_door", "action": "unlock",
                  "risk": "high", "confirmation_required": true,
                  "description": "Unlock Front Door"
                }}
                """.trimIndent(),
            ),
        )
        assertTrue(confirmation.confirmationRequired)
        assertEquals("Unlock Front Door", confirmation.description)
    }
}
