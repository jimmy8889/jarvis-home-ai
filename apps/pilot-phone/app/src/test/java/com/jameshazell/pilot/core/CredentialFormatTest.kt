package com.jameshazell.pilot.core

import com.jameshazell.pilot.fieldNames
import java.time.Instant
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The on-disk formats shared with 1.x installs. Changing any expectation here unpairs phones. */
class CredentialFormatTest {
    private class FakeStore : SecretStore {
        val values = linkedMapOf<String, String>()
        val durableWrites = mutableListOf<String>()
        override fun get(name: String): String? = values[name]
        override fun put(name: String, value: String, durable: Boolean) {
            values[name] = value
            if (durable) durableWrites += name
        }
        override fun remove(name: String) { values.remove(name) }
    }

    /** Exactly what 1.0.9 wrote (and what unified-provision.json contains). */
    private val installed = """
        {"pilot":{"url":"https://pilot.example.net/","device_id":"fold-7","token":"pilot-token"},
         "control":{"url":"https://services01.tail7af3e.ts.net:8448","token":"control-token"},
         "energy":{"url":"https://energy.example.net","gateway_token":"gateway",
                   "session":{"device_id":"energy-device","access_token":"access",
                              "access_expires_at":"2026-11-12T03:00:00Z","refresh_token":"refresh",
                              "scopes":["read","control"]}},
         "future_section":{"keep":"me"}}
    """.trimIndent()

    @Test fun storageNamesAreFrozen() {
        assertEquals("unified", UnifiedCredentials.KEY)
        assertEquals("secure", SecureStore.FILE)
        assertEquals("app-v1", SecureStore.KEY_ALIAS)
        assertEquals("pilot_secure", DeviceTokenStore.FILE)
        assertEquals("token_iv", DeviceTokenStore.KEY_IV)
        assertEquals("token_ciphertext", DeviceTokenStore.KEY_CIPHERTEXT)
        assertEquals("pilot-wall-device-token", DeviceTokenStore.KEY_ALIAS)
        assertEquals("pilot_wall", Prefs.FILE)
        assertEquals(
            listOf("core_url", "device_id", "refresh_seconds", "keep_screen_on"),
            listOf(Prefs.KEY_CORE_URL, Prefs.KEY_DEVICE_ID, Prefs.KEY_REFRESH_SECONDS, Prefs.KEY_KEEP_SCREEN_ON),
        )
        assertEquals("unified-provision.json", Provisioner.FILE_NAME)
    }

    @Test fun readsTheInstalledUnifiedBlob() {
        val credentials = UnifiedCredentials.parse(installed)
        assertEquals(PilotCredentials("https://pilot.example.net/", "fold-7", "pilot-token"), credentials.pilot)
        assertEquals(ControlCredentials("https://services01.tail7af3e.ts.net:8448", "control-token"), credentials.control)
        val energy = credentials.energy!!
        assertEquals("https://energy.example.net", energy.url)
        assertEquals("gateway", energy.gatewayToken)
        assertNull(energy.grant)
        assertEquals(
            EnergySession("energy-device", "access", "2026-11-12T03:00:00Z", "refresh"),
            energy.session,
        )
    }

    @Test fun emptyOrMissingBlobMeansNothingIsPaired() {
        val credentials = UnifiedCredentials.parse(null)
        assertNull(credentials.pilot)
        assertNull(credentials.control)
        assertNull(credentials.energy)
        assertEquals("{}", credentials.toJson())
    }

    @Test fun pairingStoresTheSessionVerbatimAndDiscardsTheGrant() {
        val credentials = UnifiedCredentials.parse(
            """{"energy":{"url":"https://energy.example.net","gateway_token":"gateway","grant":"one-time"}}""",
        )
        assertEquals("one-time", credentials.energy!!.grant)
        assertNull(credentials.energy!!.session)

        credentials.setEnergySession(
            JSONObject(
                """{"device_id":"d1","access_token":"a1","access_expires_at":"2026-11-12T03:00:00Z",
                   "refresh_token":"r1","server_extra":7}""",
            ),
        )
        val written = JSONObject(credentials.toJson()).getJSONObject("energy")
        assertFalse(written.has("grant"))
        assertEquals("gateway", written.getString("gateway_token"))
        val session = written.getJSONObject("session")
        assertEquals(setOf("device_id", "access_token", "access_expires_at", "refresh_token", "server_extra"), session.fieldNames())
        assertEquals("d1", credentials.energy!!.session!!.deviceId)
    }

