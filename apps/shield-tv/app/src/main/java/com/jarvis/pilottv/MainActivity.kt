package com.jarvis.pilottv

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Button
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.Text
import androidx.tv.material3.darkColorScheme

private val Background = Color(0xFF071218)
private val Panel = Color(0xFF10232A)
private val PanelRaised = Color(0xFF173038)
private val Mint = Color(0xFF62E6C4)
private val Amber = Color(0xFFFFC65A)
private val Muted = Color(0xFF9AB0B6)
private val Danger = Color(0xFFFF8B8B)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val viewModel: PilotTvViewModel = viewModel()
            PilotTvTheme {
                PilotTvApp(viewModel)
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
fun PilotTvApp(viewModel: PilotTvViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Background),
    ) {
        when (val current = state) {
            PilotTvState.Disconnected -> ConnectionScreen(onConnect = viewModel::connect)
            is PilotTvState.Loading -> current.previous?.let {
                Dashboard(
                    snapshot = it,
                    status = "Refreshing",
                    error = null,
                    onRefresh = viewModel::refresh,
                    onDisconnect = viewModel::disconnect,
                )
            } ?: LoadingScreen()
            is PilotTvState.Connected -> Dashboard(
                snapshot = current.snapshot,
                status = "Live",
                error = null,
                onRefresh = viewModel::refresh,
                onDisconnect = viewModel::disconnect,
            )
            is PilotTvState.Error -> current.previous?.let {
                Dashboard(
                    snapshot = it,
                    status = "Offline",
                    error = current.message,
                    onRefresh = viewModel::refresh,
                    onDisconnect = viewModel::disconnect,
                )
            } ?: ConnectionScreen(
                initialError = current.message,
                onConnect = viewModel::connect,
            )
        }
    }
}

@Composable
private fun ConnectionScreen(
    initialError: String? = null,
    onConnect: (String, String) -> Unit,
) {
    var address by remember { mutableStateOf("http://10.0.1.64:8770") }
    var token by remember { mutableStateOf("") }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 96.dp, vertical = 72.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text("PILOT TV", color = Mint, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(12.dp))
        Text(
            "Your home intelligence,\non the largest screen.",
            fontSize = 44.sp,
            lineHeight = 50.sp,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(16.dp))
        Text(
            "This first Shield release is read only. The administrator token stays in memory and is never saved.",
            color = Muted,
            fontSize = 18.sp,
        )
        Spacer(Modifier.height(32.dp))
        LabeledField(
            label = "Pilot Core address",
            value = address,
            onValueChange = { address = it },
        )
        Spacer(Modifier.height(18.dp))
        LabeledField(
            label = "Administrator token",
            value = token,
            onValueChange = { token = it },
            password = true,
        )
        if (initialError != null) {
            Spacer(Modifier.height(14.dp))
            Text(initialError, color = Danger, fontSize = 16.sp)
        }
        Spacer(Modifier.height(28.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Button(onClick = { onConnect(address, token.trim()) }) {
                Text("Open Pilot Core")
            }
            Text(
                "Local network only · no cloud relay",
                modifier = Modifier.align(Alignment.CenterVertically),
                color = Muted,
                fontSize = 15.sp,
            )
        }
    }
}

@Composable
private fun LabeledField(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    password: Boolean = false,
) {
    Column(modifier = Modifier.width(620.dp)) {
        Text(label, color = Muted, fontSize = 14.sp)
        Spacer(Modifier.height(7.dp))
        BasicTextField(
            value = value,
            onValueChange = onValueChange,
            modifier = Modifier
                .fillMaxWidth()
                .background(PanelRaised, RoundedCornerShape(10.dp))
                .border(1.dp, Color(0xFF31515B), RoundedCornerShape(10.dp))
                .padding(horizontal = 18.dp, vertical = 15.dp),
            textStyle = TextStyle(color = Color.White, fontSize = 18.sp),
            singleLine = true,
            keyboardOptions = KeyboardOptions(
                keyboardType = if (password) KeyboardType.Password else KeyboardType.Uri,
            ),
            visualTransformation = if (password) {
                PasswordVisualTransformation()
            } else {
                androidx.compose.ui.text.input.VisualTransformation.None
            },
        )
    }
}

@Composable
private fun LoadingScreen() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text("Connecting to Pilot Core…", color = Mint, fontSize = 24.sp)
    }
}

