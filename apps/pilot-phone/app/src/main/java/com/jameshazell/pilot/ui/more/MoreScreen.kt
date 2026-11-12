package com.jameshazell.pilot.ui.more

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.jameshazell.pilot.BuildConfig
import com.jameshazell.pilot.data.pilot.PilotRepository
import com.jameshazell.pilot.ui.appViewModel
import com.jameshazell.pilot.ui.components.CardNote
import com.jameshazell.pilot.ui.components.ConfirmDialog
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.PillSwitch
import com.jameshazell.pilot.ui.components.ScreenHeader
import com.jameshazell.pilot.ui.components.SectionHeader
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens

/** More: this phone's pairing, settings and app information. */
@Composable
fun MoreScreen() {
    val model = appViewModel { MoreViewModel(it.pilot) }
    val session by model.session.collectAsStateWithLifecycle()
    val snapshot by model.snapshot.collectAsStateWithLifecycle()
    val manifest by model.manifest.collectAsStateWithLifecycle()
    var confirmUnpair by rememberSaveable { mutableStateOf(false) }

    Column(Modifier.fillMaxSize()) {
        ScreenHeader(title = "More", status = "Pilot ${BuildConfig.VERSION_NAME}")
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(PilotDimens.ScreenPadding),
            verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap),
        ) {
            SectionHeader("Pilot Core")
            PilotCard {
                CardNote(session.config.coreUrl, color = PilotColors.Text)
                CardNote("Phone ID: ${session.config.deviceId}")
                CardNote(PilotRepository.dashboardLabel(snapshot, session.paired))
                CardNote(
                    if (manifest?.features?.contains(PilotRepository.FEATURE_HOME_CONTROL) == true) {
                        "This phone can control room devices."
                    } else "This phone can view room devices but not control them.",
                )
            }

            SectionHeader("Display")
            PilotCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Keep screen on", style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                    PillSwitch(
                        checked = session.config.keepScreenOn,
                        onCheckedChange = model::setKeepScreenOn,
                        label = "Keep screen on",
                    )
                }
            }

            // FEATURE: remaining settings and per-service status belong here.

            SectionHeader("Pairing")
            PilotCard {
                CardNote("Unpairing removes this phone's Pilot Core identity. Energy Manager and James Control stay set up.")
                TextButton(onClick = { confirmUnpair = true }, modifier = Modifier.heightIn(min = PilotDimens.TouchTarget)) {
                    Text("Unpair this phone", color = PilotColors.Red)
                }
            }
        }
    }

    if (confirmUnpair) {
        ConfirmDialog(
            title = "Unpair this phone?",
            message = "You'll need a new pairing grant from Pilot Core to use Home and Pilot again.",
            confirmLabel = "Unpair",
            destructive = true,
            onConfirm = {
                confirmUnpair = false
                model.unpair()
            },
            onDismiss = { confirmUnpair = false },
        )
    }
}
