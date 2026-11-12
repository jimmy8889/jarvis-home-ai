package com.jameshazell.pilot.ui.energy

import com.jameshazell.pilot.data.energy.EnergyBootstrap
import com.jameshazell.pilot.data.energy.EnergyJson
import java.time.Instant
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The flow rules of the old app's NativeEnergyFlowTest and PilotEnergyRulesTest, on the new model. */
class HouseFlowTest {
    private val now = Instant.parse("2026-10-12T02:00:00Z") // midday in Brisbane

    private fun bootstrap(snapshot: String, points: String = "[]"): EnergyBootstrap =
        EnergyJson.bootstrap(JSONObject("""{"snapshot":$snapshot,"plan":{"rolling":{"points":$points}}}"""))

    private fun live(snapshot: String) = liveFlowState(bootstrap(snapshot), live = true, now = now)

    /** Healthy telemetry measured one second before [now], plus [devices]. */
    private fun fresh(telemetry: String = "", devices: String = "{}") = live(
        """{"telemetry":{"healthy":true,"measured_at":"2026-10-12T01:59:59Z"${if (telemetry.isEmpty()) "" else ",$telemetry"}},
            "devices":$devices,"service":{"workers":{"healthy":true}}}""",
    )

    private val parked = fresh(devices = """{"ev_ble_home":true,"ev_plugged":true,"ev_charging":true,"ev_power_kw":4.0}""")

    @Test fun controllerGraphSetsDirectionAndAvoidsDoubleCountingLoads() {
        val value = live(
            """{"telemetry":{"pv_kw":99,"load_kw":99},"power_flow":{"site_load_kw":6,
                "sources_kw":{"solar":10,"battery":0,"grid":0},
                "sinks_kw":{"house":2,"ev":4,"hot_water":0,"battery":3,"grid":1}}}""",
        )
        assertEquals(10.0, value.solarKw!!, 0.0)
        assertEquals(6.0, value.houseKw!!, 0.0)
        assertEquals("charging is negative", -3.0, value.batteryKw!!, 0.0)
        assertEquals("exporting is negative", -1.0, value.gridKw!!, 0.0)
        assertEquals(4.0, value.carKw!!, 0.0)
        assertEquals(0.0, value.waterKw!!, 0.0)
    }

    @Test fun telemetryIsUsedWhenTheControllerSentNoGraph() {
        val value = live(
            """{"telemetry":{"pv_kw":5.5,"load_kw":1.2,"grid_kw":-3,"battery_kw":-1.3,"soc_pct":71},
                "devices":{"ev_power_kw":0,"hot_water_power_kw":3.6,"ev_soc_pct":64},
                "server_rack":{"wall_input_w":312}}""",
        )
        assertEquals(5.5, value.solarKw!!, 0.0)
        assertEquals(1.2, value.houseKw!!, 0.0)
        assertEquals(-3.0, value.gridKw!!, 0.0)
        assertEquals(-1.3, value.batteryKw!!, 0.0)
        assertEquals(3.6, value.waterKw!!, 0.0)
        assertEquals(0.312, value.rackKw!!, 1e-9)
        assertEquals(71.0, value.socPct!!, 0.0)
        assertEquals(64.0, value.carSocPct!!, 0.0)
    }

    @Test fun missingMeasurementsNeverBecomeZero() {
        val value = live("{}")
        assertNull(value.solarKw)
        assertNull(value.gridKw)
        assertNull(value.batteryKw)
        assertNull(value.waterKw)
        assertNull(value.houseKw)
        assertNull(value.rackKw)
        assertEquals("—", formatPower(value.batteryKw))
        assertEquals("0 W", formatPower(0.0))
        assertNull(flowNet(null, null))
        assertEquals(-2.0, flowNet(null, 2.0)!!, 0.0)
        assertEquals("Unavailable", gridLabel(value.gridKw))
        assertEquals("Unavailable", batteryLabel(value.batteryKw))
    }

    @Test fun plannedStateUsesTheSelectedPointAndDoesNotInheritLiveLoads() {
        val data = bootstrap(
            """{"telemetry":{"load_kw":30,"battery_kw":9,"soc_pct":12},"server_rack":{"wall_input_w":700}}""",
            """[{"start":"2026-10-12T05:00:00Z","predicted_soc_pct":65,"server_rack_kw":0.4,
                 "flow":{"site_load_kw":2,"sources_kw":{"battery":2},"sinks_kw":{"house":2,"battery":0}}},
                {"start":"2026-10-12T05:05:00Z","pv_kw":1.5,"ev_kw":3,"grid_import_kw":0.5,"site_export_target_kw":2,
                 "battery_discharge_kw":0,"battery_charge_kw":1.2}]""",
        )
        val graphed = plannedFlowState(data, data.plan[0])
        assertTrue(graphed.planned)
        assertEquals(2.0, graphed.houseKw!!, 0.0)
        assertEquals(2.0, graphed.batteryKw!!, 0.0)
        assertEquals(0.4, graphed.rackKw!!, 0.0)
        assertEquals(65.0, graphed.socPct!!, 0.0)

        val plain = plannedFlowState(data, data.plan[1])
        assertEquals(1.5, plain.solarKw!!, 0.0)
        assertEquals(3.0, plain.carKw!!, 0.0)
        assertEquals(-1.5, plain.gridKw!!, 0.0)
        assertEquals(-1.2, plain.batteryKw!!, 0.0)
        assertNull("no planned house total without a graph", plain.houseKw)
        assertNull(plain.waterKw)
        assertNull(plain.socPct)
    }

