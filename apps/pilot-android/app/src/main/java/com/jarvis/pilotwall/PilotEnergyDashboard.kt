@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package com.jarvis.pilotwall

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import java.time.Duration
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min

private enum class DashboardPage(val title: String) { Flow("Flow"), History("History"), Daily("Daily"), Climate("Climate") }

internal const val ENERGY_ACTIVITY_THRESHOLD_W = 25.0
internal const val GRID_ACTIVITY_THRESHOLD_W = 100.0
internal const val BATTERY_ACTIVITY_THRESHOLD_W = 100.0
internal const val VEHICLE_ACTIVITY_THRESHOLD_W = 100.0

internal fun isDayEnergyScene(solarW: Double?): Boolean = (solarW ?: 0.0) >= GRID_ACTIVITY_THRESHOLD_W

internal fun shouldShowVehicleEnergy(vehicle: DashboardVehicle): Boolean =
    vehicle.connected == true && abs(vehicle.powerW ?: 0.0) >= VEHICLE_ACTIVITY_THRESHOLD_W

@Composable
fun PilotEnergyDashboard(state: PilotUiState, model: PilotViewModel) {
    var page by remember { mutableStateOf(DashboardPage.Flow) }
    val dashboard = state.snapshot?.dashboard
    val animationsEnabled = rememberSystemAnimationsEnabled()
    Column(Modifier.fillMaxSize().padding(horizontal = 20.dp, vertical = 12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("JAMES HOUSE", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.labelSmall)
                Text("Home intelligence", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            }
            Text(
                if (dashboard?.status == "ok") "● Live" else "● Reconnecting",
                color = if (dashboard?.status == "ok") PilotMint else PilotAmber,
                fontWeight = FontWeight.SemiBold,
            )
        }
        Row(Modifier.padding(vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            DashboardPage.entries.forEach { item ->
                if (page == item) Button(onClick = { page = item }) { Text(item.title) }
                else OutlinedButton(onClick = { page = item }) { Text(item.title) }
            }
        }
        if (dashboard == null) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Card(shape = RoundedCornerShape(24.dp)) {
                    Column(Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                        Text("Dashboard is connecting", style = MaterialTheme.typography.headlineSmall)
                        Text("Pilot Core will restore the live view automatically.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Spacer(Modifier.height(12.dp))
                        Button(onClick = model::refresh) { Text("Refresh") }
                    }
                }
            }
        } else {
            when (page) {
                DashboardPage.Flow -> FlowDashboard(dashboard, animationsEnabled)
                DashboardPage.History -> HistoryDashboard(dashboard)
                DashboardPage.Daily -> DailyDashboard(dashboard, state.actionInFlight, model)
                DashboardPage.Climate -> ClimateDashboard(dashboard)
            }
        }
    }
}

