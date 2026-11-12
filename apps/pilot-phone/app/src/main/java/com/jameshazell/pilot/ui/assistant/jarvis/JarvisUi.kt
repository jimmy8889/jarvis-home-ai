package com.jameshazell.pilot.ui.assistant.jarvis

import com.jameshazell.pilot.data.jarvis.JarvisConnection
import com.jameshazell.pilot.data.jarvis.JarvisPhase
import com.jameshazell.pilot.data.jarvis.JarvisTelemetryState
import com.jameshazell.pilot.data.jarvis.JarvisVoiceMode
import com.jameshazell.pilot.ui.more.ServiceStatus
import com.jameshazell.pilot.ui.more.StatusTone
import kotlin.math.roundToInt

/*
 * Plain Kotlin (no Android, no Compose) so it runs in JVM unit tests. Wording follows the
 * JARVIS phone app.
 */

/** Which assistant the Pilot tab shows. JARVIS is the default. */
enum class AssistantMode(val label: String) { Jarvis("JARVIS"), House("House assistant") }

/** How the reactor is drawn. */
enum class ReactorState { Offline, Idle, Listening, Thinking, Speaking }

fun reactorState(phase: JarvisPhase, connection: JarvisConnection): ReactorState = when {
    phase == JarvisPhase.Listening -> ReactorState.Listening
    phase == JarvisPhase.Speaking -> ReactorState.Speaking
    phase.busy -> ReactorState.Thinking
    connection is JarvisConnection.Connected || connection == JarvisConnection.Checking -> ReactorState.Idle
    else -> ReactorState.Offline
}

/** The status line under the title. */
data class LinkLine(val text: String, val good: Boolean, val canRetry: Boolean = false)

fun linkLine(connection: JarvisConnection): LinkLine = when (connection) {
    JarvisConnection.Loading, JarvisConnection.Checking -> LinkLine("CONNECTING TO LAPTOP  /  PRIVATE SESSION", false)
    JarvisConnection.NotPaired -> LinkLine("PAIRING REQUIRED  ·  OPEN SETTINGS", false)
    is JarvisConnection.Connected ->
        if (connection.health.connected) LinkLine("●  LAPTOP CONNECTED  /  LOCAL ONLY", true)
        else LinkLine("●  LAPTOP CONNECTED  /  MODELS UNAVAILABLE", false)
    is JarvisConnection.Unreachable -> LinkLine("●  LAPTOP OFFLINE  ·  RETRY IN ${connection.retryInSeconds} S  ·  TAP TO RETRY", false, canRetry = true)
    JarvisConnection.Unauthorized -> LinkLine("●  PAIRING REJECTED  ·  PAIR AGAIN IN SETTINGS", false)
}

/** The sentence under the reactor. A [notice] (a problem or tip from the last turn) wins in standby. */
fun reactorHint(phase: JarvisPhase, connection: JarvisConnection, notice: String?, onDevice: Boolean): String = when (phase) {
    JarvisPhase.Listening -> if (onDevice) "Listening on this phone. Speak naturally." else "Listening. Speak naturally."
    JarvisPhase.Transcribing -> "Listening back…"
    JarvisPhase.Thinking -> "One moment, sir."
    JarvisPhase.Working -> "Working on the laptop, sir."
    JarvisPhase.PreparingVoice -> "Preparing your reply…"
    JarvisPhase.Speaking -> "At your service."
    JarvisPhase.Standby -> notice ?: when (connection) {
        JarvisConnection.NotPaired -> "Pair with the laptop to wake JARVIS."
        JarvisConnection.Unauthorized -> "Pair this phone with your laptop again."
        is JarvisConnection.Unreachable -> "Connect the phone and laptop to Tailscale, and keep the laptop awake."
        is JarvisConnection.Connected ->
            if (connection.health.connected) "At your service, James." else "The laptop is up, but its model services aren't answering."
        else -> "At your service, James."
    }
}

/** What touching the reactor will do, shown beneath it. */
fun reactorAction(phase: JarvisPhase, paired: Boolean): String = when {
    !paired -> "TAP TO PAIR"
    phase == JarvisPhase.Standby -> "TAP OR HOLD TO SPEAK"
    phase == JarvisPhase.Listening -> "TAP TO FINISH"
    phase == JarvisPhase.Speaking -> "TAP TO INTERRUPT"
    else -> "TAP TO STOP"
}

/** "41%", or "—" for no reading or a stale one. Never a made-up zero. */
fun percentLabel(value: Double?, fresh: Boolean): String = if (fresh && value != null) "${value.roundToInt()}%" else "—"

fun telemetryStrip(state: JarvisTelemetryState, nowMs: Long): String {
    val fresh = state.fresh(nowMs)
    val s = state.sample
    return "LAPTOP   CPU ${percentLabel(s?.cpuPercent, fresh)}    RAM ${percentLabel(s?.ramPercent, fresh)}    GPU ${percentLabel(s?.gpuPercent, fresh)}"
}

