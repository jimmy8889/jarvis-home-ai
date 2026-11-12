package com.jameshazell.pilot.ui.more.music

import com.jameshazell.pilot.data.pilot.EffectiveMediaState
import com.jameshazell.pilot.data.pilot.MediaSnapshot
import com.jameshazell.pilot.data.pilot.PilotPlayerState
import com.jameshazell.pilot.data.pilot.PilotRoom
import java.util.Locale
import kotlin.math.roundToInt

// Plain Kotlin: shared by the Music page and the Media card in room detail, and unit-tested.

/**
 * Whether a player can do [action]. Players that list capabilities are taken at their word;
 * players that list none are assumed to manage only the basics.
 */
fun EffectiveMediaState.supports(action: String): Boolean = when {
    action in capabilities -> true
    capabilities.isNotEmpty() -> false
    else -> action in setOf("play", "pause", "stop", "set_volume", "transfer")
}

val EffectiveMediaState.isPlaying: Boolean get() = playbackState == "playing"

/** "3:07"; hours appear only when needed ("1:02:45"). */
fun formatDuration(seconds: Double): String {
    val total = seconds.coerceAtLeast(0.0).roundToInt()
    val hours = total / 3600
    val minutes = (total % 3600) / 60
    val secs = total % 60
    return if (hours > 0) String.format(Locale.US, "%d:%02d:%02d", hours, minutes, secs)
    else String.format(Locale.US, "%d:%02d", minutes, secs)
}

fun nowPlayingTitle(state: PilotPlayerState): String =
    state.effective.media?.title?.takeIf { it.isNotBlank() }
        ?: if (state.effective.available) "Nothing playing" else "Player unavailable"

fun nowPlayingSubtitle(state: PilotPlayerState): String {
    val media = state.effective.media
    return listOfNotNull(media?.artist, media?.album).filter { it.isNotBlank() }.joinToString(" · ")
        .ifBlank { state.effective.source?.takeIf { it.isNotBlank() } ?: state.player.name }
}

/**
 * The player the Music page controls for a room: one that has something loaded, else the room's
 * default music player, else its first player. Null when the room has none.
 */
fun roomPlayer(media: MediaSnapshot, roomId: String?): PilotPlayerState? {
    val room = media.rooms.firstOrNull { it.id == roomId } ?: return null
    val inRoom = media.players.filter { it.player.roomId == room.id && it.player.enabled }
    return inRoom.firstOrNull { it.effective.media?.title != null && it.effective.playbackState in setOf("playing", "paused") }
        ?: inRoom.firstOrNull { it.player.id == room.defaultMusicPlayerId }
        ?: inRoom.firstOrNull { it.effective.media?.title != null }
        ?: inRoom.firstOrNull()
}

/** Rooms music can be played in. */
fun musicRooms(rooms: List<PilotRoom>): List<PilotRoom> =
    rooms.filter { it.musicEnabled && (it.defaultMusicPlayerId != null || it.players.isNotEmpty()) }

/** Rooms the current playback can be moved to: every other room with a default music player. */
fun transferTargets(rooms: List<PilotRoom>, player: PilotPlayerState): List<PilotRoom> =
    if (!player.effective.supports("transfer")) emptyList()
    else rooms.filter { it.id != player.player.roomId && it.musicEnabled && it.defaultMusicPlayerId != null }

/** Seek position for a slider, or null when the track length is unknown. */
fun playbackProgress(state: EffectiveMediaState): Pair<Float, Float>? {
    val duration = state.durationSeconds ?: state.media?.durationSeconds ?: return null
    if (duration <= 0) return null
    return (state.positionSeconds ?: 0.0).toFloat().coerceIn(0f, duration.toFloat()) to duration.toFloat()
}
