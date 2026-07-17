package com.jarvis.pilottv

import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CoreAddressPolicyTest {
    @Test
    fun permitsPrivateLanAddresses() {
        assertTrue(CoreAddressPolicy.isPrivateHost("10.0.1.64"))
        assertTrue(CoreAddressPolicy.isPrivateHost("172.20.0.2"))
        assertTrue(CoreAddressPolicy.isPrivateHost("192.168.1.10"))
        assertTrue(CoreAddressPolicy.isPrivateHost("pilot-core.local"))
    }

    @Test
    fun rejectsPublicCleartextAddresses() {
        assertFalse(CoreAddressPolicy.isPrivateHost("8.8.8.8"))
        assertTrue(
            CoreConnection("http://8.8.8.8:8770", "secret")
                .validate()
                ?.contains("private local") == true,
        )
    }

    @Test
    fun allowsHttpsAndRequiresToken() {
        assertNull(CoreConnection("https://pilot.example", "secret").validate())
        assertTrue(
            CoreConnection("https://pilot.example", "")
                .validate()
                ?.contains("token") == true,
        )
    }
}
