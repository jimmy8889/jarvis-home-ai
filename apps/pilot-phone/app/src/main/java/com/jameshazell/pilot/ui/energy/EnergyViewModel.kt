package com.jameshazell.pilot.ui.energy

import android.app.Activity
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jameshazell.pilot.core.AppError
import com.jameshazell.pilot.core.ErrorKind
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.core.Outcome
import com.jameshazell.pilot.data.energy.EnergyAction
import com.jameshazell.pilot.data.energy.EnergyBootstrap
import com.jameshazell.pilot.data.energy.EnergyDay
import com.jameshazell.pilot.data.energy.EnergyRepository
import com.jameshazell.pilot.data.energy.EnergySettings
import com.jameshazell.pilot.data.energy.EnergyTelemetry
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Feedback after a save or a command. [ok] false is a failure the user should read. */
internal data class EnergyNotice(val text: String, val ok: Boolean)

/**
 * The settings form while it differs from the controller.
 *
 * @param base the controller's settings when editing started.
 * @param baseRevision their revision; a save is refused if the controller has moved on from it.
 */
internal data class SettingsEdit(val base: EnergySettings, val baseRevision: String, val draft: SettingsDraft)

internal data class SettingsFormState(
    val edit: SettingsEdit? = null,
    val saving: Boolean = false,
    val notice: EnergyNotice? = null,
)

/**
 * A signed command from "asked" to "done".
 *
 * @param pending the command awaiting confirmation; the ConfirmDialog is shown while non-null.
 * @param busy the challenge / phone unlock / send sequence is running.
 * @param error why the last attempt failed; shown inside the dialog so it can be retried.
 * @param notice the outcome of the last finished command.
 */
internal data class ActionState(
    val pending: EnergyAction? = null,
    val busy: Boolean = false,
    val error: String? = null,
    val notice: EnergyNotice? = null,
)

/**
 * State for the whole Energy destination. Lives as long as the activity, so the selected
 * pane, a half-edited settings form and a pending confirmation all survive folding.
 */
class EnergyViewModel(private val energy: EnergyRepository) : ViewModel() {
    val bootstrap: StateFlow<LoadState<EnergyBootstrap>> = energy.bootstrap
    val history: StateFlow<LoadState<List<EnergyTelemetry>>> = energy.history
    val daily: StateFlow<LoadState<List<EnergyDay>>> = energy.daily

    private val _pane = MutableStateFlow(EnergyPane.Now)
    val pane: StateFlow<EnergyPane> = _pane.asStateFlow()

    private val _settingsForm = MutableStateFlow(SettingsFormState())
    internal val settingsForm: StateFlow<SettingsFormState> = _settingsForm.asStateFlow()

    private val _action = MutableStateFlow(ActionState())
    internal val action: StateFlow<ActionState> = _action.asStateFlow()

    /** Polling follows the screen: call from LifecycleStartEffect. */
    fun onScreenStarted() = energy.start()
    fun onScreenStopped() = energy.stop()

    fun refresh() {
        viewModelScope.launch { energy.refresh() }
    }

    fun selectPane(pane: EnergyPane) {
        _pane.value = pane
    }

    /** History is only fetched while the Solar pane is on screen. */
    fun setHistoryVisible(visible: Boolean) = energy.setHistoryVisible(visible)

    // ------------------------------------------------------------ settings

    /** Applies one control's change to the form, starting an edit from the live settings if needed. */
    internal fun editSettings(change: (SettingsDraft) -> SettingsDraft) {
        _settingsForm.update { form ->
            val edit = form.edit ?: startEdit() ?: return@update form
            form.copy(edit = edit.copy(draft = change(edit.draft)), notice = null)
        }
    }

    internal fun discardSettings() {
        _settingsForm.update { it.copy(edit = null, notice = null) }
    }

    internal fun saveSettings() {
        val edit = _settingsForm.value.edit ?: return
        if (_settingsForm.value.saving) return
        val patch = settingsPatch(edit.base, edit.draft)
        if (patch == null) {
            discardSettings()
            return
        }
        val current = liveBootstrap()
        if (current == null) {
            _settingsForm.update {
                it.copy(notice = EnergyNotice("Reconnect to Energy Manager before changing settings.", ok = false))
            }
            return
        }
        // Someone else changed the settings while this form was open: never overwrite blindly.
        if (current.settingsRevision != edit.baseRevision) {
            conflict()
            return
        }
        _settingsForm.update { it.copy(saving = true, notice = null) }
        viewModelScope.launch {
            when (val outcome = energy.updateSettings(patch)) {
                is Outcome.Success ->
                    _settingsForm.value = SettingsFormState(notice = EnergyNotice("Settings saved.", ok = true))
                is Outcome.Failure -> {
                    if (outcome.error.status == 409) {
                        energy.refresh()
                        conflict()
                    } else {
                        _settingsForm.update {
                            it.copy(saving = false, notice = EnergyNotice(outcome.error.message, ok = false))
                        }
                    }
                }
            }
        }
    }

    private fun conflict() {
        _settingsForm.value = SettingsFormState(
            notice = EnergyNotice(
                "These settings were changed somewhere else. The latest values are shown; make your change again.",
                ok = false,
            ),
        )
    }

    private fun liveBootstrap(): EnergyBootstrap? =
        (bootstrap.value as? LoadState.Content)?.takeIf { !it.stale }?.value

    private fun startEdit(): SettingsEdit? {
        val current = liveBootstrap() ?: return null
        val settings = current.settings ?: return null
        val revision = current.settingsRevision ?: return null
        return SettingsEdit(settings, revision, settings.toDraft())
    }

    // ------------------------------------------------------------ signed actions

    /** Step 1: ask. Shows the confirmation dialog. */
    internal fun requestAction(action: EnergyAction) {
        if (_action.value.busy) return
        _action.value = ActionState(pending = action)
    }

    internal fun cancelAction() {
        if (_action.value.busy) return
        _action.update { it.copy(pending = null, error = null) }
    }

    /** Step 2: confirmed. The system unlock prompt appears over [activity]; then the command is sent. */
    internal fun confirmAction(activity: Activity) {
        val action = _action.value.pending ?: return
        if (_action.value.busy) return
        _action.update { it.copy(busy = true, error = null) }
        viewModelScope.launch {
            when (val outcome = energy.runAction(activity, action)) {
                is Outcome.Success ->
                    _action.value = ActionState(notice = EnergyNotice(actionCopy(action).success, ok = true))
                is Outcome.Failure ->
                    _action.update { it.copy(busy = false, error = actionFailure(outcome.error)) }
            }
        }
    }
}

/** Every failure says plainly whether anything was sent. */
internal fun actionFailure(error: AppError): String = when (error.kind) {
    ErrorKind.AuthCancelled, ErrorKind.Security, ErrorKind.NotPaired, ErrorKind.Invalid -> error.message
    ErrorKind.Timeout -> "${error.message} The command may not have been applied; check the readings before trying again."
    else -> "${error.message} The command was not confirmed."
}
