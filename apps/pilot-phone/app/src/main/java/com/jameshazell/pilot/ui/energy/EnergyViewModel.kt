package com.jameshazell.pilot.ui.energy

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.data.energy.EnergyBootstrap
import com.jameshazell.pilot.data.energy.EnergyRepository
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class EnergyViewModel(private val energy: EnergyRepository) : ViewModel() {
    val bootstrap: StateFlow<LoadState<EnergyBootstrap>> = energy.bootstrap

    /** Polling follows the screen: call from LifecycleStartEffect. */
    fun onScreenStarted() = energy.start()
    fun onScreenStopped() = energy.stop()

    fun refresh() {
        viewModelScope.launch { energy.refresh() }
    }

    // FEATURE: expose energy.history / energy.daily (call energy.setHistoryVisible(true) while
    // the Solar analytics page is shown), settings edits (energy.updateSettings) and signed
    // commands (energy.runAction(activity, action) after a ConfirmDialog).
}
