package com.jarvis.pilotwall

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.lerp
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import java.time.Duration
import java.time.Instant
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

private enum class PilotDestination(val label: String, val glyph: String) {
    Home("Home", "⌂"),
    Rooms("Rooms", "▦"),
    Music("Music", "♫"),
    Assistant("Pilot", "✦"),
    Settings("Settings", "⚙"),
}

@Composable
fun PilotWallApp(state: PilotUiState, model: PilotViewModel, night: Boolean) {
    if (!state.configured) {
        PilotPairingScreen(state, model)
        return
    }
    PilotIdleGuard(state) {
        BurnInGuard(enabled = night) {
            PilotShell(state, model)
        }
    }
    state.pendingHomeAction?.let { action ->
        AlertDialog(
            onDismissRequest = model::cancelHomeAction,
            title = { Text("Confirm home action") },
            text = {
                Text(
                    action.description
                        ?: "Pilot will perform this high-risk action once. It expires automatically.",
                )
            },
            confirmButton = {
                Button(onClick = model::confirmHomeAction) { Text("Confirm") }
            },
            dismissButton = {
                TextButton(onClick = model::cancelHomeAction) { Text("Cancel") }
            },
        )
    }
    PilotAssistantOverlay(state, model)
}

@Composable
private fun BurnInGuard(enabled: Boolean, content: @Composable () -> Unit) {
    val step by produceState(0, enabled) {
        while (true) {
            delay(60_000)
            value = (value + 1) % 4
        }
    }
    val offsets = listOf(0 to 0, 2 to 1, 0 to 2, -2 to 1)
    val offset = if (enabled) offsets[step] else 0 to 0
    Box(
        Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .offset { IntOffset(offset.first, offset.second) },
    ) {
        content()
    }
}

@Composable
private fun PilotShell(state: PilotUiState, model: PilotViewModel) {
    var destination by remember { mutableStateOf(PilotDestination.Home) }
    val wide = LocalConfiguration.current.screenWidthDp >= 700
    val nowPlaying = state.snapshot?.media?.players
        ?.firstOrNull { it.effective.playbackState == "playing" }

    Row(
        Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.safeDrawing),
    ) {
        if (wide) {
            NavigationRail(
                modifier = Modifier.fillMaxHeight(),
                containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.72f),
            ) {
                Spacer(Modifier.height(16.dp))
                Text("P", style = MaterialTheme.typography.headlineMedium, color = PilotMint)
                Spacer(Modifier.height(24.dp))
                PilotDestination.entries.forEach {
                    NavigationRailItem(
                        selected = destination == it,
                        onClick = { destination = it },
                        icon = { Text(it.glyph, style = MaterialTheme.typography.titleLarge) },
                        label = { Text(it.label) },
                    )
                }
            }
        }
        Scaffold(
            modifier = Modifier.weight(1f),
            containerColor = Color.Transparent,
            bottomBar = {
                Column {
                    if (nowPlaying != null) {
                        PilotMiniPlayer(
                            nowPlaying,
                            model::artwork,
                            state.actionInFlight,
                            model::media,
                        )
                    }
                    if (!wide) {
                        NavigationBar {
                            PilotDestination.entries.forEach {
                                NavigationBarItem(
                                    selected = destination == it,
                                    onClick = { destination = it },
                                    icon = { Text(it.glyph) },
                                    label = { Text(it.label) },
                                )
                            }
                        }
                    }
                }
            },
        ) { padding ->
            Column(Modifier.padding(padding).fillMaxSize()) {
                ConnectionBanner(state, model::refresh)
                when (destination) {
                    PilotDestination.Home -> HomeScreen(state, model)
                    PilotDestination.Rooms -> RoomsScreen(state, model)
                    PilotDestination.Music -> PilotMusicExperience(state, model)
                    PilotDestination.Assistant -> PilotAssistantPanel(state, model)
                    PilotDestination.Settings -> SettingsScreen(state, model)
                }
            }
        }
    }
}

