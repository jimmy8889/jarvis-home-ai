package com.jameshazell.pilot.ui.more

import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.jameshazell.pilot.BuildConfig
import com.jameshazell.pilot.data.pilot.PilotRepository
import com.jameshazell.pilot.ui.adaptive.ListDetailLayout
import com.jameshazell.pilot.ui.appViewModel
import com.jameshazell.pilot.ui.components.ConfirmDialog
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.ScreenHeader
import com.jameshazell.pilot.ui.home.ControlRow
import com.jameshazell.pilot.ui.home.EmptyDetail
import com.jameshazell.pilot.ui.home.HomeIcons
import com.jameshazell.pilot.ui.more.music.MusicScreen
import com.jameshazell.pilot.ui.more.settings.AboutPage
import com.jameshazell.pilot.ui.more.settings.SettingsActions
import com.jameshazell.pilot.ui.more.settings.SettingsPage
import com.jameshazell.pilot.ui.more.settings.SettingsState
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens
import com.jameshazell.pilot.ui.theme.PilotIcons

/** More: Music, Settings and About. A menu with the chosen page beside it (open Fold) or over it. */
@Composable
fun MoreScreen() {
    val model = appViewModel { MoreViewModel(it.pilot, it.energy, it.control) }
    val page by model.page.collectAsStateWithLifecycle()
    val session by model.session.collectAsStateWithLifecycle()
    val snapshot by model.snapshot.collectAsStateWithLifecycle()
    val manifest by model.manifest.collectAsStateWithLifecycle()
    val liveEvents by model.liveEvents.collectAsStateWithLifecycle()
    val energy by model.energyBootstrap.collectAsStateWithLifecycle()
    val controlOverview by model.controlOverview.collectAsStateWithLifecycle()
    val controlConnection by model.controlConnection.collectAsStateWithLifecycle()
    // Which confirmation is showing: "repair", "unpair" or none.
    var confirm by rememberSaveable { mutableStateOf<String?>(null) }

    val settings = SettingsState(
        services = listOf(
            pilotStatus(snapshot, session.paired, liveEvents),
            energyStatus(energy),
            controlStatus(controlOverview, controlConnection),
        ),
        config = session.config,
        canControlHome = manifest?.features?.contains(PilotRepository.FEATURE_HOME_CONTROL) == true,
        versionName = BuildConfig.VERSION_NAME,
        versionCode = BuildConfig.VERSION_CODE,
    )
    val actions = object : SettingsActions {
        override fun refresh() = model.refresh()
        override fun setRefreshSeconds(seconds: Int) = model.setRefreshSeconds(seconds)
        override fun setKeepScreenOn(enabled: Boolean) = model.setKeepScreenOn(enabled)
        override fun requestRepair() { confirm = "repair" }
        override fun requestUnpair() { confirm = "unpair" }
    }

    MoreContent(
        page = page,
        onOpen = model::open,
        onBack = model::close,
        music = { MusicScreen(onBack = model::close) },
        settings = settings,
        actions = actions,
    )

    when (confirm) {
        "repair" -> ConfirmDialog(
            title = "Pair this phone again?",
            message = "This phone's Pilot Core identity is removed first. You'll need a new pairing grant from Pilot Core to finish.",
            confirmLabel = "Remove and pair again",
            destructive = true,
            onConfirm = {
                confirm = null
                model.unpair()
            },
            onDismiss = { confirm = null },
        )
        "unpair" -> ConfirmDialog(
            title = "Unpair this phone?",
            message = "You'll need a new pairing grant from Pilot Core to use Home and Pilot again.",
            confirmLabel = "Unpair",
            destructive = true,
            onConfirm = {
                confirm = null
                model.unpair()
            },
            onDismiss = { confirm = null },
        )
    }
}

/** Stateless More. [music] is a slot because the Music page has its own view model. */
@Composable
fun MoreContent(
    page: MorePage?,
    onOpen: (MorePage) -> Unit,
    onBack: () -> Unit,
    music: @Composable () -> Unit,
    settings: SettingsState,
    actions: SettingsActions,
) {
    ListDetailLayout(
        hasDetail = page != null,
        onBack = onBack,
        list = { MoreMenu(page, onOpen, settings) },
        detail = {
            when (page) {
                MorePage.Music -> music()
                MorePage.Settings -> SettingsPage(settings, actions, onBack)
                MorePage.About -> AboutPage(settings, onBack)
                null -> Unit
            }
        },
        emptyDetail = {
            EmptyDetail("Choose an item", "Music, settings and app information open here.", PilotIcons.More)
        },
    )
}

@Composable
private fun MoreMenu(selected: MorePage?, onOpen: (MorePage) -> Unit, settings: SettingsState) {
    Column(Modifier.fillMaxSize()) {
        ScreenHeader(title = "More", status = "Pilot ${settings.versionName}")
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(PilotDimens.ScreenPadding),
            verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap),
        ) {
            MorePage.entries.forEach { page ->
                val shape = RoundedCornerShape(PilotDimens.CardRadius)
                PilotCard(
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(if (page == selected) Modifier.border(2.dp, PilotColors.Violet, shape) else Modifier),
                    onClick = { onOpen(page) },
                ) {
                    ControlRow(
                        title = page.title,
                        subtitle = page.summary,
                        icon = page.icon,
                        iconTint = PilotColors.Violet,
                    ) {
                        Icon(HomeIcons.ChevronRight, contentDescription = null, tint = PilotColors.TextFaint, modifier = Modifier.size(22.dp))
                    }
                }
            }
        }
    }
}

private val MorePage.icon: ImageVector
    get() = when (this) {
        MorePage.Music -> HomeIcons.Music
        MorePage.Settings -> HomeIcons.Settings
        MorePage.About -> HomeIcons.Info
    }