@Composable
private fun FlowDashboard(value: DashboardSnapshot, animationsEnabled: Boolean) {
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            DailyMetric("Generated", value.daily.generatedKWh, PilotAmber, Modifier.weight(1f))
            DailyMetric("Home used", value.daily.homeKWh, PilotMint, Modifier.weight(1f))
            DailyMetric("Exported", value.daily.exportedKWh, PilotCyan, Modifier.weight(1f))
        }
        Card(
            Modifier.fillMaxSize(),
            colors = CardDefaults.cardColors(containerColor = Color(0xFF030812)),
            shape = RoundedCornerShape(28.dp),
        ) {
            BoxWithConstraints(Modifier.fillMaxSize()) {
                val daytime = value.sceneIsDay ?: isDayEnergyScene(value.power.solarW)
                val carPresent = value.vehicle.connected == true
                val showVehicleEnergy = shouldShowVehicleEnergy(value.vehicle)
                Image(
                    painter = painterResource(
                        when {
                            daytime && carPresent -> R.drawable.pilot_house_energy
                            daytime -> R.drawable.pilot_house_no_car
                            carPresent -> R.drawable.pilot_house_night_car
                            else -> R.drawable.pilot_house_night
                        },
                    ),
                    contentDescription = if (daytime) "James House during the day" else "James House at night",
                    modifier = Modifier.fillMaxSize().padding(horizontal = 42.dp, vertical = 6.dp),
                    contentScale = ContentScale.Fit,
                )
                EnergyFlowCanvas(
                    value.power,
                    value.vehicle,
                    animationsEnabled,
                    Modifier.fillMaxSize(),
                )
                HomeEnergyNode(
                    Modifier
                        .offset(x = maxWidth * .48f, y = maxHeight * .47f)
                        .size(62.dp),
                )
                AnimatedBatteryTower(
                    soc = value.power.batterySocPercent,
                    powerW = value.power.batteryW,
                    direction = value.power.batteryDirection,
                    animationsEnabled = animationsEnabled,
                    modifier = Modifier
                        .offset(x = maxWidth * .69f, y = maxHeight * .60f)
                        .size(width = 72.dp, height = 116.dp),
                )
                ServerRackVisual(
                    powerW = value.power.serverRackW,
                    animationsEnabled = animationsEnabled,
                    modifier = Modifier
                        .offset(x = maxWidth * .84f, y = maxHeight * .53f)
                        .size(width = 76.dp, height = 116.dp),
                )
                FlowMetric(
                    "PV",
                    watts(value.power.solarW),
                    PilotAmber,
                    Modifier.align(Alignment.TopCenter).padding(top = 8.dp),
                    detail = if ((value.power.solarW ?: 0.0) >= ENERGY_ACTIVITY_THRESHOLD_W) "Producing" else "Idle",
                )
                FlowMetric(
                    "Grid",
                    watts(value.power.gridW),
                    PilotCyan,
                    Modifier.align(Alignment.TopEnd).padding(end = 18.dp, top = 20.dp),
                    detail = if (value.power.gridDirection == "exporting") "Export" else "Import",
                )
                if (carPresent) {
                    FlowMetric(
                        "Jarvis",
                        if (showVehicleEnergy) watts(value.vehicle.powerW) else "Plugged in",
                        PilotRed,
                        Modifier.align(Alignment.BottomStart).padding(start = 18.dp, bottom = 22.dp),
                        detail = if (showVehicleEnergy) "Charging" else "Ready",
                    )
                }
                FlowMetric(
                    "Home",
                    watts(value.power.homeLoadW),
                    PilotMint,
                    Modifier.align(Alignment.BottomCenter).padding(bottom = 14.dp),
                    detail = "Consuming",
                )
                FlowMetric(
                    "Server rack",
                    watts(value.power.serverRackW),
                    ServerViolet,
                    Modifier.align(Alignment.BottomEnd).padding(end = 12.dp, bottom = 16.dp),
                    detail = "Always on",
                )
            }
        }
    }
}

