@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package com.jarvis.pilotwall

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

private enum class DashboardPage(val title: String) { Flow("Flow"), History("History"), Daily("Daily"), Climate("Climate") }

@Composable
fun PilotEnergyDashboard(state: PilotUiState, model: PilotViewModel) {
    var page by remember { mutableStateOf(DashboardPage.Flow) }
    val dashboard = state.snapshot?.dashboard
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
                DashboardPage.Flow -> FlowDashboard(dashboard)
                DashboardPage.History -> HistoryDashboard(dashboard)
                DashboardPage.Daily -> DailyDashboard(dashboard, state.actionInFlight, model)
                DashboardPage.Climate -> ClimateDashboard(dashboard)
            }
        }
    }
}

@Composable
private fun FlowDashboard(value: DashboardSnapshot) {
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
            Box(Modifier.fillMaxSize()) {
                Image(
                    painter = painterResource(
                        if (value.vehicle.connected == true) R.drawable.pilot_house_energy
                        else R.drawable.pilot_house_no_car,
                    ),
                    contentDescription = "James House energy model",
                    modifier = Modifier.fillMaxSize().padding(horizontal = 70.dp),
                    contentScale = ContentScale.Fit,
                )
                EnergyFlowCanvas(value.power, value.vehicle, Modifier.fillMaxSize())
                FlowMetric("PV", watts(value.power.solarW), PilotAmber, Modifier.align(Alignment.TopCenter).padding(top = 6.dp))
                FlowMetric("Grid", watts(value.power.gridW), PilotCyan, Modifier.align(Alignment.TopEnd).padding(12.dp))
                FlowMetric("Jarvis", if (value.vehicle.connected == true) watts(value.vehicle.powerW) else "Away", PilotRed, Modifier.align(Alignment.BottomStart).padding(12.dp))
                FlowMetric("Home", watts(value.power.homeLoadW), PilotMint, Modifier.align(Alignment.BottomCenter).padding(8.dp))
                Column(Modifier.align(Alignment.BottomEnd).padding(10.dp), horizontalAlignment = Alignment.End) {
                    FlowMetric("Server rack", watts(value.power.serverRackW), Color(0xFFB49BFF), Modifier)
                    Spacer(Modifier.height(6.dp))
                    FlowMetric("Battery ${value.power.batterySocPercent?.let { "${it.toInt()}%" } ?: ""}", watts(value.power.batteryW), PilotMint, Modifier)
                }
            }
        }
    }
}

@Composable
private fun EnergyFlowCanvas(power: DashboardPower, vehicle: DashboardVehicle, modifier: Modifier) {
    val maximum = maxOf(
        abs(power.solarW ?: 0.0), abs(power.gridW ?: 0.0), abs(power.batteryW ?: 0.0),
        abs(vehicle.powerW ?: 0.0), abs(power.serverRackW ?: 0.0), 1.0,
    )
    val duration = (2200 - min(1500.0, maximum / 5)).toInt().coerceAtLeast(650)
    val phase by rememberInfiniteTransition(label = "power-flow").animateFloat(
        initialValue = 0f, targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(duration, easing = LinearEasing)), label = "phase",
    )
    Canvas(modifier) {
        fun flow(from: Offset, to: Offset, watts: Double?, color: Color, active: Boolean, reverse: Boolean = false) {
            val magnitude = abs(watts ?: 0.0)
            drawLine(Color.White.copy(alpha = .08f), from, to, strokeWidth = 6f, cap = StrokeCap.Round)
            if (!active) return
            val intensity = (.35f + min(1.0, magnitude / 7000).toFloat() * .65f)
            val start = if (reverse) to else from
            val end = if (reverse) from else to
            drawLine(color.copy(alpha = intensity * .46f), start, end, strokeWidth = 4f + intensity * 4f, cap = StrokeCap.Round)
            val point = Offset(start.x + (end.x - start.x) * phase, start.y + (end.y - start.y) * phase)
            drawCircle(color, 5f + intensity * 3f, point)
        }
        val centre = Offset(size.width * .51f, size.height * .55f)
        flow(Offset(size.width * .5f, size.height * .07f), centre, power.solarW, PilotAmber, (power.solarW ?: 0.0) >= 25)
        flow(Offset(size.width * .92f, size.height * .19f), centre, power.gridW, PilotCyan, power.gridFlowActive, reverse = power.gridDirection == "exporting")
        flow(Offset(size.width * .88f, size.height * .88f), centre, power.batteryW, PilotMint, abs(power.batteryW ?: 0.0) >= 25, reverse = power.batteryDirection == "charging")
        flow(centre, Offset(size.width * .13f, size.height * .86f), vehicle.powerW, PilotRed, vehicle.connected == true && (vehicle.powerW ?: 0.0) >= 100)
        flow(centre, Offset(size.width * .91f, size.height * .57f), power.serverRackW, Color(0xFFB49BFF), (power.serverRackW ?: 0.0) >= 25)
    }
}

