package com.jarvis.pilottv

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import java.time.Instant
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

sealed interface PilotTvState {
    data class Unpaired(val message: String? = null) : PilotTvState

    data object Pairing : PilotTvState

    data class Loading(
        val previous: PilotTvSnapshot? = null,
        val message: String = "Connecting to Pilot Core…",
    ) : PilotTvState

    data class Ready(
        val snapshot: PilotTvSnapshot,
        val refreshedAt: Instant,
        val pendingAction: String? = null,
        val notice: String? = null,
    ) : PilotTvState

    data class Error(
        val message: String,
        val previous: PilotTvSnapshot? = null,
        val unauthorized: Boolean = false,
    ) : PilotTvState
}

class PilotTvViewModel : ViewModel() {
    private val mutableState = MutableStateFlow<PilotTvState>(PilotTvState.Loading())
    val state: StateFlow<PilotTvState> = mutableState.asStateFlow()

    private var store: CredentialStore? = null
    private var client: PilotCoreClient? = null
    private var manifest: DeviceManifest? = null
    private var refreshLoop: Job? = null
    private var refreshRequest: Job? = null

    fun attachStore(value: CredentialStore) {
        if (store != null) return
        store = value
        val credentials = value.load()
        if (credentials == null) {
            mutableState.value = PilotTvState.Unpaired()
        } else {
            connect(credentials)
        }
    }

    fun pair(baseUrl: String, grantToken: String) {
        if (mutableState.value is PilotTvState.Pairing) return
        mutableState.value = PilotTvState.Pairing
        viewModelScope.launch {
            try {
                val credentials = PilotCoreClient.pair(baseUrl, grantToken)
                store?.save(credentials)
                connect(credentials)
            } catch (error: PilotCoreException) {
                mutableState.value = PilotTvState.Unpaired(error.message)
            }
        }
    }

    fun refresh(showLoading: Boolean = false) {
        val activeClient = client ?: return
        val activeManifest = manifest ?: return
        if (refreshRequest?.isActive == true) return
        val previous = currentSnapshot()
        if (showLoading) {
            mutableState.value = PilotTvState.Loading(previous, "Refreshing your home…")
        }
        refreshRequest = viewModelScope.launch {
            try {
                val next = activeClient.snapshot(activeManifest, previous?.cursor)
                mutableState.value = PilotTvState.Ready(
                    snapshot = next,
                    refreshedAt = Instant.now(),
                )
            } catch (error: PilotCoreException) {
                val unauthorized = error.statusCode == 401
                if (unauthorized) {
                    stopClient(clearCredentials = true)
                }
                mutableState.value = PilotTvState.Error(
                    message = error.message ?: "Pilot Core request failed.",
                    previous = if (unauthorized) null else previous?.copy(stale = true),
                    unauthorized = unauthorized,
                )
            } catch (error: Exception) {
                mutableState.value = PilotTvState.Error(
                    message = error.message ?: "Pilot Core is unavailable.",
                    previous = previous?.copy(stale = true),
                )
            }
        }
    }

    fun media(command: MediaCommand) {
        val activeClient = client ?: return
        val previous = currentSnapshot() ?: return
        val label = command.action.replace('_', ' ')
        mutableState.value = PilotTvState.Ready(
            snapshot = previous,
            refreshedAt = Instant.now(),
            pendingAction = label,
        )
        viewModelScope.launch {
            try {
                activeClient.mediaCommand(command)
                mutableState.value = PilotTvState.Ready(
                    snapshot = previous,
                    refreshedAt = Instant.now(),
                    notice = "${label.replaceFirstChar(Char::uppercase)} sent",
                )
                refresh()
            } catch (error: PilotCoreException) {
                mutableState.value = PilotTvState.Ready(
                    snapshot = previous,
                    refreshedAt = Instant.now(),
                    notice = error.message ?: "Media command failed",
                )
            }
        }
    }

    fun disconnect() {
        stopClient(clearCredentials = true)
        mutableState.value = PilotTvState.Unpaired("Pilot TV has been unpaired.")
    }

    fun rotateCredentials() {
        val activeClient = client ?: return
        val previous = currentSnapshot() ?: return
        viewModelScope.launch {
            try {
                val credentials = activeClient.rotateCredentials()
                store?.save(credentials)
                connect(credentials, previous)
            } catch (error: PilotCoreException) {
                mutableState.value = PilotTvState.Ready(
                    previous,
                    Instant.now(),
                    notice = error.message ?: "Credential rotation failed",
                )
            }
        }
    }

    private fun connect(
        credentials: DeviceCredentials,
        previous: PilotTvSnapshot? = null,
    ) {
        val connection = CoreConnection(credentials.baseUrl, credentials.deviceId, credentials.token)
        val error = connection.validate()
        if (error != null) {
            mutableState.value = PilotTvState.Unpaired(error)
            return
        }
        stopClient(clearCredentials = false)
        client = PilotCoreClient.authenticated(credentials)
        mutableState.value = PilotTvState.Loading(previous)
        viewModelScope.launch {
            try {
                manifest = client?.manifest()
                    ?: throw PilotCoreException("Pilot Core client is unavailable.")
                refresh(showLoading = false)
                startRefreshLoop()
            } catch (error: PilotCoreException) {
                val unauthorized = error.statusCode == 401
                if (unauthorized) stopClient(clearCredentials = true)
                mutableState.value = if (unauthorized) {
                    PilotTvState.Unpaired("Pairing expired or was revoked. Pair Pilot TV again.")
                } else {
                    PilotTvState.Error(error.message ?: "Unable to load Pilot TV.", previous)
                }
            }
        }
    }

    private fun startRefreshLoop() {
        refreshLoop?.cancel()
        refreshLoop = viewModelScope.launch {
            while (isActive) {
                delay(5_000)
                refresh(showLoading = false)
            }
        }
    }

    private fun stopClient(clearCredentials: Boolean) {
        refreshLoop?.cancel()
        refreshRequest?.cancel()
        refreshLoop = null
        refreshRequest = null
        client = null
        manifest = null
        if (clearCredentials) store?.clear()
    }

    private fun currentSnapshot(): PilotTvSnapshot? = when (val value = state.value) {
        is PilotTvState.Ready -> value.snapshot
        is PilotTvState.Error -> value.previous
        is PilotTvState.Loading -> value.previous
        PilotTvState.Pairing,
        is PilotTvState.Unpaired,
        -> null
    }
}
