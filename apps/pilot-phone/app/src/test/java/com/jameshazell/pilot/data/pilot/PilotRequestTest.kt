package com.jameshazell.pilot.data.pilot

import com.jameshazell.pilot.fieldNames
import com.jameshazell.pilot.core.HttpClients
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.core.PilotConfig
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PilotRequestTest {
    private val client = PilotCoreClient(HttpClients(), PilotConfig("https://pilot.example.net/", "fold 7"), "token")

    @Test fun eventPathsResolveTheDeviceAndAddCursorAndLongPoll() {
        assertEquals(
            "v1/devices/fold 7/events/snapshot",
            client.eventPath("/v1/devices/{device_id}/events/snapshot", null, longPoll = false),
        )
        assertEquals(
            "v1/devices/fold 7/events?cursor=event+43%2Fa&timeout_seconds=25",
            client.eventPath("/v1/devices/{id}/events", "event 43/a", longPoll = true),
        )
        assertEquals(
            "v1/events?room=a&timeout_seconds=25",
            client.eventPath("v1/events?room=a", "", longPoll = true),
        )
    }

    @Test fun homeActionBodyAlwaysCarriesParameters() {
        val plain = PilotCoreClient.homeActionBody("office", "light.desk", "turn_on", null)
        assertEquals(setOf("room_id", "entity_id", "action", "parameters"), plain.fieldNames())
        assertEquals(0, plain.getJSONObject("parameters").length())
        val level = PilotCoreClient.homeActionBody("office", "light.desk", "set_brightness", 40.0)
        assertEquals(40.0, level.getJSONObject("parameters").getDouble("value"), 0.0)
    }

    @Test fun mediaCommandBodyOmitsUnsetFields() {
        val body = PilotCoreClient.mediaCommandBody(MediaCommand(action = "set_volume", playerId = "p1", volume = 30))
        assertEquals(setOf("action", "player_id", "volume"), body.fieldNames())
        val transfer = PilotCoreClient.mediaCommandBody(
            MediaCommand("transfer", playerId = "p1", targetRoomId = "lounge", targetPlayerId = "p2", muted = false),
        )
        assertEquals(setOf("action", "player_id", "target_room_id", "target_player_id", "muted"), transfer.fieldNames())
    }

    private val envelope = JSONObject(
        """{"media":{"rooms":[{"id":"office","name":"Office","players":[]}],"media":{"players":{}}},
            "surface":{"now_playing":[]},
            "dashboard":{"status":"partial"},
            "saved_at":"2026-11-12T01:00:00Z"}""",
    )

    @Test fun savedSnapshotEnvelopeDecodes() {
        val snapshot = PilotRepository.decodeEnvelope(envelope, fromCache = true)
        assertEquals("Office", snapshot.media.rooms.single().name)
        assertEquals("2026-11-12T01:00:00Z", snapshot.receivedAt.toString())
        assertTrue(snapshot.fromCache)
        envelope.remove("dashboard")
        assertEquals(null, PilotRepository.decodeEnvelope(envelope, fromCache = false).dashboard)
    }

    /** Ported from 1.x DashboardConnectionTest. */
    @Test fun missingSensorsDoNotMeanDisconnected() {
        fun live(status: String?) = LoadState.Content(
            PilotRepository.decodeEnvelope(
                JSONObject(envelope.toString()).put("dashboard", status?.let { JSONObject().put("status", it) }),
                fromCache = false,
            ),
        )
        assertEquals("Live", PilotRepository.dashboardLabel(live("ok")))
        assertEquals("Connected · some readings unavailable", PilotRepository.dashboardLabel(live("partial")))
        assertEquals("Connected · readings unavailable", PilotRepository.dashboardLabel(live("unavailable")))
        assertEquals("Connected · readings unavailable", PilotRepository.dashboardLabel(live(null)))
        assertEquals("Saved", PilotRepository.dashboardLabel(live("ok").copy(stale = true)))
        assertEquals("Connecting", PilotRepository.dashboardLabel(LoadState.Loading))
        assertEquals("Not connected", PilotRepository.dashboardLabel(LoadState.Loading, paired = false))
    }

    @Test fun readOnlyPhonesGetNoDeviceActions() {
        val projection = PilotJson.home(
            JSONObject(
                """{"room":{"id":"office","name":"Office"},"entities":[
                   {"entity_id":"light.desk","domain":"light","name":"Desk","state":"off","actions":["turn_on"]}]}""",
            ),
        )
        with(PilotRepository) {
            assertTrue(projection.readOnlyUnless(false).entities.single().actions.isEmpty())
            assertEquals(listOf("turn_on"), projection.readOnlyUnless(true).entities.single().actions)
        }
        val lamp = projection.entities.single()
        assertTrue(PilotRepository.optimisticEntity(lamp, "turn_on", null).isOn)
        assertFalse(PilotRepository.optimisticEntity(lamp, "refresh", null).isOn)
    }
}
