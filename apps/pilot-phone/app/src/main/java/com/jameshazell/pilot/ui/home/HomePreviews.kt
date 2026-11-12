package com.jameshazell.pilot.ui.home

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import com.jameshazell.pilot.ui.adaptive.LocalPilotWindow
import com.jameshazell.pilot.ui.adaptive.PilotWindow
import com.jameshazell.pilot.ui.adaptive.WindowSizeClass
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotTheme
import java.time.LocalDateTime

/** Wraps a preview in the app theme and the window class for [widthDp]. */
@Composable
internal fun PreviewFrame(widthDp: Int, content: @Composable () -> Unit) {
    PilotTheme {
        CompositionLocalProvider(
            LocalPilotWindow provides PilotWindow(WindowSizeClass.fromWidthDp(widthDp.toFloat()), widthDp = widthDp.toFloat()),
        ) {
            Box(Modifier.fillMaxSize().background(PilotColors.Background)) { content() }
        }
    }
}

private val PreviewTime: LocalDateTime = LocalDateTime.of(2026, 11, 12, 18, 30)

@Preview(name = "Home · closed Fold", widthDp = 360, heightDp = 780)
@Composable
private fun HomeCompactPreview() = PreviewFrame(360) {
    HomeContent(HomeFixtures.state(), HomeFixtures.noActions, PreviewTime)
}

@Preview(name = "Room · closed Fold", widthDp = 360, heightDp = 1400)
@Composable
private fun RoomCompactPreview() = PreviewFrame(360) {
    HomeContent(HomeFixtures.state(openRoomId = "living"), HomeFixtures.noActions, PreviewTime)
}

@Preview(name = "Garage, read-only · closed Fold", widthDp = 360, heightDp = 780)
@Composable
private fun GarageReadOnlyPreview() = PreviewFrame(360) {
    HomeContent(
        HomeFixtures.state(openRoomId = "garage", online = false, error = "Pilot Core took too long to answer."),
        HomeFixtures.noActions,
        PreviewTime,
    )
}

@Preview(name = "Home · open Fold", widthDp = 752, heightDp = 840)
@Composable
private fun HomeMediumPreview() = PreviewFrame(752) {
    HomeContent(HomeFixtures.state(), HomeFixtures.noActions, PreviewTime)
}

@Preview(name = "Home + room · open Fold", widthDp = 752, heightDp = 1400)
@Composable
private fun RoomMediumPreview() = PreviewFrame(752) {
    HomeContent(HomeFixtures.state(openRoomId = "living"), HomeFixtures.noActions, PreviewTime)
}
