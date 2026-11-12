package com.jameshazell.pilot.ui.assistant

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaDataSource
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** A recording failure with a message that is safe to show. */
class VoiceException(message: String) : Exception(message)

/** Captures speech as 16 kHz mono 16-bit PCM. */
interface VoiceRecorder {
    /** Loudness of what is being heard right now, 0 to 1. */
    val level: StateFlow<Float>

    /**
     * Starts capturing. Call on the main thread.
     *
     * @param onInterrupted called on the main thread if another app takes the audio away or the
     * length limit is reached; the recording is still held until [stop] or [cancel].
     * @throws VoiceException when the microphone can't be used.
     */
    fun start(onInterrupted: (limitReached: Boolean) -> Unit)

    /** Ends the capture and returns the PCM. May block briefly: call off the main thread. */
    fun stop(): ByteArray

    /** Ends the capture and throws the audio away. */
    fun cancel()
}

/** Plays a spoken reply. All calls and callbacks are on the main thread. */
interface ReplyPlayer {
    /** @param onDone called once when playback ends by itself; `false` if it could not be played. */
    fun play(audio: ByteArray, onDone: (played: Boolean) -> Unit)

    /** Stops now. `onDone` is not called. */
    fun stop()
}

/**
 * Holds audio focus for one recording or one reply, so music pauses or ducks while Pilot is
 * listening or speaking and comes back afterwards.
 */
internal class AssistantAudioFocus(context: Context, private val exclusive: Boolean, private val onLost: () -> Unit) {
    private val manager = context.getSystemService(AudioManager::class.java)
    private val request = AudioFocusRequest.Builder(
        if (exclusive) AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE else AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK,
    )
        .setAudioAttributes(assistantAttributes())
        .setOnAudioFocusChangeListener(
            { change -> if (change <= AudioManager.AUDIOFOCUS_LOSS) lost() },
            Handler(Looper.getMainLooper()),
        )
        .build()
    private var held = false

    /** False when the system refuses, e.g. during a phone call. */
    fun acquire(): Boolean {
        held = manager.requestAudioFocus(request) == AudioManager.AUDIOFOCUS_REQUEST_GRANTED
        return held
    }

    fun release() {
        if (!held) return
        held = false
        manager.abandonAudioFocusRequest(request)
    }

    private fun lost() {
        if (!held) return
        release()
        onLost()
    }
}

internal fun assistantAttributes(): AudioAttributes = AudioAttributes.Builder()
    .setUsage(AudioAttributes.USAGE_ASSISTANT)
    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
    .build()

class AndroidVoiceRecorder(context: Context) : VoiceRecorder {
    private val appContext = context.applicationContext
    private val main = Handler(Looper.getMainLooper())
    private val recording = AtomicBoolean(false)
    private val _level = MutableStateFlow(0f)
    override val level: StateFlow<Float> = _level.asStateFlow()

    private var recorder: AudioRecord? = null
    private var worker: Thread? = null
    private var buffer: PcmBuffer? = null
    private var focus: AssistantAudioFocus? = null

    @SuppressLint("MissingPermission") // Checked on the first line.
    @Synchronized
    override fun start(onInterrupted: (limitReached: Boolean) -> Unit) {
        if (ContextCompat.checkSelfPermission(appContext, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            throw VoiceException(AssistantMessages.MIC_DENIED)
        }
        if (recording.get()) throw VoiceException(AssistantMessages.MIC_FAILED)

        val audioFocus = AssistantAudioFocus(appContext, exclusive = true) { if (recording.get()) onInterrupted(false) }
        if (!audioFocus.acquire()) throw VoiceException(AssistantMessages.MIC_BUSY)

        val minimum = AudioRecord.getMinBufferSize(Pcm.SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
            .coerceAtLeast(4_096)
        val next = try {
            AudioRecord.Builder()
                .setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(Pcm.SAMPLE_RATE)
                        .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                        .build(),
                )
                .setBufferSizeInBytes(minimum * 2)
                .build()
                .also {
                    check(it.state == AudioRecord.STATE_INITIALIZED)
                    it.startRecording()
                    check(it.recordingState == AudioRecord.RECORDSTATE_RECORDING)
                }
        } catch (_: Exception) {
            audioFocus.release()
            throw VoiceException(AssistantMessages.MIC_FAILED)
        }

        val pcm = PcmBuffer()
        recorder = next
        buffer = pcm
        focus = audioFocus
        recording.set(true)
        worker = Thread({
            val chunk = ByteArray(minimum)
            while (recording.get()) {
                val count = next.read(chunk, 0, chunk.size, AudioRecord.READ_BLOCKING)
                if (count < 0) break
                if (count == 0) continue
                _level.value = Pcm.level(chunk, count)
                val room = synchronized(pcm) { pcm.append(chunk, count) }
                if (!room) {
                    main.post { if (recording.get() && buffer === pcm) onInterrupted(true) }
                    break
                }
            }
        }, "pilot-voice-capture").apply { start() }
    }

    @Synchronized
    override fun stop(): ByteArray {
        val pcm = buffer
        if (!recording.getAndSet(false)) return ByteArray(0)
        runCatching { recorder?.stop() }
        runCatching { worker?.join(1_500) }
        runCatching { recorder?.release() }
        focus?.release()
        recorder = null
        worker = null
        buffer = null
        focus = null
        _level.value = 0f
        return pcm?.let { synchronized(it) { it.toUpload() } } ?: ByteArray(0)
    }

    override fun cancel() {
        stop()
    }
}

class AndroidReplyPlayer(context: Context) : ReplyPlayer {
    private val appContext = context.applicationContext
    private var player: MediaPlayer? = null
    private var focus: AssistantAudioFocus? = null
    private var onDone: ((Boolean) -> Unit)? = null

    override fun play(audio: ByteArray, onDone: (played: Boolean) -> Unit) {
        stop()
        val audioFocus = AssistantAudioFocus(appContext, exclusive = false) { finish(played = true) }
        if (audio.isEmpty() || !audioFocus.acquire()) {
            onDone(false)
            return
        }
        focus = audioFocus
        this.onDone = onDone
        try {
            player = MediaPlayer().apply {
                setAudioAttributes(assistantAttributes())
                setOnPreparedListener { if (player === it) it.start() }
                setOnCompletionListener { if (player === it) finish(played = true) }
                setOnErrorListener { failed, _, _ ->
                    if (player === failed) finish(played = false)
                    true
                }
                setDataSource(BytesSource(audio))
                prepareAsync()
            }
        } catch (_: Exception) {
            finish(played = false)
        }
    }

    override fun stop() {
        onDone = null
        release()
    }

    /** How far into the reply playback is, in ms; 0 when nothing is playing. */
    fun positionMs(): Int = runCatching { player?.takeIf { it.isPlaying }?.currentPosition ?: 0 }.getOrDefault(0)

    private fun finish(played: Boolean) {
        val callback = onDone
        onDone = null
        release()
        callback?.invoke(played)
    }

    private fun release() {
        player?.let { active ->
            player = null
            runCatching { active.stop() }
            runCatching { active.release() }
        }
        focus?.release()
        focus = null
    }

    /** Lets MediaPlayer read the reply from memory: nothing is written to disk. */
    private class BytesSource(private val data: ByteArray) : MediaDataSource() {
        override fun readAt(position: Long, buffer: ByteArray, offset: Int, size: Int): Int {
            if (position >= data.size) return -1
            val count = size.coerceAtMost(data.size - position.toInt())
            System.arraycopy(data, position.toInt(), buffer, offset, count)
            return count
        }

        override fun getSize(): Long = data.size.toLong()

        override fun close() = Unit
    }
}
