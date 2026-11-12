package com.jameshazell.pilot.ui.pairing

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jameshazell.pilot.core.Outcome
import com.jameshazell.pilot.data.pilot.PilotRepository
import com.jameshazell.pilot.data.pilot.PilotSession
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class PairingUiState(val busy: Boolean = false, val error: String? = null)

class PairingViewModel(private val pilot: PilotRepository) : ViewModel() {
    val session: StateFlow<PilotSession> = pilot.session

    /** A `pilot://pair` link that opened the app, to pre-fill the form. */
    val pendingLink: StateFlow<String?> = pilot.pendingPairing

    private val _state = MutableStateFlow(PairingUiState())
    val state: StateFlow<PairingUiState> = _state.asStateFlow()

    fun pair(coreUrl: String, grantOrLink: String) = submit { pilot.pair(coreUrl, grantOrLink) }

    fun connectManually(coreUrl: String, deviceId: String, deviceToken: String) =
        submit { pilot.connectManually(coreUrl, deviceId, deviceToken) }

    fun clearError() = _state.update { it.copy(error = null) }

    private fun submit(block: suspend () -> Outcome<Unit>) {
        if (_state.value.busy) return
        _state.value = PairingUiState(busy = true)
        viewModelScope.launch {
            val result = block()
            // On success the session flips to paired and this screen leaves composition.
            _state.value = PairingUiState(error = result.errorOrNull()?.message)
        }
    }
}
