package com.jameshazell.pilot.ui

import androidx.compose.ui.graphics.vector.ImageVector
import com.jameshazell.pilot.ui.adaptive.ShellDestination
import com.jameshazell.pilot.ui.theme.PilotIcons

/** The five top-level destinations, in navigation order. */
sealed class Destination(val id: String, val label: String, val icon: ImageVector) {
    data object Home : Destination("home", "Home", PilotIcons.Home)
    data object Energy : Destination("energy", "Energy", PilotIcons.Energy)
    data object Control : Destination("control", "Control", PilotIcons.Control)
    /** The assistant. */
    data object Pilot : Destination("pilot", "Pilot", PilotIcons.Assistant)
    data object More : Destination("more", "More", PilotIcons.More)

    fun toShell() = ShellDestination(id, label, icon)

    companion object {
        val all: List<Destination> by lazy { listOf(Home, Energy, Control, Pilot, More) }
        fun byId(id: String?): Destination = all.firstOrNull { it.id == id } ?: Home
    }
}
