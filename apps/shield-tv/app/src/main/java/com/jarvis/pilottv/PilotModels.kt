package com.jarvis.pilottv

import java.time.Instant
import org.json.JSONArray
import org.json.JSONObject

const val PILOT_CLIENT_SCHEMA = "pilot.client.v1"

data class DeviceCredentials(
    val baseUrl: String,
    val deviceId: String,
    val token: String,
)

data class DeviceManifest(
    val schemaVersion: String,
    val coreVersion: String?,
    val registryRevision: String?,
    val deviceId: String,
    val deviceName: String,
    val roomId: String,
    val roomName: String,
    val capabilities: Set<String>,
    val featureFlags: Set<String>,
    val eventCursor: Long?,
) {
    fun supports(capability: String): Boolean = capability in capabilities
}

data class MediaDescription(
    val title: String?,
    val artist: String?,
    val album: String?,
    val artworkUrl: String?,
    val uri: String?,
)

data class QueueItem(
    val id: String,
    val title: String,
    val subtitle: String?,
    val artworkUrl: String?,
    val active: Boolean,
)

data class PlayerState(
    val id: String,
    val roomId: String,
    val name: String,
    val kind: String,
    val protocol: String,
    val controlEnabled: Boolean,
    val status: String,
    val available: Boolean,
    val powered: Boolean?,
    val playbackState: String?,
    val volumePercent: Int?,
    val muted: Boolean?,
    val source: String?,
    val media: MediaDescription?,
    val positionSeconds: Double?,
    val durationSeconds: Double?,
    val capabilities: Set<String>,
    val queue: List<QueueItem>,
    val groupMembers: List<String>,
) {
    val progress: Float?
        get() = if (
            positionSeconds != null &&
            durationSeconds != null &&
            durationSeconds > 0
        ) {
            (positionSeconds / durationSeconds).toFloat().coerceIn(0f, 1f)
        } else {
            null
        }

    fun can(action: String): Boolean = controlEnabled &&
        (capabilities.isEmpty() || action in capabilities)
}

data class RoomState(
    val id: String,
    val name: String,
    val defaultMusicPlayerId: String?,
    val responsePlayerId: String?,
    val players: List<PlayerState>,
)

data class EnergyMeasurement(
    val value: Double?,
    val unit: String,
    val direction: String?,
) {
    fun display(): String = value?.let {
        when {
            unit == "%" -> "%.0f%%".format(it)
            unit == "W" && kotlin.math.abs(it) >= 1_000 -> "%.1f kW".format(it / 1_000)
            unit.isNotBlank() -> "%.0f %s".format(it, unit)
            else -> "%.1f".format(it)
        }
    } ?: "—"
}

data class EnergyState(
    val status: String,
    val solar: EnergyMeasurement,
    val homeLoad: EnergyMeasurement,
    val grid: EnergyMeasurement,
    val battery: EnergyMeasurement,
    val batterySoc: EnergyMeasurement,
)

data class HomeEntity(
    val id: String,
    val name: String,
    val state: String,
    val category: String,
    val section: String,
    val priority: Int,
    val icon: String?,
    val unavailable: Boolean,
)

data class HomeState(
    val roomId: String?,
    val roomName: String?,
    val entities: List<HomeEntity>,
)

data class PilotTvSnapshot(
    val schemaVersion: String,
    val revision: Long?,
    val cursor: Long?,
    val generatedAt: Instant?,
    val manifest: DeviceManifest,
    val rooms: List<RoomState>,
    val energy: EnergyState?,
    val home: HomeState?,
    val stale: Boolean = false,
) {
    val players: List<PlayerState> get() = rooms.flatMap(RoomState::players)

    val nowPlaying: PlayerState?
        get() = players.firstOrNull { it.playbackState == "playing" }
            ?: players.firstOrNull { it.media?.title != null }
}

data class MediaCommand(
    val action: String,
    val playerId: String? = null,
    val volume: Int? = null,
    val positionSeconds: Double? = null,
    val muted: Boolean? = null,
    val targetRoomId: String? = null,
    val targetPlayerId: String? = null,
    val mediaUri: String? = null,
)

