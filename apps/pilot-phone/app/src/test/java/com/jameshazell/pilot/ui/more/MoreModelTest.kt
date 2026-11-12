package com.jameshazell.pilot.ui.more

import com.jameshazell.pilot.core.AppError
import com.jameshazell.pilot.core.ErrorKind
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.data.control.ControlConnection
import com.jameshazell.pilot.data.pilot.EffectiveMediaState
import com.jameshazell.pilot.ui.home.HomeFixtures
import com.jameshazell.pilot.ui.more.music.MusicUiState
import com.jameshazell.pilot.ui.more.music.buildMusicState
import com.jameshazell.pilot.ui.more.music.formatDuration
import com.jameshazell.pilot.ui.more.music.musicRooms
import com.jameshazell.pilot.ui.more.music.nowPlayingSubtitle
import com.jameshazell.pilot.ui.more.music.nowPlayingTitle
import com.jameshazell.pilot.ui.more.music.playbackProgress
import com.jameshazell.pilot.ui.more.music.roomPlayer
import com.jameshazell.pilot.ui.more.music.supports
import com.jameshazell.pilot.ui.more.music.transferTargets
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MoreModelTest {
    private val offline = AppError(ErrorKind.Offline, "This phone can't reach Pilot Core. Check the network or VPN.")

    // ---- Connection status ------------------------------------------------------------------

    @Test fun pilotStatusInEveryState() {
        val live = pilotStatus(LoadState.Content(HomeFixtures.snapshot), paired = true, liveEvents = true)
        assertEquals(ServiceStatus("Pilot Core", "Live", "Live updates are on.", StatusTone.Good), live)
        assertEquals(
            "Refreshing on a timer.",
            pilotStatus(LoadState.Content(HomeFixtures.snapshot), paired = true, liveEvents = false).detail,
        )
        val saved = pilotStatus(LoadState.Content(HomeFixtures.snapshot, stale = true, problem = offline), true, false)
        assertEquals(StatusTone.Warning, saved.tone)
        assertEquals("Showing saved data", saved.label)
        assertEquals(offline.message, saved.detail)
        val failed = pilotStatus(LoadState.Error(offline), true, false)
        assertEquals(StatusTone.Bad, failed.tone)
        assertEquals(offline.message, failed.detail)
        assertEquals(StatusTone.Idle, pilotStatus(LoadState.Loading, paired = false, liveEvents = false).tone)
        assertEquals("Connecting", pilotStatus(LoadState.Loading, paired = true, liveEvents = false).label)
    }

    @Test fun energyStatusIsHonestBeforeTheEnergyTabHasConnected() {
        val untouched = energyStatus(LoadState.Loading)
        assertEquals("Not checked yet", untouched.label)
        assertEquals("Open Energy to connect.", untouched.detail)
        assertEquals(StatusTone.Idle, untouched.tone)
        assertEquals(StatusTone.Good, energyStatus(LoadState.Content(Unit)).tone)
        assertEquals("Showing saved data", energyStatus(LoadState.Content(Unit, stale = true)).label)
        val notPaired = energyStatus(LoadState.Error(AppError(ErrorKind.NotPaired, "Energy Manager isn't set up on this phone.")))
        assertEquals("Not set up", notPaired.label)
        assertEquals(StatusTone.Idle, notPaired.tone)
        assertEquals("Pairing needed", energyStatus(LoadState.Error(AppError(ErrorKind.Unauthorized, "Rejected."))).label)
        assertEquals("Can't connect", energyStatus(LoadState.Error(offline)).label)
    }

    @Test fun controlStatusPrefersTheLiveConnection() {
        assertEquals(StatusTone.Good, controlStatus(LoadState.Loading, ControlConnection.Live).tone)
        val retrying = controlStatus(LoadState.Content(Unit), ControlConnection.Reconnecting(3, 8))
        assertEquals("Reconnecting", retrying.label)
        assertEquals("Next try in 8 seconds.", retrying.detail)
        assertEquals("Next try in 1 second.", controlStatus(LoadState.Loading, ControlConnection.Reconnecting(1, 1)).detail)
        assertEquals(StatusTone.Bad, controlStatus(LoadState.Loading, ControlConnection.SessionExpired).tone)
        assertEquals("Not set up", controlStatus(LoadState.Loading, ControlConnection.NotPaired).label)
        assertEquals("Open Control to connect.", controlStatus(LoadState.Loading, ControlConnection.Idle).detail)
        assertEquals("Connected", controlStatus(LoadState.Content(Unit), ControlConnection.Idle).label)
    }

    @Test fun refreshChoicesAndLabels() {
        assertEquals(listOf(5, 15, 30, 60, 120), refreshChoices(15))
        assertEquals(listOf(5, 15, 30, 45, 60, 120), refreshChoices(45))
        assertEquals("15 s", refreshLabel(15))
        assertEquals("1 min", refreshLabel(60))
        assertEquals("2 min", refreshLabel(120))
        assertEquals("1 min 30 s", refreshLabel(90))
    }

    @Test fun menuHasMusicSettingsAbout() {
        assertEquals(listOf("Music", "Settings", "About"), MorePage.entries.map { it.title })
    }

    // ---- Music ------------------------------------------------------------------------------

    private val playing = HomeFixtures.players[0]
    private val idle = HomeFixtures.players[1]

    @Test fun capabilitiesGateTransportControls() {
        assertTrue(playing.effective.supports("seek"))
        assertFalse(playing.effective.supports("group"))
        // A player that lists nothing is assumed to manage the basics only.
        assertTrue(idle.effective.supports("pause"))
        assertTrue(idle.effective.supports("set_volume"))
        assertFalse(idle.effective.supports("next"))
        assertFalse(idle.effective.supports("seek"))
        assertFalse(idle.effective.supports("mute"))
    }

    @Test fun durationsAndProgress() {
        assertEquals("0:00", formatDuration(-3.0))
        assertEquals("3:44", formatDuration(224.0))
        assertEquals("1:02:05", formatDuration(3725.0))
        assertEquals(71f to 224f, playbackProgress(playing.effective))
        assertNull(playbackProgress(idle.effective))
        assertNull(playbackProgress(EffectiveMediaState(true, true, "playing", 10, false, null, null, durationSeconds = 0.0)))
    }

    @Test fun nowPlayingText() {
        assertEquals("Weather With You", nowPlayingTitle(playing))
        assertEquals("Crowded House · Woodface", nowPlayingSubtitle(playing))
        assertEquals("Nothing playing", nowPlayingTitle(idle))
        assertEquals("Kitchen speaker", nowPlayingSubtitle(idle))
        val gone = idle.copy(effective = idle.effective.copy(available = false))
        assertEquals("Player unavailable", nowPlayingTitle(gone))
    }

    @Test fun roomPlayerAndRooms() {
        val media = HomeFixtures.snapshot.media
        assertEquals("living-speaker", roomPlayer(media, "living")!!.player.id)
        assertEquals("kitchen-speaker", roomPlayer(media, "kitchen")!!.player.id)
        assertNull(roomPlayer(media, "bedroom"))
        assertNull(roomPlayer(media, null))
        // Rooms with no player are not offered for music.
        assertEquals(listOf("living", "kitchen"), musicRooms(media.rooms).map { it.id })
    }

    @Test fun transferTargetsAreOtherRoomsWithADefaultPlayer() {
        val rooms = HomeFixtures.rooms
        assertEquals(listOf("kitchen"), transferTargets(rooms, playing).map { it.id })
        assertEquals(listOf("living"), transferTargets(rooms, idle).map { it.id })
        val fixed = playing.copy(effective = playing.effective.copy(capabilities = setOf("play", "pause")))
        assertTrue(transferTargets(rooms, fixed).isEmpty())
    }

    @Test fun musicStatePicksTheRoomPlayerQueueAndTargets() {
        val state = buildMusicState(HomeFixtures.snapshot, "living", online = true, ui = MusicUiState())
        assertEquals("Living Room", state.roomName)
        assertEquals("living-speaker", state.player!!.player.id)
        assertEquals(3, state.queue!!.items.size)
        assertEquals(listOf("kitchen"), state.moveTargets.map { it.id })
        assertTrue(state.commandsEnabled)

        // A room without music falls back to the first music room; an empty queue is hidden.
        val fallback = buildMusicState(HomeFixtures.snapshot, "garage", online = false, ui = MusicUiState(busy = true))
        assertEquals("living", fallback.roomId)
        assertFalse(fallback.commandsEnabled)
        assertNull(buildMusicState(HomeFixtures.snapshot, "kitchen", true, MusicUiState()).queue)
    }
}
