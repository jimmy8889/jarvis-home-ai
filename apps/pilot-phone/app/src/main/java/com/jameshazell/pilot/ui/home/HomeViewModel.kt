package com.jameshazell.pilot.ui.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.core.Outcome
import com.jameshazell.pilot.core.onFailure
import com.jameshazell.pilot.data.pilot.ClientManifest
import com.jameshazell.pilot.data.pilot.HomeAction
import com.jameshazell.pilot.data.pilot.HomeEntity
import com.jameshazell.pilot.data.pilot.MediaCommand
import com.jameshazell.pilot.data.pilot.PilotRepository
import com.jameshazell.pilot.data.pilot.ProjectionReason
import com.jameshazell.pilot.data.pilot.PilotSnapshot
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** What the Home UI can ask for. Implemented by [HomeViewModel]; previews pass a no-op. */
interface HomeActions {
    fun openRoom(roomId: String)
    fun closeRoom()
    fun toggleRoomLights(roomId: String)
    fun setRoomBrightness(roomId: String, percent: Int)
    fun act(roomId: String, entity: HomeEntity, action: String, value: Double? = null, option: String? = null)
    fun media(command: MediaCommand)
    fun retryRoom(roomId: String)
    fun dismissError()
}

/**
 * Home and room detail. Activity-scoped, so the open room, in-flight commands and loaded devices
 * all survive folding and unfolding.
 *
 * Reading a room's devices is very expensive for Pilot Core, so a room is read only when the
 * user opens it, asks to refresh it, or has just sent it a command; the repository may also
 * re-read the room that is visibly open when something changed (at most every 30 s). The Home
 * grid never causes a read: tiles use the snapshot plus what earlier opens left behind.
 */
class HomeViewModel(private val pilot: PilotRepository) : ViewModel(), HomeActions {
    val snapshot: StateFlow<LoadState<PilotSnapshot>> = pilot.snapshot
    val manifest: StateFlow<ClientManifest?> = pilot.manifest
    val liveEvents: StateFlow<Boolean> = pilot.liveEvents

    private val _local = MutableStateFlow(HomeLocalState())
    val local: StateFlow<HomeLocalState> = _local.asStateFlow()

    private var visible = false

    init {
        viewModelScope.launch {
            pilot.snapshot.collect { state ->
                val value = state.valueOrNull()
                if (value == null) {
                    // Unpaired or pairing again: nothing from the previous house may linger.
                    if (state is LoadState.Loading) {
                        _local.value = HomeLocalState()
                        syncVisibleRoom()
                    }
                    return@collect
                }
                val ids = value.media.rooms.map { it.id }.toSet()
                _local.update { it.copy(rooms = it.rooms.keepOnly(ids), openRoomId = it.openRoomId?.takeIf(ids::contains)) }
                syncVisibleRoom()
            }
        }
        // Rooms re-read by the repository (the visible room, when something changed) land here.
        viewModelScope.launch {
            pilot.roomProjections.collect { fresh ->
                _local.update { local ->
                    val changed = fresh.values.filter { local.rooms.confirmed[it.roomId] !== it }
                    if (changed.isEmpty()) local
                    else local.copy(rooms = changed.fold(local.rooms) { rooms, room -> rooms.confirm(room) })
                }
            }
        }
    }

    /** Home is on screen (true) or not (false). */
    fun setVisible(value: Boolean) {
        visible = value
        syncVisibleRoom()
    }

    /** Retry from the connection error or the "saved data" banner. */
    fun refresh() {
        pilot.refresh()
        _local.value.openRoomId?.let(::retryRoom)
    }

    override fun onCleared() = pilot.setRoomVisible(null)

    /** A room counts as visible only while Home is on screen with that room's detail open. */
    private fun syncVisibleRoom() = pilot.setRoomVisible(_local.value.openRoomId.takeIf { visible })

    // ---- Rooms ------------------------------------------------------------------------------

    override fun openRoom(roomId: String) {
        _local.update { it.copy(openRoomId = roomId, error = null) }
        syncVisibleRoom()
        // The open room is also the context for music and the assistant.
        pilot.selectRoom(roomId)
        viewModelScope.launch { loadRoom(roomId, ProjectionReason.UserOpened) }
    }

