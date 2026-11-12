package com.jameshazell.pilot.data.energy

import com.jameshazell.pilot.core.arr
import com.jameshazell.pilot.core.boolOrNull
import com.jameshazell.pilot.core.doubleOrNull
import com.jameshazell.pilot.core.instantOrNull
import com.jameshazell.pilot.core.obj
import com.jameshazell.pilot.core.objects
import com.jameshazell.pilot.core.str
import com.jameshazell.pilot.core.strOrNull
import com.jameshazell.pilot.core.strings
import java.time.Instant
import org.json.JSONObject

/*
 * Typed view of the Energy Manager mobile API. Missing readings are null, never zero.
 * Power is kW unless the name says W. Sections without a stable shape yet (the power-flow
 * graph) stay reachable through the raw objects on EnergyBootstrap.
 */

/** Commands the Energy Manager accepts at `POST /mobile/v1/actions/<id>`; each needs phone unlock. */
enum class EnergyAction(val id: String, val label: String) {
    EnableAutomation("enable-automation", "Enable automation"),
    DisableAutomation("disable-automation", "Disable automation"),
    HotWaterEnable("hot-water-enable", "Enable hot water"),
    HotWaterAway("hot-water-away", "Hot water away mode"),
    StopEv("stop-ev", "Stop Tesla charging"),
    StopHotWater("stop-hot-water", "Stop hot water"),
    SafeState("safe-state", "Safe state"),
}

data class EnergySettings(
    val controlEnabled: Boolean,
    val hotWaterEnabled: Boolean,
    val evChargeLimitPct: Int?,
    val minSellPricePerKwh: Double?,
    val evOpportunisticFitMaxPerKwh: Double?,
    val evGridAllowed: Boolean,
    val evTripProfile: String?,
)

/** A settings change; null fields are left out of the PATCH and stay as they are. */
data class EnergySettingsPatch(
    val evChargeLimitPct: Int? = null,
    val minSellPricePerKwh: Double? = null,
    val evOpportunisticFitMaxPerKwh: Double? = null,
    val evGridAllowed: Boolean? = null,
    val evTripProfile: String? = null,
) {
    /** @throws IllegalArgumentException with a message for the settings form. */
    fun toJson(): JSONObject {
        evChargeLimitPct?.let { require(it in 50..100) { "Charge limit must be 50–100%" } }
        return JSONObject().apply {
            evChargeLimitPct?.let { put("ev_charge_limit_pct", it) }
            minSellPricePerKwh?.let { put("min_sell_price_per_kwh", it) }
            evOpportunisticFitMaxPerKwh?.let { put("ev_opportunistic_fit_max_per_kwh", it) }
            evGridAllowed?.let { put("ev_grid_allowed", it) }
            evTripProfile?.let { put("ev_trip_profile", it) }
        }
    }
}

data class EnergyTelemetry(
    val measuredAt: Instant?,
    val healthy: Boolean,
    val pvKw: Double?,
    /** The three solar inputs, PV 1–3. */
    val pvStringsKw: List<Double?>,
    val loadKw: Double?,
    /** Positive = importing. */
    val gridKw: Double?,
    /** Positive = discharging. */
    val batteryKw: Double?,
    val socPct: Double?,
)

data class EnergyDevices(
    val evSocPct: Double?,
    val evHome: Boolean?,
    /** Bluetooth-confirmed presence; the house scene shows the car only when this is true. */
    val evBleHome: Boolean?,
    val evPlugged: Boolean?,
    val evCharging: Boolean?,
    val evPowerKw: Double?,
    val hotWaterAvailable: Boolean,
    val hotWaterOn: Boolean,
    val hotWaterConfirmed: Boolean,
    val hotWaterPowerKw: Double?,
    val hotWaterRuntimeHours: Double?,
    val hotWaterSource: String?,
)

data class EnergyDecision(val mode: String?, val reason: String?, val phase: String?)

data class EnergyPrices(val feedInPerKwh: Double?, val importPerKwh: Double?)

data class EnergyDay(
    val date: String?,
    val solarGeneratedKwh: Double?,
    val houseConsumedKwh: Double?,
    val gridExportedKwh: Double?,
)

data class EnergyRack(
    val available: Boolean,
    val status: String?,
    val wallInputW: Double?,
    val batteryChargePct: Double?,
    val batteryRuntimeSeconds: Double?,
    val energyTodayKwh: Double?,
    val rackOutputW: Double?,
    val officeOutputW: Double?,
    val conversionLossW: Double?,
    val inputVoltageV: Double?,
)

