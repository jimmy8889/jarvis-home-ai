package com.jameshazell.pilot.ui.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.jameshazell.pilot.data.pilot.PilotRepository
import com.jameshazell.pilot.ui.appViewModel
import com.jameshazell.pilot.ui.components.CardNote
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.ScreenHeader
import com.jameshazell.pilot.ui.components.SectionHeader
import com.jameshazell.pilot.ui.components.StateScaffold
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens

/** Home: rooms, devices, now playing and the house energy summary. */
@Composable
fun HomeScreen() {
    val model = appViewModel { HomeViewModel(it.pilot) }
    val snapshot by model.snapshot.collectAsStateWithLifecycle()
    val live by model.liveEvents.collectAsStateWithLifecycle()

    Column(Modifier.fillMaxSize()) {
        ScreenHeader(
            title = "Home",
            status = PilotRepository.dashboardLabel(snapshot),
            statusColor = if (snapshot.isLive) PilotColors.Teal else PilotColors.TextDim,
        )
        StateScaffold(snapshot, onRetry = model::refresh, loadingLabel = "Connecting to Pilot Core…") { value ->
            // FEATURE: replace this placeholder with the Home dashboard. Suggested shape:
            // ListDetailLayout(list = room tiles (RoomTile), detail = the selected room's devices
            // from model.roomDevices), with now-playing and energy StatCells above the rooms.
            Column(
                Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(PilotDimens.ScreenPadding),
                verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap),
            ) {
                SectionHeader("Connection")
                PilotCard {
                    CardNote("${value.media.rooms.size} rooms · ${value.media.players.size} players")
                    CardNote(if (live) "Live updates are on." else "Live updates are off; refreshing on a timer.")
                }
            }
        }
    }
}
