package com.jameshazell.pilot.ui.assistant.jarvis

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jameshazell.pilot.core.Outcome
import com.jameshazell.pilot.data.jarvis.JarvisConnection
import com.jameshazell.pilot.data.jarvis.JarvisMessage
import com.jameshazell.pilot.data.jarvis.JarvisPairing
import com.jameshazell.pilot.data.jarvis.JarvisPhase
import com.jameshazell.pilot.data.jarvis.JarvisReply
import com.jameshazell.pilot.data.jarvis.JarvisRepository
import com.jameshazell.pilot.data.jarvis.JarvisTelemetryState
import com.jameshazell.pilot.data.jarvis.JarvisTurnEvent
import com.jameshazell.pilot.data.jarvis.JarvisTurnMachine
import com.jameshazell.pilot.data.jarvis.JarvisTurnState
import com.jameshazell.pilot.data.jarvis.JarvisVoiceMode
import com.jameshazell.pilot.data.jarvis.JarvisProtocol
import com.jameshazell.pilot.data.jarvis.Wav
import com.jameshazell.pilot.ui.assistant.AndroidReplyPlayer
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Screen-only state. Everything else comes from [JarvisRepository].
 *
 * @param continuous listen again after each spoken reply while the tab is visible.
 * @param onDeviceRecognition speech is recognised on this phone (else recorded for the laptop).
 * @param localNotice a phone-side tip (voice selection, Clear refused) for the hint line.
 */
data class JarvisUiState(
    val draft: String = "",
    val continuous: Boolean = false,
    val sheetOpen: Boolean = false,
    val pairAddress: String = "",
    val pairCode: String = "",
    val phoneVoiceReady: Boolean = false,
    val onDeviceRecognition: Boolean = false,
    val localNotice: String? = null,
)

/** What the JARVIS screen can ask for. The ViewModel implements it; previews use the defaults. */
interface JarvisActions {
    /** @return true when the microphone opened. */
    fun listen(): Boolean = false
    fun finishListening() {}
    /** Stop listening, the turn in flight, and any speech. */
    fun stop() {}
    fun setDraft(text: String) {}
    fun sendText() {}
    fun ask(prompt: String) {}
    fun setContinuous(enabled: Boolean) {}
    fun selectVoice(mode: JarvisVoiceMode) {}
    fun clearConversation() {}
    fun retryConnection() {}
    fun openSheet() {}
    fun closeSheet() {}
    fun setPairAddress(text: String) {}
    fun setPairCode(text: String) {}
    fun pair() {}
    fun unpair() {}
    fun microphoneDenied() {}
}

/**
 * Runs the JARVIS conversation: decides how to listen (this phone's offline recogniser first,
 * the laptop's as fallback), hands turns to the repository, and speaks the replies in the chosen
 * voice. Activity-scoped, so it survives switching tabs and folding.
 */
class JarvisViewModel(private val jarvis: JarvisRepository, context: Context) : ViewModel(), JarvisActions {
    private val appContext = context.applicationContext

    val connection: StateFlow<JarvisConnection> = jarvis.connection
    val pairing: StateFlow<JarvisPairing> = jarvis.pairing
    val telemetry: StateFlow<JarvisTelemetryState> = jarvis.telemetry
    val conversation: StateFlow<List<JarvisMessage>> = jarvis.conversation
    val turn: StateFlow<JarvisTurnState> = jarvis.turn
    val voiceMode: StateFlow<JarvisVoiceMode> = jarvis.voiceMode

    private val recognizer = PhoneRecognizer(appContext)
    private val recorder = BridgeRecorder(appContext)
    private val player = AndroidReplyPlayer(appContext)
    private val phoneVoice = PhoneVoice(appContext) { ready -> _ui.update { it.copy(phoneVoiceReady = ready) } }

    private val _ui = MutableStateFlow(JarvisUiState(onDeviceRecognition = recognizer.available))
    val ui: StateFlow<JarvisUiState> = _ui.asStateFlow()

    private val _level = MutableStateFlow(0f)
    /** Microphone loudness while listening, the reply's own envelope while speaking; 0 to 1. */
    val level: StateFlow<Float> = _level.asStateFlow()

    /** Time source for telemetry freshness. */
    fun now(): Long = jarvis.clock()

    private var visible = false
    private var usingRecognizer = false
    private var meter: Job? = null
    private var again: Job? = null

