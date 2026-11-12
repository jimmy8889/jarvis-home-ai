package com.jameshazell.pilot.ui.assistant.jarvis

import android.Manifest
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.waitForUpOrCancellation
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.LifecycleStartEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.jameshazell.pilot.data.jarvis.JarvisConnection
import com.jameshazell.pilot.data.jarvis.JarvisMessage
import com.jameshazell.pilot.data.jarvis.JarvisPairing
import com.jameshazell.pilot.data.jarvis.JarvisPhase
import com.jameshazell.pilot.data.jarvis.JarvisTelemetryState
import com.jameshazell.pilot.data.jarvis.JarvisTurnState
import com.jameshazell.pilot.data.jarvis.JarvisVoiceMode
import com.jameshazell.pilot.ui.adaptive.LocalPilotWindow
import com.jameshazell.pilot.ui.appViewModel
import com.jameshazell.pilot.ui.assistant.rememberSystemAnimationsEnabled
import com.jameshazell.pilot.ui.control.keyboardPadding
import com.jameshazell.pilot.ui.theme.PilotDimens
import kotlinx.coroutines.delay

/** Everything the JARVIS screen draws from. */
internal data class JarvisScreenState(
    val connection: JarvisConnection = JarvisConnection.NotPaired,
    val pairing: JarvisPairing = JarvisPairing(),
    val telemetry: JarvisTelemetryState = JarvisTelemetryState(),
    val conversation: List<JarvisMessage> = emptyList(),
    val turn: JarvisTurnState = JarvisTurnState(),
    val voiceMode: JarvisVoiceMode = JarvisVoiceMode.VoiceStudio,
    val ui: JarvisUiState = JarvisUiState(),
    /** Monotonic now, for telemetry freshness. */
    val nowMs: Long = 0,
) {
    val model: String? get() = (connection as? JarvisConnection.Connected)?.health?.model
    val systemTools: Boolean
        get() = telemetry.fresh(nowMs) && telemetry.sample?.systemTools == true
    val hint: String get() = reactorHint(turn.phase, connection, ui.localNotice ?: turn.notice, ui.onDeviceRecognition)
}

/** JARVIS: the private voice assistant on the laptop. */
@Composable
fun JarvisScreen() {
    val context = LocalContext.current.applicationContext
    val model = appViewModel { JarvisViewModel(it.jarvis, context) }
    val connection by model.connection.collectAsStateWithLifecycle()
    val pairing by model.pairing.collectAsStateWithLifecycle()
    val telemetry by model.telemetry.collectAsStateWithLifecycle()
    val conversation by model.conversation.collectAsStateWithLifecycle()
    val turn by model.turn.collectAsStateWithLifecycle()
    val voiceMode by model.voiceMode.collectAsStateWithLifecycle()
    val ui by model.ui.collectAsStateWithLifecycle()
    // Re-evaluates telemetry freshness once a second without touching the network.
    val now by produceState(model.now()) {
        while (true) {
            delay(1_000)
            value = model.now()
        }
    }

    // Visible only: connection checks, telemetry, microphone and the turn stop when the tab is left.
    LifecycleStartEffect(model) {
        model.onShown()
        onStopOrDispose { model.onHidden() }
    }

    // The microphone is requested the first time JARVIS is asked to listen.
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) model.listen() else model.microphoneDenied()
    }
    val listen = {
        if (!pairing.paired || hasMicrophonePermission(context)) model.listen()
        else {
            permission.launch(Manifest.permission.RECORD_AUDIO)
            false
        }
    }

    JarvisContent(
        state = JarvisScreenState(connection, pairing, telemetry, conversation, turn, voiceMode, ui, now),
        level = { model.level.value },
        animate = rememberSystemAnimationsEnabled(),
        actions = model,
        listen = listen,
    )
    JarvisPairingSheet(pairing, connection, ui, model)
}

