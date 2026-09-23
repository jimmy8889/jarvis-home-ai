package com.jarvis.pilotwall

import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
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

    @Test
    fun inactiveHistorySamplesSplitStepSeriesInsteadOfDrawingRamps() {
        val points = listOf(0.0, -120.0, -7200.0, -30.0, -6500.0, 0.0)
            .mapIndexed { index, value -> DashboardPoint(null, value) }
        val series = DashboardSeries(
            id = "tesla",
            label = "Tesla",
            color = "#D970FF",
            points = points,
            activityThresholdW = 100.0,
            renderMode = "step",
        )

        assertEquals(
            listOf(listOf(-120.0, -7200.0), listOf(-6500.0)),
            visibleHistorySegments(series).map { segment -> segment.map(DashboardPoint::value) },
        )
    }

    private fun vehicle(connected: Boolean, watts: Double) = DashboardVehicle(
        connected = connected,
        charging = watts >= VEHICLE_ACTIVITY_THRESHOLD_W,
        powerW = watts,
        socPercent = 70.0,
    )
}
