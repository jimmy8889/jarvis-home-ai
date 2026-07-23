package com.jarvis.pilotwall

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat

@Composable
fun PilotAssistantPanel(state: PilotUiState, model: PilotViewModel) {
    var input by remember { mutableStateOf("") }
    val context = LocalContext.current
    val permission = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted -> if (granted) model.startVoiceCapture() }
    Column(Modifier.fillMaxSize().padding(24.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Pilot", style = MaterialTheme.typography.headlineLarge)
                Text(
                    "Understands the context of ${state.selectedRoom?.name ?: "this display"}",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            VoiceActionButton(state.assistantPhase) {
                when (state.assistantPhase) {
                    AssistantPhase.Idle, AssistantPhase.Failed -> {
                        if (ContextCompat.checkSelfPermission(
                                context,
                                Manifest.permission.RECORD_AUDIO,
                            ) == PackageManager.PERMISSION_GRANTED
                        ) model.startVoiceCapture()
                        else permission.launch(Manifest.permission.RECORD_AUDIO)
                    }
                    AssistantPhase.Listening -> model.stopVoiceCapture()
                    AssistantPhase.Processing, AssistantPhase.Speaking -> model.cancelAssistant()
                }
            }
        }
        Spacer(Modifier.height(14.dp))
        LazyColumn(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            items(state.chat, key = { it.id }) { message ->
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = if (message.role == ChatRole.User) Arrangement.End else Arrangement.Start,
                ) {
                    Surface(
                        color = if (message.role == ChatRole.User) PilotMint.copy(alpha = .16f)
                        else MaterialTheme.colorScheme.surface,
                        shape = RoundedCornerShape(20.dp),
                        modifier = Modifier.fillMaxWidth(.74f),
                    ) { Text(message.text, Modifier.padding(16.dp)) }
                }
            }
            if (state.assistantCards.isNotEmpty()) {
                item { Text("Results", color = PilotCyan, fontWeight = FontWeight.Bold) }
                items(state.assistantCards) { card -> AssistantResultCard(card) }
            }
            if (state.assistantSources.isNotEmpty()) {
                item {
                    Text(
                        "Sources: ${state.assistantSources.joinToString { it.label }}",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            if (state.assistantPhase == AssistantPhase.Processing) {
                item {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                        Spacer(Modifier.width(10.dp))
                        Text("Pilot is reasoning…", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
        Spacer(Modifier.height(12.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = input,
                onValueChange = { input = it },
                label = { Text("Ask about your home") },
                modifier = Modifier.weight(1f),
                maxLines = 3,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = {
                    model.ask(input)
                    input = ""
                }),
            )
            Spacer(Modifier.width(10.dp))
            Button(
                onClick = {
                    model.ask(input)
                    input = ""
                },
                enabled = input.isNotBlank() && !state.assistantBusy,
            ) { Text("Send") }
        }
    }
}

@Composable
fun PilotAssistantOverlay(state: PilotUiState, model: PilotViewModel) {
    AnimatedVisibility(
        visible = state.assistantPhase in setOf(
            AssistantPhase.Listening,
            AssistantPhase.Processing,
            AssistantPhase.Speaking,
        ),
    ) {
        Box(
            Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background.copy(alpha = .97f))
                .semantics {
                    contentDescription = when (state.assistantPhase) {
                        AssistantPhase.Listening -> "Pilot is listening"
                        AssistantPhase.Processing -> "Pilot is reasoning"
                        AssistantPhase.Speaking -> "Pilot is speaking"
                        else -> "Pilot assistant"
                    }
                },
            contentAlignment = Alignment.Center,
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                PilotVoiceOrb(state.assistantPhase, Modifier.size(210.dp))
                Spacer(Modifier.height(24.dp))
                Text(
                    when (state.assistantPhase) {
                        AssistantPhase.Listening -> "I'm listening"
                        AssistantPhase.Processing -> "Thinking locally"
                        AssistantPhase.Speaking -> "Pilot is speaking"
                        else -> "Pilot"
                    },
                    style = MaterialTheme.typography.headlineLarge,
                )
                Text(
                    when (state.assistantPhase) {
                        AssistantPhase.Listening -> "Tap Done when you've finished"
                        AssistantPhase.Processing -> "Understanding your home and intent"
                        AssistantPhase.Speaking -> "Tap Stop to interrupt"
                        else -> ""
                    },
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(24.dp))
                if (state.assistantPhase == AssistantPhase.Listening) {
                    Button(onClick = model::stopVoiceCapture) { Text("Done") }
                } else {
                    OutlinedButton(onClick = model::cancelAssistant) { Text("Stop") }
                }
            }
        }
    }
}

@Composable
private fun VoiceActionButton(phase: AssistantPhase, action: () -> Unit) {
    Button(
        onClick = action,
        modifier = Modifier.height(54.dp),
        shape = CircleShape,
    ) {
        Text(
            when (phase) {
                AssistantPhase.Idle, AssistantPhase.Failed -> "✦  Talk to Pilot"
                AssistantPhase.Listening -> "✓  Done"
                AssistantPhase.Processing -> "Cancel"
                AssistantPhase.Speaking -> "Stop"
            },
        )
    }
}

@Composable
private fun PilotVoiceOrb(phase: AssistantPhase, modifier: Modifier = Modifier) {
    val animationsEnabled = rememberSystemAnimationsEnabled()
    val pulse = if (animationsEnabled) {
        val transition = rememberInfiniteTransition(label = "pilot-voice-orb")
        val animatedPulse by transition.animateFloat(
            initialValue = .82f,
            targetValue = 1f,
            animationSpec = infiniteRepeatable(
                tween(if (phase == AssistantPhase.Listening) 650 else 1_100, easing = FastOutSlowInEasing),
                RepeatMode.Reverse,
            ),
            label = "pulse",
        )
        animatedPulse
    } else {
        .92f
    }
    Canvas(modifier) {
        val center = Offset(size.width / 2, size.height / 2)
        val radius = size.minDimension * .35f * pulse
        drawCircle(
            brush = Brush.radialGradient(
                listOf(PilotMint, PilotCyan.copy(alpha = .75f), Color.Transparent),
                center = center,
                radius = radius * 1.55f,
            ),
            radius = radius * 1.55f,
            center = center,
        )
        drawCircle(PilotMint.copy(alpha = .2f), radius, center)
        repeat(5) { index ->
            val x = center.x + (index - 2) * radius * .25f
            val height = radius * (.32f + ((index + pulse) % 3) * .12f)
            drawRoundRect(
                color = Color.White.copy(alpha = .9f),
                topLeft = Offset(x - 4f, center.y - height / 2),
                size = androidx.compose.ui.geometry.Size(8f, height),
                cornerRadius = androidx.compose.ui.geometry.CornerRadius(8f, 8f),
            )
        }
    }
}

@Composable
private fun AssistantResultCard(card: AssistantCard) {
    Card(
        Modifier.fillMaxWidth(.78f),
        colors = CardDefaults.cardColors(containerColor = PilotCyan.copy(alpha = .09f)),
        shape = RoundedCornerShape(18.dp),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(card.title, fontWeight = FontWeight.SemiBold)
            card.detail?.let { Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
    }
}
