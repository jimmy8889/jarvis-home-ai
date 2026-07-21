package com.jarvis.pilotwall

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.unit.dp
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Stable rendering entry point for emulator screenshots. CI can persist the
 * captured bitmap as a golden once the target 1024×600 emulator is available.
 */
class PilotWallScreenshotScaffoldTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun designSpecimenRendersForGoldenCapture() {
        compose.setContent {
            PilotTheme(night = false) {
                Box(Modifier.fillMaxSize().padding(24.dp)) {
                    PilotDesignSpecimen()
                }
            }
        }
        val image = compose.onRoot().captureToImage()
        assertTrue(image.width > 0)
        assertTrue(image.height > 0)
    }
}
