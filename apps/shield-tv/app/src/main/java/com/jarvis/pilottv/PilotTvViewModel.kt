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
    data object Disconnected : PilotTvState

    data class Loading(
        val previous: OperationsSnapshot? = null,
    ) : PilotTvState

    data class Connected(
        val snapshot: OperationsSnapshot,
        val refreshedAt: Instant,
    ) : PilotTvState

    data class Error(
        val message: String,
        val previous: OperationsSnapshot? = null,
        val unauthorized: Boolean = false,
    ) : PilotTvState
}

class PilotTvViewModel : ViewModel() {
    private val mutableState = MutableStateFlow<PilotTvState>(PilotTvState.Disconnected)
    val state: StateFlow<PilotTvState> = mutableState.asStateFlow()

    private var client: PilotCoreClient? = null
    private var refreshLoop: Job? = null

    fun connect(baseUrl: String, token: String) {
        val connection = CoreConnection(baseUrl, token)
        val error = connection.validate()
        if (error != null) {
            mutableState.value = PilotTvState.Error(error)
            return
        }
        client = PilotCoreClient(connection)
        refreshLoop?.cancel()
        refresh()
        refreshLoop = viewModelScope.launch {
            while (isActive) {
                delay(15_000)
                refresh(showLoading = false)
            }
        }
    }

    fun refresh(showLoading: Boolean = true) {
        val activeClient = client ?: return
        val previous = currentSnapshot()
        if (showLoading) mutableState.value = PilotTvState.Loading(previous)
        viewModelScope.launch {
            try {
                mutableState.value = PilotTvState.Connected(
                    snapshot = activeClient.operations(),
                    refreshedAt = Instant.now(),
                )
            } catch (error: PilotCoreException) {
                val unauthorized = error.statusCode == 401
                mutableState.value = PilotTvState.Error(
                    message = error.message ?: "Pilot Core request failed.",
                    previous = if (unauthorized) null else previous,
                    unauthorized = unauthorized,
                )
                if (unauthorized) {
                    client = null
                    refreshLoop?.cancel()
                }
            } catch (error: Exception) {
                mutableState.value = PilotTvState.Error(
                    message = error.message ?: "Pilot Core is unavailable.",
                    previous = previous,
                )
            }
        }
    }

    fun disconnect() {
        refreshLoop?.cancel()
        refreshLoop = null
        client = null
        mutableState.value = PilotTvState.Disconnected
    }

    private fun currentSnapshot(): OperationsSnapshot? = when (val value = state.value) {
        is PilotTvState.Connected -> value.snapshot
        is PilotTvState.Error -> value.previous
        is PilotTvState.Loading -> value.previous
        PilotTvState.Disconnected -> null
    }
}