/** The whole JARVIS screen, stateless: previews and the screen both render through here. */
@Composable
internal fun JarvisContent(
    state: JarvisScreenState,
    level: () -> Float,
    animate: Boolean,
    actions: JarvisActions,
    listen: () -> Boolean,
) {
    val wide = LocalPilotWindow.current.isTwoPane
    val typing = WindowInsets.ime.getBottom(LocalDensity.current) > 0
    Column(
        Modifier
            .fillMaxSize()
            .background(JarvisColors.Background)
            .hudGrid()
            .keyboardPadding()
            .padding(start = PilotDimens.ScreenPadding, end = PilotDimens.ScreenPadding, top = 8.dp, bottom = 8.dp),
    ) {
        Header(state, actions, wide)
        Rule(Modifier.padding(top = 8.dp, bottom = 8.dp))
        if (wide) {
            // Open Fold: instruments, reactor, conversation.
            Row(Modifier.weight(1f).fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Column(Modifier.width(136.dp).fillMaxHeight(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    SystemsPanel(state, Modifier.weight(1f))
                    VoicePanel(state, actions, Modifier.weight(1f))
                }
                ReactorBlock(state, level, animate, actions, listen, Modifier.weight(1f).fillMaxHeight(), showModel = true)
                Column(Modifier.weight(1f).fillMaxHeight()) {
                    ConversationPanel(state, actions, Modifier.weight(1f))
                    Spacer(Modifier.height(8.dp))
                    ContinuousToggle(state.ui.continuous, actions::setContinuous)
                    TypingRow(state, actions)
                }
            }
        } else {
            // Cover screen: reactor above the conversation. The reactor makes way for the keyboard.
            HudText(telemetryStrip(state.telemetry, state.nowMs), 9, JarvisColors.Muted, mono = true)
            if (!typing) ReactorBlock(state, level, animate, actions, listen, Modifier.weight(1.08f).fillMaxWidth(), showModel = false)
            else Spacer(Modifier.height(8.dp))
            ConversationPanel(state, actions, Modifier.weight(1f))
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                ContinuousToggle(state.ui.continuous, actions::setContinuous, Modifier.weight(1f))
                // One button that steps through the three voices, as in the JARVIS app.
                HudButton(
                    state.voiceMode.label.uppercase(),
                    onClick = { actions.selectVoice(JarvisVoiceMode.byId((state.voiceMode.id + 1) % 3)) },
                    description = "Voice: ${state.voiceMode.label}. Tap to change.",
                )
            }
            TypingRow(state, actions)
        }
    }
}

// ---- Building blocks ------------------------------------------------------------------------

/** Faint 50dp grid, drawn once per size change: the HUD backdrop without its moving parts. */
private fun Modifier.hudGrid(): Modifier = drawBehind {
    val step = 50.dp.toPx()
    val line = Color(0xFF0C1D28)
    var x = 0f
    while (x < size.width) {
        drawLine(line, Offset(x, 0f), Offset(x, size.height), 1f)
        x += step
    }
    var y = 0f
    while (y < size.height) {
        drawLine(line, Offset(0f, y), Offset(size.width, y), 1f)
        y += step
    }
}

@Composable
private fun HudText(
    text: String,
    size: Int,
    color: Color,
    modifier: Modifier = Modifier,
    mono: Boolean = false,
    spacing: Float = 0.08f,
    align: TextAlign = TextAlign.Start,
    maxLines: Int = 1,
) {
    Text(
        text,
        modifier = modifier,
        color = color,
        fontSize = size.sp,
        lineHeight = (size + 4).sp,
        letterSpacing = (size * spacing).sp,
        fontFamily = if (mono) FontFamily.Monospace else FontFamily.Default,
        textAlign = align,
        maxLines = maxLines,
        overflow = TextOverflow.Ellipsis,
    )
}

@Composable
private fun Rule(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().height(1.dp).background(JarvisColors.Rule))
}

/** A text button in HUD lettering with a full-size touch target. */
@Composable
private fun HudButton(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    color: Color = JarvisColors.Muted,
    description: String? = null,
    enabled: Boolean = true,
) {
    Box(
        modifier
            .defaultMinSize(minHeight = PilotDimens.TouchTarget)
            .clip(RoundedCornerShape(6.dp))
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick)
            .then(if (description != null) Modifier.semantics { contentDescription = description } else Modifier)
            .padding(horizontal = 8.dp),
        contentAlignment = Alignment.Center,
    ) { HudText(label, 11, if (enabled) color else color.copy(alpha = 0.4f), spacing = 0.1f) }
}

