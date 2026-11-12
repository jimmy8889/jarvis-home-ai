package com.jameshazell.pilot.data.energy

import android.app.Activity
import com.jameshazell.pilot.core.AppError
import com.jameshazell.pilot.core.ErrorKind
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.core.Outcome
import com.jameshazell.pilot.core.Service
import com.jameshazell.pilot.core.authenticateOnPhone
import com.jameshazell.pilot.core.failedWith
import com.jameshazell.pilot.core.objects
import com.jameshazell.pilot.core.outcomeOf
import com.jameshazell.pilot.core.toAppError
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONArray
import org.json.JSONObject

/**
 * Energy Manager: live readings, plan, history, settings and signed commands.
 * The controller stays authoritative; this phone only displays and requests.
 *
 * Reads are cached-then-live. Polling runs only between [start] and [stop] (the Energy screen
 * calls them); history is fetched only while [setHistoryVisible] is true.
 */
class EnergyRepository(
    private val scope: CoroutineScope,
    private val client: EnergyClient,
) {
    private val _bootstrap = MutableStateFlow<LoadState<EnergyBootstrap>>(LoadState.Loading)
    val bootstrap: StateFlow<LoadState<EnergyBootstrap>> = _bootstrap.asStateFlow()

    private val _history = MutableStateFlow<LoadState<List<EnergyTelemetry>>>(LoadState.Loading)
    /** Recorded telemetry, oldest first as the server returns it (up to 288 rows). */
    val history: StateFlow<LoadState<List<EnergyTelemetry>>> = _history.asStateFlow()

    private val _daily = MutableStateFlow<LoadState<List<EnergyDay>>>(LoadState.Loading)
    /** Daily totals for up to 30 days. */
    val daily: StateFlow<LoadState<List<EnergyDay>>> = _daily.asStateFlow()

    private var started = false
    private var historyVisible = false
    private var pollJob: Job? = null
    private var historyJob: Job? = null
    private val refreshLock = Mutex()

    /** Begin 15-second polling. Safe to call repeatedly. */
    fun start() {
        if (started) return
        started = true
        restart()
    }

    fun stop() {
        started = false
        pollJob?.cancel()
        historyJob?.cancel()
    }

    fun onNetworkAvailable() {
        if (started) restart()
    }

    /** Turn the 60-second history and daily polling on or off (the Solar analytics page). */
    fun setHistoryVisible(visible: Boolean) {
        if (historyVisible == visible) return
        historyVisible = visible
        if (started) restartHistory()
    }

    /** Fetch live readings now; suspends until done. Overlapping calls are serialised. */
    suspend fun refresh() {
        refreshLock.withLock {
            try {
                val read = client.read(EnergyClient.BOOTSTRAP_PATH)
                val value = EnergyJson.bootstrap(read.json as JSONObject)
                _bootstrap.value = LoadState.Content(
                    value,
                    stale = read.stale,
                    savedAt = read.savedAt,
                    problem = read.problem?.toAppError(Service.Energy),
                )
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                val appError = error.toAppError(Service.Energy)
                _bootstrap.update {
                    if (appError.kind == ErrorKind.Unauthorized || appError.kind == ErrorKind.NotPaired) {
                        LoadState.Error(appError)
                    } else it.failedWith(appError)
                }
            }
        }
    }

    /**
     * Changes controller settings. Sends the revision currently on screen as `If-Match`, so a
     * change made elsewhere in the meantime is rejected rather than overwritten.
     */
    suspend fun updateSettings(patch: EnergySettingsPatch): Outcome<Unit> {
        val current = _bootstrap.value
        val revision = (current as? LoadState.Content)?.takeIf { !it.stale }?.value?.settingsRevision
            ?: return Outcome.Failure(
                AppError(ErrorKind.Offline, "Reconnect to Energy Manager before changing settings."),
            )
        return outcomeOf(Service.Energy) {
            client.send(EnergyClient.SETTINGS_PATH, "PATCH", patch.toJson(), mapOf("If-Match" to revision))
            Unit
        }.also { if (it is Outcome.Success) refresh() }
    }

    /**
     * Runs a command after the owner unlocks the phone. The UI should confirm intent first
     * (ConfirmDialog); the system unlock prompt then appears over [activity].
     * Returns the controller's response.
     */
    suspend fun runAction(activity: Activity, action: EnergyAction): Outcome<JSONObject> =
        outcomeOf(Service.Energy) {
            client.signedAction(action) { authenticateOnPhone(activity, "Authorise: ${action.label}") }
        }.also { if (it is Outcome.Success) refresh() }

    /** One-off first-run step: consume a provisioned pairing grant, if one is waiting. */
    suspend fun consumePendingGrant() {
        if (client.hasPendingGrant()) refresh()
    }

    private fun restart() {
        pollJob?.cancel()
        pollJob = scope.launch {
            if (_bootstrap.value !is LoadState.Content) {
                client.saved(EnergyClient.BOOTSTRAP_PATH)?.let { saved ->
                    runCatching { EnergyJson.bootstrap(saved.json as JSONObject) }.getOrNull()?.let {
                        _bootstrap.value = LoadState.Content(it, stale = true, savedAt = saved.savedAt)
                    }
                }
            }
            while (true) {
                refresh()
                delay(POLL_MS)
            }
        }
        restartHistory()
    }

    private fun restartHistory() {
        historyJob?.cancel()
        if (!historyVisible) return
        historyJob = scope.launch {
            while (true) {
                loadList(EnergyClient.HISTORY_PATH, _history, EnergyJson::history)
                loadList(EnergyClient.DAILY_PATH, _daily, EnergyJson::daily)
                delay(HISTORY_POLL_MS)
            }
        }
    }

    private suspend fun <T> loadList(
        path: String,
        target: MutableStateFlow<LoadState<List<T>>>,
        decode: (List<JSONObject>) -> List<T>,
    ) {
        try {
            val read = client.read(path)
            target.value = LoadState.Content(
                decode((read.json as? JSONArray).objects()),
                stale = read.stale,
                savedAt = read.savedAt,
                problem = read.problem?.toAppError(Service.Energy),
            )
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: Exception) {
            target.update { it.failedWith(error.toAppError(Service.Energy)) }
        }
    }

    private companion object {
        const val POLL_MS = 15_000L
        const val HISTORY_POLL_MS = 60_000L
    }
}
