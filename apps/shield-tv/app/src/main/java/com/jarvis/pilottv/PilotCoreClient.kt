package com.jarvis.pilottv

import java.io.IOException
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import org.json.JSONObject

class PilotCoreException(
    message: String,
    val statusCode: Int? = null,
) : IOException(message)

data class CoreConnection(
    val baseUrl: String,
    val deviceId: String = "",
    val token: String = "",
) {
    fun normalizedBaseUrl(): String = baseUrl.trim().removeSuffix("/")

    fun validate(requireCredentials: Boolean = true): String? {
        if (requireCredentials && deviceId.isBlank()) return "Pilot TV has not been paired."
        if (requireCredentials && token.isBlank()) return "Pilot TV credentials are missing."
        val uri = runCatching { URI(normalizedBaseUrl()) }.getOrNull()
            ?: return "Pilot Core address is invalid."
        if (uri.host.isNullOrBlank() || uri.userInfo != null) {
            return "Pilot Core address needs a host and cannot include credentials."
        }
        if (!uri.path.isNullOrBlank() && uri.path != "/") {
            return "Pilot Core address cannot include a path."
        }
        if (uri.query != null || uri.fragment != null) {
            return "Pilot Core address cannot include a query or fragment."
        }
        if (uri.scheme == "https") return null
        if (uri.scheme != "http") return "Use HTTPS, or HTTP on a private local address."
        if (!CoreAddressPolicy.isPrivateHost(uri.host)) {
            return "Cleartext HTTP is permitted only for private local addresses."
        }
        return null
    }
}

object CoreAddressPolicy {
    fun isPrivateHost(host: String): Boolean {
        val normalized = host.removePrefix("[").removeSuffix("]").lowercase()
        if (normalized == "localhost" || normalized.endsWith(".local")) return true
        val octets = normalized.split(".")
            .takeIf { it.size == 4 }
            ?.map { it.toIntOrNull() }
            ?.takeIf { values -> values.all { it != null && it in 0..255 } }
            ?.map { requireNotNull(it) }
            ?: return false
        return octets[0] == 10 ||
            (octets[0] == 172 && octets[1] in 16..31) ||
            (octets[0] == 192 && octets[1] == 168) ||
            octets[0] == 127
    }
}

