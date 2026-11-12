package com.jameshazell.pilot.ui.control

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens
import com.jameshazell.pilot.ui.theme.PilotIcons

/*
 * Conversation building blocks shared by Control and the Pilot assistant.
 */

/** Icons these two destinations need on top of PilotIcons. */
internal object ChatIcons {
    val Send = icon("Send", "M2.01,21L23,12 2.01,3 2,10l15,2 -15,2z")
    val Stop = icon("Stop", "M6,6h12v12H6z")
    val ArrowDown = icon("ArrowDown", "M7,10l5,5 5,-5z")

    private fun icon(name: String, pathData: String): ImageVector =
        ImageVector.Builder(name = name, defaultWidth = 24.dp, defaultHeight = 24.dp, viewportWidth = 24f, viewportHeight = 24f)
            .addPath(pathData = addPathNodes(pathData), fill = SolidColor(Color.Black))
            .build()
}

internal fun Tone.color(): Color = when (this) {
    Tone.Neutral -> PilotColors.TextDim
    Tone.Good -> PilotColors.Teal
    Tone.Active -> PilotColors.Blue
    Tone.Warn -> PilotColors.Amber
    Tone.Bad -> PilotColors.Red
}

/**
 * Lifts content above the on-screen keyboard. Unlike `imePadding()` it only adds the part of the
 * keyboard that actually overlaps this element, so the bottom navigation bar under it is not
 * counted twice.
 */
@Composable
internal fun Modifier.keyboardPadding(): Modifier {
    val density = LocalDensity.current
    val view = LocalView.current
    val keyboard = WindowInsets.ime.getBottom(density)
    var spaceBelow by remember { mutableIntStateOf(0) }
    val overlap = (keyboard - spaceBelow).coerceAtLeast(0)
    return this
        .onGloballyPositioned { spaceBelow = (view.rootView.height - (it.positionInWindow().y + it.size.height)).toInt().coerceAtLeast(0) }
        .padding(bottom = with(density) { overlap.toDp() })
}

/** A small rounded status label: "Running", "Offline", "High risk". */
@Composable
internal fun StatusPill(text: String, tone: Tone, modifier: Modifier = Modifier) {
    val color = tone.color()
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(PilotDimens.PillRadius),
        color = color.copy(alpha = 0.16f).compositeOver(PilotColors.Panel),
        contentColor = color,
    ) {
        Text(
            text,
            style = MaterialTheme.typography.labelMedium,
            maxLines = 1,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
        )
    }
}

/**
 * One chat bubble. [mine] bubbles sit on the trailing edge with a violet wash; the others sit on
 * the leading edge on a panel.
 *
 * @param label small caption above the text ("Codex", "Working notes").
 * @param footer content under the text: status, retry, cards.
 */
