package com.jameshazell.pilot.ui.energy

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.ui.adaptive.LocalPilotWindow
import com.jameshazell.pilot.ui.adaptive.PilotWindow
import com.jameshazell.pilot.ui.adaptive.WindowSizeClass
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotTheme

/* Previews with fixture data at the two Galaxy Fold widths: 360dp closed, 752dp open. */

@Composable
private fun EnergyPreview(widthDp: Float, pane: EnergyPane, saved: Boolean = false) {
    PilotTheme {
        CompositionLocalProvider(
            LocalPilotWindow provides PilotWindow(WindowSizeClass.fromWidthDp(widthDp), widthDp = widthDp, heightDp = 800f),
        ) {
            Box(Modifier.fillMaxSize().background(PilotColors.Background)) {
                EnergyContent(
                    EnergyUi(
                        bootstrap = EnergyFixtures.bootstrap(),
                        saved = saved,
                        pane = pane,
                        history = LoadState.Content(EnergyFixtures.history()),
                        daily = LoadState.Content(EnergyFixtures.daily()),
                    ),
                    EnergyCallbacks(),
                )
            }
        }
    }
}

@Preview(name = "Now · closed Fold", widthDp = 360, heightDp = 1500)
@Composable
private fun NowCompactPreview() = EnergyPreview(360f, EnergyPane.Now)

@Preview(name = "Now · open Fold", widthDp = 752, heightDp = 900)
@Composable
private fun NowOpenPreview() = EnergyPreview(752f, EnergyPane.Now)

@Preview(name = "Plan · closed Fold", widthDp = 360, heightDp = 1900)
@Composable
private fun PlanCompactPreview() = EnergyPreview(360f, EnergyPane.Plan)

@Preview(name = "Plan · open Fold", widthDp = 752, heightDp = 900)
@Composable
private fun PlanOpenPreview() = EnergyPreview(752f, EnergyPane.Plan)

@Preview(name = "Solar · closed Fold", widthDp = 360, heightDp = 1300)
@Composable
private fun SolarCompactPreview() = EnergyPreview(360f, EnergyPane.Solar)

@Preview(name = "Solar · open Fold", widthDp = 752, heightDp = 900)
@Composable
private fun SolarOpenPreview() = EnergyPreview(752f, EnergyPane.Solar)

@Preview(name = "UPS & rack · closed Fold", widthDp = 360, heightDp = 900)
@Composable
private fun UpsCompactPreview() = EnergyPreview(360f, EnergyPane.Ups)

@Preview(name = "UPS & rack · open Fold", widthDp = 752, heightDp = 900)
@Composable
private fun UpsOpenPreview() = EnergyPreview(752f, EnergyPane.Ups)

@Preview(name = "Controls · closed Fold", widthDp = 360, heightDp = 1400)
@Composable
private fun ControlsCompactPreview() = EnergyPreview(360f, EnergyPane.Controls)

@Preview(name = "Controls · open Fold, saved data", widthDp = 752, heightDp = 900)
@Composable
private fun ControlsOpenSavedPreview() = EnergyPreview(752f, EnergyPane.Controls, saved = true)
