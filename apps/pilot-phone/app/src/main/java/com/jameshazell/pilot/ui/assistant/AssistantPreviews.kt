package com.jameshazell.pilot.ui.assistant

import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import com.jameshazell.pilot.data.pilot.AssistantCard
import com.jameshazell.pilot.data.pilot.AssistantSource
import com.jameshazell.pilot.ui.control.PreviewFrame

internal object AssistantFixtures {
    val messages = listOf(
        AssistantMessage(1, fromUser = true, text = "Is the garage door shut?", spoken = true),
        AssistantMessage(
            2, fromUser = false, text = "Yes. The garage door closed at 6:42 pm and the car is plugged in.",
            cards = listOf(AssistantCard("device", "Garage door", "Closed · 6:42 pm"), AssistantCard("vehicle", "Car", "Charging · 64%")),
            sources = listOf(AssistantSource("Home Assistant", null)),
        ),
        AssistantMessage(3, fromUser = true, text = "How much solar did we make today?"),
    )

    fun state(phase: AssistantPhase, error: String? = null) = AssistantUiState(messages = messages, phase = phase, error = error)
}

private val NoActions = object : AssistantActions {}

@Composable
private fun AssistantPreview(widthDp: Int, state: AssistantUiState, level: Float = 0f) {
    PreviewFrame(widthDp) {
        AssistantContent(state, level, live = true, roomName = "Lounge", animate = false, actions = NoActions, startListening = { false })
    }
}

@Preview(name = "Pilot · thinking · closed", widthDp = 360, heightDp = 800)
@Composable
private fun AssistantClosedPreview() = AssistantPreview(360, AssistantFixtures.state(AssistantPhase.Thinking))

@Preview(name = "Pilot · listening · open", widthDp = 752, heightDp = 800)
@Composable
private fun AssistantOpenPreview() = AssistantPreview(752, AssistantFixtures.state(AssistantPhase.Listening), level = 0.6f)

@Preview(name = "Pilot · error · closed", widthDp = 360, heightDp = 800)
@Composable
private fun AssistantErrorPreview() = AssistantPreview(360, AssistantFixtures.state(AssistantPhase.Idle, AssistantMessages.TOO_SHORT))

@Preview(name = "Pilot · empty · open", widthDp = 752, heightDp = 800)
@Composable
private fun AssistantEmptyPreview() = AssistantPreview(752, AssistantUiState())
