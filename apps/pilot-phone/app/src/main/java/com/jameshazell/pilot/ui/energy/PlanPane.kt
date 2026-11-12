package com.jameshazell.pilot.ui.energy

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.jameshazell.pilot.data.energy.EnergyBootstrap
import com.jameshazell.pilot.ui.components.CardNote
import com.jameshazell.pilot.ui.components.LevelSlider
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.StatCell
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens
import com.jameshazell.pilot.ui.theme.PilotIcons
import kotlin.math.roundToInt

/** The controller's recommendations and the 36-hour plan: tariff, power and battery timelines. */
@Composable
internal fun PlanPane(bootstrap: EnergyBootstrap) {
    val points = bootstrap.plan
    val actions = remember(bootstrap) { planActions(bootstrap) }

    PilotCard {
        CardTitle("What happens next")
        Text(
            bootstrap.narrative.currentSummary ?: "The controller is building its plan.",
            style = MaterialTheme.typography.titleLarge,
        )
        CardNote(bootstrap.narrative.headline ?: "Waiting for prices, solar and load forecasts.")
        if (actions.isEmpty()) {
            if (points.isNotEmpty()) CardNote("Nothing is scheduled in the next 36 hours.")
        } else {
            actions.take(8).forEach { action ->
                HorizontalDivider(color = PilotColors.Hairline)
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(planActionWhen(action), style = MaterialTheme.typography.labelMedium, color = PilotColors.Violet)
                    Text(action.title, style = MaterialTheme.typography.bodyLarge)
                    action.reason?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = PilotColors.TextDim) }
                }
            }
            if (actions.size > 8) CardNote("${actions.size - 8} later actions are not shown.")
        }
    }

    if (points.isEmpty()) {
        PilotCard {
            CardTitle("Tariff")
            Row(horizontalArrangement = Arrangement.spacedBy(PilotDimens.Gap)) {
                PriceCell("Import now", bootstrap.prices.importPerKwh, EnergyColors.Grid, Modifier.weight(1f))
                PriceCell("Feed-in now", bootstrap.prices.feedInPerKwh, EnergyColors.Solar, Modifier.weight(1f))
            }
            CardNote("The price timeline appears once the controller has published a plan.")
        }
        return
    }

    var selected by rememberSaveable { mutableIntStateOf(0) }
    val index = selected.coerceIn(0, points.lastIndex)
    val point = points[index]
    val xLabels = remember(points) { spreadLabels(points) { formatHour(it.start) } }
    val highlights = remember(points) { tariffHighlights(points) }

    PilotCard {
        CardTitle("Tariff")
        Row(horizontalArrangement = Arrangement.spacedBy(PilotDimens.Gap)) {
            PriceCell("Import now", bootstrap.prices.importPerKwh, EnergyColors.Grid, Modifier.weight(1f))
            PriceCell("Feed-in now", bootstrap.prices.feedInPerKwh, EnergyColors.Solar, Modifier.weight(1f))
        }
        LineChart(
            series = remember(points) {
                listOf(
                    ChartSeries("Import", EnergyColors.Grid, points.map { cents(it.importPerKwh) }),
                    ChartSeries("Feed-in", EnergyColors.Solar, points.map { cents(it.feedInPerKwh) }),
                )
            },
            unit = "c",
            summary = "Import and feed-in prices over the plan, in cents per kilowatt hour.",
            xLabels = xLabels,
            marker = index,
        )
        highlights.cheapestImport?.let { InfoLine("Cheapest import", "${formatPrice(it.perKwh)} · ${formatDayTime(it.at)}") }
        highlights.bestFeedIn?.let { InfoLine("Best feed-in", "${formatPrice(it.perKwh)} · ${formatDayTime(it.at)}") }
    }

    PilotCard {
        CardTitle("Look ahead")
        if (points.size > 1) {
            LevelSlider(
                label = "Time in the plan",
                value = index.toFloat(),
                valueText = formatDayTime(point.start),
                onValueChange = { selected = it.roundToInt() },
                range = 0f..points.lastIndex.toFloat(),
                accent = PilotColors.Violet,
            )
        }
        val planned = remember(bootstrap, index) { plannedFlowState(bootstrap, point) }
        InfoLine("Import price", formatPrice(point.importPerKwh))
        InfoLine("Feed-in price", formatPrice(point.feedInPerKwh))
        InfoLine("Solar", formatPower(planned.solarKw), EnergyColors.Solar)
        InfoLine("House", formatPower(planned.houseKw ?: point.loadKw), EnergyColors.House)
        InfoLine("Grid", gridLabel(planned.gridKw).let { if (planned.gridKw == null) it else "$it · ${formatPower(planned.gridKw)}" })
        InfoLine("Battery", "${formatPercent(planned.socPct)} · ${batteryNote(planned.batteryKw)}", EnergyColors.Battery)
        InfoLine("Tesla", formatPower(planned.carKw))
        CardNote("A forecast, not a command. The controller replans as prices, weather and demand change.")
    }

    PilotCard {
        CardTitle("Planned power")
        LineChart(
            series = remember(points) {
                listOf(
                    ChartSeries("Solar", EnergyColors.Solar, points.map { it.pvKw }),
                    ChartSeries("House", EnergyColors.House, points.map { it.loadKw }),
                    ChartSeries("Tesla", EnergyColors.Car, points.map { it.evKw }, activityThreshold = FLOW_ACTIVE_KW),
                )
            },
            unit = "kW",
            summary = "Planned solar, house and Tesla power over the next 36 hours.",
            xLabels = xLabels,
            marker = index,
        )
    }

    PilotCard {
        CardTitle("Predicted battery")
        LineChart(
            series = remember(points) {
                listOf(
                    ChartSeries("Battery", EnergyColors.Battery, points.map { it.predictedSocPct }),
                    ChartSeries("Protected reserve", PilotColors.TextFaint, points.map { it.protectedSocPct }),
                )
            },
            unit = "%",
            summary = "Predicted battery charge and the protected reserve over the next 36 hours.",
            bounds = 0.0..100.0,
            xLabels = xLabels,
            marker = index,
        )
    }

    val notes = remember(bootstrap) { planNotes(bootstrap) }
    if (notes.isNotEmpty()) {
        PilotCard {
            CardTitle("How the plan works")
            notes.forEach { CardNote(it) }
        }
    }
}

@Composable
private fun PriceCell(label: String, perKwh: Double?, accent: androidx.compose.ui.graphics.Color, modifier: Modifier = Modifier) {
    StatCell(
        PilotIcons.Energy,
        label,
        perKwh?.takeIf(Double::isFinite)?.let { "%.1f".format(java.util.Locale.US, it * 100) } ?: UNKNOWN,
        modifier,
        unit = perKwh?.let { "c/kWh" },
        accent = accent,
    )
}
