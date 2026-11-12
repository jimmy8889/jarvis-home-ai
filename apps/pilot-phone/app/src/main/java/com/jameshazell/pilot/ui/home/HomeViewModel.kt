package com.jameshazell.pilot.ui.home

import androidx.lifecycle.ViewModel
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.data.pilot.HomeProjection
import com.jameshazell.pilot.data.pilot.PilotRepository
import com.jameshazell.pilot.data.pilot.PilotSnapshot
import kotlinx.coroutines.flow.StateFlow

class HomeViewModel(private val pilot: PilotRepository) : ViewModel() {
    val snapshot: StateFlow<LoadState<PilotSnapshot>> = pilot.snapshot
    val selectedRoomId: StateFlow<String?> = pilot.selectedRoomId
    val roomDevices: StateFlow<LoadState<HomeProjection>> = pilot.home
    val liveEvents: StateFlow<Boolean> = pilot.liveEvents

    fun refresh() = pilot.refresh()
    fun selectRoom(roomId: String) = pilot.selectRoom(roomId)

    // FEATURE: room device actions (pilot.homeAction / confirmHomeAction), media transport
    // (pilot.media), search (pilot.search) and dashboard controls (pilot.dashboardAction) go
    // here, each launched in viewModelScope with its Outcome turned into UI state.
}