    init {
        viewModelScope.launch { jarvis.replies.collect(::speak) }
        viewModelScope.launch {
            // A pilot://jarvis link fills in the pairing sheet; the user still presses Connect.
            jarvis.pairing.collect { state ->
                state.offered?.let { link ->
                    _ui.update { it.copy(sheetOpen = true, pairAddress = link.host, pairCode = link.code) }
                    jarvis.dismissOfferedLink()
                }
            }
        }
    }

    fun onShown() {
        visible = true
        jarvis.setVisible(true)
    }

    /** The tab was left or the app went out of view: microphone, speech and the turn all stop. */
    fun onHidden() {
        visible = false
        _ui.update { it.copy(continuous = false) }
        stop()
        jarvis.setVisible(false)
    }

    private val phase: JarvisPhase get() = jarvis.turn.value.phase
    private val paired: Boolean get() = jarvis.pairing.value.paired

    // ---- Listening --------------------------------------------------------------------------

    override fun listen(): Boolean {
        if (!paired) {
            openSheet()
            return false
        }
        if (!visible || !JarvisTurnMachine.canBegin(jarvis.turn.value)) return false
        if (!hasMicrophonePermission(appContext)) {
            microphoneDenied()
            return false
        }
        silence()
        again?.cancel()
        _ui.update { it.copy(localNotice = null) }
        usingRecognizer = _ui.value.onDeviceRecognition
        val started = if (usingRecognizer) recognizer.start(recognitionListener) else startRecorder()
        if (usingRecognizer && !started) {
            // The recogniser would not start: use the laptop's from now on.
            _ui.update { it.copy(onDeviceRecognition = false) }
            usingRecognizer = false
            if (!startRecorder()) return false
        } else if (!started) return false
        jarvis.report(JarvisTurnEvent.ListeningStarted)
        return true
    }

    private fun startRecorder(): Boolean {
        var problem: String? = null
        val started = recorder.start(onLevel = { _level.value = it }) { wav, why ->
            _level.value = 0f
            if (wav == null) {
                problem = why
                jarvis.report(JarvisTurnEvent.ListeningFailed(why))
            } else if (!jarvis.submit("", wav)) jarvis.report(JarvisTurnEvent.ListeningFailed(null))
        }
        if (!started) _ui.update { it.copy(localNotice = problem ?: JarvisText.MIC_FAILED) }
        return started
    }

    private val recognitionListener = object : PhoneRecognizer.Listener {
        override fun onLevel(level: Float) {
            _level.value = level
        }

        override fun onPartial(text: String) = jarvis.report(JarvisTurnEvent.Heard(text))

        override fun onEndOfSpeech() = jarvis.report(JarvisTurnEvent.ListeningEnded)

        override fun onResult(text: String?) {
            _level.value = 0f
            if (text == null || !jarvis.submit(text, null)) jarvis.report(JarvisTurnEvent.ListeningFailed(JarvisText.NO_SPEECH.takeIf { text == null }))
        }

        override fun onError(noSpeech: Boolean, fatal: Boolean) {
            _level.value = 0f
            if (fatal) _ui.update { it.copy(onDeviceRecognition = false) }
            jarvis.report(
                JarvisTurnEvent.ListeningFailed(
                    when {
                        noSpeech -> JarvisText.NO_SPEECH
                        fatal -> JarvisText.PHONE_ASR_FAILED
                        else -> null
                    },
                ),
            )
        }
    }

    override fun finishListening() {
        if (phase != JarvisPhase.Listening) return
        if (usingRecognizer) recognizer.finish() else recorder.finish()
    }

    override fun microphoneDenied() = _ui.update { it.copy(localNotice = JarvisText.MIC_DENIED) }

    // ---- Turns ------------------------------------------------------------------------------

    override fun setDraft(text: String) = _ui.update { it.copy(draft = text.take(JarvisProtocol.MAX_TEXT)) }

    override fun sendText() {
        val text = _ui.value.draft.trim()
        if (text.isEmpty()) return
        if (send(text)) _ui.update { it.copy(draft = "") }
    }

    override fun ask(prompt: String) {
        send(prompt)
    }

    private fun send(text: String): Boolean {
        if (!paired) {
            openSheet()
            return false
        }
        if (!JarvisTurnMachine.canBegin(jarvis.turn.value)) return false
        silence()
        again?.cancel()
        _ui.update { it.copy(localNotice = null) }
        return jarvis.submit(text, null)
    }

