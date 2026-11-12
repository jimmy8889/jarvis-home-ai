package com.jameshazell.pilot.ui.more.music

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.jameshazell.pilot.data.pilot.MediaCommand
import com.jameshazell.pilot.data.pilot.MediaQueue
import com.jameshazell.pilot.data.pilot.MusicSearchResult
import com.jameshazell.pilot.data.pilot.PilotPlayerState
import com.jameshazell.pilot.ui.appViewModel
import com.jameshazell.pilot.ui.components.CardNote
import com.jameshazell.pilot.ui.components.Chip
import com.jameshazell.pilot.ui.components.LevelSlider
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.SectionHeader
import com.jameshazell.pilot.ui.components.StateScaffold
import com.jameshazell.pilot.ui.home.ControlRow
import com.jameshazell.pilot.ui.home.DetailHeader
import com.jameshazell.pilot.ui.home.HomeIcons
import com.jameshazell.pilot.ui.home.InlineMessage
import com.jameshazell.pilot.ui.home.PillButton
import com.jameshazell.pilot.ui.home.RoundIconButton
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens
import kotlin.math.roundToInt

/** Music: pick a room, control what is playing there, see the queue, search and play. */
@Composable
fun MusicScreen(onBack: () -> Unit) {
    val model = appViewModel { MusicViewModel(it.pilot) }
    val snapshot by model.snapshot.collectAsStateWithLifecycle()
    val selectedRoomId by model.selectedRoomId.collectAsStateWithLifecycle()
    val ui by model.ui.collectAsStateWithLifecycle()

    Column(Modifier.fillMaxSize()) {
        DetailHeader("Music", onBack)
        StateScaffold(snapshot, onRetry = model::refresh, loadingLabel = "Connecting to Pilot Core…") { value ->
            val online = snapshot.isLive
            val state = remember(value, selectedRoomId, online, ui) { buildMusicState(value, selectedRoomId, online, ui) }
            MusicContent(state, model, model::artwork)
        }
    }
}

/** Stateless Music page body (everything under the header). */
@Composable
fun MusicContent(state: MusicScreenState, actions: MusicActions, artwork: ArtworkLoader) {
    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap),
    ) {
        val gutter = Modifier.padding(horizontal = PilotDimens.ScreenPadding)
        if (state.rooms.isEmpty()) {
            CardNote("Pilot Core hasn't listed a room with a music player yet.", gutter)
            return@Column
        }
        if (state.rooms.size > 1) {
            Row(
                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = PilotDimens.ScreenPadding),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                state.rooms.forEach { room ->
                    Chip(room.name, selected = room.id == state.roomId, onClick = { actions.selectRoom(room.id) })
                }
            }
        }
        state.ui.error?.let { InlineMessage(it, gutter, actionLabel = "Dismiss", onAction = actions::dismissError) }
        if (!state.online) {
            InlineMessage("Reconnect to control playback. Saved data is read-only.", gutter, color = PilotColors.Amber)
        }

        val player = state.player
        if (player == null) {
            PilotCard(gutter.fillMaxWidth()) {
                CardNote("No player in ${state.roomName ?: "this room"}. Choose another room.")
            }
        } else {
            NowPlaying(player, state, actions, artwork, gutter)
        }
        state.queue?.let { Queue(it, artwork, gutter) }
        Search(state, actions, artwork, gutter)
    }
}