@Composable
private fun EnergyFlowCanvas(
    power: DashboardPower,
    vehicle: DashboardVehicle,
    animationsEnabled: Boolean,
    modifier: Modifier,
) {
    val maximum = maxOf(
        abs(power.solarW ?: 0.0), abs(power.gridW ?: 0.0), abs(power.batteryW ?: 0.0),
        abs(vehicle.powerW ?: 0.0), abs(power.serverRackW ?: 0.0), 1.0,
    )
    val duration = (3900 - min(2500.0, maximum / 3)).toInt().coerceAtLeast(900)
    val phase = if (animationsEnabled) {
        val animatedPhase by rememberInfiniteTransition(label = "power-flow").animateFloat(
            initialValue = 0f, targetValue = 1f,
            animationSpec = infiniteRepeatable(tween(duration, easing = LinearEasing)), label = "phase",
        )
        animatedPhase
    } else {
        .35f
    }
    Canvas(modifier) {
        fun flow(
            anchors: List<Offset>,
            watts: Double?,
            color: Color,
            active: Boolean,
            reverse: Boolean = false,
            showInactiveTrack: Boolean = true,
        ) {
            val magnitude = abs(watts ?: 0.0)
            val points = roundedRoute(anchors)
            if (showInactiveTrack) drawRoute(points, Color.White.copy(alpha = .09f), 5f)
            if (!active) return
            val intensity = (.30f + min(1.0, magnitude / 7000).toFloat() * .70f)
            drawRoute(points, color.copy(alpha = .24f + intensity * .28f), 3.5f + intensity * 4.5f)
            listOf(0f, .5f).forEach { offset ->
                val start = (phase + offset) % 1f
                val end = start + .10f + intensity * .04f
                drawGlow(points, start, min(1f, end), color, reverse, intensity)
                if (end > 1f) drawGlow(points, 0f, end - 1f, color, reverse, intensity)
            }
        }
        val centre = Offset(size.width * .54f, size.height * .51f)
        flow(
            listOf(Offset(size.width * .52f, size.height * .15f), Offset(size.width * .66f, size.height * .15f), centre),
            power.solarW,
            PilotAmber,
            (power.solarW ?: 0.0) >= ENERGY_ACTIVITY_THRESHOLD_W,
        )
        flow(
            listOf(Offset(size.width * .93f, size.height * .26f), Offset(size.width * .77f, size.height * .26f), centre),
            power.gridW,
            PilotCyan,
            power.gridFlowActive && abs(power.gridW ?: 0.0) >= GRID_ACTIVITY_THRESHOLD_W,
            reverse = power.gridDirection == "exporting",
        )
        flow(
            listOf(Offset(size.width * .72f, size.height * .70f), Offset(size.width * .72f, size.height * .57f), centre),
            power.batteryW,
            PilotMint,
            abs(power.batteryW ?: 0.0) >= BATTERY_ACTIVITY_THRESHOLD_W,
            reverse = power.batteryDirection == "charging",
            showInactiveTrack = false,
        )
        flow(
            listOf(centre, Offset(size.width * .23f, size.height * .51f), Offset(size.width * .23f, size.height * .72f)),
            vehicle.powerW,
            PilotRed,
            shouldShowVehicleEnergy(vehicle),
            showInactiveTrack = false,
        )
        flow(
            listOf(centre, Offset(size.width * .81f, size.height * .51f), Offset(size.width * .86f, size.height * .62f)),
            power.serverRackW,
            ServerViolet,
            abs(power.serverRackW ?: 0.0) >= ENERGY_ACTIVITY_THRESHOLD_W,
        )
        flow(
            listOf(centre, Offset(size.width * .50f, size.height * .60f)),
            power.homeLoadW,
            PilotMint,
            abs(power.homeLoadW ?: 0.0) >= ENERGY_ACTIVITY_THRESHOLD_W,
        )
    }
}

private val ServerViolet = Color(0xFFB49BFF)

private fun androidx.compose.ui.graphics.drawscope.DrawScope.roundedRoute(anchors: List<Offset>): List<Offset> {
    if (anchors.size < 3) return anchors
    val result = mutableListOf(anchors.first())
    anchors.indices.drop(1).dropLast(1).forEach { index ->
        val previous = anchors[index - 1]
        val corner = anchors[index]
        val next = anchors[index + 1]
        val incoming = hypot((corner.x - previous.x).toDouble(), (corner.y - previous.y).toDouble()).toFloat()
        val outgoing = hypot((next.x - corner.x).toDouble(), (next.y - corner.y).toDouble()).toFloat()
        if (incoming == 0f || outgoing == 0f) return@forEach
        val radius = min(18f, min(incoming * .35f, outgoing * .35f))
        val before = Offset(
            corner.x - (corner.x - previous.x) / incoming * radius,
            corner.y - (corner.y - previous.y) / incoming * radius,
        )
        val after = Offset(
            corner.x + (next.x - corner.x) / outgoing * radius,
            corner.y + (next.y - corner.y) / outgoing * radius,
        )
        result += before
        (1..6).forEach { step ->
            val t = step / 6f
            val inverse = 1 - t
            result += Offset(
                inverse * inverse * before.x + 2 * inverse * t * corner.x + t * t * after.x,
                inverse * inverse * before.y + 2 * inverse * t * corner.y + t * t * after.y,
            )
        }
    }
    result += anchors.last()
    return result
}

