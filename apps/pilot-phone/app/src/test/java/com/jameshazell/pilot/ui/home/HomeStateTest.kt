package com.jameshazell.pilot.ui.home

import com.jameshazell.pilot.data.pilot.PilotCoreClient
import com.jameshazell.pilot.data.pilot.PilotJson
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HomeStateTest {
    @Test fun homeStateSummarisesEveryRoomInCoreOrder() {
        val state = HomeFixtures.state()
        assertEquals(listOf("Living Room", "Kitchen", "Master Bedroom", "Garage"), state.rooms.map { it.name })
        assertEquals(2, state.house.lightsOn)
        assertNull(state.openRoom)
        assertTrue(state.controlsEnabled)
        assertNull(state.controlNotice)
        // The bedroom has an aircon reading; the dashboard label match is only a fallback.
        assertEquals(21.3, state.rooms[2].temperatureC!!, 0.001)
    }

    @Test fun openRoomCarriesItsDevicesAndPlayers() {
        val open = HomeFixtures.state(openRoomId = "living").openRoom!!
        assertEquals("Living Room", open.summary.name)
        assertEquals(3, open.content.lights.size)
        assertEquals(listOf("living-speaker"), open.players.map { it.player.id })
        assertNull(open.loadError)
        assertNull(HomeFixtures.state(openRoomId = "gone").openRoom)
    }

    @Test fun pendingChangesShowInTilesAndDetail() {
        val shelf = HomeFixtures.living.entities.first { it.entityId == "light.living_shelf" }
        val local = HomeLocalState(
            rooms = OptimisticRooms(HomeFixtures.projections).begin(EntityCommand(shelf, "turn_on")),
            openRoomId = "living",
            busy = setOf(shelf.entityId),
        )
        val state = buildHomeState(HomeFixtures.snapshot, online = true, canControl = true, local = local)
        assertEquals(3, state.rooms[0].lightsOn)
        assertEquals(3, state.house.lightsOn)
        assertTrue(state.openRoom!!.content.lights.all { it.isLit })
        assertEquals(setOf(shelf.entityId), state.busy)
    }

    @Test fun controlsAreDisabledOfflineOrReadOnlyWithAReason() {
        val offline = HomeFixtures.state(online = false)
        assertFalse(offline.controlsEnabled)
        assertEquals("Reconnect to control devices. Saved data is read-only.", offline.controlNotice)
        val readOnly = HomeFixtures.state(canControl = false)
        assertFalse(readOnly.controlsEnabled)
        assertEquals("This phone can view room devices but not control them.", readOnly.controlNotice)
    }

    @Test fun roomsWithoutLoadedDevicesStillAppear() {
        val state = buildHomeState(HomeFixtures.snapshot, online = false, canControl = false, local = HomeLocalState())
        assertEquals(4, state.rooms.size)
        assertTrue(state.rooms.none { it.loaded })
        assertFalse(state.house.lightsKnown)
        // Now playing comes from the snapshot, so it is known even without devices.
        assertTrue(state.rooms[0].playing)
    }

    @Test fun roomLoadErrorReachesTheOpenRoom() {
        val local = HomeLocalState(openRoomId = "kitchen", roomErrors = mapOf("kitchen" to "Pilot Core took too long to answer."))
        val open = buildHomeState(HomeFixtures.snapshot, true, true, local).openRoom!!
        assertEquals("Pilot Core took too long to answer.", open.loadError)
        assertFalse(open.summary.loaded)
        assertTrue(open.content.isEmpty)
    }

    // ---- The additive Pilot Core client changes Home relies on --------------------------------

    @Test fun hvacModeIsSentAsATextValue() {
        val body = PilotCoreClient.homeActionBody("living", "climate.living", "set_hvac_mode", null, "cool")
        assertEquals("cool", body.getJSONObject("parameters").getString("value"))
        val numeric = PilotCoreClient.homeActionBody("living", "climate.living", "set_temperature", 22.5, null)
        assertEquals(22.5, numeric.getJSONObject("parameters").getDouble("value"), 0.001)
        val none = PilotCoreClient.homeActionBody("living", "light.a", "turn_on", null)
        assertEquals(0, none.getJSONObject("parameters").length())
    }

    @Test fun climateReadingsAreParsedFromTheProjection() {
        val projection = PilotJson.home(
            JSONObject(
                """
                {"room": {"id": "living", "name": "Living Room"}, "entities": [
                  {"entity_id": "climate.living", "domain": "climate", "name": "Aircon", "state": "cool",
                   "attributes": {"current_temperature": 24.6, "temperature": 23, "humidity": 51},
                   "presentation": {"supported_actions": ["turn_on", "turn_off", "set_temperature", "set_hvac_mode"]}}
                ]}
                """.trimIndent(),
            ),
        )
        val climate = projection.entities.single()
        assertEquals(24.6, climate.currentTemperature!!, 0.001)
        assertEquals(51.0, climate.humidity!!, 0.001)
        assertEquals(23.0, climate.targetTemperature!!, 0.001)
        assertEquals(24.6, roomTemperature("Living Room", projection.entities)!!, 0.001)
    }
}
