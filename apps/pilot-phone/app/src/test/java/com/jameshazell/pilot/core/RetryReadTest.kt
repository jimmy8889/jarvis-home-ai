package com.jameshazell.pilot.core

import java.io.IOException
import javax.net.ssl.SSLHandshakeException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Ported from 1.x PilotTransportTest. */
class RetryReadTest {
    @Test fun droppedReadRecoversOnce() = runBlocking {
        var calls = 0
        val value = retryRead("GET", {}) { if (++calls == 1) throw IOException("dropped socket"); "fresh" }
        assertEquals("fresh", value)
        assertEquals(2, calls)
    }

    @Test fun unavailableReadIsBounded() = runBlocking {
        var calls = 0
        runCatching { retryRead("GET", {}) { calls++; throw IOException() } }
        assertEquals(2, calls)
    }

    @Test fun commandsAreNeverReplayed() = runBlocking {
        for (method in listOf("POST", "PATCH", "PUT", "DELETE")) {
            var calls = 0
            runCatching { retryRead(method, {}) { calls++; throw IOException() } }
            assertEquals(method, 1, calls)
        }
    }

    @Test fun permissionAndCertificateFailuresAreNotRetried() = runBlocking {
        for (error in listOf(HttpFailure(401, "denied"), HttpFailure(403, "denied"), SSLHandshakeException("certificate"))) {
            var calls = 0
            runCatching { retryRead("GET", {}) { calls++; throw error } }
            assertEquals(1, calls)
        }
    }

    @Test fun temporaryGatewayFailureRecovers() = runBlocking {
        var calls = 0
        retryRead("GET", {}) { if (++calls == 1) throw HttpFailure(503, "temporary"); "fresh" }
        assertEquals(2, calls)
    }

    @Test fun cancellationIsPropagated() = runBlocking {
        var calls = 0
        val failure = runCatching { retryRead("GET", {}) { calls++; throw CancellationException() } }.exceptionOrNull()
        assertTrue(failure is CancellationException)
        assertEquals(1, calls)
    }
}