private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawRoute(points: List<Offset>, color: Color, width: Float) {
    if (points.isEmpty()) return
    val path = Path().apply {
        moveTo(points.first().x, points.first().y)
        points.drop(1).forEach { lineTo(it.x, it.y) }
    }
    drawPath(path, color, style = Stroke(width = width, cap = StrokeCap.Round, join = StrokeJoin.Round))
}

private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawGlow(
    points: List<Offset>,
    start: Float,
    end: Float,
    color: Color,
    reverse: Boolean,
    intensity: Float,
) {
    if (end <= start || points.size < 2) return
    val samples = (0..9).map { step ->
        val progress = start + (end - start) * step / 9f
        pointOnRoute(points, if (reverse) 1f - progress else progress)
    }
    drawRoute(samples, color.copy(alpha = .12f + intensity * .11f), 15f + intensity * 5f)
    drawRoute(samples, color.copy(alpha = .42f + intensity * .30f), 7f + intensity * 3f)
    drawRoute(samples, Color.White.copy(alpha = .82f + intensity * .16f), 2.2f)
}

private fun pointOnRoute(points: List<Offset>, progress: Float): Offset {
    val lengths = points.zipWithNext { first, second -> (second - first).getDistance() }
    val total = lengths.sum().coerceAtLeast(.001f)
    var distance = progress.coerceIn(0f, 1f) * total
    lengths.forEachIndexed { index, length ->
        if (distance <= length) {
            val ratio = if (length == 0f) 0f else distance / length
            return points[index] + (points[index + 1] - points[index]) * ratio
        }
        distance -= length
    }
    return points.last()
}

@Composable
private fun HomeEnergyNode(modifier: Modifier) {
    Canvas(modifier.semantics { contentDescription = "Home energy junction" }) {
        drawCircle(Color(0xE6030812), radius = size.minDimension * .46f)
        drawCircle(PilotMint.copy(alpha = .82f), radius = size.minDimension * .46f, style = Stroke(3f))
        val centre = Offset(size.width / 2, size.height * .55f)
        val roof = Path().apply {
            moveTo(size.width * .22f, size.height * .48f)
            lineTo(size.width * .50f, size.height * .24f)
            lineTo(size.width * .78f, size.height * .48f)
            lineTo(size.width * .70f, size.height * .48f)
            lineTo(size.width * .70f, size.height * .75f)
            lineTo(size.width * .30f, size.height * .75f)
            lineTo(size.width * .30f, size.height * .48f)
            close()
        }
        drawPath(roof, PilotMint)
        drawCircle(Color.White.copy(alpha = .85f), radius = 2.5f, center = centre)
    }
}

