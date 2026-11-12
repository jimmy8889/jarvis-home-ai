package com.jameshazell.pilot.ui.assistant

import android.Manifest
import android.content.pm.PackageManager
import android.database.ContentObserver
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.waitForUpOrCancellation
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LifecycleStartEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.jameshazell.pilot.core.humanLabel
import com.jameshazell.pilot.data.pilot.AssistantCard
import com.jameshazell.pilot.data.pilot.AssistantSource
import com.jameshazell.pilot.ui.adaptive.ListDetailLayout
import com.jameshazell.pilot.ui.adaptive.LocalPilotWindow
import com.jameshazell.pilot.ui.appViewModel
import com.jameshazell.pilot.ui.assistant.jarvis.AssistantMode
import com.jameshazell.pilot.ui.assistant.jarvis.JarvisScreen
import com.jameshazell.pilot.ui.components.Chip
import com.jameshazell.pilot.ui.components.CardNote
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.ScreenHeader
import com.jameshazell.pilot.ui.control.ChatIcons
import com.jameshazell.pilot.ui.control.Composer
import com.jameshazell.pilot.ui.control.MessageBubble
import com.jameshazell.pilot.ui.control.RoundIconButton
import com.jameshazell.pilot.ui.control.keyboardPadding
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens
import com.jameshazell.pilot.ui.theme.PilotIcons

/**
 * The Pilot tab. JARVIS (the private assistant on the laptop) is the default; the house
 * assistant from Pilot Core, which can control the house, is one tap away.
 */
@Composable
fun AssistantScreen() {
    var mode by rememberSaveable { mutableStateOf(AssistantMode.Jarvis) }
    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = PilotDimens.ScreenPadding),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            AssistantMode.entries.forEach { option ->
                Chip(option.label, selected = option == mode, onClick = { mode = option })
            }
        }
        // Only the chosen assistant is composed, so the other one's microphone and polling are off.
        Box(Modifier.weight(1f).fillMaxWidth()) {
            when (mode) {
                AssistantMode.Jarvis -> JarvisScreen()
                AssistantMode.House -> HouseAssistantScreen()
            }
        }
    }
}

/** The house assistant: talk or type to Pilot Core. */
@Composable
private fun HouseAssistantScreen() {
    val context = LocalContext.current.applicationContext
    val model = appViewModel {
        AssistantViewModel(it.pilot, AndroidVoiceRecorder(context), AndroidReplyPlayer(context), it.dispatchers.io)
    }
    val ui by model.ui.collectAsStateWithLifecycle()
    val level by model.level.collectAsStateWithLifecycle()
    val snapshot by model.snapshot.collectAsStateWithLifecycle()
    val roomId by model.selectedRoomId.collectAsStateWithLifecycle()

    // The microphone is asked for the first time the orb is used, not when the screen opens.
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) model.startRecording() else model.microphoneDenied()
    }
    val startListening = {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            model.startRecording()
        } else {
            permission.launch(Manifest.permission.RECORD_AUDIO)
            false
        }
    }

    // Leaving the screen or backgrounding the app closes the microphone.
    LifecycleStartEffect(model) {
        model.onScreenStarted()
        onStopOrDispose { model.onScreenStopped() }
    }

    val rooms = snapshot.valueOrNull()?.media?.rooms.orEmpty()
    AssistantContent(
        ui = ui,
        level = level,
        live = snapshot.isLive,
        roomName = (rooms.firstOrNull { it.id == roomId } ?: rooms.firstOrNull())?.name,
        animate = rememberSystemAnimationsEnabled(),
        actions = model,
        startListening = startListening,
    )
}

