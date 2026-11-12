package com.jameshazell.pilot.ui.home.rooms

import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.jameshazell.pilot.data.pilot.HomeControlKind
import com.jameshazell.pilot.data.pilot.HomeEntity
import com.jameshazell.pilot.data.pilot.MediaCommand
import com.jameshazell.pilot.data.pilot.PilotPlayerState
import com.jameshazell.pilot.ui.components.CardNote
import com.jameshazell.pilot.ui.components.Chip
import com.jameshazell.pilot.ui.components.LevelSlider
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.PillSwitch
import com.jameshazell.pilot.ui.components.SectionHeader
import com.jameshazell.pilot.ui.home.ControlRow
import com.jameshazell.pilot.ui.home.DetailHeader
import com.jameshazell.pilot.ui.home.HomeActions
import com.jameshazell.pilot.ui.home.HomeIcons
import com.jameshazell.pilot.ui.home.HomeScreenState
import com.jameshazell.pilot.ui.home.HvacModes
import com.jameshazell.pilot.ui.home.InlineMessage
import com.jameshazell.pilot.ui.home.OpenRoom
import com.jameshazell.pilot.ui.home.PillButton
import com.jameshazell.pilot.ui.home.RoundIconButton
import com.jameshazell.pilot.ui.home.averageBrightness
import com.jameshazell.pilot.ui.home.brightnessTargets
import com.jameshazell.pilot.ui.home.can
import com.jameshazell.pilot.ui.home.canSwitch
import com.jameshazell.pilot.ui.home.climateActive
import com.jameshazell.pilot.ui.home.climateStatus
import com.jameshazell.pilot.ui.home.degrees
import com.jameshazell.pilot.ui.home.hvacModeLabel
import com.jameshazell.pilot.ui.home.isGarageLike
import com.jameshazell.pilot.ui.home.isLit
import com.jameshazell.pilot.ui.home.stateLabel
import com.jameshazell.pilot.ui.home.steppedTarget
import com.jameshazell.pilot.ui.home.usable
import com.jameshazell.pilot.ui.more.music.isPlaying
import com.jameshazell.pilot.ui.more.music.nowPlayingSubtitle
import com.jameshazell.pilot.ui.more.music.nowPlayingTitle
import com.jameshazell.pilot.ui.more.music.supports
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens
import com.jameshazell.pilot.ui.theme.PilotIcons
import com.jameshazell.pilot.ui.theme.PilotText
import kotlin.math.roundToInt

/** How a card reaches the view model for one room, and whether its controls may be used. */
private class RoomScope(val roomId: String, val state: HomeScreenState, val actions: HomeActions) {
    fun enabled(entity: HomeEntity): Boolean =
        state.controlsEnabled && entity.usable && entity.entityId !in state.busy

    fun send(entity: HomeEntity, action: String, value: Double? = null, option: String? = null) =
        actions.act(roomId, entity, action, value, option)
}