/** The JARVIS frame: a dark plate, a hairline, and cyan ticks on two corners. */
@Composable
private fun HudPanel(label: String, modifier: Modifier = Modifier, trailing: (@Composable () -> Unit)? = null, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier
            .background(JarvisColors.Panel)
            .border(1.dp, JarvisColors.Line)
            .drawBehind {
                val tick = 18.dp.toPx()
                drawLine(JarvisColors.Cyan, Offset(0f, 0f), Offset(tick, 0f), 1.dp.toPx())
                drawLine(JarvisColors.Cyan, Offset(size.width, size.height), Offset(size.width, size.height - tick * 0.85f), 1.dp.toPx())
            }
            .padding(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.heightIn(min = 20.dp)) {
            HudText(label, 10, JarvisColors.Muted, Modifier.weight(1f).semantics { heading() }, mono = true)
            trailing?.invoke()
        }
        content()
    }
}

@Composable
private fun Header(state: JarvisScreenState, actions: JarvisActions, wide: Boolean) {
    val link = linkLine(state.connection)
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(
                "J . A . R . V . I . S .",
                color = JarvisColors.Cyan,
                fontSize = if (wide) 23.sp else 20.sp,
                fontWeight = FontWeight.Light,
                maxLines = 1,
                modifier = Modifier.semantics {
                    heading()
                    contentDescription = "JARVIS"
                },
            )
            HudText(
                link.text, 10, if (link.good) JarvisColors.Cyan else JarvisColors.Muted,
                Modifier
                    .semantics { liveRegion = LiveRegionMode.Polite }
                    .then(if (link.canRetry) Modifier.clickable(role = Role.Button, onClickLabel = "Retry now", onClick = actions::retryConnection) else Modifier)
                    .padding(vertical = 4.dp),
                spacing = 0.1f,
            )
        }
        HudButton("⚙", actions::openSheet, description = "JARVIS connection and pairing", color = JarvisColors.Soft)
    }
}

@Composable
private fun SystemsPanel(state: JarvisScreenState, modifier: Modifier = Modifier) {
    val fresh = state.telemetry.fresh(state.nowMs)
    val sample = state.telemetry.sample
    HudPanel("01 / SYSTEMS", modifier) {
        Spacer(Modifier.height(12.dp))
        Metric("PROCESSOR", percentLabel(sample?.cpuPercent, fresh))
        Metric("MEMORY", percentLabel(sample?.ramPercent, fresh))
        Metric("GPU LOAD", percentLabel(sample?.gpuPercent, fresh))
    }
}

@Composable
private fun Metric(name: String, value: String) {
    Column(Modifier.padding(bottom = 10.dp).semantics(mergeDescendants = true) {}) {
        HudText(name, 9, JarvisColors.Muted)
        Text(value, color = JarvisColors.Cyan, fontSize = 20.sp, fontFamily = FontFamily.Monospace)
    }
}

@Composable
private fun VoicePanel(state: JarvisScreenState, actions: JarvisActions, modifier: Modifier = Modifier) {
    HudPanel("02 / VOICE", modifier) {
        Spacer(Modifier.height(4.dp))
        JarvisVoiceMode.entries.forEach { mode ->
            val selected = mode == state.voiceMode
            val unavailable = mode == JarvisVoiceMode.PhoneVoice && !state.ui.phoneVoiceReady
            Row(
                Modifier
                    .fillMaxWidth()
                    .heightIn(min = 40.dp)
                    .clickable(role = Role.RadioButton, onClick = { actions.selectVoice(mode) })
                    .semantics { stateDescription = if (selected) "Selected" else if (unavailable) "Not installed" else "Not selected" },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                HudText(if (selected) "◉" else "○", 11, if (selected) JarvisColors.Cyan else JarvisColors.Muted)
                Spacer(Modifier.width(8.dp))
                HudText(mode.label.uppercase(), 10, if (selected) JarvisColors.Text else JarvisColors.Muted.copy(alpha = if (unavailable) 0.5f else 1f))
            }
        }
        Spacer(Modifier.weight(1f))
        HudText(
            if (state.systemTools) "SYSTEM TOOLS ON" else "TOOLS · CONNECTING", 9,
            if (state.systemTools) JarvisColors.Gold else JarvisColors.Muted,
        )
    }
}

