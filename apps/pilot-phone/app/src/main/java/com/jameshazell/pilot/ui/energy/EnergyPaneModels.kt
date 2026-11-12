package com.jameshazell.pilot.ui.energy

import com.jameshazell.pilot.core.arr
import com.jameshazell.pilot.core.doubleOrNull
import com.jameshazell.pilot.core.humanLabel
import com.jameshazell.pilot.core.instantOrNull
import com.jameshazell.pilot.core.obj
import com.jameshazell.pilot.core.objects
import com.jameshazell.pilot.core.strOrNull
import com.jameshazell.pilot.data.energy.EnergyAction
import com.jameshazell.pilot.data.energy.EnergyBootstrap
import com.jameshazell.pilot.data.energy.EnergyPlanPoint
import com.jameshazell.pilot.data.energy.EnergySettings
import com.jameshazell.pilot.data.energy.EnergySettingsPatch
import java.time.Instant
import kotlin.math.abs
import kotlin.math.roundToInt

/* What each pane shows, worked out from the bootstrap. No Compose here; all unit tested. */

/** The sub-pages of the Energy destination, in segmented-control order. */
enum class EnergyPane(val label: String) {
    Now("Now"),
    Plan("Plan"),
    Solar("Solar"),
    Ups("UPS & rack"),
    Controls("Controls"),
}

// ---------------------------------------------------------------- status line

internal enum class StatusTone { Good, Warn, Bad }

internal data class EnergyStatusLine(val text: String, val tone: StatusTone)

/**
 * The one-line health summary under the house. Order matters: saved data first (everything
 * else on screen is then old), then controller faults, then stale telemetry, then "live".
 *
 * @param saved the readings came from the on-device cache, not a live answer.
 */
internal fun energyStatusLine(bootstrap: EnergyBootstrap, saved: Boolean, now: Instant = Instant.now()): EnergyStatusLine {
    if (saved) return EnergyStatusLine("Saved readings · movement paused", StatusTone.Warn)
    bootstrap.fault?.let { return EnergyStatusLine(it, StatusTone.Bad) }
    if (!bootstrap.telemetryFresh(now)) {
        return EnergyStatusLine("Controller readings are stale · movement paused", StatusTone.Warn)
    }
    val decision = bootstrap.decision.mode?.let(::humanLabel) ?: "Waiting for the controller's decision"
    val grid = bootstrap.gridHealth?.let { " · Grid ${humanLabel(it).lowercase()}" }.orEmpty()
    return EnergyStatusLine("Live · $decision$grid", StatusTone.Good)
}

/** "Charging · 1.7 kW" under the battery percentage. */
internal fun batteryNote(kw: Double?): String = when (val label = batteryLabel(kw)) {
    "Charging", "Discharging" -> "$label · ${formatPower(kw)}"
    else -> label
}

/** Direction plus the price that applies to it: importing shows the import price, exporting the feed-in. */
internal fun gridNote(kw: Double?, importPerKwh: Double?, feedInPerKwh: Double?): String = when (val label = gridLabel(kw)) {
    "Importing" -> importPerKwh?.let { "$label · ${formatPrice(it)}" } ?: label
    "Exporting" -> feedInPerKwh?.let { "$label · ${formatPrice(it)}" } ?: label
    else -> label
}

// ---------------------------------------------------------------- plan

internal data class PlanAction(
    val start: Instant?,
    val end: Instant?,
    val title: String,
    val reason: String?,
    /** "Now" / "Next" / "Today" / "Overnight". */
    val group: String?,
)

/** The controller's recommendations, soonest first as it sends them. Untitled entries are dropped. */
internal fun planActions(bootstrap: EnergyBootstrap): List<PlanAction> =
    bootstrap.raw.obj("plan").obj("rolling").obj("narrative").arr("next_actions").objects().mapNotNull { action ->
        val title = action.strOrNull("title") ?: return@mapNotNull null
        PlanAction(
            start = action.instantOrNull("start"),
            end = action.instantOrNull("end"),
            title = title,
            reason = action.strOrNull("reason"),
            group = action.strOrNull("group"),
        )
    }

internal fun planActionWhen(action: PlanAction): String = when {
    action.start == null -> action.group ?: "Planned"
    action.end == null -> formatDayTime(action.start)
    else -> "${formatDayTime(action.start)} – ${formatTime(action.end)}"
}

/** The plan's own one-line explanations (house, battery, car, hot water, export), in that order. */
internal fun planNotes(bootstrap: EnergyBootstrap): List<String> {
    val narrative = bootstrap.raw.obj("plan").obj("rolling").obj("narrative")
    return listOf("house", "battery", "ev", "hot_water", "export").mapNotNull(narrative::strOrNull)
}

internal data class TariffMoment(val at: Instant?, val perKwh: Double)

/**
 * @param cheapestImport the lowest import price in the plan horizon.
 * @param bestFeedIn the highest feed-in price in the plan horizon.
 */
internal data class TariffHighlights(val cheapestImport: TariffMoment?, val bestFeedIn: TariffMoment?)