/** One room: lights, scenes, climate, covers, locks, fans, media and everything else in it. */
@Composable
fun RoomDetail(room: OpenRoom, state: HomeScreenState, actions: HomeActions, modifier: Modifier = Modifier) {
    val scope = RoomScope(room.summary.id, state, actions)
    val content = room.content
    Column(modifier.fillMaxSize()) {
        DetailHeader(
            title = room.summary.name,
            subtitle = room.summary.status,
            onBack = actions::closeRoom,
        ) {
            if (room.loading) {
                CircularProgressIndicator(
                    color = PilotColors.Violet, strokeWidth = 2.dp,
                    modifier = Modifier.padding(12.dp).size(24.dp).semantics { contentDescription = "Refreshing devices" },
                )
            } else {
                RoundIconButton(
                    PilotIcons.Refresh, "Refresh ${room.summary.name}",
                    onClick = { actions.retryRoom(room.summary.id) }, enabled = state.online,
                )
            }
        }
        // Keyed by room so each room starts scrolled to the top.
        key(room.summary.id) {
            Column(
                Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(start = PilotDimens.ScreenPadding, end = PilotDimens.ScreenPadding, bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap),
            ) {
                state.error?.let { InlineMessage(it, actionLabel = "Dismiss", onAction = actions::dismissError) }
                if (room.loadError != null) {
                    InlineMessage(
                        if (room.summary.loaded) "Couldn't refresh this room. ${room.loadError}" else room.loadError,
                        color = PilotColors.Amber,
                        actionLabel = "Retry",
                        onAction = { actions.retryRoom(room.summary.id) },
                    )
                }
                state.controlNotice?.takeIf { room.summary.loaded }?.let {
                    InlineMessage(it, color = PilotColors.Amber)
                }

                if (!room.summary.loaded && room.loadError == null) {
                    when {
                        room.loading -> LoadingDevices()
                        state.online -> CardNote("Tap refresh to load this room's devices.")
                        else -> CardNote("Room devices appear when Pilot Core is reachable.")
                    }
                }
                if (content.lights.isNotEmpty()) LightsCard(content.lights, scope)
                if (content.scenes.isNotEmpty()) ScenesSection(content.scenes, scope)
                if (content.climates.isNotEmpty()) {
                    Section("Climate") { content.climates.forEach { ClimateCard(it, scope) } }
                }
                if (content.covers.isNotEmpty()) {
                    Section("Covers") { content.covers.forEach { CoverCard(it, scope) } }
                }
                if (content.locks.isNotEmpty()) {
                    Section("Locks") { PilotCard(Modifier.fillMaxWidth()) { Divided(content.locks) { LockRow(it, scope) } } }
                }
                if (content.fans.isNotEmpty()) {
                    Section("Fans") { content.fans.forEach { FanCard(it, scope) } }
                }
                if (room.players.isNotEmpty()) {
                    Section("Media") { room.players.forEach { MediaCard(it, state, actions) } }
                }
                content.others.forEach { group ->
                    Section(group.title) {
                        PilotCard(Modifier.fillMaxWidth()) { Divided(group.entities) { OtherRow(it, scope) } }
                    }
                }
                if (room.summary.loaded && content.isEmpty && room.players.isEmpty()) {
                    CardNote("Pilot Core has no devices for this room.")
                }
            }
        }
    }
}

@Composable
private fun LoadingDevices() {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 8.dp)) {
        CircularProgressIndicator(color = PilotColors.Violet, strokeWidth = 2.dp, modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(PilotDimens.Gap))
        Text("Loading devices…", style = MaterialTheme.typography.bodyMedium, color = PilotColors.TextDim)
    }
}

@Composable
private fun Section(title: String, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        SectionHeader(title)
        content()
    }
}

@Composable
private fun <T> Divided(items: List<T>, row: @Composable (T) -> Unit) {
    Column {
        items.forEachIndexed { index, item ->
            if (index > 0) HorizontalDivider(color = PilotColors.Hairline, modifier = Modifier.padding(vertical = 4.dp))
            row(item)
        }
    }
}

// ---- Lights -------------------------------------------------------------------------------

@Composable
private fun LightsCard(lights: List<HomeEntity>, scope: RoomScope) {
    val lit = lights.count { it.isLit }
    val level = averageBrightness(lights)
    val switchable = lights.filter { it.usable && it.canSwitch }
    val dimmable = brightnessTargets(lights)
    val groupEnabled = scope.state.controlsEnabled && switchable.none { it.entityId in scope.state.busy }
    Section("Lights") {
        PilotCard(Modifier.fillMaxWidth(), tint = PilotColors.Amber.takeIf { lit > 0 }) {
            ControlRow(
                title = if (lights.size == 1) lights.first().displayName else "All lights",
                subtitle = when {
                    lights.size == 1 -> stateLabel(lights.first())
                    lit == 0 -> "Off"
                    level != null -> "$lit of ${lights.size} on · $level%"
                    else -> "$lit of ${lights.size} on"
                },
                icon = PilotIcons.Light,
                iconTint = if (lit > 0) PilotColors.Amber else PilotColors.TextFaint,
            ) {
                if (switchable.isNotEmpty()) {
                    PillSwitch(
                        checked = lit > 0,
                        onCheckedChange = { scope.actions.toggleRoomLights(scope.roomId) },
                        label = if (lights.size == 1) lights.first().displayName else "All lights",
                        accent = PilotColors.Amber,
                        enabled = groupEnabled,
                    )
                }
            }
            if (dimmable.isNotEmpty()) {
                val shown = (level ?: 0).toFloat()
                var preview by remember(scope.roomId, shown) { mutableFloatStateOf(shown) }
                LevelSlider(
                    label = "Brightness",
                    value = preview,
                    valueText = "${preview.roundToInt()}%",
                    onValueChange = { preview = it },
                    onValueChangeFinished = { scope.actions.setRoomBrightness(scope.roomId, preview.roundToInt()) },
                    steps = 19,
                    accent = PilotColors.Amber,
                    enabled = groupEnabled,
                )
            }
            if (lights.size > 1) {
                Divided(lights) { light ->
                    ControlRow(
                        title = light.displayName,
                        subtitle = stateLabel(light),
                        subtitleColor = if (light.usable) PilotColors.TextDim else PilotColors.Amber,
                    ) {
                        if (light.canSwitch) {
                            PillSwitch(
                                checked = light.isLit,
                                onCheckedChange = { scope.send(light, if (it) "turn_on" else "turn_off") },
                                label = light.displayName,
                                accent = PilotColors.Amber,
                                enabled = scope.enabled(light),
                            )
                        }
                    }
                }
            }
        }
    }
}

