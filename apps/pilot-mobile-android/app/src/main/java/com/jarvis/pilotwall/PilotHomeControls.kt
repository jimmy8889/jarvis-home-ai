package com.jarvis.pilotwall

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlin.math.roundToInt

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun CuratedHomeControls(state: PilotUiState, model: PilotViewModel) {
    val entities = state.home?.entities.orEmpty()
        .sortedWith(compareBy<HomeEntity> { it.presentation.priority }.thenBy { it.displayName })
    val unavailable = entities.count { it.unavailable }
    val stale = entities.count { it.stale }
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(26.dp),
    ) {
        Column(
            Modifier.fillMaxWidth().padding(22.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(
                        state.home?.roomName ?: state.selectedRoom?.name ?: "Room controls",
                        style = MaterialTheme.typography.headlineMedium,
                    )
                    Text(
                        when {
                            unavailable > 0 -> "$unavailable device${if (unavailable == 1) "" else "s"} unavailable"
                            stale > 0 -> "$stale reading${if (stale == 1) "" else "s"} waiting to refresh"
                            state.liveEventsConnected -> "Live updates from Pilot Core"
                            else -> "Secure, curated controls through Pilot Core"
                        },
                        color = when {
                            unavailable > 0 -> PilotRed
                            stale > 0 -> PilotAmber
                            else -> MaterialTheme.colorScheme.onSurfaceVariant
                        },
                    )
                }
                if (state.homeLoading) {
                    CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp)
                }
            }
            state.homeError?.let { error ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(error, color = PilotAmber, modifier = Modifier.weight(1f))
                    OutlinedButton(onClick = { model.refreshHome() }) { Text("Retry") }
                }
            }
            if (!state.homeLoading && state.homeError == null && entities.isEmpty()) {
                Text(
                    "Pilot Core has not exposed any useful controls for this room.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            entities.groupBy(HomeEntity::section).forEach { (section, items) ->
                Text(
                    section.uppercase(),
                    color = PilotCyan,
                    style = MaterialTheme.typography.labelLarge,
                )
                FlowRow(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                    maxItemsInEachRow = 3,
                ) {
                    items.forEach { entity ->
                        if (entity.controlKind in setOf(
                                HomeControlKind.Sensor,
                                HomeControlKind.Contact,
                            ) && entity.actions.isEmpty()
                        ) {
                            SensorTile(entity)
                        } else {
                            EntityControlTile(
                                entity = entity,
                                busy = state.activeHomeEntityId == entity.entityId,
                                action = model::homeAction,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SensorTile(entity: HomeEntity) {
    val alert = entity.unavailable || entity.stale ||
        (entity.controlKind == HomeControlKind.Contact && entity.isOn)
    Column(
        Modifier
            .widthIn(min = 178.dp, max = 260.dp)
            .background(
                if (alert) PilotAmber.copy(alpha = .10f)
                else MaterialTheme.colorScheme.onSurface.copy(alpha = .045f),
                RoundedCornerShape(18.dp),
            )
            .padding(15.dp)
            .semantics {
                contentDescription = "${entity.displayName}, ${entityStateLabel(entity)}"
            },
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(entityGlyph(entity), color = if (alert) PilotAmber else PilotCyan)
            Spacer(Modifier.width(9.dp))
            Text(
                entity.displayName,
                modifier = Modifier.weight(1f),
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Text(
            entityStateLabel(entity),
            style = MaterialTheme.typography.titleLarge,
            color = if (alert) PilotAmber else MaterialTheme.colorScheme.onSurface,
            maxLines = 1,
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun EntityControlTile(
    entity: HomeEntity,
    busy: Boolean,
    action: (HomeEntity, String, Double?) -> Unit,
) {
    val disabled = busy || entity.stale || entity.unavailable
    Column(
        Modifier
            .widthIn(min = 240.dp, max = 360.dp)
            .background(
                if (entity.isOn) PilotMint.copy(alpha = .09f)
                else MaterialTheme.colorScheme.onSurface.copy(alpha = .045f),
                RoundedCornerShape(18.dp),
            )
            .padding(15.dp)
            .semantics {
                contentDescription = "${entity.displayName}, ${entityStateLabel(entity)}"
            },
        verticalArrangement = Arrangement.spacedBy(9.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(34.dp).background(
                    if (entity.isOn) PilotMint.copy(alpha = .18f)
                    else MaterialTheme.colorScheme.surfaceVariant,
                    CircleShape,
                ),
                contentAlignment = Alignment.Center,
            ) { Text(entityGlyph(entity), color = if (entity.isOn) PilotMint else PilotCyan) }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    entity.displayName,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    if (entity.stale) "Stale" else entityStateLabel(entity),
                    color = if (entity.stale || entity.unavailable) PilotAmber
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                )
            }
            if (busy) {
                CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp)
            } else if ("turn_on" in entity.actions && "turn_off" in entity.actions) {
                Switch(
                    checked = entity.isOn,
                    onCheckedChange = { action(entity, if (it) "turn_on" else "turn_off", null) },
                    enabled = !disabled,
                )
            }
        }
        val ranged = when {
            "set_brightness" in entity.actions -> Triple(
                entity.brightnessPercent ?: 0f,
                "Brightness",
                "set_brightness",
            )
            "set_percentage" in entity.actions -> Triple(
                entity.percentage ?: 0f,
                "Speed",
                "set_percentage",
            )
            "set_position" in entity.actions -> Triple(
                entity.positionPercent ?: 0f,
                "Position",
                "set_position",
            )
            else -> null
        }
        ranged?.let { (initial, label, command) ->
            var preview by remember(entity.entityId, initial) { mutableFloatStateOf(initial) }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.weight(1f))
                Text("${preview.roundToInt()}%", fontWeight = FontWeight.SemiBold)
            }
            Slider(
                value = preview,
                onValueChange = { preview = it },
                onValueChangeFinished = { action(entity, command, preview.toDouble()) },
                valueRange = 0f..100f,
                enabled = !disabled,
            )
        }
        if ("set_temperature" in entity.actions) {
            val current = entity.targetTemperature ?: entity.numericValue ?: 22.0
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedButton(
                    onClick = { action(entity, "set_temperature", (current - .5).coerceAtLeast(10.0)) },
                    enabled = !disabled,
                ) { Text("−") }
                Text(
                    "%.1f°".format(current),
                    modifier = Modifier.weight(1f),
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.SemiBold,
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                )
                OutlinedButton(
                    onClick = { action(entity, "set_temperature", (current + .5).coerceAtMost(35.0)) },
                    enabled = !disabled,
                ) { Text("+") }
            }
        }
        FlowRow(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
            if ("activate" in entity.actions) {
                Button(onClick = { action(entity, "activate", null) }, enabled = !disabled) {
                    Text("Activate")
                }
            }
            if ("open" in entity.actions) {
                AssistChip(onClick = { action(entity, "open", null) }, label = { Text("Open") }, enabled = !disabled)
                AssistChip(onClick = { action(entity, "stop", null) }, label = { Text("Stop") }, enabled = !disabled)
                AssistChip(onClick = { action(entity, "close", null) }, label = { Text("Close") }, enabled = !disabled)
            }
            if ("lock" in entity.actions) {
                val next = if (entity.state == "locked") "unlock" else "lock"
                FilledTonalButton(onClick = { action(entity, next, null) }, enabled = !disabled) {
                    Text(next.replaceFirstChar(Char::uppercase))
                }
            }
            if ("arm_home" in entity.actions) {
                val next = if (entity.state == "disarmed") "arm_home" else "disarm"
                FilledTonalButton(onClick = { action(entity, next, null) }, enabled = !disabled) {
                    Text(next.replace('_', ' ').replaceFirstChar(Char::uppercase))
                }
            }
        }
    }
}

private fun entityGlyph(entity: HomeEntity): String = entity.presentation.icon ?: when (entity.controlKind) {
    HomeControlKind.Light -> "●"
    HomeControlKind.Climate -> "◉"
    HomeControlKind.Cover -> "▤"
    HomeControlKind.Fan -> "✣"
    HomeControlKind.Lock -> "◆"
    HomeControlKind.Scene -> "✦"
    HomeControlKind.Switch -> "◍"
    HomeControlKind.Contact -> "▯"
    HomeControlKind.Sensor -> "∿"
    HomeControlKind.Generic -> "•"
}

private fun entityStateLabel(entity: HomeEntity): String {
    if (entity.unavailable) return "Unavailable"
    if (entity.stale) return "Waiting to refresh"
    entity.numericValue?.let { value ->
        return if (entity.unit.isNullOrBlank()) "%.1f".format(value)
        else "%.1f %s".format(value, entity.unit)
    }
    return entity.state.replace('_', ' ').replaceFirstChar(Char::uppercase)
}
