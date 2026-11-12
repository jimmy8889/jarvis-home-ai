package com.jameshazell.pilot.ui.energy

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.foundation.background
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.jameshazell.pilot.ui.theme.PilotColors
import java.util.Locale

/*
 * Charts drawn with Compose Canvas only. Paths are built once per data/size change
 * (drawWithCache), not per frame.
 */

/**
 * One line on a [LineChart].
 *
 * @param values one sample per x step; null breaks the line (an unknown reading is not zero).
 * @param activityThreshold when set, samples below it (in magnitude) break the line too.
 */
internal data class ChartSeries(
    val label: String,
    val color: Color,
    val values: List<Double?>,
    val activityThreshold: Double? = null,
)

/**
 * A multi-series line chart with a legend, min/max labels on the left and time labels below.
 *
 * @param unit appended to the axis numbers, e.g. "kW".
 * @param bounds fixed vertical range (e.g. 0..100 for percent); by default it fits the data.
 * @param xLabels a few evenly spread labels for the time axis, first to last.
 * @param marker index of a sample to mark with a vertical line (the scrubber), if any.
 * @param summary what a screen reader says instead of the picture.
 */
@Composable
internal fun LineChart(
    series: List<ChartSeries>,
    unit: String,
    summary: String,
    modifier: Modifier = Modifier,
    height: Dp = 170.dp,
    bounds: ClosedFloatingPointRange<Double>? = null,
    xLabels: List<String> = emptyList(),
    marker: Int? = null,
) {
    val range = bounds ?: chartBounds(series.map { it.values })
    val count = series.maxOfOrNull { it.values.size } ?: 0
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        ChartLegend(series.map { it.label to it.color })
        Row(Modifier.fillMaxWidth().height(height)) {
            Column(Modifier.width(44.dp).fillMaxSize(), verticalArrangement = Arrangement.SpaceBetween) {
                AxisLabel(axisNumber(range.endInclusive, unit))
                if (range.start < 0 && range.endInclusive > 0) AxisLabel("0")
                AxisLabel(axisNumber(range.start, unit))
            }
            Spacer(
                Modifier
                    .weight(1f)
                    .fillMaxSize()
                    .semantics { contentDescription = summary }
                    .drawWithCache {
                        val span = (range.endInclusive - range.start).takeIf { it > 0 } ?: 1.0
                        fun x(index: Int) = if (count <= 1) size.width / 2 else index * size.width / (count - 1)
                        fun y(value: Double) = (size.height - (value - range.start) / span * size.height).toFloat()
                        val lines = series.map { line ->
                            Path().apply {
                                for (segment in chartSegments(line.values, line.activityThreshold)) {
                                    moveTo(x(segment.first), y(line.values[segment.first]!!))
                                    if (segment.first == segment.last) {
                                        // A lone sample would otherwise be invisible.
                                        lineTo(x(segment.first) + 1f, y(line.values[segment.first]!!))
                                    }
                                    for (index in segment.first + 1..segment.last) lineTo(x(index), y(line.values[index]!!))
                                }
                            }
                        }
                        val stroke = Stroke(2.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round)
                        val hair = 1.dp.toPx()
                        val zero = y(0.0)
                        onDrawBehind {
                            for (step in 0..2) {
                                val gridY = size.height * step / 2
                                drawLine(PilotColors.Hairline, Offset(0f, gridY), Offset(size.width, gridY), hair)
                            }
                            if (range.start < 0) drawLine(PilotColors.TextFaint, Offset(0f, zero), Offset(size.width, zero), hair)
                            lines.forEachIndexed { index, path -> drawPath(path, series[index].color, style = stroke) }
                            if (marker != null && count > 0) {
                                val markerX = x(marker.coerceIn(0, count - 1))
                                drawLine(PilotColors.Text, Offset(markerX, 0f), Offset(markerX, size.height), hair)
                            }
                        }
                    },
            )
        }
        if (xLabels.isNotEmpty()) {
            Row(Modifier.fillMaxWidth()) {
                Spacer(Modifier.width(44.dp))
                Row(Modifier.weight(1f), horizontalArrangement = Arrangement.SpaceBetween) {
                    xLabels.forEach { AxisLabel(it) }
                }
            }
        }
    }
}

