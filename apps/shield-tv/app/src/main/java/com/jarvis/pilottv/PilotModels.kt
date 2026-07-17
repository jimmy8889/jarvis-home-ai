package com.jarvis.pilottv

data class DeploymentInfo(
    val version: String,
    val release: String,
    val uptimeSeconds: Long,
)

data class SystemSummary(
    val roomCount: Int,
    val deviceCount: Int,
    val connectedDeviceCount: Int,
    val configuredIntegrationCount: Int,
    val healthyIntegrationCount: Int,
    val armedRoomCount: Int,
    val unarmedRoomCount: Int,
    val pendingCommandCount: Int,
)

data class SafetyState(
    val audibleActionsGated: Boolean,
    val armedRooms: List<String>,
    val unarmedRooms: List<String>,
)

data class IntegrationState(
    val id: String,
    val status: String,
    val configured: Boolean,
    val latencyMs: Long?,
)

data class EndpointState(
    val id: String,
    val name: String,
    val connected: Boolean,
    val ready: Boolean?,
    val uptimeSeconds: Long?,
)

data class MediaDescription(
    val title: String?,
    val artist: String?,
    val album: String?,
)

data class PlayerState(
    val id: String,
    val name: String,
    val kind: String,
    val protocol: String,
    val controlEnabled: Boolean,
    val status: String,
    val available: Boolean?,
    val powered: Boolean?,
    val playbackState: String?,
    val volumePercent: Int?,
    val muted: Boolean?,
    val source: String?,
    val media: MediaDescription?,
)

data class SourceState(
    val id: String,
    val active: Boolean,
)

data class RoomState(
    val id: String,
    val name: String,
    val armed: Boolean,
    val foregroundSource: String?,
    val devices: List<EndpointState>,
    val players: List<PlayerState>,
    val sources: List<SourceState>,
)

data class OperationsSnapshot(
    val generatedAt: String,
    val deployment: DeploymentInfo,
    val summary: SystemSummary,
    val safety: SafetyState,
    val integrations: List<IntegrationState>,
    val rooms: List<RoomState>,
)
