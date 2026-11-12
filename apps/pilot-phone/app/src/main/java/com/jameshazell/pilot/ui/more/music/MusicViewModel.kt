package com.jameshazell.pilot.ui.more.music

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.core.Outcome
import com.jameshazell.pilot.core.onFailure
import com.jameshazell.pilot.data.pilot.MediaCommand
import com.jameshazell.pilot.data.pilot.MediaQueue
import com.jameshazell.pilot.data.pilot.MusicSearchResult
import com.jameshazell.pilot.data.pilot.PilotPlayerState
import com.jameshazell.pilot.data.pilot.PilotRepository
import com.jameshazell.pilot.data.pilot.PilotRoom
import com.jameshazell.pilot.data.pilot.PilotSnapshot
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Search and command state of the Music page. Held by MusicViewModel, so it survives folding. */
data class MusicUiState(
    val query: String = "",
    val searching: Boolean = false,
    /** The query the current [results] answer; null before the first search. */
    val searchedFor: String? = null,
    val results: List<MusicSearchResult> = emptyList(),
    /** A playback command is in flight. */
    val busy: Boolean = false,
    val error: String? = null,
)

/** What the Music page draws. Built by [buildMusicState]. */
data class MusicScreenState(
    val rooms: List<PilotRoom>,
    val roomId: String?,
    val player: PilotPlayerState?,
    val queue: MediaQueue?,
    val moveTargets: List<PilotRoom>,
    val online: Boolean,
    val ui: MusicUiState,
) {
    val roomName: String? get() = rooms.firstOrNull { it.id == roomId }?.name
    val commandsEnabled: Boolean get() = online && !ui.busy
}

fun buildMusicState(snapshot: PilotSnapshot, selectedRoomId: String?, online: Boolean, ui: MusicUiState): MusicScreenState {
    val rooms = musicRooms(snapshot.media.rooms)
    val roomId = selectedRoomId?.takeIf { id -> rooms.any { it.id == id } } ?: rooms.firstOrNull()?.id
    val player = roomPlayer(snapshot.media, roomId)
    return MusicScreenState(
        rooms = rooms,
        roomId = roomId,
        player = player,
        queue = player?.let { snapshot.media.queues[it.player.id] }?.takeIf { it.items.isNotEmpty() },
        moveTargets = player?.let { transferTargets(snapshot.media.rooms, it) }.orEmpty(),
        online = online,
        ui = ui,
    )
}

/** What the Music UI can ask for. Implemented by [MusicViewModel]; previews pass a no-op. */
interface MusicActions {
    fun selectRoom(roomId: String)
    fun setQuery(text: String)
    fun search()
    fun play(result: MusicSearchResult, playerId: String?)
    fun command(command: MediaCommand)
    fun dismissError()
}

class MusicViewModel(private val pilot: PilotRepository) : ViewModel(), MusicActions {
    val snapshot: StateFlow<LoadState<PilotSnapshot>> = pilot.snapshot
    val selectedRoomId: StateFlow<String?> = pilot.selectedRoomId

    private val _ui = MutableStateFlow(MusicUiState())
    val ui: StateFlow<MusicUiState> = _ui.asStateFlow()

    fun refresh() = pilot.refresh()

    override fun selectRoom(roomId: String) = pilot.selectRoom(roomId)

    override fun setQuery(text: String) = _ui.update { it.copy(query = text) }

    override fun search() {
        val query = _ui.value.query.trim()
        if (query.isEmpty() || _ui.value.searching) return
        viewModelScope.launch {
            _ui.update { it.copy(searching = true, error = null) }
            when (val result = pilot.search(query)) {
                is Outcome.Success -> _ui.update { it.copy(searching = false, searchedFor = query, results = result.value) }
                is Outcome.Failure -> _ui.update { it.copy(searching = false, error = result.error.message) }
            }
        }
    }

    override fun play(result: MusicSearchResult, playerId: String?) =
        command(MediaCommand(action = "play_media", playerId = playerId, mediaUri = result.uri))

    override fun command(command: MediaCommand) {
        if (!pilot.snapshot.value.isLive) {
            _ui.update { it.copy(error = "Reconnect to control playback. Saved data is read-only.") }
            return
        }
        if (_ui.value.busy) return
        viewModelScope.launch {
            _ui.update { it.copy(busy = true, error = null) }
            pilot.media(command).onFailure { error -> _ui.update { it.copy(error = error.message) } }
            _ui.update { it.copy(busy = false) }
        }
    }

    override fun dismissError() = _ui.update { it.copy(error = null) }

    suspend fun artwork(url: String): ByteArray? = pilot.artwork(url)
}