internal fun tariffHighlights(points: List<EnergyPlanPoint>): TariffHighlights = TariffHighlights(
    cheapestImport = points.filter { it.importPerKwh != null }.minByOrNull { it.importPerKwh!! }
        ?.let { TariffMoment(it.start, it.importPerKwh!!) },
    bestFeedIn = points.filter { it.feedInPerKwh != null }.maxByOrNull { it.feedInPerKwh!! }
        ?.let { TariffMoment(it.start, it.feedInPerKwh!!) },
)

/** Dollars per kWh to cents, keeping unknowns unknown. */
internal fun cents(perKwh: Double?): Double? = perKwh?.times(100)

// ---------------------------------------------------------------- charts

/**
 * Index ranges of a series that should be drawn as connected lines. Unknown samples break the
 * line. With [activityThreshold], samples whose magnitude is below it break the line too, so
 * an on/off load (the car) is drawn as separate blocks instead of ramps down to zero.
 */
internal fun chartSegments(values: List<Double?>, activityThreshold: Double? = null): List<IntRange> {
    val segments = mutableListOf<IntRange>()
    var start = -1
    values.forEachIndexed { index, value ->
        val visible = value != null && value.isFinite() && (activityThreshold == null || abs(value) >= activityThreshold)
        if (visible && start < 0) start = index
        if (!visible && start >= 0) {
            segments += start until index
            start = -1
        }
    }
    if (start >= 0) segments += start until values.size
    return segments
}

/**
 * The vertical range for a chart: always includes zero, never collapses to nothing, and is at
 * least [minSpan] tall so a flat line of small values is not drawn as dramatic noise.
 */
internal fun chartBounds(series: List<List<Double?>>, minSpan: Double = 1.0): ClosedFloatingPointRange<Double> {
    val all = series.flatten().filterNotNull().filter(Double::isFinite)
    val low = minOf(0.0, all.minOrNull() ?: 0.0)
    val high = maxOf(low + minSpan, all.maxOrNull() ?: 0.0, 0.0)
    return low..high
}

/** Total of the known values, or null when there are none (so an empty month is not "0 kWh"). */
internal fun knownTotal(values: List<Double?>): Double? =
    values.filterNotNull().filter(Double::isFinite).takeIf { it.isNotEmpty() }?.sum()

// ---------------------------------------------------------------- UPS & rack

/**
 * @param headline plain words for the NUT status flags.
 * @param notes extra conditions worth showing ("Battery low", "Replace battery").
 */
internal data class UpsStatus(val headline: String, val tone: StatusTone, val notes: List<String>, val onBattery: Boolean)

/** Translates NUT status flags ("OL CHRG", "OB LB") into words. */
internal fun upsStatus(available: Boolean, status: String?): UpsStatus {
    if (!available) return UpsStatus("UPS readings unavailable", StatusTone.Warn, emptyList(), onBattery = false)
    val flags = status.orEmpty().split(' ', ',').map { it.trim().uppercase() }.filter(String::isNotEmpty).toSet()
    val onBattery = "OB" in flags
    val notes = buildList {
        if ("LB" in flags) add("Battery low")
        if ("RB" in flags) add("Replace battery")
        if ("OVER" in flags) add("Overloaded")
        if ("BYPASS" in flags) add("On bypass: loads are not protected")
        if ("CHRG" in flags) add("Battery charging")
        if ("DISCHRG" in flags && !onBattery) add("Battery discharging")
        if ("TRIM" in flags || "BOOST" in flags) add("Correcting mains voltage")
    }
    val bad = onBattery && "LB" in flags || "OVER" in flags || "OFF" in flags || "FSD" in flags
    val warn = onBattery || "RB" in flags || "LB" in flags || "BYPASS" in flags
    val headline = when {
        "FSD" in flags -> "Shutting down protected loads"
        "OFF" in flags -> "UPS output is off"
        onBattery -> "On battery · mains supply interrupted"
        "OL" in flags -> "On mains power"
        else -> "Connected"
    }
    return UpsStatus(headline, if (bad) StatusTone.Bad else if (warn) StatusTone.Warn else StatusTone.Good, notes, onBattery)
}

/** Everything the UPS pane shows. Fields the bootstrap does not carry stay null. */
internal data class UpsView(
    val status: UpsStatus,
    val chargePct: Double?,
    val runtimeSeconds: Double?,
    val loadPct: Double?,
    val wallInputW: Double?,
    val rackOutputW: Double?,
    val officeOutputW: Double?,
    val protectedOutputW: Double?,
    val conversionLossW: Double?,
    val inputVoltageV: Double?,
    val outputVoltageV: Double?,
    val energyTodayKwh: Double?,
)

internal fun upsView(bootstrap: EnergyBootstrap): UpsView {
    val rack = bootstrap.rack
    // Not typed in the data layer yet: read straight from the snapshot.
    val raw = bootstrap.snapshot.obj("server_rack")
    return UpsView(
        status = upsStatus(rack.available, rack.status),
        chargePct = rack.batteryChargePct,
        runtimeSeconds = rack.batteryRuntimeSeconds,
        loadPct = raw.doubleOrNull("load_pct"),
        wallInputW = rack.wallInputW,
        rackOutputW = rack.rackOutputW,
        officeOutputW = rack.officeOutputW,
        protectedOutputW = raw.doubleOrNull("protected_output_w"),
        conversionLossW = rack.conversionLossW,
        inputVoltageV = rack.inputVoltageV,
        outputVoltageV = raw.doubleOrNull("output_voltage_v"),
        energyTodayKwh = rack.energyTodayKwh,
    )
}