@Composable
private fun Dashboard(
    snapshot: OperationsSnapshot,
    status: String,
    error: String?,
    onRefresh: () -> Unit,
    onDisconnect: () -> Unit,
) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(horizontal = 64.dp, vertical = 42.dp),
        verticalArrangement = Arrangement.spacedBy(24.dp),
    ) {
        item {
            Header(snapshot, status, onRefresh, onDisconnect)
        }
        error?.let { message ->
            item {
                PanelBox(borderColor = Danger) {
                    Text(message, color = Danger, fontSize = 17.sp)
                }
            }
        }
        item {
            SummaryRow(snapshot)
        }
        item {
            SectionTitle("ROOM FABRIC", "Live rooms")
        }
        items(snapshot.rooms, key = RoomState::id) { room ->
            RoomPanel(room)
        }
        item {
            SectionTitle("SERVICE BOUNDARY", "Integrations")
        }
        item {
            IntegrationPanel(snapshot.integrations)
        }
        item {
            Footer(snapshot)
        }
    }
}

@Composable
private fun Header(
    snapshot: OperationsSnapshot,
    status: String,
    onRefresh: () -> Unit,
    onDisconnect: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column {
            Text("PILOT CORE / JARVIS HOME AI", color = Mint, fontSize = 16.sp)
            Text(
                "One calm view of every room.",
                fontSize = 36.sp,
                fontWeight = FontWeight.SemiBold,
            )
        }
        Row(
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            StatusPill(
                label = status,
                color = if (status == "Live") Mint else Amber,
            )
            Button(onClick = onRefresh) { Text("Refresh") }
            Button(onClick = onDisconnect) { Text("Lock") }
        }
    }
    Spacer(Modifier.height(6.dp))
    Text(
        "Release ${snapshot.deployment.release} · Core ${snapshot.deployment.version}",
        color = Muted,
        fontSize = 15.sp,
    )
}

@Composable
private fun SummaryRow(snapshot: OperationsSnapshot) {
    val summary = snapshot.summary
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Metric(
            modifier = Modifier.weight(1f),
            label = "Rooms",
            value = summary.roomCount.toString(),
            detail = "${summary.armedRoomCount} armed · ${summary.unarmedRoomCount} locked",
        )
        Metric(
            modifier = Modifier.weight(1f),
            label = "Endpoints",
            value = "${summary.connectedDeviceCount}/${summary.deviceCount}",
            detail = "Connected room agents",
        )
        Metric(
            modifier = Modifier.weight(1f),
            label = "Integrations",
            value = "${summary.healthyIntegrationCount}/${summary.configuredIntegrationCount}",
            detail = "Healthy providers",
        )
        Metric(
            modifier = Modifier.weight(1f),
            label = "Audio safety",
            value = if (snapshot.safety.audibleActionsGated) "Locked" else "Armed",
            detail = if (snapshot.safety.audibleActionsGated) {
                "Audible actions fail closed"
            } else {
                "Every room supervised"
            },
            accent = if (snapshot.safety.audibleActionsGated) Amber else Mint,
        )
    }
}

@Composable
private fun Metric(
    modifier: Modifier,
    label: String,
    value: String,
    detail: String,
    accent: Color = Color.White,
) {
    PanelBox(modifier = modifier) {
        Text(label.uppercase(), color = Muted, fontSize = 13.sp)
        Spacer(Modifier.height(8.dp))
        Text(value, color = accent, fontSize = 30.sp, fontWeight = FontWeight.Bold)
        Text(detail, color = Muted, fontSize = 14.sp)
    }
}

