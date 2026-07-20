package com.jarvis.pilotwall

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL

class PilotCoreClient(
    private val config: PilotConfig,
    private val token: String,
) {
    suspend fun snapshot(): PilotSnapshot = coroutineScope {
        val media = async { request("v1/devices/${config.deviceId}/media") }
        val surface = async { request("v1/devices/${config.deviceId}/surface") }
        PilotSnapshot(
            media = PilotJson.media(media.await()),
            surface = PilotJson.surface(surface.await()),
        )
    }

    suspend fun mediaCommand(command: MediaCommand) {
        val body = JSONObject().apply {
            put("action", command.action)
            command.playerId?.let { put("player_id", it) }
            command.mediaUri?.let { put("media_uri", it) }
            command.targetRoomId?.let { put("target_room_id", it) }
            command.targetPlayerId?.let { put("target_player_id", it) }
            command.volume?.let { put("volume", it) }
        }
        request("v1/devices/${config.deviceId}/media", "POST", body)
    }

    suspend fun search(query: String): List<MusicSearchResult> {
        val body = JSONObject()
            .put("query", query)
            .put("limit", 30)
            .put("library_only", false)
        return PilotJson.search(
            request("v1/devices/${config.deviceId}/media/search", "POST", body),
        )
    }

    suspend fun ask(text: String, roomId: String, conversationId: String?): AssistantReply {
        val body = JSONObject()
            .put("text", text)
            .put("language", "en-AU")
            .put("room_id", roomId)
        conversationId?.let { body.put("conversation_id", it) }
        return PilotJson.assistant(
            request("v1/devices/${config.deviceId}/assistant", "POST", body),
        )
    }

    suspend fun home(roomId: String): HomeProjection {
        val encoded = java.net.URLEncoder.encode(roomId, Charsets.UTF_8.name())
        return PilotJson.home(request("v1/devices/${config.deviceId}/home?room_id=$encoded"))
    }

    suspend fun homeAction(
        roomId: String,
        entityId: String,
        action: String,
        value: Double? = null,
    ): HomeAction {
        val parameters = JSONObject()
        value?.let { parameters.put("value", it) }
        val body = JSONObject()
            .put("room_id", roomId)
            .put("entity_id", entityId)
            .put("action", action)
            .put("parameters", parameters)
        return PilotJson.homeAction(
            request("v1/devices/${config.deviceId}/home/actions", "POST", body),
        )
    }

    suspend fun confirmHomeAction(actionId: String): HomeAction =
        PilotJson.homeAction(
            request(
                "v1/devices/${config.deviceId}/home/actions/$actionId/confirm",
                "POST",
                JSONObject(),
            ),
        )

    suspend fun testConnection(): String {
        val result = request("v1/devices/${config.deviceId}/media")
        return result.optString("device_id", config.deviceId)
    }

    private suspend fun request(
        path: String,
        method: String = "GET",
        body: JSONObject? = null,
    ): JSONObject = withContext(Dispatchers.IO) {
        val normalized = CoreAddressPolicy.normalize(config.coreUrl)
        val connection = URL(normalized + path).openConnection() as HttpURLConnection
        try {
            // Never forward the device bearer token to a provider-controlled
            // redirect target. Pilot Core endpoints are addressed directly.
            connection.instanceFollowRedirects = false
            connection.requestMethod = method
            connection.connectTimeout = 8_000
            connection.readTimeout = 25_000
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("Authorization", "Bearer $token")
            connection.setRequestProperty("X-Pilot-Device-ID", config.deviceId)
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(body.toString().toByteArray()) }
            }
            val status = connection.responseCode
            val content = (if (status in 200..299) connection.inputStream else connection.errorStream)
                ?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (status !in 200..299) {
                val detail = runCatching { JSONObject(content).optString("detail") }.getOrNull()
                throw PilotApiException(status, detail?.takeIf(String::isNotBlank) ?: "Pilot Core request failed")
            }
            if (content.isBlank()) JSONObject() else JSONObject(content)
        } catch (error: PilotApiException) {
            throw error
        } catch (error: Exception) {
            throw IOException("Unable to reach Pilot Core", error)
        } finally {
            connection.disconnect()
        }
    }
}

class PilotApiException(val status: Int, override val message: String) : IOException(message)

object CoreAddressPolicy {
    fun normalize(value: String): String {
        val uri = runCatching { URI(value.trim()) }
            .getOrElse { throw IllegalArgumentException("Enter a valid Pilot Core URL") }
        require(uri.scheme == "https" || uri.scheme == "http") {
            "Pilot Core must use HTTP or HTTPS"
        }
        require(!uri.host.isNullOrBlank() && uri.userInfo == null && uri.query == null && uri.fragment == null) {
            "Enter a server URL without credentials, query, or fragment"
        }
        require(uri.path.isNullOrBlank() || uri.path == "/") {
            "Pilot Core URL must not contain a path"
        }
        if (uri.scheme == "http") {
            require(isPrivateOrLoopback(uri.host)) {
                "Unencrypted HTTP is only allowed for a private Pilot Core address"
            }
        }
        return value.trim().trimEnd('/') + "/"
    }

    internal fun isPrivateOrLoopback(host: String): Boolean {
        if (host == "localhost" || host == "127.0.0.1" || host == "::1") return true
        val octets = host.split('.').mapNotNull { it.toIntOrNull() }
        if (octets.size != 4 || octets.any { it !in 0..255 }) return false
        return octets[0] == 10 ||
            (octets[0] == 192 && octets[1] == 168) ||
            (octets[0] == 172 && octets[1] in 16..31)
    }
}
