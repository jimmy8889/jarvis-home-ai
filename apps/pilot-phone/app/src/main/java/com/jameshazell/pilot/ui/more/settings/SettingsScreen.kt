package com.jameshazell.pilot.ui.more.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.jameshazell.pilot.core.PilotConfig
import com.jameshazell.pilot.ui.components.CardNote
import com.jameshazell.pilot.ui.components.Chip
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.PillSwitch
import com.jameshazell.pilot.ui.components.SectionHeader
import com.jameshazell.pilot.ui.home.ControlRow
import com.jameshazell.pilot.ui.home.DetailHeader
import com.jameshazell.pilot.ui.home.PillButton
import com.jameshazell.pilot.ui.more.ServiceStatus
import com.jameshazell.pilot.ui.more.StatusTone
import com.jameshazell.pilot.ui.more.refreshChoices
import com.jameshazell.pilot.ui.more.refreshLabel
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens

/** Everything the Settings and About pages show. */
data class SettingsState(
    val services: List<ServiceStatus>,
    val config: PilotConfig,
    val canControlHome: Boolean,
    val versionName: String,
    val versionCode: Int,
)

interface SettingsActions {
    fun refresh()
    fun setRefreshSeconds(seconds: Int)
    fun setKeepScreenOn(enabled: Boolean)
    fun requestRepair()
    fun requestUnpair()
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SettingsPage(state: SettingsState, actions: SettingsActions, onBack: () -> Unit) {
    Column(Modifier.fillMaxSize()) {
        DetailHeader("Settings", onBack)
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(start = PilotDimens.ScreenPadding, end = PilotDimens.ScreenPadding, bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap),
        ) {
            SectionHeader("Connections", actionLabel = "Refresh", onAction = actions::refresh)
            PilotCard(Modifier.fillMaxWidth()) {
                Column {
                    state.services.forEachIndexed { index, service ->
                        if (index > 0) HorizontalDivider(color = PilotColors.Hairline, modifier = Modifier.padding(vertical = 4.dp))
                        ServiceRow(service)
                    }
                }
            }

            SectionHeader("Pilot Core")
            PilotCard(Modifier.fillMaxWidth()) {
                ControlRow("Address", subtitle = state.config.coreUrl)
                ControlRow("Phone ID", subtitle = state.config.deviceId.ifBlank { "Not paired" })
                CardNote(
                    if (state.canControlHome) "This phone can control room devices."
                    else "This phone can view room devices but not control them.",
                )
                CardNote("To use a different Pilot Core address, pair this phone again.")
            }

            SectionHeader("Refresh")
            PilotCard(Modifier.fillMaxWidth()) {
                CardNote("How often Home is refreshed when live updates aren't available.")
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    refreshChoices(state.config.refreshSeconds).forEach { seconds ->
                        Chip(
                            label = refreshLabel(seconds),
                            selected = seconds == state.config.refreshSeconds,
                            onClick = { actions.setRefreshSeconds(seconds) },
                        )
                    }
                }
            }

            SectionHeader("Display")
            PilotCard(Modifier.fillMaxWidth()) {
                ControlRow("Keep screen on", subtitle = "While Pilot is open on this phone.") {
                    PillSwitch(
                        checked = state.config.keepScreenOn,
                        onCheckedChange = actions::setKeepScreenOn,
                        label = "Keep screen on",
                    )
                }
            }

            SectionHeader("Pairing")
            PilotCard(Modifier.fillMaxWidth()) {
                CardNote(
                    "Pairing again or unpairing removes this phone's Pilot Core identity. " +
                        "Energy Manager and James Control stay set up.",
                )
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    PillButton("Pair again", actions::requestRepair)
                    PillButton("Unpair this phone", actions::requestUnpair, accent = PilotColors.Red, filled = true)
                }
            }

            SectionHeader("App")
            PilotCard(Modifier.fillMaxWidth()) {
                ControlRow("Version", subtitle = "Pilot ${state.versionName} (build ${state.versionCode})")
            }
        }
    }
}

@Composable
private fun ServiceRow(service: ServiceStatus) {
    val color = when (service.tone) {
        StatusTone.Good -> PilotColors.Teal
        StatusTone.Warning -> PilotColors.Amber
        StatusTone.Bad -> PilotColors.Red
        StatusTone.Idle -> PilotColors.TextFaint
    }
    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp).semantics(mergeDescendants = true) {}) {
        Box(Modifier.padding(top = 7.dp).size(10.dp).background(color, CircleShape))
        Spacer(Modifier.width(PilotDimens.Gap))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(service.name, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                Text(service.label, style = MaterialTheme.typography.labelLarge, color = color)
            }
            if (!service.detail.isNullOrBlank()) {
                Text(service.detail, style = MaterialTheme.typography.bodyMedium, color = PilotColors.TextDim)
            }
        }
    }
}

@Composable
fun AboutPage(state: SettingsState, onBack: () -> Unit) {
    Column(Modifier.fillMaxSize()) {
        DetailHeader("About", onBack)
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(start = PilotDimens.ScreenPadding, end = PilotDimens.ScreenPadding, bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap),
        ) {
            PilotCard(Modifier.fillMaxWidth()) {
                Text("Pilot", style = MaterialTheme.typography.headlineMedium)
                CardNote("Version ${state.versionName} (build ${state.versionCode})", color = PilotColors.Text)
                CardNote("The house on this phone: rooms and devices, energy, James Control and the Pilot assistant.")
            }
            SectionHeader("What it talks to")
            PilotCard(Modifier.fillMaxWidth()) {
                ControlRow("Pilot Core", subtitle = "Home, music and the assistant. Every device command goes through it.")
                ControlRow("Energy Manager", subtitle = "Solar, battery and tariff detail on the Energy tab.")
                ControlRow("James Control", subtitle = "Projects, tasks and approvals on the Control tab.")
            }
            SectionHeader("Your data")
            PilotCard(Modifier.fillMaxWidth()) {
                CardNote("This phone's credentials are stored encrypted on the phone and are only sent to the service they belong to.")
                CardNote("The last readings are saved on the phone so the app opens instantly. Saved data is marked and is read-only.")
                CardNote("Commands are only sent while connected. They are never queued for later.")
            }
        }
    }
}
