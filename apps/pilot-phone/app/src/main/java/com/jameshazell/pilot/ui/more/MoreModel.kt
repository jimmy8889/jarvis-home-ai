package com.jameshazell.pilot.ui.more

import com.jameshazell.pilot.core.ErrorKind
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.core.PilotConfig
import com.jameshazell.pilot.data.control.ControlConnection
import com.jameshazell.pilot.data.pilot.PilotRepository
import com.jameshazell.pilot.data.pilot.PilotSnapshot

// Plain Kotlin so it runs in JVM tests.

/** The pages under More, in menu order. */
enum class MorePage(val title: String, val summary: String) {
    Music("Music", "Search, now playing and room transfer"),
    Settings("Settings", "Connections, refresh and pairing"),
    About("About", "Version and how Pilot keeps your data"),
}

enum class StatusTone { Good, Warning, Bad, Idle }

/** One backend's connection state, in words. */
data class ServiceStatus(val name: String, val label: String, val detail: String?, val tone: StatusTone)

fun pilotStatus(snapshot: LoadState<PilotSnapshot>, paired: Boolean, liveEvents: Boolean): ServiceStatus {
    val label = PilotRepository.dashboardLabel(snapshot, paired)
    return when {
        !paired -> ServiceStatus("Pilot Core", label, "Pair this phone to use Home and Pilot.", StatusTone.Idle)
        snapshot is LoadState.Loading -> ServiceStatus("Pilot Core", label, null, StatusTone.Warning)
        snapshot is LoadState.Error -> ServiceStatus("Pilot Core", label, snapshot.error.message, StatusTone.Bad)
        snapshot is LoadState.Content && snapshot.stale -> ServiceStatus(
            "Pilot Core", "Showing saved data", snapshot.problem?.message ?: "Updating…", StatusTone.Warning,
        )
        else -> ServiceStatus(
            "Pilot Core",
            label,
            if (liveEvents) "Live updates are on." else "Refreshing on a timer.",
            StatusTone.Good,
        )
    }
}

/**
 * Energy Manager and James Control only connect while their own screen is open, so before that
 * the honest answer is "not checked yet".
 */
fun energyStatus(bootstrap: LoadState<*>): ServiceStatus =
    passiveStatus("Energy Manager", bootstrap, "Open Energy to connect.")

fun controlStatus(overview: LoadState<*>, connection: ControlConnection): ServiceStatus {
    val name = "James Control"
    return when (connection) {
        ControlConnection.Live -> ServiceStatus(name, "Connected", "Live updates are on.", StatusTone.Good)
        ControlConnection.Connecting -> ServiceStatus(name, "Connecting", null, StatusTone.Warning)
        is ControlConnection.Reconnecting -> ServiceStatus(
            name,
            "Reconnecting",
            if (connection.retryInSeconds == 1) "Next try in 1 second." else "Next try in ${connection.retryInSeconds} seconds.",
            StatusTone.Warning,
        )
        ControlConnection.SessionExpired -> ServiceStatus(
            name, "Session expired", "Renew the James Control session for this phone.", StatusTone.Bad,
        )
        ControlConnection.NotPaired -> ServiceStatus(
            name, "Not set up", "This phone has no James Control session.", StatusTone.Idle,
        )
        ControlConnection.Idle -> passiveStatus(name, overview, "Open Control to connect.")
    }
}

private fun passiveStatus(name: String, state: LoadState<*>, hint: String): ServiceStatus = when (state) {
    is LoadState.Loading -> ServiceStatus(name, "Not checked yet", hint, StatusTone.Idle)
    is LoadState.Content ->
        if (state.stale) ServiceStatus(name, "Showing saved data", state.problem?.message ?: hint, StatusTone.Warning)
        else ServiceStatus(name, "Connected", null, StatusTone.Good)
    is LoadState.Error -> when (state.error.kind) {
        ErrorKind.NotPaired -> ServiceStatus(name, "Not set up", state.error.message, StatusTone.Idle)
        ErrorKind.Unauthorized -> ServiceStatus(name, "Pairing needed", state.error.message, StatusTone.Bad)
        else -> ServiceStatus(name, "Can't connect", state.error.message, StatusTone.Bad)
    }
}

/** Refresh intervals offered in Settings, in seconds. All within [PilotConfig.REFRESH_RANGE]. */
val RefreshChoices: List<Int> = listOf(5, 15, 30, 60, 120)

/** The choices, plus the saved value when it is not one of them (set by an older version). */
fun refreshChoices(current: Int): List<Int> =
    if (current in RefreshChoices) RefreshChoices else (RefreshChoices + current.coerceIn(PilotConfig.REFRESH_RANGE)).sorted()

fun refreshLabel(seconds: Int): String = when {
    seconds < 60 -> "$seconds s"
    seconds % 60 == 0 -> "${seconds / 60} min"
    else -> "${seconds / 60} min ${seconds % 60} s"
}
