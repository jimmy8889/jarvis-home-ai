package com.jarvis.pilotwall

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PilotEnergyRulesTest {
    @Test
    fun hidesVehicleEnergyUntilDrawIsMeaningful() {
        assertFalse(shouldShowVehicleEnergy(vehicle(connected = true, watts = 1.6)))
        assertFalse(shouldShowVehicleEnergy(vehicle(connected = true, watts = 99.9)))
        assertTrue(shouldShowVehicleEnergy(vehicle(connected = true, watts = 100.0)))
        assertFalse(shouldShowVehicleEnergy(vehicle(connected = false, watts = 7200.0)))
    }

    @Test
    fun solarFallbackSelectsDayAndNightScenes() {
        assertFalse(isDayEnergyScene(null))
        assertFalse(isDayEnergyScene(99.9))
        assertTrue(isDayEnergyScene(100.0))
    }

    private fun vehicle(connected: Boolean, watts: Double) = DashboardVehicle(
        connected = connected,
        charging = watts >= VEHICLE_ACTIVITY_THRESHOLD_W,
        powerW = watts,
        socPercent = 70.0,
    )
}
