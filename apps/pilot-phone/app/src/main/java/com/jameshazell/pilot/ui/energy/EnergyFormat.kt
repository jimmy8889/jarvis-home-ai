package com.jameshazell.pilot.ui.energy

import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.math.abs
import kotlin.math.roundToInt

/* Wording for readings. An unknown reading is always "—", never zero. */

internal const val UNKNOWN = "—"

/** The house (and its Energy Manager) run on Brisbane time wherever the phone is. */
internal val HouseZone: ZoneId = ZoneId.of("Australia/Brisbane")

private val dayTime = DateTimeFormatter.ofPattern("EEE h:mm a", Locale.ENGLISH)
private val timeOnly = DateTimeFormatter.ofPattern("h:mm a", Locale.ENGLISH)
private val hourOnly = DateTimeFormatter.ofPattern("ha", Locale.ENGLISH)
private val shortDate = DateTimeFormatter.ofPattern("d MMM", Locale.ENGLISH)

/** A value and its unit, for StatCell. */
internal data class Reading(val value: String, val unit: String?)

private fun fixed(value: Double, decimals: Int): String = String.format(Locale.US, "%.${decimals}f", value)

/** Magnitude of a power in kW: "850 W", "3.4 kW". Direction is worded separately. */
internal fun powerReading(kw: Double?): Reading = when {
    kw == null || !kw.isFinite() -> Reading(UNKNOWN, null)
    abs(kw) < 1 -> Reading(fixed(abs(kw) * 1000, 0), "W")
    else -> Reading(fixed(abs(kw), 1), "kW")
}

internal fun formatPower(kw: Double?): String = powerReading(kw).let { if (it.unit == null) it.value else "${it.value} ${it.unit}" }

internal fun formatWatts(watts: Double?): String = watts?.takeIf(Double::isFinite)?.let { "${fixed(it, 0)} W" } ?: UNKNOWN

internal fun formatPercent(value: Double?): String = value?.takeIf(Double::isFinite)?.let { "${it.roundToInt()}%" } ?: UNKNOWN

internal fun formatKwh(value: Double?): String = value?.takeIf(Double::isFinite)?.let { "${fixed(it, 1)} kWh" } ?: UNKNOWN

internal fun formatVolts(value: Double?): String = value?.takeIf(Double::isFinite)?.let { "${fixed(it, 0)} V" } ?: UNKNOWN

/** A price in dollars per kWh shown as cents: 0.285 -> "28.5 c/kWh". Negative prices keep their sign. */
internal fun formatPrice(perKwh: Double?): String = perKwh?.takeIf(Double::isFinite)?.let { "${fixed(it * 100, 1)} c/kWh" } ?: UNKNOWN

internal fun formatCents(cents: Double): String =
    if (abs(cents - cents.roundToInt()) < 0.05) "${cents.roundToInt()} c/kWh" else "${fixed(cents, 1)} c/kWh"

/** "25 min", "1 h 5 min"; unknown or negative is "—". */
internal fun formatRuntime(seconds: Double?): String {
    if (seconds == null || !seconds.isFinite() || seconds < 0) return UNKNOWN
    val minutes = (seconds / 60).toInt()
    return when {
        minutes < 1 -> "Under 1 min"
        minutes < 60 -> "$minutes min"
        minutes % 60 == 0 -> "${minutes / 60} h"
        else -> "${minutes / 60} h ${minutes % 60} min"
    }
}

internal fun formatDayTime(at: Instant?): String = at?.let { dayTime.format(it.atZone(HouseZone)) } ?: UNKNOWN

internal fun formatTime(at: Instant?): String = at?.let { timeOnly.format(it.atZone(HouseZone)) } ?: UNKNOWN

/** Compact axis label: "3PM". */
internal fun formatHour(at: Instant?): String = at?.let { hourOnly.format(it.atZone(HouseZone)) } ?: ""

/** "2026-11-11" -> "11 Nov"; anything else is returned unchanged. */
internal fun formatDate(isoDate: String?): String {
    if (isoDate == null) return UNKNOWN
    return runCatching { shortDate.format(LocalDate.parse(isoDate.take(10))) }.getOrDefault(isoDate)
}
