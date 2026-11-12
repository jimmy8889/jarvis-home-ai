package com.jameshazell.pilot.ui.adaptive

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.NavigationRailItemDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import com.jameshazell.pilot.ui.theme.PilotColors

/** One entry in the app's navigation. */
data class ShellDestination(val id: String, val label: String, val icon: ImageVector)

/**
 * The app frame: a bottom bar in Compact windows, a navigation rail on the leading edge
 * otherwise. [content] keeps its state when the window changes class (fold / unfold), and is
 * already inset from the system bars and the navigation.
 */
@Composable
fun AdaptiveShell(
    destinations: List<ShellDestination>,
    selectedId: String,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    val compact = LocalPilotWindow.current.sizeClass.isCompact
    Row(
        modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Horizontal)),
    ) {
        if (!compact) {
            NavigationRail(
                modifier = Modifier.fillMaxHeight(),
                containerColor = PilotColors.Background,
                contentColor = PilotColors.TextDim,
                windowInsets = WindowInsets.safeDrawing.only(WindowInsetsSides.Vertical),
            ) {
                destinations.forEach { destination ->
                    NavigationRailItem(
                        selected = destination.id == selectedId,
                        onClick = { onSelect(destination.id) },
                        icon = { Icon(destination.icon, contentDescription = null) },
                        label = { Text(destination.label) },
                        colors = NavigationRailItemDefaults.colors(
                            selectedIconColor = PilotColors.OnAccent,
                            selectedTextColor = PilotColors.Text,
                            indicatorColor = PilotColors.Violet,
                            unselectedIconColor = PilotColors.TextDim,
                            unselectedTextColor = PilotColors.TextDim,
                        ),
                    )
                }
            }
        }
        Column(Modifier.weight(1f).fillMaxHeight()) {
            Box(
                Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .windowInsetsPadding(
                        WindowInsets.safeDrawing.only(
                            if (compact) WindowInsetsSides.Top else WindowInsetsSides.Vertical,
                        ),
                    ),
            ) { content() }
            if (compact) {
                NavigationBar(
                    containerColor = PilotColors.Panel,
                    contentColor = PilotColors.TextDim,
                    windowInsets = WindowInsets.safeDrawing.only(WindowInsetsSides.Bottom),
                ) {
                    destinations.forEach { destination ->
                        NavigationBarItem(
                            selected = destination.id == selectedId,
                            onClick = { onSelect(destination.id) },
                            icon = { Icon(destination.icon, contentDescription = null) },
                            label = { Text(destination.label) },
                            colors = NavigationBarItemDefaults.colors(
                                selectedIconColor = PilotColors.OnAccent,
                                selectedTextColor = PilotColors.Text,
                                indicatorColor = PilotColors.Violet,
                                unselectedIconColor = PilotColors.TextDim,
                                unselectedTextColor = PilotColors.TextDim,
                            ),
                        )
                    }
                }
            }
        }
    }
}