@Composable
private fun HistoryDashboard(value: DashboardSnapshot) {
    Card(Modifier.fillMaxSize(), shape = RoundedCornerShape(28.dp)) {
        Column(Modifier.fillMaxSize().padding(20.dp)) {
            Text("Power · last 24 hours", style = MaterialTheme.typography.headlineMedium)
            Text("House consumption, battery and solar on one scale", color = MaterialTheme.colorScheme.onSurfaceVariant)
            DashboardLineChart(value.history, Modifier.weight(1f).fillMaxWidth().padding(top = 16.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(22.dp)) {
                value.history.forEach { Text("● ${it.label}", color = color(it.color), fontWeight = FontWeight.SemiBold) }
            }
        }
    }
}

@Composable
private fun DashboardLineChart(series: List<DashboardSeries>, modifier: Modifier) {
    val values = series.flatMap { it.points }.map { it.value }
    val low = min(0.0, values.minOrNull() ?: 0.0)
    val high = max(1.0, values.maxOrNull() ?: 1.0)
    Canvas(modifier) {
        repeat(5) { index ->
            val y = size.height * index / 4f
            drawLine(Color.White.copy(alpha = .08f), Offset(0f, y), Offset(size.width, y), 1f)
        }
        series.forEach { item ->
            if (item.points.size < 2) return@forEach
            val path = Path()
            item.points.forEachIndexed { index, point ->
                val x = size.width * index / (item.points.size - 1).toFloat()
                val y = size.height * (1 - ((point.value - low) / (high - low))).toFloat()
                if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
            }
            drawPath(path, color(item.color), style = Stroke(width = 5f, cap = StrokeCap.Round))
        }
    }
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

@Composable private fun FlowMetric(label: String, value: String, tint: Color, modifier: Modifier) {
    Card(modifier, colors = CardDefaults.cardColors(containerColor = Color(0xE8101722)), shape = RoundedCornerShape(15.dp)) {
        Column(Modifier.padding(horizontal = 13.dp, vertical = 8.dp)) {
            Text(label.uppercase(), color = tint, style = MaterialTheme.typography.labelSmall)
            Text(value, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable private fun Price(label: String, value: Double?) { Column { Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant); Text(value?.let { "%.2f¢/kWh".format(it) } ?: "—", style = MaterialTheme.typography.headlineMedium) } }
@Composable private fun TemperatureCard(item: DashboardTemperature) { Card(Modifier.width(150.dp), shape = RoundedCornerShape(18.dp)) { Column(Modifier.padding(15.dp)) { Text(item.label, color = MaterialTheme.colorScheme.onSurfaceVariant); Text(item.temperatureC?.let { "%.1f°".format(it) } ?: "—", style = MaterialTheme.typography.headlineMedium) } } }
@Composable private fun ForecastCard(item: DashboardForecast, modifier: Modifier) { Card(modifier, shape = RoundedCornerShape(18.dp)) { Column(Modifier.padding(12.dp), horizontalAlignment = Alignment.CenterHorizontally) { Text(item.at?.atZone(ZoneId.systemDefault())?.format(DateTimeFormatter.ofPattern("EEE")) ?: "—"); Text(weatherGlyph(item.condition), style = MaterialTheme.typography.headlineMedium, color = PilotAmber); Text("${item.highC?.toInt() ?: "—"}° / ${item.lowC?.toInt() ?: "—"}°", fontWeight = FontWeight.Bold); Text(item.rainPercent?.let { "${it.toInt()}% rain" } ?: item.condition.orEmpty(), style = MaterialTheme.typography.labelSmall, textAlign = TextAlign.Center) } } }

private fun watts(value: Double?): String = when { value == null -> "—"; abs(value) >= 1000 -> "%.1f kW".format(abs(value) / 1000); else -> "%.0f W".format(abs(value)) }
private fun color(hex: String): Color = runCatching { Color(android.graphics.Color.parseColor(hex)) }.getOrDefault(PilotCyan)
private fun weatherGlyph(condition: String?): String = when { condition?.contains("rain", true) == true -> "☂"; condition?.contains("cloud", true) == true -> "☁"; condition?.contains("storm", true) == true -> "ϟ"; condition?.contains("night", true) == true -> "☾"; else -> "☀" }
