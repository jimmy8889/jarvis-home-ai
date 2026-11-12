package com.jameshazell.pilot.data.pilot

import java.time.Instant

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

data class SurfaceMeasurement(
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

data class SurfaceEnergy(
    val status: String,
    val solar: SurfaceMeasurement,
    val grid: SurfaceMeasurement,
    val battery: SurfaceMeasurement,
    val batterySoc: SurfaceMeasurement,
    val homeLoad: SurfaceMeasurement,
)

data class DashboardPower(
    val solarW: Double?, val gridW: Double?, val batteryW: Double?,
    val batterySocPercent: Double?, val homeLoadW: Double?, val serverRackW: Double?,
    val gridDirection: String, val batteryDirection: String, val gridFlowActive: Boolean,
)
data class DashboardDaily(val generatedKWh: Double?, val homeKWh: Double?, val exportedKWh: Double?)
data class DashboardVehicle(val connected: Boolean?, val charging: Boolean, val powerW: Double?, val socPercent: Double?, val home: Boolean? = null)
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
    val energyObservedAt: Instant? = null,
    val energyStale: Boolean = false,
    val sceneIsDay: Boolean? = null,
    val historyStartedAt: Instant? = null,
    val historyEndedAt: Instant? = null,
    val historyWindow: String? = null,
)

data class SurfaceSnapshot(
    val serverTime: Instant?,
    val energy: SurfaceEnergy?,
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

data class PilotSnapshot(
    val media: MediaSnapshot,
    val surface: SurfaceSnapshot,
    val dashboard: DashboardSnapshot? = null,
    val receivedAt: Instant = Instant.now(),
    val fromCache: Boolean = false,
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
    /** Climate: the measured room temperature (`current_temperature`). */
    val currentTemperature: Double? = null,
    /** Climate and humidity sensors: relative humidity in percent. */
    val humidity: Double? = null,
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
