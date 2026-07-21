package com.jarvis.pilottv

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class OperationsParserTest {
    private val credentials = DeviceCredentials(
        "http://10.0.1.64:8770",
        "pilot-tv-media-room",
        "device-secret",
    )

    @Test
    fun parsesDeviceManifestWithoutAdministrativeData() {
        val manifest = PilotJson.manifest(
            JSONObject(
                """
                {
                  "schema_version":"pilot.client.v1",
                  "core_version":"0.25.0",
                  "registry_revision":"abc123",
                  "device":{"id":"pilot-tv-media-room","name":"Pilot TV","room_id":"media-room","capabilities":["display","media-control","home-read"]},
                  "room":{"id":"media-room","name":"Media Room"},
                  "features":{"media":true,"home":true,"meetings":false},
                  "realtime":{"cursor":42}
                }
                """.trimIndent(),
            ),
            credentials,
        )

        assertEquals(PILOT_CLIENT_SCHEMA, manifest.schemaVersion)
        assertEquals("Media Room", manifest.roomName)
        assertTrue(manifest.supports("media-control"))
        assertFalse("meetings" in manifest.featureFlags)
        assertEquals(42L, manifest.eventCursor)
    }

    @Test
    fun parsesRichMediaEnergyAndCuratedHomeState() {
        val manifest = DeviceManifest(
            PILOT_CLIENT_SCHEMA,
            "0.25.0",
            "abc123",
            "pilot-tv-media-room",
            "Pilot TV",
            "media-room",
            "Media Room",
            setOf("display", "media-control", "home-read"),
            setOf("media", "home"),
            42,
        )
        val media = JSONObject(
            """
            {
              "rooms":[{"id":"media-room","name":"Media Room","default_music_player_id":"media-room-heos","players":[{"id":"media-room-heos","room_id":"media-room","name":"Denon","kind":"music","protocol":"heos","control_enabled":true}]}],
              "media":{"observed_at":"2026-07-22T10:00:00Z","players":{"media-room-heos":{"status":"ok","player":{"id":"media-room-heos","room_id":"media-room","name":"Denon","kind":"music","protocol":"heos","control_enabled":true},"capabilities":["play","pause","stop","set_volume","transfer"],"effective":{"available":true,"powered":true,"playback_state":"playing","volume_percent":35,"muted":false,"position_seconds":70,"duration_seconds":140,"media":{"title":"Time","artist":"Pink Floyd","album":"The Dark Side of the Moon","artwork_url":"/v1/artwork/test"},"queue":{"index":0,"items":[{"id":"one","title":"Time","artist":"Pink Floyd"},{"id":"two","title":"Money","artist":"Pink Floyd"}]}}}}}
            }
            """.trimIndent(),
        )
        val surface = JSONObject(
            """{"energy":{"status":"ok","solar":{"value":8600,"unit":"W"},"home_load":{"value":2900,"unit":"W"},"grid":{"value":-5000,"unit":"W","direction":"exporting"},"battery":{"value":700,"unit":"W","direction":"charging"},"battery_soc":{"value":84,"unit":"%"}}}""",
        )
        val home = JSONObject(
            """
            {"room":{"id":"media-room","name":"Media Room"},"entities":[
              {"entity_id":"light.media_room","name":"Ceiling lights","state":"off","presentation":{"included":true,"category":"lighting","section":"overview","priority":10,"display_name":"Ceiling lights"}},
              {"entity_id":"sensor.receiver_rssi","state":"-61","presentation":{"included":false,"reason":"diagnostic"}}
            ]}
            """.trimIndent(),
        )

        val snapshot = PilotJson.snapshot(manifest, media, surface, home)

        assertEquals("Time", snapshot.nowPlaying?.media?.title)
        assertEquals(0.5f, snapshot.nowPlaying?.progress)
        assertEquals(2, snapshot.nowPlaying?.queue?.size)
        assertEquals("8.6 kW", snapshot.energy?.solar?.display())
        assertEquals(1, snapshot.home?.entities?.size)
        assertEquals("Ceiling lights", snapshot.home?.entities?.single()?.name)
        assertNull(snapshot.revision)
    }
}
