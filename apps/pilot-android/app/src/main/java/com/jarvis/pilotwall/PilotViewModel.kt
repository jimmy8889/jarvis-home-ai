package com.jarvis.pilotwall

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.Duration
import java.time.Instant
import java.util.concurrent.atomic.AtomicLong

data class PilotUiState(
    val config: PilotConfig = PilotConfig(),
    val configured: Boolean = false,
    val connection: ConnectionState = ConnectionState.Unconfigured,
    val snapshot: PilotSnapshot? = null,
    val selectedRoomId: String? = null,
    val error: String? = null,
    val actionInFlight: Boolean = false,
    val searchQuery: String = "",
    val searchResults: List<MusicSearchResult> = emptyList(),
    val searching: Boolean = false,
    val chat: List<ChatMessage> = listOf(
        ChatMessage(0, ChatRole.Pilot, "Good evening. What can I help with?"),
    ),
    val conversationId: String? = null,
    val assistantBusy: Boolean = false,
    val home: HomeProjection? = null,
    val homeLoading: Boolean = false,
    val homeError: String? = null,
    val activeHomeEntityId: String? = null,
    val pendingHomeAction: HomeAction? = null,
) {
    val rooms: List<PilotRoom> get() = snapshot?.media?.rooms.orEmpty()
    val selectedRoom: PilotRoom?
        get() = rooms.firstOrNull { it.id == selectedRoomId } ?: rooms.firstOrNull()
    val isStale: Boolean
        get() = snapshot?.receivedAt?.let { Duration.between(it, Instant.now()).seconds > 60 } ?: false
}

class PilotViewModel(application: Application) : AndroidViewModel(application) {
    private val preferences = PilotPreferences(application)
    private val messages = AtomicLong(1)
    private val _state = MutableStateFlow(
        PilotUiState(
            config = preferences.config(),
            configured = !preferences.token().isNullOrBlank(),
            connection = if (preferences.token().isNullOrBlank()) {
                ConnectionState.Unconfigured
            } else {
                ConnectionState.Loading
            },
        ),
    )
    val state: StateFlow<PilotUiState> = _state.asStateFlow()
    private var pollJob: Job? = null

    init {
        if (_state.value.configured) startPolling()
    }

    fun refresh() {
        val config = _state.value.config
        val token = preferences.token() ?: return
        viewModelScope.launch {
            if (_state.value.snapshot == null) {
                _state.update { it.copy(connection = ConnectionState.Loading, error = null) }
            }
            runCatching { PilotCoreClient(config, token).snapshot() }
                .onSuccess { snapshot ->
                    val selectedRoomId = _state.value.selectedRoomId
                        ?: snapshot.media.rooms.firstOrNull()?.id
                    _state.update {
                        it.copy(
                            snapshot = snapshot,
                            connection = ConnectionState.Online,
                            selectedRoomId = selectedRoomId,
                            error = null,
                        )
                    }
                    selectedRoomId?.let { refreshHome(it, silent = true) }
                }
                .onFailure { error ->
                    _state.update {
                        it.copy(
                            connection = if (it.snapshot == null) {
                                ConnectionState.Offline
                            } else {
                                ConnectionState.Stale
                            },
                            error = friendlyError(error),
                        )
                    }
                }
        }
    }

    fun connect(coreUrl: String, deviceId: String, token: String) {
        val config = runCatching {
            require(deviceId.isNotBlank()) { "Device ID is required" }
            require(token.isNotBlank()) { "Device token is required" }
            _state.value.config.copy(
                coreUrl = CoreAddressPolicy.normalize(coreUrl),
                deviceId = deviceId.trim(),
            )
        }.getOrElse { error ->
            _state.update { it.copy(error = error.message ?: "Check the connection details.") }
            return
        }
        _state.update { it.copy(connection = ConnectionState.Loading, error = null) }
        viewModelScope.launch {
            runCatching { PilotCoreClient(config, token.trim()).testConnection() }
                .onSuccess {
                    preferences.save(config, token)
                    _state.update {
                        it.copy(
                            config = config,
                            configured = true,
                            connection = ConnectionState.Loading,
                            error = null,
                        )
                    }
                    startPolling()
                }
                .onFailure { error ->
                    _state.update {
                        it.copy(connection = ConnectionState.Unconfigured, error = friendlyError(error))
                    }
                }
        }
    }

    fun updateSettings(refreshSeconds: Int, keepScreenOn: Boolean, nightMode: NightMode) {
        val config = _state.value.config.copy(
            refreshSeconds = refreshSeconds.coerceIn(5, 300),
            keepScreenOn = keepScreenOn,
            nightMode = nightMode,
        )
        preferences.save(config)
        _state.update { it.copy(config = config) }
        startPolling()
    }

    fun disconnect() {
        pollJob?.cancel()
        preferences.clearCredentials()
        _state.value = PilotUiState(config = preferences.config())
    }

    fun selectRoom(roomId: String) {
        _state.update {
            it.copy(selectedRoomId = roomId, home = null, homeError = null)
        }
        refreshHome(roomId)
    }