@Composable
private fun RoomPanel(room: RoomState) {
    PanelBox {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Text(room.name, fontSize = 26.sp, fontWeight = FontWeight.SemiBold)
                Text(
                    "${room.devices.count(EndpointState::connected)}/${room.devices.size} endpoints · " +
                        "${room.players.size} players",
                    color = Muted,
                    fontSize = 14.sp,
                )
            }
            StatusPill(
                label = if (room.armed) "Audio armed" else "Audio locked",
                color = if (room.armed) Mint else Amber,
            )
        }
        Spacer(Modifier.height(22.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(24.dp),
        ) {
            Column(modifier = Modifier.weight(1.15f)) {
                ColumnLabel("ENDPOINTS & PLAYERS")
                if (room.devices.isEmpty()) {
                    DetailText("No enrolled endpoint.")
                }
                room.devices.forEach { endpoint ->
                    ItemLine(
                        title = endpoint.name,
                        detail = endpoint.id,
                        state = if (endpoint.connected) "Connected" else "Offline",
                        stateColor = if (endpoint.connected) Mint else Danger,
                    )
                }
                room.players
                    .filter { it.kind == "music" || it.kind == "video" }
                    .forEach { player ->
                        val detail = buildString {
                            append(player.protocol.replaceFirstChar(Char::uppercase))
                            player.volumePercent?.let { append(" · $it%") }
                            append(if (player.controlEnabled) " · control ready" else " · read only")
                        }
                        ItemLine(
                            title = player.name,
                            detail = player.media?.title?.let { "$detail · $it" } ?: detail,
                            state = player.playbackState?.replaceFirstChar(Char::uppercase)
                                ?: player.status.replaceFirstChar(Char::uppercase),
                            stateColor = if (player.status == "ok" && player.available != false) {
                                Mint
                            } else {
                                Danger
                            },
                        )
                    }
            }
            Column(modifier = Modifier.weight(1f)) {
                ColumnLabel("SOURCE STATE")
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    room.sources.forEach { source ->
                        StatusPill(
                            label = source.id.replaceFirstChar(Char::uppercase),
                            color = if (source.active) Mint else Muted,
                            muted = !source.active,
                        )
                    }
                }
                Spacer(Modifier.height(14.dp))
                DetailText(
                    room.foregroundSource?.let {
                        "${it.replaceFirstChar(Char::uppercase)} has focus."
                    } ?: "No active foreground source.",
                )
                Spacer(Modifier.height(18.dp))
                ColumnLabel("NOW PLAYING")
                val nowPlaying = room.players.firstOrNull {
                    it.media?.title != null || it.playbackState == "playing"
                }
                DetailText(
                    nowPlaying?.media?.let { media ->
                        listOfNotNull(media.title, media.artist).joinToString(" — ")
                    } ?: "Nothing playing",
                )
            }
        }
    }
}

@Composable
private fun IntegrationPanel(integrations: List<IntegrationState>) {
    PanelBox {
        integrations.forEachIndexed { index, integration ->
            if (index > 0) Spacer(Modifier.height(14.dp))
            ItemLine(
                title = integration.id
                    .replace("_", " ")
                    .split(" ")
                    .joinToString(" ") { it.replaceFirstChar(Char::uppercase) },
                detail = integration.latencyMs?.let { "$it ms response" }
                    ?: if (integration.configured) "Configured" else "Not configured",
                state = integration.status.replace("_", " ")
                    .replaceFirstChar(Char::uppercase),
                stateColor = if (integration.status == "ok" || integration.status == "configured") {
                    Mint
                } else {
                    Amber
                },
            )
        }
    }
}

@Composable
private fun SectionTitle(eyebrow: String, title: String) {
    Column {
        Text(eyebrow, color = Mint, fontSize = 13.sp, fontWeight = FontWeight.Bold)
        Text(title, fontSize = 28.sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun ItemLine(
    title: String,
    detail: String,
    state: String,
    stateColor: Color,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 7.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(title, fontSize = 17.sp, fontWeight = FontWeight.Medium)
            Text(detail, color = Muted, fontSize = 13.sp)
        }
        Spacer(Modifier.width(12.dp))
        StatusPill(state, stateColor)
    }
}

@Composable
private fun StatusPill(
    label: String,
    color: Color,
    muted: Boolean = false,
) {
    Row(
        modifier = Modifier
            .background(
                color.copy(alpha = if (muted) 0.08f else 0.14f),
                RoundedCornerShape(50),
            )
            .border(1.dp, color.copy(alpha = 0.42f), RoundedCornerShape(50))
            .padding(horizontal = 11.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier
                .width(7.dp)
                .height(7.dp)
                .background(color, RoundedCornerShape(50)),
        )
        Spacer(Modifier.width(7.dp))
        Text(label, color = color, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun ColumnLabel(value: String) {
    Text(value, color = Muted, fontSize = 12.sp, fontWeight = FontWeight.Bold)
    Spacer(Modifier.height(7.dp))
}

@Composable
private fun DetailText(value: String) {
    Text(value, color = Muted, fontSize = 14.sp)
}

@Composable
private fun PanelBox(
    modifier: Modifier = Modifier,
    borderColor: Color = Color(0xFF23434C),
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier = modifier
            .background(Panel, RoundedCornerShape(16.dp))
            .border(1.dp, borderColor, RoundedCornerShape(16.dp))
            .padding(22.dp),
        content = content,
    )
}

@Composable
private fun Footer(snapshot: OperationsSnapshot) {
    val uptimeHours = snapshot.deployment.uptimeSeconds / 3600
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 16.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text("Pilot Core keeps control local.", color = Muted, fontSize = 14.sp)
        Text(
            "${snapshot.generatedAt} · ${uptimeHours}h uptime · read-only client",
            color = Muted,
            fontSize = 14.sp,
        )
    }
}
