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
                    _state.update {
                        it.copy(
                            snapshot = snapshot,
                            connection = ConnectionState.Online,
                            selectedRoomId = it.selectedRoomId
                                ?: snapshot.media.rooms.firstOrNull()?.id,
                            error = null,
                        )
                    }
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
        _state.update { it.copy(selectedRoomId = roomId) }
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
