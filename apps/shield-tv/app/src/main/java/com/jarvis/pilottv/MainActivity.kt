package com.jarvis.pilottv

import android.content.Context
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.tv.material3.Button
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.Text
import androidx.tv.material3.darkColorScheme

private val Background = Color(0xFF050B11)
private val Panel = Color(0xE6162530)
private val PanelRaised = Color(0xFF1C303C)
private val Line = Color(0xFF2A4654)
private val Cyan = Color(0xFF74D9FF)
private val Mint = Color(0xFF6EF0C8)
private val Violet = Color(0xFFA994FF)
private val Amber = Color(0xFFFFCB70)
private val Muted = Color(0xFFA2B4BE)
private val Danger = Color(0xFFFF8F9C)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val credentialStore = CredentialStore(this)
        setContent {
            val viewModel: PilotTvViewModel = viewModel()
            PilotTvTheme {
                PilotTvApp(viewModel, credentialStore)
            }
        }
    }
}

@Composable
private fun PilotTvTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Mint,
            onPrimary = Background,
            surface = Panel,
            onSurface = Color.White,
            background = Background,
            onBackground = Color.White,
        ),
        content = content,
    )
}

@Composable
fun PilotTvApp(viewModel: PilotTvViewModel, credentialStore: CredentialStore) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    LaunchedEffect(credentialStore) { viewModel.attachStore(credentialStore) }
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.radialGradient(
                    listOf(Color(0xFF123142), Background),
                    radius = 1_300f,
                ),
            ),
    ) {
        when (val current = state) {
            is PilotTvState.Unpaired -> PairingScreen(
                initialError = current.message,
                pairing = false,
                onPair = viewModel::pair,
            )
            PilotTvState.Pairing -> PairingScreen(pairing = true, onPair = viewModel::pair)
            is PilotTvState.Loading -> current.previous?.let { snapshot ->
                HomeScreen(
                    snapshot = snapshot,
                    status = current.message,
                    warning = null,
                    pendingAction = null,
                    notice = null,
                    onMedia = viewModel::media,
                    onRefresh = { viewModel.refresh(true) },
                    onRotateCredentials = viewModel::rotateCredentials,
                    onUnpair = viewModel::disconnect,
                )
            } ?: LoadingScreen(current.message)
            is PilotTvState.Ready -> HomeScreen(
                snapshot = current.snapshot,
                status = if (current.snapshot.stale) "Stale" else "Live",
                warning = null,
                pendingAction = current.pendingAction,
                notice = current.notice,
                onMedia = viewModel::media,
                onRefresh = { viewModel.refresh(true) },
                onRotateCredentials = viewModel::rotateCredentials,
                onUnpair = viewModel::disconnect,
            )
            is PilotTvState.Error -> current.previous?.let { snapshot ->
                HomeScreen(
                    snapshot = snapshot,
                    status = "Offline",
                    warning = current.message,
                    pendingAction = null,
                    notice = null,
                    onMedia = viewModel::media,
                    onRefresh = { viewModel.refresh(true) },
                    onRotateCredentials = viewModel::rotateCredentials,
                    onUnpair = viewModel::disconnect,
                )
            } ?: PairingScreen(
                initialError = current.message,
                pairing = false,
                onPair = viewModel::pair,
            )
        }
    }
}

