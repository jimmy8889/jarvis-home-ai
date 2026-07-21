package com.jarvis.pilotwall

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PilotClientContractTest {
    private val fixture: JSONObject by lazy {
        val text = checkNotNull(javaClass.classLoader?.getResourceAsStream("contracts/pilot-client-v1.json"))
            .bufferedReader().use { it.readText() }
        JSONObject(text)
    }

    @Test
    fun decodesCanonicalManifestAndResumableEvents() {
        val manifest = PilotJson.manifest(fixture.getJSONObject("manifest"))
        assertEquals("pilot.client.v1", manifest.schema)
        assertTrue("live_events" in manifest.features)
        assertEquals(
            "/v1/devices/{device_id}/events/snapshot",
            manifest.eventSnapshotPath,
        )
        assertEquals("/v1/devices/{device_id}/events", manifest.eventLongPollPath)

        val page = PilotJson.events(fixture.getJSONObject("events"))
        assertEquals("event-43", page.cursor)
        assertFalse(page.resetRequired)
        assertEquals("home.entity.changed", page.events.single().type)
    }

    @Test
    fun honorsCuratedPresentationAndRemovesDuplicates() {
        val projection = PilotJson.home(fixture.getJSONObject("home"))
        assertEquals(2, projection.entities.size)
        val lamp = projection.entities.first()
        assertEquals("Desk lamp", lamp.displayName)
        assertEquals("Favourites", lamp.section)
        assertEquals(HomeControlKind.Light, lamp.controlKind)
        assertEquals("registry", lamp.presentation.roomTrust)
        assertTrue(lamp.presentation.roomAuthoritative)

        val temperature = projection.entities.single { it.entityId == "sensor.office_temperature" }
        assertEquals(23.4, temperature.numericValue!!, 0.01)
        assertEquals("°C", temperature.unit)
        assertNull(projection.entities.firstOrNull { it.entityId.endsWith("duplicate") })
    }

    @Test
    fun decodesRichNowPlayingQueueAndAssistantResults() {
        val media = PilotJson.media(fixture.getJSONObject("media"))
        val player = media.players.single()
        assertEquals("media-42", media.revision)
        assertEquals(62.0, player.effective.positionSeconds!!, 0.01)
        assertTrue("seek" in player.effective.capabilities)
        assertEquals("Angel", media.queues.getValue("office-n150").items[1].title)

        val assistant = PilotJson.assistant(fixture.getJSONObject("assistant"))
        assertEquals("complete", assistant.status)
        assertEquals("Office temperature", assistant.cards.single().title)
        assertEquals("Home Assistant", assistant.sources.single().label)
    }

    @Test
    fun parsesSingleUsePairingLinksWithoutPersistingTheGrant() {
        val payload = PairingPayload.parse(
            "pilot://pair?core=http%3A%2F%2F10.0.1.64%3A8770&grant=one-time-secret",
        )
        assertEquals("http://10.0.1.64:8770/", payload.coreUrl)
        assertEquals("one-time-secret", payload.grantToken)
    }
}
