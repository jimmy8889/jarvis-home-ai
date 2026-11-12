package com.jameshazell.pilot.data.pilot

import com.jameshazell.pilot.core.AddressPolicy
import com.jameshazell.pilot.core.HttpClients
import com.jameshazell.pilot.core.HttpFailure
import com.jameshazell.pilot.core.PilotConfig
import com.jameshazell.pilot.core.await
import com.jameshazell.pilot.core.jsonBody
import com.jameshazell.pilot.core.parseJsonObject
import com.jameshazell.pilot.core.retryRead
import com.jameshazell.pilot.core.serverDetail
import com.jameshazell.pilot.core.textOrThrow
import java.io.ByteArrayOutputStream
import java.net.URI
import java.net.URLEncoder
import java.time.Instant
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONObject

/**
 * Pilot Core HTTP API for one paired device. Stateless and cheap to create.
 * Every call throws IOException subclasses ([HttpFailure] for non-2xx); the repository maps them.
 */
class PilotCoreClient(
    private val http: HttpClients,
    private val config: PilotConfig,
    private val token: String,
) {
    private val base = AddressPolicy.normalize(config.coreUrl)
    private val device = "v1/devices/${config.deviceId}"

    /**
     * Media + surface + dashboard in the saved-snapshot envelope
     * `{"media", "surface", "dashboard", "saved_at"}` (the format of the `pilot-snapshot:` cache).
     * A failed dashboard read is tolerated; the other two are required.
     */
    suspend fun snapshotEnvelope(): JSONObject = coroutineScope {
        val media = async { request("$device/media") }
        val surface = async { request("$device/surface") }
        val dashboard = async {
            try {
                request("$device/dashboard")
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                null
            }
        }
        JSONObject()
            .put("media", media.await())
            .put("surface", surface.await())
            .put("dashboard", dashboard.await())
            .put("saved_at", Instant.now().toString())
    }

    /** Null when this Core predates the client manifest (404/405/501). */
    suspend fun manifest(): ClientManifest? = try {
        PilotJson.manifest(request("$device/manifest"))
    } catch (error: HttpFailure) {
        if (error.status in setOf(404, 405, 501)) null else throw error
    }

    suspend fun eventSnapshotCursor(pathTemplate: String, cursor: String?): String? {
        val root = request(eventPath(pathTemplate, cursor, longPoll = false))
        return root.optString("cursor").takeIf(String::isNotBlank)
            ?: root.optString("next_cursor").takeIf(String::isNotBlank)
    }

    /**
     * The current event cursor, read from the cheap events endpoint. Core's events *snapshot*
     * endpoint builds every room's device list just to return the same number, which stalls Core.
     */
    suspend fun currentEventCursor(pathTemplate: String): String? {
        val root = request(eventPath(pathTemplate, "0", longPoll = false) + "&limit=1")
        return root.optString("cursor").takeIf(String::isNotBlank)
    }

    /** Long poll: the server holds the request for up to 25 seconds. */
    suspend fun events(pathTemplate: String, cursor: String?): PilotEventPage =
        PilotJson.events(request(eventPath(pathTemplate, cursor, longPoll = true)))

    internal fun eventPath(pathTemplate: String, cursor: String?, longPoll: Boolean): String {
        val resolved = pathTemplate
            .replace("{id}", config.deviceId)
            .replace("{device_id}", config.deviceId)
            .trimStart('/')
        val parameters = buildList {
            cursor?.takeIf(String::isNotBlank)?.let { add("cursor=${encode(it)}") }
            if (longPoll) add("timeout_seconds=25")
        }
        if (parameters.isEmpty()) return resolved
        val separator = if ('?' in resolved) '&' else '?'
        return "$resolved$separator${parameters.joinToString("&")}"
    }

    suspend fun home(roomId: String): HomeProjection =
        PilotJson.home(request("$device/home?room_id=${encode(roomId)}"))

    /** @param option a text parameter instead of [value], e.g. the mode for `set_hvac_mode`. */
    suspend fun homeAction(
        roomId: String,
        entityId: String,
        action: String,
        value: Double? = null,
        option: String? = null,
    ): HomeAction = PilotJson.homeAction(
        request("$device/home/actions", "POST", homeActionBody(roomId, entityId, action, value, option)),
    )

    suspend fun confirmHomeAction(actionId: String): HomeAction =
        PilotJson.homeAction(request("$device/home/actions/$actionId/confirm", "POST", JSONObject()))

    suspend fun mediaCommand(command: MediaCommand) {
        request("$device/media", "POST", mediaCommandBody(command))
    }

    suspend fun search(query: String): List<MusicSearchResult> {
        val body = JSONObject().put("query", query).put("limit", 30).put("library_only", false)
        return PilotJson.search(request("$device/media/search", "POST", body))
    }

    suspend fun dashboardAction(action: String, value: String) {
        request("$device/dashboard/actions", "POST", JSONObject().put("action", action).put("value", value))
    }

    suspend fun ask(text: String, roomId: String, conversationId: String?): AssistantReply {
        val body = JSONObject().put("text", text).put("language", LANGUAGE).put("room_id", roomId)
        conversationId?.let { body.put("conversation_id", it) }
        return PilotJson.assistant(request("$device/assistant", "POST", body))
    }

    /** Uploads raw 16-bit mono PCM. */
    suspend fun voice(pcm: ByteArray, sampleRate: Int = 16_000, conversationId: String? = null): AssistantReply {
        val request = authorised("$device/voice")
            .header("X-Pilot-Sample-Rate", sampleRate.toString())
            .header("X-Pilot-Language", LANGUAGE)
            .apply { conversationId?.let { header("X-Pilot-Conversation-ID", it) } }
            .post(pcm.toRequestBody("application/octet-stream".toMediaType()))
            .build()
        return PilotJson.assistant(parseJsonObject(http.pilot.await(request) { it.textOrThrow() }))
    }

    /** Spoken reply audio. Only ever fetched from the paired Core, with the device token. */
    suspend fun audioAsset(path: String): ByteArray {
        val relative = if (path.startsWith("http://") || path.startsWith("https://")) {
            require(sameOrigin(path)) { "Pilot audio must come from the paired Pilot Core" }
            path.removePrefix(base)
        } else path.trimStart('/')
        return http.pilot.await(authorised(relative).get().build()) { it.bytesOrThrow(Int.MAX_VALUE) }
    }

    /**
     * Artwork bytes (max 8 MB). Core-hosted artwork is fetched with the device token; anything
     * else is fetched anonymously so the token never leaves the paired Core.
     */
    suspend fun artworkAsset(path: String): ByteArray {
        val absolute = if (path.startsWith("http://") || path.startsWith("https://")) path else base + path.trimStart('/')
        return if (sameOrigin(absolute)) {
            val request = authorised(absolute.removePrefix(base)).header("Accept", "image/*").get().build()
            http.pilot.await(request) { it.bytesOrThrow(MAX_ARTWORK_BYTES) }
        } else {
            val request = Request.Builder().url(absolute).header("Accept", "image/*").get().build()
            http.external.await(request) { it.bytesOrThrow(MAX_ARTWORK_BYTES) }
        }
    }

    /** Confirms the address, device ID and token work. Returns the device ID Core reports. */
    suspend fun testConnection(): String =
        request("$device/media").optString("device_id", config.deviceId)

    private fun sameOrigin(url: String): Boolean = runCatching {
        val candidate = URI(url).toURL()
        val core = URI(base).toURL()
        candidate.protocol == core.protocol && candidate.host == core.host && candidate.port == core.port
    }.getOrDefault(false)

    private fun authorised(path: String): Request.Builder = Request.Builder()
        .url(base + path.trimStart('/'))
        .header("Accept", "application/json")
        .header("Authorization", "Bearer $token")
        .header("X-Pilot-Device-ID", config.deviceId)

    private suspend fun request(path: String, method: String = "GET", body: JSONObject? = null): JSONObject {
        val request = authorised(path).method(method, if (method == "GET") null else jsonBody(body)).build()
        return parseJsonObject(retryRead(method) { http.pilot.await(request) { it.textOrThrow() } })
    }

    companion object {
        private const val LANGUAGE = "en-AU"
        const val MAX_ARTWORK_BYTES = 8 * 1024 * 1024

        private fun encode(value: String) = URLEncoder.encode(value, Charsets.UTF_8.name())

        internal fun homeActionBody(
            roomId: String,
            entityId: String,
            action: String,
            value: Double?,
            option: String? = null,
        ): JSONObject {
            val parameters = JSONObject()
            value?.let { parameters.put("value", it) }
            if (value == null) option?.let { parameters.put("value", it) }
            return JSONObject()
                .put("room_id", roomId)
                .put("entity_id", entityId)
                .put("action", action)
                .put("parameters", parameters)
        }

        internal fun mediaCommandBody(command: MediaCommand): JSONObject = JSONObject().apply {
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

        /**
         * Exchanges a single-use grant for this phone's device identity:
         * `POST v1/devices/bootstrap` with the grant as the bearer token and an empty body.
         */
        suspend fun redeemBootstrap(http: HttpClients, coreUrl: String, grantToken: String): BootstrapRegistration {
            val request = Request.Builder()
                .url(AddressPolicy.normalize(coreUrl) + "v1/devices/bootstrap")
                .header("Accept", "application/json")
                .header("Authorization", "Bearer ${grantToken.trim()}")
                .post(ByteArray(0).toRequestBody(null))
                .build()
            return PilotJson.bootstrap(parseJsonObject(http.pilot.await(request) { it.textOrThrow() }))
        }

        private fun Response.bytesOrThrow(limit: Int): ByteArray {
            if (!isSuccessful) throw HttpFailure(code, serverDetail(body.string()))
            val declared = body.contentLength()
            require(declared < 0 || declared <= limit) { "Artwork is too large" }
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(16_384)
            body.byteStream().use { input ->
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    output.write(buffer, 0, count)
                    require(output.size() <= limit) { "Artwork is too large" }
                }
            }
            return output.toByteArray()
        }
    }
}
