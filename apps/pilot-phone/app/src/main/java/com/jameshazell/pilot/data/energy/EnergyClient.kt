package com.jameshazell.pilot.data.energy

import com.jameshazell.pilot.core.AddressPolicy
import com.jameshazell.pilot.core.AppDispatchers
import com.jameshazell.pilot.core.AppError
import com.jameshazell.pilot.core.AppException
import com.jameshazell.pilot.core.CredentialStore
import com.jameshazell.pilot.core.ErrorKind
import com.jameshazell.pilot.core.HttpClients
import com.jameshazell.pilot.core.ReadResult
import com.jameshazell.pilot.core.SnapshotCache
import com.jameshazell.pilot.core.jsonBody
import com.jameshazell.pilot.core.jsonOf
import com.jameshazell.pilot.core.parseJson
import com.jameshazell.pilot.core.str
import com.jameshazell.pilot.core.text
import java.io.IOException
import java.security.GeneralSecurityException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.Request
import org.json.JSONObject

/**
 * Energy Manager mobile API. Handles the device session transparently:
 * first use consumes the one-time pairing grant (registering the `energy-proof` public key),
 * and the access token is refreshed 30 seconds before it expires.
 */
class EnergyClient(
    private val http: HttpClients,
    private val credentials: CredentialStore,
    private val key: EnergyKey,
    private val cache: SnapshotCache,
    private val dispatchers: AppDispatchers,
) {
    private class Access(val url: String, val gatewayToken: String, val accessToken: String)

    private val sessionLock = Mutex()

    /** True when Energy Manager credentials exist on this phone. */
    suspend fun isPaired(): Boolean = withContext(dispatchers.io) {
        runCatching { credentials.load().energy?.let { it.session != null || it.grant != null } ?: false }
            .getOrDefault(false)
    }

    /** True when a one-time grant is waiting to be consumed (first run after provisioning). */
    suspend fun hasPendingGrant(): Boolean = withContext(dispatchers.io) {
        runCatching { credentials.load().energy?.grant != null }.getOrDefault(false)
    }

    /** The saved copy of a GET, without touching the network. */
    suspend fun saved(path: String): ReadResult? = withContext(dispatchers.io) {
        cache.get(cacheId(path))?.let { saved ->
            runCatching { ReadResult(parseJson(saved.body), stale = true, savedAt = saved.savedAt, problem = null) }.getOrNull()
        }
    }

    /**
     * GET with read-through caching: a live answer is saved; a transport or 5xx failure falls
     * back to the saved copy (marked stale). Rejected credentials never fall back.
     */
    suspend fun read(path: String): ReadResult {
        try {
            val text = send(path, "GET", null, emptyMap())
            withContext(dispatchers.io) { cache.put(cacheId(path), text) }
            return ReadResult(parseJson(text), stale = false, savedAt = null, problem = null)
        } catch (error: IOException) {
            if (SnapshotCache.mayUseSaved("GET", error)) {
                saved(path)?.let { return it.copy(problem = error) }
            }
            throw error
        }
    }

    /** Any request; returns the response text. Mutations are sent exactly once. */
    suspend fun send(path: String, method: String, body: JSONObject?, headers: Map<String, String>): String {
        val access = access()
        return wire(access.url, path, access.accessToken, method, body, transport(access.gatewayToken) + headers)
    }

    /**
     * Signed command. Order matters: fetch a challenge, have the owner unlock the phone
     * ([authenticate]), sign `POST\n<path>\n<challenge>\n<sha256 of body>` with the Keystore key,
     * then send. The body is always `{}`.
     */
    suspend fun signedAction(action: EnergyAction, authenticate: suspend () -> Unit): JSONObject {
        val challenge = (parseJson(send(CHALLENGE_PATH, "POST", JSONObject(), emptyMap())) as JSONObject).str("challenge")
        if (challenge.isBlank()) throw AppException(
            AppError(ErrorKind.Server, "Energy Manager didn't issue a command challenge. Try again."),
        )
        authenticate()
        val path = actionPath(action)
        val body = JSONObject()
        val signature = withContext(dispatchers.io) {
            try {
                key.sign(EnergyProof.signingString(path, challenge, body.toString()))
            } catch (error: GeneralSecurityException) {
                throw AppException(
                    AppError(ErrorKind.AuthCancelled, "This phone couldn't sign the command. Unlock it and try again."),
                    error,
                )
            }
        }
        val headers = mapOf(EnergyProof.CHALLENGE_HEADER to challenge, EnergyProof.SIGNATURE_HEADER to signature)
        return parseJson(send(path, "POST", body, headers)) as? JSONObject ?: JSONObject()
    }

    private suspend fun access(): Access = sessionLock.withLock {
        val all = withContext(dispatchers.io) { credentials.load() }
        val energy = all.energy ?: throw notPaired()
        var session = energy.session
        if (session == null) {
            val grant = energy.grant ?: throw notPaired()
            val pem = withContext(dispatchers.io) {
                try {
                    key.publicKeyPem()
                } catch (error: GeneralSecurityException) {
                    throw AppException(
                        AppError(ErrorKind.Invalid, "Set a screen lock on this phone before pairing with Energy Manager."),
                        error,
                    )
                }
            }
            val response = parseJson(
                wire(
                    energy.url, PAIRING_PATH, "", "POST",
                    jsonOf("grant" to grant, "device_name" to DEVICE_NAME, "public_key_pem" to pem),
                    transport(energy.gatewayToken),
                ),
            ) as JSONObject
            all.setEnergySession(response)
            withContext(dispatchers.io) { credentials.save(all) }
            session = all.energy?.session ?: throw notPaired()
        }
        if (session.needsRefresh()) {
            val renewed = parseJson(
                wire(
                    energy.url, REFRESH_PATH, "", "POST",
                    jsonOf("device_id" to session.deviceId, "refresh_token" to session.refreshToken),
                    transport(energy.gatewayToken),
                ),
            ) as JSONObject
            all.renewEnergyAccess(renewed.str("access_token"), renewed.str("access_expires_at"))
            withContext(dispatchers.io) { credentials.save(all) }
            session = all.energy?.session ?: throw notPaired()
        }
        Access(energy.url, energy.gatewayToken, session.accessToken)
    }

    private suspend fun wire(
        url: String,
        path: String,
        token: String,
        method: String,
        body: JSONObject?,
        headers: Map<String, String>,
    ): String {
        AddressPolicy.requireSecure(url, path)
        val request = Request.Builder().url(url + path).header("Accept", "application/json")
        if (token.isNotBlank()) request.header("Authorization", "Bearer $token")
        headers.forEach { (name, value) -> request.header(name, value) }
        request.method(method, if (method == "GET") null else jsonBody(body))
        return http.shared.text(request.build())
    }

    private fun notPaired() = AppException(
        AppError(ErrorKind.NotPaired, "Energy Manager isn't paired on this phone yet."),
    )

    companion object {
        const val BOOTSTRAP_PATH = "/mobile/v1/bootstrap"
        const val HISTORY_PATH = "/mobile/v1/history?limit=288"
        const val DAILY_PATH = "/mobile/v1/daily?limit=30"
        const val SETTINGS_PATH = "/mobile/v1/settings"
        const val CHALLENGE_PATH = "/mobile/v1/auth/challenge"
        const val PAIRING_PATH = "/mobile/v1/pairing/consume"
        const val REFRESH_PATH = "/mobile/v1/session/refresh"
        const val GATEWAY_HEADER = "X-House-Energy-Device-Token"
        /** Shown in the Energy Manager's device list. */
        const val DEVICE_NAME = "Galaxy Fold · Pilot"

        fun actionPath(action: EnergyAction) = "/mobile/v1/actions/${action.id}"
        fun cacheId(path: String) = "energy:$path"
        private fun transport(gatewayToken: String) = mapOf(GATEWAY_HEADER to gatewayToken)
    }
}