    @Test fun carArtworkRequiresVerifiedBluetoothPresence() {
        val unverified = live("""{"devices":{"ev_home":true,"ev_plugged":true}}""")
        assertNull(unverified.carHome)
        assertEquals(true, unverified.carPlugged)
        assertEquals(true, live("""{"devices":{"ev_ble_home":true}}""").carHome)
        assertEquals(false, live("""{"devices":{"ev_ble_home":false}}""").carHome)
    }

    @Test fun dayAndNightFollowSolarThenTheBrisbaneClock() {
        val midnight = Instant.parse("2026-10-12T15:00:00Z") // 1 am in Brisbane
        assertFalse(isDaylight(null, midnight))
        assertFalse(isDaylight(0.0999, midnight))
        assertTrue("100 W of solar is daylight whatever the clock says", isDaylight(0.1, midnight))
        assertTrue("an overcast midday is still day", isDaylight(0.0, now))
        assertTrue("a missing solar reading does not turn the lights off", isDaylight(null, now))
        val data = bootstrap("{}", """[{"start":"2026-10-12T15:00:00Z","pv_kw":0},{"start":"2026-10-12T02:00:00Z","pv_kw":0}]""")
        assertFalse(plannedFlowState(data, data.plan[0]).daylight)
        assertTrue(plannedFlowState(data, data.plan[1]).daylight)
    }

    @Test fun chargingNeedsPresenceCableChargingAndAHundredWatts() {
        assertTrue(carFlowActive(parked))
        assertEquals("Charging", carStateLabel(parked))
        assertFalse(carFlowActive(parked.copy(carHome = false)))
        assertEquals("Away", carStateLabel(parked.copy(carHome = false)))
        assertFalse(carFlowActive(parked.copy(carPlugged = false)))
        assertEquals("Home · unplugged", carStateLabel(parked.copy(carPlugged = false)))
        assertFalse(carFlowActive(parked.copy(carCharging = false)))
        assertEquals("Plugged in · idle", carStateLabel(parked.copy(carCharging = false)))
        assertFalse(carFlowActive(parked.copy(carKw = 0.0999)))
        assertEquals("Plugged in · idle", carStateLabel(parked.copy(carKw = 0.05)))
        assertFalse(carFlowActive(parked.copy(carKw = -4.0)))
        assertFalse(carFlowActive(parked.copy(carKw = null)))
        assertTrue(carFlowActive(parked.copy(carKw = 0.1)))
        assertFalse(carFlowActive(parked.copy(planned = true)))
        assertEquals("Forecast consumption", carStateLabel(parked.copy(planned = true)))
    }

    @Test fun unknownCarStateStaysUnknown() {
        val unknown = live("{}")
        assertNull(unknown.carCharging)
        assertFalse(carFlowActive(unknown))
        assertEquals("Presence unknown", carStateLabel(unknown))
        assertEquals("Home · cable unknown", carStateLabel(unknown.copy(carHome = true)))
        assertEquals("Plugged in · charge unknown", carStateLabel(unknown.copy(carHome = true, carPlugged = true)))
    }

    @Test fun carTrailNeedsAllThreeCarStates() {
        assertTrue(routeMotion(parked, FlowRoute.Car).active)
        assertFalse(routeMotion(parked.copy(carHome = null), FlowRoute.Car).active)
        assertFalse(routeMotion(parked.copy(carPlugged = null), FlowRoute.Car).active)
        assertFalse(routeMotion(parked.copy(carCharging = null), FlowRoute.Car).active)
        assertFalse(routeMotion(parked.copy(carKw = 0.0999), FlowRoute.Car).active)
    }

    @Test fun trailDirectionFollowsTheSignOfGridAndBattery() {
        val state = fresh("\"pv_kw\":4,\"grid_kw\":-2.5,\"battery_kw\":1.5")
        assertTrue(routeMotion(state, FlowRoute.Solar).active)
        assertFalse(routeMotion(state, FlowRoute.Solar).reverse)
        assertTrue("exporting runs house -> pole", routeMotion(state, FlowRoute.Grid).reverse)
        assertFalse("discharging runs battery -> house", routeMotion(state, FlowRoute.Battery).reverse)
        val opposite = state.copy(gridKw = 2.5, batteryKw = -1.5)
        assertFalse(routeMotion(opposite, FlowRoute.Grid).reverse)
        assertTrue(routeMotion(opposite, FlowRoute.Battery).reverse)
        assertTrue(routeMotion(opposite, FlowRoute.Battery).active)
    }