@Composable
private fun PairingScreen(
    initialError: String? = null,
    pairing: Boolean,
    onPair: (String, String) -> Unit,
) {
    var address by remember { mutableStateOf("http://10.0.1.64:8770") }
    var code by remember { mutableStateOf("") }
    Row(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 92.dp, vertical = 64.dp),
        horizontalArrangement = Arrangement.spacedBy(72.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Eyebrow("PILOT TV")
            Spacer(Modifier.height(14.dp))
            Text(
                "Bring the room\nto life.",
                fontSize = 52.sp,
                lineHeight = 55.sp,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.height(18.dp))
            Text(
                "Pair this Shield as a limited media-room device. Your administrator and provider credentials never leave Pilot Core.",
                color = Muted,
                fontSize = 19.sp,
                lineHeight = 27.sp,
            )
        }
        PanelBox(modifier = Modifier.width(590.dp)) {
            Text("Pair Pilot TV", fontSize = 29.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(8.dp))
            Text(
                "Create a TV pairing grant in Pilot Core, then enter its one-time code here.",
                color = Muted,
                fontSize = 17.sp,
            )
            Spacer(Modifier.height(25.dp))
            LabeledField("Pilot Core", address, { address = it })
            Spacer(Modifier.height(17.dp))
            LabeledField(
                "One-time pairing code",
                code,
                { code = it },
                keyboardType = KeyboardType.Password,
            )
            AnimatedVisibility(initialError != null) {
                Column {
                    Spacer(Modifier.height(14.dp))
                    Text(initialError.orEmpty(), color = Danger, fontSize = 16.sp)
                }
            }
            Spacer(Modifier.height(24.dp))
            Button(
                enabled = !pairing,
                onClick = { onPair(address, code.trim()) },
            ) {
                Text(if (pairing) "Pairing securely…" else "Pair this Shield")
            }
            Spacer(Modifier.height(14.dp))
            Text("Local network only · encrypted device token · revocable", color = Muted, fontSize = 13.sp)
        }
    }
}

@Composable
private fun LabeledField(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    keyboardType: KeyboardType = KeyboardType.Uri,
) {
    Column {
        Text(label, color = Muted, fontSize = 14.sp)
        Spacer(Modifier.height(7.dp))
        BasicTextField(
            value = value,
            onValueChange = onValueChange,
            modifier = Modifier
                .fillMaxWidth()
                .background(PanelRaised, RoundedCornerShape(12.dp))
                .border(1.dp, Line, RoundedCornerShape(12.dp))
                .padding(horizontal = 18.dp, vertical = 16.dp),
            textStyle = TextStyle(color = Color.White, fontSize = 19.sp),
            singleLine = true,
            keyboardOptions = KeyboardOptions(
                keyboardType = keyboardType,
                capitalization = KeyboardCapitalization.None,
            ),
            visualTransformation = if (keyboardType == KeyboardType.Password) {
                PasswordVisualTransformation()
            } else {
                VisualTransformation.None
            },
        )
    }
}

@Composable
private fun LoadingScreen(message: String) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            PilotOrb(72.dp)
            Spacer(Modifier.height(22.dp))
            Text(message, color = Cyan, fontSize = 24.sp)
        }
    }
}

@Composable
private fun HomeScreen(
    snapshot: PilotTvSnapshot,
    status: String,
    warning: String?,
    pendingAction: String?,
    notice: String?,
    onMedia: (MediaCommand) -> Unit,
    onRefresh: () -> Unit,
    onRotateCredentials: () -> Unit,
    onUnpair: () -> Unit,
) {
    val context = LocalContext.current
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(horizontal = 64.dp, vertical = 38.dp),
        verticalArrangement = Arrangement.spacedBy(25.dp),
    ) {
        item { Header(snapshot, status) }
        warning?.let { message ->
            item { MessagePanel(message, Danger) }
        }
        (pendingAction ?: notice)?.let { message ->
            item {
                MessagePanel(
                    if (pendingAction != null) "${message.replaceFirstChar(Char::uppercase)}…" else message,
                    if (pendingAction != null) Cyan else Mint,
                )
            }
        }
        item { NowPlayingHero(snapshot.nowPlaying, onMedia) }
        if (snapshot.rooms.isNotEmpty()) {
            item {
                SectionHeading("ROOMS", "Choose where Pilot plays")
                Spacer(Modifier.height(13.dp))
                RoomOutputs(snapshot, onMedia)
            }
        }
        snapshot.energy?.let { energy ->
            item {
                SectionHeading("HOME", "Energy right now")
                Spacer(Modifier.height(13.dp))
                EnergyPanel(energy)
            }
        }
        snapshot.home?.entities?.takeIf { it.isNotEmpty() }?.let { entities ->
            item {
                SectionHeading("MEDIA ROOM", "What matters here")
                Spacer(Modifier.height(13.dp))
                HomeGlance(entities.take(6))
            }
        }
        snapshot.nowPlaying?.queue?.takeIf { it.isNotEmpty() }?.let { queue ->
            item {
                SectionHeading("UP NEXT", "Queue")
                Spacer(Modifier.height(13.dp))
                QueuePanel(queue)
            }
        }
        item {
            SectionHeading("WATCH", "Open a video app")
            Spacer(Modifier.height(13.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                Button(onClick = { launchPackage(context, "org.jellyfin.androidtv", "Jellyfin") }) {
                    Text("Open Jellyfin")
                }
                Button(onClick = { launchPackage(context, "org.xbmc.kodi", "Kodi") }) {
                    Text("Open Kodi")
                }
            }
        }
        item {
            SettingsPanel(
                snapshot = snapshot,
                onRefresh = onRefresh,
                onRotateCredentials = onRotateCredentials,
                onUnpair = onUnpair,
            )
        }
    }
}

