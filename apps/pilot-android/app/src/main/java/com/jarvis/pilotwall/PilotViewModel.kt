package com.jarvis.pilotwall

import android.app.Application
import android.content.pm.PackageManager
import android.util.LruCache
import androidx.core.content.ContextCompat
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
    val manifest: ClientManifest? = null,
    val eventCursor: String? = null,
    val liveEventsConnected: Boolean = false,
    val assistantPhase: AssistantPhase = AssistantPhase.Idle,
    val assistantCards: List<AssistantCard> = emptyList(),
    val assistantSources: List<AssistantSource> = emptyList(),
    val pairingPayload: String? = null,
    val pairingBusy: Boolean = false,
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
    private var eventJob: Job? = null
    private var assistantJob: Job? = null
    private var voiceTimeoutJob: Job? = null
    private val voiceCapture = PilotVoiceCapture()
    private val replyPlayer = PilotReplyPlayer(application)
    private val artworkCache = object : LruCache<String, ByteArray>(24 * 1024 * 1024) {
        override fun sizeOf(key: String, value: ByteArray): Int = value.size
    }

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

    fun handlePairingUri(value: String?) {
        value?.takeIf(String::isNotBlank)?.let { payload ->
            _state.update { it.copy(pairingPayload = payload, error = null) }
        }
    }

    fun redeemBootstrap(coreUrl: String, grantOrUri: String) {
        if (_state.value.pairingBusy) return
        val pairing = runCatching { PairingPayload.parse(grantOrUri, coreUrl) }
            .getOrElse { error ->
                _state.update { it.copy(error = error.message ?: "Check the pairing code.") }
                return
            }
        _state.update { it.copy(pairingBusy = true, connection = ConnectionState.Loading, error = null) }
        viewModelScope.launch {
            runCatching {
                PilotCoreClient.redeemBootstrap(pairing.coreUrl, pairing.grantToken)
            }.onSuccess { registration ->
                val config = _state.value.config.copy(
                    coreUrl = pairing.coreUrl,
                    deviceId = registration.deviceId,
                )
                preferences.save(config, registration.deviceToken)
                _state.update {
                    it.copy(
                        config = config,
                        configured = true,
                        connection = ConnectionState.Loading,
                        pairingPayload = null,
                        error = null,
                    )
                }
                startPolling()
            }.onFailure { error ->
                _state.update {
                    it.copy(connection = ConnectionState.Unconfigured, error = friendlyError(error))
                }
            }
            _state.update { it.copy(pairingBusy = false) }
        }
    }

    fun updateSettings(
        refreshSeconds: Int,
        keepScreenOn: Boolean,
        nightMode: NightMode,
        kioskMode: Boolean = _state.value.config.kioskMode,
        ambientAfterMinutes: Int = _state.value.config.ambientAfterMinutes,
    ) {
        val config = _state.value.config.copy(
            refreshSeconds = refreshSeconds.coerceIn(5, 300),
            keepScreenOn = keepScreenOn,
            nightMode = nightMode,
            kioskMode = kioskMode,
            ambientAfterMinutes = ambientAfterMinutes.coerceIn(1, 60),
        )
        preferences.save(config)
        _state.update { it.copy(config = config) }
        startPolling()
    }

    fun updateDisplayBrightness(brightnessPercent: Int) {
        val config = _state.value.config.copy(
            displayBrightnessPercent = brightnessPercent.coerceIn(
                MIN_DISPLAY_BRIGHTNESS_PERCENT,
                MAX_DISPLAY_BRIGHTNESS_PERCENT,
            ),
        )
        preferences.save(config)
        _state.update { it.copy(config = config) }
    }

    fun disconnect() {
        pollJob?.cancel()
        eventJob?.cancel()
        assistantJob?.cancel()
        voiceTimeoutJob?.cancel()
        voiceCapture.cancel()
        replyPlayer.stop()
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
        val previous = _state.value.home
        val optimistic = optimisticEntity(entity, action, value)
        if (optimistic != entity) {
            _state.update { state ->
                state.copy(
                    home = state.home?.copy(
                        entities = state.home.entities.map {
                            if (it.entityId == entity.entityId) optimistic else it
                        },
                    ),
                )
            }
        }
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
                _state.update { it.copy(home = previous, homeError = friendlyError(error)) }
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

    fun dashboardAction(action: String, value: String) {
        val token = preferences.token() ?: return
        viewModelScope.launch {
            _state.update { it.copy(actionInFlight = true, error = null) }
            runCatching { PilotCoreClient(_state.value.config, token).dashboardAction(action, value) }
                .onSuccess { refresh() }
                .onFailure { error -> _state.update { it.copy(error = friendlyError(error)) } }
            _state.update { it.copy(actionInFlight = false) }
        }
    }

    fun transferMedia(targetRoomId: String) {
        val source = _state.value.snapshot?.media?.players?.firstOrNull {
            it.player.roomId == _state.value.selectedRoom?.id &&
                it.effective.playbackState in setOf("playing", "paused")
        } ?: return
        val target = _state.value.rooms.firstOrNull { it.id == targetRoomId } ?: return
        media(
            MediaCommand(
                action = "transfer",
                playerId = source.player.id,
                targetRoomId = target.id,
                targetPlayerId = target.defaultMusicPlayerId,
            ),
        )
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

    suspend fun artwork(url: String): ByteArray? {
        artworkCache.get(url)?.let { return it }
        val token = preferences.token() ?: return null
        return runCatching { PilotCoreClient(_state.value.config, token).artworkAsset(url) }
            .getOrNull()
            ?.also { artworkCache.put(url, it) }
    }

    fun ask(text: String) {
        val trimmed = text.trim()
        val token = preferences.token() ?: return
        val roomId = _state.value.selectedRoom?.id ?: return
        if (trimmed.isEmpty() || _state.value.assistantBusy) return
        val user = ChatMessage(messages.getAndIncrement(), ChatRole.User, trimmed)
        _state.update {
            it.copy(
                chat = it.chat + user,
                assistantBusy = true,
                assistantPhase = AssistantPhase.Processing,
                assistantCards = emptyList(),
                assistantSources = emptyList(),
                error = null,
            )
        }
        assistantJob = viewModelScope.launch {
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
                        assistantCards = reply.cards,
                        assistantSources = reply.sources,
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
                        assistantPhase = AssistantPhase.Failed,
                    )
                }
            }
            _state.update {
                it.copy(
                    assistantBusy = false,
                    assistantPhase = if (it.assistantPhase == AssistantPhase.Failed) {
                        AssistantPhase.Failed
                    } else AssistantPhase.Idle,
                )
            }
        }
    }

    fun startVoiceCapture() {
        if (_state.value.assistantPhase != AssistantPhase.Idle &&
            _state.value.assistantPhase != AssistantPhase.Failed
        ) return
        val permission = ContextCompat.checkSelfPermission(
            getApplication(),
            android.Manifest.permission.RECORD_AUDIO,
        )
        if (permission != PackageManager.PERMISSION_GRANTED) {
            _state.update {
                it.copy(
                    assistantPhase = AssistantPhase.Failed,
                    error = "Microphone permission is required for Talk to Pilot.",
                )
            }
            return
        }
        runCatching { voiceCapture.start() }
            .onSuccess {
                _state.update {
                    it.copy(
                        assistantPhase = AssistantPhase.Listening,
                        assistantCards = emptyList(),
                        assistantSources = emptyList(),
                        error = null,
                    )
                }
                voiceTimeoutJob?.cancel()
                voiceTimeoutJob = viewModelScope.launch {
                    delay(15_000)
                    stopVoiceCapture()
                }
            }
            .onFailure { error ->
                _state.update {
                    it.copy(assistantPhase = AssistantPhase.Failed, error = friendlyError(error))
                }
            }
    }

    fun stopVoiceCapture() {
        if (_state.value.assistantPhase != AssistantPhase.Listening) return
        voiceTimeoutJob?.cancel()
        val audio = voiceCapture.stop()
        if (audio.size < PilotVoiceCapture.SAMPLE_RATE) {
            _state.update {
                it.copy(
                    assistantPhase = AssistantPhase.Failed,
                    error = "I didn't hear enough audio. Hold Talk to Pilot a little longer.",
                )
            }
            return
        }
        val token = preferences.token() ?: return
        _state.update {
            it.copy(
                assistantPhase = AssistantPhase.Processing,
                assistantBusy = true,
                error = null,
            )
        }
        assistantJob = viewModelScope.launch {
            val client = PilotCoreClient(_state.value.config, token)
            runCatching { client.voice(audio, conversationId = _state.value.conversationId) }
                .onSuccess { reply ->
                    val transcript = reply.transcript?.takeIf(String::isNotBlank)
                    val messagesToAdd = buildList {
                        transcript?.let {
                            add(ChatMessage(messages.getAndIncrement(), ChatRole.User, it))
                        }
                        add(ChatMessage(messages.getAndIncrement(), ChatRole.Pilot, reply.text))
                    }
                    _state.update {
                        it.copy(
                            chat = it.chat + messagesToAdd,
                            conversationId = reply.conversationId,
                            assistantCards = reply.cards,
                            assistantSources = reply.sources,
                        )
                    }
                    val audioPath = reply.audioDownloadUrl
                    if (audioPath == null) {
                        _state.update {
                            it.copy(assistantBusy = false, assistantPhase = AssistantPhase.Idle)
                        }
                    } else {
                        runCatching { client.audioAsset(audioPath) }
                            .onSuccess { speech ->
                                _state.update { it.copy(assistantPhase = AssistantPhase.Speaking) }
                                replyPlayer.play(speech) { result ->
                                    _state.update {
                                        it.copy(
                                            assistantBusy = false,
                                            assistantPhase = if (result.isSuccess) {
                                                AssistantPhase.Idle
                                            } else AssistantPhase.Failed,
                                            error = result.exceptionOrNull()?.message,
                                        )
                                    }
                                }
                            }
                            .onFailure { error ->
                                _state.update {
                                    it.copy(
                                        assistantBusy = false,
                                        assistantPhase = AssistantPhase.Failed,
                                        error = "Pilot answered, but speech playback failed: ${friendlyError(error)}",
                                    )
                                }
                            }
                    }
                }
                .onFailure { error ->
                    _state.update {
                        it.copy(
                            assistantBusy = false,
                            assistantPhase = AssistantPhase.Failed,
                            error = friendlyError(error),
                        )
                    }
                }
        }
    }

    fun cancelAssistant() {
        voiceTimeoutJob?.cancel()
        if (_state.value.assistantPhase == AssistantPhase.Listening) voiceCapture.cancel()
        assistantJob?.cancel()
        replyPlayer.stop()
        _state.update {
            it.copy(assistantBusy = false, assistantPhase = AssistantPhase.Idle, error = null)
        }
    }

    private fun startPolling() {
        pollJob?.cancel()
        eventJob?.cancel()
        if (!_state.value.configured) return
        startEventSync()
        pollJob = viewModelScope.launch {
            while (true) {
                refresh()
                val seconds = if (_state.value.liveEventsConnected) 60
                else _state.value.config.refreshSeconds
                delay(seconds * 1_000L)
            }
        }
    }

    private fun startEventSync() {
        val token = preferences.token() ?: return
        eventJob = viewModelScope.launch {
            val client = PilotCoreClient(_state.value.config, token)
            val manifest = runCatching { client.manifest() }.getOrNull()
            _state.update { it.copy(manifest = manifest) }
            val snapshotPath = manifest?.eventSnapshotPath ?: return@launch
            val eventPath = manifest.eventLongPollPath
                ?: snapshotPath.removeSuffix("/snapshot")
            var cursor = _state.value.eventCursor
            runCatching { client.eventSnapshotCursor(snapshotPath, cursor) }
                .onSuccess { snapshotCursor ->
                    cursor = snapshotCursor ?: cursor
                    _state.update { it.copy(eventCursor = cursor) }
                    refresh()
                }
            var delayMs = 1_000L
            while (true) {
                runCatching { client.events(eventPath, cursor) }
                    .onSuccess { page ->
                        cursor = page.cursor ?: cursor
                        _state.update {
                            it.copy(
                                eventCursor = cursor,
                                liveEventsConnected = true,
                            )
                        }
                        if (page.resetRequired || page.events.isNotEmpty()) refresh()
                        delayMs = if (page.events.isEmpty()) 2_000L else 250L
                    }
                    .onFailure {
                        _state.update { it.copy(liveEventsConnected = false) }
                        delayMs = (delayMs * 2).coerceAtMost(30_000L)
                    }
                delay(delayMs)
            }
        }
    }

    private fun optimisticEntity(entity: HomeEntity, action: String, value: Double?): HomeEntity =
        when (action) {
            "turn_on" -> entity.copy(state = "on")
            "turn_off" -> entity.copy(state = "off")
            "lock" -> entity.copy(state = "locked")
            "unlock" -> entity.copy(state = "unlocked")
            "open" -> entity.copy(state = "opening")
            "close" -> entity.copy(state = "closing")
            "set_brightness" -> entity.copy(brightnessPercent = value?.toFloat())
            "set_position" -> entity.copy(positionPercent = value?.toFloat())
            "set_percentage" -> entity.copy(percentage = value?.toFloat())
            "set_temperature" -> entity.copy(targetTemperature = value)
            else -> entity
        }

    private fun friendlyError(error: Throwable): String = when (error) {
        is PilotApiException -> when (error.status) {
            401 -> "This tablet's device token was rejected."
            403 -> "This tablet does not have the required Pilot capability."
            404 -> "The registered Pilot device could not be found."
            409 -> error.message
            422 -> error.message
            503 -> "Pilot Core is online, but one of its local services is unavailable."
            else -> error.message
        }
        else -> error.message ?: "Pilot Core is unavailable."
    }
}
