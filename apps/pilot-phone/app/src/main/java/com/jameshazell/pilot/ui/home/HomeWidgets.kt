package com.jameshazell.pilot.ui.home

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
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
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.jameshazell.pilot.ui.adaptive.LocalPilotWindow
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens
import com.jameshazell.pilot.ui.theme.PilotIcons

// Small building blocks shared by Home, room detail and More.

/**
 * Title bar of a detail pane. The leading button is Back in a Compact window (the pane covers
 * the list) and Close when list and detail sit side by side.
 */
@Composable
fun DetailHeader(
    title: String,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    trailing: @Composable () -> Unit = {},
) {
    val twoPane = LocalPilotWindow.current.isTwoPane
    Row(
        modifier.fillMaxWidth().padding(start = 4.dp, end = PilotDimens.ScreenPadding, top = 4.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RoundIconButton(
            icon = if (twoPane) PilotIcons.Close else PilotIcons.Back,
            description = if (twoPane) "Close $title" else "Back",
            onClick = onBack,
        )
        Column(Modifier.weight(1f).padding(start = 4.dp)) {
            Text(
                title,
                style = MaterialTheme.typography.titleLarge,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.semantics { heading() },
            )
            if (!subtitle.isNullOrBlank()) {
                Text(
                    subtitle,
                    style = MaterialTheme.typography.bodyMedium,
                    color = PilotColors.TextDim,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        trailing()
    }
}

/** A round icon button with a 48dp touch target. [filled] draws it on a solid [accent] disc. */
@Composable
fun RoundIconButton(
    icon: ImageVector,
    description: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    filled: Boolean = false,
    outlined: Boolean = false,
    accent: Color = PilotColors.Violet,
) {
    Box(
        modifier
            .size(PilotDimens.TouchTarget)
            .alpha(if (enabled) 1f else 0.4f)
            .clip(CircleShape)
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick)
            .semantics { contentDescription = description },
        contentAlignment = Alignment.Center,
    ) {
        Surface(
            shape = CircleShape,
            color = if (filled) accent else if (outlined) PilotColors.PanelRaised else Color.Transparent,
            modifier = Modifier.size(40.dp),
        ) {
            Box(contentAlignment = Alignment.Center) {
                Icon(
                    icon,
                    contentDescription = null,
                    tint = if (filled) PilotColors.OnAccent else PilotColors.Text,
                    modifier = Modifier.size(22.dp),
                )
            }
        }
    }
}

/** A pill-shaped text button, at least 48dp tall. [filled] makes it the primary action. */
@Composable
fun PillButton(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    filled: Boolean = false,
    accent: Color = PilotColors.Violet,
    icon: ImageVector? = null,
) {
    Box(
        modifier
            .defaultMinSize(minWidth = PilotDimens.TouchTarget, minHeight = PilotDimens.TouchTarget)
            .alpha(if (enabled) 1f else 0.4f)
            .clip(RoundedCornerShape(PilotDimens.PillRadius))
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Surface(
            shape = RoundedCornerShape(PilotDimens.PillRadius),
            color = if (filled) accent else PilotColors.PanelRaised,
            contentColor = if (filled) PilotColors.OnAccent else PilotColors.Text,
            border = if (filled) null else BorderStroke(1.dp, PilotColors.Hairline),
        ) {
            Row(Modifier.padding(horizontal = 16.dp, vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
                if (icon != null) {
                    Icon(icon, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                }
                Text(label, style = MaterialTheme.typography.labelLarge, maxLines = 1)
            }
        }
    }
}

/** A read-only or tappable status pill for the Home chip row. */
@Composable
fun StatusPill(
    label: String,
    icon: ImageVector,
    modifier: Modifier = Modifier,
    accent: Color = PilotColors.TextDim,
    active: Boolean = false,
    onClick: (() -> Unit)? = null,
    onClickLabel: String? = null,
) {
    val shape = RoundedCornerShape(PilotDimens.PillRadius)
    Box(
        modifier
            .defaultMinSize(minHeight = PilotDimens.TouchTarget)
            .clip(shape)
            .then(
                if (onClick != null) Modifier.clickable(role = Role.Button, onClickLabel = onClickLabel, onClick = onClick)
                else Modifier,
            ),
        contentAlignment = Alignment.Center,
    ) {
        Surface(
            shape = shape,
            color = if (active) accent.copy(alpha = 0.16f) else PilotColors.Panel,
            contentColor = if (active) PilotColors.Text else PilotColors.TextDim,
            border = BorderStroke(1.dp, if (active) accent.copy(alpha = 0.35f) else PilotColors.Hairline),
        ) {
            Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(icon, contentDescription = null, tint = if (active) accent else PilotColors.TextFaint, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(6.dp))
                Text(label, style = MaterialTheme.typography.labelLarge, maxLines = 1)
            }
        }
    }
}

/** An inline notice: why something failed or why controls are disabled. Announced politely. */
@Composable
fun InlineMessage(
    text: String,
    modifier: Modifier = Modifier,
    color: Color = PilotColors.Red,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
) {
    Surface(
        modifier = modifier.fillMaxWidth().semantics { liveRegion = LiveRegionMode.Polite },
        shape = RoundedCornerShape(14.dp),
        color = PilotColors.PanelRaised,
        contentColor = PilotColors.Text,
    ) {
        Row(Modifier.padding(start = 12.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(PilotIcons.Warning, contentDescription = null, tint = color, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(10.dp))
            Text(
                text,
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.weight(1f).padding(vertical = 12.dp),
            )
            if (actionLabel != null && onAction != null) {
                TextButton(onClick = onAction, modifier = Modifier.heightIn(min = PilotDimens.TouchTarget)) {
                    Text(actionLabel, color = PilotColors.Violet)
                }
            } else Spacer(Modifier.width(8.dp))
        }
    }
}

/** A device or setting line: icon, name, state and a trailing control. At least 48dp tall. */
@Composable
fun ControlRow(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    icon: ImageVector? = null,
    iconTint: Color = PilotColors.TextFaint,
    subtitleColor: Color = PilotColors.TextDim,
    onClick: (() -> Unit)? = null,
    trailing: @Composable () -> Unit = {},
) {
    Row(
        modifier
            .fillMaxWidth()
            .heightIn(min = PilotDimens.TouchTarget)
            .then(if (onClick != null) Modifier.clip(RoundedCornerShape(12.dp)).clickable(role = Role.Button, onClick = onClick) else Modifier),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null, tint = iconTint, modifier = Modifier.size(22.dp))
            Spacer(Modifier.width(PilotDimens.Gap))
        }
        Column(Modifier.weight(1f).semantics(mergeDescendants = true) {}) {
            Text(title, style = MaterialTheme.typography.bodyLarge, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (!subtitle.isNullOrBlank()) {
                Text(
                    subtitle,
                    style = MaterialTheme.typography.bodyMedium,
                    color = subtitleColor,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        Spacer(Modifier.width(8.dp))
        trailing()
    }
}

/** What the detail pane shows on the open Fold when nothing is selected. */
@Composable
fun EmptyDetail(title: String, text: String, icon: ImageVector, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize().padding(PilotDimens.ScreenPadding), contentAlignment = Alignment.Center) {
        Column(
            Modifier.widthIn(max = 280.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Icon(icon, contentDescription = null, tint = PilotColors.TextFaint, modifier = Modifier.size(32.dp))
            Text(title, style = MaterialTheme.typography.titleMedium, textAlign = TextAlign.Center)
            Text(text, style = MaterialTheme.typography.bodyMedium, color = PilotColors.TextDim, textAlign = TextAlign.Center)
        }
    }
}
