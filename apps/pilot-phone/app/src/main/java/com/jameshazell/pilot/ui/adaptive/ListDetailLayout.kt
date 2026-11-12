package com.jameshazell.pilot.ui.adaptive

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.ExitTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.slideInVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.movableContentOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens

/**
 * A list with a detail view, laid out for the current [LocalPilotWindow]:
 *
 * - Compact (closed Fold): the list fills the screen; when [hasDetail] the detail slides up as a
 *   full-height sheet over it and system Back calls [onBack].
 * - Medium / Expanded (open Fold): list and detail side by side. With a separating hinge the
 *   split sits exactly on it; otherwise the list takes [listFraction] of the width.
 *
 * [list] and [detail] keep their state (scroll position, text input) when the phone is folded
 * or unfolded. [detail] is only composed while [hasDetail] is true.
 *
 * @param onBack clear the selection so [hasDetail] becomes false.
 * @param emptyDetail what the detail pane shows in two-pane mode when nothing is selected.
 */
@Composable
fun ListDetailLayout(
    hasDetail: Boolean,
    onBack: () -> Unit,
    list: @Composable () -> Unit,
    detail: @Composable () -> Unit,
    modifier: Modifier = Modifier,
    listFraction: Float = 0.42f,
    paneGap: Dp = PilotDimens.Gap,
    emptyDetail: @Composable () -> Unit = {},
) {
    val window = LocalPilotWindow.current
    val currentList by rememberUpdatedState(list)
    val currentDetail by rememberUpdatedState(detail)
    // Movable so the same composition (and its state) is reused in both arrangements.
    val listPane = remember { movableContentOf { currentList() } }
    val detailPane = remember { movableContentOf { currentDetail() } }

    if (!window.isTwoPane) {
        Box(modifier.fillMaxSize()) {
            listPane()
            AnimatedVisibility(
                visible = hasDetail,
                enter = slideInVertically(tween(220)) { it / 6 } + fadeIn(tween(160)),
                exit = ExitTransition.None,
            ) {
                Box(Modifier.fillMaxSize().background(PilotColors.Background)) { detailPane() }
            }
        }
        BackHandler(enabled = hasDetail, onBack = onBack)
        return
    }

    val density = LocalDensity.current
    var leftInWindow by remember { mutableFloatStateOf(0f) }
    val hinge = window.hinge
    Row(modifier.fillMaxSize().onGloballyPositioned { leftInWindow = it.positionInWindow().x }) {
        val listModifier: Modifier
        val gap: Dp
        if (hinge != null && hinge.left - leftInWindow > with(density) { 200.dp.toPx() }) {
            listModifier = Modifier.width(with(density) { (hinge.left - leftInWindow).toDp() })
            gap = with(density) { hinge.width.toDp() }.coerceAtLeast(paneGap)
        } else {
            listModifier = Modifier.weight(listFraction.coerceIn(0.2f, 0.8f))
            gap = paneGap
        }
        Box(listModifier.fillMaxHeight()) { listPane() }
        Spacer(Modifier.width(gap))
        Box(Modifier.weight(1f - listFraction.coerceIn(0.2f, 0.8f)).fillMaxHeight()) {
            if (hasDetail) detailPane() else emptyDetail()
        }
    }
}
