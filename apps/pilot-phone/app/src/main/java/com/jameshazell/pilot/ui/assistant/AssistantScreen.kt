package com.jameshazell.pilot.ui.assistant

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
import com.jameshazell.pilot.ui.appViewModel
import com.jameshazell.pilot.ui.components.CardNote
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.ScreenHeader
import com.jameshazell.pilot.ui.components.SectionHeader
import com.jameshazell.pilot.ui.components.StateScaffold
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens

/** Pilot: talk or type to the house assistant. */
@Composable
fun AssistantScreen() {
    val model = appViewModel { AssistantViewModel(it.pilot) }
    val snapshot by model.snapshot.collectAsStateWithLifecycle()
    val roomId by model.selectedRoomId.collectAsStateWithLifecycle()

    Column(Modifier.fillMaxSize()) {
        ScreenHeader(
            title = "Pilot",
            status = if (snapshot.isLive) "Ready" else "Waiting for Pilot Core",
            statusColor = if (snapshot.isLive) PilotColors.Teal else PilotColors.TextDim,
        )
        StateScaffold(snapshot, onRetry = model::refresh, loadingLabel = "Connecting to Pilot Core…") { value ->
            // FEATURE: replace this placeholder with the assistant conversation (message list,
            // text input, hold-to-talk, reply cards and sources).
            Column(
                Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(PilotDimens.ScreenPadding),
                verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap),
            ) {
                SectionHeader("Connection")
                PilotCard {
                    val room = value.media.rooms.firstOrNull { it.id == roomId }
                    CardNote(room?.let { "Answering for ${it.name}." } ?: "No room is assigned to this phone yet.")
                }
            }
        }
    }
}