@Composable
private fun ConnectionBanner(state: PilotUiState, refresh: () -> Unit) {
    AnimatedVisibility(
        visible = state.connection != ConnectionState.Online || state.error != null,
    ) {
        val color = when (state.connection) {
            ConnectionState.Loading -> PilotCyan
            ConnectionState.Stale -> PilotAmber
            else -> PilotRed
        }
        Row(
            Modifier
                .fillMaxWidth()
                .background(color.copy(alpha = 0.14f))
                .padding(horizontal = 20.dp, vertical = 9.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                when (state.connection) {
                    ConnectionState.Loading -> "Connecting to Pilot Core…"
                    ConnectionState.Stale -> "Showing the last known home state"
                    ConnectionState.Offline -> "Pilot Core is offline"
                    else -> state.error ?: ""
                },
                modifier = Modifier.weight(1f),
                color = color,
            )
            TextButton(onClick = refresh) { Text("Retry") }
        }
    }
}

@Composable
private fun HomeScreen(state: PilotUiState, model: PilotViewModel) {
    val now by produceState(LocalDateTime.now()) {
        while (true) {
            value = LocalDateTime.now()
            delay(30_000)
        }
    }
    val energy = state.snapshot?.surface?.energy
    val playing = state.snapshot?.media?.players?.filter {
        it.effective.playbackState == "playing"
    }.orEmpty()
    LazyColumn(
        contentPadding = PaddingValues(24.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp),
    ) {
        item {
            Row(verticalAlignment = Alignment.Bottom) {
                Column(Modifier.weight(1f)) {
                    Text(
                        now.format(DateTimeFormatter.ofPattern("EEEE, d MMMM")),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        now.format(DateTimeFormatter.ofPattern("h:mm")),
                        style = MaterialTheme.typography.displayLarge,
                    )
                    Text(
                        "Your home, at a glance",
                        style = MaterialTheme.typography.headlineMedium,
                    )
                }
                StatusPill(state.connection, state.snapshot?.receivedAt)
            }
        }
        item {
            if (energy == null) {
                StateCard(
                    title = "Energy is waiting for Pilot Core",
                    detail = "The tablet will recover automatically when the energy surface is available.",
                    action = "Refresh",
                    onAction = model::refresh,
                )
            } else {
                EnergyFlowCard(energy)
            }
        }
        item {
            Text("Rooms", style = MaterialTheme.typography.headlineMedium)
            Spacer(Modifier.height(10.dp))
            LazyRow(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                items(state.rooms, key = { it.id }) { room ->
                    val roomState = state.snapshot?.media?.players
                        ?.firstOrNull { it.player.roomId == room.id }
                    RoomSummaryCard(
                        room = room,
                        state = roomState,
                        selected = state.selectedRoom?.id == room.id,
                        onClick = { model.selectRoom(room.id) },
                    )
                }
            }
        }
        item {
            CuratedHomeControls(state, model)
        }
        item {
            Text("Active now", style = MaterialTheme.typography.headlineMedium)
            Spacer(Modifier.height(10.dp))
            if (playing.isEmpty()) {
                StateCard("The house is quiet", "Nothing is currently playing.")
            } else {
                playing.forEach { state ->
                    NowPlayingCard(state, model::media)
                    Spacer(Modifier.height(10.dp))
                }
            }
        }
    }
}

@Composable
private fun HomeControlsCard(state: PilotUiState, model: PilotViewModel) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(26.dp),
    ) {
        Column(
            Modifier.fillMaxWidth().padding(22.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(
                        state.home?.roomName ?: state.selectedRoom?.name ?: "Room controls",
                        style = MaterialTheme.typography.headlineMedium,
                    )
                    Text(
                        "Secure controls through Pilot Core",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (state.homeLoading) CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp)
            }
            state.homeError?.let {
                Text(it, color = PilotAmber)
                OutlinedButton(onClick = { model.refreshHome() }) { Text("Retry") }
            }
            val grouped = state.home?.entities.orEmpty().groupBy { it.domain }
            if (!state.homeLoading && state.homeError == null && grouped.isEmpty()) {
                Text(
                    "No mapped controls. Assign Home Assistant devices to this room.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            grouped.toSortedMap().forEach { (domain, entities) ->
                Text(
                    domain.replace('_', ' ').uppercase(),
                    color = PilotCyan,
                    style = MaterialTheme.typography.labelLarge,
                )
                entities.sortedBy { it.name }.forEach { entity ->
                    HomeEntityControl(
                        entity = entity,
                        busy = state.activeHomeEntityId == entity.entityId,
                        action = model::homeAction,
                    )
                }
            }
        }
    }
}

