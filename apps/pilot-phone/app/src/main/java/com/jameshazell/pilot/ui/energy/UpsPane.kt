package com.jameshazell.pilot.ui.energy

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.unit.dp
import com.jameshazell.pilot.data.energy.EnergyBootstrap
import com.jameshazell.pilot.ui.components.CardNote
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.StatCell
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens
import com.jameshazell.pilot.ui.theme.PilotIcons

/** UPS & rack: supply status, battery charge and runtime, load and where the power goes. */
@Composable
internal fun UpsPane(bootstrap: EnergyBootstrap, saved: Boolean) {
    val ups = remember(bootstrap) { upsView(bootstrap) }
    val tone = toneColor(ups.status.tone)

    PilotCard(tint = tone.takeIf { ups.status.tone != StatusTone.Good }) {
        CardTitle("UPS")
        Text(ups.status.headline, style = MaterialTheme.typography.titleLarge, color = tone)
        ups.status.notes.forEach { CardNote(it) }
        if (saved) CardNote("A saved reading: the UPS may have changed since.", color = PilotColors.Amber)
    }

    PilotCard {
        Row(horizontalArrangement = Arrangement.spacedBy(PilotDimens.Gap)) {
            StatCell(
                PilotIcons.Battery, "Charge",
                ups.chargePct?.let { "%.0f".format(java.util.Locale.US, it) } ?: UNKNOWN,
                Modifier.weight(1f),
                unit = ups.chargePct?.let { "%" },
                accent = EnergyColors.Battery,
            )
            StatCell(
                PilotIcons.Power, "Runtime", formatRuntime(ups.runtimeSeconds), Modifier.weight(1f),
                note = "At the current load",
                accent = EnergyColors.Battery,
            )
        }
        Box(
            Modifier
                .fillMaxWidth()
                .height(6.dp)
                .clip(RoundedCornerShape(3.dp))
                .background(PilotColors.PanelRaised)
                .clearAndSetSemantics {},
        ) {
            ups.chargePct?.let {
                Box(Modifier.fillMaxWidth((it / 100).toFloat().coerceIn(0f, 1f)).fillMaxHeight().background(EnergyColors.Battery))
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(PilotDimens.Gap)) {
            val load = ups.loadPct
            val output = powerReading(ups.protectedOutputW?.div(1000))
            StatCell(
                PilotIcons.Energy, "Load",
                load?.let { "%.0f".format(java.util.Locale.US, it) } ?: output.value,
                Modifier.weight(1f),
                unit = if (load != null) "%" else output.unit,
                note = if (load != null) ups.protectedOutputW?.let { "${formatWatts(it)} protected output" } else "Protected output",
                accent = EnergyColors.House,
            )
            val rack = powerReading(ups.rackOutputW?.div(1000))
            StatCell(
                PilotIcons.Control, "Rack power", rack.value, Modifier.weight(1f), unit = rack.unit,
                note = ups.energyTodayKwh?.let { "${formatKwh(it)} today" },
                accent = EnergyColors.Grid,
            )
        }
    }

    PilotCard {
        CardTitle("Where the power goes")
        InfoLine("From the wall", formatWatts(ups.wallInputW))
        InfoLine("Server rack", formatWatts(ups.rackOutputW))
        InfoLine("Office desk", formatWatts(ups.officeOutputW))
        InfoLine("Conversion loss", formatWatts(ups.conversionLossW))
        InfoLine("Input voltage", formatVolts(ups.inputVoltageV))
        InfoLine("Output voltage", formatVolts(ups.outputVoltageV))
        InfoLine("Energy today", formatKwh(ups.energyTodayKwh))
        CardNote("Runtime is the UPS's own estimate. Battery discharge power is not measured separately.")
    }
}
