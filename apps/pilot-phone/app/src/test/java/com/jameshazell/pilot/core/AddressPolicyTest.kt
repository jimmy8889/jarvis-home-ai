package com.jameshazell.pilot.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class AddressPolicyTest {
    @Test
    fun acceptsPrivateHttpAndNormalizesTrailingSlash() {
        assertEquals(
            "http://10.0.1.64:8770/",
            AddressPolicy.normalize("http://10.0.1.64:8770"),
        )
        assertTrue(AddressPolicy.isPrivateOrLoopback("192.168.1.10"))
        assertTrue(AddressPolicy.isPrivateOrLoopback("172.20.4.8"))
    }

    @Test
    fun rejectsPublicCleartextAndCredentialBearingUrls() {
        assertThrows(IllegalArgumentException::class.java) {
            AddressPolicy.normalize("http://example.com")
        }
        assertThrows(IllegalArgumentException::class.java) {
            AddressPolicy.normalize("https://token@example.com")
        }
        assertFalse(AddressPolicy.isPrivateOrLoopback("8.8.8.8"))
    }

    @Test
    fun acceptsPublicHttpsWithoutPaths() {
        assertEquals(
            "https://pilot.example.com/",
            AddressPolicy.normalize("https://pilot.example.com/"),
        )
        assertThrows(IllegalArgumentException::class.java) {
            AddressPolicy.normalize("https://pilot.example.com/admin")
        }
    }
}
