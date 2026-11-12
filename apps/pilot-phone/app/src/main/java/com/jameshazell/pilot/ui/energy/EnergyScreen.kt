package com.jameshazell.pilot.ui.energy

import androidx.activity.compose.LocalActivity
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.movableContentOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LifecycleStartEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.data.energy.EnergyAction
import com.jameshazell.pilot.data.energy.EnergyBootstrap
import com.jameshazell.pilot.data.energy.EnergyDay
import com.jameshazell.pilot.data.energy.EnergyTelemetry
import com.jameshazell.pilot.ui.adaptive.ListDetailLayout
import com.jameshazell.pilot.ui.adaptive.LocalPilotWindow
import com.jameshazell.pilot.ui.appViewModel
import com.jameshazell.pilot.ui.components.ConfirmDialog
import com.jameshazell.pilot.ui.components.ScreenHeader
import com.jameshazell.pilot.ui.components.StateScaffold
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens

/**
 * Energy: one destination with five panes (Now, Plan, Solar, UPS & rack, Controls).
 *
 * Closed Fold: one column; the pane selector scrolls sideways. Open Fold: the house scene and
 * its summary stay on the left while the selected pane shows on the right.
 */
@Composable
fun EnergyScreen() {
    val model = appViewModel { EnergyViewModel(it.energy) }
    val bootstrap by model.bootstrap.collectAsStateWithLifecycle()
    val history by model.history.collectAsStateWithLifecycle()
    val daily by model.daily.collectAsStateWithLifecycle()
    val pane by model.pane.collectAsStateWithLifecycle()
    val settingsForm by model.settingsForm.collectAsStateWithLifecycle()
    val action by model.action.collectAsStateWithLifecycle()
    val activity = LocalActivity.current

    LifecycleStartEffect(model) {
        model.onScreenStarted()
        onStopOrDispose { model.onScreenStopped() }
    }

    val callbacks = remember(model, activity) {
        EnergyCallbacks(
            onSelectPane = model::selectPane,
            onRefresh = model::refresh,
            onHistoryVisible = model::setHistoryVisible,
            onEditSettings = model::editSettings,
            onSaveSettings = model::saveSettings,
            onDiscardSettings = model::discardSettings,
            onRequestAction = model::requestAction,
            onCancelAction = model::cancelAction,
            onConfirmAction = { activity?.let(model::confirmAction) },
        )
    }

    Column(Modifier.fillMaxSize()) {
        ScreenHeader(
            title = "Energy",
            status = energyStatus(bootstrap),
            statusColor = if (bootstrap.isLive) PilotColors.Teal else PilotColors.TextDim,
        )
        StateScaffold(bootstrap, onRetry = model::refresh, loadingLabel = "Connecting to Energy Manager…") { value ->
            EnergyContent(
                EnergyUi(
                    bootstrap = value,
                    saved = (bootstrap as? LoadState.Content)?.stale == true,
                    pane = pane,
                    history = history,
                    daily = daily,
                    settingsForm = settingsForm,
                    action = action,
                ),
                callbacks,
            )
        }
    }
}

/**
 * Everything the Energy panes draw from.
 *
 * @param saved [bootstrap] is a cached copy: nothing animates and nothing can be changed.
 */
internal data class EnergyUi(
    val bootstrap: EnergyBootstrap,
    val saved: Boolean,
    val pane: EnergyPane,
    val history: LoadState<List<EnergyTelemetry>>,
    val daily: LoadState<List<EnergyDay>>,
    val settingsForm: SettingsFormState = SettingsFormState(),
    val action: ActionState = ActionState(),
)

internal class EnergyCallbacks(
    val onSelectPane: (EnergyPane) -> Unit = {},
    val onRefresh: () -> Unit = {},
    val onHistoryVisible: (Boolean) -> Unit = {},
    val onEditSettings: ((SettingsDraft) -> SettingsDraft) -> Unit = {},
    val onSaveSettings: () -> Unit = {},
    val onDiscardSettings: () -> Unit = {},
    val onRequestAction: (EnergyAction) -> Unit = {},
    val onCancelAction: () -> Unit = {},
    val onConfirmAction: () -> Unit = {},
)