@Composable
private fun ReactorBlock(
    state: JarvisScreenState,
    level: () -> Float,
    animate: Boolean,
    actions: JarvisActions,
    listen: () -> Boolean,
    modifier: Modifier = Modifier,
    showModel: Boolean,
) {
    val phase = state.turn.phase
    val paired = state.pairing.paired
    val currentPhase by rememberUpdatedState(phase)
    val currentPaired by rememberUpdatedState(paired)
    val currentListen by rememberUpdatedState(listen)
    val currentActions by rememberUpdatedState(actions)

    fun perform(action: ReactorAction): Boolean = when (action) {
        ReactorAction.Listen, ReactorAction.InterruptAndListen -> currentListen()
        ReactorAction.Finish -> { currentActions.finishListening(); false }
        ReactorAction.Stop -> { currentActions.stop(); false }
        ReactorAction.Pair -> { currentActions.openSheet(); false }
        ReactorAction.None -> false
    }

    Column(modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        HudText(
            if (state.connection is JarvisConnection.Unreachable && phase == JarvisPhase.Standby) "OFFLINE" else phase.label,
            12, JarvisColors.Cyan, Modifier.semantics { liveRegion = LiveRegionMode.Polite }, spacing = 0.24f,
        )
        Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
            ArcReactor(
                reactorState(phase, state.connection),
                level,
                animate,
                Modifier
                    .fillMaxHeight()
                    .aspectRatio(1f, matchHeightConstraintsFirst = true)
                    .semantics(mergeDescendants = true) {
                        role = Role.Button
                        contentDescription = "Arc reactor. Speak to JARVIS."
                        stateDescription = phase.label.lowercase()
                        onClick(label = reactorAction(phase, paired).lowercase().removePrefix("tap to ").removePrefix("tap or hold to ")) {
                            perform(ReactorGesture.onClick(currentPhase, currentPaired))
                            true
                        }
                    }
                    .pointerInput(Unit) {
                        awaitEachGesture {
                            awaitFirstDown().consume()
                            val pressedAt = System.nanoTime()
                            val startedHere = perform(ReactorGesture.onPress(currentPhase, currentPaired))
                            waitForUpOrCancellation()?.consume()
                            perform(ReactorGesture.onRelease(currentPhase, startedHere, (System.nanoTime() - pressedAt) / 1_000_000))
                        }
                    },
            )
        }
        HudText(reactorAction(phase, paired), 10, JarvisColors.Cyan, spacing = 0.14f)
        Text(
            state.hint,
            color = JarvisColors.Soft,
            fontSize = 13.sp,
            lineHeight = 17.sp,
            textAlign = TextAlign.Center,
            maxLines = 3,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(top = 4.dp, bottom = 6.dp).semantics { liveRegion = LiveRegionMode.Polite },
        )
        if (showModel) HudText("${state.model?.uppercase() ?: "LOCAL MODEL"}  /  LOCAL INTELLIGENCE", 9, JarvisColors.Muted)
    }
}

