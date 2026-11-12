package com.jameshazell.pilot.data.pilot

import android.util.LruCache
import com.jameshazell.pilot.core.AddressPolicy
import com.jameshazell.pilot.core.AppDispatchers
import com.jameshazell.pilot.core.AppError
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

    private val _home = MutableStateFlow<LoadState<HomeProjection>>(LoadState.Loading)
    /** Devices of the selected room. Actions are stripped unless [canControlHome]. */
    val home: StateFlow<LoadState<HomeProjection>> = _home.asStateFlow()

    /** True when the manifest grants `home_control`; otherwise room devices are read-only. */
    val canControlHome: Boolean get() = _manifest.value?.features?.contains(FEATURE_HOME_CONTROL) == true

    @Volatile private var token: String? = null
    private var started = false
    private var refreshJob: Job? = null
    private var pollJob: Job? = null
    private var eventJob: Job? = null
    private var homeJob: Job? = null
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
        pollJob?.cancel()
        eventJob?.cancel()
        refreshJob?.cancel()
        _liveEvents.value = false
    }

    /** The network came back or changed: drop in-flight reads and start again. */
    fun onNetworkAvailable() {
        if (!started) return
        refreshJob?.cancel()
        refreshJob = null
        restart()
    }

    /** Fetch the snapshot now. A refresh already in flight is not duplicated. */
    fun refresh() {
        if (refreshJob?.isActive == true) return
        val client = client() ?: return
        refreshJob = scope.launch { refreshSnapshot(client) }
    }

    private fun restart() {
        pollJob?.cancel()
        eventJob?.cancel()
        if (!started || !_session.value.paired) return
        startEventSync()
        pollJob = scope.launch {
            while (true) {
                refresh()
                // Events trigger refreshes when they work; polling is then only a safety net.
                val seconds = if (_liveEvents.value) 60 else _session.value.config.refreshSeconds
                delay(seconds * 1_000L)
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
            _snapshot.value = LoadState.Content(snapshot)
            val room = _selectedRoomId.value?.takeIf { id -> snapshot.media.rooms.any { it.id == id } }
                ?: snapshot.media.rooms.firstOrNull()?.id
            _selectedRoomId.value = room
            room?.let { refreshHome(it, silent = true) }
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: Exception) {
            val appError = error.toAppError(Service.Pilot)
            // A rejected pairing must not keep showing the house as if it were still connected.
            _snapshot.update {
                if (appError.kind == ErrorKind.Unauthorized || appError.kind == ErrorKind.Forbidden) {
                    LoadState.Error(appError)
                } else it.failedWith(appError)
            }
        }
    }

    private fun startEventSync() {
        val client = client() ?: return
        eventJob = scope.launch {
            val manifest = try {
                client.manifest()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                null
            }
            _manifest.value = manifest
            val snapshotPath = manifest?.eventSnapshotPath ?: return@launch
            val eventPath = manifest.eventLongPollPath ?: snapshotPath.removeSuffix("/snapshot")
            try {
                eventCursor = client.eventSnapshotCursor(snapshotPath, eventCursor) ?: eventCursor
                refresh()
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
                    if (page.resetRequired || page.events.isNotEmpty()) refresh()
                    delayMs = if (page.events.isEmpty()) 2_000L else 250L
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (_: Exception) {
                    _liveEvents.value = false
                    delayMs = (delayMs * 2).coerceAtMost(30_000L)
                }
                delay(delayMs)
            }
        }
    }

    // ---- Rooms and devices ------------------------------------------------------------------

    fun selectRoom(roomId: String) {
        if (_selectedRoomId.value == roomId) return
        _selectedRoomId.value = roomId
        _home.value = LoadState.Loading
        refreshHome(roomId)
    }

    /** @param silent keep showing the current devices while reloading. */
    fun refreshHome(roomId: String? = _selectedRoomId.value, silent: Boolean = false) {
        val client = client() ?: return
        val selected = roomId ?: return
        homeJob?.cancel()
        homeJob = scope.launch {
            if (!silent && _home.value !is LoadState.Content) _home.value = LoadState.Loading
            val result = outcomeOf(Service.Pilot) { client.home(selected) }
            if (_selectedRoomId.value != selected) return@launch
            when (result) {
                is Outcome.Success -> _home.value = LoadState.Content(result.value.readOnlyUnless(canControlHome))
                is Outcome.Failure -> _home.update { it.failedWith(result.error) }
            }
        }
    }

    /**
     * Sends a device action (`turn_on`, `set_brightness`, `unlock`, ...). The room list updates
     * optimistically and is rolled back on failure. When the returned action has
     * `confirmationRequired && status == "pending"`, show a ConfirmDialog and call
     * [confirmHomeAction] with its id; nothing has happened yet.
     */
    suspend fun homeAction(entity: HomeEntity, action: String, value: Double? = null): Outcome<HomeAction> {
        if (!canControlHome) return Outcome.Failure(
            AppError(ErrorKind.Forbidden, "This phone has read-only access to room devices."),
        )
        val client = liveClient() ?: return notLive()
        val roomId = _selectedRoomId.value ?: return notLive()
        val before = _home.value
        val optimistic = optimisticEntity(entity, action, value)
        if (optimistic != entity && before is LoadState.Content) {
            _home.value = before.copy(
                value = before.value.copy(
                    entities = before.value.entities.map { if (it.entityId == entity.entityId) optimistic else it },
                ),
            )
        }
        val result = outcomeOf(Service.Pilot) { client.homeAction(roomId, entity.entityId, action, value) }
        when (result) {
            is Outcome.Success -> {
                val pending = result.value.confirmationRequired && result.value.status == "pending"
                if (pending) _home.value = before else refreshHome(roomId, silent = true)
            }
            is Outcome.Failure -> _home.value = before
        }
        return result
    }

    suspend fun confirmHomeAction(actionId: String): Outcome<HomeAction> {
        val client = liveClient() ?: return notLive()
        return outcomeOf(Service.Pilot) { client.confirmHomeAction(actionId) }
            .also { if (it is Outcome.Success) refreshHome(silent = true) }
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
        _home.value = LoadState.Loading
        _session.value = PilotSession(loaded = true, paired = true, config = config)
        restart()
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
        _home.value = LoadState.Loading
        _session.update { it.copy(paired = false) }
    }

    suspend fun updateSettings(refreshSeconds: Int, keepScreenOn: Boolean) {
        val config = _session.value.config.copy(
            refreshSeconds = refreshSeconds.coerceIn(PilotConfig.REFRESH_RANGE),
            keepScreenOn = keepScreenOn,
        )
        withContext(dispatchers.io) { prefs.save(config) }
        _session.update { it.copy(config = config) }
        restart()
    }

    // ---- Internals --------------------------------------------------------------------------

    private fun stopJobs() {
        pollJob?.cancel()
        eventJob?.cancel()
        refreshJob?.cancel()
        homeJob?.cancel()
        _liveEvents.value = false
    }

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
