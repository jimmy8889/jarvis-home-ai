package com.jameshazell.pilot.ui.energy

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.jameshazell.pilot.core.humanLabel
import com.jameshazell.pilot.data.energy.EnergyBootstrap
import com.jameshazell.pilot.data.energy.EnergyHealth
import com.jameshazell.pilot.ui.components.CardNote
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.StatCell
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens
import com.jameshazell.pilot.ui.theme.PilotIcons

/** The cards under (closed Fold) or beside (open Fold) the house scene. */
@Composable
internal fun NowDetails(bootstrap: EnergyBootstrap, flow: HouseFlowState) {
    val devices = bootstrap.devices

    PilotCard {
        CardTitle("Controller")
        Text(
            bootstrap.decision.mode?.let(::humanLabel) ?: "Waiting for the controller's decision",
            style = MaterialTheme.typography.titleLarge,
        )
        bootstrap.decision.reason?.let { CardNote(humanLabel(it)) }
        bootstrap.narrative.currentSummary?.let { InfoLine("Plan", it) }
        bootstrap.decision.phase?.let { InfoLine("Inverter command", humanLabel(it)) }
        bootstrap.householdFloorPct?.let { InfoLine("Household reserve", formatPercent(it)) }
        bootstrap.batteryStoredKwh?.let { InfoLine("Battery stored", formatKwh(it)) }
        bootstrap.fault?.let { CardNote(it, color = PilotColors.Red) }
    }

    PilotCard {
        CardTitle("Tesla")
        // Three separate facts: where the car is, whether the cable is in, whether power flows.
        InfoLine("Battery", formatPercent(devices.evSocPct))
        InfoLine(
            "Presence",
            when (flow.carHome) {
                true -> "At home"
                false -> "Away"
                null -> "Unknown"
            },
        )
        InfoLine(
            "Cable",
            when (flow.carPlugged) {
                true -> "Connected"
                false -> "Unplugged"
                null -> "Unknown"
            },
        )
        InfoLine(
            "Charging",
            when {
                carFlowActive(flow) -> formatPower(flow.carKw)
                flow.carCharging == null -> "Unknown"
                else -> "Not charging"
            },
            valueColor = if (carFlowActive(flow)) EnergyColors.Car else PilotColors.Text,
        )
    }

    PilotCard {
        CardTitle("Hot water")
        Text(EnergyHealth.hotWater(bootstrap.snapshot), style = MaterialTheme.typography.titleLarge, color = EnergyColors.Water)
        CardNote(EnergyHealth.confirmedMinutes(bootstrap.snapshot))
        devices.hotWaterSource?.let { InfoLine("Source", humanLabel(it)) }
    }

    PilotCard {
        CardTitle("Today")
        Row(horizontalArrangement = Arrangement.spacedBy(PilotDimens.Gap)) {
            val today = bootstrap.today
            StatCell(PilotIcons.Sun, "Generated", today.solarGeneratedKwh.kwhValue(), Modifier.weight(1f), unit = today.solarGeneratedKwh.kwhUnit(), accent = EnergyColors.Solar)
            StatCell(PilotIcons.Home, "Used", today.houseConsumedKwh.kwhValue(), Modifier.weight(1f), unit = today.houseConsumedKwh.kwhUnit(), accent = EnergyColors.House)
            StatCell(PilotIcons.Energy, "Exported", today.gridExportedKwh.kwhValue(), Modifier.weight(1f), unit = today.gridExportedKwh.kwhUnit(), accent = EnergyColors.Grid)
        }
    }

    PilotCard {
        CardTitle("Controller confidence")
        val fresh = flow.fresh
        InfoLine("Telemetry", if (fresh) "Fresh" else "Unavailable or stale", if (fresh) PilotColors.Teal else PilotColors.Amber)
        InfoLine("Forecast sources", bootstrap.forecast.providers.joinToString(" + ").ifBlank { UNKNOWN })
        bootstrap.gridHealth?.let { InfoLine("Grid", humanLabel(it)) }
        CardNote(EnergyHealth.purchase(bootstrap.snapshot))
    }
}

internal fun Double?.kwhValue(): String = this?.takeIf(Double::isFinite)?.let { "%.1f".format(java.util.Locale.US, it) } ?: UNKNOWN
internal fun Double?.kwhUnit(): String? = this?.takeIf(Double::isFinite)?.let { "kWh" }
