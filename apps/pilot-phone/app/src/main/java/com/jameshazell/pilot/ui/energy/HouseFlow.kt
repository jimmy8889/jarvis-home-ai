package com.jameshazell.pilot.ui.energy

import com.jameshazell.pilot.data.energy.EnergyBootstrap
import com.jameshazell.pilot.data.energy.EnergyPlanPoint
import com.jameshazell.pilot.data.energy.flowGraph
import java.time.Instant
import kotlin.math.abs
import kotlin.math.min

/*
 * The rules behind the house scene. No Compose here, so everything is unit tested.
 * Power is kW. Signs: grid + = importing, battery + = discharging.
 */

/** Below this a reading is "idle". */
internal const val FLOW_IDLE_KW = 0.025

/** Grid, battery and the car need at least 100 W before a trail is drawn. */
internal const val FLOW_ACTIVE_KW = 0.1

/** Telemetry counts as live for this long after it was measured. */
internal const val FLOW_FRESH_SECONDS = 30L

internal data class HouseFlowState(
    val solarKw: Double?,
    val gridKw: Double?,
    val batteryKw: Double?,
    /** Whole-house load, which already includes the car, hot water and the rack. */
    val houseKw: Double?,
    val carKw: Double?,
    val waterKw: Double?,
    val rackKw: Double?,
    /** Bluetooth-verified presence only. Null = unknown; the artwork then shows no car. */
    val carHome: Boolean? = null,
    /** Cable connected. Separate from presence and from charging. */
    val carPlugged: Boolean? = null,
    val carCharging: Boolean? = null,
    val socPct: Double? = null,
    val carSocPct: Double? = null,
    val daylight: Boolean = true,
    val measuredAt: Instant? = null,
    /** True for a forecast step of the plan rather than a measurement. */
    val planned: Boolean = false,
    /** Live, healthy and recent. Trails only move while this is true. */
    val fresh: Boolean = false,
)

/** Net of a node that can be both source and sink; null when neither side is known. */
internal fun flowNet(source: Double?, sink: Double?): Double? =
    if (source == null && sink == null) null else (source ?: 0.0) - (sink ?: 0.0)

/**
 * Day artwork while the panels produce at least 100 W; otherwise by the Brisbane clock, so an
 * overcast afternoon is still day and a missing solar reading does not turn the lights off.
 */
internal fun isDaylight(solarKw: Double?, at: Instant): Boolean =
    (solarKw ?: 0.0) >= FLOW_ACTIVE_KW || at.atZone(HouseZone).hour in 6..17

/**
 * Live readings. The controller's flow graph wins over raw telemetry where it exists, because
 * it is already balanced and does not double-count the car and hot water inside the house load.
 *
 * @param live false for a saved (cached) copy; saved readings are never [HouseFlowState.fresh].
 */
internal fun liveFlowState(bootstrap: EnergyBootstrap, live: Boolean, now: Instant = Instant.now()): HouseFlowState {
    val telemetry = bootstrap.telemetry
    val devices = bootstrap.devices
    val graph = bootstrap.flowGraph()
    val solar = graph?.sourcesKw?.get("solar") ?: telemetry.pvKw
    return HouseFlowState(
        solarKw = solar,
        gridKw = flowNet(graph?.sourcesKw?.get("grid"), graph?.sinksKw?.get("grid")) ?: telemetry.gridKw,
        batteryKw = flowNet(graph?.sourcesKw?.get("battery"), graph?.sinksKw?.get("battery")) ?: telemetry.batteryKw,
        houseKw = graph?.siteLoadKw ?: telemetry.loadKw,
        carKw = graph?.sinksKw?.get("ev") ?: devices.evPowerKw,
        waterKw = graph?.sinksKw?.get("hot_water") ?: devices.hotWaterPowerKw,
        rackKw = bootstrap.rack.wallInputW?.div(1000) ?: graph?.submetersKw?.get("server_rack"),
        carHome = devices.evBleHome,
        carPlugged = devices.evPlugged,
        carCharging = devices.evCharging,
        socPct = telemetry.socPct,
        carSocPct = devices.evSocPct,
        daylight = isDaylight(solar, now),
        measuredAt = telemetry.measuredAt,
        fresh = live && bootstrap.telemetryFresh(now),
    )
}

/** One forecast step of the plan. It never inherits live loads the plan does not state. */
internal fun plannedFlowState(bootstrap: EnergyBootstrap, point: EnergyPlanPoint): HouseFlowState {
    val graph = point.flowGraph()
    val raw = point.raw
    fun number(key: String): Double? = raw.optDouble(key, Double.NaN).takeIf(Double::isFinite)
    val solar = graph?.sourcesKw?.get("solar") ?: point.pvKw
    return HouseFlowState(
        solarKw = solar,
        gridKw = flowNet(graph?.sourcesKw?.get("grid"), graph?.sinksKw?.get("grid"))
            ?: flowNet(number("grid_import_kw"), number("site_export_target_kw")),
        batteryKw = flowNet(graph?.sourcesKw?.get("battery"), graph?.sinksKw?.get("battery"))
            ?: number("battery_target_kw")
            ?: flowNet(number("battery_discharge_kw"), number("battery_charge_kw")),
        houseKw = graph?.siteLoadKw,
        carKw = graph?.sinksKw?.get("ev") ?: point.evKw,
        waterKw = graph?.sinksKw?.get("hot_water"),
        rackKw = number("server_rack_kw"),
        carHome = bootstrap.devices.evBleHome,
        carPlugged = bootstrap.devices.evPlugged,
        carCharging = bootstrap.devices.evCharging,
        socPct = point.predictedSocPct,
        carSocPct = bootstrap.devices.evSocPct,
        daylight = isDaylight(solar, point.start ?: Instant.now()),
        measuredAt = point.start,
        planned = true,
        fresh = true,
    )
}