@Composable
private fun HomeEntityControl(
    entity: HomeEntity,
    busy: Boolean,
    action: (HomeEntity, String, Double?) -> Unit,
) {
    Column(
        Modifier
            .fillMaxWidth()
            .background(
                MaterialTheme.colorScheme.onSurface.copy(alpha = .045f),
                RoundedCornerShape(16.dp),
            )
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(entity.name, fontWeight = FontWeight.SemiBold)
                Text(
                    if (entity.stale) "Stale" else entity.state.replace('_', ' '),
                    color = if (entity.stale || entity.unavailable) {
                        PilotAmber
                    } else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (busy) {
                CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp)
            } else if ("turn_on" in entity.actions) {
                Switch(
                    checked = entity.isOn,
                    onCheckedChange = {
                        action(entity, if (it) "turn_on" else "turn_off", null)
                    },
                    enabled = !entity.stale && !entity.unavailable,
                )
            } else {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    if ("activate" in entity.actions) {
                        AssistChip(
                            onClick = { action(entity, "activate", null) },
                            label = { Text("Activate") },
                        )
                    }
                    if ("open" in entity.actions) {
                        AssistChip(
                            onClick = { action(entity, "open", null) },
                            label = { Text("Open") },
                        )
                        AssistChip(
                            onClick = { action(entity, "close", null) },
                            label = { Text("Close") },
                        )
                    }
                    if ("lock" in entity.actions) {
                        val next = if (entity.state == "locked") "unlock" else "lock"
                        AssistChip(
                            onClick = { action(entity, next, null) },
                            label = { Text(next.replaceFirstChar(Char::uppercase)) },
                        )
                    }
                    if ("arm_home" in entity.actions) {
                        val next = if (entity.state == "disarmed") "arm_home" else "disarm"
                        AssistChip(
                            onClick = { action(entity, next, null) },
                            label = { Text(next.replace('_', ' ').replaceFirstChar(Char::uppercase)) },
                        )
                    }
                }
            }
        }
        entity.brightnessPercent?.takeIf { "set_brightness" in entity.actions }?.let { brightness ->
            var preview by remember(entity.entityId, brightness) { mutableStateOf(brightness) }
            Slider(
                value = preview,
                onValueChange = { preview = it },
                onValueChangeFinished = { action(entity, "set_brightness", preview.toDouble()) },
                valueRange = 0f..100f,
                steps = 19,
                enabled = !busy && !entity.stale && !entity.unavailable,
            )
        }
    }
}

@Composable
private fun EnergyFlowCard(energy: EnergySnapshot) {
    val onSurface = MaterialTheme.colorScheme.onSurface
    val transition = rememberInfiniteTransition(label = "energy-flow")
    val phase by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(1_700, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "flow-position",
    )
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(26.dp),
    ) {
        Column(Modifier.padding(22.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Live energy", style = MaterialTheme.typography.headlineMedium)
                    Text(
                        if (energy.status == "ok") "All sources reporting" else "Partial live data",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Text(
                    energy.batterySoc.display(),
                    style = MaterialTheme.typography.headlineMedium,
                    color = PilotMint,
                )
            }
            Canvas(
                Modifier
                    .fillMaxWidth()
                    .height(250.dp)
                    .semantics {
                        contentDescription = buildString {
                            append("Energy flow. Solar ${energy.solar.display()}, ")
                            append("home ${energy.homeLoad.display()}, ")
                            append("grid ${energy.grid.display()} ${energy.grid.direction.orEmpty()}, ")
                            append("battery ${energy.battery.display()} ${energy.battery.direction.orEmpty()}.")
                        }
                    },
            ) {
                val centre = Offset(size.width * .5f, size.height * .5f)
                val solar = Offset(size.width * .5f, size.height * .12f)
                val battery = Offset(size.width * .14f, size.height * .53f)
                val grid = Offset(size.width * .86f, size.height * .53f)
                val home = Offset(size.width * .5f, size.height * .88f)
                flowLine(solar, centre, phase, PilotAmber, energy.solar.value != null)
                flowLine(
                    if (energy.battery.direction == "charging") centre else battery,
                    if (energy.battery.direction == "charging") battery else centre,
                    phase,
                    PilotMint,
                    energy.battery.direction != "idle",
                )
                flowLine(
                    if (energy.grid.direction == "exporting") centre else grid,
                    if (energy.grid.direction == "exporting") grid else centre,
                    phase,
                    PilotCyan,
                    energy.grid.direction != "idle",
                )
                flowLine(centre, home, phase, PilotMint, energy.homeLoad.value != null)
                energyNode(solar, PilotAmber)
                energyNode(battery, PilotMint)
                energyNode(grid, PilotCyan)
                energyNode(centre, onSurface)
                energyNode(home, PilotMint)
            }
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                EnergyLegend("Solar", energy.solar.display(), PilotAmber)
                EnergyLegend("Battery", energy.battery.display(), PilotMint)
                EnergyLegend("Grid", energy.grid.display(), PilotCyan)
                EnergyLegend("Home", energy.homeLoad.display(), MaterialTheme.colorScheme.onSurface)
            }
        }
    }
}

