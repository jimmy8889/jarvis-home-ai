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
    val kioskMode: Boolean = true,
    val ambientAfterMinutes: Int = 5,
    val displayBrightnessPercent: Int = 70,
)

enum class NightMode { Automatic, Day, Night }

enum class ConnectionState { Unconfigured, Loading, Online, Stale, Offline }

data class PilotRoom(
    val id: String,
    val name: String,
    val responsePlayerId: String?,
    val defaultMusicPlayerId: String?,
    val players: List<PilotPlayer>,
    val musicEnabled: Boolean = true,
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
    val mediaType: String? = null,
    val contentId: String? = null,
    val durationSeconds: Double? = null,
)

data class EffectiveMediaState(
    val available: Boolean,
    val powered: Boolean?,
    val playbackState: String?,
    val volumePercent: Int?,
    val muted: Boolean?,
    val source: String?,
    val media: CurrentMedia?,
    val positionSeconds: Double? = null,
    val durationSeconds: Double? = null,
    val capabilities: Set<String> = emptySet(),
    val groupMembers: List<String> = emptyList(),
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
    val revision: String? = null,
    val queues: Map<String, MediaQueue> = emptyMap(),
)

data class MediaQueueItem(
    val id: String,
    val title: String,
    val artist: String?,
    val album: String?,
    val imageUrl: String?,
    val durationSeconds: Double?,
    val active: Boolean,
)

