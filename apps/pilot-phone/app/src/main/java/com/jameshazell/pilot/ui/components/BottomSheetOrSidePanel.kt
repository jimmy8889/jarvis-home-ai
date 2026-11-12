package com.jameshazell.pilot.ui.components

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.jameshazell.pilot.ui.adaptive.LocalPilotWindow
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens
import com.jameshazell.pilot.ui.theme.PilotIcons

/**
 * Secondary content over the current screen (device controls, settings forms):
 * a modal bottom sheet in Compact windows, a panel sliding in from the trailing edge otherwise.
 * Dismissed by Back, by tapping outside, by the close button, or by swiping the sheet down.
 *
 * Place it at the top level of a screen so the side panel can cover the full height.
 * [content] scrolls; children are spaced 12dp apart.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BottomSheetOrSidePanel(
    visible: Boolean,
    onDismiss: () -> Unit,
    title: String,
    modifier: Modifier = Modifier,
    panelWidth: Dp = 380.dp,
    content: @Composable ColumnScope.() -> Unit,
) {
    val compact = LocalPilotWindow.current.sizeClass.isCompact
    if (compact) {
        if (!visible) return
        ModalBottomSheet(
            onDismissRequest = onDismiss,
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
            containerColor = PilotColors.Panel,
            contentColor = PilotColors.Text,
            shape = RoundedCornerShape(topStart = PilotDimens.CardRadius, topEnd = PilotDimens.CardRadius),
            modifier = modifier,
        ) {
            PanelBody(title, onDismiss, showClose = false, content = content)
        }
        return
    }

    BackHandler(enabled = visible, onBack = onDismiss)
    Box(modifier.fillMaxSize()) {
        AnimatedVisibility(visible, enter = fadeIn(), exit = fadeOut()) {
            Box(
                Modifier
                    .fillMaxSize()
                    .background(Color(0x99000000))
                    .clickable(
                        interactionSource = remember { MutableInteractionSource() },
                        indication = null,
                        onClickLabel = "Close $title",
                        onClick = onDismiss,
                    ),
            )
        }
        AnimatedVisibility(
            visible,
            modifier = Modifier.align(Alignment.CenterEnd),
            enter = slideInHorizontally { it },
            exit = slideOutHorizontally { it },
        ) {
            Surface(
                modifier = Modifier.width(panelWidth).fillMaxHeight().padding(PilotDimens.Gap),
                shape = RoundedCornerShape(PilotDimens.CardRadius),
                color = PilotColors.Panel,
                contentColor = PilotColors.Text,
            ) {
                PanelBody(title, onDismiss, showClose = true, content = content)
            }
        }
    }
}

@Composable
private fun PanelBody(
    title: String,
    onDismiss: () -> Unit,
    showClose: Boolean,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        Modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .padding(start = PilotDimens.CardPadding, end = PilotDimens.CardPadding, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = if (showClose) 8.dp else 0.dp)) {
            Text(
                title,
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.weight(1f).semantics { heading() },
            )
            if (showClose) {
                Box(
                    Modifier
                        .size(PilotDimens.TouchTarget)
                        .clip(CircleShape)
                        .clickable(role = Role.Button, onClickLabel = "Close", onClick = onDismiss),
                    contentAlignment = Alignment.Center,
                ) { Icon(PilotIcons.Close, contentDescription = "Close", tint = PilotColors.TextDim) }
            }
        }
        content()
    }
}
