package com.jameshazell.pilot.ui.more

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.core.PilotConfig
import com.jameshazell.pilot.data.control.ControlConnection
import com.jameshazell.pilot.data.pilot.MediaCommand
import com.jameshazell.pilot.data.pilot.MusicSearchResult
import com.jameshazell.pilot.ui.home.DetailHeader
import com.jameshazell.pilot.ui.home.HomeFixtures
import com.jameshazell.pilot.ui.home.PreviewFrame
import com.jameshazell.pilot.ui.more.music.MusicActions
import com.jameshazell.pilot.ui.more.music.MusicContent
import com.jameshazell.pilot.ui.more.music.MusicUiState
import com.jameshazell.pilot.ui.more.music.buildMusicState
import com.jameshazell.pilot.ui.more.settings.SettingsActions
import com.jameshazell.pilot.ui.more.settings.SettingsState

private val settings = SettingsState(
    services = listOf(
        pilotStatus(LoadState.Content(HomeFixtures.snapshot), paired = true, liveEvents = true),
        energyStatus(LoadState.Loading),
        controlStatus(LoadState.Loading, ControlConnection.Reconnecting(attempt = 2, retryInSeconds = 4)),
    ),
    config = PilotConfig(coreUrl = "https://pilot.example.ts.net/", deviceId = "phone-fold", refreshSeconds = 15),
    canControlHome = true,
    versionName = "2.0.0",
    versionCode = 11,
)

private val noSettingsActions = object : SettingsActions {
    override fun refresh() = Unit
    override fun setRefreshSeconds(seconds: Int) = Unit
    override fun setKeepScreenOn(enabled: Boolean) = Unit
    override fun requestRepair() = Unit
    override fun requestUnpair() = Unit
}

private val noMusicActions = object : MusicActions {
    override fun selectRoom(roomId: String) = Unit
    override fun setQuery(text: String) = Unit
    override fun search() = Unit
    override fun play(result: MusicSearchResult, playerId: String?) = Unit
    override fun command(command: MediaCommand) = Unit
    override fun dismissError() = Unit
}

@Composable
private fun MusicPreviewPage() {
    Column(Modifier.fillMaxSize()) {
        DetailHeader("Music", onBack = {})
        MusicContent(
            buildMusicState(
                HomeFixtures.snapshot,
                selectedRoomId = "living",
                online = true,
                ui = MusicUiState(
                    query = "crowded house",
                    searchedFor = "crowded house",
                    results = listOf(
                        MusicSearchResult("r1", "Woodface", "Album · Crowded House", "tidal://album/1", "album"),
                        MusicSearchResult("r2", "Don't Dream It's Over", "Track · Crowded House", "tidal://track/2", "track"),
                    ),
                ),
            ),
            noMusicActions,
            artwork = { null },
        )
    }
}

@Composable
private fun MorePreview(page: MorePage?) {
    MoreContent(page, onOpen = {}, onBack = {}, music = { MusicPreviewPage() }, settings = settings, actions = noSettingsActions)
}

@Preview(name = "More · closed Fold", widthDp = 360, heightDp = 780)
@Composable
private fun MoreCompactPreview() = PreviewFrame(360) { MorePreview(null) }

@Preview(name = "Music · closed Fold", widthDp = 360, heightDp = 1300)
@Composable
private fun MusicCompactPreview() = PreviewFrame(360) { MorePreview(MorePage.Music) }

@Preview(name = "Settings · closed Fold", widthDp = 360, heightDp = 1300)
@Composable
private fun SettingsCompactPreview() = PreviewFrame(360) { MorePreview(MorePage.Settings) }

@Preview(name = "More + Music · open Fold", widthDp = 752, heightDp = 1200)
@Composable
private fun MusicMediumPreview() = PreviewFrame(752) { MorePreview(MorePage.Music) }

@Preview(name = "More + Settings · open Fold", widthDp = 752, heightDp = 1200)
@Composable
private fun SettingsMediumPreview() = PreviewFrame(752) { MorePreview(MorePage.Settings) }

@Preview(name = "More + About · open Fold", widthDp = 752, heightDp = 840)
@Composable
private fun AboutMediumPreview() = PreviewFrame(752) { MorePreview(MorePage.About) }