internal object PilotJson {
    fun manifest(root: JSONObject, credentials: DeviceCredentials): DeviceManifest {
        val device = root.optJSONObject("device") ?: JSONObject()
        val room = root.optJSONObject("room") ?: JSONObject()
        val realtime = root.optJSONObject("realtime") ?: JSONObject()
        return DeviceManifest(
            schemaVersion = root.optString("schema_version", PILOT_CLIENT_SCHEMA),
            coreVersion = root.nullableString("core_version"),
            registryRevision = root.nullableString("registry_revision"),
            deviceId = device.optString("id", credentials.deviceId),
            deviceName = device.optString("name", "Pilot TV"),
            roomId = room.optString("id", device.optString("room_id")),
            roomName = room.optString("name", "Media Room"),
            capabilities = device.optJSONArray("capabilities").strings().toSet(),
            featureFlags = root.optJSONObject("features")?.keysList()
                ?.filter { root.optJSONObject("features")?.optBoolean(it) == true }
                ?.toSet()
                ?: emptySet(),
            eventCursor = realtime.nullableLong("cursor"),
        )
    }

    fun snapshot(
        manifest: DeviceManifest,
        mediaRoot: JSONObject,
        surfaceRoot: JSONObject?,
        homeRoot: JSONObject?,
        envelope: JSONObject? = null,
    ): PilotTvSnapshot {
        val mediaForParsing = JSONObject(mediaRoot.toString())
        envelope?.optJSONObject("media")?.let { mediaForParsing.put("media", it) }
        val embeddedEnergy = envelope?.optJSONObject("energy")
            ?: surfaceRoot?.optJSONObject("energy")
        val rawHome = envelope?.optJSONObject("home") ?: homeRoot
        val embeddedHome = rawHome?.optJSONObject("rooms")
            ?.optJSONObject(manifest.roomId)
            ?: rawHome
        val rooms = parseRooms(mediaForParsing)
        return PilotTvSnapshot(
            schemaVersion = envelope?.optString("schema_version", manifest.schemaVersion)
                ?: manifest.schemaVersion,
            revision = envelope.nullableLong("revision"),
            cursor = envelope.nullableLong("cursor") ?: manifest.eventCursor,
            generatedAt = envelope?.nullableString("generated_at")
                ?.let { runCatching { Instant.parse(it) }.getOrNull() }
                ?: mediaRoot.optJSONObject("media")?.nullableString("observed_at")
                    ?.let { runCatching { Instant.parse(it) }.getOrNull() },
            manifest = manifest,
            rooms = rooms,
            energy = embeddedEnergy?.let(::energy),
            home = embeddedHome?.let(::home),
        )
    }

    private fun parseRooms(root: JSONObject): List<RoomState> {
        val roomRows = root.optJSONArray("rooms").objects()
        val media = root.optJSONObject("media") ?: root
        val stateRows = media.optJSONObject("players")?.objectsWithKeys().orEmpty()
            .associate { (id, value) -> id to playerState(value, id) }
        if (roomRows.isEmpty()) {
            return stateRows.values.groupBy(PlayerState::roomId).map { (roomId, players) ->
                RoomState(
                    id = roomId,
                    name = roomId.displayName(),
                    defaultMusicPlayerId = players.firstOrNull()?.id,
                    responsePlayerId = null,
                    players = players,
                )
            }
        }
        return roomRows.map { room ->
            val configuredPlayers = room.optJSONArray("players").objects().map { configured ->
                val id = configured.optString("id")
                stateRows[id] ?: playerState(configured, id)
            }
            RoomState(
                id = room.optString("id"),
                name = room.optString("name", room.optString("id").displayName()),
                defaultMusicPlayerId = room.nullableString("default_music_player_id"),
                responsePlayerId = room.nullableString("response_player_id"),
                players = configuredPlayers,
            )
        }
    }