data class MediaQueue(
    val playerId: String,
    val index: Int?,
    val items: List<MediaQueueItem>,
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

data class DashboardPower(
    val solarW: Double?, val gridW: Double?, val batteryW: Double?,
    val batterySocPercent: Double?, val homeLoadW: Double?, val serverRackW: Double?,
    val gridDirection: String, val batteryDirection: String, val gridFlowActive: Boolean,
)
data class DashboardDaily(val generatedKWh: Double?, val homeKWh: Double?, val exportedKWh: Double?)
data class DashboardVehicle(val connected: Boolean?, val charging: Boolean, val powerW: Double?, val socPercent: Double?)
data class DashboardTemperature(val id: String, val label: String, val temperatureC: Double?)
data class DashboardPoint(val at: Instant?, val value: Double)
data class DashboardSeries(
    val id: String,
    val label: String,
    val color: String,
    val points: List<DashboardPoint>,
    val activityThresholdW: Double? = null,
    val renderMode: String? = null,
)
data class DashboardForecast(val at: Instant?, val condition: String?, val highC: Double?, val lowC: Double?, val rainPercent: Double?)
data class DashboardWeather(
    val condition: String?, val temperatureC: Double?, val humidityPercent: Double?,
    val windSpeed: Double?, val windSpeedUnit: String?, val forecast: List<DashboardForecast>,
)
data class DashboardTariff(val importCents: Double?, val feedInCents: Double?, val forecast: List<DashboardPoint>)
data class DashboardControls(val chargingMode: String?, val chargingModes: List<String>, val mediaRoomAvailable: Boolean)
data class DashboardSnapshot(
    val status: String, val power: DashboardPower, val daily: DashboardDaily,
    val vehicle: DashboardVehicle, val temperatures: List<DashboardTemperature>,
    val history: List<DashboardSeries>, val weather: DashboardWeather,
    val tariff: DashboardTariff, val controls: DashboardControls,
    val sceneIsDay: Boolean? = null,
    val historyStartedAt: Instant? = null,
    val historyEndedAt: Instant? = null,
    val historyWindow: String? = null,
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
    val imageUrl: String? = null,
)

data class AssistantCard(
    val kind: String,
    val title: String,
    val detail: String?,
)

data class AssistantSource(
    val label: String,
    val url: String?,
)

data class AssistantReply(
    val text: String,
    val conversationId: String?,
    val provider: String?,
    val continueConversation: Boolean,
    val roomId: String?,
    val status: String = "complete",
    val transcript: String? = null,
    val audioDownloadUrl: String? = null,
    val cards: List<AssistantCard> = emptyList(),
    val sources: List<AssistantSource> = emptyList(),
    val actions: List<String> = emptyList(),
)

data class ChatMessage(
    val id: Long,
    val role: ChatRole,
    val text: String,
    val pending: Boolean = false,
)

enum class ChatRole { User, Pilot }

enum class AssistantPhase { Idle, Listening, Processing, Speaking, Failed }

data class PilotSnapshot(
    val media: MediaSnapshot,
    val surface: SurfaceSnapshot,
    val dashboard: DashboardSnapshot? = null,
    val receivedAt: Instant = Instant.now(),
)

data class MediaCommand(
    val action: String,
    val playerId: String? = null,
    val mediaUri: String? = null,
    val targetRoomId: String? = null,
    val targetPlayerId: String? = null,
    val volume: Int? = null,
    val positionSeconds: Double? = null,
    val muted: Boolean? = null,
    val source: String? = null,
)

enum class HomeControlKind { Light, Climate, Cover, Fan, Lock, Scene, Switch, Sensor, Contact, Generic }

data class EntityPresentation(
    val included: Boolean = true,
    val exposurePolicy: String = "automatic",
    val reason: String? = null,
    val category: String? = null,
    val priority: Int = 500,
    val roomTrust: String? = null,
    val roomAuthoritative: Boolean = false,
    val canonicalId: String? = null,
    val duplicateOf: String? = null,
    val displayName: String? = null,
    val icon: String? = null,
    val section: String? = null,
    val control: String? = null,
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
    val presentation: EntityPresentation = EntityPresentation(),
    val unit: String? = null,
    val deviceClass: String? = null,
    val numericValue: Double? = null,
    val targetTemperature: Double? = null,
    val positionPercent: Float? = null,
    val percentage: Float? = null,
) {
    val isOn: Boolean
        get() = state.lowercase() in setOf(
            "on", "open", "opening", "unlocked", "active", "heat", "cool",
        )

    val displayName: String get() = presentation.displayName ?: name

    val controlKind: HomeControlKind
        get() = when (presentation.control?.lowercase()) {
            "light" -> HomeControlKind.Light
            "climate" -> HomeControlKind.Climate
            "cover", "shade" -> HomeControlKind.Cover
            "fan" -> HomeControlKind.Fan
            "lock" -> HomeControlKind.Lock
            "scene" -> HomeControlKind.Scene
            "switch" -> HomeControlKind.Switch
            "sensor" -> HomeControlKind.Sensor
            "contact" -> HomeControlKind.Contact
            else -> when (domain) {
                "light" -> HomeControlKind.Light
                "climate" -> HomeControlKind.Climate
                "cover" -> HomeControlKind.Cover
                "fan" -> HomeControlKind.Fan
                "lock", "alarm_control_panel" -> HomeControlKind.Lock
                "scene" -> HomeControlKind.Scene
                "switch", "input_boolean" -> HomeControlKind.Switch
                "binary_sensor" -> HomeControlKind.Contact
                "sensor" -> HomeControlKind.Sensor
                else -> HomeControlKind.Generic
            }
        }

    val section: String
        get() = presentation.section?.takeIf(String::isNotBlank) ?: when (controlKind) {
            HomeControlKind.Light -> "Lighting"
            HomeControlKind.Climate -> "Climate"
            HomeControlKind.Cover -> "Shades"
            HomeControlKind.Fan -> "Air"
            HomeControlKind.Lock, HomeControlKind.Contact -> "Security"
            HomeControlKind.Scene -> "Scenes"
            HomeControlKind.Sensor -> "Sensors"
            HomeControlKind.Switch -> "Switches"
            HomeControlKind.Generic -> "Other"
        }
}

data class HomeProjection(
    val roomId: String,
    val roomName: String,
    val entities: List<HomeEntity>,
    val observedAt: Instant? = null,
    val status: String = "ok",
)

data class ClientManifest(
    val schema: String = "pilot.client.v1",
    val version: String? = null,
    val features: Set<String> = emptySet(),
    val eventSnapshotPath: String? = null,
    val eventLongPollPath: String? = null,
    val eventWebSocketPath: String? = null,
)

data class PilotEvent(
    val id: String,
    val type: String,
    val revision: String?,
    val occurredAt: Instant?,
)

data class PilotEventPage(
    val cursor: String?,
    val resetRequired: Boolean,
    val events: List<PilotEvent>,
)

data class BootstrapRegistration(
    val deviceId: String,
    val deviceToken: String,
    val roomId: String?,
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
        val freshness = root.optJSONObject("freshness") ?: JSONObject()
        return HomeProjection(
            roomId = room.optString("id", root.optString("selected_room_id")),
            roomName = room.optString("name", "Room"),
            entities = root.optJSONArray("entities").objects().map { entity ->
                val attributes = entity.optJSONObject("attributes") ?: JSONObject()
                val presentation = entity.optJSONObject("presentation") ?: JSONObject()
                val roomPresentation = presentation.optJSONObject("room") ?: JSONObject()
                val supportedActions = presentation.optJSONArray("supported_actions").strings()
                    .ifEmpty { entity.optJSONArray("actions").strings() }
                HomeEntity(
                    entityId = entity.optString("entity_id"),
                    domain = entity.optString("domain"),
                    name = entity.optString("name", entity.optString("entity_id")),
                    state = entity.optString("state"),
                    areaId = entity.optNullableString("area_id"),
                    unavailable = entity.optBoolean("unavailable"),
                    stale = entity.optBoolean("stale"),
                    actions = supportedActions,
                    brightnessPercent = attributes.optDouble("brightness")
                        .takeIf { attributes.has("brightness") && it.isFinite() }
                        ?.div(255.0)?.times(100)?.toFloat()?.coerceIn(0f, 100f),
                    presentation = EntityPresentation(
                        included = presentation.optNullableBoolean("included") ?: true,
                        exposurePolicy = presentation.optString("exposure_policy", "automatic"),
                        reason = presentation.optNullableString("reason"),
                        category = presentation.optNullableString("category"),
                        priority = presentation.optInt("priority", 500),
                        roomTrust = roomPresentation.optNullableString("trust")
                            ?: presentation.optNullableString("room_trust"),
                        roomAuthoritative = roomPresentation.optNullableBoolean("authoritative")
                            ?: presentation.optBoolean("room_authoritative", false),
                        canonicalId = presentation.optNullableString("canonical_id"),
                        duplicateOf = presentation.optNullableString("duplicate_of"),
                        displayName = presentation.optNullableString("display_name"),
                        icon = presentation.optNullableString("icon"),
                        section = presentation.optNullableString("section"),
                        control = presentation.optNullableString("control"),
                    ),
                    unit = attributes.optNullableString("unit_of_measurement"),
                    deviceClass = attributes.optNullableString("device_class"),
                    numericValue = entity.optFiniteDouble("state")
                        ?: attributes.optFiniteDouble("value"),
                    targetTemperature = attributes.optFiniteDouble("temperature"),
                    positionPercent = attributes.optFiniteDouble("current_position")
                        ?.toFloat()?.coerceIn(0f, 100f),
                    percentage = attributes.optFiniteDouble("percentage")
                        ?.toFloat()?.coerceIn(0f, 100f),
                )
            }.filter { it.presentation.included && it.presentation.duplicateOf == null },
            observedAt = freshness.optInstant("observed_at")
                ?: root.optInstant("observed_at"),
            status = freshness.optString("status", root.optString("status", "ok")),
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
        val queueRoot = media.optJSONObject("queues") ?: root.optJSONObject("queues")
        val topLevelQueues = queueRoot.objectsWithKeys().associate { (id, value) ->
            id to queue(value, id)
        }
        val embeddedQueues = media.optJSONObject("players").objectsWithKeys().mapNotNull { (id, value) ->
            val embedded = (value.optJSONObject("effective") ?: value).optJSONObject("queue")
            embedded?.let { id to queue(it, id) }
        }.toMap()
        return MediaSnapshot(
            observedAt = media.optInstant("observed_at"),
            rooms = rooms,
            players = states,
            revision = media.optNullableString("revision")
                ?: root.optNullableString("revision"),
            queues = topLevelQueues + embeddedQueues,
        )
    }

    fun surface(root: JSONObject): SurfaceSnapshot {
        val nowPlayingValue = root.opt("now_playing")
        val nowPlaying = when (nowPlayingValue) {
            is JSONArray -> nowPlayingValue.objects().map { playerState(it) }
            is JSONObject -> {
                val items = nowPlayingValue.optJSONArray("items")
                if (items != null) items.objects().map(::nowPlayingState)
                else {
                    val players = nowPlayingValue.optJSONObject("players") ?: nowPlayingValue
                    players.objectsWithKeys().map { (id, value) -> playerState(value, id) }
                }
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

    fun dashboard(root: JSONObject): DashboardSnapshot {
        val power = root.optJSONObject("power") ?: JSONObject()
        val directions = power.optJSONObject("directions") ?: JSONObject()
        val active = power.optJSONObject("flow_active") ?: JSONObject()
        val daily = root.optJSONObject("daily") ?: JSONObject()
        val vehicle = root.optJSONObject("vehicle") ?: JSONObject()
        val tariff = root.optJSONObject("tariff") ?: JSONObject()
        val weather = root.optJSONObject("weather") ?: JSONObject()
        val controls = root.optJSONObject("controls") ?: JSONObject()
        val scene = root.optJSONObject("scene") ?: JSONObject()
        val history = root.optJSONObject("history") ?: JSONObject()
        val chargingMode = controls.optJSONObject("tesla_charging_mode") ?: JSONObject()
        return DashboardSnapshot(
            status = root.optString("status", "partial"),
            power = DashboardPower(
                solarW = power.optFiniteDouble("solar_w"),
                gridW = power.optFiniteDouble("grid_w"),
                batteryW = power.optFiniteDouble("battery_w"),
                batterySocPercent = power.optFiniteDouble("battery_soc_percent"),
                homeLoadW = power.optFiniteDouble("home_load_w"),
                serverRackW = power.optFiniteDouble("server_rack_w"),
                gridDirection = directions.optString("grid", "idle"),
                batteryDirection = directions.optString("battery", "idle"),
                gridFlowActive = active.optBoolean("grid", false),
            ),
            daily = DashboardDaily(
                generatedKWh = daily.optFiniteDouble("solar_generated_kwh"),
                homeKWh = daily.optFiniteDouble("home_used_kwh"),
                exportedKWh = daily.optFiniteDouble("grid_exported_kwh"),
            ),
            vehicle = DashboardVehicle(
                connected = vehicle.optNullableBoolean("connected"),
                charging = vehicle.optBoolean("charging", false),
                powerW = vehicle.optFiniteDouble("power_w"),
                socPercent = vehicle.optFiniteDouble("state_of_charge_percent"),
            ),
            temperatures = root.optJSONArray("temperatures").objects().map {
                DashboardTemperature(
                    id = it.optString("id"), label = it.optString("label"),
                    temperatureC = it.optFiniteDouble("temperature_c"),
                )
            },
            history = history.optJSONArray("series").objects().map { series ->
                DashboardSeries(
                    id = series.optString("id"),
                    label = series.optString("label"),
                    color = series.optString("color", "#55B6FF"),
                    points = series.optJSONArray("points").objects().mapNotNull { point ->
                        point.optFiniteDouble("value")?.let { DashboardPoint(point.optInstant("at"), it) }
                    },
                    activityThresholdW = series.optFiniteDouble("activity_threshold_w"),
                    renderMode = series.optNullableString("render_mode"),
                )
            },
            weather = DashboardWeather(
                condition = weather.optNullableString("condition"),
                temperatureC = weather.optFiniteDouble("temperature_c"),
                humidityPercent = weather.optFiniteDouble("humidity_percent"),
                windSpeed = weather.optFiniteDouble("wind_speed"),
                windSpeedUnit = weather.optNullableString("wind_speed_unit"),
                forecast = weather.optJSONArray("forecast").objects().map {
                    DashboardForecast(
                        at = it.optInstant("at"), condition = it.optNullableString("condition"),
                        highC = it.optFiniteDouble("high_temperature_c"),
                        lowC = it.optFiniteDouble("low_temperature_c"),
                        rainPercent = it.optFiniteDouble("precipitation_probability"),
                    )
                },
            ),
            tariff = DashboardTariff(
                importCents = tariff.optFiniteDouble("import_cents_per_kwh"),
                feedInCents = tariff.optFiniteDouble("feed_in_cents_per_kwh"),
                forecast = tariff.optJSONArray("feed_in_forecast").objects().mapNotNull {
                    it.optFiniteDouble("cents_per_kwh")?.let { value -> DashboardPoint(it.optInstant("at"), value) }
                },
            ),
            controls = DashboardControls(
                chargingMode = chargingMode.optNullableString("value"),
                chargingModes = chargingMode.optJSONArray("options").strings(),
                mediaRoomAvailable = controls.optJSONObject("media_room_mode")
                    ?.optBoolean("available", false) == true,
            ),
            sceneIsDay = scene.optNullableBoolean("is_day"),
            historyStartedAt = history.optInstant("started_at"),
            historyEndedAt = history.optInstant("ended_at"),
            historyWindow = history.optNullableString("window"),
        )
    }

    fun assistant(root: JSONObject): AssistantReply {
        val audio = root.optJSONObject("audio") ?: JSONObject()
        return AssistantReply(
            text = root.optString("response_text", "I couldn't prepare a response."),
            conversationId = root.optNullableString("conversation_id"),
            provider = root.optNullableString("provider"),
            continueConversation = root.optBoolean("continue_conversation", false),
            roomId = root.optNullableString("room_id"),
            status = root.optString("status", "complete"),
            transcript = root.optNullableString("transcript"),
            audioDownloadUrl = audio.optNullableString("download_url"),
            cards = root.optJSONArray("cards").objects().map { card ->
                AssistantCard(
                    kind = card.optString("kind", card.optString("type", "information")),
                    title = card.optString("title", "Pilot"),
                    detail = card.optNullableString("detail")
                        ?: card.optNullableString("text"),
                )
            },
            sources = (root.optJSONArray("sources") ?: root.optJSONArray("citations")).objects().map { source ->
                AssistantSource(
                    label = source.optString("label", source.optString("title", "Source")),
                    url = source.optNullableString("url"),
                )
            },
            actions = root.optJSONArray("actions").strings(),
        )
    }

    fun manifest(root: JSONObject): ClientManifest {
        val contract = root.optJSONObject("contract") ?: root
        val endpoints = root.optJSONObject("endpoints") ?: JSONObject()
        return ClientManifest(
            schema = contract.optString(
                "schema",
                root.optString("schema_version", root.optString("schema", "pilot.client.v1")),
            ),
            version = contract.optNullableString("version")
                ?: root.optNullableString("version")
                ?: root.optNullableString("core_version"),
            features = root.optJSONArray("features").strings().toSet() +
                (root.optJSONObject("features")?.trueKeys().orEmpty()),
            eventSnapshotPath = endpoints.endpointPath("events_snapshot")
                ?: endpoints.endpointPath("event_snapshot")
                ?: endpoints.endpointPath("snapshot"),
            eventLongPollPath = endpoints.endpointPath("events")
                ?: endpoints.endpointPath("event_long_poll"),
            eventWebSocketPath = endpoints.endpointPath("events_websocket")
                ?: endpoints.endpointPath("events_ws"),
        )
    }

    fun events(root: JSONObject): PilotEventPage = PilotEventPage(
        cursor = root.optNullableString("cursor") ?: root.optNullableString("next_cursor"),
        resetRequired = root.optBoolean("reset_required", false),
        events = root.optJSONArray("events").objects().map { event ->
            PilotEvent(
                id = event.optString("id", event.optString("cursor")),
                type = event.optString("type", "state.changed"),
                revision = event.optNullableString("revision"),
                occurredAt = event.optInstant("occurred_at")
                    ?: event.optInstant("created_at"),
            )
        },
    )

    fun bootstrap(root: JSONObject) = BootstrapRegistration(
        deviceId = root.optString("device_id"),
        deviceToken = root.optString("device_token"),
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
                                imageUrl = item.optNullableString("image_url")
                                    ?: item.optNullableString("image"),
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
        musicEnabled = value.optBoolean("music_enabled", true),
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
        val nowPlaying = effective.optJSONObject("now_playing")
            ?: effective.optJSONObject("media")
        val capabilityRoot = effective.opt("capabilities") ?: value.opt("capabilities")
        val capabilities = when (capabilityRoot) {
            is JSONArray -> capabilityRoot.strings().toSet()
            is JSONObject -> capabilityRoot.trueKeys() +
                capabilityRoot.optJSONArray("actions").strings() +
                setOfNotNull(
                    "group".takeIf { capabilityRoot.optBoolean("grouping", false) },
                    "set_volume".takeIf { capabilityRoot.optBoolean("volume", false) },
                )
            else -> emptySet()
        }
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
                media = nowPlaying?.let {
                    CurrentMedia(
                        title = it.optNullableString("title"),
                        artist = it.optNullableString("artist"),
                        album = it.optNullableString("album"),
                        imageUrl = effective.optNullableString("artwork_url")
                            ?: it.optJSONObject("artwork")?.optNullableString("proxy_url")
                            ?: it.optJSONObject("artwork")?.optNullableString("source_url")
                            ?: it.optNullableString("artwork_url")
                            ?: it.optNullableString("image_url")
                            ?: it.optNullableString("image"),
                        mediaType = it.optNullableString("media_type")
                            ?: it.optNullableString("content_type"),
                        contentId = it.optNullableString("content_id")
                            ?: it.optNullableString("uri"),
                        durationSeconds = it.optFiniteDouble("duration_seconds")
                            ?: it.optFiniteDouble("duration"),
                    )
                },
                positionSeconds = effective.optFiniteDouble("position_seconds")
                    ?: effective.optFiniteDouble("elapsed_seconds"),
                durationSeconds = effective.optFiniteDouble("duration_seconds")
                    ?: nowPlaying?.optFiniteDouble("duration_seconds")
                    ?: nowPlaying?.optFiniteDouble("duration"),
                capabilities = capabilities,
                groupMembers = effective.optJSONArray("group_members").strings()
                    .ifEmpty {
                        effective.optJSONObject("group")
                            ?.optJSONArray("members").strings()
                    },
            ),
        )
    }

    private fun nowPlayingState(value: JSONObject): PilotPlayerState {
        val id = value.optString("player_id")
        return PilotPlayerState(
            player = PilotPlayer(
                id = id,
                roomId = value.optString("room_id"),
                name = value.optString("player_name", id),
                kind = "audio",
                protocol = value.optString("provider"),
                enabled = true,
                controlEnabled = true,
            ),
            status = value.optString("status", "ok"),
            effective = EffectiveMediaState(
                available = true,
                powered = true,
                playbackState = value.optNullableString("state"),
                volumePercent = value.optNullableInt("volume_percent"),
                muted = value.optNullableBoolean("muted"),
                source = value.optNullableString("source"),
                media = CurrentMedia(
                    title = value.optNullableString("title"),
                    artist = value.optNullableString("artist"),
                    album = value.optNullableString("album"),
                    imageUrl = value.optNullableString("artwork_url")
                        ?: value.optNullableString("image_url"),
                    mediaType = value.optNullableString("media_type"),
                    contentId = value.optNullableString("content_id"),
                    durationSeconds = value.optFiniteDouble("duration_seconds"),
                ),
                positionSeconds = value.optFiniteDouble("elapsed_seconds")
                    ?: value.optFiniteDouble("position_seconds"),
                durationSeconds = value.optFiniteDouble("duration_seconds"),
                capabilities = value.optJSONArray("capabilities").strings().toSet(),
                groupMembers = value.optJSONArray("group_members").strings(),
            ),
        )
    }

    private fun queue(value: JSONObject, fallbackId: String): MediaQueue {
        val entries = value.optJSONArray("items") ?: value.optJSONArray("queue")
        val activeIndex = value.optNullableInt("index")
            ?: value.optNullableInt("current_index")
        return MediaQueue(
            playerId = value.optString("player_id", fallbackId),
            index = activeIndex,
            items = entries.objects().mapIndexed { index, item ->
                MediaQueueItem(
                    id = item.optString("id", item.optString("uri", "$fallbackId-$index")),
                    title = item.optString("title", item.optString("name", "Untitled")),
                    artist = item.optNullableString("artist"),
                    album = item.optNullableString("album"),
                    imageUrl = item.optNullableString("artwork_url")
                        ?: item.optNullableString("image_url"),
                    durationSeconds = item.optFiniteDouble("duration_seconds")
                        ?: item.optFiniteDouble("duration"),
                    active = item.optBoolean("active", activeIndex == index),
                )
            },
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

private fun JSONObject.trueKeys(): Set<String> = keys().asSequence().mapNotNull { key ->
    key.takeIf { optBoolean(key, false) }
}.toSet()

private fun JSONObject.optNullableString(key: String): String? =
    (opt(key) as? String)?.takeIf(String::isNotBlank)

private fun JSONObject.optNullableInt(key: String): Int? =
    if (has(key) && !isNull(key)) optInt(key) else null

private fun JSONObject.optNullableBoolean(key: String): Boolean? =
    if (has(key) && !isNull(key)) optBoolean(key) else null

private fun JSONObject.optInstant(key: String): Instant? =
    optNullableString(key)?.let { runCatching { Instant.parse(it) }.getOrNull() }

private fun JSONObject.optFiniteDouble(key: String): Double? {
    if (!has(key) || isNull(key)) return null
    val value = when (val raw = opt(key)) {
        is Number -> raw.toDouble()
        is String -> raw.toDoubleOrNull()
        else -> null
    }
    return value?.takeIf(Double::isFinite)
}

private fun JSONObject.endpointPath(key: String): String? =
    optNullableString(key) ?: optJSONObject(key)?.optNullableString("path")
