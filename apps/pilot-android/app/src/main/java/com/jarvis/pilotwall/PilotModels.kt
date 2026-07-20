package com.jarvis.pilotwall

import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant

data class PilotConfig(
    val coreUrl: String = "http://10.0.1.64:8770/",
    val deviceId: String = "pilot-wall-tablet",
    val refreshSeconds: Int = 15,
    val keepScreenOn: Boolean = true,
    val nightMode: NightMode = NightMode.Automatic,
)

enum class NightMode { Automatic, Day, Night }

enum class ConnectionState { Unconfigured, Loading, Online, Stale, Offline }

data class PilotRoom(
    val id: String,
    val name: String,
    val responsePlayerId: String?,
    val defaultMusicPlayerId: String?,
    val players: List<PilotPlayer>,
)

data class PilotPlayer(
    val id: String,
    val roomId: String,
    val name: String,
    val kind: String,
    val protocol: String,
    val enabled: Boolean,
    val controlEnabled: Boolean,
)

data class CurrentMedia(
    val title: String?,
    val artist: String?,
    val album: String?,
    val imageUrl: String?,
)

data class EffectiveMediaState(
    val available: Boolean,
    val powered: Boolean?,
    val playbackState: String?,
    val volumePercent: Int?,
    val muted: Boolean?,
    val source: String?,
    val media: CurrentMedia?,
)

data class PilotPlayerState(
    val player: PilotPlayer,
    val status: String,
    val effective: EffectiveMediaState,
)

data class MediaSnapshot(
    val observedAt: Instant?,
    val rooms: List<PilotRoom>,
    val players: List<PilotPlayerState>,
)

data class EnergyMeasurement(
    val value: Double?,
    val unit: String,
    val direction: String?,
    val observedAt: Instant?,
) {
    fun display(): String = value?.let {
        if (unit == "W" && kotlin.math.abs(it) >= 1000) "%.1f kW".format(it / 1000.0)
        else if (unit == "%") "%.0f%%".format(it)
        else "%.0f %s".format(it, unit)
    } ?: "—"
}

data class EnergySnapshot(
    val status: String,
    val solar: EnergyMeasurement,
    val grid: EnergyMeasurement,
    val battery: EnergyMeasurement,
    val batterySoc: EnergyMeasurement,
    val homeLoad: EnergyMeasurement,
)

data class SurfaceSnapshot(
    val serverTime: Instant?,
    val energy: EnergySnapshot?,
    val nowPlaying: List<PilotPlayerState>,
)

data class MusicSearchResult(
    val id: String,
    val title: String,
    val subtitle: String,
    val uri: String,
    val mediaType: String?,
)

data class AssistantReply(
    val text: String,
    val conversationId: String?,
    val provider: String?,
    val continueConversation: Boolean,
    val roomId: String?,
)

data class ChatMessage(
    val id: Long,
    val role: ChatRole,
    val text: String,
    val pending: Boolean = false,
)

enum class ChatRole { User, Pilot }

data class PilotSnapshot(
    val media: MediaSnapshot,
    val surface: SurfaceSnapshot,
    val receivedAt: Instant = Instant.now(),
)

data class MediaCommand(
    val action: String,
    val playerId: String? = null,
    val mediaUri: String? = null,
    val targetRoomId: String? = null,
    val targetPlayerId: String? = null,
    val volume: Int? = null,
)

data class HomeEntity(
    val entityId: String,
    val domain: String,
    val name: String,
    val state: String,
    val areaId: String?,
    val unavailable: Boolean,
    val stale: Boolean,
    val actions: List<String>,
    val brightnessPercent: Float?,
) {
    val isOn: Boolean
        get() = state.lowercase() in setOf(
            "on", "open", "opening", "unlocked", "active", "heat", "cool",
        )
}

data class HomeProjection(
    val roomId: String,
    val roomName: String,
    val entities: List<HomeEntity>,
)