/** The Energy pages for loaded data. Stateless, so previews can drive it with fixtures. */
@Composable
internal fun EnergyContent(ui: EnergyUi, on: EnergyCallbacks, modifier: Modifier = Modifier) {
    val twoPane = LocalPilotWindow.current.isTwoPane
    val flow = remember(ui.bootstrap, ui.saved) { liveFlowState(ui.bootstrap, live = !ui.saved) }

    // The selected pane is one movable composition, so its scroll position and the plan
    // scrubber survive the move between the one-column and two-pane layouts (fold / unfold).
    val currentUi by rememberUpdatedState(ui)
    val currentFlow by rememberUpdatedState(flow)
    val currentOn by rememberUpdatedState(on)
    val paneBody = remember {
        movableContentOf { withScene: Boolean -> PaneBody(currentUi, currentFlow, currentOn, withScene) }
    }

    if (!twoPane) {
        Column(modifier.fillMaxSize()) {
            PaneSelector(ui.pane, on.onSelectPane)
            Box(Modifier.weight(1f).fillMaxWidth()) { paneBody(true) }
        }
    } else {
        ListDetailLayout(
            hasDetail = true,
            onBack = {},
            modifier = modifier,
            listFraction = 0.46f,
            paneGap = 0.dp,
            list = {
                SceneBlock(
                    ui.bootstrap,
                    flow,
                    ui.saved,
                    Modifier
                        .fillMaxSize()
                        .verticalScroll(rememberScrollState())
                        .padding(start = PilotDimens.ScreenPadding, top = 4.dp, bottom = PilotDimens.ScreenPadding),
                )
            },
            detail = {
                Column(Modifier.fillMaxSize()) {
                    PaneSelector(ui.pane, on.onSelectPane)
                    Box(Modifier.weight(1f).fillMaxWidth()) { paneBody(false) }
                }
            },
        )
    }

    ui.action.pending?.let { pending ->
        val copy = actionCopy(pending)
        ConfirmDialog(
            title = copy.title,
            message = "${copy.message}\n\nYou'll be asked to unlock the phone before it is sent.",
            confirmLabel = copy.confirmLabel,
            onConfirm = on.onConfirmAction,
            onDismiss = on.onCancelAction,
            destructive = copy.destructive,
            busy = ui.action.busy,
            error = ui.action.error,
        )
    }
}

/**
 * The scrolling body of the selected pane.
 *
 * @param withScene one-column layout: the Now pane then starts with the house scene. In the
 * two-pane layout the scene is already on the left, so Now shows only its detail cards.
 */
@Composable
private fun PaneBody(ui: EnergyUi, flow: HouseFlowState, on: EnergyCallbacks, withScene: Boolean) {
    val holder = rememberSaveableStateHolder()
    // Each pane keeps its own scroll position while another one is shown.
    holder.SaveableStateProvider(ui.pane.name) {
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(PaddingValues(start = PilotDimens.ScreenPadding, end = PilotDimens.ScreenPadding, top = 4.dp, bottom = PilotDimens.ScreenPadding)),
            verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap),
        ) {
            when (ui.pane) {
                EnergyPane.Now -> {
                    if (withScene) SceneBlock(ui.bootstrap, flow, ui.saved)
                    NowDetails(ui.bootstrap, flow)
                }
                EnergyPane.Plan -> PlanPane(ui.bootstrap)
                EnergyPane.Solar -> SolarPane(ui.bootstrap, ui.history, ui.daily, on.onHistoryVisible, on.onRefresh)
                EnergyPane.Ups -> UpsPane(ui.bootstrap, ui.saved)
                EnergyPane.Controls -> ControlsPane(
                    bootstrap = ui.bootstrap,
                    saved = ui.saved,
                    form = ui.settingsForm,
                    action = ui.action,
                    onEdit = on.onEditSettings,
                    onSave = on.onSaveSettings,
                    onDiscard = on.onDiscardSettings,
                    onRequestAction = on.onRequestAction,
                )
            }
        }
    }
}

internal fun energyStatus(state: LoadState<EnergyBootstrap>): String = when (state) {
    is LoadState.Loading -> "Connecting"
    is LoadState.Error -> "Offline"
    is LoadState.Content -> when {
        state.stale -> "Saved"
        state.value.telemetryFresh() -> "Live"
        else -> "Connected · controller readings are stale"
    }
}
