package com.jameshazell.pilot.ui.energy

import com.jameshazell.pilot.core.AppError
import com.jameshazell.pilot.core.ErrorKind
import com.jameshazell.pilot.data.energy.EnergyAction
import com.jameshazell.pilot.data.energy.EnergyBootstrap
import com.jameshazell.pilot.data.energy.EnergyJson
import com.jameshazell.pilot.data.energy.EnergySettings
import com.jameshazell.pilot.data.energy.EnergySettingsPatch
import com.jameshazell.pilot.fieldNames
import java.time.Instant
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class EnergyPaneModelsTest {
    private val now = Instant.parse("2026-11-12T02:00:00Z")
    private val fixture = EnergyFixtures.bootstrap(measuredAt = now.minusSeconds(1))

    private fun bootstrap(json: String): EnergyBootstrap = EnergyJson.bootstrap(JSONObject(json))

    // ------------------------------------------------------------ status line

    @Test fun statusLineSaysLiveWithTheDecisionAndGridState() {
        val line = energyStatusLine(fixture, saved = false, now = now)
        assertEquals("Live · Self consume · Grid normal", line.text)
        assertEquals(StatusTone.Good, line.tone)
    }

    @Test fun savedReadingsOutrankEverythingElse() {
        val line = energyStatusLine(fixture, saved = true, now = now)
        assertEquals(StatusTone.Warn, line.tone)
        assertTrue(line.text.startsWith("Saved readings"))
    }

    @Test fun controllerFaultsAreShownBeforeStaleness() {
        val faulty = bootstrap(
            """{"snapshot":{"telemetry":{"healthy":true,"measured_at":"2026-11-12T01:00:00Z"},
                "service":{"workers":{"healthy":false}}}}""",
        )
        val line = energyStatusLine(faulty, saved = false, now = now)
        assertEquals(StatusTone.Bad, line.tone)
        assertEquals("A manager worker needs attention", line.text)
    }

    @Test fun oldTelemetryIsCalledStaleNotLive() {
        val line = energyStatusLine(fixture, saved = false, now = now.plusSeconds(120))
        assertEquals(StatusTone.Warn, line.tone)
        assertTrue(line.text.contains("stale"))
        assertEquals(StatusTone.Warn, energyStatusLine(bootstrap("{}"), saved = false, now = now).tone)
    }

    @Test fun batteryAndGridNotesCarryDirectionAndTheRightPrice() {
        assertEquals("Charging · 1.7 kW", batteryNote(-1.7))
        assertEquals("Discharging · 850 W", batteryNote(0.85))
        assertEquals("Idle", batteryNote(0.05))
        assertEquals("Unavailable", batteryNote(null))
        assertEquals("Importing · 28.5 c/kWh", gridNote(1.2, importPerKwh = 0.285, feedInPerKwh = 0.082))
        assertEquals("Exporting · 8.2 c/kWh", gridNote(-1.2, importPerKwh = 0.285, feedInPerKwh = 0.082))
        assertEquals("Exporting", gridNote(-1.2, importPerKwh = 0.285, feedInPerKwh = null))
        assertEquals("Idle", gridNote(0.0, 0.285, 0.082))
    }

    // ------------------------------------------------------------ plan

    @Test fun planActionsKeepTheControllersOrderAndReasons() {
        val actions = planActions(fixture)
        assertEquals(listOf("Charge EV toward 80%", "Export profitable energy"), actions.map { it.title })
        assertEquals("Now", actions[0].group)
        assertEquals(Instant.parse("2026-11-12T07:30:00Z"), actions[1].start)
        assertTrue(actions[1].reason!!.startsWith("FIT clears"))
        assertEquals("Thu 5:30 PM – 7:00 PM", planActionWhen(actions[1]))
    }

    @Test fun untitledOrMissingActionsAreDropped() {
        assertTrue(planActions(bootstrap("{}")).isEmpty())
        val actions = planActions(
            bootstrap("""{"plan":{"rolling":{"narrative":{"next_actions":[{"start":"2026-11-12T05:00:00Z"},{"title":"Run hot water","group":"Next"}]}}}}"""),
        )
        assertEquals(1, actions.size)
        assertEquals("Next", planActionWhen(actions.single()))
        assertNull(actions.single().reason)
    }

    @Test fun planNotesComeInAFixedOrder() {
        assertEquals(2, planNotes(fixture).size)
        assertTrue(planNotes(fixture).first().startsWith("Solar serves"))
        assertTrue(planNotes(bootstrap("{}")).isEmpty())
    }

    @Test fun tariffHighlightsFindCheapestImportAndBestFeedIn() {
        val data = bootstrap(
            """{"plan":{"rolling":{"points":[
                {"start":"2026-11-12T02:00:00Z","import_per_kwh":0.30,"fit_per_kwh":0.05},
                {"start":"2026-11-12T02:05:00Z","import_per_kwh":0.12,"fit_per_kwh":-0.02},
                {"start":"2026-11-12T02:10:00Z","fit_per_kwh":0.21},
                {"start":"2026-11-12T02:15:00Z"}]}}}""",
        )
        val highlights = tariffHighlights(data.plan)
        assertEquals(0.12, highlights.cheapestImport!!.perKwh, 0.0)
        assertEquals(Instant.parse("2026-11-12T02:05:00Z"), highlights.cheapestImport.at)
        assertEquals(0.21, highlights.bestFeedIn!!.perKwh, 0.0)
        assertNull(tariffHighlights(emptyList()).cheapestImport)
        assertNull(tariffHighlights(data.plan.takeLast(1)).bestFeedIn)
        assertEquals(28.5, cents(0.285)!!, 1e-9)
        assertNull(cents(null))
    }

    // ------------------------------------------------------------ charts

    @Test fun inactiveSamplesSplitSeriesInsteadOfDrawingRamps() {
        val values = listOf(0.0, -0.12, -7.2, -0.03, -6.5, 0.0)
        assertEquals(listOf(1..2, 4..4), chartSegments(values, activityThreshold = 0.1))
        assertEquals(listOf(0..5), chartSegments(values))
    }

    @Test fun unknownSamplesBreakTheLineRatherThanDroppingToZero() {
        assertEquals(listOf(0..1, 3..3), chartSegments(listOf(1.0, 2.0, null, 3.0)))
        assertEquals(listOf(1..1), chartSegments(listOf(Double.NaN, 2.0, null)))
        assertTrue(chartSegments(emptyList()).isEmpty())
        assertTrue(chartSegments(listOf(null, null)).isEmpty())
    }

    @Test fun chartBoundsIncludeZeroAndNeverCollapse() {
        assertEquals(0.0..9.5, chartBounds(listOf(listOf(2.0, 9.5, null), listOf(1.0))))
        assertEquals(-3.0..4.0, chartBounds(listOf(listOf(-3.0, 4.0))))
        assertEquals(0.0..1.0, chartBounds(listOf(listOf(0.2, 0.4))))
        assertEquals(0.0..1.0, chartBounds(emptyList()))
        assertEquals(-5.0..0.0, chartBounds(listOf(listOf(-5.0))))
        assertEquals(-0.5..0.5, chartBounds(listOf(listOf(-0.5))))
    }

    @Test fun totalsOfNothingAreUnknownNotZero() {
        assertNull(knownTotal(listOf(null, null)))
        assertEquals(3.5, knownTotal(listOf(1.5, null, 2.0))!!, 0.0)
        assertEquals("—", formatKwh(knownTotal(emptyList())))
    }

    @Test fun axisLabelsAreSpreadFromFirstToLast() {
        assertEquals(listOf("0", "3", "6", "9"), spreadLabels((0..9).toList()) { it.toString() })
        assertEquals(listOf("0", "2"), spreadLabels(listOf(0, 1, 2)) { it.toString() })
        assertEquals(listOf("7"), spreadLabels(listOf(7)) { it.toString() })
        assertTrue(spreadLabels(emptyList<Int>()) { it.toString() }.isEmpty())
    }

    // ------------------------------------------------------------ UPS

    @Test fun upsStatusFlagsBecomeWords() {
        val mains = upsStatus(available = true, status = "OL CHRG")
        assertEquals("On mains power", mains.headline)
        assertEquals(StatusTone.Good, mains.tone)
        assertEquals(listOf("Battery charging"), mains.notes)
        assertFalse(mains.onBattery)

        val battery = upsStatus(available = true, status = "OB DISCHRG")
        assertTrue(battery.onBattery)
        assertEquals(StatusTone.Warn, battery.tone)
        assertTrue(battery.headline.startsWith("On battery"))
        assertTrue(battery.notes.isEmpty())

        val low = upsStatus(available = true, status = "OB LB")
        assertEquals(StatusTone.Bad, low.tone)
        assertEquals(listOf("Battery low"), low.notes)

        assertEquals(StatusTone.Warn, upsStatus(available = true, status = "OL RB").tone)
        assertEquals("Connected", upsStatus(available = true, status = null).headline)
    }

    @Test fun unavailableUpsNeverClaimsMainsPower() {
        val status = upsStatus(available = false, status = "OL")
        assertEquals("UPS readings unavailable", status.headline)
        assertEquals(StatusTone.Warn, status.tone)
    }

    @Test fun upsViewReadsWhatTheSnapshotCarriesAndLeavesTheRestUnknown() {
        val full = upsView(fixture)
        assertEquals(96.0, full.chargePct!!, 0.0)
        assertEquals(1560.0, full.runtimeSeconds!!, 0.0)
        assertEquals(21.0, full.loadPct!!, 0.0)
        assertEquals(214.0, full.rackOutputW!!, 0.0)
        assertEquals(275.0, full.protectedOutputW!!, 0.0)
        assertEquals(230.0, full.outputVoltageV!!, 0.0)
        assertEquals("26 min", formatRuntime(full.runtimeSeconds))

        val sparse = upsView(bootstrap("""{"snapshot":{"server_rack":{"available":true,"status":"OL","wall_input_w":300}}}"""))
        assertEquals(300.0, sparse.wallInputW!!, 0.0)
        assertNull(sparse.chargePct)
        assertNull(sparse.loadPct)
        assertNull(sparse.runtimeSeconds)
        assertEquals("—", formatRuntime(sparse.runtimeSeconds))
        assertEquals("—", formatWatts(sparse.rackOutputW))
    }

    // ------------------------------------------------------------ settings

    private val settings = EnergySettings(
        controlEnabled = true, hotWaterEnabled = true, evChargeLimitPct = 80, minSellPricePerKwh = 0.12,
        evOpportunisticFitMaxPerKwh = 0.01, evGridAllowed = false, evTripProfile = "no_trip",
    )

    @Test fun draftShowsPricesInCents() {
        val draft = settings.toDraft()
        assertEquals(12.0, draft.minSellCents!!, 0.0)
        assertEquals(1.0, draft.evFitMaxCents!!, 0.0)
        assertEquals(80, draft.evChargeLimitPct)
        assertEquals(10.0, settings.copy(minSellPricePerKwh = 0.1).toDraft().minSellCents!!, 0.0)
    }

    @Test fun anUntouchedFormSendsNothing() {
        assertNull(settingsPatch(settings, settings.toDraft()))
    }

    @Test fun patchCarriesOnlyTheChangedFieldsInControllerUnits() {
        val patch = settingsPatch(settings, settings.toDraft().copy(evChargeLimitPct = 90, minSellCents = 15.0))!!
        assertEquals(EnergySettingsPatch(evChargeLimitPct = 90, minSellPricePerKwh = 0.15), patch)
        assertEquals(setOf("ev_charge_limit_pct", "min_sell_price_per_kwh"), patch.toJson().fieldNames())

        val toggled = settingsPatch(settings, settings.toDraft().copy(evGridAllowed = true, evTripProfile = "target_100", evFitMaxCents = 2.5))!!
        assertEquals(true, toggled.evGridAllowed)
        assertEquals("target_100", toggled.evTripProfile)
        assertEquals(0.025, toggled.evOpportunisticFitMaxPerKwh!!, 1e-12)
        assertNull(toggled.evChargeLimitPct)
        assertNull(toggled.minSellPricePerKwh)
    }

    @Test fun changingAValueBackIsNotAChange() {
        val draft = settings.toDraft().copy(evChargeLimitPct = 90).copy(evChargeLimitPct = 80)
        assertNull(settingsPatch(settings, draft))
    }

    @Test fun settingsTheControllerDidNotReportStayOutOfThePatch() {
        val partial = settings.copy(evChargeLimitPct = null, minSellPricePerKwh = null)
        val draft = partial.toDraft()
        assertNull(draft.evChargeLimitPct)
        assertNull(settingsPatch(partial, draft))
        assertEquals(EnergySettingsPatch(evGridAllowed = true), settingsPatch(partial, draft.copy(evGridAllowed = true)))
    }

    @Test fun tripProfilesMatchTheControllersChoices() {
        assertEquals(
            listOf("no_trip", "distance_100_km", "distance_200_km", "target_80", "target_100"),
            TripProfiles.map { it.first },
        )
        assertEquals("No trip", tripProfileLabel("no_trip"))
        assertEquals("Weekend away", tripProfileLabel("weekend_away"))
        assertEquals("Unknown", tripProfileLabel(null))
    }

    @Test fun sliderGrowsToFitAValueAlreadyAboveTheUsualRange() {
        assertEquals(50f, sliderCeiling(12.0, usual = 50.0, step = 1.0), 0f)
        assertEquals(50f, sliderCeiling(null, usual = 50.0, step = 1.0), 0f)
        assertEquals(120f, sliderCeiling(120.0, usual = 50.0, step = 1.0), 0f)
        assertEquals(22.5f, sliderCeiling(22.3, usual = 20.0, step = 0.5), 0f)
    }

    // ------------------------------------------------------------ signed actions

    @Test fun everyCommandHasItsOwnConfirmationThatNamesTheAction() {
        val copies = EnergyAction.entries.map(::actionCopy)
        assertEquals(EnergyAction.entries.size, copies.map { it.title }.toSet().size)
        copies.forEach { copy ->
            assertTrue(copy.title.endsWith("?"))
            assertFalse(copy.confirmLabel.equals("OK", ignoreCase = true))
            assertTrue(copy.message.isNotBlank() && copy.success.isNotBlank())
        }
        assertTrue(actionCopy(EnergyAction.SafeState).destructive)
        assertTrue(actionCopy(EnergyAction.DisableAutomation).destructive)
        assertFalse(actionCopy(EnergyAction.EnableAutomation).destructive)
    }

    @Test fun commandFailuresSayWhetherAnythingWasSent() {
        val cancelled = AppError(ErrorKind.AuthCancelled, "Phone unlock was cancelled. Nothing was sent.")
        assertEquals(cancelled.message, actionFailure(cancelled))
        assertTrue(actionFailure(AppError(ErrorKind.Timeout, "Energy Manager took too long to answer.")).contains("may not have been applied"))
        assertTrue(actionFailure(AppError(ErrorKind.Offline, "This phone can't reach Energy Manager.")).endsWith("was not confirmed."))
    }

    // ------------------------------------------------------------ wording

    @Test fun readingsAreFormattedWithoutInventingZeros() {
        assertEquals(Reading("850", "W"), powerReading(-0.85))
        assertEquals(Reading("3.4", "kW"), powerReading(3.42))
        assertEquals(Reading("—", null), powerReading(null))
        assertEquals(Reading("—", null), powerReading(Double.NaN))
        assertEquals("—", formatPercent(null))
        assertEquals("77%", formatPercent(76.6))
        assertEquals("28.5 c/kWh", formatPrice(0.285))
        assertEquals("-2.0 c/kWh", formatPrice(-0.02))
        assertEquals("—", formatPrice(null))
        assertEquals("12 c/kWh", formatCents(12.0))
        assertEquals("2.5 c/kWh", formatCents(2.5))
        assertEquals("Under 1 min", formatRuntime(40.0))
        assertEquals("1 h 5 min", formatRuntime(3900.0))
        assertEquals("2 h", formatRuntime(7200.0))
        assertEquals("—", formatRuntime(-1.0))
    }

    @Test fun timesAreShownInBrisbaneWhereverThePhoneIs() {
        assertEquals("Thu 12:00 PM", formatDayTime(now))
        assertEquals("12PM", formatHour(now))
        assertEquals("11 Nov", formatDate("2026-11-11"))
        assertEquals("—", formatDate(null))
        assertEquals("—", formatDayTime(null))
    }

    @Test fun panesAreInSegmentedControlOrder() {
        assertEquals(listOf("Now", "Plan", "Solar", "UPS & rack", "Controls"), EnergyPane.entries.map { it.label })
    }
}
