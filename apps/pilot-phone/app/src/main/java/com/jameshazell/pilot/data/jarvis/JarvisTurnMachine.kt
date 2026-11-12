package com.jameshazell.pilot.data.jarvis

/** What JARVIS is doing, in the order a spoken turn passes through. */
enum class JarvisPhase(val label: String) {
    Standby("STANDBY"),
    Listening("LISTENING"),
    Transcribing("TRANSCRIBING"),
    Thinking("THINKING"),
    Working("WORKING"),
    PreparingVoice("PREPARING VOICE"),
    Speaking("SPEAKING");

    /** A request is with the laptop. */
    val busy: Boolean get() = this == Transcribing || this == Thinking || this == Working || this == PreparingVoice
}

/**
 * @param pendingUser what is being said or was just sent (partial transcript, then final).
 * @param pendingReply the reply so far, growing as the laptop streams it.
 * @param notice a hint or problem to show under the reactor until the next turn.
 * @param inFlight a turn has been submitted and has not finished: no second one may start.
 */
data class JarvisTurnState(
    val phase: JarvisPhase = JarvisPhase.Standby,
    val pendingUser: String = "",
    val pendingReply: String = "",
    val notice: String? = null,
    val inFlight: Boolean = false,
    val lastSeconds: Double? = null,
)

sealed interface JarvisTurnEvent {
    /** The microphone opened. */
    data object ListeningStarted : JarvisTurnEvent
    /** Partial on-device transcript. */
    data class Heard(val text: String) : JarvisTurnEvent
    /** Speech ended; waiting for the final transcript. */
    data object ListeningEnded : JarvisTurnEvent
    /** Nothing usable was heard; [message] says why. */
    data class ListeningFailed(val message: String?) : JarvisTurnEvent
    /** A turn was sent: typed / recognised [text], or a recording when [audio]. */
    data class Submitted(val text: String, val audio: Boolean) : JarvisTurnEvent
    /** A poll of the running turn. */
    data class Snapshot(val turn: JarvisTurn) : JarvisTurnEvent
    data class Completed(val turn: JarvisTurn) : JarvisTurnEvent
    data object SpeakingStarted : JarvisTurnEvent
    data class SpeakingFinished(val notice: String? = null) : JarvisTurnEvent
    /** The user stopped whatever was happening. */
    data object Stopped : JarvisTurnEvent
    data class Failed(val message: String) : JarvisTurnEvent
}

/** The turn state machine. Events that don't apply in the current phase leave the state alone. */
object JarvisTurnMachine {
    /** A new turn (or the microphone) may start: nothing is in flight. Speaking may be interrupted. */
    fun canBegin(state: JarvisTurnState): Boolean =
        !state.inFlight && (state.phase == JarvisPhase.Standby || state.phase == JarvisPhase.Speaking)

    fun reduce(state: JarvisTurnState, event: JarvisTurnEvent): JarvisTurnState = when (event) {
        JarvisTurnEvent.ListeningStarted ->
            if (!canBegin(state)) state
            else state.copy(phase = JarvisPhase.Listening, pendingUser = "", pendingReply = "", notice = null)

        is JarvisTurnEvent.Heard ->
            if (state.phase == JarvisPhase.Listening && !state.inFlight) state.copy(pendingUser = event.text) else state

        JarvisTurnEvent.ListeningEnded ->
            if (state.phase == JarvisPhase.Listening && !state.inFlight) state.copy(phase = JarvisPhase.Transcribing) else state

        is JarvisTurnEvent.ListeningFailed ->
            if (state.inFlight || (state.phase != JarvisPhase.Listening && state.phase != JarvisPhase.Transcribing)) state
            else state.copy(phase = JarvisPhase.Standby, pendingUser = "", notice = event.message)

        is JarvisTurnEvent.Submitted ->
            if (state.inFlight) state
            else state.copy(
                phase = if (event.audio) JarvisPhase.Transcribing else JarvisPhase.Thinking,
                pendingUser = event.text, pendingReply = "", notice = null, inFlight = true,
            )

        is JarvisTurnEvent.Snapshot ->
            if (!state.inFlight) state
            else state.copy(
                phase = when (event.turn.stage) {
                    JarvisStage.Listening -> JarvisPhase.Transcribing
                    JarvisStage.Thinking -> JarvisPhase.Thinking
                    JarvisStage.Acting -> JarvisPhase.Working
                    JarvisStage.Voicing -> JarvisPhase.PreparingVoice
                    else -> state.phase
                },
                pendingUser = event.turn.transcript.ifEmpty { state.pendingUser },
                pendingReply = event.turn.reply,
            )

        is JarvisTurnEvent.Completed ->
            if (!state.inFlight) state
            else JarvisTurnState(lastSeconds = event.turn.totalSeconds, notice = event.turn.speechError)

        JarvisTurnEvent.SpeakingStarted ->
            if (state.phase == JarvisPhase.Standby && !state.inFlight) state.copy(phase = JarvisPhase.Speaking) else state

        is JarvisTurnEvent.SpeakingFinished ->
            if (state.phase == JarvisPhase.Speaking) state.copy(phase = JarvisPhase.Standby, notice = event.notice ?: state.notice) else state

        JarvisTurnEvent.Stopped -> JarvisTurnState(lastSeconds = state.lastSeconds)

        is JarvisTurnEvent.Failed -> JarvisTurnState(notice = event.message, lastSeconds = state.lastSeconds)
    }
}
