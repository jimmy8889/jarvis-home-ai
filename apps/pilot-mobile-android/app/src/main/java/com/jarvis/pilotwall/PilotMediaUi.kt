package com.jarvis.pilotwall

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlin.math.roundToInt

@Composable
fun PilotMusicExperience(state: PilotUiState, model: PilotViewModel) {
    val player = state.snapshot?.media?.players?.firstOrNull {
        it.player.roomId == state.selectedRoom?.id && it.effective.media?.title != null
    } ?: state.snapshot?.media?.players?.firstOrNull {
        it.player.roomId == state.selectedRoom?.id
    }
    val queue = player?.let { state.snapshot?.media?.queues?.get(it.player.id) }
    LazyColumn(
        contentPadding = PaddingValues(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            Text("Music", style = MaterialTheme.typography.headlineLarge)
            Text(
                "One queue, every room—powered by Music Assistant.",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        item {
            MediaRoomSelector(state.rooms, state.selectedRoom?.id, model::selectRoom)
        }
        player?.let { current ->
            item {
                ExpandedNowPlaying(
                    state = current,
                    queue = queue,
                    rooms = state.rooms,
                    artwork = model::artwork,
                    busy = state.actionInFlight,
                    command = model::media,
                    transfer = model::transferMedia,
                )
            }
        } ?: item {
            MediaEmptyState("No player in this room", "Choose another room or register a player in Pilot Core.")
        }
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(
                    value = state.searchQuery,
                    onValueChange = model::setSearchQuery,
                    label = { Text("Search TIDAL and your library") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                    keyboardActions = KeyboardActions(onSearch = { model.search() }),
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(10.dp))
                Button(onClick = model::search, enabled = !state.searching) {
                    if (state.searching) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    else Text("Search")
                }
            }
        }
        if (state.searchResults.isEmpty() && state.searchQuery.isNotBlank() && !state.searching) {
            item { MediaEmptyState("No matches", "Try an artist, album, track, or playlist.") }
        }
        items(state.searchResults, key = { it.id }) { result ->
            SearchResultCard(result, model::artwork) { model.play(result) }
        }
    }
}

@Composable
fun PilotMiniPlayer(
    state: PilotPlayerState,
    artwork: suspend (String) -> ByteArray?,
    busy: Boolean,
    command: (MediaCommand) -> Unit,
) {
    Surface(color = MaterialTheme.colorScheme.surfaceVariant, tonalElevation = 8.dp) {
        Column {
            val progress = mediaProgress(state.effective)
            if (progress != null) {
                Box(Modifier.fillMaxWidth().height(2.dp).background(MaterialTheme.colorScheme.outline)) {
                    Box(
                        Modifier.fillMaxWidth(progress).height(2.dp).background(PilotMint),
                    )
                }
            }
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 9.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Artwork(state.effective.media?.imageUrl, artwork, Modifier.size(42.dp))
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        state.effective.media?.title ?: "Now playing",
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        state.effective.media?.artist ?: state.player.name,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                TextButton(
                    enabled = !busy,
                    onClick = {
                        command(
                            MediaCommand(
                                action = if (state.effective.playbackState == "playing") "pause" else "play",
                                playerId = state.player.id,
                            ),
                        )
                    },
                ) { Text(if (state.effective.playbackState == "playing") "Pause" else "Play") }
                TextButton(
                    enabled = !busy,
                    onClick = { command(MediaCommand("stop", state.player.id)) },
                ) { Text("Stop") }
            }
        }
    }
}