    fun refreshHome(roomId: String? = _state.value.selectedRoom?.id, silent: Boolean = false) {
        val token = preferences.token() ?: return
        val selected = roomId ?: return
        viewModelScope.launch {
            if (!silent) _state.update { it.copy(homeLoading = true, homeError = null) }
            runCatching {
                PilotCoreClient(_state.value.config, token).home(selected)
            }.onSuccess { projection ->
                if (_state.value.selectedRoom?.id == selected) {
                    _state.update {
                        it.copy(home = projection, homeLoading = false, homeError = null)
                    }
                }
            }.onFailure { error ->
                _state.update {
                    it.copy(homeLoading = false, homeError = friendlyError(error))
                }
            }
        }
    }

    fun homeAction(entity: HomeEntity, action: String, value: Double? = null) {
        val token = preferences.token() ?: return
        val roomId = _state.value.selectedRoom?.id ?: return
        viewModelScope.launch {
            _state.update {
                it.copy(activeHomeEntityId = entity.entityId, homeError = null)
            }
            runCatching {
                PilotCoreClient(_state.value.config, token)
                    .homeAction(roomId, entity.entityId, action, value)
            }.onSuccess { result ->
                if (result.confirmationRequired && result.status == "pending") {
                    _state.update { it.copy(pendingHomeAction = result) }
                } else {
                    refreshHome(roomId, silent = true)
                }
            }.onFailure { error ->
                _state.update { it.copy(homeError = friendlyError(error)) }
            }
            _state.update { it.copy(activeHomeEntityId = null) }
        }
    }

    fun confirmHomeAction() {
        val token = preferences.token() ?: return
        val pending = _state.value.pendingHomeAction ?: return
        viewModelScope.launch {
            _state.update { it.copy(activeHomeEntityId = pending.entityId) }
            runCatching {
                PilotCoreClient(_state.value.config, token).confirmHomeAction(pending.id)
            }.onSuccess {
                _state.update { state -> state.copy(pendingHomeAction = null) }
                refreshHome(silent = true)
            }.onFailure { error ->
                _state.update { it.copy(homeError = friendlyError(error)) }
            }
            _state.update { it.copy(activeHomeEntityId = null) }
        }
    }

    fun cancelHomeAction() {
        _state.update { it.copy(pendingHomeAction = null) }
    }

    fun media(command: MediaCommand) {
        val token = preferences.token() ?: return
        val targetPlayer = command.playerId ?: _state.value.selectedRoom?.defaultMusicPlayerId
        val resolved = command.copy(playerId = targetPlayer)
        viewModelScope.launch {
            _state.update { it.copy(actionInFlight = true, error = null) }
            runCatching { PilotCoreClient(_state.value.config, token).mediaCommand(resolved) }
                .onSuccess { refresh() }
                .onFailure { error -> _state.update { it.copy(error = friendlyError(error)) } }
            _state.update { it.copy(actionInFlight = false) }
        }
    }

    fun setSearchQuery(value: String) {
        _state.update { it.copy(searchQuery = value) }
    }

    fun search() {
        val query = _state.value.searchQuery.trim()
        val token = preferences.token() ?: return
        if (query.isEmpty()) return
        viewModelScope.launch {
            _state.update { it.copy(searching = true, error = null) }
            runCatching { PilotCoreClient(_state.value.config, token).search(query) }
                .onSuccess { results -> _state.update { it.copy(searchResults = results) } }
                .onFailure { error -> _state.update { it.copy(error = friendlyError(error)) } }
            _state.update { it.copy(searching = false) }
        }
    }

    fun play(result: MusicSearchResult) {
        media(MediaCommand(action = "play_media", mediaUri = result.uri))
    }

    fun ask(text: String) {
        val trimmed = text.trim()
        val token = preferences.token() ?: return
        val roomId = _state.value.selectedRoom?.id ?: return
        if (trimmed.isEmpty() || _state.value.assistantBusy) return
        val user = ChatMessage(messages.getAndIncrement(), ChatRole.User, trimmed)
        _state.update { it.copy(chat = it.chat + user, assistantBusy = true, error = null) }
        viewModelScope.launch {
            runCatching {
                PilotCoreClient(_state.value.config, token)
                    .ask(trimmed, roomId, _state.value.conversationId)
            }.onSuccess { reply ->
                _state.update {
                    it.copy(
                        chat = it.chat + ChatMessage(
                            messages.getAndIncrement(),
                            ChatRole.Pilot,
                            reply.text,
                        ),
                        conversationId = reply.conversationId,
                    )
                }
            }.onFailure { error ->
                _state.update {
                    it.copy(
                        chat = it.chat + ChatMessage(
                            messages.getAndIncrement(),
                            ChatRole.Pilot,
                            "I couldn't reach Pilot Core. ${friendlyError(error)}",
                        ),
                        error = friendlyError(error),
                    )
                }
            }
            _state.update { it.copy(assistantBusy = false) }
        }
    }

    private fun startPolling() {
        pollJob?.cancel()
        if (!_state.value.configured) return
        pollJob = viewModelScope.launch {
            while (true) {
                refresh()
                delay(_state.value.config.refreshSeconds * 1_000L)
            }
        }
    }

    private fun friendlyError(error: Throwable): String = when (error) {
        is PilotApiException -> when (error.status) {
            401 -> "This tablet's device token was rejected."
            403 -> "This tablet does not have the required Pilot capability."
            404 -> "The registered Pilot device could not be found."
            else -> error.message
        }
        else -> error.message ?: "Pilot Core is unavailable."
    }
}