@Composable
private fun AnimatedBatteryTower(
    soc: Double?,
    powerW: Double?,
    direction: String,
    animationsEnabled: Boolean,
    modifier: Modifier,
) {
    val targetSoc = ((soc ?: 0.0) / 100.0).toFloat().coerceIn(0f, 1f)
    val changingSoc by animateFloatAsState(targetSoc, tween(900), label = "battery-soc")
    val animatedSoc = if (animationsEnabled) changingSoc else targetSoc
    val active = abs(powerW ?: 0.0) >= BATTERY_ACTIVITY_THRESHOLD_W
    val charging = direction == "charging"
    val motion = if (animationsEnabled) {
        val transition = rememberInfiniteTransition(label = "battery-motion")
        val sweep by transition.animateFloat(
            0f,
            1f,
            infiniteRepeatable(tween(1250, easing = LinearEasing)),
            label = "battery-sweep",
        )
        val pulse by transition.animateFloat(
            .25f,
            1f,
            infiniteRepeatable(tween(850), RepeatMode.Reverse),
            label = "battery-pulse",
        )
        sweep to pulse
    } else {
        .5f to .65f
    }
    val sweep = motion.first
    val pulse = motion.second
    Box(
        modifier
            .graphicsLayer {
                scaleX = 1f + if (active && animationsEnabled) pulse * .018f else 0f
                scaleY = 1f + if (active && animationsEnabled) pulse * .018f else 0f
            }
            .semantics {
                contentDescription = "Home battery ${soc?.toInt() ?: 0} percent, ${direction.ifBlank { "idle" }}"
            },
        contentAlignment = Alignment.Center,
    ) {
        Canvas(Modifier.fillMaxSize()) {
            val bodyLeft = size.width * .12f
            val bodyTop = size.height * .09f
            val bodyWidth = size.width * .76f
            val bodyHeight = size.height * .82f
            val radius = CornerRadius(12f, 12f)
            if (active) {
                drawRoundRect(
                    PilotMint.copy(alpha = pulse * .12f),
                    topLeft = Offset(bodyLeft - 7f, bodyTop - 7f),
                    size = Size(bodyWidth + 14f, bodyHeight + 14f),
                    cornerRadius = CornerRadius(17f, 17f),
                )
            }
            drawRoundRect(Color(0xFF101A21), Offset(bodyLeft, bodyTop), Size(bodyWidth, bodyHeight), radius)
            drawRoundRect(
                if (active) PilotMint.copy(alpha = .45f + pulse * .4f) else Color.White.copy(alpha = .22f),
                Offset(bodyLeft, bodyTop),
                Size(bodyWidth, bodyHeight),
                radius,
                style = Stroke(if (active) 3.5f else 2f),
            )
            val inset = 7f
            val innerHeight = bodyHeight - inset * 2
            val filledHeight = innerHeight * animatedSoc
            val fillTop = bodyTop + inset + innerHeight - filledHeight
            drawRoundRect(
                brush = Brush.verticalGradient(
                    if (charging) listOf(PilotCyan, PilotMint) else listOf(PilotMint, Color(0xFF2C936F)),
                    startY = fillTop,
                    endY = bodyTop + bodyHeight - inset,
                ),
                topLeft = Offset(bodyLeft + inset, fillTop),
                size = Size(bodyWidth - inset * 2, filledHeight.coerceAtLeast(1f)),
                cornerRadius = CornerRadius(7f, 7f),
                alpha = .82f,
            )
            if (active && animationsEnabled && filledHeight > 2f) {
                val travel = innerHeight * sweep
                val y = if (charging) bodyTop + bodyHeight - inset - travel else bodyTop + inset + travel
                if (y in fillTop..(bodyTop + bodyHeight - inset)) {
                    drawLine(Color.White.copy(alpha = .85f), Offset(bodyLeft + inset + 3f, y), Offset(bodyLeft + bodyWidth - inset - 3f, y), 3f, StrokeCap.Round)
                    drawLine(PilotMint.copy(alpha = .24f), Offset(bodyLeft + inset, y), Offset(bodyLeft + bodyWidth - inset, y), 11f, StrokeCap.Round)
                }
            }
            repeat(3) { index ->
                val y = bodyTop + bodyHeight * (index + 1) / 4f
                drawLine(Color.White.copy(alpha = .10f), Offset(bodyLeft + inset, y), Offset(bodyLeft + bodyWidth - inset, y), 1f)
            }
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(if (!active) "—" else if (charging) "↓" else "↑", color = Color.White, fontWeight = FontWeight.Bold)
            Text(soc?.let { "${it.toInt()}%" } ?: "—", color = Color.White, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
private fun ServerRackVisual(powerW: Double?, animationsEnabled: Boolean, modifier: Modifier) {
    val active = abs(powerW ?: 0.0) >= ENERGY_ACTIVITY_THRESHOLD_W
    val lights = if (animationsEnabled) {
        val transition = rememberInfiniteTransition(label = "rack-lights")
        val blink by transition.animateFloat(
            .18f,
            1f,
            infiniteRepeatable(tween(720), RepeatMode.Reverse),
            label = "rack-blink-a",
        )
        val alternateBlink by transition.animateFloat(
            1f,
            .12f,
            infiniteRepeatable(tween(940), RepeatMode.Reverse),
            label = "rack-blink-b",
        )
        blink to alternateBlink
    } else {
        .72f to .42f
    }
    val blink = lights.first
    val alternateBlink = lights.second
    Box(
        modifier.semantics {
            contentDescription = "Server rack using ${watts(powerW)}"
        },
    ) {
        Image(
            painter = painterResource(R.drawable.pilot_server_rack),
            contentDescription = null,
            modifier = Modifier.fillMaxSize(),
            contentScale = ContentScale.Crop,
        )
        Canvas(Modifier.fillMaxSize()) {
            val ledPoints = listOf(
                Offset(size.width * .46f, size.height * .34f),
                Offset(size.width * .53f, size.height * .40f),
                Offset(size.width * .48f, size.height * .48f),
                Offset(size.width * .56f, size.height * .55f),
                Offset(size.width * .47f, size.height * .63f),
                Offset(size.width * .55f, size.height * .72f),
            )
            ledPoints.forEachIndexed { index, point ->
                val color = if (index % 3 == 0) PilotCyan else PilotMint
                val alpha = if (!active) .12f else if (index % 2 == 0) blink else alternateBlink
                drawCircle(color.copy(alpha = alpha * .22f), 8f, point)
                drawCircle(color.copy(alpha = alpha), 2.5f, point)
            }
        }
    }
}

@Composable
private fun HistoryDashboard(value: DashboardSnapshot) {
    Card(Modifier.fillMaxSize(), shape = RoundedCornerShape(28.dp)) {
        Column(Modifier.fillMaxSize().padding(20.dp)) {
            Text(
                if (value.historyWindow == "calendar_day") "Power · today" else "Power history",
                style = MaterialTheme.typography.headlineMedium,
            )
            Text(
                "Midnight to midnight · loads are shown below zero",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            DashboardLineChart(
                value.history,
                Modifier.weight(1f).fillMaxWidth().padding(top = 16.dp),
                value.historyStartedAt,
                value.historyEndedAt,
            )
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                listOf("12 AM", "6 AM", "12 PM", "6 PM", "12 AM").forEach {
                    Text(
                        it,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(22.dp)) {
                value.history.forEach { Text("● ${it.label}", color = color(it.color), fontWeight = FontWeight.SemiBold) }
            }
        }
    }
}

@Composable
private fun DashboardLineChart(
    series: List<DashboardSeries>,
    modifier: Modifier,
    startedAt: java.time.Instant? = null,
    endedAt: java.time.Instant? = null,
) {
    val values = series.flatMap { it.points }.map { it.value }
    val low = min(0.0, values.minOrNull() ?: 0.0)
    val high = max(1.0, values.maxOrNull() ?: 1.0)
    Canvas(modifier) {
        repeat(5) { index ->
            val y = size.height * index / 4f
            drawLine(Color.White.copy(alpha = .08f), Offset(0f, y), Offset(size.width, y), 1f)
        }
        val zeroY = size.height * (1 - ((0.0 - low) / (high - low))).toFloat()
        drawLine(
            Color.White.copy(alpha = .2f),
            Offset(0f, zeroY),
            Offset(size.width, zeroY),
            1.5f,
        )
        series.forEach { item ->
            val durationMillis = if (startedAt != null && endedAt != null) {
                Duration.between(startedAt, endedAt).toMillis().coerceAtLeast(1)
            } else null
            visibleHistorySegments(item).forEach { segment ->
                if (segment.size < 2) return@forEach
                val rawCoordinates = segment.mapIndexed { index, point ->
                    val fraction = if (durationMillis != null && point.at != null) {
                        Duration.between(startedAt, point.at).toMillis()
                            .toDouble().div(durationMillis).coerceIn(0.0, 1.0)
                    } else {
                        index.toDouble() / (segment.size - 1).coerceAtLeast(1)
                    }
                    Offset(
                        size.width * fraction.toFloat(),
                        size.height * (1 - ((point.value - low) / (high - low))).toFloat(),
                    )
                }
                val coordinates = if (item.renderMode == "step") {
                    buildList {
                        add(rawCoordinates.first())
                        rawCoordinates.drop(1).forEach { point ->
                            add(Offset(point.x, last().y))
                            add(point)
                        }
                    }
                } else {
                    rawCoordinates
                }
                val path = Path()
                coordinates.forEachIndexed { index, point ->
                    if (index == 0) path.moveTo(point.x, point.y)
                    else path.lineTo(point.x, point.y)
                }
                val area = Path().apply {
                    moveTo(coordinates.first().x, zeroY)
                    coordinates.forEach { lineTo(it.x, it.y) }
                    lineTo(coordinates.last().x, zeroY)
                    close()
                }
                val seriesColor = color(item.color)
                val seriesTop = min(zeroY, coordinates.minOf { it.y })
                val seriesBottom = max(zeroY, coordinates.maxOf { it.y })
                drawPath(
                    area,
                    brush = Brush.verticalGradient(
                        colors = listOf(
                            seriesColor.copy(alpha = .04f),
                            seriesColor.copy(alpha = .28f),
                            seriesColor.copy(alpha = .04f),
                        ),
                        startY = seriesTop,
                        endY = max(seriesTop + 1f, seriesBottom),
                    ),
                )
                drawPath(path, seriesColor, style = Stroke(width = 5f, cap = StrokeCap.Round))
            }
        }
    }
}

internal fun visibleHistorySegments(series: DashboardSeries): List<List<DashboardPoint>> {
    val threshold = series.activityThresholdW ?: return listOf(series.points).filter { it.isNotEmpty() }
    val segments = mutableListOf<List<DashboardPoint>>()
    var active = mutableListOf<DashboardPoint>()
    fun finish() {
        if (active.isNotEmpty()) {
            segments += active
            active = mutableListOf()
        }
    }
    series.points.forEach { point ->
        if (abs(point.value) >= threshold) active += point else finish()
    }
    finish()
    return segments
}

@Composable
private fun DailyDashboard(
    value: DashboardSnapshot,
    actionInFlight: Boolean,
    model: PilotViewModel,
) {
    LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                DailyMetric("Solar generated", value.daily.generatedKWh, PilotAmber, Modifier.weight(1f), large = true)
                DailyMetric("Home used", value.daily.homeKWh, PilotMint, Modifier.weight(1f), large = true)
                DailyMetric("Grid exported", value.daily.exportedKWh, PilotCyan, Modifier.weight(1f), large = true)
            }
        }
        item {
            Card(shape = RoundedCornerShape(24.dp)) {
                Row(Modifier.fillMaxWidth().padding(20.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("JARVIS", color = PilotRed, fontWeight = FontWeight.Bold)
                        Text(value.vehicle.socPercent?.let { "${it.toInt()}%" } ?: "—", style = MaterialTheme.typography.displaySmall)
                        Text(if (value.vehicle.connected == true) if (value.vehicle.charging) "Charging · ${watts(value.vehicle.powerW)}" else "Plugged in" else "Not plugged in", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    value.controls.chargingModes.filter { it in setOf("Grid", "Solar") }.forEach { mode ->
                        if (value.controls.chargingMode == mode) Button(onClick = {}) { Text(mode) }
                        else OutlinedButton(
                            onClick = { model.dashboardAction("set_tesla_charging_mode", mode) },
                            enabled = !actionInFlight,
                        ) { Text(mode) }
                        Spacer(Modifier.width(8.dp))
                    }
                }
            }
        }
        item {
            Card(shape = RoundedCornerShape(24.dp)) {
                Column(Modifier.fillMaxWidth().padding(20.dp)) {
                    Text("AMBER PRICES", color = PilotCyan, fontWeight = FontWeight.Bold)
                    Row(Modifier.padding(vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(38.dp)) {
                        Price("Buy now", value.tariff.importCents)
                        Price("Feed-in now", value.tariff.feedInCents)
                    }
                    DashboardLineChart(
                        listOf(DashboardSeries("fit", "Feed-in forecast", "#61E6A8", value.tariff.forecast)),
                        Modifier.fillMaxWidth().height(110.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun ClimateDashboard(value: DashboardSnapshot) {
    LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Card(shape = RoundedCornerShape(26.dp)) {
                Row(Modifier.fillMaxWidth().padding(22.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(weatherGlyph(value.weather.condition), fontSize = MaterialTheme.typography.displayLarge.fontSize, color = PilotAmber)
                    Spacer(Modifier.width(20.dp))
                    Column {
                        Text(value.weather.temperatureC?.let { "${it.toInt()}°" } ?: "—", style = MaterialTheme.typography.displayLarge)
                        Text(value.weather.condition?.replaceFirstChar(Char::uppercase) ?: "Weather unavailable", style = MaterialTheme.typography.headlineSmall)
                        Text("${value.weather.humidityPercent?.toInt() ?: "—"}% humidity · ${value.weather.windSpeed?.toInt() ?: "—"} ${value.weather.windSpeedUnit.orEmpty()} wind", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
        item {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                value.temperatures.forEach { TemperatureCard(it) }
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                value.weather.forecast.take(5).forEach { ForecastCard(it, Modifier.weight(1f)) }
            }
        }
    }
}

@Composable private fun DailyMetric(label: String, value: Double?, tint: Color, modifier: Modifier, large: Boolean = false) {
    Card(modifier, colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), shape = RoundedCornerShape(20.dp)) {
        Column(Modifier.fillMaxWidth().padding(if (large) 20.dp else 13.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(value?.let { "%.1f kWh".format(it) } ?: "—", color = tint, style = if (large) MaterialTheme.typography.headlineLarge else MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable private fun FlowMetric(label: String, value: String, tint: Color, modifier: Modifier, detail: String? = null) {
    Card(
        modifier,
        colors = CardDefaults.cardColors(containerColor = Color(0xE8101722)),
        shape = RoundedCornerShape(15.dp),
    ) {
        Column(Modifier.padding(horizontal = 13.dp, vertical = 7.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(label.uppercase(), color = tint, style = MaterialTheme.typography.labelSmall)
            Text(value, fontWeight = FontWeight.Bold)
            detail?.let { Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.labelSmall) }
        }
    }
}

@Composable private fun Price(label: String, value: Double?) { Column { Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant); Text(value?.let { "%.2f¢/kWh".format(it) } ?: "—", style = MaterialTheme.typography.headlineMedium) } }
@Composable private fun TemperatureCard(item: DashboardTemperature) { Card(Modifier.width(150.dp), shape = RoundedCornerShape(18.dp)) { Column(Modifier.padding(15.dp)) { Text(item.label, color = MaterialTheme.colorScheme.onSurfaceVariant); Text(item.temperatureC?.let { "%.1f°".format(it) } ?: "—", style = MaterialTheme.typography.headlineMedium) } } }
@Composable private fun ForecastCard(item: DashboardForecast, modifier: Modifier) { Card(modifier, shape = RoundedCornerShape(18.dp)) { Column(Modifier.padding(12.dp), horizontalAlignment = Alignment.CenterHorizontally) { Text(item.at?.atZone(ZoneId.systemDefault())?.format(DateTimeFormatter.ofPattern("EEE")) ?: "—"); Text(weatherGlyph(item.condition), style = MaterialTheme.typography.headlineMedium, color = PilotAmber); Text("${item.highC?.toInt() ?: "—"}° / ${item.lowC?.toInt() ?: "—"}°", fontWeight = FontWeight.Bold); Text(item.rainPercent?.let { "${it.toInt()}% rain" } ?: item.condition.orEmpty(), style = MaterialTheme.typography.labelSmall, textAlign = TextAlign.Center) } } }

private fun watts(value: Double?): String = when { value == null -> "—"; abs(value) >= 1000 -> "%.1f kW".format(abs(value) / 1000); else -> "%.0f W".format(abs(value)) }
private fun color(hex: String): Color = runCatching { Color(android.graphics.Color.parseColor(hex)) }.getOrDefault(PilotCyan)
private fun weatherGlyph(condition: String?): String = when { condition?.contains("rain", true) == true -> "☂"; condition?.contains("cloud", true) == true -> "☁"; condition?.contains("storm", true) == true -> "ϟ"; condition?.contains("night", true) == true -> "☾"; else -> "☀" }