data class EnergyForecast(
    val ghiWm2: Double?,
    val poaNorthWm2: Double?,
    val poaSouthWm2: Double?,
    val expectedPvKw: Double?,
    val expectedPvFresh: Boolean,
    val providers: List<String>,
)

/** One step of the rolling 36-hour plan. [raw] also carries the planned `flow` graph. */
data class EnergyPlanPoint(
    val start: Instant?,
    val pvKw: Double?,
    val loadKw: Double?,
    val evKw: Double?,
    val predictedSocPct: Double?,
    val protectedSocPct: Double?,
    val feedInPerKwh: Double?,
    val importPerKwh: Double?,
    val raw: JSONObject,
)

data class EnergyNextAction(val start: Instant?, val title: String)

data class EnergyNarrative(
    val currentSummary: String?,
    val headline: String?,
    val nextActions: List<EnergyNextAction>,
)

/** `GET /mobile/v1/bootstrap`: everything the Energy tab shows except recorded history. */
data class EnergyBootstrap(
    /** Null when the controller sent no settings; settings controls must then be disabled. */
    val settings: EnergySettings?,
    /** Send as `If-Match` when changing settings; null means settings cannot be edited. */
    val settingsRevision: String?,
    val telemetry: EnergyTelemetry,
    val devices: EnergyDevices,
    val decision: EnergyDecision,
    val prices: EnergyPrices,
    val batteryStoredKwh: Double?,
    val householdFloorPct: Double?,
    val gridHealth: String?,
    val today: EnergyDay,
    val rack: EnergyRack,
    val forecast: EnergyForecast,
    val plan: List<EnergyPlanPoint>,
    val narrative: EnergyNarrative,
    /** Raw `snapshot` object: input for [EnergyHealth] and the `flow` / `power_flow` graph. */
    val snapshot: JSONObject,
    /** The whole response, for fields not typed yet. */
    val raw: JSONObject,
) {
    /** True when telemetry is healthy and measured within the last 30 seconds. */
    fun telemetryFresh(now: Instant = Instant.now()): Boolean = EnergyHealth.fresh(snapshot, now)

    /** A controller problem worth showing, or null. */
    val fault: String? get() = EnergyHealth.fault(snapshot)
}

internal object EnergyJson {
    fun bootstrap(root: JSONObject): EnergyBootstrap {
        val snapshot = root.obj("snapshot")
        val service = snapshot.obj("service")
        val command = snapshot.obj("command")
        val prices = snapshot.obj("prices")
        val rolling = root.obj("plan").obj("rolling")
        val narrative = rolling.obj("narrative")
        val forecast = snapshot.obj("forecast")
        val irradiance = forecast.obj("irradiance")
        val rack = snapshot.obj("server_rack")
        return EnergyBootstrap(
            settings = root.optJSONObject("settings")?.let(::settings),
            settingsRevision = root.str("settings_revision").takeIf(String::isNotBlank),
            telemetry = telemetry(snapshot.obj("telemetry")),
            devices = devices(snapshot.obj("devices")),
            decision = EnergyDecision(
                mode = command.strOrNull("mode"),
                reason = command.strOrNull("reason"),
                phase = service.strOrNull("command_phase"),
            ),
            prices = EnergyPrices(
                feedInPerKwh = prices.obj("amber_fit").doubleOrNull("price_per_kwh"),
                importPerKwh = prices.obj("amber_import").doubleOrNull("price_per_kwh"),
            ),
            batteryStoredKwh = snapshot.obj("battery").doubleOrNull("gross_stored_kwh"),
            householdFloorPct = service.doubleOrNull("household_floor_pct"),
            gridHealth = snapshot.obj("grid_health").strOrNull("state"),
            today = day(snapshot.obj("daily_energy")),
            rack = EnergyRack(
                available = rack.optBoolean("available"),
                status = rack.strOrNull("status"),
                wallInputW = rack.doubleOrNull("wall_input_w"),
                batteryChargePct = rack.doubleOrNull("battery_charge_pct"),
                batteryRuntimeSeconds = rack.doubleOrNull("battery_runtime_seconds"),
                energyTodayKwh = rack.doubleOrNull("energy_today_kwh"),
                rackOutputW = rack.doubleOrNull("rack_output_w"),
                officeOutputW = rack.doubleOrNull("office_output_w"),
                conversionLossW = rack.doubleOrNull("conversion_loss_w"),
                inputVoltageV = rack.doubleOrNull("input_voltage_v"),
            ),
            forecast = EnergyForecast(
                ghiWm2 = irradiance.doubleOrNull("ghi_wm2"),
                poaNorthWm2 = irradiance.doubleOrNull("poa_north_wm2"),
                poaSouthWm2 = irradiance.doubleOrNull("poa_south_wm2"),
                expectedPvKw = forecast.doubleOrNull("expected_pv_kw"),
                expectedPvFresh = forecast.optBoolean("expected_pv_fresh"),
                providers = forecast.arr("providers").strings(),
            ),
            plan = rolling.arr("points").objects().map(::planPoint),
            narrative = EnergyNarrative(
                currentSummary = narrative.strOrNull("current_summary"),
                headline = narrative.strOrNull("headline"),
                nextActions = narrative.arr("next_actions").objects().map {
                    EnergyNextAction(it.instantOrNull("start"), it.str("title"))
                },
            ),
            snapshot = snapshot,
            raw = root,
        )
    }

