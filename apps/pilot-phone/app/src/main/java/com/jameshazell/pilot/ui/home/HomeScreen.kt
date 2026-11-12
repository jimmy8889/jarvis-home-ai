package com.jameshazell.pilot.ui.home

import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.jameshazell.pilot.data.pilot.PilotRepository
import com.jameshazell.pilot.ui.appViewModel
import com.jameshazell.pilot.ui.adaptive.ListDetailLayout
import com.jameshazell.pilot.ui.components.CardNote
import com.jameshazell.pilot.ui.components.ConfirmDialog
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.RoomTile
import com.jameshazell.pilot.ui.components.SectionHeader
import com.jameshazell.pilot.ui.components.StatCell
import com.jameshazell.pilot.ui.components.StateScaffold
import com.jameshazell.pilot.ui.home.rooms.RoomDetail
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens
import com.jameshazell.pilot.ui.theme.PilotIcons
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Home: greeting, house status, energy summary and the rooms, with room detail beside or over it. */
@Composable
fun HomeScreen() {
    val model = appViewModel { HomeViewModel(it.pilot) }
    val snapshot by model.snapshot.collectAsStateWithLifecycle()
    val manifest by model.manifest.collectAsStateWithLifecycle()
    val local by model.local.collectAsStateWithLifecycle()

    DisposableEffect(model) {
        model.setVisible(true)
        onDispose { model.setVisible(false) }
    }

    StateScaffold(snapshot, onRetry = model::refresh, loadingLabel = "Connecting to Pilot Core…") { value ->
        val online = snapshot.isLive
        val canControl = manifest?.features?.contains(PilotRepository.FEATURE_HOME_CONTROL) == true
        val label = PilotRepository.dashboardLabel(snapshot)
        val state = remember(value, online, canControl, local, label) {
            buildHomeState(value, online, canControl, local, label)
        }
        HomeContent(state, model)
    }

    local.confirm?.let { pending ->
        ConfirmDialog(
            title = pending.prompt.title,
            message = pending.prompt.message,
            confirmLabel = pending.prompt.confirmLabel,
            destructive = pending.prompt.destructive,
            busy = pending.busy,
            error = pending.error,
            onConfirm = model::confirmPending,
            onDismiss = model::cancelPending,
        )
    }
}

/** Stateless Home: the dashboard list with the open room beside it (open Fold) or over it. */
@Composable
fun HomeContent(state: HomeScreenState, actions: HomeActions, now: LocalDateTime = LocalDateTime.now()) {
    ListDetailLayout(
        hasDetail = state.openRoom != null,
        onBack = actions::closeRoom,
        listFraction = 0.46f,
        list = { HomeList(state, actions, now) },
        detail = { state.openRoom?.let { RoomDetail(it, state, actions) } },
        emptyDetail = {
            EmptyDetail(
                title = "Choose a room",
                text = "Its lights, climate and other devices appear here.",
                icon = PilotIcons.Home,
            )
        },
    )
}

@Composable
private fun HomeList(state: HomeScreenState, actions: HomeActions, now: LocalDateTime) {
    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(vertical = PilotDimens.ScreenPadding),
        verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap),
    ) {
        val gutter = Modifier.padding(horizontal = PilotDimens.ScreenPadding)
        Greeting(state, now, gutter)
        StatusChips(state, actions)
        // An open room shows its own errors.
        if (state.error != null && state.openRoom == null) {
            InlineMessage(state.error, gutter, actionLabel = "Dismiss", onAction = actions::dismissError)
        }
        state.energy?.let { EnergyCard(it, gutter) }
        Rooms(state, actions, gutter)
    }
}

