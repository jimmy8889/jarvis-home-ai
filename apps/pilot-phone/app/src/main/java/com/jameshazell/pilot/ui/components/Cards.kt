package com.jameshazell.pilot.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens
import com.jameshazell.pilot.ui.theme.PilotIcons
import com.jameshazell.pilot.ui.theme.PilotText

/**
 * The standard panel: 22dp corners, hairline border, 16dp padding, 12dp between children.
 *
 * @param tint when set, the panel is washed with this accent (an "active" card).
 * @param raised use the lighter panel colour, for a card that sits on another card.
 * @param onClick makes the whole card one button.
 */
@Composable
fun PilotCard(
    modifier: Modifier = Modifier,
    tint: Color? = null,
    raised: Boolean = false,
    onClick: (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val base = if (raised) PilotColors.PanelRaised else PilotColors.Panel
    val shape = RoundedCornerShape(PilotDimens.CardRadius)
    Surface(
        modifier = modifier
            .clip(shape)
            .then(if (onClick != null) Modifier.clickable(role = Role.Button, onClick = onClick) else Modifier),
        shape = shape,
        color = tint?.copy(alpha = 0.16f)?.compositeOver(base) ?: base,
        contentColor = PilotColors.Text,
        border = BorderStroke(1.dp, tint?.copy(alpha = 0.35f) ?: PilotColors.Hairline),
    ) {
        Column(
            Modifier.padding(PilotDimens.CardPadding),
            verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap),
            content = content,
        )
    }
}

/** Small-caps section title with an optional text action on the right. */
@Composable
fun SectionHeader(
    title: String,
    modifier: Modifier = Modifier,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
) {
    Row(
        modifier.fillMaxWidth().heightIn(min = if (actionLabel != null) PilotDimens.TouchTarget else 32.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            title.uppercase(),
            style = MaterialTheme.typography.labelSmall,
            color = PilotColors.TextDim,
            modifier = Modifier.weight(1f).semantics { heading() },
        )
        if (actionLabel != null && onAction != null) {
            TextButton(onClick = onAction) { Text(actionLabel, color = PilotColors.Violet) }
        }
    }
}

/**
 * One reading: icon and label on top, a large value with its unit, and an optional note.
 * Pass `value = "—"` for an unknown reading; never show zero for missing data.
 */
@Composable
fun StatCell(
    icon: ImageVector,
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    unit: String? = null,
    note: String? = null,
    accent: Color = PilotColors.Violet,
) {
    Column(modifier.semantics(mergeDescendants = true) {}, verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(icon, contentDescription = null, tint = accent, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(6.dp))
            Text(
                label,
                style = MaterialTheme.typography.labelMedium,
                color = PilotColors.TextDim,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Row(verticalAlignment = Alignment.Bottom) {
            Text(value, style = PilotText.Value, color = PilotColors.Text, maxLines = 1)
            if (unit != null) {
                Spacer(Modifier.width(4.dp))
                Text(unit, style = PilotText.Unit, color = PilotColors.TextDim, modifier = Modifier.padding(bottom = 3.dp))
            }
        }
        if (note != null) {
            Text(note, style = MaterialTheme.typography.labelMedium, color = PilotColors.TextFaint)
        }
    }
}

/**
 * A room (or device group) tile. Washed with [accent] while [active]. Tapping the tile opens the
 * room; the round power button, shown when [onPower] is given, switches it without opening.
 */
@Composable
fun RoomTile(
    name: String,
    status: String,
    active: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    accent: Color = PilotColors.Amber,
    icon: ImageVector? = null,
    onPower: (() -> Unit)? = null,
    powerEnabled: Boolean = true,
) {
    PilotCard(modifier = modifier, tint = accent.takeIf { active }, onClick = onClick) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (icon != null) {
                Icon(
                    icon,
                    contentDescription = null,
                    tint = if (active) accent else PilotColors.TextFaint,
                    modifier = Modifier.size(24.dp),
                )
                Spacer(Modifier.width(PilotDimens.Gap))
            }
            Column(Modifier.weight(1f)) {
                Text(name, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(
                    status,
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (active) PilotColors.Text else PilotColors.TextDim,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (onPower != null) {
                Spacer(Modifier.width(PilotDimens.Gap))
                Box(
                    Modifier
                        .size(PilotDimens.TouchTarget)
                        .clip(CircleShape)
                        .clickable(
                            enabled = powerEnabled,
                            role = Role.Switch,
                            onClickLabel = if (active) "Turn $name off" else "Turn $name on",
                            onClick = onPower,
                        ),
                    contentAlignment = Alignment.Center,
                ) {
                    Surface(
                        shape = CircleShape,
                        color = if (active) accent else PilotColors.PanelRaised,
                        modifier = Modifier.size(40.dp),
                    ) {
                        Box(contentAlignment = Alignment.Center) {
                            Icon(
                                PilotIcons.Power,
                                contentDescription = null,
                                tint = if (active) PilotColors.OnAccent else PilotColors.TextDim,
                                modifier = Modifier.size(20.dp),
                            )
                        }
                    }
                }
            }
        }
    }
}

/** A line of secondary text for empty or explanatory states inside a card. */
@Composable
fun CardNote(text: String, modifier: Modifier = Modifier, color: Color = PilotColors.TextDim) {
    Text(text, style = MaterialTheme.typography.bodyMedium, color = color, modifier = modifier.defaultMinSize(minHeight = 20.dp))
}