/** When live readings stop counting as fresh, so the scene can pause itself without polling. */
internal fun freshUntil(state: HouseFlowState): Instant? =
    if (state.fresh && !state.planned) state.measuredAt?.plusSeconds(FLOW_FRESH_SECONDS + 1) else null

/**
 * A charging trail needs all of: the car verified at home, the cable connected, the charger
 * reporting charging, and at least 100 W actually flowing. Any unknown counts as "no".
 */
internal fun carFlowActive(state: HouseFlowState): Boolean =
    !state.planned && state.carHome == true && state.carPlugged == true && state.carCharging == true &&
        (state.carKw ?: 0.0) >= FLOW_ACTIVE_KW

/** Presence, cable and charging in one line, most basic unknown first. */
internal fun carStateLabel(state: HouseFlowState): String = when {
    state.planned -> "Forecast consumption"
    state.carHome == false -> "Away"
    state.carHome == null -> "Presence unknown"
    state.carPlugged == false -> "Home · unplugged"
    state.carPlugged == null -> "Home · cable unknown"
    carFlowActive(state) -> "Charging"
    state.carCharging == null -> "Plugged in · charge unknown"
    else -> "Plugged in · idle"
}

internal fun gridLabel(kw: Double?): String = when {
    kw == null -> "Unavailable"
    kw >= FLOW_ACTIVE_KW -> "Importing"
    kw <= -FLOW_ACTIVE_KW -> "Exporting"
    else -> "Idle"
}

internal fun batteryLabel(kw: Double?): String = when {
    kw == null -> "Unavailable"
    kw >= FLOW_ACTIVE_KW -> "Discharging"
    kw <= -FLOW_ACTIVE_KW -> "Charging"
    else -> "Idle"
}

internal fun solarLabel(kw: Double?): String = when {
    kw == null -> "Unavailable"
    kw > FLOW_IDLE_KW -> "Producing"
    else -> "Idle"
}

/** The animated paths. Each is drawn from the supply end to the house, or the house to a load. */
internal enum class FlowRoute { Solar, Grid, Battery, Car, Water, Rack }

/**
 * @param active a trail is drawn and moves.
 * @param reverse the trail runs against the route's drawn direction (exporting, battery charging).
 * @param cyclesPerSecond how many times per second a pulse travels the whole route.
 */
internal data class RouteMotion(val active: Boolean, val reverse: Boolean, val cyclesPerSecond: Float)

internal fun routePower(state: HouseFlowState, route: FlowRoute): Double? = when (route) {
    FlowRoute.Solar -> state.solarKw
    FlowRoute.Grid -> state.gridKw
    FlowRoute.Battery -> state.batteryKw
    FlowRoute.Car -> state.carKw
    FlowRoute.Water -> state.waterKw
    FlowRoute.Rack -> state.rackKw
}

/** Direction and speed follow the live value; nothing moves on stale, unknown or forecast data. */
internal fun routeMotion(state: HouseFlowState, route: FlowRoute): RouteMotion {
    val power = routePower(state, route)?.takeIf(Double::isFinite)
    val threshold = when (route) {
        FlowRoute.Grid, FlowRoute.Battery, FlowRoute.Car -> FLOW_ACTIVE_KW
        else -> FLOW_IDLE_KW
    }
    val active = state.fresh && !state.planned && power != null && abs(power) >= threshold &&
        (route != FlowRoute.Car || carFlowActive(state)) &&
        (route == FlowRoute.Grid || route == FlowRoute.Battery || power > 0)
    val reverse = (route == FlowRoute.Grid || route == FlowRoute.Battery) && power != null && power < 0
    // One pass takes about 8 s at a trickle and under 3 s at 8 kW and above.
    val rate = 1.2 + min(abs(power ?: 0.0) / 8.0, 1.0) * 2.5
    return RouteMotion(active, reverse, (rate / 10.0).toFloat())
}

/** The single on/off switch for the frame clock. */
internal fun sceneShouldAnimate(
    state: HouseFlowState,
    systemAnimations: Boolean,
    started: Boolean,
    onScreen: Boolean,
): Boolean = systemAnimations && started && onScreen && FlowRoute.entries.any { routeMotion(state, it).active }

/** False when the system "Animator duration scale" is off (0) or nonsense. */
internal fun animationsEnabledForScale(animatorDurationScale: Float): Boolean =
    animatorDurationScale.isFinite() && animatorDurationScale > 0f
