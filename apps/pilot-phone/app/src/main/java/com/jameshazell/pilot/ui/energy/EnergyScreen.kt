package com.jameshazell.pilot.ui.energy

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.LifecycleStartEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.core.humanLabel
import com.jameshazell.pilot.data.energy.EnergyBootstrap
import com.jameshazell.pilot.ui.appViewModel
import com.jameshazell.pilot.ui.components.CardNote
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.ScreenHeader
import com.jameshazell.pilot.ui.components.SectionHeader
import com.jameshazell.pilot.ui.components.StateScaffold
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens

/** Energy: the Energy Manager's house flow, plan, solar analytics, UPS and controls. */
@Composable
fun EnergyScreen() {
    val model = appViewModel { EnergyViewModel(it.energy) }
    val bootstrap by model.bootstrap.collectAsStateWithLifecycle()

    LifecycleStartEffect(model) {
        model.onScreenStarted()
        onStopOrDispose { model.onScreenStopped() }
    }

    Column(Modifier.fillMaxSize()) {
        ScreenHeader(
            title = "Energy",
            status = energyStatus(bootstrap),
            statusColor = if (bootstrap.isLive) PilotColors.Teal else PilotColors.TextDim,
        )
        StateScaffold(bootstrap, onRetry = model::refresh, loadingLabel = "Connecting to Energy Manager…") { value ->
            // FEATURE: replace this placeholder with the Energy pages (house scene, plan, solar
            // analytics, UPS & rack, controls). The house artwork is in res/drawable-nodpi:
            // house_day, house_day_car, house_night, house_night_car, house_water, house_rack.
            Column(
                Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(PilotDimens.ScreenPadding),
                verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap),
            ) {
                SectionHeader("Connection")
                PilotCard {
                    CardNote(value.decision.mode?.let { "Current decision: ${humanLabel(it)}" } ?: "Waiting for the controller's decision.")
                    value.fault?.let { CardNote(it, color = PilotColors.Red) }
                }
            }
        }
    }
}

internal fun energyStatus(state: LoadState<EnergyBootstrap>): String = when (state) {
    is LoadState.Loading -> "Connecting"
    is LoadState.Error -> "Offline"
    is LoadState.Content -> when {
        state.stale -> "Saved"
        state.value.telemetryFresh() -> "Live"
        else -> "Connected · controller readings are stale"
    }
}
