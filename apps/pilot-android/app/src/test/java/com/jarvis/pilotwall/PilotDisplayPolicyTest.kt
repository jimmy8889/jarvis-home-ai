package com.jarvis.pilotwall

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PilotDisplayPolicyTest {
    @Test
    fun ambientTimeoutUsesConfiguredMinutesAndClampsUnsafeValues() {
        assertEquals(60_000L, ambientTimeoutMillis(1))
        assertEquals(5 * 60_000L, ambientTimeoutMillis(5))
        assertEquals(60 * 60_000L, ambientTimeoutMillis(99))
        assertEquals(60_000L, ambientTimeoutMillis(0))
    }

    @Test
    fun brightnessRestoresTheConfiguredLevelAfterIdleDimming() {
        assertEquals(.05f, displayBrightnessFraction(0), .0001f)
        assertEquals(.42f, resolvedWindowBrightness(42, dimmed = false), .0001f)
        assertEquals(.03f, resolvedWindowBrightness(42, dimmed = true), .0001f)
        assertEquals(1f, displayBrightnessFraction(150), .0001f)
    }

    @Test
    fun zeroAnimatorScaleDisablesContinuousMotion() {
        assertFalse(animationsEnabledForScale(0f))
        assertFalse(animationsEnabledForScale(Float.NaN))
        assertTrue(animationsEnabledForScale(.5f))
        assertTrue(animationsEnabledForScale(1f))
    }
}