/** The whole destination, stateless: previews and the screen both render through here. */
@Composable
internal fun AssistantContent(
    ui: AssistantUiState,
    level: Float,
    live: Boolean,
    roomName: String?,
    animate: Boolean,
    actions: AssistantActions,
    startListening: () -> Boolean,
) {
    val twoPane = LocalPilotWindow.current.isTwoPane
    Column(Modifier.fillMaxSize()) {
        ScreenHeader(
            title = "House assistant",
            status = when {
                !live -> "Waiting for Pilot Core"
                roomName != null -> "Answering for $roomName"
                else -> "Ready"
            },
            statusColor = if (live) PilotColors.Teal else PilotColors.TextDim,
        ) {
            if (ui.messages.isNotEmpty()) {
                TextButton(onClick = actions::newConversation) { Text("New chat", color = PilotColors.Violet) }
            }
        }
        if (twoPane) {
            // Open Fold: the orb has the left half to itself, the conversation is on the right.
            ListDetailLayout(
                hasDetail = true,
                onBack = {},
                listFraction = 0.4f,
                list = {
                    Column(
                        Modifier.fillMaxSize().padding(PilotDimens.ScreenPadding),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap, Alignment.CenterVertically),
                    ) {
                        VoiceOrb(ui.phase, level, animate, 176.dp, actions, startListening)
                        OrbCaptionText(ui.phase, centered = true)
                        StopControl(ui.phase, actions)
                    }
                },
                detail = {
                    Column(Modifier.fillMaxSize().keyboardPadding()) {
                        Thread(ui, Modifier.weight(1f))
                        ErrorStrip(ui.error, actions::dismissError)
                        TextComposer(ui, actions)
                    }
                },
            )
        } else {
            Column(Modifier.fillMaxSize().keyboardPadding()) {
                Thread(ui, Modifier.weight(1f))
                ErrorStrip(ui.error, actions::dismissError)
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = PilotDimens.ScreenPadding, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    VoiceOrb(ui.phase, level, animate, 76.dp, actions, startListening)
                    Spacer(Modifier.width(PilotDimens.Gap))
                    Box(Modifier.weight(1f)) { OrbCaptionText(ui.phase, centered = false) }
                    StopControl(ui.phase, actions)
                }
                TextComposer(ui, actions)
            }
        }
    }
}

@Composable
private fun TextComposer(ui: AssistantUiState, actions: AssistantActions) {
    Composer(
        value = ui.draft,
        onValueChange = actions::setDraft,
        onSend = actions::sendText,
        placeholder = "Ask about your home",
        canSend = ui.draft.isNotBlank() && ui.phase != AssistantPhase.Listening && ui.phase != AssistantPhase.Thinking,
        modifier = Modifier.padding(start = PilotDimens.ScreenPadding, end = PilotDimens.ScreenPadding, bottom = 8.dp),
    )
}

@Composable
private fun Thread(ui: AssistantUiState, modifier: Modifier = Modifier) {
    val listState = rememberLazyListState()
    val thinking = ui.phase == AssistantPhase.Thinking
    val count = ui.messages.size + if (thinking) 1 else 0
    LaunchedEffect(count) { if (count > 0) listState.animateScrollToItem(count - 1) }
    LazyColumn(
        modifier.fillMaxWidth(),
        state = listState,
        contentPadding = PaddingValues(PilotDimens.ScreenPadding),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        if (ui.messages.isEmpty() && !thinking) {
            item(key = "empty") {
                PilotCard {
                    Text("Ask Pilot", style = MaterialTheme.typography.titleMedium)
                    CardNote("Ask about the house or tell it what to do: “Is the garage door shut?”, “Turn the lounge lights down”, “How much solar did we make today?”")
                }
            }
        }
        items(ui.messages, key = { it.id }) { message ->
            if (message.fromUser) {
                MessageBubble(message.text, mine = true, label = "You said".takeIf { message.spoken })
            } else {
                MessageBubble(
                    message.text,
                    mine = false,
                    footer = if (message.cards.isEmpty() && message.sources.isEmpty()) null else {
                        {
                            message.cards.forEach { ResultCard(it) }
                            Sources(message.sources)
                        }
                    },
                )
            }
        }
        if (thinking) {
            item(key = "thinking") {
                Row(
                    Modifier.padding(horizontal = 4.dp).semantics { liveRegion = LiveRegionMode.Polite },
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    CircularProgressIndicator(color = PilotColors.Violet, strokeWidth = 2.dp, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(10.dp))
                    CardNote("Pilot is thinking…")
                }
            }
        }
    }
}

