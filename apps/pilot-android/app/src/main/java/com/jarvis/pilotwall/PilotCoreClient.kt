package com.jarvis.pilotwall

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.ByteArrayOutputStream
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

    suspend fun manifest(): ClientManifest? = try {
        PilotJson.manifest(request("v1/devices/${config.deviceId}/manifest"))
    } catch (error: PilotApiException) {
        if (error.status in setOf(404, 405, 501)) null else throw error
    }

    suspend fun eventSnapshotCursor(pathTemplate: String, cursor: String?): String? {
        val root = request(eventPath(pathTemplate, cursor, longPoll = false))
        return root.optString("cursor").takeIf(String::isNotBlank)
            ?: root.optString("next_cursor").takeIf(String::isNotBlank)
    }

    suspend fun events(pathTemplate: String, cursor: String?): PilotEventPage =
        PilotJson.events(request(eventPath(pathTemplate, cursor, longPoll = true)))

    private fun eventPath(pathTemplate: String, cursor: String?, longPoll: Boolean): String {
        val resolved = pathTemplate
            .replace("{id}", config.deviceId)
            .replace("{device_id}", config.deviceId)
            .trimStart('/')
        val parameters = buildList {
            cursor?.takeIf(String::isNotBlank)?.let {
                add("cursor=${java.net.URLEncoder.encode(it, Charsets.UTF_8.name())}")
            }
            if (longPoll) add("timeout_seconds=25")
        }
        if (parameters.isEmpty()) return resolved
        val separator = if ('?' in resolved) '&' else '?'
        return "$resolved$separator${parameters.joinToString("&")}"
    }

    suspend fun mediaCommand(command: MediaCommand) {
        val body = JSONObject().apply {
            put("action", command.action)
            command.playerId?.let { put("player_id", it) }
            command.mediaUri?.let { put("media_uri", it) }
            command.targetRoomId?.let { put("target_room_id", it) }
            command.targetPlayerId?.let { put("target_player_id", it) }
            command.volume?.let { put("volume", it) }
            command.positionSeconds?.let { put("position_seconds", it) }
            command.muted?.let { put("muted", it) }
            command.source?.let { put("source", it) }
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

    suspend fun voice(
        pcm: ByteArray,
        sampleRate: Int = 16_000,
        conversationId: String? = null,
    ): AssistantReply = withContext(Dispatchers.IO) {
        val connection = connection("v1/devices/${config.deviceId}/voice")
        try {
            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/octet-stream")
            connection.setRequestProperty("X-Pilot-Sample-Rate", sampleRate.toString())
            connection.setRequestProperty("X-Pilot-Language", "en-AU")
            conversationId?.let {
                connection.setRequestProperty("X-Pilot-Conversation-ID", it)
            }
            connection.setFixedLengthStreamingMode(pcm.size)
            connection.outputStream.use { it.write(pcm) }
            PilotJson.assistant(readJson(connection))
        } finally {
            connection.disconnect()
        }
    }

    suspend fun audioAsset(path: String): ByteArray = withContext(Dispatchers.IO) {
        val resolved = if (path.startsWith("http://") || path.startsWith("https://")) {
            val candidate = URL(path)
            val core = URL(CoreAddressPolicy.normalize(config.coreUrl))
            require(candidate.protocol == core.protocol && candidate.host == core.host && candidate.port == core.port) {
                "Pilot audio must come from the configured Core server"
            }
            path.removePrefix(CoreAddressPolicy.normalize(config.coreUrl))
        } else path.trimStart('/')
        val connection = connection(resolved)
        try {
            val status = connection.responseCode
            if (status !in 200..299) throw apiError(connection, status)
            connection.inputStream.use { input ->
                val output = ByteArrayOutputStream()
                input.copyTo(output)
                output.toByteArray()
            }
        } finally {
            connection.disconnect()
        }
    }

    suspend fun artworkAsset(path: String): ByteArray = withContext(Dispatchers.IO) {
        val core = URL(CoreAddressPolicy.normalize(config.coreUrl))
        val candidate = if (path.startsWith("http://") || path.startsWith("https://")) {
            URL(path)
        } else {
            URL(CoreAddressPolicy.normalize(config.coreUrl) + path.trimStart('/'))
        }
        val sameOrigin = candidate.protocol == core.protocol && candidate.host == core.host &&
            candidate.port == core.port
        val connection = if (sameOrigin) {
            connection(candidate.toString().removePrefix(CoreAddressPolicy.normalize(config.coreUrl)))
        } else {
            (candidate.openConnection() as HttpURLConnection).apply {
                instanceFollowRedirects = true
                connectTimeout = 8_000
                readTimeout = 15_000
            }
        }
        try {
            connection.setRequestProperty("Accept", "image/*")
            val status = connection.responseCode
            if (status !in 200..299) throw apiError(connection, status)
            val declared = connection.contentLengthLong
            require(declared <= MAX_ARTWORK_BYTES || declared < 0) { "Artwork is too large" }
            connection.inputStream.use { input ->
                val output = ByteArrayOutputStream()
                val buffer = ByteArray(16_384)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    output.write(buffer, 0, count)
                    require(output.size() <= MAX_ARTWORK_BYTES) { "Artwork is too large" }
                }
                output.toByteArray()
            }
        } finally {
            connection.disconnect()
        }
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

    private fun connection(path: String): HttpURLConnection {
        val normalized = CoreAddressPolicy.normalize(config.coreUrl)
        return (URL(normalized + path.trimStart('/')).openConnection() as HttpURLConnection).apply {
            instanceFollowRedirects = false
            connectTimeout = 8_000
            readTimeout = 25_000
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Authorization", "Bearer $token")
            setRequestProperty("X-Pilot-Device-ID", config.deviceId)
        }
    }

    private suspend fun request(
        path: String,
        method: String = "GET",
        body: JSONObject? = null,
    ): JSONObject = withContext(Dispatchers.IO) {
        val connection = connection(path)
        try {
            // Never forward the device bearer token to a provider-controlled
            // redirect target. Pilot Core endpoints are addressed directly.
            connection.requestMethod = method
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(body.toString().toByteArray()) }
            }
            readJson(connection)
        } catch (error: PilotApiException) {
            throw error
        } catch (error: Exception) {
            throw IOException("Unable to reach Pilot Core", error)
        } finally {
            connection.disconnect()
        }
    }


    private fun readJson(connection: HttpURLConnection): JSONObject {
        val status = connection.responseCode
        val content = (if (status in 200..299) connection.inputStream else connection.errorStream)
            ?.bufferedReader()?.use { it.readText() }.orEmpty()
        if (status !in 200..299) throw apiError(status, content)
        return if (content.isBlank()) JSONObject() else JSONObject(content)
    }

    private fun apiError(connection: HttpURLConnection, status: Int): PilotApiException {
        val content = connection.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
        return apiError(status, content)
    }

    private fun apiError(status: Int, content: String): PilotApiException {
        val detail = runCatching { JSONObject(content).optString("detail") }.getOrNull()
        return PilotApiException(
            status,
            detail?.takeIf(String::isNotBlank) ?: "Pilot Core request failed",
        )
    }

    companion object {
        private const val MAX_ARTWORK_BYTES = 8 * 1024 * 1024

        suspend fun redeemBootstrap(coreUrl: String, grantToken: String): BootstrapRegistration =
            withContext(Dispatchers.IO) {
                val normalized = CoreAddressPolicy.normalize(coreUrl)
                val connection = URL(normalized + "v1/devices/bootstrap")
                    .openConnection() as HttpURLConnection
                try {
                    connection.instanceFollowRedirects = false
                    connection.requestMethod = "POST"
                    connection.connectTimeout = 8_000
                    connection.readTimeout = 15_000
                    connection.setRequestProperty("Accept", "application/json")
                    connection.setRequestProperty("Authorization", "Bearer ${grantToken.trim()}")
                    connection.setFixedLengthStreamingMode(0)
                    connection.doOutput = true
                    connection.outputStream.use { }
                    val status = connection.responseCode
                    val content = (if (status in 200..299) connection.inputStream else connection.errorStream)
                        ?.bufferedReader()?.use { it.readText() }.orEmpty()
                    if (status !in 200..299) {
                        val detail = runCatching { JSONObject(content).optString("detail") }.getOrNull()
                        throw PilotApiException(status, detail ?: "Pairing grant was rejected")
                    }
                    PilotJson.bootstrap(JSONObject(content))
                } catch (error: PilotApiException) {
                    throw error
                } catch (error: Exception) {
                    throw IOException("Unable to pair with Pilot Core", error)
                } finally {
                    connection.disconnect()
                }
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