@Composable
private fun Greeting(state: HomeScreenState, now: LocalDateTime, modifier: Modifier) {
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(
                greetingFor(now.hour),
                style = MaterialTheme.typography.headlineMedium,
                modifier = Modifier.semantics { heading() },
            )
            Text(
                listOf(now.format(DateFormat), state.statusLabel).filter { it.isNotBlank() }.joinToString(" · "),
                style = MaterialTheme.typography.bodyMedium,
                color = if (state.online) PilotColors.TextDim else PilotColors.Amber,
            )
        }
        state.weather?.let { weather ->
            Spacer(Modifier.padding(start = 8.dp))
            StatusPill(weather.label, HomeIcons.Cloud, accent = PilotColors.Blue, active = true)
        }
    }
}

private val DateFormat: DateTimeFormatter = DateTimeFormatter.ofPattern("EEEE d MMMM", Locale.getDefault())

@Composable
private fun StatusChips(state: HomeScreenState, actions: HomeActions) {
    val house = state.house
    val chips = buildList<@Composable () -> Unit> {
        if (house.playing > 0) add {
            StatusPill(
                if (house.playing == 1) "Music playing" else "${house.playing} rooms playing",
                HomeIcons.Music,
                accent = PilotColors.Pink,
                active = true,
            )
        }
        if (house.carCharging) add {
            StatusPill("Car charging", HomeIcons.Car, accent = PilotColors.Teal, active = true)
        }
    }
    if (chips.isEmpty()) return
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = PilotDimens.ScreenPadding),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) { chips.forEach { it() } }
}

@Composable
private fun EnergyCard(energy: EnergySummary, modifier: Modifier) {
    Column(modifier) {
        SectionHeader("Energy")
        PilotCard(Modifier.fillMaxWidth()) {
            Row(horizontalArrangement = Arrangement.spacedBy(PilotDimens.Gap)) {
                EnergyCell(PilotIcons.Sun, "Solar", energy.solar, PilotColors.Amber, Modifier.weight(1f))
                EnergyCell(PilotIcons.Home, "House", energy.house, PilotColors.Violet, Modifier.weight(1f))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(PilotDimens.Gap)) {
                EnergyCell(PilotIcons.Battery, "Battery", energy.battery, PilotColors.Teal, Modifier.weight(1f))
                EnergyCell(PilotIcons.Energy, "Grid", energy.grid, PilotColors.Blue, Modifier.weight(1f))
            }
        }
    }
}

@Composable
private fun EnergyCell(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    reading: EnergyReading,
    accent: androidx.compose.ui.graphics.Color,
    modifier: Modifier,
) {
    StatCell(icon, label, reading.value, modifier, unit = reading.unit, note = reading.note, accent = accent)
}

@Composable
private fun Rooms(state: HomeScreenState, actions: HomeActions, modifier: Modifier) {
    Column(modifier) {
        SectionHeader("Rooms")
        if (state.rooms.isEmpty()) {
            PilotCard(Modifier.fillMaxWidth()) { CardNote("Pilot Core hasn't listed any rooms yet.") }
            return
        }
        BoxWithConstraints(Modifier.fillMaxWidth()) {
            val columns = (maxWidth / 250.dp).toInt().coerceIn(1, 3)
            Column(verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap)) {
                state.rooms.chunked(columns).forEach { row ->
                    Row(horizontalArrangement = Arrangement.spacedBy(PilotDimens.Gap)) {
                        row.forEach { room ->
                            val selected = state.openRoom?.summary?.id == room.id
                            RoomTile(
                                name = room.name,
                                status = room.status.ifEmpty { "Open to see devices" },
                                active = room.active,
                                onClick = { actions.openRoom(room.id) },
                                modifier = Modifier
                                    .weight(1f)
                                    .then(
                                        if (selected) Modifier.border(
                                            2.dp, PilotColors.Violet, RoundedCornerShape(PilotDimens.CardRadius),
                                        ) else Modifier,
                                    ),
                                icon = if (room.active) PilotIcons.Light else PilotIcons.Home,
                                onPower = if (room.canToggleLights) ({ actions.toggleRoomLights(room.id) }) else null,
                                powerEnabled = state.controlsEnabled,
                            )
                        }
                        repeat(columns - row.size) { Spacer(Modifier.weight(1f)) }
                    }
                }
            }
        }
    }
}