@Composable
private fun ConversationPanel(state: JarvisScreenState, actions: JarvisActions, modifier: Modifier = Modifier) {
    val turn = state.turn
    val lines = buildList {
        addAll(state.conversation)
        if (turn.pendingUser.isNotEmpty()) add(JarvisMessage(JarvisMessage.ROLE_USER, turn.pendingUser))
        if (turn.pendingReply.isNotEmpty()) add(JarvisMessage(JarvisMessage.ROLE_ASSISTANT, turn.pendingReply))
    }
    val listState = rememberLazyListState()
    LaunchedEffect(lines.size, turn.pendingReply.length) {
        if (lines.isNotEmpty()) listState.scrollToItem(lines.size - 1, Int.MAX_VALUE / 2)
    }
    HudPanel(
        "03 / CONVERSATION",
        modifier.fillMaxWidth(),
        trailing = { if (state.conversation.isNotEmpty()) HudButton("CLEAR", actions::clearConversation, description = "Clear the conversation saved on this phone") },
    ) {
        Rule(Modifier.padding(vertical = 6.dp))
        Box(Modifier.weight(1f).fillMaxWidth()) {
            when {
                lines.isNotEmpty() -> SelectionContainer {
                    LazyColumn(Modifier.fillMaxSize(), state = listState, verticalArrangement = Arrangement.spacedBy(14.dp)) {
                        itemsIndexed(lines) { _, message ->
                            Column {
                                HudText(if (message.fromUser) "YOU" else "JARVIS", 10, if (message.fromUser) JarvisColors.Muted else JarvisColors.Cyan, spacing = 0.12f)
                                Text(
                                    message.content,
                                    color = if (message.fromUser) JarvisColors.UserText else JarvisColors.Text,
                                    fontSize = 15.sp,
                                    lineHeight = 21.sp,
                                    modifier = Modifier.padding(top = 4.dp),
                                )
                            }
                        }
                    }
                }
                !state.pairing.paired || state.connection == JarvisConnection.Unauthorized -> Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        if (state.pairing.paired) "Pairing was rejected." else "JARVIS isn't paired yet.",
                        color = JarvisColors.Text, fontSize = 20.sp, fontWeight = FontWeight.Light,
                    )
                    Text(
                        "He runs on your laptop and is reached over Tailscale. Enter the laptop's address and a one-time pairing code to connect this phone.",
                        color = JarvisColors.Muted, fontSize = 13.sp, lineHeight = 18.sp,
                    )
                    HudButton("PAIR WITH LAPTOP  ↗", actions::openSheet, color = JarvisColors.Cyan)
                }
                else -> Column {
                    Text("Good to have you back.", color = JarvisColors.Text, fontSize = 21.sp, fontWeight = FontWeight.Light)
                    Text("Your laptop. Your models. Your assistant.", color = JarvisColors.Muted, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp, bottom = 6.dp))
                    JarvisText.SUGGESTIONS.forEach { prompt ->
                        HudButton("$prompt  ↗", { actions.ask(prompt) }, color = JarvisColors.Cyan, modifier = Modifier.padding(start = 0.dp))
                    }
                }
            }
        }
        HudText(latencyLine(state.model, state.voiceMode, turn.lastSeconds), 9, JarvisColors.Muted, Modifier.padding(top = 6.dp))
    }
}

@Composable
private fun ContinuousToggle(on: Boolean, onChange: (Boolean) -> Unit, modifier: Modifier = Modifier) {
    Box(modifier, contentAlignment = Alignment.CenterStart) {
        HudButton(
            if (on) "CONTINUOUS  ON" else "CONTINUOUS  OFF",
            onClick = { onChange(!on) },
            color = if (on) JarvisColors.Cyan else JarvisColors.Muted,
            description = if (on) "Continuous conversation is on. Tap to turn off." else "Continuous conversation is off. Tap to listen again after each reply.",
        )
    }
}

@Composable
private fun TypingRow(state: JarvisScreenState, actions: JarvisActions) {
    val canSend = state.ui.draft.isNotBlank() && !state.turn.inFlight && state.turn.phase != JarvisPhase.Listening
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        BasicTextField(
            value = state.ui.draft,
            onValueChange = actions::setDraft,
            singleLine = true,
            textStyle = TextStyle(color = Color.White, fontSize = 14.sp),
            cursorBrush = SolidColor(JarvisColors.Cyan),
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            keyboardActions = KeyboardActions(onSend = { if (canSend) actions.sendText() }),
            modifier = Modifier
                .weight(1f)
                .height(PilotDimens.TouchTarget)
                .background(JarvisColors.Field)
                .border(1.dp, JarvisColors.Line)
                .semantics { contentDescription = "Type a request for JARVIS" },
            decorationBox = { field ->
                Box(Modifier.padding(horizontal = 12.dp), contentAlignment = Alignment.CenterStart) {
                    if (state.ui.draft.isEmpty()) Text("Or type a request…", color = JarvisColors.Muted, fontSize = 14.sp)
                    field()
                }
            },
        )
        HudButton("SEND ↗", actions::sendText, color = JarvisColors.Cyan, enabled = canSend, description = "Send message")
    }
}

