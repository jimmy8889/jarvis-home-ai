package com.jarvis.pilottv

import java.io.IOException
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

class PilotCoreException(
    message: String,
    val statusCode: Int? = null,
) : IOException(message)

data class CoreConnection(
    val baseUrl: String,
    val token: String,
) {
    fun normalizedBaseUrl(): String = baseUrl.trim().removeSuffix("/")

    fun validate(): String? {
        if (token.isBlank()) return "Administrator token is required."
        val uri = runCatching { URI(normalizedBaseUrl()) }.getOrNull()
            ?: return "Pilot Core address is invalid."
        if (uri.host.isNullOrBlank()) return "Pilot Core address needs a host."
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

class PilotCoreClient(
    private val connection: CoreConnection,
) {
    suspend fun operations(): OperationsSnapshot = withContext(Dispatchers.IO) {
        val validationError = connection.validate()
        if (validationError != null) throw PilotCoreException(validationError)
        val url = URL("${connection.normalizedBaseUrl()}/v1/operations")
        val request = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 8_000
            readTimeout = 12_000
            useCaches = false
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Authorization", "Bearer ${connection.token}")
        }
        try {
            val status = request.responseCode
            if (status !in 200..299) {
                val detail = runCatching {
                    request.errorStream?.bufferedReader()?.use { it.readText() }
                }.getOrNull()
                val message = when (status) {
                    401 -> "Pilot Core rejected the administrator token."
                    else -> "Pilot Core returned HTTP $status${detail?.let { ": $it" } ?: ""}"
                }
                throw PilotCoreException(message, status)
            }
            val body = request.inputStream.bufferedReader().use { it.readText() }
            OperationsParser.parse(JSONObject(body))
        } finally {
            request.disconnect()
        }
    }
}

internal object OperationsParser {
    private val sourceOrder = listOf(
        "critical",
        "assistant",
        "bluetooth",
        "airplay",
        "music",
    )

    fun parse(root: JSONObject): OperationsSnapshot {
        val deployment = root.getJSONObject("deployment")
        val summary = root.getJSONObject("summary")
        val safety = root.getJSONObject("safety")
        val mediaPlayers = root.optJSONObject("media")
            ?.optJSONObject("players")
            ?: JSONObject()

        return OperationsSnapshot(
            generatedAt = root.optString("generated_at"),
            deployment = DeploymentInfo(
                version = deployment.optString("version", "unknown"),
                release = deployment.optString("release", "development"),
                uptimeSeconds = deployment.optDouble("uptime_seconds", 0.0).toLong(),
            ),
            summary = SystemSummary(
                roomCount = summary.optInt("room_count"),
                deviceCount = summary.optInt("device_count"),
                connectedDeviceCount = summary.optInt("connected_device_count"),
                configuredIntegrationCount = summary.optInt("configured_integration_count"),
                healthyIntegrationCount = summary.optInt("healthy_integration_count"),
                armedRoomCount = summary.optInt("armed_room_count"),
                unarmedRoomCount = summary.optInt("unarmed_room_count"),
                pendingCommandCount = summary.optInt("pending_command_count"),
            ),
            safety = SafetyState(
                audibleActionsGated = safety.optBoolean("audible_actions_gated", true),
                armedRooms = safety.optJSONArray("armed_rooms").strings(),
                unarmedRooms = safety.optJSONArray("unarmed_rooms").strings(),
            ),
            integrations = parseIntegrations(root.optJSONObject("integrations")),
            rooms = parseRooms(root.optJSONObject("rooms"), mediaPlayers),
        )
    }

    private fun parseIntegrations(values: JSONObject?): List<IntegrationState> =
        values.keysList().map { id ->
            val value = values?.optJSONObject(id) ?: JSONObject()
            IntegrationState(
                id = id,
                status = value.optString("status", "unknown"),
                configured = value.optBoolean("configured", false),
                latencyMs = value.nullableLong("latency_ms"),
            )
        }

    private fun parseRooms(
        values: JSONObject?,
        mediaPlayers: JSONObject,
    ): List<RoomState> = values.keysList().map { roomId ->
        val state = values?.optJSONObject(roomId) ?: JSONObject()
        val room = state.optJSONObject("room") ?: JSONObject()
        val devices = state.optJSONArray("devices").objects().map { device ->
            val health = device.optJSONObject("health")?.optJSONObject("payload")
            EndpointState(
                id = device.optString("id"),
                name = device.optString("name", device.optString("id")),
                connected = device.optBoolean("connected"),
                ready = health.nullableBoolean("ready"),
                uptimeSeconds = health.nullableLong("uptime_seconds"),
            )
        }
        val players = room.optJSONArray("players").objects().map { player ->
            parsePlayer(player, mediaPlayers.optJSONObject(player.optString("id")))
        }
        val sourcesObject = state.optJSONObject("sources")
        val sources = sourceOrder.map { source ->
            SourceState(
                id = source,
                active = sourcesObject
                    ?.optJSONObject(source)
                    ?.optBoolean("active")
                    ?: false,
            )
        }
        val foreground = state.optJSONObject("focus")
            ?.optString("foreground")
            ?.takeIf(String::isNotBlank)
        RoomState(
            id = room.optString("id", roomId),
            name = room.optString("name", roomId),
            armed = devices.any { it.connected && it.ready == true } &&
                devices.any { device ->
                    val raw = state.optJSONArray("devices").objects()
                        .firstOrNull { it.optString("id") == device.id }
                    raw?.optJSONObject("health")
                        ?.optJSONObject("payload")
                        ?.optJSONObject("audio_activation")
                        ?.optBoolean("allowed") == true
                },
            foregroundSource = foreground,
            devices = devices,
            players = players,
            sources = sources,
        )
    }

    private fun parsePlayer(
        player: JSONObject,
        state: JSONObject?,
    ): PlayerState {
        val effective = state?.optJSONObject("effective")
        val media = effective?.optJSONObject("media")
        return PlayerState(
            id = player.optString("id"),
            name = player.optString("name", player.optString("id")),
            kind = player.optString("kind"),
            protocol = player.optString("protocol"),
            controlEnabled = player.optBoolean("control_enabled", true),
            status = state?.optString("status", "unresolved") ?: "unresolved",
            available = effective.nullableBoolean("available"),
            powered = effective.nullableBoolean("powered"),
            playbackState = effective.nullableString("playback_state"),
            volumePercent = effective.nullableInt("volume_percent"),
            muted = effective.nullableBoolean("muted"),
            source = effective.nullableString("source"),
            media = media?.let {
                MediaDescription(
                    title = it.nullableString("title"),
                    artist = it.nullableString("artist"),
                    album = it.nullableString("album"),
                )
            },
        )
    }
}

private fun JSONObject?.keysList(): List<String> {
    if (this == null) return emptyList()
    return keys().asSequence().toList().sorted()
}

private fun JSONArray?.objects(): List<JSONObject> {
    if (this == null) return emptyList()
    return (0 until length()).mapNotNull { optJSONObject(it) }
}

private fun JSONArray?.strings(): List<String> {
    if (this == null) return emptyList()
    return (0 until length()).mapNotNull { index ->
        optString(index).takeIf(String::isNotBlank)
    }
}

private fun JSONObject?.nullableBoolean(key: String): Boolean? =
    if (this == null || isNull(key)) null else optBoolean(key)

private fun JSONObject?.nullableInt(key: String): Int? =
    if (this == null || isNull(key)) null else optInt(key)

private fun JSONObject?.nullableLong(key: String): Long? =
    if (this == null || isNull(key)) null else optDouble(key).toLong()

private fun JSONObject?.nullableString(key: String): String? =
    if (this == null || isNull(key)) null else optString(key).takeIf(String::isNotBlank)