@Composable
private fun NowPlaying(
    player: PilotPlayerState,
    state: MusicScreenState,
    actions: MusicActions,
    artwork: ArtworkLoader,
    modifier: Modifier,
) {
    val effective = player.effective
    val id = player.player.id
    val enabled = state.commandsEnabled && effective.available && player.player.controlEnabled
    PilotCard(modifier.fillMaxWidth(), tint = PilotColors.Pink.takeIf { effective.isPlaying }) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Artwork(effective.media?.imageUrl, artwork, Modifier.size(88.dp))
            Spacer(Modifier.width(PilotDimens.Gap))
            Column(Modifier.weight(1f).semantics(mergeDescendants = true) {}) {
                Text(
                    player.player.name.uppercase(),
                    style = MaterialTheme.typography.labelSmall,
                    color = PilotColors.Pink,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    nowPlayingTitle(player),
                    style = MaterialTheme.typography.titleLarge,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    nowPlayingSubtitle(player),
                    style = MaterialTheme.typography.bodyMedium,
                    color = PilotColors.TextDim,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }

        playbackProgress(effective)?.let { (position, duration) ->
            var preview by remember(id, position, duration) { mutableFloatStateOf(position) }
            val canSeek = effective.supports("seek")
            LevelSlider(
                label = formatDuration(preview.toDouble()),
                value = preview,
                valueText = formatDuration(duration.toDouble()),
                onValueChange = { preview = it },
                onValueChangeFinished = {
                    if (canSeek) actions.command(MediaCommand("seek", id, positionSeconds = preview.toDouble()))
                },
                range = 0f..duration,
                accent = PilotColors.Pink,
                enabled = enabled && canSeek,
                modifier = Modifier.semantics { contentDescription = "Playback position" },
            )
        }

        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
            if (effective.supports("previous")) {
                RoundIconButton(HomeIcons.Previous, "Previous track", { actions.command(MediaCommand("previous", id)) }, enabled = enabled)
            }
            Spacer(Modifier.width(8.dp))
            val toggle = if (effective.isPlaying) "pause" else "play"
            RoundIconButton(
                icon = if (effective.isPlaying) HomeIcons.Pause else HomeIcons.Play,
                description = if (effective.isPlaying) "Pause" else "Play",
                onClick = { actions.command(MediaCommand(toggle, id)) },
                enabled = enabled && effective.supports(toggle),
                filled = true,
                accent = PilotColors.Pink,
            )
            Spacer(Modifier.width(8.dp))
            if (effective.supports("next")) {
                RoundIconButton(HomeIcons.Next, "Next track", { actions.command(MediaCommand("next", id)) }, enabled = enabled)
            }
            if (effective.supports("stop")) {
                RoundIconButton(HomeIcons.Stop, "Stop", { actions.command(MediaCommand("stop", id)) }, enabled = enabled)
            }
        }

        val volume = effective.volumePercent
        if (volume != null && effective.supports("set_volume")) {
            var preview by remember(id, volume) { mutableFloatStateOf(volume.toFloat()) }
            Row(verticalAlignment = Alignment.Bottom) {
                LevelSlider(
                    label = if (effective.muted == true) "Volume · muted" else "Volume",
                    value = preview,
                    valueText = "${preview.roundToInt()}%",
                    onValueChange = { preview = it },
                    onValueChangeFinished = { actions.command(MediaCommand("set_volume", id, volume = preview.roundToInt())) },
                    accent = PilotColors.Pink,
                    enabled = enabled,
                    modifier = Modifier.weight(1f),
                )
                if (effective.supports("mute")) {
                    Spacer(Modifier.width(8.dp))
                    PillButton(
                        label = if (effective.muted == true) "Unmute" else "Mute",
                        onClick = { actions.command(MediaCommand("mute", id, muted = effective.muted != true)) },
                        enabled = enabled,
                    )
                }
            }
        }

        if (state.moveTargets.isNotEmpty()) {
            Text("MOVE TO", style = MaterialTheme.typography.labelSmall, color = PilotColors.TextDim)
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                state.moveTargets.forEach { room ->
                    PillButton(
                        label = room.name,
                        onClick = {
                            actions.command(
                                MediaCommand("transfer", id, targetRoomId = room.id, targetPlayerId = room.defaultMusicPlayerId),
                            )
                        },
                        enabled = enabled,
                        modifier = Modifier.semantics { contentDescription = "Move music to ${room.name}" },
                    )
                    if (effective.supports("group")) {
                        PillButton(
                            label = "Add ${room.name}",
                            onClick = {
                                actions.command(
                                    MediaCommand("group", id, targetRoomId = room.id, targetPlayerId = room.defaultMusicPlayerId),
                                )
                            },
                            enabled = enabled,
                            icon = HomeIcons.Plus,
                        )
                    }
                }
            }
        }
        if (effective.groupMembers.isNotEmpty()) {
            CardNote("Playing together: ${effective.groupMembers.joinToString()}", color = PilotColors.Teal)
        }
    }
}