@Composable
internal fun MessageBubble(
    text: String,
    mine: Boolean,
    modifier: Modifier = Modifier,
    label: String? = null,
    dim: Boolean = false,
    footer: (@Composable ColumnScope.() -> Unit)? = null,
) {
    Row(modifier.fillMaxWidth(), horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start) {
        if (mine) Spacer(Modifier.width(40.dp))
        Surface(
            modifier = Modifier.weight(1f, fill = false).widthIn(max = 560.dp),
            shape = RoundedCornerShape(
                topStart = 20.dp, topEnd = 20.dp,
                bottomStart = if (mine) 20.dp else 6.dp, bottomEnd = if (mine) 6.dp else 20.dp,
            ),
            color = if (mine) PilotColors.Violet.copy(alpha = 0.18f).compositeOver(PilotColors.Panel) else PilotColors.Panel,
            contentColor = PilotColors.Text,
            border = BorderStroke(1.dp, if (mine) PilotColors.Violet.copy(alpha = 0.35f) else PilotColors.Hairline),
        ) {
            Column(Modifier.padding(horizontal = 14.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                if (label != null) Text(label, style = MaterialTheme.typography.labelMedium, color = PilotColors.TextDim)
                if (text.isNotEmpty()) {
                    Text(text, style = MaterialTheme.typography.bodyLarge, color = if (dim) PilotColors.TextDim else PilotColors.Text)
                }
                if (footer != null) footer()
            }
        }
        if (!mine) Spacer(Modifier.width(40.dp))
    }
}

/** A round 48dp button with one icon. [label] is what screen readers announce. */
@Composable
internal fun RoundIconButton(
    icon: ImageVector,
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    filled: Boolean = false,
    accent: Color = PilotColors.Violet,
    size: Dp = PilotDimens.TouchTarget,
) {
    Box(
        modifier
            .size(size)
            .alpha(if (enabled) 1f else 0.4f)
            .clip(CircleShape)
            .background(if (filled) accent else Color.Transparent)
            .clickable(enabled = enabled, role = Role.Button, onClickLabel = label, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, contentDescription = label, tint = if (filled) PilotColors.OnAccent else PilotColors.TextDim, modifier = Modifier.size(22.dp))
    }
}

/**
 * The message box with its Send button.
 *
 * @param canSend false disables Send (the field stays editable so a draft is never lost).
 * @param blockedReason shown under the field when sending is not possible right now.
 */
@Composable
internal fun Composer(
    value: String,
    onValueChange: (String) -> Unit,
    onSend: () -> Unit,
    placeholder: String,
    canSend: Boolean,
    modifier: Modifier = Modifier,
    blockedReason: String? = null,
    trailing: (@Composable RowScope.() -> Unit)? = null,
) {
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = value,
                onValueChange = onValueChange,
                placeholder = { Text(placeholder, color = PilotColors.TextFaint, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                modifier = Modifier.weight(1f).heightIn(min = PilotDimens.TouchTarget),
                maxLines = 5,
                shape = RoundedCornerShape(PilotDimens.CardRadius),
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences, imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = { if (canSend) onSend() }),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedContainerColor = PilotColors.Panel,
                    unfocusedContainerColor = PilotColors.Panel,
                    focusedBorderColor = PilotColors.Violet,
                    unfocusedBorderColor = PilotColors.Hairline,
                    cursorColor = PilotColors.Violet,
                    focusedTextColor = PilotColors.Text,
                    unfocusedTextColor = PilotColors.Text,
                ),
            )
            RoundIconButton(ChatIcons.Send, "Send", onSend, enabled = canSend, filled = true)
            if (trailing != null) trailing()
        }
        if (blockedReason != null) {
            Text(
                blockedReason,
                style = MaterialTheme.typography.labelMedium,
                color = PilotColors.Amber,
                modifier = Modifier.padding(horizontal = 4.dp).semantics { liveRegion = LiveRegionMode.Polite },
            )
        }
    }
}

/**
 * Frame of a detail pane: a title row (with Back when the pane covers the list) above [content].
 * It swallows touches so nothing under a Compact detail sheet can be tapped through it.
 */
@Composable
internal fun DetailPane(
    title: String,
    showBack: Boolean,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    actions: @Composable RowScope.() -> Unit = {},
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(modifier.fillMaxSize().pointerInput(Unit) {}) {
        Row(
            Modifier.fillMaxWidth().padding(start = if (showBack) 4.dp else PilotDimens.ScreenPadding, end = 4.dp).heightIn(min = 56.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (showBack) RoundIconButton(PilotIcons.Back, "Back", onBack)
            Column(Modifier.weight(1f).padding(horizontal = if (showBack) 4.dp else 0.dp)) {
                Text(
                    title,
                    style = MaterialTheme.typography.titleMedium,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.semantics { heading() },
                )
                if (!subtitle.isNullOrBlank()) {
                    Text(subtitle, style = MaterialTheme.typography.labelMedium, color = PilotColors.TextDim, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            actions()
        }
        content()
    }
}
