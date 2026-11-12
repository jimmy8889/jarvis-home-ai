package com.jameshazell.pilot.data.pilot

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class PairingPayloadTest {
    @Test fun parsesTheDeepLinkWithGrant() {
        val payload = PairingPayload.parse("pilot://pair?core=http%3A%2F%2F10.0.1.64%3A8770&grant=one-time-secret")
        assertEquals(PairingPayload("http://10.0.1.64:8770/", "one-time-secret"), payload)
    }

    @Test fun acceptsTokenAsAnAliasForGrant() {
        val payload = PairingPayload.parse("pilot://pair?core=https%3A%2F%2Fpilot.example.net&token=abc%2B123")
        assertEquals(PairingPayload("https://pilot.example.net/", "abc+123"), payload)
    }

    @Test fun grantWinsWhenBothArePresentAndSchemeIsCaseInsensitive() {
        val payload = PairingPayload.parse("PILOT://pair?core=https%3A%2F%2Fpilot.example.net&token=old&grant=new")
        assertEquals("new", payload.grantToken)
    }

    @Test fun linkWithoutCoreUsesTheFormAddress() {
        val payload = PairingPayload.parse("pilot://pair?grant=g", fallbackCoreUrl = "https://pilot.example.net")
        assertEquals(PairingPayload("https://pilot.example.net/", "g"), payload)
    }

    @Test fun bareGrantNeedsTheFormAddress() {
        assertEquals(
            PairingPayload("https://pilot.example.net/", "bare-grant"),
            PairingPayload.parse("  bare-grant  ", "https://pilot.example.net/"),
        )
        assertThrows(IllegalArgumentException::class.java) { PairingPayload.parse("bare-grant") }
    }

    @Test fun rejectsOtherLinksIncompleteLinksAndPublicCleartext() {
        assertThrows(IllegalArgumentException::class.java) { PairingPayload.parse("") }
        assertThrows(IllegalArgumentException::class.java) { PairingPayload.parse("pilot://settings?grant=g&core=https%3A%2F%2Fa.example") }
        assertThrows(IllegalArgumentException::class.java) { PairingPayload.parse("pilot://pair?core=https%3A%2F%2Fa.example") }
        assertThrows(IllegalArgumentException::class.java) { PairingPayload.parse("pilot://pair?core=http%3A%2F%2Fexample.com&grant=g") }
    }
}
