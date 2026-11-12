package com.jameshazell.pilot.ui.control

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
import com.jameshazell.pilot.data.control.ControlConnection
import com.jameshazell.pilot.ui.appViewModel
import com.jameshazell.pilot.ui.components.CardNote
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.ScreenHeader
import com.jameshazell.pilot.ui.components.SectionHeader
import com.jameshazell.pilot.ui.components.StateScaffold
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens

/** Control: James Control projects, tasks, workers, conversations and chat. */
@Composable
fun ControlScreen() {
    val model = appViewModel { ControlViewModel(it.control) }
    val overview by model.overview.collectAsStateWithLifecycle()
    val connection by model.connection.collectAsStateWithLifecycle()

    LifecycleStartEffect(model) {
        model.onScreenStarted()
        onStopOrDispose { model.onScreenStopped() }
    }

    Column(Modifier.fillMaxSize()) {
        ScreenHeader(
            title = "Control",
            status = controlStatus(connection),
            statusColor = when (connection) {
                ControlConnection.Live -> PilotColors.Teal
                ControlConnection.SessionExpired -> PilotColors.Red
                else -> PilotColors.TextDim
            },
        )
        StateScaffold(overview, onRetry = model::refresh, loadingLabel = "Connecting to James Control…") { value ->
            // FEATURE: replace this placeholder with the Control workspace. Suggested shape:
            // ListDetailLayout(list = projects / tasks / conversations, detail = chat or
            // transcript), with approvals surfaced above the list.
            Column(
                Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(PilotDimens.ScreenPadding),
                verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap),
            ) {
                SectionHeader("Connection")
                PilotCard {
                    CardNote(
                        "${value.projects.size} projects · ${value.tasks.size} tasks · " +
                            "${value.workers.size} workers · ${value.conversations.size} conversations",
                    )
                    if (connection == ControlConnection.SessionExpired) {
                        CardNote("This phone's session must be renewed before new messages can be sent.", color = PilotColors.Red)
                    }
                }
            }
        }
    }
}

internal fun controlStatus(connection: ControlConnection): String = when (connection) {
    ControlConnection.Idle -> "Not connected"
    ControlConnection.Connecting -> "Connecting"
    ControlConnection.Live -> "Live"
    is ControlConnection.Reconnecting -> "Reconnecting in ${connection.retryInSeconds} s"
    ControlConnection.SessionExpired -> "Session expired"
    ControlConnection.NotPaired -> "Not set up on this phone"
}
