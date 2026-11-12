package com.jameshazell.pilot.data.pilot

import android.util.LruCache
import com.jameshazell.pilot.core.AddressPolicy
import com.jameshazell.pilot.core.AppDispatchers
import com.jameshazell.pilot.core.AppError
import com.jameshazell.pilot.core.AppException
import com.jameshazell.pilot.core.DeviceTokenStore
import com.jameshazell.pilot.core.ErrorKind
import com.jameshazell.pilot.core.HttpClients
import com.jameshazell.pilot.core.HttpFailure
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.core.Outcome
import com.jameshazell.pilot.core.PilotConfig
import com.jameshazell.pilot.core.Prefs
import com.jameshazell.pilot.core.SecretStore
import com.jameshazell.pilot.core.Service
import com.jameshazell.pilot.core.SnapshotCache
import com.jameshazell.pilot.core.failedWith
import com.jameshazell.pilot.core.outcomeOf
import com.jameshazell.pilot.core.toAppError
import java.time.Instant
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** Whether this phone is paired with Pilot Core. [loaded] is false until storage has been read. */
data class PilotSession(
    val loaded: Boolean = false,
    val paired: Boolean = false,
    val config: PilotConfig = PilotConfig(),
)

/**
 * Pilot Core: pairing, the house snapshot (media, surface, dashboard), live events, room
 * devices, and commands. One instance for the app, created by AppContainer.
 *
 * Reads are cached-then-live: the encrypted saved snapshot is published first as
 * `Content(stale = true)`, then replaced by live data. Commands need a live connection and are
 * never queued or replayed.
 */