/** A structured result attached to a reply: a device state, a reading, a list entry. */
@Composable
private fun ResultCard(card: AssistantCard) {
    Surface(
        shape = RoundedCornerShape(14.dp),
        color = PilotColors.PanelRaised,
        contentColor = PilotColors.Text,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            if (card.kind.isNotBlank()) {
                Text(humanLabel(card.kind).uppercase(), style = MaterialTheme.typography.labelSmall, color = PilotColors.Teal)
            }
            if (card.title.isNotBlank()) Text(card.title, style = MaterialTheme.typography.titleMedium)
            card.detail?.takeIf(String::isNotBlank)?.let {
                Text(it, style = MaterialTheme.typography.bodyMedium, color = PilotColors.TextDim)
            }
        }
    }
}

@Composable
private fun Sources(sources: List<AssistantSource>) {
    if (sources.isEmpty()) return
    val uriHandler = LocalUriHandler.current
    Column {
        Text("SOURCES", style = MaterialTheme.typography.labelSmall, color = PilotColors.TextFaint)
        sources.forEach { source ->
            val link = source.url?.takeIf { it.startsWith("https://") || it.startsWith("http://") }
            Text(
                source.label.ifBlank { link ?: "Source" },
                style = MaterialTheme.typography.bodyMedium,
                color = if (link != null) PilotColors.Blue else PilotColors.TextDim,
                textDecoration = if (link != null) TextDecoration.Underline else null,
                modifier = if (link == null) Modifier else Modifier
                    .clickable(role = Role.Button, onClickLabel = "Open source") { runCatching { uriHandler.openUri(link) } }
                    .padding(vertical = 6.dp),
            )
        }
    }
}

/** Assistant problems, shown only here. Stays until dismissed or the next attempt. */
@Composable
private fun ErrorStrip(error: String?, onDismiss: () -> Unit) {
    if (error == null) return
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = PilotDimens.ScreenPadding, vertical = 4.dp)
            .semantics { liveRegion = LiveRegionMode.Polite },
        shape = RoundedCornerShape(14.dp),
        color = PilotColors.Red.copy(alpha = 0.14f).compositeOver(PilotColors.Panel),
        contentColor = PilotColors.Text,
    ) {
        Row(Modifier.padding(start = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(PilotIcons.Warning, contentDescription = null, tint = PilotColors.Red, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(10.dp))
            Text(error, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f).padding(vertical = 10.dp))
            RoundIconButton(PilotIcons.Close, "Dismiss", onDismiss)
        }
    }
}

@Composable
private fun OrbCaptionText(phase: AssistantPhase, centered: Boolean) {
    val caption = orbCaption(phase)
    val align = if (centered) TextAlign.Center else TextAlign.Start
    Column(
        Modifier.semantics { liveRegion = LiveRegionMode.Polite },
        horizontalAlignment = if (centered) Alignment.CenterHorizontally else Alignment.Start,
    ) {
        Text(caption.title, style = MaterialTheme.typography.titleMedium, textAlign = align)
        Text(caption.hint, style = MaterialTheme.typography.bodyMedium, color = PilotColors.TextDim, textAlign = align)
    }
}

