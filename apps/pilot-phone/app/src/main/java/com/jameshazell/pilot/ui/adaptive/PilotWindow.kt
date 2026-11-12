package com.jameshazell.pilot.ui.adaptive

import android.app.Activity
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.IntRect
import androidx.window.layout.FoldingFeature
import androidx.window.layout.WindowInfoTracker
import androidx.window.layout.WindowLayoutInfo
import androidx.window.layout.WindowMetricsCalculator

/**
 * Width classes of the app window (not the screen: split-screen and the Fold's two displays
 * both change it). Galaxy Fold: cover ~360dp = Compact, open ~752dp = Medium.
 */
enum class WindowSizeClass {
    /** Under 600dp: one pane, bottom navigation. */
    Compact,
    /** 600–839dp: two panes, navigation rail. The open Fold lands here. */
    Medium,
    /** 840dp and wider. */
    Expanded;

    val isCompact: Boolean get() = this == Compact

    companion object {
        fun fromWidthDp(widthDp: Float): WindowSizeClass = when {
            widthDp < 600f -> Compact
            widthDp < 840f -> Medium
            else -> Expanded
        }
    }
}

/**
 * @param hinge bounds, in window pixels, of a vertical fold that splits the window into a left
 * and a right area (the phone half-opened like a book, or a dual-screen hinge). Null when the
 * display is flat or the fold is horizontal; a flat open Fold therefore has no hinge.
 */
data class PilotWindow(
    val sizeClass: WindowSizeClass,
    val hinge: IntRect? = null,
    val widthDp: Float = 0f,
    val heightDp: Float = 0f,
) {
    /** Two panes fit side by side. */
    val isTwoPane: Boolean get() = !sizeClass.isCompact
}

/** The current window. Provided once by MainActivity; read it anywhere with `.current`. */
val LocalPilotWindow = staticCompositionLocalOf { PilotWindow(WindowSizeClass.Compact) }

/** The fold to lay out around, if any: vertical and actually separating the two halves. */
internal fun separatingVerticalHinge(features: List<FoldingFeature>): IntRect? =
    features.firstOrNull { it.orientation == FoldingFeature.Orientation.VERTICAL && it.isSeparating }
        ?.bounds?.let { IntRect(it.left, it.top, it.right, it.bottom) }

/**
 * Tracks the window size and fold state. Updates in place when the phone is folded, unfolded
 * or rotated (the activity handles those configuration changes itself and is not recreated).
 */
@Composable
fun rememberPilotWindow(activity: Activity): PilotWindow {
    // Reading the configuration makes this recompose on every fold / rotation / resize.
    val configuration = LocalConfiguration.current
    val density = LocalDensity.current.density
    val bounds = remember(configuration) {
        WindowMetricsCalculator.getOrCreate().computeCurrentWindowMetrics(activity).bounds
    }
    val layoutFlow = remember(activity) { WindowInfoTracker.getOrCreate(activity).windowLayoutInfo(activity) }
    val layout: WindowLayoutInfo? by layoutFlow.collectAsState(initial = null)
    val hinge = separatingVerticalHinge(layout?.displayFeatures.orEmpty().filterIsInstance<FoldingFeature>())
    val widthDp = bounds.width() / density
    val heightDp = bounds.height() / density
    return remember(widthDp, heightDp, hinge) {
        PilotWindow(WindowSizeClass.fromWidthDp(widthDp), hinge, widthDp, heightDp)
    }
}