    fun settings(value: JSONObject) = EnergySettings(
        controlEnabled = value.optBoolean("control_enabled"),
        hotWaterEnabled = value.optBoolean("hot_water_enabled"),
        evChargeLimitPct = value.doubleOrNull("ev_charge_limit_pct")?.toInt(),
        minSellPricePerKwh = value.doubleOrNull("min_sell_price_per_kwh"),
        evOpportunisticFitMaxPerKwh = value.doubleOrNull("ev_opportunistic_fit_max_per_kwh"),
        evGridAllowed = value.optBoolean("ev_grid_allowed"),
        evTripProfile = value.strOrNull("ev_trip_profile"),
    )

    fun telemetry(value: JSONObject) = EnergyTelemetry(
        measuredAt = value.instantOrNull("measured_at"),
        healthy = value.optBoolean("healthy", false),
        pvKw = value.doubleOrNull("pv_kw"),
        pvStringsKw = (1..3).map { value.doubleOrNull("pv${it}_kw") },
        loadKw = value.doubleOrNull("load_kw"),
        gridKw = value.doubleOrNull("grid_kw"),
        batteryKw = value.doubleOrNull("battery_kw"),
        socPct = value.doubleOrNull("soc_pct"),
    )

    private fun devices(value: JSONObject) = EnergyDevices(
        evSocPct = value.doubleOrNull("ev_soc_pct"),
        evHome = value.boolOrNull("ev_home"),
        evBleHome = value.boolOrNull("ev_ble_home"),
        evPlugged = value.boolOrNull("ev_plugged"),
        evCharging = value.boolOrNull("ev_charging"),
        evPowerKw = value.doubleOrNull("ev_power_kw"),
        hotWaterAvailable = value.optBoolean("hot_water_available", false),
        hotWaterOn = value.optBoolean("hot_water_on", false),
        hotWaterConfirmed = value.optBoolean("hot_water_confirmed", false),
        hotWaterPowerKw = value.doubleOrNull("hot_water_power_kw"),
        hotWaterRuntimeHours = value.doubleOrNull("hot_water_runtime_hours"),
        hotWaterSource = value.strOrNull("hot_water_source"),
    )

    fun day(value: JSONObject) = EnergyDay(
        date = value.strOrNull("local_date") ?: value.strOrNull("date") ?: value.strOrNull("day"),
        solarGeneratedKwh = value.doubleOrNull("solar_generated_kwh"),
        houseConsumedKwh = value.doubleOrNull("house_consumed_kwh"),
        gridExportedKwh = value.doubleOrNull("grid_exported_kwh"),
    )

    private fun planPoint(value: JSONObject) = EnergyPlanPoint(
        start = value.instantOrNull("start"),
        pvKw = value.doubleOrNull("pv_kw"),
        loadKw = value.doubleOrNull("load_kw"),
        evKw = value.doubleOrNull("ev_kw"),
        predictedSocPct = value.doubleOrNull("predicted_soc_pct"),
        protectedSocPct = value.doubleOrNull("protected_soc_pct"),
        feedInPerKwh = value.doubleOrNull("fit_per_kwh"),
        importPerKwh = value.doubleOrNull("import_per_kwh"),
        raw = value,
    )

    /** `GET /mobile/v1/history`: rows are telemetry, or wrap it in a `telemetry` field. */
    fun history(rows: List<JSONObject>): List<EnergyTelemetry> =
        rows.map { telemetry(it.optJSONObject("telemetry") ?: it) }

    fun daily(rows: List<JSONObject>): List<EnergyDay> = rows.map(::day)
}