// ---- Scenes -------------------------------------------------------------------------------

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ScenesSection(scenes: List<HomeEntity>, scope: RoomScope) {
    Section("Scenes") {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            scenes.forEach { scene ->
                PillButton(
                    label = scene.displayName,
                    onClick = { scope.send(scene, "activate") },
                    enabled = scope.enabled(scene) && scene.can("activate"),
                    icon = HomeIcons.Scene,
                    modifier = Modifier.semantics { contentDescription = "Activate ${scene.displayName}" },
                )
            }
        }
    }
}

// ---- Climate ------------------------------------------------------------------------------

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ClimateCard(entity: HomeEntity, scope: RoomScope) {
    val active = entity.climateActive
    val accent = if (entity.state.equals("heat", ignoreCase = true)) PilotColors.Amber else PilotColors.Blue
    val enabled = scope.enabled(entity)
    PilotCard(Modifier.fillMaxWidth(), tint = accent.takeIf { active }) {
        ControlRow(
            title = entity.displayName,
            subtitle = if (entity.stale) "Waiting to refresh" else climateStatus(entity),
            icon = HomeIcons.Thermostat,
            iconTint = if (active) accent else PilotColors.TextFaint,
        ) {
            if (entity.canSwitch && !entity.can("set_hvac_mode")) {
                PillSwitch(
                    checked = active,
                    onCheckedChange = { scope.send(entity, if (it) "turn_on" else "turn_off") },
                    label = "${entity.displayName} power",
                    accent = accent,
                    enabled = enabled,
                )
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f).semantics(mergeDescendants = true) {}) {
                Text("Now", style = MaterialTheme.typography.labelMedium, color = PilotColors.TextDim)
                Text(entity.currentTemperature?.let(::degrees) ?: "—", style = PilotText.Value)
            }
            if (entity.can("set_temperature")) {
                val target = entity.targetTemperature
                val canStep = enabled && active && target != null
                RoundIconButton(
                    HomeIcons.Minus, "Cooler", outlined = true, enabled = canStep,
                    onClick = { steppedTarget(entity, -1)?.let { scope.send(entity, "set_temperature", it) } },
                )
                Column(
                    Modifier.width(76.dp).semantics(mergeDescendants = true) {},
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text("Target", style = MaterialTheme.typography.labelMedium, color = PilotColors.TextDim)
                    Text(target?.let(::degrees) ?: "—", style = MaterialTheme.typography.titleLarge)
                }
                RoundIconButton(
                    HomeIcons.Plus, "Warmer", outlined = true, enabled = canStep,
                    onClick = { steppedTarget(entity, +1)?.let { scope.send(entity, "set_temperature", it) } },
                )
            }
        }
        if (entity.can("set_hvac_mode")) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                HvacModes.forEach { mode ->
                    val selected = entity.usable && (entity.state.equals(mode, ignoreCase = true) ||
                        (mode == "auto" && entity.state.equals("heat_cool", ignoreCase = true)))
                    Chip(
                        label = hvacModeLabel(mode),
                        selected = selected,
                        onClick = { if (!selected) scope.send(entity, "set_hvac_mode", option = mode) },
                        accent = if (mode == "heat") PilotColors.Amber else PilotColors.Blue,
                        enabled = enabled,
                    )
                }
            }
        }
    }
}