/** An explicit way out of every busy state, next to the orb. */
@Composable
private fun StopControl(phase: AssistantPhase, actions: AssistantActions) {
    val label = when (phase) {
        AssistantPhase.Idle -> null
        AssistantPhase.Listening -> "Discard"
        AssistantPhase.Thinking -> "Cancel"
        AssistantPhase.Speaking -> "Stop"
    }
    // Keeps its height while idle so the layout doesn't jump when a state begins.
    Box(Modifier.height(PilotDimens.TouchTarget), contentAlignment = Alignment.Center) {
        if (label != null) {
            TextButton(onClick = actions::stop) {
                Icon(ChatIcons.Stop, contentDescription = null, tint = PilotColors.Red, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text(label, color = PilotColors.Red)
            }
        }
    }
}

/**
 * The voice orb. Hold to talk and release to send, or tap to start and tap again to send; while
 * Pilot is thinking or speaking a touch stops it. It only moves while something is happening,
 * and not at all when the system's animations are switched off ([animate] false).
 */
@Composable
private fun VoiceOrb(
    phase: AssistantPhase,
    level: Float,
    animate: Boolean,
    size: Dp,
    actions: AssistantActions,
    startListening: () -> Boolean,
) {
    val currentPhase by rememberUpdatedState(phase)
    val currentStart by rememberUpdatedState(startListening)
    val currentActions by rememberUpdatedState(actions)

    fun perform(action: OrbAction): Boolean = when (action) {
        OrbAction.StartRecording -> currentStart()
        OrbAction.FinishRecording -> { currentActions.finishRecording(); false }
        OrbAction.Stop -> { currentActions.stop(); false }
        OrbAction.None -> false
    }

    val pulse = if (animate && phase != AssistantPhase.Idle) {
        val transition = rememberInfiniteTransition(label = "pilot-orb")
        val value by transition.animateFloat(
            initialValue = 0.86f,
            targetValue = 1f,
            animationSpec = infiniteRepeatable(
                tween(if (phase == AssistantPhase.Listening) 650 else 1_100, easing = FastOutSlowInEasing),
                RepeatMode.Reverse,
            ),
            label = "pulse",
        )
        value
    } else 0.92f
    val loudness = if (animate && phase == AssistantPhase.Listening) level.coerceIn(0f, 1f) else 0f
    val accent = when (phase) {
        AssistantPhase.Idle, AssistantPhase.Thinking -> PilotColors.Violet
        AssistantPhase.Listening -> PilotColors.Teal
        AssistantPhase.Speaking -> PilotColors.Blue
    }

    Box(
        Modifier
            .size(size)
            .semantics(mergeDescendants = true) {
                role = Role.Button
                contentDescription = "Talk to Pilot"
                stateDescription = orbCaption(phase).title
                onClick(
                    label = when (phase) {
                        AssistantPhase.Idle -> "start listening"
                        AssistantPhase.Listening -> "send"
                        else -> "stop"
                    },
                ) {
                    perform(OrbGesture.onClick(currentPhase))
                    true
                }
            }
            .pointerInput(Unit) {
                awaitEachGesture {
                    awaitFirstDown().consume()
                    val pressedAt = System.nanoTime()
                    val startedHere = perform(OrbGesture.onPress(currentPhase))
                    waitForUpOrCancellation()?.consume()
                    val heldMs = (System.nanoTime() - pressedAt) / 1_000_000
                    perform(OrbGesture.onRelease(currentPhase, startedHere, heldMs))
                }
            },
        contentAlignment = Alignment.Center,
    ) {
        Canvas(Modifier.fillMaxSize()) {
            val center = Offset(this.size.width / 2, this.size.height / 2)
            val full = this.size.minDimension / 2
            val core = full * 0.62f * pulse
            val glow = (core * (1.25f + loudness * 0.5f)).coerceAtMost(full)
            drawCircle(
                brush = Brush.radialGradient(listOf(accent.copy(alpha = 0.55f), accent.copy(alpha = 0.18f), Color.Transparent), center, glow),
                radius = glow,
                center = center,
            )
            drawCircle(accent, core, center)
        }
        Icon(
            if (phase == AssistantPhase.Idle || phase == AssistantPhase.Listening) PilotIcons.Assistant else ChatIcons.Stop,
            contentDescription = null,
            tint = PilotColors.OnAccent,
            modifier = Modifier.size(size * 0.3f),
        )
    }
}

/** False when the system "animator duration scale" is 0 (Remove animations / battery saver). */
@Composable
internal fun rememberSystemAnimationsEnabled(): Boolean {
    val resolver = LocalContext.current.applicationContext.contentResolver
    fun read(): Boolean = animationsEnabledForScale(
        runCatching { Settings.Global.getFloat(resolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) }.getOrDefault(1f),
    )
    var enabled by remember(resolver) { mutableStateOf(read()) }
    DisposableEffect(resolver) {
        val observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
            override fun onChange(selfChange: Boolean) {
                enabled = read()
            }
        }
        resolver.registerContentObserver(Settings.Global.getUriFor(Settings.Global.ANIMATOR_DURATION_SCALE), false, observer)
        onDispose { resolver.unregisterContentObserver(observer) }
    }
    return enabled
}