    @Test fun refreshRewritesOnlyTheAccessTokenAndExpiry() {
        val credentials = UnifiedCredentials.parse(installed)
        credentials.renewEnergyAccess("access-2", "2026-11-12T04:00:00Z")
        val root = JSONObject(credentials.toJson())
        val session = root.getJSONObject("energy").getJSONObject("session")
        assertEquals("access-2", session.getString("access_token"))
        assertEquals("2026-11-12T04:00:00Z", session.getString("access_expires_at"))
        assertEquals("refresh", session.getString("refresh_token"))
        assertEquals("energy-device", session.getString("device_id"))
        assertEquals(2, session.getJSONArray("scopes").length())
        // Sections this version does not know about survive a rewrite.
        assertEquals("me", root.getJSONObject("future_section").getString("keep"))
        assertEquals("pilot-token", root.getJSONObject("pilot").getString("token"))
    }

    @Test fun sessionRefreshesThirtySecondsBeforeExpiry() {
        val session = EnergySession("d", "a", "2026-11-12T03:00:00Z", "r")
        assertFalse(session.needsRefresh(Instant.parse("2026-11-12T02:59:29Z")))
        assertTrue(session.needsRefresh(Instant.parse("2026-11-12T02:59:31Z")))
        assertTrue(session.copy(accessExpiresAt = "").needsRefresh(Instant.parse("2026-11-12T00:00:00Z")))
    }

    @Test fun retiredControlUrlMigratesOnceAndKeepsEverythingElse() {
        val store = FakeStore()
        store.values["unified"] = installed.replace(
            "https://services01.tail7af3e.ts.net:8448",
            "https://hermes-control.tail7af3e.ts.net/",
        )
        val loaded = CredentialStore(store).load()
        assertEquals("https://services01.tail7af3e.ts.net:8448", loaded.control!!.url)
        assertEquals("control-token", loaded.control!!.token)
        assertEquals(listOf("unified"), store.durableWrites)
        val persisted = JSONObject(store.values.getValue("unified"))
        assertEquals("https://services01.tail7af3e.ts.net:8448", persisted.getJSONObject("control").getString("url"))
        assertEquals("refresh", persisted.getJSONObject("energy").getJSONObject("session").getString("refresh_token"))

        CredentialStore(store).load()
        assertEquals("no second write", 1, store.durableWrites.size)
    }

    @Test fun otherControlUrlsAreLeftAlone() {
        val store = FakeStore()
        store.values["unified"] = """{"control":{"url":"https://control.example.net","token":"t"}}"""
        assertEquals("https://control.example.net", CredentialStore(store).load().control!!.url)
        assertTrue(store.durableWrites.isEmpty())
    }

    @Test fun missingUrlsFallBackToTheDefaults() {
        val credentials = UnifiedCredentials.parse("""{"control":{"token":"t"},"energy":{"gateway_token":"g"}}""")
        assertEquals(Endpoints.CONTROL_DEFAULT_URL, credentials.control!!.url)
        assertEquals(Endpoints.ENERGY_DEFAULT_URL, credentials.energy!!.url)
        assertNull("no token means not paired", UnifiedCredentials.parse("""{"control":{"url":"https://x"}}""").control)
    }

    @Test fun snapshotCacheKeepsThe1xRecordFormat() {
        val store = FakeStore()
        val cache = SnapshotCache(store) { Instant.parse("2026-11-12T01:02:03Z") }
        cache.put("energy:/mobile/v1/bootstrap", """{"a":1}""")
        val record = JSONObject(store.values.getValue("snapshot:energy:/mobile/v1/bootstrap"))
        assertEquals(setOf("body", "savedAt"), record.fieldNames())
        assertEquals("""{"a":1}""", record.getString("body"))
        assertEquals("2026-11-12T01:02:03Z", record.getString("savedAt"))
        assertTrue("caches are not durable writes", store.durableWrites.isEmpty())

        val saved = cache.get("energy:/mobile/v1/bootstrap")!!
        assertEquals("""{"a":1}""", saved.body)
        assertEquals(Instant.parse("2026-11-12T01:02:03Z"), saved.savedAt)
    }

    @Test fun snapshotCacheStillReadsRecordsWrittenBy1x() {
        val store = FakeStore()
        store.values["snapshot:control:/v1/tasks"] = """{"body":"[]","savedAt":"2026-10-01T00:00:00Z"}"""
        store.values["cache:control:/v1/workers"] = "[1]"
        val cache = SnapshotCache(store)
        assertEquals(Instant.parse("2026-10-01T00:00:00Z"), cache.get("control:/v1/tasks")!!.savedAt)
        assertEquals(SnapshotCache.Saved("[1]", null), cache.get("control:/v1/workers"))
        assertNull(cache.get("control:/v1/projects"))
        assertEquals(
            "pilot-snapshot:https://pilot.example.net/:fold-7",
            SnapshotCache.pilotSnapshotKey("https://pilot.example.net/", "fold-7"),
        )
    }
}
