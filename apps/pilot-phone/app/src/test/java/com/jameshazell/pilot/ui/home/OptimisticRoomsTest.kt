package com.jameshazell.pilot.ui.home

import com.jameshazell.pilot.ui.home.HomeFixtures.entity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class OptimisticRoomsTest {
    private val rooms = OptimisticRooms(HomeFixtures.projections)
    private val shelf = HomeFixtures.living.entities.first { it.entityId == "light.living_shelf" }
    private val ceiling = HomeFixtures.living.entities.first { it.entityId == "light.living_ceiling" }
    private val climate = HomeFixtures.living.entities.first { it.entityId == "climate.living" }

    private fun OptimisticRooms.light(id: String) = visible("living")!!.entities.first { it.entityId == id }

    @Test fun beginShowsTheExpectedStateWithoutTouchingConfirmedData() {
        val next = rooms.begin(EntityCommand(shelf, "turn_on"))
        assertTrue(next.light("light.living_shelf").isLit)
        assertFalse(next.confirmed.getValue("living").entities.first { it.entityId == shelf.entityId }.isLit)
        // Other rooms and devices are untouched.
        assertEquals(HomeFixtures.kitchen, next.visible("kitchen"))
        assertEquals(ceiling, next.light("light.living_ceiling"))
    }

    @Test fun rollbackRestoresTheConfirmedState() {
        val failed = rooms.begin(EntityCommand(shelf, "turn_on")).rollback(shelf.entityId)
        assertEquals(rooms, failed)
        assertFalse(failed.light("light.living_shelf").isLit)
    }

    @Test fun confirmReplacesTheRoomAndSettlesFinishedCommandsOnly() {
        val pending = rooms
            .begin(EntityCommand(shelf, "turn_on"))
            .begin(EntityCommand(ceiling, "turn_off"))
        val fresh = HomeFixtures.living.copy(
            entities = HomeFixtures.living.entities.map {
                if (it.entityId == shelf.entityId) it.copy(state = "on", brightnessPercent = 100f) else it
            },
        )
        val next = pending.confirm(fresh, settled = setOf(shelf.entityId))
        // The settled light shows what Pilot Core reported...
        assertEquals(100f, next.light("light.living_shelf").brightnessPercent)
        // ...while the command still in flight keeps its optimistic state.
        assertFalse(next.light("light.living_ceiling").isLit)
        assertEquals(setOf(ceiling.entityId), next.pending.keys)
    }

    @Test fun aRefreshDuringACommandDoesNotFlickerBack() {
        val pending = rooms.begin(EntityCommand(shelf, "turn_on"))
        val next = pending.confirm(HomeFixtures.living)
        assertTrue(next.light("light.living_shelf").isLit)
    }

    @Test fun promoteKeepsASucceededChangeWhenTheRoomCannotBeReloaded() {
        val next = rooms.begin(EntityCommand(shelf, "turn_on")).promote("living", setOf(shelf.entityId))
        assertTrue(next.pending.isEmpty())
        assertTrue(next.confirmed.getValue("living").entities.first { it.entityId == shelf.entityId }.isLit)
        // Unknown room: the pending change is simply dropped.
        assertTrue(rooms.begin(EntityCommand(shelf, "turn_on")).promote("nowhere", setOf(shelf.entityId)).pending.isEmpty())
    }

    @Test fun commandsWithoutAVisibleEffectAddNothing() {
        val scene = HomeFixtures.living.entities.first { it.entityId == "scene.living_movie" }
        assertSame(rooms, rooms.begin(EntityCommand(scene, "activate")))
        assertSame(rooms, rooms.begin(EntityCommand(shelf, "turn_off")))
    }

    @Test fun commandsStackOnTheSameDevice() {
        val next = rooms
            .begin(EntityCommand(climate, "set_hvac_mode", option = "heat"))
            .begin(EntityCommand(climate, "set_temperature", 21.0))
        val shown = next.visible("living")!!.entities.first { it.entityId == climate.entityId }
        assertEquals("heat", shown.state)
        assertEquals(21.0, shown.targetTemperature!!, 0.001)
    }

    @Test fun optimisticEntityCoversEveryAction() {
        assertEquals("on", optimisticEntity(shelf, "turn_on", null).state)
        assertEquals("off", optimisticEntity(ceiling, "toggle", null).state)
        val dimmed = optimisticEntity(shelf, "set_brightness", 30.0)
        assertEquals(30f, dimmed.brightnessPercent)
        assertEquals("on", dimmed.state)
        assertEquals("off", optimisticEntity(climate, "set_hvac_mode", null, "off").state)
        assertEquals(climate, optimisticEntity(climate, "set_hvac_mode", null, null))
        assertEquals("unlocked", optimisticEntity(entity("lock.a", "A", "locked"), "unlock", null).state)
        assertEquals("opening", optimisticEntity(entity("cover.a", "A", "closed"), "open", null).state)
        assertEquals(40f, optimisticEntity(entity("cover.a", "A", "open"), "set_position", 40.0).positionPercent)
        assertEquals(55f, optimisticEntity(entity("fan.a", "A", "on"), "set_percentage", 55.0).percentage)
        assertEquals("disarmed", optimisticEntity(entity("alarm_control_panel.a", "A", "armed_home"), "disarm", null).state)
        val stopped = entity("cover.a", "A", "opening")
        assertEquals(stopped, optimisticEntity(stopped, "stop", null))
    }

    @Test fun keepOnlyForgetsRemovedRooms() {
        val next = rooms.keepOnly(setOf("living", "kitchen"))
        assertEquals(setOf("living", "kitchen"), next.confirmed.keys)
        assertNull(next.visible("garage"))
        assertSame(rooms, rooms.keepOnly(HomeFixtures.projections.keys + "new"))
    }
}
