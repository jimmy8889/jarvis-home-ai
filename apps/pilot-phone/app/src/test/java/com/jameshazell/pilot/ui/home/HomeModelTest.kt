package com.jameshazell.pilot.ui.home

import com.jameshazell.pilot.data.pilot.DashboardTemperature
import com.jameshazell.pilot.data.pilot.HomeControlKind
import com.jameshazell.pilot.data.pilot.HomeProjection
import com.jameshazell.pilot.data.pilot.SurfaceEnergy
import com.jameshazell.pilot.data.pilot.SurfaceMeasurement
import com.jameshazell.pilot.ui.home.HomeFixtures.entity
import com.jameshazell.pilot.ui.home.HomeFixtures.light
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HomeModelTest {
    // ---- Room summaries ---------------------------------------------------------------------

    @Test fun roomSummaryCountsLightsAndReadsClimateTemperature() {
        val summary = summariseRoom(HomeFixtures.rooms[0], HomeFixtures.living, HomeFixtures.players)
        assertEquals(2, summary.lightsOn)
        assertEquals(3, summary.lightsTotal)
        assertEquals(24.6, summary.temperatureC!!, 0.001)
        assertTrue(summary.active)
        assertTrue(summary.climateActive)
        assertTrue(summary.playing)
        assertTrue(summary.canToggleLights)
        assertEquals("24.6° · 2 of 3 on · Climate on · Playing", summary.status)
    }

    @Test fun roomSummaryFallsBackToSensorThenDashboardTemperature() {
        val kitchen = summariseRoom(HomeFixtures.rooms[1], HomeFixtures.kitchen)
        assertEquals(22.4, kitchen.temperatureC!!, 0.001)
        assertEquals("22.4° · Lights off", kitchen.status)
        assertFalse(kitchen.active)

        val noReadings = HomeProjection("bedroom", "Master Bedroom", listOf(light("b", "Lamp", on = false)))
        val fromDashboard = summariseRoom(
            HomeFixtures.rooms[2], noReadings,
            dashboardTemperatures = listOf(DashboardTemperature("x", " master bedroom ", 19.5)),
        )
        assertEquals(19.5, fromDashboard.temperatureC!!, 0.001)
        assertNull(summariseRoom(HomeFixtures.rooms[2], noReadings).temperatureC)
    }

    @Test fun roomWithoutDevicesInventsNothing() {
        val unloaded = summariseRoom(HomeFixtures.rooms[3], null)
        assertFalse(unloaded.loaded)
        assertEquals("", unloaded.status)
        assertFalse(unloaded.canToggleLights)
        assertNull(unloaded.temperatureC)

        val empty = summariseRoom(HomeFixtures.rooms[3], HomeProjection("garage", "Garage", emptyList()))
        assertEquals("No devices", empty.status)
    }

    @Test fun unavailableLightsAreNeitherOnNorSwitchable() {
        val summary = summariseRoom(HomeFixtures.rooms[3], HomeFixtures.garage)
        assertEquals(0, summary.lightsOn)
        assertEquals(1, summary.lightsTotal)
        assertFalse(summary.canToggleLights)
    }

    @Test fun houseSummaryCountsAcrossRooms() {
        val house = summariseHouse(HomeFixtures.snapshot, HomeFixtures.projections)
        assertEquals(2, house.lightsOn)
        assertTrue(house.lightsKnown)
        assertEquals(1, house.climateActive)
        assertEquals(1, house.playing)
        assertEquals(0, house.unlocked)
        assertTrue(house.carCharging)
        assertFalse(summariseHouse(HomeFixtures.snapshot, emptyMap()).lightsKnown)
    }

    @Test fun allLightsOffTargetsOnlyLitLights() {
        val commands = allLightsOff(HomeFixtures.projections)
        assertEquals(listOf("light.living_ceiling", "light.living_lamp"), commands.map { it.second.entity.entityId })
        assertTrue(commands.all { it.first == "living" && it.second.action == "turn_off" })
    }

    // ---- Room power button and brightness ---------------------------------------------------

    @Test fun roomToggleSwitchesLitLightsOffOrEverythingOn() {
        val living = HomeFixtures.living.entities.filter { it.isLight }
        val off = roomLightToggle(living)
        assertEquals(listOf("turn_off", "turn_off"), off.map { it.action })
        assertEquals(setOf("light.living_ceiling", "light.living_lamp"), off.map { it.entity.entityId }.toSet())

        val kitchen = HomeFixtures.kitchen.entities.filter { it.isLight }
        assertEquals(listOf("turn_on", "turn_on"), roomLightToggle(kitchen).map { it.action })

        assertTrue(roomLightToggle(HomeFixtures.garage.entities.filter { it.isLight }).isEmpty())
        val readOnly = living.map { it.copy(actions = emptyList()) }
        assertTrue(roomLightToggle(readOnly).isEmpty())
    }

    @Test fun brightnessAveragesLitLightsAndTargetsThem() {
        val living = HomeFixtures.living.entities.filter { it.isLight }
        assertEquals(60, averageBrightness(living))
        assertEquals(listOf("light.living_ceiling", "light.living_lamp"), brightnessTargets(living).map { it.entityId })

        val kitchen = HomeFixtures.kitchen.entities.filter { it.isLight }
        assertNull(averageBrightness(kitchen))
        assertEquals(2, brightnessTargets(kitchen).size)
    }

    // ---- Entity → control mapping -----------------------------------------------------------

    @Test fun roomContentSortsDevicesIntoCardsByKindAndPriority() {
        val content = roomContent(HomeFixtures.living)
        assertEquals(listOf("Ceiling", "Floor lamp", "Shelf strip"), content.lights.map { it.displayName })
        assertEquals(listOf("Movie", "Evening"), content.scenes.map { it.displayName })
        assertEquals(listOf("climate.living"), content.climates.map { it.entityId })
        assertEquals(listOf("cover.living_blinds"), content.covers.map { it.entityId })
        assertEquals(listOf("fan.living_purifier"), content.fans.map { it.entityId })
        assertTrue(content.locks.isEmpty())
        // The rest keeps Pilot Core's section names, most important group first.
        assertEquals(listOf("Controls", "Environment", "Status"), content.others.map { it.title })
        assertEquals(listOf("switch.living_tv"), content.others[0].entities.map { it.entityId })
        assertFalse(content.isEmpty)
        assertTrue(roomContent(null).isEmpty)
    }

    @Test fun roomContentHonoursPresentationOverridesAndDropsMediaPlayers() {
        val projection = HomeProjection(
            "x", "X",
            listOf(
                entity("switch.lamp_plug", "Lamp plug", "on", listOf("turn_on", "turn_off"))
                    .let { it.copy(presentation = it.presentation.copy(control = "light", displayName = "Reading lamp")) },
                entity("media_player.tv", "TV", "playing"),
                entity("alarm_control_panel.house", "Alarm", "disarmed", listOf("arm_home", "arm_away", "disarm")),
            ),
        )
        val content = roomContent(projection)
        assertEquals(listOf("Reading lamp"), content.lights.map { it.displayName })
        assertEquals(HomeControlKind.Lock, content.locks.single().controlKind)
        assertTrue(content.others.isEmpty())
    }

    @Test fun stateLabelsAreWordsNotRawStates() {
        assertEquals("On · 80%", stateLabel(light("a", "A", on = true, brightness = 80f)))
        assertEquals("Off", stateLabel(light("a", "A", on = false)))
        assertEquals("Unavailable", stateLabel(light("a", "A", on = true).copy(unavailable = true)))
        assertEquals("Open · 70% open", stateLabel(HomeFixtures.living.entities.first { it.entityId == "cover.living_blinds" }))
        assertEquals("Closed", stateLabel(HomeFixtures.garage.entities.first { it.entityId == "cover.garage_door" }))
        assertEquals("52%", stateLabel(HomeFixtures.living.entities.first { it.entityId == "sensor.living_humidity" }))
        assertEquals("22.4 °C".replace(" ", ""), stateLabel(HomeFixtures.kitchen.entities.last()))
        assertEquals("Open", stateLabel(HomeFixtures.living.entities.first { it.entityId == "binary_sensor.living_window" }))
        assertEquals("Armed home", stateLabel(entity("alarm_control_panel.h", "Alarm", "armed_home")))
        assertEquals("1250 W", stateLabel(entity("sensor.p", "Power", "1250.4", unit = "W")))
    }

    @Test fun climateStatusAndTargetStepping() {
        val cooling = HomeFixtures.living.entities.first { it.entityId == "climate.living" }
        assertEquals("Cooling to 23°", climateStatus(cooling))
        assertEquals("Heating to 21.5°", climateStatus(cooling.copy(state = "heat", targetTemperature = 21.5)))
        assertEquals("Off", climateStatus(cooling.copy(state = "off")))
        assertEquals("Unavailable", climateStatus(cooling.copy(unavailable = true)))
        assertTrue(cooling.copy(state = "fan_only").climateActive)
        assertFalse(cooling.copy(state = "off").climateActive)

        assertEquals(23.5, steppedTarget(cooling, +1)!!, 0.001)
        assertEquals(22.5, steppedTarget(cooling, -1)!!, 0.001)
        assertEquals(35.0, steppedTarget(cooling.copy(targetTemperature = 35.0), +1)!!, 0.001)
        assertEquals(10.0, steppedTarget(cooling.copy(targetTemperature = 10.0), -1)!!, 0.001)
        assertNull(steppedTarget(cooling.copy(targetTemperature = null), +1))
        assertEquals("Fan", hvacModeLabel("fan_only"))
    }

    // ---- Confirmation policy ----------------------------------------------------------------

    @Test fun garageLikeCoversAreRecognised() {
        val garage = HomeFixtures.garage.entities.first { it.entityId == "cover.garage_door" }
        val blinds = HomeFixtures.living.entities.first { it.entityId == "cover.living_blinds" }
        assertTrue(garage.isGarageLike)
        assertFalse(blinds.isGarageLike)
        assertTrue(entity("cover.front_gate", "Front gate", "closed").isGarageLike)
        assertTrue(entity("cover.x", "Roller Door", "closed").isGarageLike)
        // A light in the garage is not a garage door.
        assertFalse(light("garage_light", "Garage light", on = false).isGarageLike)
    }

    @Test fun garageMovesAndEveryLockCommandNeedConfirmation() {
        val garage = HomeFixtures.garage.entities.first { it.entityId == "cover.garage_door" }
        val lock = HomeFixtures.garage.entities.first { it.entityId == "lock.garage_entry" }
        val blinds = HomeFixtures.living.entities.first { it.entityId == "cover.living_blinds" }

        val open = confirmationFor(garage, "open")
        assertNotNull(open)
        assertEquals("Open Garage door?", open!!.title)
        assertEquals("Open", open.confirmLabel)
        assertNotNull(confirmationFor(garage, "close"))
        assertNotNull(confirmationFor(garage, "set_position"))
        // Stopping a moving door must be instant.
        assertNull(confirmationFor(garage, "stop"))

        assertTrue(confirmationFor(lock, "unlock")!!.destructive)
        assertNotNull(confirmationFor(lock, "lock"))
        assertNotNull(confirmationFor(entity("alarm_control_panel.h", "Alarm", "armed_home"), "disarm"))

        assertNull(confirmationFor(blinds, "open"))
        assertNull(confirmationFor(light("a", "A", on = false), "turn_on"))
    }

    // ---- Header and energy ------------------------------------------------------------------

    @Test fun greetingFollowsTheClock() {
        assertEquals("Good morning", greetingFor(5))
        assertEquals("Good morning", greetingFor(11))
        assertEquals("Good afternoon", greetingFor(12))
        assertEquals("Good evening", greetingFor(18))
        assertEquals("Good night", greetingFor(22))
        assertEquals("Good night", greetingFor(3))
    }

    @Test fun weatherChipOnlyWhenTheDashboardHasWeather() {
        assertEquals("24° Partly cloudy", weatherChip(HomeFixtures.dashboard)!!.label)
        assertNull(weatherChip(null))
        val none = HomeFixtures.dashboard.copy(weather = HomeFixtures.dashboard.weather.copy(condition = null, temperatureC = null))
        assertNull(weatherChip(none))
    }

    @Test fun energySummaryFromDashboard() {
        val energy = energySummary(HomeFixtures.snapshot)!!
        assertEquals(EnergyReading("4.2", "kW"), energy.solar)
        assertEquals(EnergyReading("1.8", "kW"), energy.house)
        assertEquals(EnergyReading("82", "%", "Charging 600 W"), energy.battery)
        // Export is shown as a magnitude with its direction in words, never a negative number.
        assertEquals(EnergyReading("1.9", "kW", "Exporting"), energy.grid)
    }

    @Test fun energySummaryFallsBackToSurfaceAndHidesWhenEmpty() {
        val bare = HomeFixtures.snapshot.copy(dashboard = null)
        assertNull(energySummary(bare))

        fun reading(value: Double?, direction: String? = null) = SurfaceMeasurement(value, "W", direction, null)
        val surface = bare.copy(
            surface = bare.surface.copy(
                energy = SurfaceEnergy("ok", reading(900.0), reading(120.0, "importing"), reading(null), SurfaceMeasurement(null, "%", null, null), reading(1020.0)),
            ),
        )
        val energy = energySummary(surface)!!
        assertEquals(EnergyReading("900", "W"), energy.solar)
        assertEquals(EnergyReading("120", "W", "Importing"), energy.grid)
        // Unknown stays unknown; it is never shown as zero.
        assertEquals("—", energy.battery.value)
    }

    @Test fun groupFailureWording() {
        assertEquals("Offline.", groupFailureMessage(1, 1, "Offline."))
        assertEquals("Offline.", groupFailureMessage(3, 3, "Offline."))
        assertEquals("1 of 3 devices didn't respond. Offline.", groupFailureMessage(1, 3, "Offline."))
    }
}