    override fun closeRoom() {
        _local.update { it.copy(openRoomId = null, error = null) }
        syncVisibleRoom()
    }

    /** The Refresh button or Retry in a room: the one explicit way to re-read its devices. */
    override fun retryRoom(roomId: String) {
        viewModelScope.launch { loadRoom(roomId, ProjectionReason.UserRetry) }
    }

    override fun dismissError() = _local.update { it.copy(error = null) }

    /**
     * Reads one room's devices if the repository's gate allows it now. Rooms are never read for
     * the Home grid, on a timer or ahead of time: reading a room is very expensive for Pilot Core.
     *
     * @param settled entities whose commands just succeeded; their optimistic state is replaced.
     */
    private suspend fun loadRoom(roomId: String, reason: ProjectionReason, settled: Set<String> = emptySet()) {
        _local.update { it.copy(loadingRooms = it.loadingRooms + roomId) }
        val result = try {
            pilot.homeFor(roomId, reason)
        } finally {
            _local.update { it.copy(loadingRooms = it.loadingRooms - roomId) }
        }
        when (result) {
            is Outcome.Success -> _local.update {
                it.copy(rooms = it.rooms.confirm(result.value, settled), roomErrors = it.roomErrors - roomId)
            }
            is Outcome.Failure -> _local.update {
                it.copy(
                    rooms = it.rooms.promote(roomId, settled),
                    roomErrors = it.roomErrors + (roomId to result.error.message),
                )
            }
            // Not read this time (too soon, or the user has moved on): keep what is shown.
            null -> _local.update { it.copy(rooms = it.rooms.promote(roomId, settled)) }
        }
    }

    // ---- Device commands --------------------------------------------------------------------

    override fun act(roomId: String, entity: HomeEntity, action: String, value: Double?, option: String?) {
        if (!ready()) return
        val command = EntityCommand(entity, action, value, option)
        val prompt = confirmationFor(entity, action)
        if (prompt != null) {
            _local.update { it.copy(confirm = PendingConfirm(roomId, command, prompt), error = null) }
            return
        }
        viewModelScope.launch {
            when (val sent = execute(roomId, command, userConfirmed = false)) {
                Sent.Done -> loadRoom(roomId, ProjectionReason.AfterAction, setOf(entity.entityId))
                Sent.Held -> Unit
                is Sent.Failed -> showError(sent.message)
            }
        }
    }

    override fun toggleRoomLights(roomId: String) {
        val lights = _local.value.rooms.visible(roomId)?.entities.orEmpty().filter { it.isLight }
        sendGroup(roomLightToggle(lights).map { roomId to it })
    }

    override fun setRoomBrightness(roomId: String, percent: Int) {
        val lights = _local.value.rooms.visible(roomId)?.entities.orEmpty().filter { it.isLight }
        val level = percent.coerceIn(0, 100).toDouble()
        sendGroup(brightnessTargets(lights).map { roomId to EntityCommand(it, "set_brightness", level) })
    }

    /** The user tapped the confirm button of the dialog for [HomeLocalState.confirm]. */
    fun confirmPending() {
        val pending = _local.value.confirm?.takeIf { !it.busy } ?: return
        if (!pilot.snapshot.value.isLive) {
            _local.update { it.copy(confirm = pending.copy(error = "Reconnect to send this. Nothing was sent.")) }
            return
        }
        _local.update { it.copy(confirm = pending.copy(busy = true, error = null)) }
        viewModelScope.launch {
            val id = pending.command.entity.entityId
            val sent = if (pending.serverActionId == null) {
                execute(pending.roomId, pending.command, userConfirmed = true)
            } else {
                _local.update { it.copy(rooms = it.rooms.begin(pending.command), busy = it.busy + id) }
                finish(id, pilot.confirmHomeAction(pending.serverActionId))
            }
            if (sent is Sent.Failed) {
                _local.update { it.copy(confirm = it.confirm?.copy(busy = false, error = sent.message)) }
            } else {
                _local.update { it.copy(confirm = null) }
                loadRoom(pending.roomId, ProjectionReason.AfterAction, setOf(id))
            }
        }
    }