class PilotCoreClient private constructor(
    private val connection: CoreConnection,
) {
    val credentials = DeviceCredentials(
        baseUrl = connection.normalizedBaseUrl(),
        deviceId = connection.deviceId,
        token = connection.token,
    )

    companion object {
        fun authenticated(credentials: DeviceCredentials): PilotCoreClient = PilotCoreClient(
            CoreConnection(credentials.baseUrl, credentials.deviceId, credentials.token),
        )

        suspend fun pair(baseUrl: String, grantToken: String): DeviceCredentials {
            val connection = CoreConnection(baseUrl)
            connection.validate(requireCredentials = false)?.let {
                throw PilotCoreException(it)
            }
            if (grantToken.isBlank()) {
                throw PilotCoreException("Enter the one-time pairing code from Pilot Core.")
            }
            val result = requestJson(
                connection = connection,
                path = "/v1/devices/bootstrap",
                method = "POST",
                bearer = grantToken.trim(),
            )
            val deviceId = result.optString("device_id")
            val token = result.optString("device_token")
            if (deviceId.isBlank() || token.isBlank()) {
                throw PilotCoreException("Pilot Core returned incomplete device credentials.")
            }
            return DeviceCredentials(connection.normalizedBaseUrl(), deviceId, token)
        }

        private suspend fun requestJson(
            connection: CoreConnection,
            path: String,
            method: String = "GET",
            body: JSONObject? = null,
            bearer: String? = null,
            includeDeviceHeader: Boolean = false,
        ): JSONObject = withContext(Dispatchers.IO) {
            val request = URL("${connection.normalizedBaseUrl()}$path")
                .openConnection() as HttpURLConnection
            try {
                request.instanceFollowRedirects = false
                request.requestMethod = method
                request.connectTimeout = 8_000
                request.readTimeout = 25_000
                request.useCaches = false
                request.setRequestProperty("Accept", "application/json")
                bearer?.let { request.setRequestProperty("Authorization", "Bearer $it") }
                if (includeDeviceHeader) {
                    request.setRequestProperty("X-Pilot-Device-ID", connection.deviceId)
                }
                if (body != null) {
                    request.doOutput = true
                    request.setRequestProperty("Content-Type", "application/json")
                    request.outputStream.use { output ->
                        output.write(body.toString().toByteArray(Charsets.UTF_8))
                    }
                }
                val status = request.responseCode
                val content = (if (status in 200..299) {
                    request.inputStream
                } else {
                    request.errorStream
                })?.bufferedReader()?.use { it.readText() }.orEmpty()
                if (status !in 200..299) {
                    val detail = runCatching { JSONObject(content).optString("detail") }
                        .getOrNull()
                        ?.takeIf(String::isNotBlank)
                    val message = when (status) {
                        401 -> "Pilot Core rejected these device credentials."
                        403 -> detail ?: "This Pilot TV is not permitted to use that feature."
                        404 -> detail ?: "This feature requires a newer Pilot Core release."
                        else -> detail ?: "Pilot Core returned HTTP $status."
                    }
                    throw PilotCoreException(message, status)
                }
                if (content.isBlank()) JSONObject() else JSONObject(content)
            } catch (error: PilotCoreException) {
                throw error
            } catch (error: Exception) {
                throw PilotCoreException("Unable to reach Pilot Core: ${error.message}")
            } finally {
                request.disconnect()
            }
        }
    }

    suspend fun manifest(): DeviceManifest {
        connection.validate()?.let { throw PilotCoreException(it) }
        val root = request("/v1/devices/${connection.deviceId}/manifest")
        return PilotJson.manifest(root, credentials)
    }

    suspend fun snapshot(
        manifest: DeviceManifest,
        cursor: Long? = null,
    ): PilotTvSnapshot = coroutineScope {
        val eventEnvelope = async {
            optionalRequest(
                "/v1/devices/${connection.deviceId}/events/snapshot" +
                    (cursor?.let { "?cursor=$it" } ?: ""),
            )
        }
        val media = async {
            request("/v1/devices/${connection.deviceId}/media")
        }
        val surface = async {
            optionalRequest("/v1/devices/${connection.deviceId}/surface")
        }
        val home = async {
            optionalRequest(
                "/v1/devices/${connection.deviceId}/home?room_id=${urlEncode(manifest.roomId)}",
            )
        }
        val mediaValue = media.await()
        PilotJson.snapshot(
            manifest = manifest,
            mediaRoot = mediaValue,
            surfaceRoot = surface.await(),
            homeRoot = home.await(),
            envelope = eventEnvelope.await(),
        )
    }

    suspend fun mediaCommand(command: MediaCommand): JSONObject {
        val body = JSONObject().put("action", command.action)
        command.playerId?.let { body.put("player_id", it) }
        command.volume?.let { body.put("volume", it) }
        command.positionSeconds?.let { body.put("position_seconds", it) }
        command.muted?.let { body.put("muted", it) }
        command.targetRoomId?.let { body.put("target_room_id", it) }
        command.targetPlayerId?.let { body.put("target_player_id", it) }
        command.mediaUri?.let { body.put("media_uri", it) }
        return request(
            "/v1/devices/${connection.deviceId}/media",
            method = "POST",
            body = body,
        )
    }

    suspend fun rotateCredentials(): DeviceCredentials {
        val root = request(
            "/v1/devices/${connection.deviceId}/credentials/rotate-self",
            method = "POST",
            body = JSONObject(),
        )
        val token = root.optString("device_token")
        if (token.isBlank()) throw PilotCoreException("Credential rotation returned no token.")
        return credentials.copy(token = token)
    }

    private suspend fun optionalRequest(path: String): JSONObject? = try {
        request(path)
    } catch (error: PilotCoreException) {
        if (error.statusCode in setOf(403, 404, 405, 501)) null else throw error
    }

    private suspend fun request(
        path: String,
        method: String = "GET",
        body: JSONObject? = null,
    ): JSONObject = requestJson(
        connection = connection,
        path = path,
        method = method,
        body = body,
        bearer = connection.token,
        includeDeviceHeader = true,
    )
}

private fun urlEncode(value: String): String =
    java.net.URLEncoder.encode(value, Charsets.UTF_8.name())
