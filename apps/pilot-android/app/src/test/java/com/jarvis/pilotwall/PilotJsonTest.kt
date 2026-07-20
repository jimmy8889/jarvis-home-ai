package com.jarvis.pilotwall

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PilotJsonTest {
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
        assertEquals("Artist", results.first().subtitle)
        assertFalse(results.any { it.uri.isBlank() })
    }
}
