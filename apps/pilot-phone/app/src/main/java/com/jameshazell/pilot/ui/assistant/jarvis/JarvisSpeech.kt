package com.jameshazell.pilot.ui.assistant.jarvis

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import androidx.core.content.ContextCompat
import com.jameshazell.pilot.data.jarvis.Wav
import com.jameshazell.pilot.ui.assistant.AssistantAudioFocus
import java.io.ByteArrayOutputStream
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.sqrt
import kotlin.concurrent.thread

internal fun hasMicrophonePermission(context: Context): Boolean =
    ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

/**
 * Android's explicitly on-device speech recogniser (never a cloud one), as the JARVIS app uses
 * it. All calls and callbacks are on the main thread.
 */
internal class PhoneRecognizer(context: Context) {
    interface Listener {
        fun onLevel(level: Float)
        fun onPartial(text: String)
        fun onEndOfSpeech()
        /** Final transcript; null when nothing was recognised. */
        fun onResult(text: String?)
        /** @param fatal on-device recognition does not work here: fall back to the laptop. */
        fun onError(noSpeech: Boolean, fatal: Boolean)
    }

    private val appContext = context.applicationContext
    private var recognizer: SpeechRecognizer? = null
    private var active = false

    val available: Boolean = runCatching { SpeechRecognizer.isOnDeviceRecognitionAvailable(appContext) }.getOrDefault(false)

    /** @return false when the recogniser could not be started. */
    fun start(listener: Listener): Boolean = runCatching {
        val engine = recognizer ?: SpeechRecognizer.createOnDeviceSpeechRecognizer(appContext).also { recognizer = it }
        active = true
        engine.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) = Unit
            override fun onBeginningOfSpeech() = Unit
            override fun onBufferReceived(buffer: ByteArray?) = Unit
            override fun onEvent(eventType: Int, params: Bundle?) = Unit
            override fun onRmsChanged(rmsdB: Float) {
                if (active) listener.onLevel((rmsdB / 12f).coerceIn(0f, 1f))
            }

            override fun onEndOfSpeech() {
                if (active) listener.onEndOfSpeech()
            }

            override fun onError(error: Int) {
                if (!active) return
                active = false
                when (error) {
                    SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> listener.onError(noSpeech = true, fatal = false)
                    SpeechRecognizer.ERROR_CLIENT -> listener.onError(noSpeech = false, fatal = false)
                    else -> listener.onError(noSpeech = false, fatal = true)
                }
            }

            override fun onResults(results: Bundle?) {
                if (!active) return
                active = false
                listener.onResult(results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.takeIf(String::isNotBlank))
            }

            override fun onPartialResults(partialResults: Bundle?) {
                val text = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()
                if (active && !text.isNullOrBlank()) listener.onPartial(text)
            }
        })
        engine.startListening(
            Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-AU")
                .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true),
        )
        true
    }.getOrElse {
        active = false
        false
    }

    /** The speaker has finished: produce the result now. */
    fun finish() {
        if (active) runCatching { recognizer?.stopListening() }
    }

    /** Stop and report nothing. */
    fun cancel() {
        active = false
        runCatching { recognizer?.cancel() }
    }

    fun destroy() {
        active = false
        runCatching { recognizer?.destroy() }
        recognizer = null
    }
}

/**
 * The phone's own voice: an installed offline en-GB voice at the JARVIS app's rate and pitch.
 * [ready] stays false when there is no such voice. Callbacks are on the main thread.
 */
internal class PhoneVoice(context: Context, private val onReadyChanged: (Boolean) -> Unit) {
    private val main = Handler(Looper.getMainLooper())
    private val sequence = AtomicInteger()
    private var onDone: ((Boolean) -> Unit)? = null
    private var current = ""
    var ready = false
        private set

    private val tts: TextToSpeech = TextToSpeech(context.applicationContext) { result ->
        if (result == TextToSpeech.SUCCESS) runCatching { chooseVoice() }
    }