// ---- Covers -------------------------------------------------------------------------------

@Composable
private fun CoverCard(entity: HomeEntity, scope: RoomScope) {
    val enabled = scope.enabled(entity)
    val garage = entity.isGarageLike
    PilotCard(Modifier.fillMaxWidth(), tint = PilotColors.Teal.takeIf { entity.usable && entity.isOn }) {
        ControlRow(
            title = entity.displayName,
            subtitle = stateLabel(entity),
            icon = HomeIcons.Blinds,
            iconTint = if (entity.usable && entity.isOn) PilotColors.Teal else PilotColors.TextFaint,
            subtitleColor = if (entity.usable) PilotColors.TextDim else PilotColors.Amber,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (entity.can("open")) {
                PillButton("Open", { scope.send(entity, "open") }, Modifier.weight(1f), enabled = enabled)
            }
            if (entity.can("stop")) {
                PillButton("Stop", { scope.send(entity, "stop") }, Modifier.weight(1f), enabled = enabled)
            }
            if (entity.can("close")) {
                PillButton("Close", { scope.send(entity, "close") }, Modifier.weight(1f), enabled = enabled)
            }
        }
        // A slider is too easy to brush for a garage door or gate; those only get the buttons.
        if (!garage && entity.can("set_position") && entity.positionPercent != null) {
            val position = entity.positionPercent
            var preview by remember(entity.entityId, position) { mutableFloatStateOf(position) }
            LevelSlider(
                label = "Position",
                value = preview,
                valueText = "${preview.roundToInt()}% open",
                onValueChange = { preview = it },
                onValueChangeFinished = { scope.send(entity, "set_position", preview.roundToInt().toDouble()) },
                steps = 19,
                accent = PilotColors.Teal,
                enabled = enabled,
            )
        }
        if (garage) CardNote("You'll be asked to confirm before it moves.")
    }
}

// ---- Locks and alarms ---------------------------------------------------------------------

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun LockRow(entity: HomeEntity, scope: RoomScope) {
    val enabled = scope.enabled(entity)
    val locked = entity.state.equals("locked", ignoreCase = true)
    val secure = locked || entity.state.lowercase().startsWith("armed")
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        ControlRow(
            title = entity.displayName,
            subtitle = stateLabel(entity),
            icon = HomeIcons.Lock,
            iconTint = if (!entity.usable) PilotColors.TextFaint else if (secure) PilotColors.Teal else PilotColors.Red,
            subtitleColor = if (entity.usable) PilotColors.TextDim else PilotColors.Amber,
        ) {
            if (entity.can("lock") && entity.can("unlock")) {
                PillButton(
                    label = if (locked) "Unlock" else "Lock",
                    onClick = { scope.send(entity, if (locked) "unlock" else "lock") },
                    enabled = enabled,
                )
            }
        }
        val alarmActions = listOf("arm_home" to "Arm home", "arm_away" to "Arm away", "disarm" to "Disarm")
            .filter { entity.can(it.first) }
        if (alarmActions.isNotEmpty()) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                alarmActions.forEach { (action, label) ->
                    PillButton(label, { scope.send(entity, action) }, enabled = enabled)
                }
            }
        }
    }
}

// ---- Fans ---------------------------------------------------------------------------------