// ---------------------------------------------------------------- settings

/** Trip preparation choices the controller accepts, with their picker labels. */
internal val TripProfiles: List<Pair<String, String>> = listOf(
    "no_trip" to "No trip",
    "distance_100_km" to "100 km trip",
    "distance_200_km" to "200 km trip",
    "target_80" to "Charge to 80%",
    "target_100" to "Charge to 100%",
)

internal fun tripProfileLabel(id: String?): String =
    TripProfiles.firstOrNull { it.first == id }?.second ?: id?.let(::humanLabel) ?: "Unknown"

/**
 * The settings form. Prices are edited in whole or half cents per kWh; null means the
 * controller did not report that setting, and its control stays disabled.
 */
internal data class SettingsDraft(
    val evChargeLimitPct: Int?,
    val minSellCents: Double?,
    val evFitMaxCents: Double?,
    val evGridAllowed: Boolean,
    val evTripProfile: String?,
)

private fun roundedCents(perKwh: Double?): Double? = perKwh?.let { (it * 1000).roundToInt() / 10.0 }

internal fun EnergySettings.toDraft() = SettingsDraft(
    evChargeLimitPct = evChargeLimitPct,
    minSellCents = roundedCents(minSellPricePerKwh),
    evFitMaxCents = roundedCents(evOpportunisticFitMaxPerKwh),
    evGridAllowed = evGridAllowed,
    evTripProfile = evTripProfile,
)

/** Only what differs from [base]; null when nothing changed (Save stays disabled). */
internal fun settingsPatch(base: EnergySettings, draft: SettingsDraft): EnergySettingsPatch? {
    val from = base.toDraft()
    val patch = EnergySettingsPatch(
        evChargeLimitPct = draft.evChargeLimitPct?.takeIf { it != from.evChargeLimitPct },
        minSellPricePerKwh = draft.minSellCents?.takeIf { it != from.minSellCents }?.div(100),
        evOpportunisticFitMaxPerKwh = draft.evFitMaxCents?.takeIf { it != from.evFitMaxCents }?.div(100),
        evGridAllowed = draft.evGridAllowed.takeIf { it != from.evGridAllowed },
        evTripProfile = draft.evTripProfile?.takeIf { it != from.evTripProfile },
    )
    return patch.takeIf { it != EnergySettingsPatch() }
}

/** The top of a price slider: the usual ceiling, raised to fit a larger value already set. */
internal fun sliderCeiling(current: Double?, usual: Double, step: Double): Float {
    val needed = current ?: return usual.toFloat()
    return if (needed <= usual) usual.toFloat() else (kotlin.math.ceil(needed / step) * step).toFloat()
}

// ---------------------------------------------------------------- signed actions

/**
 * @param message what will happen, shown in the confirmation dialog before phone unlock.
 * @param confirmLabel names the action; never "OK".
 * @param success shown once the controller accepts the command.
 */
internal data class ActionCopy(
    val title: String,
    val message: String,
    val confirmLabel: String,
    val success: String,
    val destructive: Boolean = false,
)

internal fun actionCopy(action: EnergyAction): ActionCopy = when (action) {
    EnergyAction.EnableAutomation -> ActionCopy(
        "Turn automation on?",
        "The controller will resume deciding when to charge, export and run flexible loads.",
        "Turn automation on",
        "Automation is on.",
    )
    EnergyAction.DisableAutomation -> ActionCopy(
        "Turn automation off?",
        "The controller stops sending commands. The inverter keeps its current safe behaviour and hot water falls back to its fixed timer.",
        "Turn automation off",
        "Automation is off.",
        destructive = true,
    )
    EnergyAction.HotWaterEnable -> ActionCopy(
        "Enable hot water?",
        "Hot-water heating returns to its normal schedule.",
        "Enable hot water",
        "Hot water is enabled.",
    )
    EnergyAction.HotWaterAway -> ActionCopy(
        "Set hot water to away?",
        "The hot-water system will not heat until it is enabled again.",
        "Set hot water away",
        "Hot water is in away mode.",
        destructive = true,
    )
    EnergyAction.StopEv -> ActionCopy(
        "Stop Tesla charging?",
        "Charging stops now. The plan may start it again later.",
        "Stop charging",
        "Tesla charging was told to stop.",
        destructive = true,
    )
    EnergyAction.StopHotWater -> ActionCopy(
        "Stop hot water?",
        "The hot-water element switches off now. The plan may run it again later.",
        "Stop hot water",
        "Hot water was told to stop.",
        destructive = true,
    )
    EnergyAction.SafeState -> ActionCopy(
        "Put the system in safe state?",
        "Forced battery charging and export stop, and the inverter returns to plain self-consumption.",
        "Go to safe state",
        "The system is in safe state.",
        destructive = true,
    )
}
