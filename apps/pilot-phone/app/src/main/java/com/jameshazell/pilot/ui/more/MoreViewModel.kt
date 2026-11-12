package com.jameshazell.pilot.ui.more

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.data.control.ControlConnection
import com.jameshazell.pilot.data.control.ControlOverview
import com.jameshazell.pilot.data.control.ControlRepository
import com.jameshazell.pilot.data.energy.EnergyBootstrap
import com.jameshazell.pilot.data.energy.EnergyRepository
import com.jameshazell.pilot.data.pilot.ClientManifest
import com.jameshazell.pilot.data.pilot.PilotRepository
import com.jameshazell.pilot.data.pilot.PilotSession
import com.jameshazell.pilot.data.pilot.PilotSnapshot
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** More: which page is open, the three backends' status, and this phone's settings. */
class MoreViewModel(
    private val pilot: PilotRepository,
    energy: EnergyRepository,
    control: ControlRepository,
) : ViewModel() {
    val session: StateFlow<PilotSession> = pilot.session
    val snapshot: StateFlow<LoadState<PilotSnapshot>> = pilot.snapshot
    val manifest: StateFlow<ClientManifest?> = pilot.manifest
    val liveEvents: StateFlow<Boolean> = pilot.liveEvents
    val energyBootstrap: StateFlow<LoadState<EnergyBootstrap>> = energy.bootstrap
    val controlOverview: StateFlow<LoadState<ControlOverview>> = control.overview
    val controlConnection: StateFlow<ControlConnection> = control.connection

    private val _page = MutableStateFlow<MorePage?>(null)
    /** The open page; null shows just the menu. Kept here so it survives folding. */
    val page: StateFlow<MorePage?> = _page.asStateFlow()

    fun open(page: MorePage) {
        _page.value = page
    }

    fun close() {
        _page.value = null
    }

    fun refresh() = pilot.refresh()

    fun setKeepScreenOn(enabled: Boolean) {
        viewModelScope.launch { pilot.updateSettings(session.value.config.refreshSeconds, enabled) }
    }

    fun setRefreshSeconds(seconds: Int) {
        viewModelScope.launch { pilot.updateSettings(seconds, session.value.config.keepScreenOn) }
    }

    /** Forgets the Pilot Core pairing; the app returns to the pairing screen. */
    fun unpair() {
        _page.value = null
        viewModelScope.launch { pilot.unpair() }
    }
}