class PilotRepository(
    private val scope: CoroutineScope,
    private val dispatchers: AppDispatchers,
    private val http: HttpClients,
    private val prefs: Prefs,
    private val tokens: DeviceTokenStore,
    private val secure: SecretStore,
) {
    private val _session = MutableStateFlow(PilotSession())
    val session: StateFlow<PilotSession> = _session.asStateFlow()

    private val _pendingPairing = MutableStateFlow<String?>(null)
    /** A `pilot://pair?...` link that opened the app and has not been redeemed yet. */
    val pendingPairing: StateFlow<String?> = _pendingPairing.asStateFlow()

    private val _snapshot = MutableStateFlow<LoadState<PilotSnapshot>>(LoadState.Loading)
    val snapshot: StateFlow<LoadState<PilotSnapshot>> = _snapshot.asStateFlow()

    private val _manifest = MutableStateFlow<ClientManifest?>(null)
    /** What this Core supports and what this phone is allowed to do; null until fetched. */
    val manifest: StateFlow<ClientManifest?> = _manifest.asStateFlow()

    private val _liveEvents = MutableStateFlow(false)
    /** True while the event long-poll is healthy (changes arrive within seconds). */
    val liveEvents: StateFlow<Boolean> = _liveEvents.asStateFlow()

    private val _selectedRoomId = MutableStateFlow<String?>(null)
    val selectedRoomId: StateFlow<String?> = _selectedRoomId.asStateFlow()

    private val _roomProjections = MutableStateFlow<Map<String, HomeProjection>>(emptyMap())
    /**
     * The devices of each room as last read in this app session, by room id. Only rooms the user
     * has opened are here; nothing is prefetched, so treat every entry but the visible room's as old.
     */
    val roomProjections: StateFlow<Map<String, HomeProjection>> = _roomProjections.asStateFlow()

    /** Every read of a room's devices goes through this gate; see [homeFor]. */
    private val projections = HomeProjectionGate { roomId ->
        val client = client() ?: throw AppException(AppError(ErrorKind.NotPaired, "Pair this phone with Pilot Core first."))
        client.home(roomId).copy(roomId = roomId).readOnlyUnless(canControlHome)
            .also { fresh -> _roomProjections.update { it + (roomId to fresh) } }
    }

    /** True when the manifest grants `home_control`; otherwise room devices are read-only. */
    val canControlHome: Boolean get() = _manifest.value?.features?.contains(FEATURE_HOME_CONTROL) == true

    @Volatile private var token: String? = null
    private var started = false
    private var refreshJob: Job? = null
    private var refreshQueued = false
    private var lastRefreshStartMs = 0L
    private var refreshFailures = 0
    /** Polling plus event sync. There is never more than one. */
    private var loopJob: Job? = null
    private var restartJob: Job? = null
    private var restartPending = false
    private var lastLoopStartMs = 0L
    private var eventCursor: String? = null
    private val artworkCache = object : LruCache<String, ByteArray>(24 * 1024 * 1024) {
        override fun sizeOf(key: String, value: ByteArray): Int = value.size
    }

    // ---- Start-up and lifecycle -------------------------------------------------------------

    /** Reads saved pairing and the saved snapshot. Called once by AppContainer after provisioning. */
    suspend fun load() {
        val (config, savedToken, saved) = withContext(dispatchers.io) {
            val config = prefs.load()
            val savedToken = tokens.read()
            val saved = if (savedToken == null) null else runCatching {
                secure.get(SnapshotCache.pilotSnapshotKey(config.coreUrl, config.deviceId))
                    ?.let { decodeEnvelope(JSONObject(it), fromCache = true) }
            }.getOrNull()
            Triple(config, savedToken, saved)
        }
        token = savedToken
        if (saved != null) {
            _snapshot.value = LoadState.Content(saved, stale = true, savedAt = saved.receivedAt)
            _selectedRoomId.value = saved.media.rooms.firstOrNull()?.id
        }
        _session.value = PilotSession(loaded = true, paired = savedToken != null, config = config)
        restart()
    }

    /** Begin polling and live events. Call from Activity.onStart. */
    fun start() {
        started = true
        restart()
    }

    /** Stop all background reads. Call from Activity.onStop. */
    fun stop() {
        started = false
        stopJobs()
    }

    /**
     * The network came back or changed. Reads that are working are left alone; otherwise the
     * loops start again (skipping their backoff waits), at most once per [MIN_RESTART_GAP_MS].
     */
    fun onNetworkAvailable() {
        if (!started) return
        if (_snapshot.value.isLive && _liveEvents.value) return
        restart(force = true)
    }

    /** Fetch the snapshot now. A refresh already in flight is not duplicated. */
    fun refresh() = requestRefresh(minGapMs = 0)

    /**
     * Single-flight snapshot refresh. While one is running, any number of further requests
     * collapse into one more run afterwards. [minGapMs] spaces automatic refreshes apart so a
     * burst of live events cannot turn into a burst of requests.
     */
    private fun requestRefresh(minGapMs: Long) {
        if (refreshJob?.isActive == true) {
            refreshQueued = true
            return
        }
        val client = client() ?: return
        refreshJob = scope.launch {
            var gap = minGapMs
            do {
                val wait = lastRefreshStartMs + gap - nowMs()
                if (lastRefreshStartMs != 0L && wait > 0) delay(wait)
                refreshQueued = false
                lastRefreshStartMs = nowMs()
                refreshSnapshot(client)
                // A refresh asked for while this one ran is automatic by nature: space it out.
                gap = maxOf(gap, EVENT_REFRESH_GAP_MS)
            } while (refreshQueued)
        }
    }

    /**
     * (Re)starts polling and event sync as ONE job. Calls in quick succession (app start fires
     * load, onStart and the network callback together) collapse into a single start, and loops
     * that are already running are left alone unless [force] (the network changed and they are
     * not healthy) or [replace] (the pairing changed, so they hold the wrong credentials).
     */
    private fun restart(force: Boolean = false, replace: Boolean = false) {
        if (!started || !_session.value.paired) {
            stopJobs()
            return
        }
        val running = loopJob?.isActive == true
        if (running && !force && !replace) return
        if (running && restartPending && !replace) return
        val wait = if (running && !replace) (lastLoopStartMs + MIN_RESTART_GAP_MS - nowMs()).coerceAtLeast(RESTART_DEBOUNCE_MS)
        else RESTART_DEBOUNCE_MS
        restartPending = true
        restartJob?.cancel()
        restartJob = scope.launch {
            delay(wait)
            restartPending = false
            // They may have recovered on their own while this restart was waiting.
            if (!replace && loopJob?.isActive == true && _snapshot.value.isLive && _liveEvents.value) return@launch
            loopJob?.cancel()
            refreshJob?.cancel()
            lastLoopStartMs = nowMs()
            loopJob = scope.launch {
                launch { eventSync() }
                while (true) {
                    refresh()
                    // Events trigger refreshes when they work; polling is then only a safety net.
                    // After failures the wait doubles, so a struggling Core is not hammered.
                    val base = if (_liveEvents.value) 60 else _session.value.config.refreshSeconds
                    delay(pollDelayMs(base, refreshFailures))
                }
            }
        }
    }

    private suspend fun refreshSnapshot(client: PilotCoreClient) {
        val config = _session.value.config
        try {
            val snapshot = withContext(dispatchers.io) {
                val envelope = client.snapshotEnvelope()
                val decoded = decodeEnvelope(envelope, fromCache = false)
                runCatching {
                    secure.put(
                        SnapshotCache.pilotSnapshotKey(config.coreUrl, config.deviceId),
                        envelope.toString(),
                        durable = false,
                    )
                }
                decoded
            }
            refreshFailures = 0
            val previousRevision = _snapshot.value.valueOrNull()?.media?.revision
            _snapshot.value = LoadState.Content(snapshot)
            val room = _selectedRoomId.value?.takeIf { id -> snapshot.media.rooms.any { it.id == id } }
                ?: snapshot.media.rooms.firstOrNull()?.id
            _selectedRoomId.value = room
            // Room devices are NOT read here. A changed revision is only a hint, and the gate
            // ignores it unless a room detail is on screen.
            if (snapshot.media.revision != null && snapshot.media.revision != previousRevision) hintHomeChanged()
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: Exception) {
            refreshFailures++
            val appError = error.toAppError(Service.Pilot)
            // A rejected pairing must not keep showing the house as if it were still connected.
            _snapshot.update {
                if (appError.kind == ErrorKind.Unauthorized || appError.kind == ErrorKind.Forbidden) {
                    LoadState.Error(appError)
                } else it.failedWith(appError)
            }
        }
    }

    /** One long-poll at a time, for as long as the loop job lives. Every failure backs off. */
    private suspend fun eventSync() {
        val client = client() ?: return
        val manifest = manifestWithRetry(client)
        _manifest.value = manifest
        val snapshotPath = manifest?.eventSnapshotPath ?: return
        val eventPath = manifest.eventLongPollPath ?: snapshotPath.removeSuffix("/snapshot")
        try {
            eventCursor = eventCursor ?: client.currentEventCursor(eventPath)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            // The long poll below retries with backoff.
        }
        var delayMs = 1_000L
        while (true) {
            try {
                val page = client.events(eventPath, eventCursor)
                eventCursor = page.cursor ?: eventCursor
                _liveEvents.value = true
                if (page.resetRequired || page.events.isNotEmpty()) {
                    requestRefresh(EVENT_REFRESH_GAP_MS)
                    hintHomeChanged()
                }
                delayMs = if (page.events.isEmpty()) 2_000L else 1_000L
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                _liveEvents.value = false
                delayMs = (delayMs * 2).coerceIn(2_000L, 60_000L)
            }
            delay(delayMs)
        }
    }

    /** Null when this Core has no manifest. A failed read is retried with backoff, never in a tight loop. */
    private suspend fun manifestWithRetry(client: PilotCoreClient): ClientManifest? {
        var waitMs = 5_000L
        while (true) {
            try {
                return client.manifest()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                delay(waitMs)
                waitMs = (waitMs * 2).coerceAtMost(120_000L)
            }
        }
    }

    // ---- Rooms and devices ------------------------------------------------------------------

    /** The room used as context for music and the assistant. Does not read the room's devices. */
    fun selectRoom(roomId: String) {
        _selectedRoomId.value = roomId
    }

    /**
     * Tell the repository which room's detail is on screen (null: none). Reading a room's
     * devices is very expensive for Pilot Core, so nothing but a visible room is ever re-read
     * automatically.
     */
    fun setRoomVisible(roomId: String?) = projections.setVisibleRoom(roomId)

    /**
     * Devices of one room, through the [HomeProjectionGate]: one request at a time for the whole
     * app, never in the background. Actions are stripped unless [canControlHome].
     *
     * @return null when no request was made because it is not allowed right now (too soon, or
     * the user has already moved to another room); use [roomProjections] for what is known.
     */
    suspend fun homeFor(roomId: String, reason: ProjectionReason): Outcome<HomeProjection>? {
        if (client() == null) return notPaired()
        val result = outcomeOf(Service.Pilot) { projections.request(roomId, reason) }
        return when (result) {
            is Outcome.Success -> result.value?.let { Outcome.Success(it) }
            is Outcome.Failure -> result
        }
    }

    private fun hintHomeChanged() {
        if (projections.visibleRoomId == null) return
        scope.launch {
            try {
                projections.onChangeHint()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                // The room keeps showing what it had; the user can refresh it.
            }
        }
    }

    /**
     * Sends a device action (`turn_on`, `set_brightness`, `unlock`, ...). When the returned
     * action has `confirmationRequired && status == "pending"`, show a ConfirmDialog and call
     * [confirmHomeAction] with its id; nothing has happened yet. The caller shows the optimistic
     * state and re-reads the room once with [ProjectionReason.AfterAction].
     *
     * @param roomId the room the entity is in; defaults to the selected room.
     * @param option a text parameter instead of [value], e.g. the mode for `set_hvac_mode`.
     */
    suspend fun homeAction(
        entity: HomeEntity,
        action: String,
        value: Double? = null,
        roomId: String? = null,
        option: String? = null,
    ): Outcome<HomeAction> {
        if (!canControlHome) return Outcome.Failure(
            AppError(ErrorKind.Forbidden, "This phone has read-only access to room devices."),
        )
        val client = liveClient() ?: return notLive()
        val target = roomId ?: _selectedRoomId.value ?: return notLive()
        return outcomeOf(Service.Pilot) { client.homeAction(target, entity.entityId, action, value, option) }
    }

    suspend fun confirmHomeAction(actionId: String): Outcome<HomeAction> {
        val client = liveClient() ?: return notLive()
        return outcomeOf(Service.Pilot) { client.confirmHomeAction(actionId) }
    }

    // ---- Media, dashboard, assistant --------------------------------------------------------

    /** When [MediaCommand.playerId] is null the selected room's default music player is used. */
    suspend fun media(command: MediaCommand): Outcome<Unit> {
        val client = liveClient() ?: return notLive()
        val snapshot = _snapshot.value.valueOrNull()
        val fallbackPlayer = snapshot?.media?.rooms
            ?.firstOrNull { it.id == _selectedRoomId.value }?.defaultMusicPlayerId
        val resolved = command.copy(playerId = command.playerId ?: fallbackPlayer)
        return outcomeOf(Service.Pilot) { client.mediaCommand(resolved) }
            .also { if (it is Outcome.Success) refresh() }
    }

    suspend fun search(query: String): Outcome<List<MusicSearchResult>> {
        val client = client() ?: return notPaired()
        return outcomeOf(Service.Pilot) { client.search(query.trim()) }
    }

    /** Dashboard controls, e.g. `("tesla_charging_mode", "Solar")`. */
    suspend fun dashboardAction(action: String, value: String): Outcome<Unit> {
        val client = liveClient() ?: return notLive()
        return outcomeOf(Service.Pilot) { client.dashboardAction(action, value) }
            .also { if (it is Outcome.Success) refresh() }
    }

    suspend fun ask(text: String, roomId: String, conversationId: String?): Outcome<AssistantReply> {
        val client = client() ?: return notPaired()
        return outcomeOf(Service.Pilot) { client.ask(text.trim(), roomId, conversationId) }
    }

    /** @param pcm raw 16-bit mono PCM at [sampleRate] Hz. */
    suspend fun voice(pcm: ByteArray, sampleRate: Int = 16_000, conversationId: String? = null): Outcome<AssistantReply> {
        val client = client() ?: return notPaired()
        return outcomeOf(Service.Pilot) { client.voice(pcm, sampleRate, conversationId) }
    }

    /** Spoken-reply audio for [AssistantReply.audioDownloadUrl]. */
    suspend fun audio(path: String): Outcome<ByteArray> {
        val client = client() ?: return notPaired()
        return outcomeOf(Service.Pilot) { client.audioAsset(path) }
    }

    /** Artwork bytes, memory-cached (24 MB). Null when unavailable; artwork is never an error. */
    suspend fun artwork(url: String): ByteArray? {
        artworkCache.get(url)?.let { return it }
        val client = client() ?: return null
        return outcomeOf(Service.Pilot) { client.artworkAsset(url) }.valueOrNull()
            ?.also { artworkCache.put(url, it) }
    }

    // ---- Pairing and settings ---------------------------------------------------------------

    /** Remember a `pilot://pair` deep link for the pairing screen. Ignores anything else. */
    fun offerPairingLink(uri: String?) {
        uri?.trim()?.takeIf { it.startsWith("pilot://", ignoreCase = true) }?.let { _pendingPairing.value = it }
    }

    /** Redeems a one-time grant (or a full `pilot://pair` link). The grant is never stored. */
    suspend fun pair(coreUrl: String, grantOrLink: String): Outcome<Unit> {
        val payload = try {
            PairingPayload.parse(grantOrLink, coreUrl)
        } catch (error: IllegalArgumentException) {
            return Outcome.Failure(AppError(ErrorKind.Invalid, error.message ?: "Check the pairing code."))
        }
        val registration = try {
            PilotCoreClient.redeemBootstrap(http, payload.coreUrl, payload.grantToken)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: HttpFailure) {
            return Outcome.Failure(
                if (error.status in 400..499) AppError(
                    ErrorKind.Unauthorized,
                    "That pairing grant was rejected. It may have expired or already been used.",
                    error.status,
                ) else error.toAppError(Service.Pilot),
            )
        } catch (error: Exception) {
            return Outcome.Failure(error.toAppError(Service.Pilot))
        }
        if (registration.deviceId.isBlank() || registration.deviceToken.isBlank()) {
            return Outcome.Failure(AppError(ErrorKind.Unknown, "Pilot Core didn't return a device identity."))
        }
        adopt(_session.value.config.copy(coreUrl = payload.coreUrl, deviceId = registration.deviceId), registration.deviceToken)
        _pendingPairing.value = null
        return Outcome.Success(Unit)
    }

    /** Advanced: connect with an existing device ID and token, verified before being saved. */
    suspend fun connectManually(coreUrl: String, deviceId: String, deviceToken: String): Outcome<Unit> {
        val config = try {
            require(deviceId.isNotBlank()) { "Device ID is required" }
            require(deviceToken.isNotBlank()) { "Device token is required" }
            _session.value.config.copy(coreUrl = AddressPolicy.normalize(coreUrl), deviceId = deviceId.trim())
        } catch (error: IllegalArgumentException) {
            return Outcome.Failure(AppError(ErrorKind.Invalid, error.message ?: "Check the connection details."))
        }
        val check = outcomeOf(Service.Pilot) { PilotCoreClient(http, config, deviceToken.trim()).testConnection() }
        if (check is Outcome.Failure) return check
        adopt(config, deviceToken.trim())
        return Outcome.Success(Unit)
    }

    private suspend fun adopt(config: PilotConfig, deviceToken: String) {
        withContext(dispatchers.io) {
            prefs.save(config)
            tokens.write(deviceToken)
        }
        token = deviceToken
        eventCursor = null
        _manifest.value = null
        _snapshot.value = LoadState.Loading
        _roomProjections.value = emptyMap()
        projections.reset()
        _session.value = PilotSession(loaded = true, paired = true, config = config)
        restart(replace = true)
    }

    /** Forgets the Pilot Core device token. Energy Manager and James Control are untouched. */
    suspend fun unpair() {
        stopJobs()
        withContext(dispatchers.io) { tokens.clear() }
        token = null
        eventCursor = null
        artworkCache.evictAll()
        _manifest.value = null
        _selectedRoomId.value = null
        _snapshot.value = LoadState.Loading
        _roomProjections.value = emptyMap()
        projections.reset()
        _session.update { it.copy(paired = false) }
    }

    suspend fun updateSettings(refreshSeconds: Int, keepScreenOn: Boolean) {
        val config = _session.value.config.copy(
            refreshSeconds = refreshSeconds.coerceIn(PilotConfig.REFRESH_RANGE),
            keepScreenOn = keepScreenOn,
        )
        withContext(dispatchers.io) { prefs.save(config) }
        _session.update { it.copy(config = config) }
        // The running poll loop reads the new interval on its next turn; nothing to restart.
    }

    // ---- Internals --------------------------------------------------------------------------

    private fun stopJobs() {
        restartJob?.cancel()
        restartPending = false
        loopJob?.cancel()
        refreshJob?.cancel()
        refreshQueued = false
        _liveEvents.value = false
    }

    private fun nowMs(): Long = System.nanoTime() / 1_000_000

    private fun client(): PilotCoreClient? {
        val current = token ?: return null
        val session = _session.value
        if (!session.paired) return null
        return runCatching { PilotCoreClient(http, session.config, current) }.getOrNull()
    }

    /** Commands are refused while the house snapshot is saved data. */
    private fun liveClient(): PilotCoreClient? = if (_snapshot.value.isLive) client() else null

    private fun notLive() = Outcome.Failure(
        AppError(ErrorKind.Offline, "Reconnect to send this command. Saved data is read-only."),
    )

    private fun notPaired() = Outcome.Failure(
        AppError(ErrorKind.NotPaired, "Pair this phone with Pilot Core first."),
    )

    companion object {
        const val FEATURE_HOME_CONTROL = "home_control"

        /** Calls to restart() within this window become one start. */
        private const val RESTART_DEBOUNCE_MS = 400L
        /** Running loops are torn down and restarted at most this often. */
        private const val MIN_RESTART_GAP_MS = 10_000L
        /** Minimum spacing of snapshot refreshes triggered by live events. */
        private const val EVENT_REFRESH_GAP_MS = 5_000L
        private const val MAX_POLL_DELAY_MS = 120_000L

        /** Poll wait: the configured interval, doubled per consecutive failure, capped at two minutes. */
        internal fun pollDelayMs(baseSeconds: Int, failures: Int): Long {
            val base = baseSeconds.coerceAtLeast(1) * 1_000L
            return (base shl failures.coerceIn(0, 6)).coerceIn(base, maxOf(base, MAX_POLL_DELAY_MS))
        }

        internal fun decodeEnvelope(raw: JSONObject, fromCache: Boolean) = PilotSnapshot(
            media = PilotJson.media(raw.getJSONObject("media")),
            surface = PilotJson.surface(raw.getJSONObject("surface")),
            dashboard = raw.optJSONObject("dashboard")?.let(PilotJson::dashboard),
            receivedAt = Instant.parse(raw.getString("saved_at")),
            fromCache = fromCache,
        )

        internal fun HomeProjection.readOnlyUnless(canControl: Boolean): HomeProjection =
            if (canControl) this else copy(entities = entities.map { it.copy(actions = emptyList()) })

        internal fun optimisticEntity(entity: HomeEntity, action: String, value: Double?): HomeEntity =
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

        /**
         * Status line for dashboard readings. Pilot Core's `partial` means some sensors are
         * missing, not that the phone is disconnected.
         */
        fun dashboardLabel(state: LoadState<PilotSnapshot>, paired: Boolean = true): String = when {
            !paired -> "Not connected"
            state is LoadState.Loading -> "Connecting"
            state is LoadState.Error -> "Offline"
            state is LoadState.Content && (state.stale || state.value.fromCache) -> "Saved"
            else -> when ((state as LoadState.Content).value.dashboard?.status) {
                "ok" -> "Live"
                "partial" -> "Connected · some readings unavailable"
                else -> "Connected · readings unavailable"
            }
        }
    }
}
