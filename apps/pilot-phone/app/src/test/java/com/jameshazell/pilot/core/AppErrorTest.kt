package com.jameshazell.pilot.core

import java.io.IOException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLHandshakeException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AppErrorTest {
    private val samples: List<Throwable> = listOf(
        HttpFailure(401), HttpFailure(403), HttpFailure(404), HttpFailure(409), HttpFailure(412),
        HttpFailure(422, "Brightness must be 0-100"), HttpFailure(500), HttpFailure(503), HttpFailure(418),
        IOException("java.net.SocketException: Connection reset"), SocketTimeoutException("timeout"),
        UnknownHostException("pilot.example"), SSLHandshakeException("Trust anchor for certification path not found."),
        RuntimeException("org.json.JSONException: Value <html>"),
    )

    @Test fun messagesAreForPeopleAndNeverSayTablet() {
        for (service in Service.entries) for (sample in samples) {
            val message = sample.toAppError(service).message
            assertTrue(message, message.isNotBlank() && message.first().isUpperCase())
            assertFalse(message, message.contains("tablet", ignoreCase = true))
            assertFalse(message, message.contains("Exception"))
            assertFalse(message, message.contains("java."))
        }
    }

    @Test fun rawExceptionTextIsNotShown() {
        val error = IOException("unexpected end of stream on com.android.okhttp.Address@1f").toAppError(Service.Pilot)
        assertEquals(ErrorKind.Offline, error.kind)
        assertFalse(error.message.contains("okhttp"))
    }

    @Test fun statusCodesMapToKinds() {
        assertEquals(ErrorKind.Unauthorized, HttpFailure(401).toAppError(Service.Control).kind)
        assertTrue(HttpFailure(401).toAppError(Service.Control).message.contains("expired"))
        assertEquals(ErrorKind.Forbidden, HttpFailure(403).toAppError(Service.Pilot).kind)
        assertEquals(ErrorKind.Rejected, HttpFailure(412).toAppError(Service.Energy).kind)
        assertEquals(ErrorKind.Server, HttpFailure(502).toAppError(Service.Energy).kind)
        assertEquals(ErrorKind.Security, SSLHandshakeException("x").toAppError(Service.Pilot).kind)
        assertEquals(ErrorKind.Timeout, SocketTimeoutException().toAppError(Service.Pilot).kind)
    }

    @Test fun serverExplanationIsUsedForRejectedChanges() {
        assertEquals("Brightness must be 0-100", HttpFailure(422, "Brightness must be 0-100").toAppError(Service.Pilot).message)
        assertEquals("unauthorized", serverDetail("""{"error":"unauthorized"}"""))
        assertEquals("Room not found", serverDetail("""{"detail":"Room not found"}"""))
        assertEquals(null, serverDetail("<html>Bad gateway</html>"))
    }

    @Test fun onlyTransientReadFailuresMayUseSavedData() {
        assertTrue(SnapshotCache.mayUseSaved("GET", IOException()))
        assertTrue(SnapshotCache.mayUseSaved("GET", HttpFailure(503)))
        assertFalse(SnapshotCache.mayUseSaved("GET", HttpFailure(401)))
        assertFalse(SnapshotCache.mayUseSaved("GET", HttpFailure(404)))
        assertFalse(SnapshotCache.mayUseSaved("POST", IOException()))
        assertFalse(SnapshotCache.mayUseSaved("GET", AppException(AppError(ErrorKind.NotPaired, "Not paired."))))
    }

    @Test fun failedRefreshKeepsContentButMarksItStale() {
        val error = AppError(ErrorKind.Offline, "Offline.")
        val kept = LoadState.Content("data").failedWith(error)
        assertEquals(LoadState.Content("data", stale = true, problem = error), kept)
        assertEquals(LoadState.Error(error), LoadState.Loading.failedWith(error))
    }
}
