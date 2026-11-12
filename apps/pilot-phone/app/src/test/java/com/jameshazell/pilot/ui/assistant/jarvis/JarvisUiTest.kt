package com.jameshazell.pilot.ui.assistant.jarvis

import com.jameshazell.pilot.data.jarvis.JarvisConnection
import com.jameshazell.pilot.data.jarvis.JarvisHealth
import com.jameshazell.pilot.data.jarvis.JarvisPhase
import com.jameshazell.pilot.data.jarvis.JarvisTelemetry
import com.jameshazell.pilot.data.jarvis.JarvisTelemetryState
import com.jameshazell.pilot.data.jarvis.JarvisVoiceMode
import com.jameshazell.pilot.ui.more.StatusTone
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class JarvisUiTest {
    private fun health(connected: Boolean) = JarvisHealth(connected, connected, true, true, "qwen3.5-4b", "JARVIS · British", true, true)
    private val up = JarvisConnection.Connected(health(true))
    private val modelsDown = JarvisConnection.Connected(health(false))
    private val asleep = JarvisConnection.Unreachable(2, 4)

    @Test fun everyConnectionStateIsToldApart() {
        val lines = listOf(JarvisConnection.NotPaired, JarvisConnection.Checking, up, modelsDown, asleep, JarvisConnection.Unauthorized).map(::linkLine)
        assertEquals(6, lines.map { it.text }.toSet().size)
        assertEquals(listOf(false, false, true, false, false, false), lines.map { it.good })
        assertTrue(linkLine(asleep).canRetry)
        assertTrue(linkLine(asleep).text.contains("RETRY IN 4 S"))
        assertTrue(linkLine(JarvisConnection.NotPaired).text.startsWith("PAIRING REQUIRED"))
        assertTrue(linkLine(JarvisConnection.Unauthorized).text.contains("PAIR AGAIN"))
    }

    @Test fun settingsRow() {
        assertEquals(StatusTone.Idle, jarvisStatus(JarvisConnection.NotPaired).tone)
        assertEquals("Not paired", jarvisStatus(JarvisConnection.NotPaired).label)
        assertEquals(StatusTone.Good, jarvisStatus(up).tone)
        assertEquals(StatusTone.Warning, jarvisStatus(modelsDown).tone)
        assertEquals(StatusTone.Bad, jarvisStatus(asleep).tone)
        assertEquals("Pairing rejected", jarvisStatus(JarvisConnection.Unauthorized).label)
        assertTrue(listOf(JarvisConnection.Loading, JarvisConnection.Checking, up, asleep).all { jarvisStatus(it).name == "JARVIS" })
    }

    @Test fun reactorFollowsTheTurn() {
        assertEquals(ReactorState.Idle, reactorState(JarvisPhase.Standby, up))
        assertEquals(ReactorState.Listening, reactorState(JarvisPhase.Listening, up))
        assertEquals(listOf(ReactorState.Thinking), listOf(JarvisPhase.Transcribing, JarvisPhase.Thinking, JarvisPhase.Working, JarvisPhase.PreparingVoice).map { reactorState(it, up) }.distinct())
        assertEquals(ReactorState.Speaking, reactorState(JarvisPhase.Speaking, up))
        assertEquals(ReactorState.Offline, reactorState(JarvisPhase.Standby, asleep))
        assertEquals(ReactorState.Offline, reactorState(JarvisPhase.Standby, JarvisConnection.NotPaired))
        assertEquals(ReactorState.Offline, reactorState(JarvisPhase.Standby, JarvisConnection.Unauthorized))
    }

    @Test fun hintsAreJarvisOwnWords() {
        assertEquals("At your service, James.", reactorHint(JarvisPhase.Standby, up, null, onDevice = true))
        assertEquals("Listening on this phone. Speak naturally.", reactorHint(JarvisPhase.Listening, up, null, onDevice = true))
        assertEquals("Listening. Speak naturally.", reactorHint(JarvisPhase.Listening, up, null, onDevice = false))
        assertEquals("One moment, sir.", reactorHint(JarvisPhase.Thinking, up, "old notice", onDevice = true))
        assertEquals("Working on the laptop, sir.", reactorHint(JarvisPhase.Working, up, null, onDevice = true))
        assertEquals("No speech detected. Tap to try again.", reactorHint(JarvisPhase.Standby, up, JarvisText.NO_SPEECH, onDevice = true))
        assertTrue(reactorHint(JarvisPhase.Standby, asleep, null, true).contains("Tailscale"))
        assertTrue(reactorHint(JarvisPhase.Standby, JarvisConnection.Unauthorized, null, true).contains("again"))
        assertTrue(reactorHint(JarvisPhase.Standby, JarvisConnection.NotPaired, null, true).startsWith("Pair"))
    }

    @Test fun telemetryNeverInventsAReading() {
        assertEquals("41%", percentLabel(41.4, fresh = true))
        assertEquals("—", percentLabel(null, fresh = true))
        assertEquals("—", percentLabel(41.4, fresh = false))
        val state = JarvisTelemetryState(JarvisTelemetry(12.0, 41.5, null, null, true), receivedAtMs = 0)
        assertEquals("LAPTOP   CPU 12%    RAM 42%    GPU —", telemetryStrip(state, nowMs = 3_000))
        assertEquals("LAPTOP   CPU —    RAM —    GPU —", telemetryStrip(state, nowMs = 15_000))
        assertEquals("LAPTOP   CPU —    RAM —    GPU —", telemetryStrip(JarvisTelemetryState(), nowMs = 0))
    }

    @Test fun latencyLine() {
        assertEquals("QWEN3.5-4B  ·  VOICE STUDIO  ·  REPLY 2.3s", latencyLine("qwen3.5-4b", JarvisVoiceMode.VoiceStudio, 2.34))
        assertEquals("LOCAL MODEL  ·  TEXT  ·  PRIVATE CONNECTION", latencyLine(null, JarvisVoiceMode.Off, null))
        assertTrue(latencyLine("m", JarvisVoiceMode.PhoneVoice, 1.0).contains("PHONE VOICE"))
    }

    @Test fun tapToTalk() {
        assertEquals(ReactorAction.Listen, ReactorGesture.onPress(JarvisPhase.Standby, paired = true))
        assertEquals(ReactorAction.None, ReactorGesture.onRelease(JarvisPhase.Listening, startedByThisPress = true, heldMs = 90))
        assertEquals(ReactorAction.None, ReactorGesture.onPress(JarvisPhase.Listening, paired = true))
        assertEquals(ReactorAction.Finish, ReactorGesture.onRelease(JarvisPhase.Listening, startedByThisPress = false, heldMs = 60))
    }

    @Test fun holdToTalk() {
        assertEquals(ReactorAction.Finish, ReactorGesture.onRelease(JarvisPhase.Listening, startedByThisPress = true, heldMs = ReactorGesture.HOLD_MS))
        assertEquals(ReactorAction.Finish, ReactorGesture.onRelease(JarvisPhase.Listening, startedByThisPress = true, heldMs = 4_000))
        // The recogniser already ended the turn by itself while the finger was down.
        assertEquals(ReactorAction.None, ReactorGesture.onRelease(JarvisPhase.Thinking, startedByThisPress = true, heldMs = 4_000))
    }

    @Test fun touchingWhileSpeakingInterruptsAndListens() {
        assertEquals(ReactorAction.InterruptAndListen, ReactorGesture.onPress(JarvisPhase.Speaking, paired = true))
        listOf(JarvisPhase.Transcribing, JarvisPhase.Thinking, JarvisPhase.Working, JarvisPhase.PreparingVoice).forEach {
            assertEquals(ReactorAction.Stop, ReactorGesture.onPress(it, paired = true))
        }
        assertEquals(ReactorAction.Pair, ReactorGesture.onPress(JarvisPhase.Standby, paired = false))
        assertEquals(ReactorAction.Finish, ReactorGesture.onClick(JarvisPhase.Listening, paired = true))
        assertEquals(ReactorAction.Listen, ReactorGesture.onClick(JarvisPhase.Standby, paired = true))
        assertEquals(ReactorAction.Pair, ReactorGesture.onClick(JarvisPhase.Listening, paired = false))
        assertEquals(4, listOf(JarvisPhase.Standby, JarvisPhase.Listening, JarvisPhase.Speaking, JarvisPhase.Thinking).map { reactorAction(it, true) }.toSet().size)
        assertEquals("TAP TO PAIR", reactorAction(JarvisPhase.Standby, false))
    }

    @Test fun recordingEndsAfterTrailingSilence() {
        val detector = SilenceDetector(startMs = 0)
        assertTrue(detector.feed(100.0, 100))
        assertTrue(detector.feed(2_000.0, 600)) // speech
        assertTrue(detector.heard)
        assertTrue(detector.feed(100.0, 2_000))
        assertTrue(detector.feed(100.0, 2_100))
        assertFalse(detector.feed(100.0, 2_101)) // 1.5 s after the last speech
    }

    @Test fun recordingNeverEndsInTheFirstSecondAndGivesUpOnSilence() {
        val quick = SilenceDetector(0)
        quick.feed(900.0, 0)
        assertTrue(SilenceDetector(0).also { it.feed(900.0, 0) }.feed(0.0, 999))
        val silent = SilenceDetector(1_000)
        assertTrue(silent.feed(449.0, 11_000))
        assertFalse(silent.feed(449.0, 11_001))
        assertFalse(silent.heard)
        val long = SilenceDetector(0)
        var keep = true
        var t = 0L
        while (keep && t < 60_000) { t += 100; keep = long.feed(3_000.0, t) }
        assertEquals(SilenceDetector.MAX_MS, t)
        assertTrue(long.heard)
    }

    @Test fun modesAndCopy() {
        assertEquals(listOf("JARVIS", "House assistant"), AssistantMode.entries.map { it.label })
        assertEquals(AssistantMode.Jarvis, AssistantMode.entries.first())
        assertEquals(2, JarvisText.SUGGESTIONS.size)
        assertTrue(listOf(JarvisText.NO_SPEECH, JarvisText.MIC_DENIED, JarvisText.MIC_FAILED, JarvisText.PLAYBACK_FAILED, JarvisText.STOP_FIRST).all { it.endsWith(".") })
    }
}