@Composable
private fun ExpandedNowPlaying(
    state: PilotPlayerState,
    queue: MediaQueue?,
    rooms: List<PilotRoom>,
    artwork: suspend (String) -> ByteArray?,
    busy: Boolean,
    command: (MediaCommand) -> Unit,
    transfer: (String) -> Unit,
) {
    val wide = LocalConfiguration.current.screenWidthDp >= 820
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(28.dp),
    ) {
        val content: @Composable () -> Unit = {
            Artwork(
                state.effective.media?.imageUrl,
                artwork,
                Modifier.widthIn(max = 250.dp).aspectRatio(1f),
            )
            NowPlayingControls(state, rooms, busy, command, transfer)
        }
        if (wide) {
            Row(
                Modifier.fillMaxWidth().padding(22.dp),
                horizontalArrangement = Arrangement.spacedBy(24.dp),
                verticalAlignment = Alignment.Top,
            ) { content() }
        } else {
            Column(
                Modifier.fillMaxWidth().padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(18.dp),
            ) { content() }
        }
        if (!queue?.items.isNullOrEmpty()) {
            QueuePreview(requireNotNull(queue), artwork)
        } else {
            Text(
                "Queue details will appear when this player's provider exposes them.",
                modifier = Modifier.padding(horizontal = 22.dp, vertical = 14.dp),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun NowPlayingControls(
    state: PilotPlayerState,
    rooms: List<PilotRoom>,
    busy: Boolean,
    command: (MediaCommand) -> Unit,
    transfer: (String) -> Unit,
) {
    val effective = state.effective
    val media = effective.media
    Column(Modifier.widthIn(min = 280.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(11.dp)) {
        Text(state.player.name.uppercase(), color = PilotCyan, style = MaterialTheme.typography.labelLarge)
        Text(
            media?.title ?: if (effective.available) "Ready to play" else "Player unavailable",
            style = MaterialTheme.typography.headlineMedium,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            listOfNotNull(media?.artist, media?.album).joinToString(" · ").ifBlank { effective.source ?: "Music Assistant" },
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        val duration = effective.durationSeconds ?: media?.durationSeconds
        val position = effective.positionSeconds
        if (duration != null && duration > 0) {
            var preview by remember(state.player.id, position) {
                mutableFloatStateOf((position ?: 0.0).toFloat().coerceIn(0f, duration.toFloat()))
            }
            Slider(
                value = preview,
                onValueChange = { preview = it },
                onValueChangeFinished = {
                    if (effective.supports("seek")) {
                        command(MediaCommand("seek", state.player.id, positionSeconds = preview.toDouble()))
                    }
                },
                valueRange = 0f..duration.toFloat(),
                enabled = !busy && effective.supports("seek"),
                modifier = Modifier.semantics {
                    contentDescription = "Playback position ${formatDuration(preview.toDouble())} of ${formatDuration(duration)}"
                },
            )
            Row(Modifier.fillMaxWidth()) {
                Text(formatDuration(preview.toDouble()), color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.weight(1f))
                Text(formatDuration(duration), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(9.dp), verticalAlignment = Alignment.CenterVertically) {
            if (effective.supports("previous")) {
                OutlinedButton(
                    enabled = !busy,
                    onClick = { command(MediaCommand("previous", state.player.id)) },
                ) { Text("Previous") }
            }
            FilledTonalButton(
                enabled = !busy && effective.available,
                onClick = {
                    command(
                        MediaCommand(
                            if (effective.playbackState == "playing") "pause" else "play",
                            state.player.id,
                        ),
                    )
                },
            ) { Text(if (effective.playbackState == "playing") "Pause" else "Play") }
            if (effective.supports("next")) {
                OutlinedButton(
                    enabled = !busy,
                    onClick = { command(MediaCommand("next", state.player.id)) },
                ) { Text("Next") }
            }
            OutlinedButton(
                enabled = !busy,
                onClick = { command(MediaCommand("stop", state.player.id)) },
            ) { Text("Stop") }
        }
        effective.volumePercent?.let { level ->
            var preview by remember(state.player.id, level) { mutableFloatStateOf(level.toFloat()) }
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (effective.supports("mute")) {
                    TextButton(
                        enabled = !busy,
                        onClick = {
                            command(MediaCommand("mute", state.player.id, muted = effective.muted != true))
                        },
                    ) { Text(if (effective.muted == true) "Unmute" else "Mute") }
                } else {
                    Text("Volume", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Slider(
                    value = preview,
                    onValueChange = { preview = it },
                    onValueChangeFinished = {
                        command(MediaCommand("set_volume", state.player.id, volume = preview.roundToInt()))
                    },
                    valueRange = 0f..100f,
                    enabled = !busy,
                    modifier = Modifier.weight(1f).semantics {
                        contentDescription = "${state.player.name} volume ${preview.roundToInt()} percent"
                    },
                )
                Text("${preview.roundToInt()}%", fontWeight = FontWeight.SemiBold)
            }
        }
        val targets = rooms.filter { it.id != state.player.roomId && it.defaultMusicPlayerId != null }
        if (targets.isNotEmpty()) {
            Text("MOVE TO", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.labelLarge)
            Row(
                Modifier.horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                targets.forEach { room ->
                    AssistChip(
                        onClick = { transfer(room.id) },
                        enabled = !busy,
                        label = { Text(room.name) },
                    )
                    if (effective.supports("group")) {
                        AssistChip(
                            onClick = {
                                command(
                                    MediaCommand(
                                        action = "group",
                                        playerId = state.player.id,
                                        targetRoomId = room.id,
                                        targetPlayerId = room.defaultMusicPlayerId,
                                    ),
                                )
                            },
                            enabled = !busy,
                            label = { Text("Add ${room.name}") },
                        )
                    }
                }
            }
        }
        if (effective.groupMembers.isNotEmpty()) {
            Text(
                "Playing together: ${effective.groupMembers.joinToString()}",
                color = PilotMint,
            )
        }
    }
}

@Composable
private fun QueuePreview(queue: MediaQueue, artwork: suspend (String) -> ByteArray?) {
    Column(Modifier.fillMaxWidth().padding(22.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Up next", style = MaterialTheme.typography.titleLarge)
        queue.items.take(8).forEachIndexed { index, item ->
            Row(
                Modifier
                    .fillMaxWidth()
                    .background(
                        if (item.active || queue.index == index) PilotMint.copy(alpha = .10f)
                        else MaterialTheme.colorScheme.onSurface.copy(alpha = .025f),
                        RoundedCornerShape(14.dp),
                    )
                    .padding(10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Artwork(item.imageUrl, artwork, Modifier.size(42.dp))
                Spacer(Modifier.width(11.dp))
                Column(Modifier.weight(1f)) {
                    Text(item.title, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(item.artist ?: item.album.orEmpty(), color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                }
                item.durationSeconds?.let { Text(formatDuration(it)) }
            }
        }
    }
}

@Composable
private fun SearchResultCard(
    result: MusicSearchResult,
    artwork: suspend (String) -> ByteArray?,
    play: () -> Unit,
) {
    Card(
        Modifier.fillMaxWidth().clickable(onClick = play),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(18.dp),
    ) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Artwork(result.imageUrl, artwork, Modifier.size(54.dp))
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(result.title, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(
                    result.subtitle.ifBlank { result.mediaType.orEmpty() },
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            FilledTonalButton(onClick = play) { Text("Play") }
        }
    }
}

@Composable
private fun MediaRoomSelector(rooms: List<PilotRoom>, selected: String?, select: (String) -> Unit) {
    Row(
        Modifier.horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        rooms.forEach { room ->
            AssistChip(
                onClick = { select(room.id) },
                label = { Text(if (selected == room.id) "✓ ${room.name}" else room.name) },
            )
        }
    }
}

@Composable
private fun Artwork(
    url: String?,
    load: suspend (String) -> ByteArray?,
    modifier: Modifier,
) {
    val bitmap by produceState<androidx.compose.ui.graphics.ImageBitmap?>(null, url) {
        value = url?.let { selected ->
            load(selected)?.let { bytes ->
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
            }
        }
    }
    if (bitmap == null) {
        Box(
            modifier.clip(RoundedCornerShape(16.dp)).background(PilotMint.copy(alpha = .12f)),
            contentAlignment = Alignment.Center,
        ) { Text("♫", color = PilotMint, style = MaterialTheme.typography.headlineMedium) }
    } else {
        Image(
            bitmap = requireNotNull(bitmap),
            contentDescription = "Album artwork",
            modifier = modifier.clip(RoundedCornerShape(16.dp)),
            contentScale = ContentScale.Crop,
        )
    }
}

@Composable
private fun MediaEmptyState(title: String, detail: String) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
        Column(Modifier.fillMaxWidth().padding(20.dp)) {
            Text(title, style = MaterialTheme.typography.titleLarge)
            Text(detail, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

private fun EffectiveMediaState.supports(action: String): Boolean = when {
    action in capabilities -> true
    capabilities.isNotEmpty() -> false
    action in setOf("play", "pause", "stop", "set_volume", "transfer") -> true
    else -> false
}

private fun mediaProgress(state: EffectiveMediaState): Float? {
    val duration = state.durationSeconds ?: state.media?.durationSeconds ?: return null
    if (duration <= 0) return null
    return ((state.positionSeconds ?: 0.0) / duration).toFloat().coerceIn(0f, 1f)
}

private fun formatDuration(seconds: Double): String {
    val total = seconds.coerceAtLeast(0.0).roundToInt()
    return "%d:%02d".format(total / 60, total % 60)
}