@Composable
private fun Queue(queue: MediaQueue, artwork: ArtworkLoader, modifier: Modifier) {
    Column(modifier) {
        SectionHeader("Queue")
        PilotCard(Modifier.fillMaxWidth()) {
            Column {
                val shown = queue.items.take(MAX_QUEUE_ROWS)
                shown.forEachIndexed { index, item ->
                    if (index > 0) HorizontalDivider(color = PilotColors.Hairline, modifier = Modifier.padding(vertical = 4.dp))
                    val current = item.active || queue.index == index
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Artwork(item.imageUrl, artwork, Modifier.size(44.dp), corner = 10.dp)
                        Spacer(Modifier.width(PilotDimens.Gap))
                        ControlRow(
                            title = item.title,
                            subtitle = listOfNotNull("Now playing".takeIf { current }, item.artist ?: item.album)
                                .joinToString(" · ").ifBlank { null },
                            subtitleColor = if (current) PilotColors.Pink else PilotColors.TextDim,
                            modifier = Modifier.weight(1f),
                        ) {
                            item.durationSeconds?.let {
                                Text(formatDuration(it), style = MaterialTheme.typography.labelMedium, color = PilotColors.TextDim)
                            }
                        }
                    }
                }
                if (queue.items.size > shown.size) {
                    CardNote("and ${queue.items.size - shown.size} more", Modifier.padding(top = 8.dp))
                }
            }
        }
    }
}

@Composable
private fun Search(state: MusicScreenState, actions: MusicActions, artwork: ArtworkLoader, modifier: Modifier) {
    val keyboard = LocalSoftwareKeyboardController.current
    val ui = state.ui
    val submit = {
        keyboard?.hide()
        actions.search()
    }
    Column(modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        SectionHeader("Search")
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = ui.query,
                onValueChange = actions::setQuery,
                label = { Text("Artist, album, track or playlist") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                keyboardActions = KeyboardActions(onSearch = { submit() }),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = PilotColors.Violet,
                    unfocusedBorderColor = PilotColors.TextFaint,
                    focusedLabelColor = PilotColors.Violet,
                    cursorColor = PilotColors.Violet,
                ),
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(8.dp))
            if (ui.searching) {
                CircularProgressIndicator(color = PilotColors.Violet, strokeWidth = 2.dp, modifier = Modifier.padding(12.dp).size(24.dp))
            } else {
                RoundIconButton(
                    HomeIcons.Search, "Search", submit, enabled = ui.query.isNotBlank(), filled = true,
                )
            }
        }
        when {
            ui.searchedFor == null -> Unit
            ui.results.isEmpty() -> CardNote("Nothing found for “${ui.searchedFor}”. Try an artist, album, track or playlist.")
            else -> PilotCard(Modifier.fillMaxWidth()) {
                Column {
                    ui.results.forEachIndexed { index, result ->
                        if (index > 0) HorizontalDivider(color = PilotColors.Hairline, modifier = Modifier.padding(vertical = 4.dp))
                        SearchRow(result, state, actions, artwork)
                    }
                }
            }
        }
    }
}

@Composable
private fun SearchRow(result: MusicSearchResult, state: MusicScreenState, actions: MusicActions, artwork: ArtworkLoader) {
    // Play on the room's player; with none loaded Pilot Core uses the room's default player.
    val canPlay = state.commandsEnabled && state.roomId != null
    Row(verticalAlignment = Alignment.CenterVertically) {
        Artwork(result.imageUrl, artwork, Modifier.size(48.dp), corner = 10.dp)
        Spacer(Modifier.width(PilotDimens.Gap))
        ControlRow(
            title = result.title,
            subtitle = result.subtitle.ifBlank { result.mediaType.orEmpty() }.ifBlank { null },
            modifier = Modifier.weight(1f),
        ) {
            RoundIconButton(
                HomeIcons.Play,
                "Play ${result.title}" + state.roomName?.let { " in $it" }.orEmpty(),
                { actions.play(result, state.player?.player?.id) },
                enabled = canPlay,
                outlined = true,
            )
        }
    }
}

private const val MAX_QUEUE_ROWS = 12
