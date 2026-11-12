package com.jameshazell.pilot.ui.more

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.data.pilot.ClientManifest
import com.jameshazell.pilot.data.pilot.PilotRepository
import com.jameshazell.pilot.data.pilot.PilotSession
import com.jameshazell.pilot.data.pilot.PilotSnapshot
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class MoreViewModel(private val pilot: PilotRepository) : ViewModel() {
    val session: StateFlow<PilotSession> = pilot.session
    val snapshot: StateFlow<LoadState<PilotSnapshot>> = pilot.snapshot
    val manifest: StateFlow<ClientManifest?> = pilot.manifest

    fun refresh() = pilot.refresh()

    fun setKeepScreenOn(enabled: Boolean) {
        viewModelScope.launch { pilot.updateSettings(session.value.config.refreshSeconds, enabled) }
    }

    /** Forgets the Pilot Core pairing; the app returns to the pairing screen. */
    fun unpair() {
        viewModelScope.launch { pilot.unpair() }
    }

    // FEATURE: refresh-interval setting (pilot.updateSettings), per-service connection details
    // and anything else that belongs under More.
}
