package com.jameshazell.pilot.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.ui.adaptive.AdaptiveShell
import com.jameshazell.pilot.ui.assistant.AssistantScreen
import com.jameshazell.pilot.ui.components.StateScaffold
import com.jameshazell.pilot.ui.control.ControlScreen
import com.jameshazell.pilot.ui.energy.EnergyScreen
import com.jameshazell.pilot.ui.home.HomeScreen
import com.jameshazell.pilot.ui.more.MoreScreen
import com.jameshazell.pilot.ui.pairing.PairingScreen
import com.jameshazell.pilot.ui.theme.PilotColors

/** Root of the UI: start-up splash, then pairing, then the five-destination shell. */
@Composable
fun PilotApp() {
    val container = LocalAppContainer.current
    val session by container.pilot.session.collectAsStateWithLifecycle()
    Box(Modifier.fillMaxSize().background(PilotColors.Background)) {
        when {
            !session.loaded -> StateScaffold<Unit>(LoadState.Loading, onRetry = {}, loadingLabel = "Starting Pilot…") {}
            !session.paired -> PairingScreen()
            else -> MainShell()
        }
    }
}

@Composable
private fun MainShell() {
    // Saved as a plain id so it survives process death; each destination keeps its own
    // saveable state (scroll, selection) while another one is shown.
    var selectedId by rememberSaveable { mutableStateOf(Destination.Home.id) }
    val stateHolder = rememberSaveableStateHolder()
    val destinations = Destination.all
    AdaptiveShell(
        destinations = destinations.map { it.toShell() },
        selectedId = selectedId,
        onSelect = { selectedId = it },
    ) {
        val destination = Destination.byId(selectedId)
        stateHolder.SaveableStateProvider(destination.id) {
            when (destination) {
                Destination.Home -> HomeScreen()
                Destination.Energy -> EnergyScreen()
                Destination.Control -> ControlScreen()
                Destination.Pilot -> AssistantScreen()
                Destination.More -> MoreScreen()
            }
        }
    }
}