@Composable
private fun FanCard(entity: HomeEntity, scope: RoomScope) {
    val enabled = scope.enabled(entity)
    val on = entity.usable && entity.isOn
    PilotCard(Modifier.fillMaxWidth(), tint = PilotColors.Teal.takeIf { on }) {
        ControlRow(
            title = entity.displayName,
            subtitle = stateLabel(entity),
            icon = HomeIcons.Air,
            iconTint = if (on) PilotColors.Teal else PilotColors.TextFaint,
            subtitleColor = if (entity.usable) PilotColors.TextDim else PilotColors.Amber,
        ) {
            if (entity.canSwitch) {
                PillSwitch(
                    checked = on,
                    onCheckedChange = { scope.send(entity, if (it) "turn_on" else "turn_off") },
                    label = entity.displayName,
                    accent = PilotColors.Teal,
                    enabled = enabled,
                )
            }
        }
        if (entity.can("set_percentage")) {
            val speed = entity.percentage ?: 0f
            var preview by remember(entity.entityId, speed) { mutableFloatStateOf(speed) }
            LevelSlider(
                label = "Speed",
                value = preview,
                valueText = "${preview.roundToInt()}%",
                onValueChange = { preview = it },
                onValueChangeFinished = { scope.send(entity, "set_percentage", preview.roundToInt().toDouble()) },
                steps = 19,
                accent = PilotColors.Teal,
                enabled = enabled,
            )
        }
    }
}

// ---- Media --------------------------------------------------------------------------------

@Composable
private fun MediaCard(player: PilotPlayerState, state: HomeScreenState, actions: HomeActions) {
    val effective = player.effective
    val enabled = state.online && !state.mediaBusy && effective.available && player.player.controlEnabled
    val playing = effective.isPlaying
    PilotCard(Modifier.fillMaxWidth(), tint = PilotColors.Pink.takeIf { playing }) {
        ControlRow(
            title = nowPlayingTitle(player),
            subtitle = nowPlayingSubtitle(player),
            icon = HomeIcons.Music,
            iconTint = if (playing) PilotColors.Pink else PilotColors.TextFaint,
        ) {
            val action = if (playing) "pause" else "play"
            if (effective.supports(action)) {
                RoundIconButton(
                    icon = if (playing) HomeIcons.Pause else HomeIcons.Play,
                    description = if (playing) "Pause ${player.player.name}" else "Play ${player.player.name}",
                    onClick = { actions.media(MediaCommand(action, player.player.id)) },
                    enabled = enabled,
                    filled = true,
                    accent = PilotColors.Pink,
                )
            }
        }
        val volume = effective.volumePercent
        if (volume != null && effective.supports("set_volume")) {
            var preview by remember(player.player.id, volume) { mutableFloatStateOf(volume.toFloat()) }
            LevelSlider(
                label = "Volume",
                value = preview,
                valueText = "${preview.roundToInt()}%",
                onValueChange = { preview = it },
                onValueChangeFinished = {
                    actions.media(MediaCommand("set_volume", player.player.id, volume = preview.roundToInt()))
                },
                accent = PilotColors.Pink,
                enabled = enabled,
            )
        }
    }
}

// ---- Switches, sensors and the rest ---------------------------------------------------------

@Composable
private fun OtherRow(entity: HomeEntity, scope: RoomScope) {
    val on = entity.usable && entity.isOn
    val (icon: ImageVector, tint: Color) = when (entity.controlKind) {
        HomeControlKind.Switch -> PilotIcons.Power to if (on) PilotColors.Violet else PilotColors.TextFaint
        HomeControlKind.Contact -> HomeIcons.Info to if (on) PilotColors.Amber else PilotColors.TextFaint
        else -> HomeIcons.Info to PilotColors.TextFaint
    }
    val switchable = entity.canSwitch
    ControlRow(
        title = entity.displayName,
        subtitle = if (switchable || !entity.usable) stateLabel(entity) else null,
        icon = icon,
        iconTint = tint,
        subtitleColor = if (entity.usable) PilotColors.TextDim else PilotColors.Amber,
    ) {
        when {
            switchable -> PillSwitch(
                checked = on,
                onCheckedChange = { scope.send(entity, if (it) "turn_on" else "turn_off") },
                label = entity.displayName,
                enabled = scope.enabled(entity),
            )
            entity.can("activate") -> PillButton(
                "Run", { scope.send(entity, "activate") }, enabled = scope.enabled(entity),
            )
            entity.usable -> Text(
                stateLabel(entity),
                style = MaterialTheme.typography.labelLarge,
                color = if (on && entity.controlKind == HomeControlKind.Contact) PilotColors.Amber else PilotColors.Text,
            )
        }
    }
}
