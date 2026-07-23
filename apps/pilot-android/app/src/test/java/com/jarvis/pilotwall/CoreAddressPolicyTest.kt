package com.jarvis.pilotwall

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class CoreAddressPolicyTest {
    @Test
    fun acceptsPrivateHttpAndNormalizesTrailingSlash() {
        assertEquals(
            "http://10.0.1.64:8770/",
            CoreAddressPolicy.normalize("http://10.0.1.64:8770"),
        )
        assertTrue(CoreAddressPolicy.isPrivateOrLoopback("192.168.1.10"))
        assertTrue(CoreAddressPolicy.isPrivateOrLoopback("172.20.4.8"))
    }

    @Test
    fun rejectsPublicCleartextAndCredentialBearingUrls() {
        assertThrows(IllegalArgumentException::class.java) {
            CoreAddressPolicy.normalize("http://example.com")
        }
        assertThrows(IllegalArgumentException::class.java) {
            CoreAddressPolicy.normalize("https://token@example.com")
        }
        assertFalse(CoreAddressPolicy.isPrivateOrLoopback("8.8.8.8"))
    }

    @Test
    fun acceptsPublicHttpsWithoutPaths() {
        assertEquals(
            "https://pilot.example.com/",
            CoreAddressPolicy.normalize("https://pilot.example.com/"),
        )
        assertThrows(IllegalArgumentException::class.java) {
            CoreAddressPolicy.normalize("https://pilot.example.com/admin")
        }
    }
}
