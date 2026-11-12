package com.jameshazell.pilot.ui.control

import androidx.lifecycle.ViewModel
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.data.control.ControlConnection
import com.jameshazell.pilot.data.control.ControlOverview
import com.jameshazell.pilot.data.control.ControlRepository
import kotlinx.coroutines.flow.StateFlow

class ControlViewModel(private val control: ControlRepository) : ViewModel() {
    val overview: StateFlow<LoadState<ControlOverview>> = control.overview
    val connection: StateFlow<ControlConnection> = control.connection

    /** The event socket follows the screen: call from LifecycleStartEffect. */
    fun onScreenStarted() = control.start()
    fun onScreenStopped() = control.stop()
    fun refresh() = control.refresh()

    // FEATURE: chat (control.sendMessage, control.messages), approvals (control.approvals,
    // control.decideApproval), task activity (control.taskEvents) and transcripts
    // (control.conversation), each launched in viewModelScope.
}