/** One bar group per day on a [DailyBars] chart; unknown values draw no bar. */
internal data class DayBars(val label: String, val primary: Double?, val secondary: Double?)

/**
 * Daily totals as paired bars (e.g. generated and used), oldest on the left.
 *
 * @param summary what a screen reader says instead of the picture.
 */
@Composable
internal fun DailyBars(
    days: List<DayBars>,
    primary: Pair<String, Color>,
    secondary: Pair<String, Color>,
    unit: String,
    summary: String,
    modifier: Modifier = Modifier,
    height: Dp = 170.dp,
) {
    val range = chartBounds(listOf(days.map { it.primary }, days.map { it.secondary }))
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        ChartLegend(listOf(primary, secondary))
        Row(Modifier.fillMaxWidth().height(height)) {
            Column(Modifier.width(44.dp).fillMaxSize(), verticalArrangement = Arrangement.SpaceBetween) {
                AxisLabel(axisNumber(range.endInclusive, unit))
                AxisLabel("0")
            }
            Spacer(
                Modifier
                    .weight(1f)
                    .fillMaxSize()
                    .semantics { contentDescription = summary }
                    .drawWithCache {
                        val top = range.endInclusive.takeIf { it > 0 } ?: 1.0
                        val slot = if (days.isEmpty()) size.width else size.width / days.size
                        val bar = (slot * 0.36f).coerceAtLeast(1f)
                        val corner = CornerRadius(bar / 3)
                        val hair = 1.dp.toPx()
                        onDrawBehind {
                            for (step in 0..2) {
                                val gridY = size.height * step / 2
                                drawLine(PilotColors.Hairline, Offset(0f, gridY), Offset(size.width, gridY), hair)
                            }
                            days.forEachIndexed { index, day ->
                                val left = index * slot + slot * 0.1f
                                day.primary?.takeIf { it > 0 }?.let { value ->
                                    val barHeight = (value / top * size.height).toFloat()
                                    drawRoundRect(primary.second, Offset(left, size.height - barHeight), Size(bar, barHeight), corner)
                                }
                                day.secondary?.takeIf { it > 0 }?.let { value ->
                                    val barHeight = (value / top * size.height).toFloat()
                                    drawRoundRect(secondary.second, Offset(left + bar + slot * 0.06f, size.height - barHeight), Size(bar, barHeight), corner)
                                }
                            }
                        }
                    },
            )
        }
        if (days.isNotEmpty()) {
            Row(Modifier.fillMaxWidth()) {
                Spacer(Modifier.width(44.dp))
                Row(Modifier.weight(1f), horizontalArrangement = Arrangement.SpaceBetween) {
                    AxisLabel(days.first().label)
                    if (days.size > 2) AxisLabel(days[days.size / 2].label)
                    if (days.size > 1) AxisLabel(days.last().label)
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ChartLegend(entries: List<Pair<String, Color>>) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        entries.forEach { (label, color) ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(8.dp).clip(CircleShape).background(color))
                Spacer(Modifier.width(6.dp))
                Text(label, style = MaterialTheme.typography.labelMedium, color = PilotColors.TextDim)
            }
        }
    }
}

@Composable
private fun AxisLabel(text: String) {
    Text(text, style = MaterialTheme.typography.labelMedium, color = PilotColors.TextFaint, maxLines = 1)
}

private fun axisNumber(value: Double, unit: String): String {
    val number = if (kotlin.math.abs(value) >= 10 || value == value.toLong().toDouble()) {
        String.format(Locale.US, "%.0f", value)
    } else {
        String.format(Locale.US, "%.1f", value)
    }
    return "$number $unit"
}

/** Up to [count] evenly spread labels from a list of sample times (first … last). */
internal fun <T> spreadLabels(items: List<T>, count: Int = 4, label: (T) -> String): List<String> {
    if (items.isEmpty()) return emptyList()
    if (items.size <= count) return listOf(label(items.first()), label(items.last())).distinct()
    return (0 until count).map { step -> label(items[step * (items.size - 1) / (count - 1)]) }
}