/** The line under the conversation: what answered and how long it took. */
fun latencyLine(model: String?, mode: JarvisVoiceMode, seconds: Double?): String {
    val speech = when (mode) {
        JarvisVoiceMode.VoiceStudio -> "VOICE STUDIO"
        JarvisVoiceMode.PhoneVoice -> "PHONE VOICE"
        JarvisVoiceMode.Off -> "TEXT"
    }
    val name = model?.takeIf(String::isNotBlank)?.uppercase() ?: "LOCAL MODEL"
    return if (seconds == null) "$name  ·  $speech  ·  PRIVATE CONNECTION" else "$name  ·  $speech  ·  REPLY ${"%.1f".format(java.util.Locale.US, seconds)}s"
}

/** The JARVIS row under Settings ▸ Connections. */
fun jarvisStatus(connection: JarvisConnection): ServiceStatus {
    val name = "JARVIS"
    return when (connection) {
        JarvisConnection.Loading -> ServiceStatus(name, "Not checked yet", null, StatusTone.Idle)
        JarvisConnection.NotPaired -> ServiceStatus(name, "Not paired", "Open Pilot ▸ JARVIS and pair with the laptop.", StatusTone.Idle)
        JarvisConnection.Checking -> ServiceStatus(name, "Paired", "Connects while the JARVIS tab is open.", StatusTone.Idle)
        is JarvisConnection.Connected ->
            if (connection.health.connected) ServiceStatus(name, "Connected", "Laptop bridge and models are up.", StatusTone.Good)
            else ServiceStatus(name, "Models unavailable", "The laptop answers, but a model service is down.", StatusTone.Warning)
        is JarvisConnection.Unreachable -> ServiceStatus(name, "Laptop unreachable", "Check Tailscale and keep the laptop awake.", StatusTone.Bad)
        JarvisConnection.Unauthorized -> ServiceStatus(name, "Pairing rejected", "Pair this phone with the laptop again.", StatusTone.Bad)
    }
}

enum class ReactorAction { None, Listen, Finish, Stop, InterruptAndListen, Pair }

/**
 * Touching the reactor: tap to talk (tap again to finish), or hold and release. A touch while
 * JARVIS speaks interrupts him and listens; a touch while he is working stops the turn.
 */
object ReactorGesture {
    const val HOLD_MS = 350L

    fun onPress(phase: JarvisPhase, paired: Boolean): ReactorAction = when {
        !paired -> ReactorAction.Pair
        phase == JarvisPhase.Standby -> ReactorAction.Listen
        phase == JarvisPhase.Listening -> ReactorAction.None // Decided on release.
        phase == JarvisPhase.Speaking -> ReactorAction.InterruptAndListen
        else -> ReactorAction.Stop
    }

    /** @param startedByThisPress this same press opened the microphone. */
    fun onRelease(phase: JarvisPhase, startedByThisPress: Boolean, heldMs: Long): ReactorAction = when {
        phase != JarvisPhase.Listening -> ReactorAction.None
        !startedByThisPress -> ReactorAction.Finish
        heldMs >= HOLD_MS -> ReactorAction.Finish
        else -> ReactorAction.None
    }

    /** One accessibility click. */
    fun onClick(phase: JarvisPhase, paired: Boolean): ReactorAction =
        if (paired && phase == JarvisPhase.Listening) ReactorAction.Finish else onPress(phase, paired)
}

/**
 * End-of-speech detection for laptop recognition, with the JARVIS app's thresholds: speech is
 * RMS above 450; stop 1.5 s after speech ends (never in the first second), after 10 s of nothing,
 * or at 30 s.
 */
class SilenceDetector(private val startMs: Long) {
    var heard: Boolean = false
        private set
    private var lastSpeechMs = startMs

    /** @return true to keep recording. */
    fun feed(rms: Double, nowMs: Long): Boolean {
        if (rms > SPEECH_RMS) {
            heard = true
            lastSpeechMs = nowMs
        }
        val elapsed = nowMs - startMs
        return when {
            elapsed >= MAX_MS -> false
            heard && nowMs - lastSpeechMs > TRAILING_SILENCE_MS && elapsed > MIN_MS -> false
            !heard && elapsed > NO_SPEECH_MS -> false
            else -> true
        }
    }

    companion object {
        const val SPEECH_RMS = 450.0
        const val TRAILING_SILENCE_MS = 1_500L
        const val MIN_MS = 1_000L
        const val NO_SPEECH_MS = 10_000L
        const val MAX_MS = 30_000L
        /** RMS that fills the reactor's level meter. */
        const val FULL_SCALE_RMS = 5_000.0
    }
}

object JarvisText {
    const val NO_SPEECH = "No speech detected. Tap to try again."
    const val PHONE_ASR_FAILED = "Phone recognition unavailable. Tap to use laptop recognition."
    const val MIC_DENIED = "JARVIS needs the microphone to hear you. Allow it in this app's settings, or type instead."
    const val MIC_FAILED = "Microphone is unavailable. Close another recording app and retry."
    const val NO_PHONE_VOICE = "No offline British phone voice is installed, so speech is off."
    const val PHONE_SPEECH_FAILED = "Phone speech failed. Choose Voice Studio to retry."
    const val PLAYBACK_FAILED = "Audio playback failed. Your text reply is above."
    const val STOP_FIRST = "Stop the current turn first."
    const val CONTINUOUS_ON = "Listens again after each reply while this tab is open."
    val SUGGESTIONS = listOf("Introduce yourself", "What can you help me with?")
}
