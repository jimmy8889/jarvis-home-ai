package com.jameshazell.pilot.ui.components

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.dp
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens

/** A pill for filters and tabs. Selected chips fill with [accent]. Touch target is 48dp tall. */
@Composable
fun Chip(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    accent: Color = PilotColors.Violet,
    icon: ImageVector? = null,
    enabled: Boolean = true,
) {
    Box(
        modifier
            .defaultMinSize(minHeight = PilotDimens.TouchTarget)
            .alpha(if (enabled) 1f else 0.45f)
            .clip(RoundedCornerShape(PilotDimens.PillRadius))
            .selectable(selected = selected, enabled = enabled, role = Role.Tab, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Surface(
            shape = RoundedCornerShape(PilotDimens.PillRadius),
            color = if (selected) accent else PilotColors.Panel,
            contentColor = if (selected) PilotColors.OnAccent else PilotColors.TextDim,
            border = if (selected) null else BorderStroke(1.dp, PilotColors.Hairline),
        ) {
            Row(
                Modifier.padding(horizontal = 14.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (icon != null) {
                    Icon(icon, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(6.dp))
                }
                Text(label, style = MaterialTheme.typography.labelLarge, maxLines = 1)
            }
        }
    }
}

/**
 * The on/off pill. [label] is read by screen readers; put the visible label next to it yourself.
 */
@Composable
fun PillSwitch(
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    label: String,
    modifier: Modifier = Modifier,
    accent: Color = PilotColors.Violet,
    enabled: Boolean = true,
) {
    val track by animateColorAsState(if (checked) accent else PilotColors.PanelRaised, label = "track")
    val thumbOffset by animateDpAsState(if (checked) 22.dp else 2.dp, label = "thumb")
    Box(
        modifier
            .size(width = 56.dp, height = PilotDimens.TouchTarget)
            .alpha(if (enabled) 1f else 0.45f)
            .clip(RoundedCornerShape(PilotDimens.PillRadius))
            .toggleable(value = checked, enabled = enabled, role = Role.Switch, onValueChange = onCheckedChange)
            .semantics {
                contentDescription = label
                stateDescription = if (checked) "On" else "Off"
            },
        contentAlignment = Alignment.Center,
    ) {
        Box(
            Modifier
                .size(width = 52.dp, height = 32.dp)
                .background(track, RoundedCornerShape(PilotDimens.PillRadius)),
            contentAlignment = Alignment.CenterStart,
        ) {
            Box(
                Modifier
                    .offset(x = thumbOffset)
                    .size(28.dp)
                    .background(if (checked) PilotColors.OnAccent else PilotColors.TextDim, CircleShape),
            )
        }
    }
}

/**
 * A labelled slider for brightness, volume, position and temperature.
 *
 * @param value current level within [range].
 * @param valueText what to show on the right, e.g. "64%" or "23°".
 * @param onValueChange called continuously while dragging; update local state only.
 * @param onValueChangeFinished called once on release; send the command here.
 */
@Composable
fun LevelSlider(
    label: String,
    value: Float,
    valueText: String,
    onValueChange: (Float) -> Unit,
    modifier: Modifier = Modifier,
    onValueChangeFinished: () -> Unit = {},
    range: ClosedFloatingPointRange<Float> = 0f..100f,
    steps: Int = 0,
    accent: Color = PilotColors.Amber,
    enabled: Boolean = true,
) {
    Column(modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(label, style = MaterialTheme.typography.bodyMedium, color = PilotColors.TextDim, modifier = Modifier.weight(1f))
            Text(valueText, style = MaterialTheme.typography.labelLarge, color = PilotColors.Text)
        }
        Slider(
            value = value.coerceIn(range.start, range.endInclusive),
            onValueChange = onValueChange,
            onValueChangeFinished = onValueChangeFinished,
            valueRange = range,
            steps = steps,
            enabled = enabled,
            colors = SliderDefaults.colors(
                thumbColor = accent,
                activeTrackColor = accent,
                inactiveTrackColor = PilotColors.PanelRaised,
                activeTickColor = Color.Transparent,
                inactiveTickColor = Color.Transparent,
            ),
            modifier = Modifier.semantics { contentDescription = label },
        )
    }
}

/**
 * Asks before doing something that matters.
 *
 * @param confirmLabel names the action ("Unlock front door"), never just "OK".
 * @param destructive colours the confirm button red.
 * @param busy disables both buttons while the action is being sent.
 */
@Composable
fun ConfirmDialog(
    title: String,
    message: String,
    confirmLabel: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
    dismissLabel: String = "Cancel",
    destructive: Boolean = false,
    busy: Boolean = false,
    error: String? = null,
) {
    AlertDialog(
        onDismissRequest = { if (!busy) onDismiss() },
        containerColor = PilotColors.PanelRaised,
        titleContentColor = PilotColors.Text,
        textContentColor = PilotColors.TextDim,
        shape = RoundedCornerShape(PilotDimens.CardRadius),
        title = { Text(title) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap)) {
                Text(message)
                if (error != null) Text(error, color = PilotColors.Red)
            }
        },
        confirmButton = {
            Button(
                onClick = onConfirm,
                enabled = !busy,
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (destructive) PilotColors.Red else PilotColors.Violet,
                    contentColor = PilotColors.OnAccent,
                ),
            ) { Text(if (busy) "Working…" else confirmLabel) }
        },
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = !busy) { Text(dismissLabel, color = PilotColors.TextDim) }
        },
    )
}
