package com.jameshazell.pilot.data.jarvis

import com.jameshazell.pilot.core.AppDispatchers
import com.jameshazell.pilot.core.AppError
import com.jameshazell.pilot.core.AppException
import com.jameshazell.pilot.core.ErrorKind
import com.jameshazell.pilot.core.Outcome
import com.jameshazell.pilot.core.SecretStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** The link to the laptop bridge. */
sealed interface JarvisConnection {
    /** Stored state has not been read yet. */
    data object Loading : JarvisConnection
    data object NotPaired : JarvisConnection
    /** Paired; no answer yet. */
    data object Checking : JarvisConnection
    /** The bridge answers. [JarvisHealth.connected] false means its model services are down. */
    data class Connected(val health: JarvisHealth) : JarvisConnection
    /** Laptop asleep, off, or Tailscale down. Attempt [attempt] follows in [retryInSeconds] s. */
    data class Unreachable(val attempt: Int, val retryInSeconds: Int) : JarvisConnection
    /** The bridge refused the stored token: pair again. */
    data object Unauthorized : JarvisConnection
}

/**
 * @param host the paired bridge (`100.x.y.z:18765`), for display.
 * @param offered a `pilot://jarvis` link waiting for the user to confirm in the pairing sheet.
 */
data class JarvisPairing(
    val host: String? = null,
    val offered: JarvisPairingLink? = null,
    val busy: Boolean = false,
    val error: String? = null,
) {
    val paired: Boolean get() = host != null
}

/** @param receivedAtMs monotonic time of [sample]; see [fresh]. */
data class JarvisTelemetryState(val sample: JarvisTelemetry? = null, val receivedAtMs: Long = 0) {
    /** Readings older than 15 s are shown as unavailable, as in the JARVIS app. */
    fun fresh(nowMs: Long): Boolean = sample != null && nowMs - receivedAtMs < JarvisProtocol.TELEMETRY_STALE_MS
}

/** A finished turn handed to the screen so it can speak. [audio] is the Voice Studio WAV, if any. */
class JarvisReply(val text: String, val audio: ByteArray?, val mode: JarvisVoiceMode, val speechError: String?)

/**
 * JARVIS: pairing, connection, telemetry, the conversation and the one turn that may be in
 * flight. Nothing here talks to the laptop unless [setVisible] is true (health, telemetry) or
 * the user starts a turn.
 */
