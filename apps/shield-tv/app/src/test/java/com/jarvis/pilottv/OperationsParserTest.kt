package com.jarvis.pilottv

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class OperationsParserTest {
    @Test
    fun parsesProviderNeutralMediaAndSafetyState() {
        val snapshot = OperationsParser.parse(
            JSONObject(
                """
                {
                  "generated_at": "2026-07-17T10:00:00Z",
                  "deployment": {
                    "version": "0.9.0",
                    "release": "test",
                    "uptime_seconds": 7200
                  },
                  "summary": {
                    "room_count": 1,
                    "device_count": 1,
                    "connected_device_count": 1,
                    "configured_integration_count": 2,
                    "healthy_integration_count": 2,
                    "armed_room_count": 0,
                    "unarmed_room_count": 1,
                    "pending_command_count": 0
                  },
                  "safety": {
                    "audible_actions_gated": true,
                    "armed_rooms": [],
                    "unarmed_rooms": ["media-room"]
                  },
                  "integrations": {
                    "music_assistant": {
                      "configured": true,
                      "status": "ok",
                      "latency_ms": 14
                    }
                  },
                  "media": {
                    "players": {
                      "media-room-heos": {
                        "status": "ok",
                        "effective": {
                          "available": true,
                          "powered": true,
                          "playback_state": "idle",
                          "volume_percent": 35,
                          "muted": false,
                          "source": "HEOS Music",
                          "media": {
                            "title": "Time",
                            "artist": "Pink Floyd",
                            "album": "The Dark Side of the Moon"
                          }
                        }
                      }
                    }
                  },
                  "rooms": {
                    "media-room": {
                      "room": {
                        "id": "media-room",
                        "name": "Media Room",
                        "players": [{
                          "id": "media-room-heos",
                          "name": "Media Room",
                          "kind": "music",
                          "protocol": "heos",
                          "control_enabled": false
                        }]
                      },
                      "devices": [],
                      "sources": {
                        "music": {"active": false}
                      },
                      "focus": {"foreground": null}
                    }
                  }
                }
                """.trimIndent(),
            ),
        )

        assertTrue(snapshot.safety.audibleActionsGated)
        assertEquals(1, snapshot.rooms.size)
        assertFalse(snapshot.rooms.single().armed)
        val player = snapshot.rooms.single().players.single()
        assertEquals("media-room-heos", player.id)
        assertEquals(35, player.volumePercent)
        assertEquals("Time", player.media?.title)
        assertFalse(player.controlEnabled)
        assertEquals(14L, snapshot.integrations.single().latencyMs)
    }
}
