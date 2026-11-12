package com.jameshazell.pilot.ui.assistant.jarvis

import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import com.jameshazell.pilot.data.jarvis.JarvisConnection
import com.jameshazell.pilot.data.jarvis.JarvisHealth
import com.jameshazell.pilot.data.jarvis.JarvisMessage
import com.jameshazell.pilot.data.jarvis.JarvisPairing
import com.jameshazell.pilot.data.jarvis.JarvisPhase
import com.jameshazell.pilot.data.jarvis.JarvisTelemetry
import com.jameshazell.pilot.data.jarvis.JarvisTelemetryState
import com.jameshazell.pilot.data.jarvis.JarvisTurnState
import com.jameshazell.pilot.data.jarvis.JarvisVoiceMode
import com.jameshazell.pilot.ui.control.PreviewFrame

internal object JarvisFixtures {
    private val health = JarvisHealth(connected = true, speech = true, reasoning = true, recognition = true, model = "qwen3.5-4b", voice = "JARVIS · British", systemTools = true, profileReady = true)
    private val conversation = listOf(
        JarvisMessage("user", "Introduce yourself"),
        JarvisMessage("assistant", "Good evening, James. I am JARVIS, running entirely on your laptop. How may I help?"),
    )

    val connected = JarvisScreenState(
        connection = JarvisConnection.Connected(health),
        pairing = JarvisPairing(host = "100.64.0.10:18765"),
        telemetry = JarvisTelemetryState(JarvisTelemetry(12.0, 41.5, null, null, true), receivedAtMs = 1_000),
        conversation = conversation,
        ui = JarvisUiState(phoneVoiceReady = true, onDeviceRecognition = true),
        nowMs = 2_000,
    )
    val thinking = connected.copy(
        turn = JarvisTurnState(JarvisPhase.Working, pendingUser = "How much disk space is left?", pendingReply = "Checking the laptop now", inFlight = true),
    )
    val listening = connected.copy(turn = JarvisTurnState(JarvisPhase.Listening, pendingUser = "what's the"), ui = connected.ui.copy(continuous = true))
    val unpaired = JarvisScreenState()
    val offline = connected.copy(connection = JarvisConnection.Unreachable(3, 8), conversation = emptyList(), nowMs = 60_000)
}

private val NoActions = object : JarvisActions {}

@Composable
private fun JarvisPreview(widthDp: Int, state: JarvisScreenState, level: Float = 0f) {
    PreviewFrame(widthDp) { JarvisContent(state, level = { level }, animate = false, actions = NoActions, listen = { false }) }
}

@Preview(name = "JARVIS · connected · cover", widthDp = 360, heightDp = 720)
@Composable
private fun JarvisCoverPreview() = JarvisPreview(360, JarvisFixtures.connected)

@Preview(name = "JARVIS · working · inner", widthDp = 752, heightDp = 720)
@Composable
private fun JarvisInnerPreview() = JarvisPreview(752, JarvisFixtures.thinking, level = 0.4f)

@Preview(name = "JARVIS · listening · cover", widthDp = 360, heightDp = 720)
@Composable
private fun JarvisListeningPreview() = JarvisPreview(360, JarvisFixtures.listening, level = 0.7f)

@Preview(name = "JARVIS · not paired · cover", widthDp = 360, heightDp = 720)
@Composable
private fun JarvisUnpairedPreview() = JarvisPreview(360, JarvisFixtures.unpaired)

@Preview(name = "JARVIS · laptop offline · inner", widthDp = 752, heightDp = 720)
@Composable
private fun JarvisOfflinePreview() = JarvisPreview(752, JarvisFixtures.offline)

@Preview(name = "JARVIS · not paired · inner", widthDp = 752, heightDp = 720)
@Composable
private fun JarvisUnpairedInnerPreview() = JarvisPreview(752, JarvisFixtures.unpaired)