class JarvisRepository(
    private val scope: CoroutineScope,
    private val dispatchers: AppDispatchers,
    private val api: JarvisApi,
    private val store: SecretStore,
    private val clockMs: () -> Long = { System.nanoTime() / 1_000_000 },
) {
    private val _connection = MutableStateFlow<JarvisConnection>(JarvisConnection.Loading)
    val connection: StateFlow<JarvisConnection> = _connection.asStateFlow()

    private val _pairing = MutableStateFlow(JarvisPairing())
    val pairing: StateFlow<JarvisPairing> = _pairing.asStateFlow()

    private val _telemetry = MutableStateFlow(JarvisTelemetryState())
    val telemetry: StateFlow<JarvisTelemetryState> = _telemetry.asStateFlow()

    private val _conversation = MutableStateFlow<List<JarvisMessage>>(emptyList())
    /** Finished exchanges, newest last. Saved encrypted on this phone; [clearConversation] removes them. */
    val conversation: StateFlow<List<JarvisMessage>> = _conversation.asStateFlow()

    private val _turn = MutableStateFlow(JarvisTurnState())
    val turn: StateFlow<JarvisTurnState> = _turn.asStateFlow()

    private val _voiceMode = MutableStateFlow(JarvisVoiceMode.VoiceStudio)
    val voiceMode: StateFlow<JarvisVoiceMode> = _voiceMode.asStateFlow()

    private val _replies = MutableSharedFlow<JarvisReply>(extraBufferCapacity = 4, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    /** Each completed turn, once, for whoever speaks it. */
    val replies: SharedFlow<JarvisReply> = _replies.asSharedFlow()

    private var credentials: JarvisCredentials? = null
    private var loaded = false
    private var visible = false
    private var linkJob: Job? = null
    private var telemetryJob: Job? = null
    private var turnJob: Job? = null

    fun clock(): Long = clockMs()

    /** Reads the stored pairing, conversation and voice mode. Safe to call repeatedly. */
    suspend fun load() {
        if (loaded) return
        val (saved, history, mode) = withContext(dispatchers.io) {
            Triple(
                runCatching { JarvisCredentials.fromJson(store.get(KEY_CREDENTIALS)) }.getOrNull(),
                runCatching { JarvisProtocol.messages(store.get(KEY_HISTORY)) }.getOrDefault(emptyList()),
                runCatching { JarvisVoiceMode.byId(store.get(KEY_VOICE_MODE)?.toIntOrNull()) }.getOrDefault(JarvisVoiceMode.VoiceStudio),
            )
        }
        loaded = true
        credentials = saved
        _conversation.value = history
        _voiceMode.value = mode
        _pairing.update { it.copy(host = saved?.baseUrl?.let(JarvisAddress::display)) }
        _connection.value = if (saved == null) JarvisConnection.NotPaired else JarvisConnection.Checking
        if (visible) startLink()
    }

    /** @return true when [uri] is a JARVIS pairing link (and is now waiting in [pairing]). */
    fun offerPairingLink(uri: String?): Boolean {
        val link = JarvisPairingLink.parse(uri) ?: return false
        _pairing.update { it.copy(offered = link, error = null) }
        return true
    }

    fun dismissOfferedLink() = _pairing.update { it.copy(offered = null, error = null) }

    /** Redeems a one-time pairing code. The code is not stored; the token is, encrypted. */
    suspend fun pair(address: String, code: String): Outcome<Unit> {
        if (_pairing.value.busy) return Outcome.Failure(AppError(ErrorKind.Rejected, "Pairing is already in progress."))
        val baseUrl = try {
            JarvisAddress.normalize(address)
        } catch (error: IllegalArgumentException) {
            return fail(AppError(ErrorKind.Invalid, error.message ?: "That address isn't valid."))
        }
        if (code.isBlank()) return fail(AppError(ErrorKind.Invalid, "Enter the one-time pairing code from the laptop."))
        _pairing.update { it.copy(busy = true, error = null) }
        return try {
            val token = api.pair(baseUrl, code.trim())
            val paired = JarvisCredentials(baseUrl, token)
            withContext(dispatchers.io) { store.put(KEY_CREDENTIALS, paired.toJson()) }
            credentials = paired
            _pairing.value = JarvisPairing(host = JarvisAddress.display(baseUrl))
            _connection.value = JarvisConnection.Checking
            if (visible) startLink()
            Outcome.Success(Unit)
        } catch (cancelled: CancellationException) {
            _pairing.update { it.copy(busy = false) }
            throw cancelled
        } catch (error: Exception) {
            val problem = jarvisError(error)
            fail(if (problem.kind == ErrorKind.Unauthorized) problem.copy(message = "Pairing code is invalid or already used.") else problem)
        }
    }

    private fun fail(error: AppError): Outcome<Unit> {
        _pairing.update { it.copy(busy = false, error = error.message) }
        return Outcome.Failure(error)
    }

    /** Forgets the bridge on this phone. The laptop's token is not revoked. */
    suspend fun unpair() {
        stopTurn()
        linkJob?.cancel()
        telemetryJob?.cancel()
        credentials = null
        withContext(dispatchers.io) { runCatching { store.remove(KEY_CREDENTIALS) } }
        _pairing.value = JarvisPairing()
        _telemetry.value = JarvisTelemetryState()
        _connection.value = JarvisConnection.NotPaired
    }

    /** The JARVIS tab came into or went out of view. Nothing is polled while it is hidden. */
    fun setVisible(nowVisible: Boolean) {
        if (visible == nowVisible) return
        visible = nowVisible
        if (nowVisible) startLink() else {
            linkJob?.cancel()
            telemetryJob?.cancel()
        }
    }

    /** Try the bridge now instead of waiting out the backoff. */
    fun retryNow() {
        if (visible) startLink()
    }

    /**
     * One loop decides the connection state: `/health` now, then every 30 s while it answers,
     * or with exponential backoff while it doesn't. A rejected token ends the loop.
     */
    private fun startLink() {
        val current = credentials ?: return
        linkJob?.cancel()
        linkJob = scope.launch {
            var attempt = 0
            if (_connection.value !is JarvisConnection.Connected) _connection.value = JarvisConnection.Checking
            while (isActive) {
                val wait = try {
                    _connection.value = JarvisConnection.Connected(api.health(current))
                    attempt = 0
                    startTelemetry(current)
                    JarvisProtocol.HEALTH_INTERVAL_MS
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (error: Exception) {
                    telemetryJob?.cancel()
                    if (jarvisError(error).kind == ErrorKind.Unauthorized) {
                        _connection.value = JarvisConnection.Unauthorized
                        return@launch
                    }
                    attempt++
                    JarvisBackoff.delayMs(attempt).also {
                        _connection.value = JarvisConnection.Unreachable(attempt, ((it + 999) / 1000).toInt())
                    }
                }
                delay(wait)
            }
        }
    }

    /** One request at a time, every 3 s, only while visible and the bridge is answering. */
    private fun startTelemetry(current: JarvisCredentials) {
        if (telemetryJob?.isActive == true) return
        telemetryJob = scope.launch {
            while (isActive) {
                try {
                    _telemetry.value = JarvisTelemetryState(api.telemetry(current), clockMs())
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (_: Exception) {
                    // The last sample simply goes stale; the health loop owns "unreachable".
                }
                delay(JarvisProtocol.TELEMETRY_INTERVAL_MS)
            }
        }
    }

    fun setVoiceMode(mode: JarvisVoiceMode) {
        _voiceMode.value = mode
        scope.launch(dispatchers.io) { runCatching { store.put(KEY_VOICE_MODE, mode.id.toString(), durable = false) } }
    }

    /** Listening and speaking happen on the phone; the screen reports them here. */
    fun report(event: JarvisTurnEvent) = _turn.update { JarvisTurnMachine.reduce(it, event) }

    /**
     * Sends a typed or recognised [text], or a recording ([wav]) for the laptop to transcribe.
     * Ignored while another turn is in flight: there is never more than one.
     *
     * @return false when nothing was sent.
     */
    fun submit(text: String, wav: ByteArray?): Boolean {
        val current = credentials
        if (current == null || _turn.value.inFlight || turnJob?.isCompleted == false) return false
        val message = text.trim().take(JarvisProtocol.MAX_TEXT)
        if (message.isEmpty() && wav == null) return false
        val mode = _voiceMode.value
        val history = _conversation.value
        report(JarvisTurnEvent.Submitted(message, audio = wav != null))
        turnJob = scope.launch {
            var id: String? = null
            try {
                // Not cancellable: if the laptop accepted the turn we must learn its id to cancel it.
                val started = withContext(NonCancellable) { api.startTurn(current, message, history, mode.bridgeSpeaks, wav) }
                id = started.id
                val deadline = clockMs() + JarvisProtocol.TURN_DEADLINE_MS
                while (true) {
                    if (!isActive) throw CancellationException()
                    val snapshot = api.turn(current, started.id)
                    report(JarvisTurnEvent.Snapshot(snapshot))
                    when (snapshot.stage) {
                        JarvisStage.Error -> throw AppException(AppError(ErrorKind.Rejected, snapshot.error ?: "The laptop could not reply."))
                        JarvisStage.Cancelled -> {
                            report(JarvisTurnEvent.Stopped)
                            return@launch
                        }
                        JarvisStage.Done -> {
                            finish(current, snapshot, mode)
                            return@launch
                        }
                        else -> Unit
                    }
                    if (clockMs() > deadline) throw AppException(AppError(ErrorKind.Timeout, "The laptop took too long to reply. Please retry."))
                    delay(JarvisProtocol.TURN_POLL_MS)
                }
            } catch (cancelled: CancellationException) {
                id?.let { running -> scope.launch { runCatching { api.cancel(current, running) } } }
                throw cancelled
            } catch (error: Exception) {
                val problem = jarvisError(error)
                id?.let { running -> scope.launch { runCatching { api.cancel(current, running) } } }
                report(JarvisTurnEvent.Failed(problem.message))
                when (problem.kind) {
                    ErrorKind.Unauthorized -> {
                        linkJob?.cancel()
                        telemetryJob?.cancel()
                        _connection.value = JarvisConnection.Unauthorized
                    }
                    ErrorKind.Offline -> if (visible) startLink()
                    else -> Unit
                }
            }
        }
        return true
    }

    private suspend fun finish(current: JarvisCredentials, done: JarvisTurn, mode: JarvisVoiceMode) {
        var speechError = done.speechError
        val audio = if (done.audioReady && mode == JarvisVoiceMode.VoiceStudio) {
            try {
                api.audio(current, done.id)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                speechError = "The spoken reply couldn't be fetched. Your text reply is above."
                null
            }
        } else null
        val history = JarvisProtocol.appended(_conversation.value, done.transcript, done.reply)
        _conversation.value = history
        saveHistory(history)
        report(JarvisTurnEvent.Completed(done.copy(speechError = speechError)))
        _replies.tryEmit(JarvisReply(done.reply, audio, mode, speechError))
    }

    /** Cancels the turn in flight (also on the laptop) and returns to standby. */
    fun stopTurn() {
        turnJob?.cancel()
        report(JarvisTurnEvent.Stopped)
    }

    /** Removes the saved conversation from this phone. Refused while a turn is running. */
    fun clearConversation(): Boolean {
        if (_turn.value.inFlight || _turn.value.phase == JarvisPhase.Listening) return false
        _conversation.value = emptyList()
        saveHistory(emptyList())
        report(JarvisTurnEvent.Stopped)
        return true
    }

    private fun saveHistory(history: List<JarvisMessage>) {
        scope.launch(dispatchers.io) {
            runCatching {
                if (history.isEmpty()) store.remove(KEY_HISTORY) else store.put(KEY_HISTORY, JarvisProtocol.historyJson(history), durable = false)
            }
        }
    }

    companion object {
        /** SecureStore names. Separate from every Pilot Core, Energy and Control entry. */
        const val KEY_CREDENTIALS = "jarvis-bridge-v1"
        const val KEY_HISTORY = "jarvis-conversation-v1"
        const val KEY_VOICE_MODE = "jarvis-voice-mode-v1"
    }
}
