package com.jameshazell.pilot.ui

import com.jameshazell.pilot.core.AppError
import com.jameshazell.pilot.core.ErrorKind
import com.jameshazell.pilot.ui.adaptive.PilotWindow
import com.jameshazell.pilot.ui.adaptive.WindowSizeClass
import com.jameshazell.pilot.ui.components.errorTitle
import com.jameshazell.pilot.ui.components.staleHeadline
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AdaptiveTest {
    @Test fun sizeClassBoundaries() {
        assertEquals(WindowSizeClass.Compact, WindowSizeClass.fromWidthDp(599.9f))
        assertEquals(WindowSizeClass.Medium, WindowSizeClass.fromWidthDp(600f))
        assertEquals(WindowSizeClass.Medium, WindowSizeClass.fromWidthDp(839.9f))
        assertEquals(WindowSizeClass.Expanded, WindowSizeClass.fromWidthDp(840f))
    }

    @Test fun closedFoldIsOnePaneAndOpenFoldIsTwo() {
        assertFalse(PilotWindow(WindowSizeClass.fromWidthDp(360f)).isTwoPane)
        assertTrue(PilotWindow(WindowSizeClass.fromWidthDp(752f)).isTwoPane)
    }

    @Test fun navigationHasFiveDestinationsInOrder() {
        assertEquals(listOf("Home", "Energy", "Control", "Pilot", "More"), Destination.all.map { it.label })
        assertEquals(5, Destination.all.map { it.id }.toSet().size)
        assertEquals(Destination.Home, Destination.byId("unknown"))
        assertEquals(Destination.Energy, Destination.byId("energy"))
    }

    @Test fun staleBannerWording() {
        val now = Instant.parse("2026-11-12T02:00:00Z")
        assertEquals("Showing saved data", staleHeadline(null, now))
        assertEquals("Showing data saved moments ago", staleHeadline(now.minusSeconds(20), now))
        assertEquals("Showing data saved 5 minutes ago", staleHeadline(now.minusSeconds(300), now))
        assertEquals("Showing data saved 3 hours ago", staleHeadline(now.minusSeconds(3 * 3600), now))
        assertEquals("Pairing needed", errorTitle(AppError(ErrorKind.Unauthorized, "x")))
    }
}