// ---- Pairing --------------------------------------------------------------------------------

@Composable
internal fun JarvisPairingSheet(pairing: JarvisPairing, connection: JarvisConnection, ui: JarvisUiState, actions: JarvisActions) {
    var confirmForget by androidx.compose.runtime.saveable.rememberSaveable { androidx.compose.runtime.mutableStateOf(false) }
    com.jameshazell.pilot.ui.components.BottomSheetOrSidePanel(
        visible = ui.sheetOpen,
        onDismiss = actions::closeSheet,
        title = "JARVIS connection",
    ) {
        val status = jarvisStatus(connection)
        com.jameshazell.pilot.ui.components.PilotCard {
            Text(status.label, style = MaterialTheme.typography.titleMedium)
            com.jameshazell.pilot.ui.components.CardNote(
                listOfNotNull(pairing.host?.let { "Paired with $it." }, status.detail).joinToString(" "),
            )
            com.jameshazell.pilot.ui.components.CardNote(
                "Speech in: " + (if (ui.onDeviceRecognition) "this phone's offline recogniser" else "the laptop's recogniser") +
                    ". Phone voice: " + (if (ui.phoneVoiceReady) "offline British voice available." else "not installed."),
            )
        }
        com.jameshazell.pilot.ui.components.CardNote(
            "JARVIS runs on your laptop and is reached only over Tailscale. Keep both devices on Tailscale and the laptop awake. " +
                "The pairing code works once; this phone then keeps an encrypted token. Conversations are saved on this phone until you clear them.",
        )
        SheetField("Laptop Tailscale address", ui.pairAddress, actions::setPairAddress, "100.x.y.z", secret = false)
        SheetField("One-time pairing code", ui.pairCode, actions::setPairCode, "From the laptop's JARVIS config", secret = true)
        if (pairing.error != null) {
            Text(pairing.error, color = com.jameshazell.pilot.ui.theme.PilotColors.Red, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        }
        com.jameshazell.pilot.ui.control.PrimaryButton(
            if (pairing.busy) "Pairing…" else if (pairing.paired) "Pair again" else "Pair with laptop",
            actions::pair,
            enabled = !pairing.busy && ui.pairAddress.isNotBlank() && ui.pairCode.isNotBlank(),
        )
        if (pairing.paired) {
            androidx.compose.material3.TextButton(onClick = actions::retryConnection) { Text("Check connection now", color = com.jameshazell.pilot.ui.theme.PilotColors.Violet) }
            androidx.compose.material3.TextButton(onClick = { confirmForget = true }) { Text("Forget this laptop on this phone", color = com.jameshazell.pilot.ui.theme.PilotColors.Red) }
        }
    }
    if (confirmForget) {
        com.jameshazell.pilot.ui.components.ConfirmDialog(
            title = "Forget this laptop?",
            message = "This phone's JARVIS token is removed. To use JARVIS again you'll need a fresh one-time pairing code from the laptop.",
            confirmLabel = "Forget laptop",
            destructive = true,
            onConfirm = {
                confirmForget = false
                actions.unpair()
            },
            onDismiss = { confirmForget = false },
        )
    }
}

@Composable
private fun SheetField(label: String, value: String, onChange: (String) -> Unit, hint: String, secret: Boolean) {
    androidx.compose.material3.OutlinedTextField(
        value = value,
        onValueChange = onChange,
        label = { Text(label) },
        placeholder = { Text(hint) },
        singleLine = true,
        visualTransformation = if (secret) androidx.compose.ui.text.input.PasswordVisualTransformation() else androidx.compose.ui.text.input.VisualTransformation.None,
        keyboardOptions = KeyboardOptions(
            keyboardType = if (secret) androidx.compose.ui.text.input.KeyboardType.Password else androidx.compose.ui.text.input.KeyboardType.Uri,
            autoCorrectEnabled = false,
        ),
        modifier = Modifier.fillMaxWidth(),
    )
}
