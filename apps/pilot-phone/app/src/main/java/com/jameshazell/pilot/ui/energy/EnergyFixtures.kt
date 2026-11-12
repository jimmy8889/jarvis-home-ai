package com.jameshazell.pilot.ui.energy

import com.jameshazell.pilot.data.energy.EnergyBootstrap
import com.jameshazell.pilot.data.energy.EnergyDay
import com.jameshazell.pilot.data.energy.EnergyJson
import com.jameshazell.pilot.data.energy.EnergyTelemetry
import java.time.Instant
import kotlin.math.PI
import kotlin.math.max
import kotlin.math.sin
import org.json.JSONArray
import org.json.JSONObject

/** Made-up but realistic Energy Manager data for previews and unit tests. Never sent anywhere. */
internal object EnergyFixtures {
    /**
     * A sunny afternoon: exporting, battery charging, car at home and charging.
     *
     * @param measuredAt when the telemetry was taken; pass "now" for a fresh, animated scene.
     */
    fun bootstrap(measuredAt: Instant = Instant.now(), carCharging: Boolean = true): EnergyBootstrap {
        val start = Instant.parse("2026-11-12T02:00:00Z")
        val points = JSONArray()
        for (step in 0 until 72) {
            val hour = (12 + step * 0.5) % 24
            val sun = max(0.0, sin((hour - 5.5) / 13.0 * PI))
            points.put(
                JSONObject()
                    .put("start", start.plusSeconds(step * 1800L).toString())
                    .put("pv_kw", 9.5 * sun)
                    .put("load_kw", 1.1 + 0.9 * sin(step / 5.0).let { it * it })
                    .put("ev_kw", if (step in 2..7) 5.0 else 0.0)
                    .put("predicted_soc_pct", 55 + 35 * sin(step / 11.0))
                    .put("protected_soc_pct", 20)
                    .put("fit_per_kwh", 0.04 + 0.12 * (1 - sun))
                    .put("import_per_kwh", 0.22 + 0.2 * (1 - sun))
                    .put("server_rack_kw", 0.31),
            )
        }
        val root = JSONObject(
            """
            {"settings_revision": "rev-17",
             "settings": {"control_enabled": true, "hot_water_enabled": true, "ev_charge_limit_pct": 80,
                          "min_sell_price_per_kwh": 0.12, "ev_opportunistic_fit_max_per_kwh": 0.01,
                          "ev_grid_allowed": false, "ev_trip_profile": "no_trip"},
             "snapshot": {
               "telemetry": {"healthy": true, "measured_at": "$measuredAt", "pv_kw": 8.4, "pv1_kw": 3.1,
                             "pv2_kw": 1.8, "pv3_kw": 3.5, "load_kw": 6.3, "grid_kw": -0.4,
                             "battery_kw": -1.7, "soc_pct": 77},
               "devices": {"ev_soc_pct": 64, "ev_home": true, "ev_ble_home": true, "ev_plugged": true,
                           "ev_charging": $carCharging, "ev_power_kw": ${if (carCharging) 4.6 else 0.0},
                           "hot_water_available": true, "hot_water_on": false, "hot_water_confirmed": false,
                           "hot_water_power_kw": 0.0, "hot_water_runtime_hours": 0.52,
                           "hot_water_source": "solar_surplus"},
               "command": {"mode": "self_consume", "reason": "solar_surplus"},
               "service": {"command_phase": "confirmed", "household_floor_pct": 20, "workers": {"healthy": true}},
               "prices": {"amber_fit": {"price_per_kwh": 0.082}, "amber_import": {"price_per_kwh": 0.285}},
               "battery": {"gross_stored_kwh": 31.2},
               "grid_health": {"state": "normal"},
               "daily_energy": {"solar_generated_kwh": 41.5, "house_consumed_kwh": 18.2, "grid_exported_kwh": 9.9},
               "server_rack": {"available": true, "status": "OL CHRG", "wall_input_w": 312, "battery_charge_pct": 96,
                               "battery_runtime_seconds": 1560, "load_pct": 21, "rack_output_w": 214,
                               "office_output_w": 61, "protected_output_w": 275, "conversion_loss_w": 37,
                               "input_voltage_v": 241, "output_voltage_v": 230, "energy_today_kwh": 4.1},
               "forecast": {"expected_pv_kw": 8.9, "expected_pv_fresh": true, "providers": ["solcast", "open_meteo"],
                            "irradiance": {"ghi_wm2": 710, "poa_north_wm2": 820, "poa_south_wm2": 540}}
             },
             "plan": {"rolling": {
               "narrative": {"current_summary": "Charge EV toward 80%",
                             "headline": "Solar covers the house and the car; export resumes after 3 pm.",
                             "house": "Solar serves normal loads first; the battery covers the rest above its reserve.",
                             "export": "1 profitable export window is currently planned.",
                             "next_actions": [
                               {"group": "Now", "start": "2026-11-12T02:00:00Z", "end": "2026-11-12T05:00:00Z",
                                "title": "Charge EV toward 80%", "reason": "Charge from forecast solar below the opportunistic FIT threshold"},
                               {"group": "Today", "start": "2026-11-12T07:30:00Z", "end": "2026-11-12T09:00:00Z",
                                "title": "Export profitable energy", "reason": "FIT clears the sell floor, wear, and retained-energy value"}]}}}}
            """.trimIndent(),
        )
        root.getJSONObject("plan").getJSONObject("rolling").put("points", points)
        return EnergyJson.bootstrap(root)
    }

    fun history(): List<EnergyTelemetry> = (0 until 288).map { step ->
        val hour = step / 12.0
        val sun = max(0.0, sin((hour - 5.5) / 13.0 * PI))
        EnergyTelemetry(
            measuredAt = Instant.parse("2026-11-11T14:00:00Z").plusSeconds(step * 300L),
            healthy = true,
            pvKw = 9.0 * sun,
            pvStringsKw = listOf(null, null, null),
            loadKw = 1.2 + sin(step / 9.0).let { it * it },
            gridKw = 1.0 - 4.0 * sun,
            batteryKw = null,
            socPct = null,
        )
    }

    fun daily(): List<EnergyDay> = (1..30).map { day ->
        EnergyDay(
            date = "2026-10-%02d".format(day),
            solarGeneratedKwh = 30 + 18 * sin(day / 3.0),
            houseConsumedKwh = 19 + 6 * sin(day / 2.0),
            gridExportedKwh = 8 + 5 * sin(day / 4.0),
        )
    }
}