data class HomeAction(
    val id: String,
    val status: String,
    val entityId: String,
    val action: String,
    val risk: String,
    val confirmationRequired: Boolean,
    val description: String?,
)

internal object PilotJson {
    fun home(root: JSONObject): HomeProjection {
        val room = root.optJSONObject("room") ?: JSONObject()
        return HomeProjection(
            roomId = room.optString("id", root.optString("selected_room_id")),
            roomName = room.optString("name", "Room"),
            entities = root.optJSONArray("entities").objects().map { entity ->
                val attributes = entity.optJSONObject("attributes") ?: JSONObject()
                HomeEntity(
                    entityId = entity.optString("entity_id"),
                    domain = entity.optString("domain"),
                    name = entity.optString("name", entity.optString("entity_id")),
                    state = entity.optString("state"),
                    areaId = entity.optNullableString("area_id"),
                    unavailable = entity.optBoolean("unavailable"),
                    stale = entity.optBoolean("stale"),
                    actions = entity.optJSONArray("actions").strings(),
                    brightnessPercent = attributes.optDouble("brightness")
                        .takeIf { attributes.has("brightness") && it.isFinite() }
                        ?.div(255.0)?.times(100)?.toFloat()?.coerceIn(0f, 100f),
                )
            },
        )
    }

    fun homeAction(root: JSONObject): HomeAction {
        val action = root.optJSONObject("action") ?: root
        return HomeAction(
            id = action.optString("id"),
            status = action.optString("status"),
            entityId = action.optString("entity_id"),
            action = action.optString("action"),
            risk = action.optString("risk", "low"),
            confirmationRequired = action.optBoolean("confirmation_required"),
            description = action.optNullableString("description"),
        )
    }

    fun media(root: JSONObject): MediaSnapshot {
        val rooms = root.optJSONArray("rooms").objects().map(::room)
        val media = root.optJSONObject("media") ?: JSONObject()
        val states = media.optJSONObject("players").objectsWithKeys().map { (id, value) ->
            playerState(value, id)
        }
        return MediaSnapshot(
            observedAt = media.optInstant("observed_at"),
            rooms = rooms,
            players = states,
        )
    }

    fun surface(root: JSONObject): SurfaceSnapshot {
        val nowPlayingValue = root.opt("now_playing")
        val nowPlaying = when (nowPlayingValue) {
            is JSONArray -> nowPlayingValue.objects().map { playerState(it) }
            is JSONObject -> {
                val players = nowPlayingValue.optJSONObject("players") ?: nowPlayingValue
                players.objectsWithKeys().map { (id, value) -> playerState(value, id) }
            }
            else -> emptyList()
        }
        return SurfaceSnapshot(
            serverTime = root.optInstant("server_time"),
            energy = root.optJSONObject("energy")?.takeUnless {
                it.optString("status") in setOf("not_configured", "unavailable")
            }?.let(::energy),
            nowPlaying = nowPlaying,
        )
    }

    fun assistant(root: JSONObject) = AssistantReply(
        text = root.optString("response_text", "I couldn't prepare a response."),
        conversationId = root.optNullableString("conversation_id"),
        provider = root.optNullableString("provider"),
        continueConversation = root.optBoolean("continue_conversation", false),
        roomId = root.optNullableString("room_id"),
    )

    fun search(value: Any?): List<MusicSearchResult> {
        val output = linkedMapOf<String, MusicSearchResult>()
        fun visit(item: Any?) {
            when (item) {
                is JSONArray -> (0 until item.length()).forEach { visit(item.opt(it)) }
                is JSONObject -> {
                    val uri = item.optNullableString("uri")
                        ?: item.optNullableString("media_uri")
                    val title = item.optNullableString("name")
                        ?: item.optNullableString("title")
                    if (uri != null && title != null) {
                        output.putIfAbsent(
                            uri,
                            MusicSearchResult(
                                id = uri,
                                title = title,
                                subtitle = item.optNullableString("artist")
                                    ?: item.optNullableString("album")
                                    ?: item.optNullableString("media_type")
                                    ?: "",
                                uri = uri,
                                mediaType = item.optNullableString("media_type"),
                            ),
                        )
                    } else {
                        item.keys().forEach { visit(item.opt(it)) }
                    }
                }
            }
        }
        visit(value)
        return output.values.take(40)
    }

