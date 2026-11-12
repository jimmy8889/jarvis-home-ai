package com.jameshazell.pilot.ui.assistant

import com.jameshazell.pilot.data.pilot.AssistantCard
import com.jameshazell.pilot.data.pilot.AssistantReply
import com.jameshazell.pilot.data.pilot.AssistantSource
import kotlin.math.sqrt

/*
 * Everything in this file is plain Kotlin (no Android, no Compose) so it runs in JVM unit tests.
 */

/** The one audio format Pilot Core's voice endpoint accepts: raw PCM, no WAV header. */
object Pcm {
    const val SAMPLE_RATE = 16_000
    const val BYTES_PER_SAMPLE = 2
    const val BYTES_PER_SECOND = SAMPLE_RATE * BYTES_PER_SAMPLE

    /** Shorter recordings are a slip of the finger, not a question. */
    const val MIN_UPLOAD_MS = 500L

    /** Recording stops by itself here. */
    const val MAX_RECORDING_MS = 30_000L

    /** Upload size of [durationMs] of speech: whole samples, nothing else. */
    fun bytesFor(durationMs: Long): Int = (durationMs * SAMPLE_RATE / 1000).toInt() * BYTES_PER_SAMPLE

    fun durationMs(byteCount: Int): Long = (byteCount / BYTES_PER_SAMPLE) * 1000L / SAMPLE_RATE

    fun isLongEnough(byteCount: Int): Boolean = durationMs(byteCount) >= MIN_UPLOAD_MS

    /** Loudness of the first [length] bytes of little-endian 16-bit [chunk], 0 (silence) to 1. */
    fun level(chunk: ByteArray, length: Int = chunk.size): Float {
        val samples = length.coerceAtMost(chunk.size) / BYTES_PER_SAMPLE
        if (samples == 0) return 0f
        var sum = 0.0
        for (i in 0 until samples) {
            val sample = (chunk[i * 2].toInt() and 0xff) or (chunk[i * 2 + 1].toInt() shl 8)
            sum += sample.toDouble() * sample
        }
        return (sqrt(sum / samples) / Short.MAX_VALUE).toFloat().coerceIn(0f, 1f)
    }
}

/** Collects microphone chunks up to [maxBytes]; not thread-safe. */
class PcmBuffer(private val maxBytes: Int = Pcm.bytesFor(Pcm.MAX_RECORDING_MS)) {
    private val bytes = java.io.ByteArrayOutputStream()

    val size: Int get() = bytes.size()
    val isFull: Boolean get() = size >= maxBytes

    /** Adds the first [length] bytes of [chunk]. False once the limit is reached: stop recording. */
    fun append(chunk: ByteArray, length: Int = chunk.size): Boolean {
        val take = length.coerceIn(0, chunk.size).coerceAtMost(maxBytes - size)
        if (take > 0) bytes.write(chunk, 0, take)
        return !isFull
    }

    /** What to upload: every complete sample (a trailing odd byte is dropped). */
    fun toUpload(): ByteArray {
        val all = bytes.toByteArray()
        return if (all.size % Pcm.BYTES_PER_SAMPLE == 0) all else all.copyOf(all.size - all.size % Pcm.BYTES_PER_SAMPLE)
    }
}

enum class AssistantPhase { Idle, Listening, Thinking, Speaking }

data class AssistantMessage(
    val id: Long,
    val fromUser: Boolean,
    val text: String,
    /** A user message that was spoken (the text is Pilot's transcript of it). */
    val spoken: Boolean = false,
    val cards: List<AssistantCard> = emptyList(),
    val sources: List<AssistantSource> = emptyList(),
)

/**
 * @param error what went wrong with the assistant most recently, in plain words. Only ever shown
 * on the assistant screen.
 */
data class AssistantUiState(
    val messages: List<AssistantMessage> = emptyList(),
    val phase: AssistantPhase = AssistantPhase.Idle,
    val error: String? = null,
    val draft: String = "",
    val conversationId: String? = null,
)

object AssistantReducer {
    /** A typed question was sent. */
    fun asked(state: AssistantUiState, text: String): AssistantUiState =
        state.copy(
            messages = state.messages + AssistantMessage(state.nextId(), fromUser = true, text = text),
            phase = AssistantPhase.Thinking,
            error = null,
            draft = "",
        )