    override fun stop() {
        again?.cancel()
        recognizer.cancel()
        recorder.cancel()
        silence()
        _level.value = 0f
        jarvis.stopTurn()
    }

    /** Stops any reply being spoken (playback or phone voice). */
    private fun silence() {
        meter?.cancel()
        player.stop()
        phoneVoice.stop()
        _level.value = 0f
        if (phase == JarvisPhase.Speaking) jarvis.report(JarvisTurnEvent.SpeakingFinished())
    }

    // ---- Speaking ---------------------------------------------------------------------------

    private fun speak(reply: JarvisReply) {
        if (!visible) return
        val audio = reply.audio
        when {
            reply.mode == JarvisVoiceMode.VoiceStudio && audio != null -> {
                val levels = Wav.playbackLevels(audio)
                jarvis.report(JarvisTurnEvent.SpeakingStarted)
                player.play(audio) { played -> spoken(if (played) null else JarvisText.PLAYBACK_FAILED) }
                meter?.cancel()
                meter = viewModelScope.launch {
                    // The reactor's bars follow the reply's real loudness, 30 windows a second.
                    while (true) {
                        _level.value = levels.getOrElse(player.positionMs() / 33) { 0f }
                        delay(33)
                    }
                }
            }
            reply.mode == JarvisVoiceMode.PhoneVoice && _ui.value.phoneVoiceReady -> {
                jarvis.report(JarvisTurnEvent.SpeakingStarted)
                phoneVoice.speak(reply.text) { said -> spoken(if (said) null else JarvisText.PHONE_SPEECH_FAILED) }
            }
            reply.speechError == null -> listenAgain()
        }
    }

    private fun spoken(problem: String?) {
        meter?.cancel()
        _level.value = 0f
        jarvis.report(JarvisTurnEvent.SpeakingFinished(problem))
        if (problem == null) listenAgain()
    }

    /** Continuous conversation: half a second after a reply, listen again, if still wanted. */
    private fun listenAgain() {
        if (!_ui.value.continuous || voiceMode.value == JarvisVoiceMode.Off || !visible) return
        again?.cancel()
        again = viewModelScope.launch {
            delay(JarvisProtocol.LISTEN_AGAIN_MS)
            if (_ui.value.continuous && visible && phase == JarvisPhase.Standby) listen()
        }
    }

    override fun setContinuous(enabled: Boolean) {
        if (!enabled) again?.cancel()
        _ui.update { it.copy(continuous = enabled, localNotice = JarvisText.CONTINUOUS_ON.takeIf { enabled }) }
    }

    override fun selectVoice(mode: JarvisVoiceMode) {
        silence()
        if (mode == JarvisVoiceMode.PhoneVoice && !_ui.value.phoneVoiceReady) {
            jarvis.setVoiceMode(JarvisVoiceMode.Off)
            _ui.update { it.copy(localNotice = JarvisText.NO_PHONE_VOICE) }
        } else {
            jarvis.setVoiceMode(mode)
            _ui.update { it.copy(localNotice = null) }
        }
    }

    override fun clearConversation() {
        if (!jarvis.clearConversation()) _ui.update { it.copy(localNotice = JarvisText.STOP_FIRST) }
    }

    // ---- Connection and pairing -------------------------------------------------------------

    override fun retryConnection() = jarvis.retryNow()

    override fun openSheet() = _ui.update { it.copy(sheetOpen = true) }

    override fun closeSheet() = _ui.update { it.copy(sheetOpen = false, pairCode = "") }

    override fun setPairAddress(text: String) = _ui.update { it.copy(pairAddress = text) }

    override fun setPairCode(text: String) = _ui.update { it.copy(pairCode = text) }

    override fun pair() {
        val state = _ui.value
        viewModelScope.launch {
            if (jarvis.pair(state.pairAddress, state.pairCode) is Outcome.Success) {
                _ui.update { it.copy(sheetOpen = false, pairCode = "", localNotice = null) }
            }
        }
    }

    override fun unpair() {
        stop()
        viewModelScope.launch { jarvis.unpair() }
    }

    override fun onCleared() {
        recognizer.destroy()
        recorder.cancel()
        player.stop()
        phoneVoice.shutdown()
    }
}