@Composable
private fun Header(snapshot: PilotTvSnapshot, status: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            PilotOrb(42.dp)
            Spacer(Modifier.width(16.dp))
            Column {
                Eyebrow("PILOT / ${snapshot.manifest.roomName.uppercase()}")
                Text("Good evening", fontSize = 36.sp, fontWeight = FontWeight.SemiBold)
            }
        }
        StatusPill(status, if (status == "Live") Mint else Amber)
    }
}

@Composable
private fun NowPlayingHero(player: PlayerState?, onMedia: (MediaCommand) -> Unit) {
    PanelBox(
        modifier = Modifier.fillMaxWidth(),
        brush = Brush.horizontalGradient(listOf(Color(0xFF1B3142), Color(0xFF18243A), Color(0xFF251E3E))),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(32.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            AlbumPlaceholder(player, Modifier.size(238.dp))
            Column(modifier = Modifier.weight(1f)) {
                Eyebrow(player?.name?.uppercase() ?: "NOW PLAYING")
                Spacer(Modifier.height(10.dp))
                Text(
                    player?.media?.title ?: "Nothing playing",
                    fontSize = 42.sp,
                    lineHeight = 46.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.height(7.dp))
                Text(
                    player?.media?.artist ?: "Choose music from Pilot, TIDAL or your library",
                    color = Muted,
                    fontSize = 21.sp,
                )
                player?.media?.album?.let {
                    Text(it, color = Muted.copy(alpha = .8f), fontSize = 16.sp)
                }
                Spacer(Modifier.height(24.dp))
                Progress(player?.progress ?: 0f)
                Spacer(Modifier.height(9.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(formatSeconds(player?.positionSeconds), color = Muted, fontSize = 13.sp)
                    Text(formatSeconds(player?.durationSeconds), color = Muted, fontSize = 13.sp)
                }
                Spacer(Modifier.height(17.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    if (player != null && player.can("previous")) {
                        Button(onClick = { onMedia(MediaCommand("previous", player.id)) }) { Text("Previous") }
                    }
                    Button(
                        enabled = player?.controlEnabled == true,
                        onClick = {
                            player?.let {
                                onMedia(MediaCommand(if (it.playbackState == "playing") "pause" else "play", it.id))
                            }
                        },
                    ) { Text(if (player?.playbackState == "playing") "Pause" else "Play") }
                    Button(
                        enabled = player?.controlEnabled == true,
                        onClick = { player?.let { onMedia(MediaCommand("stop", it.id)) } },
                    ) { Text("Stop") }
                    if (player != null && player.can("next")) {
                        Button(onClick = { onMedia(MediaCommand("next", player.id)) }) { Text("Next") }
                    }
                    if (
                        player != null &&
                        player.can("seek") &&
                        player.positionSeconds != null
                    ) {
                        Button(
                            onClick = {
                                onMedia(
                                    MediaCommand(
                                        action = "seek",
                                        playerId = player.id,
                                        positionSeconds = (player.positionSeconds - 30).coerceAtLeast(0.0),
                                    ),
                                )
                            },
                        ) { Text("−30s") }
                        Button(
                            onClick = {
                                onMedia(
                                    MediaCommand(
                                        action = "seek",
                                        playerId = player.id,
                                        positionSeconds = (player.positionSeconds + 30)
                                            .coerceAtMost(player.durationSeconds ?: Double.MAX_VALUE),
                                    ),
                                )
                            },
                        ) { Text("+30s") }
                    }
                    if (player != null && player.can("mute") && player.muted != null) {
                        Button(
                            onClick = {
                                onMedia(
                                    MediaCommand(
                                        action = "mute",
                                        playerId = player.id,
                                        muted = !player.muted,
                                    ),
                                )
                            },
                        ) { Text(if (player.muted) "Unmute" else "Mute") }
                    }
                    player?.volumePercent?.let { volume ->
                        Button(onClick = { onMedia(MediaCommand("set_volume", player.id, (volume - 5).coerceAtLeast(0))) }) {
                            Text("Vol −")
                        }
                        Button(onClick = { onMedia(MediaCommand("set_volume", player.id, (volume + 5).coerceAtMost(100))) }) {
                            Text("Vol +")
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AlbumPlaceholder(player: PlayerState?, modifier: Modifier = Modifier) {
    val title = player?.media?.title.orEmpty()
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(24.dp))
            .background(
                Brush.linearGradient(
                    listOf(Violet.copy(alpha = .8f), Cyan.copy(alpha = .55f), Mint.copy(alpha = .65f)),
                ),
            )
            .border(1.dp, Color.White.copy(alpha = .14f), RoundedCornerShape(24.dp)),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            title.firstOrNull()?.uppercase() ?: "♪",
            color = Color.White.copy(alpha = .92f),
            fontSize = 88.sp,
            fontWeight = FontWeight.Light,
        )
    }
}

@Composable
private fun Progress(value: Float) {
    val animated by animateFloatAsState(value.coerceIn(0f, 1f), label = "playback-progress")
    Box(
        Modifier
            .fillMaxWidth()
            .height(6.dp)
            .background(Color.White.copy(alpha = .12f), RoundedCornerShape(50)),
    ) {
        Box(
            Modifier
                .fillMaxWidth(animated)
                .height(6.dp)
                .background(Mint, RoundedCornerShape(50)),
        )
    }
}

@Composable
private fun RoomOutputs(snapshot: PilotTvSnapshot, onMedia: (MediaCommand) -> Unit) {
    val current = snapshot.nowPlaying
    LazyRow(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
        items(snapshot.rooms, key = RoomState::id) { room ->
            val player = room.players.firstOrNull { it.id == room.defaultMusicPlayerId }
                ?: room.players.firstOrNull { it.kind == "music" }
            PanelBox(modifier = Modifier.width(310.dp)) {
                Text(room.name, fontSize = 23.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(5.dp))
                Text(
                    player?.let { "${it.protocol.ifBlank { "Pilot" }} · ${it.playbackState ?: "idle"}" }
                        ?: "No music player",
                    color = Muted,
                    fontSize = 14.sp,
                )
                Spacer(Modifier.height(15.dp))
                Button(
                    enabled = current != null && player != null && current.id != player.id,
                    onClick = {
                        if (current != null && player != null) {
                            onMedia(
                                MediaCommand(
                                    action = "transfer",
                                    playerId = current.id,
                                    targetRoomId = room.id,
                                    targetPlayerId = player.id,
                                ),
                            )
                        }
                    },
                ) { Text(if (current?.id == player?.id) "Playing here" else "Move music here") }
            }
        }
    }
}

@Composable
private fun EnergyPanel(energy: EnergyState) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        EnergyMetric("Solar", energy.solar.display(), "Producing", Amber, Modifier.weight(1f))
        EnergyMetric("Home", energy.homeLoad.display(), "Using", Violet, Modifier.weight(1f))
        EnergyMetric("Grid", energy.grid.display(), energy.grid.direction ?: "Flow", Cyan, Modifier.weight(1f))
        EnergyMetric("Battery", energy.batterySoc.display(), energy.battery.direction ?: "State of charge", Mint, Modifier.weight(1f))
    }
}

@Composable
private fun EnergyMetric(
    label: String,
    value: String,
    detail: String,
    accent: Color,
    modifier: Modifier,
) {
    PanelBox(modifier) {
        Eyebrow(label.uppercase(), accent)
        Spacer(Modifier.height(9.dp))
        Text(value, fontSize = 30.sp, fontWeight = FontWeight.Bold)
        Text(detail, color = Muted, fontSize = 14.sp)
    }
}

@Composable
private fun HomeGlance(entities: List<HomeEntity>) {
    LazyRow(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        items(entities, key = HomeEntity::id) { entity ->
            PanelBox(modifier = Modifier.width(245.dp)) {
                Eyebrow(entity.category.uppercase())
                Spacer(Modifier.height(7.dp))
                Text(entity.name, fontSize = 19.sp, fontWeight = FontWeight.SemiBold)
                Text(
                    if (entity.unavailable) "Unavailable" else entity.state.replace('_', ' '),
                    color = if (entity.unavailable) Danger else Muted,
                    fontSize = 15.sp,
                )
            }
        }
    }
}

@Composable
private fun QueuePanel(queue: List<QueueItem>) {
    PanelBox {
        queue.take(8).forEachIndexed { index, item ->
            if (index > 0) Spacer(Modifier.height(13.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    if (item.active) "▶" else (index + 1).toString(),
                    color = if (item.active) Mint else Muted,
                    fontSize = 16.sp,
                    modifier = Modifier.width(38.dp),
                )
                Column {
                    Text(item.title, fontSize = 17.sp, fontWeight = FontWeight.Medium)
                    item.subtitle?.let { Text(it, color = Muted, fontSize = 13.sp) }
                }
            }
        }
    }
}

@Composable
private fun SettingsPanel(
    snapshot: PilotTvSnapshot,
    onRefresh: () -> Unit,
    onRotateCredentials: () -> Unit,
    onUnpair: () -> Unit,
) {
    PanelBox {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Eyebrow("PILOT TV DEVICE")
                Text(snapshot.manifest.deviceName, fontSize = 21.sp, fontWeight = FontWeight.SemiBold)
                Text(
                    listOfNotNull(
                        snapshot.manifest.coreVersion?.let { "Core $it" },
                        snapshot.manifest.registryRevision?.let { "registry ${it.take(8)}" },
                        snapshot.schemaVersion,
                    ).joinToString(" · "),
                    color = Muted,
                    fontSize = 13.sp,
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(onClick = onRefresh) { Text("Refresh") }
                Button(onClick = onRotateCredentials) { Text("Rotate key") }
                Button(onClick = onUnpair) { Text("Unpair") }
            }
        }
    }
}

@Composable
private fun MessagePanel(message: String, color: Color) {
    PanelBox(borderColor = color) { Text(message, color = color, fontSize = 17.sp) }
}

@Composable
private fun SectionHeading(eyebrow: String, title: String) {
    Column {
        Eyebrow(eyebrow)
        Text(title, fontSize = 29.sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun Eyebrow(value: String, color: Color = Mint) {
    Text(value, color = color, fontSize = 13.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
}

@Composable
private fun StatusPill(label: String, color: Color) {
    Row(
        modifier = Modifier
            .background(color.copy(alpha = .12f), RoundedCornerShape(50))
            .border(1.dp, color.copy(alpha = .38f), RoundedCornerShape(50))
            .padding(horizontal = 13.dp, vertical = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(7.dp).background(color, RoundedCornerShape(50)))
        Spacer(Modifier.width(7.dp))
        Text(label, color = color, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun PilotOrb(size: androidx.compose.ui.unit.Dp) {
    Box(
        Modifier
            .size(size)
            .background(
                Brush.linearGradient(listOf(Cyan, Violet, Mint)),
                RoundedCornerShape(50),
            )
            .border(1.dp, Color.White.copy(alpha = .32f), RoundedCornerShape(50)),
    )
}

@Composable
private fun PanelBox(
    modifier: Modifier = Modifier,
    borderColor: Color = Line,
    brush: Brush? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier = modifier
            .then(
                if (brush != null) Modifier.background(brush, RoundedCornerShape(20.dp))
                else Modifier.background(Panel, RoundedCornerShape(20.dp)),
            )
            .border(1.dp, borderColor, RoundedCornerShape(20.dp))
            .padding(22.dp),
        content = content,
    )
}

private fun formatSeconds(value: Double?): String {
    if (value == null || !value.isFinite() || value < 0) return "—:—"
    val total = value.toInt()
    return "%d:%02d".format(total / 60, total % 60)
}

private fun launchPackage(context: Context, packageName: String, label: String) {
    val intent = context.packageManager.getLaunchIntentForPackage(packageName)
    if (intent == null) {
        Toast.makeText(context, "$label is not installed", Toast.LENGTH_SHORT).show()
    } else {
        context.startActivity(intent)
    }
}