    @Test fun smallFlowsDrawNoTrail() {
        val state = fresh("\"pv_kw\":0.02,\"grid_kw\":0.0999,\"battery_kw\":-0.0999")
        assertFalse(routeMotion(state, FlowRoute.Solar).active)
        assertFalse(routeMotion(state, FlowRoute.Grid).active)
        assertFalse(routeMotion(state, FlowRoute.Battery).active)
        assertTrue(routeMotion(state.copy(gridKw = -0.1), FlowRoute.Grid).active)
        assertTrue(routeMotion(state.copy(solarKw = 0.03), FlowRoute.Solar).active)
        assertFalse("a negative load reading is not a flow", routeMotion(state.copy(rackKw = -1.0), FlowRoute.Rack).active)
        assertFalse("unknown is not a flow", routeMotion(state.copy(waterKw = null), FlowRoute.Water).active)
    }

    @Test fun trailSpeedGrowsWithPowerAndIsCapped() {
        fun speed(kw: Double) = routeMotion(fresh().copy(solarKw = kw), FlowRoute.Solar).cyclesPerSecond
        assertTrue(speed(0.5) < speed(3.0))
        assertTrue(speed(3.0) < speed(8.0))
        assertEquals(speed(8.0), speed(20.0), 1e-6f)
        assertEquals("a pass takes 2.7 s at full power", 0.37f, speed(8.0), 1e-4f)
        assertEquals("and about 8 s at a trickle", 0.12f, speed(0.0), 1e-4f)
    }

    @Test fun nothingMovesOnStaleSavedUnknownOrForecastData() {
        val moving = fresh("\"pv_kw\":4,\"grid_kw\":-2")
        assertTrue(moving.fresh)
        assertTrue(sceneShouldAnimate(moving, systemAnimations = true, started = true, onScreen = true))

        val old = liveFlowState(
            bootstrap("""{"telemetry":{"healthy":true,"measured_at":"2026-10-12T01:59:29Z","pv_kw":4},"service":{}}"""),
            live = true, now = now,
        )
        assertFalse("31 s old", old.fresh)
        assertFalse(routeMotion(old, FlowRoute.Solar).active)

        val unhealthy = live("""{"telemetry":{"healthy":false,"measured_at":"2026-10-12T01:59:59Z","pv_kw":4}}""")
        assertFalse(unhealthy.fresh)

        val saved = liveFlowState(
            bootstrap("""{"telemetry":{"healthy":true,"measured_at":"2026-10-12T01:59:59Z","pv_kw":4}}"""),
            live = false, now = now,
        )
        assertFalse("a cached copy is never live", saved.fresh)
        assertFalse(sceneShouldAnimate(saved, systemAnimations = true, started = true, onScreen = true))

        assertFalse(sceneShouldAnimate(moving.copy(planned = true), systemAnimations = true, started = true, onScreen = true))
        assertFalse(sceneShouldAnimate(live("{}"), systemAnimations = true, started = true, onScreen = true))
    }

    @Test fun animationStopsWhenTheSystemScaleIsZeroOrTheSceneIsNotVisible() {
        val moving = fresh("\"pv_kw\":4")
        assertFalse(sceneShouldAnimate(moving, systemAnimations = false, started = true, onScreen = true))
        assertFalse(sceneShouldAnimate(moving, systemAnimations = true, started = false, onScreen = true))
        assertFalse(sceneShouldAnimate(moving, systemAnimations = true, started = true, onScreen = false))
        assertFalse(sceneShouldAnimate(moving.copy(solarKw = 0.0), systemAnimations = true, started = true, onScreen = true))
        assertFalse(animationsEnabledForScale(0f))
        assertFalse(animationsEnabledForScale(Float.NaN))
        assertFalse(animationsEnabledForScale(-1f))
        assertTrue(animationsEnabledForScale(0.5f))
        assertTrue(animationsEnabledForScale(1f))
    }

    @Test fun liveReadingsExpireThirtyOneSecondsAfterMeasurement() {
        val state = fresh()
        assertEquals(Instant.parse("2026-10-12T02:00:30Z"), freshUntil(state))
        assertNull(freshUntil(state.copy(fresh = false)))
        assertNull("a forecast never expires", freshUntil(state.copy(planned = true)))
    }

    @Test fun fixtureIsALiveChargingAfternoon() {
        val state = liveFlowState(EnergyFixtures.bootstrap(measuredAt = now.minusSeconds(2)), live = true, now = now)
        assertTrue(state.fresh)
        assertTrue(carFlowActive(state))
        assertTrue(routeMotion(state, FlowRoute.Grid).reverse)
        assertTrue(routeMotion(state, FlowRoute.Battery).reverse)
        assertFalse(routeMotion(state, FlowRoute.Water).active)
        assertTrue(routeMotion(state, FlowRoute.Rack).active)
        val idle = liveFlowState(EnergyFixtures.bootstrap(measuredAt = now.minusSeconds(2), carCharging = false), live = true, now = now)
        assertEquals("Plugged in · idle", carStateLabel(idle))
    }
}