private fun DrawScope.flowLine(
    start: Offset,
    end: Offset,
    phase: Float,
    color: Color,
    active: Boolean,
) {
    drawLine(
        color = color.copy(alpha = if (active) .34f else .12f),
        start = start,
        end = end,
        strokeWidth = 5f,
        cap = StrokeCap.Round,
    )
    if (active) {
        repeat(3) { index ->
            val p = (phase + index / 3f) % 1f
            drawCircle(color, 7f, lerp(start, end, p))
        }
    }
}

private fun DrawScope.energyNode(position: Offset, color: Color) {
    drawCircle(color.copy(alpha = .14f), 25f, position)
    drawCircle(color, 11f, position)
}

@Composable
private fun EnergyLegend(label: String, value: String, color: Color) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value, color = color, fontWeight = FontWeight.Bold)
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun RoomsScreen(state: PilotUiState, model: PilotViewModel) {
    LazyColumn(
        contentPadding = PaddingValues(24.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Text("Rooms", style = MaterialTheme.typography.headlineLarge)
            Text(
                "Choose the context for music and Pilot conversations.",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (state.rooms.isEmpty()) {
            item {
                StateCard(
                    "No rooms available",
                    "Pilot Core has not returned a room registry yet.",
                    "Retry",
                    model::refresh,
                )
            }
        } else {
            items(state.rooms, key = { it.id }) { room ->
                val playerStates = state.snapshot?.media?.players
                    ?.filter { it.player.roomId == room.id }.orEmpty()
                Card(
                    Modifier
                        .fillMaxWidth()
                        .clickable { model.selectRoom(room.id) },
                    colors = CardDefaults.cardColors(
                        containerColor = if (state.selectedRoom?.id == room.id) {
                            PilotMint.copy(alpha = .12f)
                        } else MaterialTheme.colorScheme.surface
                    ),
                    shape = RoundedCornerShape(22.dp),
                ) {
                    Column(Modifier.padding(20.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(room.name, style = MaterialTheme.typography.headlineMedium)
                            Spacer(Modifier.weight(1f))
                            if (state.selectedRoom?.id == room.id) {
                                Text("CURRENT", color = PilotMint, fontWeight = FontWeight.Bold)
                            }
                        }
                        Spacer(Modifier.height(12.dp))
                        if (playerStates.isEmpty()) {
                            Text("No playback surfaces", color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        playerStates.forEach { playerState ->
                            Row(
                                Modifier.fillMaxWidth().padding(vertical = 6.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Box(
                                    Modifier
                                        .size(9.dp)
                                        .background(
                                            if (playerState.effective.available) PilotMint else PilotRed,
                                            CircleShape,
                                        ),
                                )
                                Spacer(Modifier.width(10.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(playerState.player.name, fontWeight = FontWeight.SemiBold)
                                    Text(
                                        playerState.effective.playbackState ?: playerState.status,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                                playerState.effective.volumePercent?.let { Text("$it%") }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun MusicScreen(state: PilotUiState, model: PilotViewModel) {
    LazyColumn(
        contentPadding = PaddingValues(24.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Text("Music", style = MaterialTheme.typography.headlineLarge)
            Text(
                "Music Assistant remains the queue and library authority.",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        item {
            RoomSelector(state.rooms, state.selectedRoom?.id, model::selectRoom)
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
                    if (state.searching) {
                        CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    } else {
                        Text("Search")
                    }
                }
            }
        }
        val current = state.snapshot?.media?.players?.firstOrNull {
            it.player.roomId == state.selectedRoom?.id &&
                it.effective.media?.title != null
        }
        current?.let {
            item { NowPlayingCard(it, model::media) }
        }
        if (state.searchResults.isEmpty() && state.searchQuery.isNotBlank() && !state.searching) {
            item { StateCard("No results yet", "Try an artist, album, track, or playlist.") }
        } else {
            items(state.searchResults, key = { it.id }) { result ->
                Card(
                    Modifier.fillMaxWidth().clickable { model.play(result) },
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                ) {
                    Row(
                        Modifier.padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            Modifier
                                .size(48.dp)
                                .background(PilotMint.copy(alpha = .12f), RoundedCornerShape(14.dp)),
                            contentAlignment = Alignment.Center,
                        ) { Text("♫", color = PilotMint) }
                        Spacer(Modifier.width(14.dp))
                        Column(Modifier.weight(1f)) {
                            Text(result.title, fontWeight = FontWeight.SemiBold)
                            Text(
                                result.subtitle,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                        FilledTonalButton(onClick = { model.play(result) }) { Text("Play") }
                    }
                }
            }
        }
    }
}

@Composable
private fun AssistantScreen(state: PilotUiState, model: PilotViewModel) {
    var input by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize().padding(24.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Pilot", style = MaterialTheme.typography.headlineLarge)
                Text(
                    "Context: ${state.selectedRoom?.name ?: "No room"}",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            RoomSelector(state.rooms, state.selectedRoom?.id, model::selectRoom)
        }
        Spacer(Modifier.height(14.dp))
        LazyColumn(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            items(state.chat, key = { it.id }) { message ->
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = if (message.role == ChatRole.User) {
                        Arrangement.End
                    } else {
                        Arrangement.Start
                    },
                ) {
                    Surface(
                        color = if (message.role == ChatRole.User) {
                            PilotMint.copy(alpha = .16f)
                        } else {
                            MaterialTheme.colorScheme.surface
                        },
                        shape = RoundedCornerShape(20.dp),
                        modifier = Modifier.fillMaxWidth(.72f),
                    ) {
                        Text(message.text, Modifier.padding(16.dp))
                    }
                }
            }
            if (state.assistantBusy) {
                item {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                        Spacer(Modifier.width(10.dp))
                        Text("Pilot is thinking…", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
        Spacer(Modifier.height(12.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = input,
                onValueChange = { input = it },
                label = { Text("Ask about your home") },
                modifier = Modifier.weight(1f),
                maxLines = 3,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = {
                    model.ask(input)
                    input = ""
                }),
            )
            Spacer(Modifier.width(10.dp))
            Button(
                onClick = {
                    model.ask(input)
                    input = ""
                },
                enabled = input.isNotBlank() && !state.assistantBusy,
            ) { Text("Send") }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SettingsScreen(state: PilotUiState, model: PilotViewModel) {
    var refresh by remember(state.config.refreshSeconds) {
        mutableStateOf(state.config.refreshSeconds.toString())
    }
    var keepAwake by remember(state.config.keepScreenOn) {
        mutableStateOf(state.config.keepScreenOn)
    }
    var nightMode by remember(state.config.nightMode) {
        mutableStateOf(state.config.nightMode)
    }
    var kioskMode by remember(state.config.kioskMode) {
        mutableStateOf(state.config.kioskMode)
    }
    var ambientAfter by remember(state.config.ambientAfterMinutes) {
        mutableStateOf(state.config.ambientAfterMinutes.toString())
    }
    LazyColumn(
        contentPadding = PaddingValues(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            Text("Tablet settings", style = MaterialTheme.typography.headlineLarge)
            Text(
                "Device credentials stay encrypted in Android Keystore.",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        item {
            SettingsCard("Pilot Core") {
                SettingLine("Server", state.config.coreUrl)
                SettingLine("Device identity", state.config.deviceId)
                SettingLine("Connection", state.connection.name)
                OutlinedButton(onClick = model::refresh) { Text("Test and refresh") }
            }
        }
        item {
            SettingsCard("Display") {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Keep display awake", fontWeight = FontWeight.SemiBold)
                        Text(
                            "Recommended for a powered wall tablet",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Switch(checked = keepAwake, onCheckedChange = { keepAwake = it })
                }
                Text("Appearance", fontWeight = FontWeight.SemiBold)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    NightMode.entries.forEach { option ->
                        AssistChip(
                            onClick = { nightMode = option },
                            label = {
                                Text(if (option == nightMode) "✓ ${option.name}" else option.name)
                            },
                        )
                    }
                }
                Text(
                    "Night mode lowers contrast and moves the interface slightly each minute to reduce static OLED/LCD wear.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Kiosk display", fontWeight = FontWeight.SemiBold)
                        Text(
                            "Hide Android system bars; swipe from an edge for temporary access.",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Switch(checked = kioskMode, onCheckedChange = { kioskMode = it })
                }
                OutlinedTextField(
                    value = ambientAfter,
                    onValueChange = { ambientAfter = it.filter(Char::isDigit).take(2) },
                    label = { Text("Ambient mode after (minutes)") },
                    supportingText = { Text("1–60 minutes; any touch wakes the dashboard.") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                )
            }
        }
        item {
            SettingsCard("Refresh") {
                OutlinedTextField(
                    value = refresh,
                    onValueChange = { refresh = it.filter(Char::isDigit).take(3) },
                    label = { Text("Refresh interval (seconds)") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    supportingText = { Text("5–300 seconds; 15 is recommended.") },
                )
                Button(
                    onClick = {
                        model.updateSettings(
                            refresh.toIntOrNull() ?: 15,
                            keepAwake,
                            nightMode,
                            kioskMode,
                            ambientAfter.toIntOrNull() ?: 5,
                        )
                    },
                ) { Text("Save settings") }
            }
        }
        item {
            SettingsCard("Security") {
                Text(
                    "This client never stores Home Assistant or Music Assistant credentials. All access is authorized by Pilot Core.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                OutlinedButton(onClick = model::disconnect) { Text("Remove device token") }
            }
        }
    }
}

@Composable
private fun SettingsCard(title: String, content: @Composable ColumnScope.() -> Unit) {
    Card(
        Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(22.dp),
    ) {
        Column(
            Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(title, style = MaterialTheme.typography.headlineMedium)
            content()
        }
    }
}

@Composable
private fun SettingLine(label: String, value: String) {
    Row(Modifier.fillMaxWidth()) {
        Text(label, modifier = Modifier.weight(1f), color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun RoomSelector(
    rooms: List<PilotRoom>,
    selectedRoomId: String?,
    onSelect: (String) -> Unit,
) {
    Row(
        Modifier.horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        rooms.forEach { room ->
            AssistChip(
                onClick = { onSelect(room.id) },
                label = { Text(if (room.id == selectedRoomId) "✓ ${room.name}" else room.name) },
            )
        }
    }
}

@Composable
private fun RoomSummaryCard(
    room: PilotRoom,
    state: PilotPlayerState?,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Card(
        Modifier.width(220.dp).clickable(onClick = onClick),
        colors = CardDefaults.cardColors(
            containerColor = if (selected) PilotMint.copy(alpha = .12f)
            else MaterialTheme.colorScheme.surface,
        ),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(Modifier.padding(18.dp)) {
            Text(room.name, style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(18.dp))
            Text(
                state?.effective?.media?.title
                    ?: state?.effective?.playbackState?.replaceFirstChar { it.uppercase() }
                    ?: "Ready",
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                color = if (state?.effective?.available != false) PilotMint else PilotRed,
            )
            Text(
                "${room.players.size} ${if (room.players.size == 1) "player" else "players"}",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun NowPlayingCard(state: PilotPlayerState, command: (MediaCommand) -> Unit) {
    Card(
        Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(22.dp),
    ) {
        Row(Modifier.padding(18.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(72.dp).background(
                    PilotMint.copy(alpha = .12f),
                    RoundedCornerShape(18.dp),
                ),
                contentAlignment = Alignment.Center,
            ) {
                Text("♫", style = MaterialTheme.typography.headlineLarge, color = PilotMint)
            }
            Spacer(Modifier.width(16.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    state.effective.media?.title ?: state.player.name,
                    style = MaterialTheme.typography.titleLarge,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    state.effective.media?.artist ?: state.player.name,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                state.effective.volumePercent?.let { Text("Volume $it%") }
            }
            FilledTonalButton(
                onClick = {
                    command(
                        MediaCommand(
                            action = if (state.effective.playbackState == "playing") "pause" else "play",
                            playerId = state.player.id,
                        ),
                    )
                },
            ) {
                Text(if (state.effective.playbackState == "playing") "Pause" else "Play")
            }
        }
    }
}

@Composable
private fun MiniPlayer(
    state: PilotPlayerState,
    busy: Boolean,
    command: (MediaCommand) -> Unit,
) {
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant,
        tonalElevation = 8.dp,
    ) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier.size(40.dp).background(PilotMint.copy(alpha = .14f), RoundedCornerShape(12.dp)),
                contentAlignment = Alignment.Center,
            ) { Text("♫", color = PilotMint) }
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
        }
    }
}

@Composable
private fun StatusPill(state: ConnectionState, receivedAt: Instant?) {
    val color = when (state) {
        ConnectionState.Online -> PilotMint
        ConnectionState.Loading -> PilotCyan
        ConnectionState.Stale -> PilotAmber
        else -> PilotRed
    }
    Surface(color = color.copy(alpha = .12f), shape = CircleShape) {
        Row(Modifier.padding(horizontal = 14.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).background(color, CircleShape))
            Spacer(Modifier.width(8.dp))
            Text(
                receivedAt?.let {
                    val seconds = Duration.between(it, Instant.now()).seconds
                    if (seconds < 30) "Live" else "Updated ${seconds}s ago"
                } ?: state.name,
                color = color,
                fontWeight = FontWeight.SemiBold,
            )
        }
    }
}

@Composable
private fun StateCard(
    title: String,
    detail: String,
    action: String? = null,
    onAction: (() -> Unit)? = null,
) {
    Card(
        Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(20.dp),
    ) {
        Row(Modifier.padding(20.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.titleLarge)
                Text(detail, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (action != null && onAction != null) {
                TextButton(onClick = onAction) { Text(action) }
            }
        }
    }
}

@Composable
private fun OnboardingScreen(
    initialConfig: PilotConfig,
    busy: Boolean,
    error: String?,
    connect: (String, String, String) -> Unit,
) {
    var url by remember { mutableStateOf(initialConfig.coreUrl) }
    var deviceId by remember { mutableStateOf(initialConfig.deviceId) }
    var token by remember { mutableStateOf("") }
    Box(
        Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .windowInsetsPadding(WindowInsets.safeDrawing),
        contentAlignment = Alignment.Center,
    ) {
        Card(
            Modifier.fillMaxWidth(.72f),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
            shape = RoundedCornerShape(30.dp),
        ) {
            Row(Modifier.padding(30.dp), horizontalArrangement = Arrangement.spacedBy(30.dp)) {
                Column(Modifier.weight(.8f)) {
                    Text("PILOT", color = PilotMint, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(12.dp))
                    Text("Bring your home to life.", style = MaterialTheme.typography.headlineLarge)
                    Spacer(Modifier.height(10.dp))
                    Text(
                        "Connect this wall tablet to Pilot Core. Home Assistant and Music Assistant credentials never leave the server.",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Column(
                    Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    OutlinedTextField(
                        value = url,
                        onValueChange = { url = it },
                        label = { Text("Pilot Core URL") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = deviceId,
                        onValueChange = { deviceId = it },
                        label = { Text("Registered device ID") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = token,
                        onValueChange = { token = it },
                        label = { Text("Device token") },
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation(),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                    Button(
                        onClick = { connect(url, deviceId, token) },
                        enabled = !busy && url.isNotBlank() && deviceId.isNotBlank() && token.isNotBlank(),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        if (busy) {
                            CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                            Spacer(Modifier.width(8.dp))
                        }
                        Text(if (busy) "Connecting…" else "Connect securely")
                    }
                }
            }
        }
    }
}

@Preview(widthDp = 1024, heightDp = 600)
@Composable
private fun DashboardPreview() {
    PilotTheme(night = false) {
        Box(Modifier.background(PilotBackground).padding(24.dp)) {
            EnergyFlowCard(PilotFixtures.energy)
        }
    }
}