    /**
     * Pilot answered. For a spoken question the transcript becomes the user's message. The
     * conversation id is kept when the reply doesn't carry one, so follow-ups stay in context.
     */
    fun replied(state: AssistantUiState, reply: AssistantReply, viaVoice: Boolean): AssistantUiState {
        val messages = state.messages.toMutableList()
        val transcript = reply.transcript?.trim().orEmpty()
        if (viaVoice && transcript.isNotEmpty()) {
            messages += AssistantMessage(state.nextId(), fromUser = true, text = transcript, spoken = true)
        }
        messages += AssistantMessage(
            id = (messages.lastOrNull()?.id ?: 0) + 1,
            fromUser = false,
            text = reply.text.trim().ifEmpty { "Pilot had nothing to say to that." },
            cards = reply.cards,
            sources = reply.sources,
        )
        return state.copy(
            messages = messages,
            phase = AssistantPhase.Idle,
            error = null,
            conversationId = reply.conversationId?.takeIf(String::isNotBlank) ?: state.conversationId,
        )
    }

    fun failed(state: AssistantUiState, message: String): AssistantUiState = state.copy(phase = AssistantPhase.Idle, error = message)

    private fun AssistantUiState.nextId(): Long = (messages.lastOrNull()?.id ?: 0) + 1
}

enum class OrbAction { None, StartRecording, FinishRecording, Stop }

/**
 * The orb works two ways: hold it, speak, release to send; or tap once to start and tap again to
 * send. While Pilot is thinking or speaking, touching it stops that.
 */
object OrbGesture {
    /** A press at least this long is a hold; anything shorter is a tap. */
    const val HOLD_MS = 350L

    fun onPress(phase: AssistantPhase): OrbAction = when (phase) {
        AssistantPhase.Idle -> OrbAction.StartRecording
        AssistantPhase.Listening -> OrbAction.None // Decided on release.
        AssistantPhase.Thinking, AssistantPhase.Speaking -> OrbAction.Stop
    }

    /**
     * @param phase when the finger lifts.
     * @param startedByThisPress this same press began the recording.
     */
    fun onRelease(phase: AssistantPhase, startedByThisPress: Boolean, heldMs: Long): OrbAction = when {
        phase != AssistantPhase.Listening -> OrbAction.None
        !startedByThisPress -> OrbAction.FinishRecording // The second tap.
        heldMs >= HOLD_MS -> OrbAction.FinishRecording // Hold released.
        else -> OrbAction.None // First tap: keep listening.
    }

    /** One accessibility click (no press and release to tell apart). */
    fun onClick(phase: AssistantPhase): OrbAction = when (phase) {
        AssistantPhase.Idle -> OrbAction.StartRecording
        AssistantPhase.Listening -> OrbAction.FinishRecording
        AssistantPhase.Thinking, AssistantPhase.Speaking -> OrbAction.Stop
    }
}

data class OrbCaption(val title: String, val hint: String)

fun orbCaption(phase: AssistantPhase): OrbCaption = when (phase) {
    AssistantPhase.Idle -> OrbCaption("Hold to talk", "Or tap once to start and again to send.")
    AssistantPhase.Listening -> OrbCaption("Listening…", "Release, or tap again, to send.")
    AssistantPhase.Thinking -> OrbCaption("Thinking…", "Tap to cancel.")
    AssistantPhase.Speaking -> OrbCaption("Speaking", "Tap to stop.")
}

/** The system "animator duration scale" setting: 0 (or nonsense) means no motion. */
fun animationsEnabledForScale(animatorDurationScale: Float): Boolean =
    animatorDurationScale.isFinite() && animatorDurationScale > 0f

/** Messages for failures that have no AppError of their own. */
object AssistantMessages {
    const val TOO_SHORT = "I didn't catch that. Keep the orb held a little longer while you speak."
    const val MIC_DENIED = "Pilot needs the microphone to hear you. Allow it in this app's settings, or type instead."
    const val MIC_FAILED = "The microphone couldn't be started. Another app may be using it."
    const val MIC_BUSY = "The microphone is busy with a call or another app. Try again in a moment."
    const val INTERRUPTED = "Recording stopped because another app took over the audio."
    const val BACKGROUNDED = "Recording stopped because Pilot went out of view. Nothing was sent."
    const val PLAYBACK_FAILED = "Pilot answered, but the spoken reply couldn't be played."
    const val NO_ROOM = "No room is assigned to this phone yet, so Pilot doesn't know where you are. Choose a room for this phone first."
}
