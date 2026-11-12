package com.jameshazell.pilot.core

import java.io.File
import java.time.Instant
import org.json.JSONObject

data class PilotCredentials(val url: String, val deviceId: String, val token: String)

data class ControlCredentials(val url: String, val token: String)

data class EnergySession(
    val deviceId: String,
    val accessToken: String,
    val accessExpiresAt: String,
    val refreshToken: String,
) {
    /** True when the access token is missing, unparseable, or expires within [marginSeconds]. */
    fun needsRefresh(now: Instant = Instant.now(), marginSeconds: Long = 30): Boolean =
        runCatching { Instant.parse(accessExpiresAt).isBefore(now.plusSeconds(marginSeconds)) }
            .getOrDefault(true)
}

data class EnergyCredentials(
    val url: String,
    val gatewayToken: String,
    /** One-time pairing grant; present only until the first successful pairing. */
    val grant: String?,
    val session: EnergySession?,
)

/**
 * The `unified` credential blob. JSON shape is frozen (shared with 1.x installs and the
 * provisioning file):
 *
 * ```
 * { "pilot":   {"url", "device_id", "token"},
 *   "control": {"url", "token"},
 *   "energy":  {"url", "gateway_token", "grant"?,
 *               "session": {"device_id", "access_token", "access_expires_at", "refresh_token"}} }
 * ```
 *
 * The document is edited in place so fields this version does not know about survive a rewrite.
 */
class UnifiedCredentials private constructor(private val root: JSONObject) {
    val pilot: PilotCredentials?
        get() = root.optJSONObject("pilot")?.let {
            PilotCredentials(it.str("url"), it.str("device_id"), it.str("token"))
        }

    val control: ControlCredentials?
        get() = root.optJSONObject("control")?.takeIf { it.str("token").isNotBlank() }?.let {
            ControlCredentials(it.str("url", Endpoints.CONTROL_DEFAULT_URL).trimEnd('/'), it.str("token"))
        }

    val energy: EnergyCredentials?
        get() = root.optJSONObject("energy")?.let { energy ->
            EnergyCredentials(
                url = energy.str("url", Endpoints.ENERGY_DEFAULT_URL).trimEnd('/'),
                gatewayToken = energy.str("gateway_token"),
                grant = energy.str("grant").takeIf(String::isNotBlank),
                session = energy.optJSONObject("session")?.let {
                    EnergySession(
                        deviceId = it.str("device_id"),
                        accessToken = it.str("access_token"),
                        accessExpiresAt = it.str("access_expires_at"),
                        refreshToken = it.str("refresh_token"),
                    )
                },
            )
        }

    /** Stores the pairing response verbatim as the session and discards the spent grant. */
    fun setEnergySession(pairingResponse: JSONObject) {
        val energy = root.optJSONObject("energy") ?: JSONObject()
        energy.put("session", pairingResponse)
        energy.remove("grant")
        root.put("energy", energy)
    }

    fun renewEnergyAccess(accessToken: String, accessExpiresAt: String) {
        val energy = checkNotNull(root.optJSONObject("energy")) { "Energy Manager is not paired" }
        val session = checkNotNull(energy.optJSONObject("session")) { "Energy Manager is not paired" }
        session.put("access_token", accessToken)
        session.put("access_expires_at", accessExpiresAt)
    }

    /** 1.0.8 shim: the exact retired Control URL becomes the current one. Returns true if changed. */
    fun migrateControlUrl(): Boolean {
        val control = root.optJSONObject("control") ?: return false
        if (control.str("url").trimEnd('/') != Endpoints.CONTROL_RETIRED_URL) return false
        control.put("url", Endpoints.CONTROL_DEFAULT_URL)
        return true
    }

    fun toJson(): String = root.toString()

    companion object {
        const val KEY = "unified"
        fun parse(raw: String?): UnifiedCredentials = UnifiedCredentials(JSONObject(raw ?: "{}"))
    }
}

/** Reads and writes the `unified` blob. All methods touch disk: call off the main thread. */
class CredentialStore(private val store: SecretStore) {
    @Synchronized
    fun load(): UnifiedCredentials {
        val credentials = UnifiedCredentials.parse(store.get(UnifiedCredentials.KEY))
        if (credentials.migrateControlUrl()) save(credentials)
        return credentials
    }

    /** Durable write: this holds rotated session tokens. */
    @Synchronized
    fun save(credentials: UnifiedCredentials) {
        store.put(UnifiedCredentials.KEY, credentials.toJson(), durable = true)
    }
}

/**
 * Imports `filesDir/unified-provision.json` (pushed privately over adb) once, then deletes it:
 * the whole document becomes the `unified` blob and its `pilot` section becomes the Pilot Core
 * pairing.
 */
class Provisioner(
    private val filesDir: File,
    private val store: SecretStore,
    private val prefs: Prefs,
    private val tokens: DeviceTokenStore,
) {
    /** @return true when a provisioning file was imported. */
    fun importIfPresent(): Boolean {
        val file = File(filesDir, FILE_NAME)
        if (!file.exists()) return false
        val raw = file.readText()
        val credentials = UnifiedCredentials.parse(raw)
        store.put(UnifiedCredentials.KEY, credentials.toJson(), durable = true)
        credentials.pilot?.let { pilot ->
            prefs.save(prefs.load().copy(coreUrl = pilot.url, deviceId = pilot.deviceId))
            pilot.token.trim().takeIf(String::isNotEmpty)?.let(tokens::write)
        }
        check(file.delete()) { "The provisioning file could not be removed" }
        return true
    }

    companion object {
        const val FILE_NAME = "unified-provision.json"
    }
}
