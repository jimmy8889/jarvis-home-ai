package com.jarvis.pilotwall

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaPlayer
import android.media.MediaRecorder
import java.io.ByteArrayOutputStream
import java.net.URI
import java.net.URLDecoder
import java.util.concurrent.atomic.AtomicBoolean

/** Captures the exact PCM format accepted by Pilot Core's device voice API. */
class PilotVoiceCapture {
    private val recording = AtomicBoolean(false)
    private var recorder: AudioRecord? = null
    private var worker: Thread? = null
    private var output: ByteArrayOutputStream? = null

    @SuppressLint("MissingPermission")
    fun start() {
        check(!recording.get()) { "Voice capture is already active" }
        val minimum = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        ).coerceAtLeast(4_096)
        val next = AudioRecord.Builder()
            .setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(SAMPLE_RATE)
                    .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                    .build(),
            )
            .setBufferSizeInBytes(minimum * 2)
            .build()
        check(next.state == AudioRecord.STATE_INITIALIZED) {
            "The tablet microphone could not be initialized"
        }
        recorder = next
        output = ByteArrayOutputStream()
        recording.set(true)
        next.startRecording()
        worker = Thread({
            val buffer = ByteArray(minimum)
            while (recording.get()) {
                val count = next.read(buffer, 0, buffer.size, AudioRecord.READ_BLOCKING)
                if (count > 0) output?.write(buffer, 0, count)
            }
        }, "pilot-voice-capture").apply { start() }
    }

    fun stop(): ByteArray {
        if (!recording.getAndSet(false)) return byteArrayOf()
        runCatching { recorder?.stop() }
        worker?.join(1_500)
        recorder?.release()
        recorder = null
        worker = null
        val content = output?.toByteArray() ?: byteArrayOf()
        output = null
        return content
    }

    fun cancel() {
        stop()
    }

    companion object {
        const val SAMPLE_RATE = 16_000
    }
}

/** Plays Core-generated TTS without exposing a backend credential to MediaPlayer. */
class PilotReplyPlayer(private val context: Context) {
    private var player: MediaPlayer? = null

    fun play(content: ByteArray, onComplete: (Result<Unit>) -> Unit) {
        stop()
        val file = kotlin.io.path.createTempFile(
            context.cacheDir.toPath(),
            "pilot-reply-",
            ".audio",
        ).toFile()
        file.writeBytes(content)
        val next = MediaPlayer().apply {
            setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANT)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build(),
            )
            setOnCompletionListener {
                file.delete()
                stop()
                onComplete(Result.success(Unit))
            }
            setOnErrorListener { _, what, extra ->
                file.delete()
                stop()
                onComplete(Result.failure(IllegalStateException("TTS playback failed ($what/$extra)")))
                true
            }
            file.inputStream().use { setDataSource(it.fd) }
            prepare()
        }
        player = next
        next.start()
    }

    fun stop() {
        player?.let { active ->
            runCatching { active.stop() }
            active.release()
        }
        player = null
    }
}

data class PairingPayload(val coreUrl: String, val grantToken: String) {
    companion object {
        /**
         * Supported QR/deep-link form:
         * pilot://pair?core=http%3A%2F%2F10.0.1.64%3A8770&grant=single-use-token
         */
        fun parse(value: String, fallbackCoreUrl: String? = null): PairingPayload {
            val trimmed = value.trim()
            require(trimmed.isNotEmpty()) { "Enter a one-time pairing grant" }
            if (trimmed.startsWith("pilot://", ignoreCase = true)) {
                val uri = URI(trimmed)
                require(uri.host == "pair") { "This is not a Pilot pairing code" }
                val query = uri.rawQuery.orEmpty().split('&').mapNotNull { part ->
                    val pair = part.split('=', limit = 2)
                    if (pair.size != 2) null else {
                        URLDecoder.decode(pair[0], Charsets.UTF_8.name()) to
                            URLDecoder.decode(pair[1], Charsets.UTF_8.name())
                    }
                }.toMap()
                val core = query["core"] ?: fallbackCoreUrl
                val grant = query["grant"] ?: query["token"]
                require(!core.isNullOrBlank() && !grant.isNullOrBlank()) {
                    "The pairing QR is incomplete"
                }
                return PairingPayload(CoreAddressPolicy.normalize(core), grant)
            }
            require(!fallbackCoreUrl.isNullOrBlank()) {
                "Enter the Pilot Core address for this grant"
            }
            return PairingPayload(CoreAddressPolicy.normalize(fallbackCoreUrl), trimmed)
        }
    }
}