    private fun chooseVoice() {
        val voice = tts.voices?.firstOrNull { it.locale.language == "en" && it.locale.country == "GB" && !it.isNetworkConnectionRequired } ?: return
        tts.voice = voice
        tts.setSpeechRate(1.03f)
        tts.setPitch(0.90f)
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) = Unit
            override fun onDone(utteranceId: String?) = finished(utteranceId, true)
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) = finished(utteranceId, false)
            override fun onError(utteranceId: String?, errorCode: Int) = finished(utteranceId, false)
        })
        ready = true
        main.post { onReadyChanged(true) }
    }

    private fun finished(id: String?, spoken: Boolean) {
        main.post {
            if (id != current) return@post
            val callback = onDone
            onDone = null
            callback?.invoke(spoken)
        }
    }

    /** @param onDone called once when the reply has been spoken (`true`) or could not be. */
    fun speak(text: String, onDone: (Boolean) -> Unit) {
        stop()
        if (!ready) {
            onDone(false)
            return
        }
        current = "reply-${sequence.incrementAndGet()}"
        this.onDone = onDone
        if (tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, current) != TextToSpeech.SUCCESS) {
            this.onDone = null
            onDone(false)
        }
    }

    /** Silence now; `onDone` is not called. */
    fun stop() {
        onDone = null
        current = ""
        runCatching { tts.stop() }
    }

    fun shutdown() {
        stop()
        runCatching { tts.shutdown() }
    }
}

/**
 * Records for the laptop's recogniser when the phone has none: 16 kHz mono 16-bit, ending by
 * itself when the speaker stops ([SilenceDetector]). Callbacks are on the main thread.
 */
internal class BridgeRecorder(context: Context) {
    private val appContext = context.applicationContext
    private val main = Handler(Looper.getMainLooper())
    private val generation = AtomicInteger()
    @Volatile private var finishing = false

    /**
     * @param onDone a complete WAV when speech was heard, else null with [problem] saying why.
     * @return false (after calling [onDone]) when the microphone could not be opened.
     */
    @SuppressLint("MissingPermission") // Checked on the first line.
    fun start(onLevel: (Float) -> Unit, onDone: (wav: ByteArray?, problem: String?) -> Unit): Boolean {
        if (!hasMicrophonePermission(appContext)) {
            onDone(null, JarvisText.MIC_DENIED)
            return false
        }
        val run = generation.incrementAndGet()
        finishing = false
        val focus = AssistantAudioFocus(appContext, exclusive = true) { if (generation.get() == run) finishing = true }
        val size = AudioRecord.getMinBufferSize(Wav.SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT).coerceAtLeast(3_200)
        val recorder = runCatching {
            check(focus.acquire())
            AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, Wav.SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, size * 2)
                .also {
                    check(it.state == AudioRecord.STATE_INITIALIZED)
                    it.startRecording()
                }
        }.getOrElse {
            focus.release()
            onDone(null, JarvisText.MIC_FAILED)
            return false
        }
        thread(name = "jarvis-capture") {
            val pcm = ByteArrayOutputStream()
            val samples = ShortArray(1_600)
            val detector = SilenceDetector(SystemClock.elapsedRealtime())
            var failed = false
            try {
                while (generation.get() == run && !finishing) {
                    val count = recorder.read(samples, 0, samples.size)
                    if (count < 0) {
                        failed = true
                        break
                    }
                    var sum = 0.0
                    for (i in 0 until count) {
                        val sample = samples[i].toInt()
                        sum += sample.toDouble() * sample
                        pcm.write(sample and 0xff)
                        pcm.write((sample shr 8) and 0xff)
                    }
                    val rms = sqrt(sum / count.coerceAtLeast(1))
                    val level = (rms / SilenceDetector.FULL_SCALE_RMS).coerceAtMost(1.0).toFloat()
                    main.post { if (generation.get() == run) onLevel(level) }
                    if (!detector.feed(rms, SystemClock.elapsedRealtime())) break
                }
            } finally {
                runCatching { recorder.stop() }
                runCatching { recorder.release() }
            }
            main.post {
                focus.release()
                if (generation.get() != run) return@post // Cancelled: say nothing.
                generation.incrementAndGet()
                val bytes = pcm.toByteArray()
                when {
                    failed -> onDone(null, JarvisText.MIC_FAILED)
                    !detector.heard || !Wav.acceptable(bytes.size) -> onDone(null, JarvisText.NO_SPEECH)
                    else -> onDone(Wav.wrap(bytes), null)
                }
            }
        }
        return true
    }

    /** The speaker has finished: send what was heard. */
    fun finish() {
        finishing = true
    }

    /** Stop and discard. */
    fun cancel() {
        generation.incrementAndGet()
    }
}