    private fun playerState(value: JSONObject, fallbackId: String): PlayerState {
        val player = value.optJSONObject("player") ?: value
        val effective = value.optJSONObject("effective") ?: value
        val media = effective.optJSONObject("media")
            ?: effective.optJSONObject("now_playing")
        val queueObject = effective.optJSONObject("queue") ?: value.optJSONObject("queue")
        val activeIndex = queueObject?.optInt("index", -1) ?: -1
        return PlayerState(
            id = player.optString("id", fallbackId),
            roomId = player.optString("room_id"),
            name = player.optString("name", fallbackId.displayName()),
            kind = player.optString("kind", "music"),
            protocol = player.optString("protocol"),
            controlEnabled = player.optBoolean("control_enabled", true),
            status = value.optString("status", "unknown"),
            available = effective.optBoolean("available", true),
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
                    artworkUrl = it.nullableString("artwork_url")
                        ?: it.nullableString("image_url")
                        ?: it.optJSONObject("artwork")?.nullableString("proxy_url")
                        ?: it.optJSONObject("artwork")?.nullableString("source_url")
                        ?: it.optJSONObject("artwork")?.nullableString("url"),
                    uri = it.nullableString("uri") ?: it.nullableString("media_uri"),
                )
            },
            positionSeconds = effective.nullableDouble("position_seconds"),
            durationSeconds = effective.nullableDouble("duration_seconds"),
            capabilities = (
                value.optJSONObject("capabilities")?.optJSONArray("actions")
                    ?: value.optJSONArray("capabilities")
                    ?: player.optJSONArray("capabilities")
                    ?: effective.optJSONArray("capabilities")
                ).strings().toSet(),
            queue = queueObject?.optJSONArray("items").objects().mapIndexed { index, item ->
                QueueItem(
                    id = item.optString("id", item.optString("uri", index.toString())),
                    title = item.optString("title", item.optString("name", "Untitled")),
                    subtitle = item.nullableString("artist") ?: item.nullableString("album"),
                    artworkUrl = item.nullableString("artwork_url")
                        ?: item.nullableString("image_url")
                        ?: item.optJSONObject("artwork")?.nullableString("proxy_url")
                        ?: item.optJSONObject("artwork")?.nullableString("source_url"),
                    active = item.optBoolean("active", index == activeIndex),
                )
            }.orEmpty(),
            groupMembers = (
                effective.optJSONArray("group_members")
                    ?: value.optJSONArray("group_members")
                    ?: value.optJSONObject("music_assistant")?.optJSONArray("group_members")
                ).strings(),
        )
    }

    private fun energy(value: JSONObject): EnergyState = EnergyState(
        status = value.optString("status", "partial"),
        solar = measurement(value.optJSONObject("solar")),
        homeLoad = measurement(value.optJSONObject("home_load")),
        grid = measurement(value.optJSONObject("grid")),
        battery = measurement(value.optJSONObject("battery")),
        batterySoc = measurement(value.optJSONObject("battery_soc")),
    )

    private fun measurement(value: JSONObject?): EnergyMeasurement = EnergyMeasurement(
        value = value.nullableDouble("value"),
        unit = value?.optString("unit") ?: "",
        direction = value.nullableString("direction"),
    )

    private fun home(root: JSONObject): HomeState {
        val room = root.optJSONObject("room")
        val entities = root.optJSONArray("entities").objects().mapNotNull { entity ->
            val presentation = entity.optJSONObject("presentation") ?: JSONObject()
            if (presentation.has("included") && !presentation.optBoolean("included")) {
                return@mapNotNull null
            }
            HomeEntity(
                id = entity.optString("entity_id"),
                name = presentation.optString(
                    "display_name",
                    entity.optString("name", entity.optString("entity_id").displayName()),
                ),
                state = entity.optString("state"),
                category = presentation.optString("category", entity.optString("domain")),
                section = presentation.optString("section", "room"),
                priority = presentation.optInt("priority", 50),
                icon = presentation.nullableString("icon"),
                unavailable = entity.optBoolean("unavailable"),
            )
        }.sortedBy(HomeEntity::priority)
        return HomeState(
            roomId = room?.nullableString("id") ?: root.nullableString("selected_room_id"),
            roomName = room?.nullableString("name"),
            entities = entities,
        )
    }
}

private fun JSONArray?.objects(): List<JSONObject> =
    if (this == null) emptyList() else (0 until length()).mapNotNull(::optJSONObject)

private fun JSONArray?.strings(): List<String> =
    if (this == null) emptyList() else (0 until length()).mapNotNull {
        optString(it).takeIf(String::isNotBlank)
    }

private fun JSONObject?.objectsWithKeys(): List<Pair<String, JSONObject>> =
    if (this == null) emptyList() else keys().asSequence().mapNotNull { key ->
        optJSONObject(key)?.let { key to it }
    }.toList()

private fun JSONObject.keysList(): List<String> = keys().asSequence().toList()

private fun JSONObject?.nullableString(key: String): String? =
    if (this == null || !has(key) || isNull(key)) null else optString(key).takeIf(String::isNotBlank)

private fun JSONObject?.nullableBoolean(key: String): Boolean? =
    if (this == null || !has(key) || isNull(key)) null else optBoolean(key)

private fun JSONObject?.nullableInt(key: String): Int? =
    if (this == null || !has(key) || isNull(key)) null else optInt(key)

private fun JSONObject?.nullableLong(key: String): Long? =
    if (this == null || !has(key) || isNull(key)) null else optLong(key)

private fun JSONObject?.nullableDouble(key: String): Double? =
    if (this == null || !has(key) || isNull(key)) null else optDouble(key).takeIf(Double::isFinite)

private fun String.displayName(): String = replace('-', ' ')
    .replace('_', ' ')
    .split(' ')
    .joinToString(" ") { it.replaceFirstChar(Char::uppercase) }
