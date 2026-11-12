package com.jameshazell.pilot.ui.energy

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.jameshazell.pilot.data.energy.EnergyBootstrap
import com.jameshazell.pilot.ui.components.Chip
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.StatCell
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens
import com.jameshazell.pilot.ui.theme.PilotIcons

/* Small pieces shared by the Energy panes. */

internal fun toneColor(tone: StatusTone): Color = when (tone) {
    StatusTone.Good -> PilotColors.Teal
    StatusTone.Warn -> PilotColors.Amber
    StatusTone.Bad -> PilotColors.Red
}

/** The segmented sub-navigation. Scrolls sideways when the five labels do not fit (closed Fold). */
@Composable
internal fun PaneSelector(selected: EnergyPane, onSelect: (EnergyPane) -> Unit, modifier: Modifier = Modifier) {
    Row(
        modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState())
            .padding(horizontal = PilotDimens.ScreenPadding),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        EnergyPane.entries.forEach { pane ->
            Chip(pane.label, selected = pane == selected, onClick = { onSelect(pane) })
        }
    }
}

/** A card's own title. */
@Composable
internal fun CardTitle(text: String, modifier: Modifier = Modifier) {
    Text(text, style = MaterialTheme.typography.titleMedium, color = PilotColors.Text, modifier = modifier.semantics { heading() })
}

/** "Label ............ value" row. */
@Composable
internal fun InfoLine(label: String, value: String, valueColor: Color = PilotColors.Text) {
    Row(Modifier.fillMaxWidth().semantics(mergeDescendants = true) {}, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = PilotColors.TextDim, modifier = Modifier.weight(1f))
        Text(value, style = MaterialTheme.typography.bodyMedium, color = valueColor, modifier = Modifier.weight(1.3f))
    }
}

/** A coloured dot and one sentence; announced politely when it changes. */
@Composable
internal fun StatusLineRow(line: EnergyStatusLine, modifier: Modifier = Modifier) {
    Row(
        modifier.fillMaxWidth().semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(toneColor(line.tone)))
        Spacer(Modifier.width(8.dp))
        Text(line.text, style = MaterialTheme.typography.bodyMedium, color = PilotColors.TextDim)
    }
}

/** Success or failure feedback after a save or a command. */
@Composable
internal fun NoticeCard(notice: EnergyNotice, modifier: Modifier = Modifier) {
    PilotCard(modifier.semantics { liveRegion = LiveRegionMode.Polite }, tint = if (notice.ok) PilotColors.Teal else PilotColors.Red) {
        Text(
            notice.text,
            style = MaterialTheme.typography.bodyMedium,
            color = if (notice.ok) PilotColors.Text else PilotColors.Red,
        )
    }
}

/** The house scene, the 2×2 summary and the health line: the part that stays visible on the open Fold. */
@Composable
internal fun SceneBlock(bootstrap: EnergyBootstrap, flow: HouseFlowState, saved: Boolean, modifier: Modifier = Modifier) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap)) {
        HouseScene(flow)
        PilotCard {
            Row(horizontalArrangement = Arrangement.spacedBy(PilotDimens.Gap)) {
                val solar = powerReading(flow.solarKw)
                StatCell(
                    PilotIcons.Sun, "Solar", solar.value, Modifier.weight(1f), unit = solar.unit,
                    note = bootstrap.today.solarGeneratedKwh?.let { "${formatKwh(it)} today" },
                    accent = EnergyColors.Solar,
                )
                val house = powerReading(flow.houseKw)
                StatCell(
                    PilotIcons.Home, "House", house.value, Modifier.weight(1f), unit = house.unit,
                    note = bootstrap.today.houseConsumedKwh?.let { "${formatKwh(it)} today" },
                    accent = EnergyColors.House,
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(PilotDimens.Gap)) {
                StatCell(
                    PilotIcons.Battery, "Battery",
                    flow.socPct?.let { "%.0f".format(java.util.Locale.US, it) } ?: UNKNOWN,
                    Modifier.weight(1f),
                    unit = if (flow.socPct != null) "%" else null,
                    note = batteryNote(flow.batteryKw),
                    accent = EnergyColors.Battery,
                )
                val grid = powerReading(flow.gridKw)
                StatCell(
                    PilotIcons.Energy, "Grid", grid.value, Modifier.weight(1f), unit = grid.unit,
                    note = gridNote(flow.gridKw, bootstrap.prices.importPerKwh, bootstrap.prices.feedInPerKwh),
                    accent = EnergyColors.Grid,
                )
            }
        }
        StatusLineRow(energyStatusLine(bootstrap, saved))
    }
}
