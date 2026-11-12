package com.jameshazell.pilot.ui.energy

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.jameshazell.pilot.data.energy.EnergyAction
import com.jameshazell.pilot.data.energy.EnergyBootstrap
import com.jameshazell.pilot.ui.components.CardNote
import com.jameshazell.pilot.ui.components.Chip
import com.jameshazell.pilot.ui.components.LevelSlider
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.PillSwitch
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens
import kotlin.math.roundToInt

/**
 * Controls: controller settings edited with typed controls and saved together, and the
 * signed commands. Every command goes through [onRequestAction], which opens the
 * confirmation dialog; nothing here sends anything by itself.
 *
 * @param saved the readings are a cached copy; everything is then read-only.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun ControlsPane(
    bootstrap: EnergyBootstrap,
    saved: Boolean,
    form: SettingsFormState,
    action: ActionState,
    onEdit: ((SettingsDraft) -> SettingsDraft) -> Unit,
    onSave: () -> Unit,
    onDiscard: () -> Unit,
    onRequestAction: (EnergyAction) -> Unit,
) {
    val settings = bootstrap.settings
    val live = !saved
    val commandsEnabled = live && !action.busy

    action.notice?.let { NoticeCard(it) }
    if (!live) {
        PilotCard(tint = PilotColors.Amber) {
            CardNote("Showing saved values. Reconnect to Energy Manager to change settings or send commands.", color = PilotColors.Text)
        }
    }

    PilotCard {
        CardTitle("Master controls")
        SwitchRow(
            title = "Automation",
            detail = when (settings?.controlEnabled) {
                true -> "On · the controller manages the battery and flexible loads"
                false -> "Off · the controller is not sending commands"
                null -> "State unknown"
            },
            checked = settings?.controlEnabled == true,
            enabled = commandsEnabled && settings != null,
            accent = PilotColors.Teal,
            onCheckedChange = { onRequestAction(if (it) EnergyAction.EnableAutomation else EnergyAction.DisableAutomation) },
        )
        SwitchRow(
            title = "Hot water",
            detail = when (settings?.hotWaterEnabled) {
                true -> "Enabled · heats on its normal schedule"
                false -> "Away · not heating"
                null -> "State unknown"
            },
            checked = settings?.hotWaterEnabled == true,
            enabled = commandsEnabled && settings != null,
            accent = EnergyColors.Water,
            onCheckedChange = { onRequestAction(if (it) EnergyAction.HotWaterEnable else EnergyAction.HotWaterAway) },
        )
        CardNote("These ask you to confirm, then to unlock the phone.")
    }

    if (settings == null) {
        PilotCard {
            CardTitle("Settings")
            CardNote("The controller didn't send its settings, so they can't be edited right now.")
        }
    } else {
        val draft = form.edit?.draft ?: settings.toDraft()
        val editable = live && bootstrap.settingsRevision != null && !form.saving
        val dirty = form.edit != null && settingsPatch(form.edit.base, form.edit.draft) != null

        PilotCard {
            CardTitle("Tesla charging")
            LevelSlider(
                label = "Charge limit",
                value = (draft.evChargeLimitPct ?: 50).toFloat(),
                valueText = draft.evChargeLimitPct?.let { "$it%" } ?: UNKNOWN,
                onValueChange = { value -> onEdit { it.copy(evChargeLimitPct = (value / 5).roundToInt() * 5) } },
                range = 50f..100f,
                steps = 9,
                accent = EnergyColors.Car,
                enabled = editable && draft.evChargeLimitPct != null,
            )
            SwitchRow(
                title = "Charge from the grid",
                detail = if (draft.evGridAllowed) "Allowed when solar is not enough" else "Solar and battery only",
                checked = draft.evGridAllowed,
                enabled = editable,
                accent = EnergyColors.Grid,
                onCheckedChange = { allowed -> onEdit { it.copy(evGridAllowed = allowed) } },
            )
            Text("Trip preparation", style = MaterialTheme.typography.bodyMedium, color = PilotColors.TextDim)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                val known = TripProfiles.map { it.first }
                // A profile this app doesn't know yet is still shown, so the picker never lies.
                val options = if (draft.evTripProfile != null && draft.evTripProfile !in known) {
                    TripProfiles + (draft.evTripProfile to tripProfileLabel(draft.evTripProfile))
                } else TripProfiles
                options.forEach { (id, label) ->
                    Chip(
                        label,
                        selected = draft.evTripProfile == id,
                        onClick = { onEdit { it.copy(evTripProfile = id) } },
                        accent = EnergyColors.Car,
                        enabled = editable,
                    )
                }
            }
            val fitTop = sliderCeiling(draft.evFitMaxCents, usual = 20.0, step = 0.5)
            LevelSlider(
                label = "Charge on spare solar when feed-in is at or below",
                value = (draft.evFitMaxCents ?: 0.0).toFloat(),
                valueText = draft.evFitMaxCents?.let(::formatCents) ?: UNKNOWN,
                onValueChange = { value -> onEdit { it.copy(evFitMaxCents = (value * 2).roundToInt() / 2.0) } },
                range = 0f..fitTop,
                steps = (fitTop * 2).roundToInt() - 1,
                accent = EnergyColors.Solar,
                enabled = editable && draft.evFitMaxCents != null,
            )
        }

        PilotCard {
            CardTitle("Selling to the grid")
            val sellTop = sliderCeiling(draft.minSellCents, usual = 50.0, step = 1.0)
            LevelSlider(
                label = "Lowest price to sell battery energy",
                value = (draft.minSellCents ?: 0.0).toFloat(),
                valueText = draft.minSellCents?.let(::formatCents) ?: UNKNOWN,
                onValueChange = { value -> onEdit { it.copy(minSellCents = value.roundToInt().toDouble()) } },
                range = 0f..sellTop,
                steps = sellTop.roundToInt() - 1,
                accent = EnergyColors.Battery,
                enabled = editable && draft.minSellCents != null,
            )
        }

        form.notice?.let { NoticeCard(it) }
        Row(horizontalArrangement = Arrangement.spacedBy(PilotDimens.Gap), verticalAlignment = Alignment.CenterVertically) {
            Button(
                onClick = onSave,
                enabled = dirty && editable,
                colors = ButtonDefaults.buttonColors(containerColor = PilotColors.Violet, contentColor = PilotColors.OnAccent),
            ) { Text(if (form.saving) "Saving…" else "Save changes") }
            if (dirty) {
                TextButton(onClick = onDiscard, enabled = !form.saving) { Text("Discard", color = PilotColors.TextDim) }
            }
        }
    }

    PilotCard {
        CardTitle("Stop now")
        CommandButton("Stop Tesla charging", commandsEnabled, PilotColors.Text) { onRequestAction(EnergyAction.StopEv) }
        CommandButton("Stop hot water", commandsEnabled, PilotColors.Text) { onRequestAction(EnergyAction.StopHotWater) }
        CommandButton("Safe state", commandsEnabled, PilotColors.Red) { onRequestAction(EnergyAction.SafeState) }
        CardNote("Safe state stops forced charging and export and returns the inverter to plain self-consumption.")
    }
}

@Composable
private fun SwitchRow(
    title: String,
    detail: String,
    checked: Boolean,
    enabled: Boolean,
    accent: Color,
    onCheckedChange: (Boolean) -> Unit,
) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(detail, style = MaterialTheme.typography.labelMedium, color = PilotColors.TextDim)
        }
        PillSwitch(checked = checked, onCheckedChange = onCheckedChange, label = title, accent = accent, enabled = enabled)
    }
}

@Composable
private fun CommandButton(label: String, enabled: Boolean, color: Color, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.fillMaxWidth(),
        border = BorderStroke(1.dp, color.copy(alpha = if (enabled) 0.5f else 0.2f)),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = color),
    ) { Text(label) }
}
