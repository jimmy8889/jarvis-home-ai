package com.jameshazell.pilot.ui.home

import com.jameshazell.pilot.data.pilot.PilotPlayerState
import com.jameshazell.pilot.data.pilot.PilotSnapshot

/** A command waiting for the user's tap in a ConfirmDialog. Nothing has been done yet. */
data class PendingConfirm(
    val roomId: String,
    val command: EntityCommand,
    val prompt: ConfirmPrompt,
    /** Set when Pilot Core itself asked for the confirmation and is holding the action. */
    val serverActionId: String? = null,
    val busy: Boolean = false,
    val error: String? = null,
)

/** Everything Home keeps besides the Pilot Core snapshot. Held by HomeViewModel, so it survives folding. */
data class HomeLocalState(
    val rooms: OptimisticRooms = OptimisticRooms(),
    /** The room shown in the detail pane; null when none is open. */
    val openRoomId: String? = null,
    /** Entity ids with a command in flight. */
    val busy: Set<String> = emptySet(),
    /** Why a room's devices could not be read, by room id. */
    val roomErrors: Map<String, String> = emptyMap(),
    /** The last command failure, shown inline until the next command or dismissal. */
    val error: String? = null,
    val confirm: PendingConfirm? = null,
    /** Rooms whose devices are being read right now. */
    val loadingRooms: Set<String> = emptySet(),
    val mediaBusy: Boolean = false,
)

data class OpenRoom(
    val summary: RoomSummary,
    val content: RoomContent,
    /** This room's players that are usable, default music player first. */
    val players: List<PilotPlayerState>,
    val loadError: String?,
    /** Its devices are being read right now. */
    val loading: Boolean = false,
)

/** What the Home screen draws. Built by [buildHomeState]; no Android types. */
data class HomeScreenState(
    val rooms: List<RoomSummary>,
    val house: HouseSummary,
    val energy: EnergySummary?,
    val weather: WeatherChip?,
    val statusLabel: String,
    val openRoom: OpenRoom?,
    /** Pilot Core is answering right now (not saved data). */
    val online: Boolean,
    /** Pilot Core lets this phone control room devices. */
    val canControl: Boolean,
    val busy: Set<String> = emptySet(),
    val error: String? = null,
    val mediaBusy: Boolean = false,
) {
    val controlsEnabled: Boolean get() = online && canControl

    /** Why controls are disabled, or null when they work. */
    val controlNotice: String?
        get() = when {
            !online -> "Reconnect to control devices. Saved data is read-only."
            !canControl -> "This phone can view room devices but not control them."
            else -> null
        }
}

fun buildHomeState(
    snapshot: PilotSnapshot,
    online: Boolean,
    canControl: Boolean,
    local: HomeLocalState,
    statusLabel: String = "",
): HomeScreenState {
    val visible = local.rooms.visibleRooms
    val players = snapshot.media.players
    val temperatures = snapshot.dashboard?.temperatures.orEmpty()
    // Only the open room's devices are current; any other room's are from an earlier visit.
    val summaries = snapshot.media.rooms.map { room ->
        summariseRoom(room, visible[room.id], players, temperatures, cached = room.id != local.openRoomId)
    }
    val open = snapshot.media.rooms.firstOrNull { it.id == local.openRoomId }?.let { room ->
        OpenRoom(
            summary = summaries.first { it.id == room.id },
            content = roomContent(visible[room.id]),
            players = players
                .filter { it.player.roomId == room.id && it.player.enabled }
                .sortedByDescending { it.player.id == room.defaultMusicPlayerId },
            loadError = local.roomErrors[room.id],
            loading = room.id in local.loadingRooms,
        )
    }
    return HomeScreenState(
        rooms = summaries,
        house = summariseHouse(snapshot),
        energy = energySummary(snapshot),
        weather = weatherChip(snapshot.dashboard),
        statusLabel = statusLabel,
        openRoom = open,
        online = online,
        canControl = canControl,
        busy = local.busy,
        error = local.error,
        mediaBusy = local.mediaBusy,
    )
}
