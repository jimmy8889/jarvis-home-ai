package com.jameshazell.pilot.ui.energy

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.data.energy.EnergyBootstrap
import com.jameshazell.pilot.data.energy.EnergyDay
import com.jameshazell.pilot.data.energy.EnergyTelemetry
import com.jameshazell.pilot.ui.components.CardNote
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.StatCell
import com.jameshazell.pilot.ui.components.StateScaffold
import com.jameshazell.pilot.ui.theme.PilotDimens
import com.jameshazell.pilot.ui.theme.PilotIcons

/** Tall enough for StateScaffold's error state and for a chart under a "saved data" banner. */
private val ChartSlotHeight = 300.dp

/**
 * Solar: what the panels do now, the last 24 hours and the last 30 days.
 *
 * @param onVisible told true when this pane appears and false when it leaves, so recorded
 * history is only fetched while someone is looking at it.
 */
@Composable
internal fun SolarPane(
    bootstrap: EnergyBootstrap,
    history: LoadState<List<EnergyTelemetry>>,
    daily: LoadState<List<EnergyDay>>,
    onVisible: (Boolean) -> Unit,
    onRetry: () -> Unit,
) {
    DisposableEffect(Unit) {
        onVisible(true)
        onDispose { onVisible(false) }
    }

    val telemetry = bootstrap.telemetry
    val forecast = bootstrap.forecast
    PilotCard {
        CardTitle("Solar now")
        Row(horizontalArrangement = Arrangement.spacedBy(PilotDimens.Gap)) {
            val now = powerReading(telemetry.pvKw)
            StatCell(PilotIcons.Sun, "Generating", now.value, Modifier.weight(1f), unit = now.unit, accent = EnergyColors.Solar)
            val expected = powerReading(forecast.expectedPvKw)
            StatCell(
                PilotIcons.Sun, "Expected", expected.value, Modifier.weight(1f), unit = expected.unit,
                note = if (forecast.expectedPvFresh) "From the weather station" else "Reading may be old",
                accent = EnergyColors.Grid,
            )
        }
        telemetry.pvStringsKw.forEachIndexed { index, kw -> InfoLine("Solar input ${index + 1}", formatPower(kw), EnergyColors.Solar) }
        InfoLine("Sunlight, horizontal", irradiance(forecast.ghiWm2))
        InfoLine("Sunlight, north roof", irradiance(forecast.poaNorthWm2))
        InfoLine("Sunlight, south roof", irradiance(forecast.poaSouthWm2))
    }

    PilotCard {
        CardTitle("Last 24 hours")
        StateScaffold(history, onRetry = onRetry, modifier = Modifier.height(ChartSlotHeight), loadingLabel = "Loading recorded history…") { rows ->
            if (rows.none { it.pvKw != null || it.loadKw != null || it.gridKw != null }) {
                EmptyChart("History appears once the controller has recorded some readings.")
            } else {
                LineChart(
                    series = remember(rows) {
                        listOf(
                            ChartSeries("Solar", EnergyColors.Solar, rows.map { it.pvKw }),
                            ChartSeries("House", EnergyColors.House, rows.map { it.loadKw }),
                            ChartSeries("Grid (import +, export −)", EnergyColors.Grid, rows.map { it.gridKw }),
                        )
                    },
                    unit = "kW",
                    summary = "Solar, house and grid power over the last 24 hours.",
                    xLabels = remember(rows) { spreadLabels(rows.filter { it.measuredAt != null }) { formatHour(it.measuredAt) } },
                )
            }
        }
    }

    PilotCard {
        CardTitle("Last 30 days")
        StateScaffold(daily, onRetry = onRetry, modifier = Modifier.height(ChartSlotHeight), loadingLabel = "Loading daily totals…") { days ->
            if (days.none { it.solarGeneratedKwh != null || it.houseConsumedKwh != null }) {
                EmptyChart("Daily totals appear after the first full day of recording.")
            } else {
                DailyBars(
                    days = remember(days) { days.map { DayBars(formatDate(it.date), it.solarGeneratedKwh, it.houseConsumedKwh) } },
                    primary = "Generated" to EnergyColors.Solar,
                    secondary = "Used" to EnergyColors.House,
                    unit = "kWh",
                    summary = "Energy generated and used each day for the last ${days.size} days.",
                )
            }
        }
        (daily as? LoadState.Content)?.value?.takeIf { it.isNotEmpty() }?.let { days ->
            InfoLine("Generated", formatKwh(knownTotal(days.map { it.solarGeneratedKwh })), EnergyColors.Solar)
            InfoLine("Used", formatKwh(knownTotal(days.map { it.houseConsumedKwh })), EnergyColors.House)
            InfoLine("Exported", formatKwh(knownTotal(days.map { it.gridExportedKwh })), EnergyColors.Grid)
        }
    }
}

private fun irradiance(value: Double?): String = value?.takeIf(Double::isFinite)?.let { "%.0f W/m²".format(java.util.Locale.US, it) } ?: UNKNOWN

@Composable
private fun EmptyChart(text: String) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CardNote(text) }
}
