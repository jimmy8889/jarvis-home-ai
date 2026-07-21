package com.jarvis.pilotwall

import android.os.SystemClock
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

@Composable
fun PilotIdleGuard(
    state: PilotUiState,
    content: @Composable () -> Unit,
) {
    var lastInteraction by remember { mutableLongStateOf(SystemClock.elapsedRealtime()) }
    val ambient by produceState(false, state.config.ambientAfterMinutes, state.assistantPhase) {
        while (true) {
            val elapsed = SystemClock.elapsedRealtime() - lastInteraction
            value = state.assistantPhase == AssistantPhase.Idle &&
                elapsed >= state.config.ambientAfterMinutes * 60_000L
            delay(5_000)
        }
    }
    Box(
        Modifier
            .fillMaxSize()
            .pointerInput(Unit) {
                awaitPointerEventScope {
                    while (true) {
                        awaitPointerEvent(PointerEventPass.Initial)
                        lastInteraction = SystemClock.elapsedRealtime()
                    }
                }
            },
    ) {
        if (ambient) PilotAmbientSurface(state) else content()
    }
}

@Composable
private fun PilotAmbientSurface(state: PilotUiState) {
    val now by produceState(LocalDateTime.now()) {
        while (true) {
            value = LocalDateTime.now()
            delay(1_000)
        }
    }
    val playing = state.snapshot?.media?.players?.firstOrNull {
        it.effective.playbackState == "playing"
    }
    val energy = state.snapshot?.surface?.energy
    Box(
        Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .padding(34.dp)
            .semantics {
                contentDescription = "Ambient display. ${now.format(DateTimeFormatter.ofPattern("h:mm a"))}. Touch to open Pilot."
            },
    ) {
        Column(Modifier.align(Alignment.TopStart)) {
            Text(
                now.format(DateTimeFormatter.ofPattern("h:mm")),
                style = MaterialTheme.typography.displayLarge,
            )
            Text(
                now.format(DateTimeFormatter.ofPattern("EEEE, d MMMM")),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Row(
            Modifier.align(Alignment.TopEnd),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier.size(8.dp).background(
                    if (state.connection == ConnectionState.Online) PilotMint else PilotAmber,
                    CircleShape,
                ),
            )
            Spacer(Modifier.width(8.dp))
            Text(
                if (state.connection == ConnectionState.Online) "Pilot is live" else "Last known state",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        energy?.let {
            Row(
                Modifier.align(Alignment.Center),
                horizontalArrangement = Arrangement.spacedBy(34.dp),
            ) {
                AmbientMetric("Solar", it.solar.display(), PilotAmber)
                AmbientMetric("Home", it.homeLoad.display(), PilotMint)
                AmbientMetric("Battery", it.batterySoc.display(), PilotCyan)
                AmbientMetric(
                    if (it.grid.direction == "exporting") "Export" else "Grid",
                    it.grid.display(),
                    PilotCyan,
                )
            }
        }
        Surface(
            modifier = Modifier.align(Alignment.BottomStart).fillMaxWidth(.62f),
            color = MaterialTheme.colorScheme.surface.copy(alpha = .75f),
            shape = CircleShape,
        ) {
            Row(Modifier.padding(horizontal = 20.dp, vertical = 13.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("♫", color = PilotMint)
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        playing?.effective?.media?.title ?: "The house is quiet",
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        playing?.effective?.media?.artist ?: "Touch anywhere to open Pilot",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

@Composable
private fun AmbientMetric(label: String, value: String, color: androidx.compose.ui.graphics.Color) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value, style = MaterialTheme.typography.headlineLarge, color = color)
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