    fun cancelPending() = _local.update { if (it.confirm?.busy == true) it else it.copy(confirm = null) }

    private fun sendGroup(commands: List<Pair<String, EntityCommand>>) {
        if (commands.isEmpty() || !ready()) return
        viewModelScope.launch {
            val results = commands.map { (roomId, command) ->
                async { Triple(roomId, command.entity.entityId, execute(roomId, command, userConfirmed = false)) }
            }.awaitAll()
            results.filter { it.third == Sent.Done }.groupBy({ it.first }, { it.second }).forEach { (roomId, ids) ->
                launch { loadRoom(roomId, ProjectionReason.AfterAction, ids.toSet()) }
            }
            val errors = results.mapNotNull { (it.third as? Sent.Failed)?.message }
            if (errors.isNotEmpty()) showError(groupFailureMessage(errors.size, commands.size, errors.first()))
        }
    }

    /**
     * Sends one command with its optimistic update. On [Sent.Done] the optimistic state stays
     * until the caller reloads the room; on [Sent.Failed] it has already been rolled back.
     *
     * A command Pilot Core holds for confirmation is only confirmed here when the user has
     * already tapped confirm for exactly this command; otherwise a dialog is raised instead.
     */
    private suspend fun execute(roomId: String, command: EntityCommand, userConfirmed: Boolean): Sent {
        val id = command.entity.entityId
        _local.update { it.copy(rooms = it.rooms.begin(command), busy = it.busy + id, error = null) }
        var result: Outcome<HomeAction> =
            pilot.homeAction(command.entity, command.action, command.value, roomId, command.option)
        val held = result.valueOrNull()?.takeIf { it.confirmationRequired && it.status == "pending" }
        if (held != null) {
            if (userConfirmed) {
                result = pilot.confirmHomeAction(held.id)
            } else {
                val prompt = ConfirmPrompt(
                    title = "${words(command.action)} ${command.entity.displayName}?",
                    message = "Pilot Core asks you to confirm this before it does anything.",
                    confirmLabel = words(command.action),
                    destructive = held.risk == "high",
                )
                _local.update {
                    it.copy(
                        rooms = it.rooms.rollback(id),
                        busy = it.busy - id,
                        confirm = PendingConfirm(roomId, command, prompt, serverActionId = held.id),
                    )
                }
                return Sent.Held
            }
        }
        return finish(id, result)
    }

    private fun finish(entityId: String, result: Outcome<HomeAction>): Sent = when (result) {
        is Outcome.Success -> {
            _local.update { it.copy(busy = it.busy - entityId) }
            Sent.Done
        }
        is Outcome.Failure -> {
            _local.update { it.copy(rooms = it.rooms.rollback(entityId), busy = it.busy - entityId) }
            Sent.Failed(result.error.message)
        }
    }

    private sealed interface Sent {
        data object Done : Sent
        /** Pilot Core is holding the action until the user confirms in the dialog now showing. */
        data object Held : Sent
        data class Failed(val message: String) : Sent
    }

    /** False (with an inline explanation) when commands cannot be sent right now. */
    private fun ready(): Boolean {
        val message = when {
            !pilot.snapshot.value.isLive -> "Reconnect to control devices. Saved data is read-only."
            !pilot.canControlHome -> "This phone can view room devices but not control them."
            else -> return true
        }
        _local.update { it.copy(error = message) }
        return false
    }

    private fun showError(message: String) = _local.update { it.copy(error = message) }

    // ---- Media in the open room -------------------------------------------------------------

    override fun media(command: MediaCommand) {
        if (!pilot.snapshot.value.isLive) {
            _local.update { it.copy(error = "Reconnect to control playback. Saved data is read-only.") }
            return
        }
        viewModelScope.launch {
            _local.update { it.copy(mediaBusy = true, error = null) }
            pilot.media(command).onFailure { showError(it.message) }
            _local.update { it.copy(mediaBusy = false) }
        }
    }
}
