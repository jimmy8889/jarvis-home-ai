package com.jameshazell.pilot.data.energy

import com.jameshazell.pilot.fieldNames
import java.time.Instant
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class EnergyJsonTest {
    private val bootstrap = JSONObject(
        """
        {"settings_revision": 17,
         "settings": {"control_enabled": true, "hot_water_enabled": false, "ev_charge_limit_pct": 80,
                      "min_sell_price_per_kwh": 0.1, "ev_opportunistic_fit_max_per_kwh": "0.01",
                      "ev_grid_allowed": false, "ev_trip_profile": "no_trip"},
         "snapshot": {
           "telemetry": {"healthy": true, "measured_at": "2026-11-12T01:59:59Z", "pv_kw": 6.2,
                         "pv1_kw": 2.1, "pv2_kw": 2.0, "load_kw": 1.4, "grid_kw": -3.1,
                         "battery_kw": -1.7, "soc_pct": 77},
           "devices": {"ev_soc_pct": 64, "ev_ble_home": true, "ev_plugged": null, "ev_power_kw": 4.5,
                       "hot_water_available": true, "hot_water_source": "solar_surplus"},
           "command": {"mode": "self_consume", "reason": "solar_surplus"},
           "service": {"command_phase": "confirmed", "household_floor_pct": 20, "workers": {"healthy": true}},
           "prices": {"amber_fit": {"price_per_kwh": 0.082}, "amber_import": {"price_per_kwh": 0.285}},
           "battery": {"gross_stored_kwh": 31.2},
           "grid_health": {"state": "normal"},
           "daily_energy": {"solar_generated_kwh": 41.5, "house_consumed_kwh": 18.2, "grid_exported_kwh": 9.9},
           "server_rack": {"available": true, "status": "OL", "wall_input_w": 312, "battery_runtime_seconds": 1500},
           "forecast": {"expected_pv_kw": 6.5, "expected_pv_fresh": true, "providers": ["solcast", "bom"],
                        "irradiance": {"ghi_wm2": 710}}
         },
         "plan": {"rolling": {
           "points": [{"start": "2026-11-12T02:00:00Z", "pv_kw": 6.0, "predicted_soc_pct": 80, "fit_per_kwh": 0.09,
                       "flow": {"edges": []}}],
           "narrative": {"current_summary": "Charging from solar", "headline": "Export after 3 pm",
                         "next_actions": [{"start": "2026-11-12T05:00:00Z", "title": "Start exporting"}]}}}}
        """.trimIndent(),
    )

    @Test fun decodesBootstrapWithoutInventingReadings() {
        val value = EnergyJson.bootstrap(bootstrap)
        assertEquals("17", value.settingsRevision)
        assertEquals(80, value.settings!!.evChargeLimitPct)
        assertEquals(0.01, value.settings.evOpportunisticFitMaxPerKwh!!, 1e-9)
        assertTrue(value.settings.controlEnabled)
        assertEquals(6.2, value.telemetry.pvKw!!, 1e-9)
        assertEquals(listOf(2.1, 2.0, null), value.telemetry.pvStringsKw)
        assertEquals(-3.1, value.telemetry.gridKw!!, 1e-9)
        assertEquals(true, value.devices.evBleHome)
        assertNull("JSON null stays unknown", value.devices.evPlugged)
        assertNull(value.devices.evCharging)
        assertNull(value.devices.hotWaterPowerKw)
        assertEquals("self_consume", value.decision.mode)
        assertEquals("confirmed", value.decision.phase)
        assertEquals(0.285, value.prices.importPerKwh!!, 1e-9)
        assertEquals(31.2, value.batteryStoredKwh!!, 1e-9)
        assertEquals(20.0, value.householdFloorPct!!, 1e-9)
        assertEquals("normal", value.gridHealth)
        assertEquals(18.2, value.today.houseConsumedKwh!!, 1e-9)
        assertEquals(312.0, value.rack.wallInputW!!, 1e-9)
        assertNull(value.rack.batteryChargePct)
        assertEquals(listOf("solcast", "bom"), value.forecast.providers)
        assertEquals(Instant.parse("2026-11-12T02:00:00Z"), value.plan.single().start)
        assertTrue(value.plan.single().raw.has("flow"))
        assertEquals("Start exporting", value.narrative.nextActions.single().title)
        assertTrue(value.telemetryFresh(Instant.parse("2026-11-12T02:00:00Z")))
        assertFalse(value.telemetryFresh(Instant.parse("2026-11-12T02:01:00Z")))
        assertNull(value.fault)
    }

    @Test fun emptyBootstrapIsAllUnknown() {
        val value = EnergyJson.bootstrap(JSONObject())
        assertNull(value.settings)
        assertNull(value.settingsRevision)
        assertNull(value.telemetry.pvKw)
        assertFalse(value.telemetryFresh())
        assertTrue(value.plan.isEmpty())
    }

    @Test fun historyRowsMayWrapTelemetry() {
        val rows = listOf(
            JSONObject("""{"telemetry":{"pv_kw":1.5,"measured_at":"2026-11-12T00:00:00Z"}}"""),
            JSONObject("""{"pv_kw":2.5}"""),
        )
        assertEquals(listOf(1.5, 2.5), EnergyJson.history(rows).map { it.pvKw })
        val day = EnergyJson.daily(listOf(JSONObject("""{"local_date":"2026-11-11","solar_generated_kwh":40}"""))).single()
        assertEquals("2026-11-11", day.date)
        assertEquals(40.0, day.solarGeneratedKwh!!, 1e-9)
    }

    @Test fun settingsPatchUsesTheControllerFieldNames() {
        val body = EnergySettingsPatch(
            evChargeLimitPct = 90, minSellPricePerKwh = 0.12, evOpportunisticFitMaxPerKwh = 0.02,
            evGridAllowed = true, evTripProfile = "long_trip",
        ).toJson()
        assertEquals(
            setOf(
                "ev_charge_limit_pct", "min_sell_price_per_kwh", "ev_opportunistic_fit_max_per_kwh",
                "ev_grid_allowed", "ev_trip_profile",
            ),
            body.fieldNames(),
        )
        assertEquals(90, body.getInt("ev_charge_limit_pct"))
        assertEquals(true, body.getBoolean("ev_grid_allowed"))
        assertEquals(setOf("ev_grid_allowed"), EnergySettingsPatch(evGridAllowed = false).toJson().fieldNames())
        assertThrows(IllegalArgumentException::class.java) { EnergySettingsPatch(evChargeLimitPct = 40).toJson() }
    }
}