    private fun room(value: JSONObject) = PilotRoom(
        id = value.optString("id"),
        name = value.optString("name"),
        responsePlayerId = value.optNullableString("response_player_id"),
        defaultMusicPlayerId = value.optNullableString("default_music_player_id"),
        players = value.optJSONArray("players").objects().map(::player),
    )

    private fun player(value: JSONObject, fallbackId: String = "") = PilotPlayer(
        id = value.optString("id", fallbackId),
        roomId = value.optString("room_id"),
        name = value.optString("name", value.optString("id", fallbackId)),
        kind = value.optString("kind"),
        protocol = value.optString("protocol"),
        enabled = value.optBoolean("enabled", true),
        controlEnabled = value.optBoolean("control_enabled", false),
    )

    private fun playerState(value: JSONObject, fallbackId: String = ""): PilotPlayerState {
        val player = player(value.optJSONObject("player") ?: value, fallbackId)
        val effective = value.optJSONObject("effective") ?: value
        return PilotPlayerState(
            player = player,
            status = value.optString("status", "unknown"),
            effective = EffectiveMediaState(
                available = effective.optBoolean("available", true),
                powered = effective.optNullableBoolean("powered"),
                playbackState = effective.optNullableString("playback_state"),
                volumePercent = effective.optNullableInt("volume_percent"),
                muted = effective.optNullableBoolean("muted"),
                source = effective.optNullableString("source"),
                media = effective.optJSONObject("media")?.let {
                    CurrentMedia(
                        title = it.optNullableString("title"),
                        artist = it.optNullableString("artist"),
                        album = it.optNullableString("album"),
                        imageUrl = it.optNullableString("image_url")
                            ?: it.optNullableString("image"),
                    )
                },
            ),
        )
    }

    private fun energy(value: JSONObject) = EnergySnapshot(
        status = value.optString("status", "partial"),
        solar = measurement(value.optJSONObject("solar")),
        grid = measurement(value.optJSONObject("grid")),
        battery = measurement(value.optJSONObject("battery")),
        batterySoc = measurement(value.optJSONObject("battery_soc")),
        homeLoad = measurement(value.optJSONObject("home_load")),
    )

    private fun measurement(value: JSONObject?) = EnergyMeasurement(
        value = value?.optDouble("value")?.takeIf { it.isFinite() },
        unit = value?.optString("unit", "") ?: "",
        direction = value?.optNullableString("direction"),
        observedAt = value?.optInstant("observed_at"),
    )
}

private fun JSONArray?.objects(): List<JSONObject> =
    if (this == null) emptyList() else (0 until length()).mapNotNull { optJSONObject(it) }

private fun JSONArray?.strings(): List<String> =
    if (this == null) emptyList() else (0 until length()).mapNotNull {
        optString(it).takeIf(String::isNotBlank)
    }

private fun JSONObject?.objectsWithKeys(): List<Pair<String, JSONObject>> =
    if (this == null) emptyList() else keys().asSequence().mapNotNull { key ->
        optJSONObject(key)?.let { key to it }
    }.toList()

private fun JSONObject.optNullableString(key: String): String? =
    optString(key).takeIf { has(key) && !isNull(key) && it.isNotBlank() }

private fun JSONObject.optNullableInt(key: String): Int? =
    if (has(key) && !isNull(key)) optInt(key) else null

private fun JSONObject.optNullableBoolean(key: String): Boolean? =
    if (has(key) && !isNull(key)) optBoolean(key) else null

private fun JSONObject.optInstant(key: String): Instant? =
    optNullableString(key)?.let { runCatching { Instant.parse(it) }.getOrNull() }
