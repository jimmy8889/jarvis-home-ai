package com.jameshazell.pilot.ui.assistant

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.core.Outcome
import com.jameshazell.pilot.data.pilot.PilotRepository
import com.jameshazell.pilot.data.pilot.PilotSnapshot
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** What the screen can ask for. The ViewModel implements it; previews use the no-op defaults. */
interface AssistantActions {
    fun setDraft(text: String) {}
    fun sendText() {}
    /** @return true when recording actually began. */
    fun startRecording(): Boolean = false
    fun finishRecording() {}
    /** Stop whatever is happening: discard a recording, cancel a question, silence a reply. */
    fun stop() {}
    fun microphoneDenied() {}
    fun dismissError() {}
    fun newConversation() {}
}

/**
 * The conversation with the house assistant. Activity-scoped, so the thread, the conversation id
 * and a reply in progress survive switching destinations and folding / unfolding.
 */
class AssistantViewModel(
    private val pilot: PilotRepository,
    private val recorder: VoiceRecorder,
    private val player: ReplyPlayer,
    private val io: CoroutineDispatcher,
) : ViewModel(), AssistantActions {
    /** Rooms come from the snapshot; a typed question is always asked on behalf of a room. */
    val snapshot: StateFlow<LoadState<PilotSnapshot>> = pilot.snapshot
    val selectedRoomId: StateFlow<String?> = pilot.selectedRoomId

    private val _ui = MutableStateFlow(AssistantUiState())
    val ui: StateFlow<AssistantUiState> = _ui.asStateFlow()

    /** Microphone loudness while listening, 0 to 1. */
    val level: StateFlow<Float> = recorder.level

    private var work: Job? = null
    private var limit: Job? = null
    private var visible = false

    fun onScreenStarted() {
        visible = true
    }

    /** The screen was left or the app went to the background: the microphone must not stay open. */
    fun onScreenStopped() {
        visible = false
        when (_ui.value.phase) {
            AssistantPhase.Listening -> {
                discardRecording()
                _ui.update { AssistantReducer.failed(it, AssistantMessages.BACKGROUNDED) }
            }
            AssistantPhase.Speaking -> {
                player.stop()
                _ui.update { it.copy(phase = AssistantPhase.Idle) }
            }
            // A question in flight still gets its written answer; it just isn't spoken.
            AssistantPhase.Thinking, AssistantPhase.Idle -> Unit
        }
    }

    override fun setDraft(text: String) = _ui.update { it.copy(draft = text) }

    override fun dismissError() = _ui.update { it.copy(error = null) }

    override fun newConversation() {
        stop()
        _ui.update { AssistantUiState(draft = it.draft) }
    }

    override fun sendText() {
        val state = _ui.value
        val text = state.draft.trim()
        if (text.isEmpty() || state.phase == AssistantPhase.Listening || state.phase == AssistantPhase.Thinking) return
        if (state.phase == AssistantPhase.Speaking) player.stop()
        val roomId = selectedRoomId.value ?: snapshot.value.valueOrNull()?.media?.rooms?.firstOrNull()?.id
        if (roomId == null) {
            _ui.update { AssistantReducer.failed(it, AssistantMessages.NO_ROOM) }
            return
        }
        _ui.update { AssistantReducer.asked(it, text) }
        work = viewModelScope.launch {
            when (val result = pilot.ask(text, roomId, state.conversationId)) {
                is Outcome.Success -> _ui.update { AssistantReducer.replied(it, result.value, viaVoice = false) }
                is Outcome.Failure -> _ui.update { AssistantReducer.failed(it, result.error.message) }
            }
        }
    }

    override fun startRecording(): Boolean {
        when (_ui.value.phase) {
            AssistantPhase.Listening, AssistantPhase.Thinking -> return false
            AssistantPhase.Speaking -> player.stop()
            AssistantPhase.Idle -> Unit
        }
        try {
            recorder.start { limitReached ->
                if (limitReached) finishRecording()
                else if (_ui.value.phase == AssistantPhase.Listening) {
                    discardRecording()
                    _ui.update { AssistantReducer.failed(it, AssistantMessages.INTERRUPTED) }
                }
            }
        } catch (error: VoiceException) {
            _ui.update { AssistantReducer.failed(it, error.message ?: AssistantMessages.MIC_FAILED) }
            return false
        } catch (_: Exception) {
            _ui.update { AssistantReducer.failed(it, AssistantMessages.MIC_FAILED) }
            return false
        }
        _ui.update { it.copy(phase = AssistantPhase.Listening, error = null) }
        limit?.cancel()
        limit = viewModelScope.launch {
            delay(Pcm.MAX_RECORDING_MS)
            finishRecording()
        }
        return true
    }

    /** Stops listening and sends what was said. */
    override fun finishRecording() {
        if (_ui.value.phase != AssistantPhase.Listening) return
        limit?.cancel()
        _ui.update { it.copy(phase = AssistantPhase.Thinking) }
        work = viewModelScope.launch {
            val pcm = withContext(io) { recorder.stop() }
            if (!Pcm.isLongEnough(pcm.size)) {
                _ui.update { AssistantReducer.failed(it, AssistantMessages.TOO_SHORT) }
                return@launch
            }
            when (val result = pilot.voice(pcm, Pcm.SAMPLE_RATE, _ui.value.conversationId)) {
                is Outcome.Failure -> _ui.update { AssistantReducer.failed(it, result.error.message) }
                is Outcome.Success -> {
                    _ui.update { AssistantReducer.replied(it, result.value, viaVoice = true) }
                    result.value.audioDownloadUrl?.takeIf { it.isNotBlank() && visible }?.let { speak(it) }
                }
            }
        }
    }

    private suspend fun speak(path: String) {
        _ui.update { it.copy(phase = AssistantPhase.Thinking) }
        val audio = pilot.audio(path).valueOrNull()
        if (audio == null || !visible) {
            _ui.update { it.copy(phase = AssistantPhase.Idle, error = if (audio == null) AssistantMessages.PLAYBACK_FAILED else it.error) }
            return
        }
        _ui.update { it.copy(phase = AssistantPhase.Speaking) }
        player.play(audio) { played ->
            _ui.update {
                if (it.phase != AssistantPhase.Speaking) it
                else it.copy(phase = AssistantPhase.Idle, error = if (played) it.error else AssistantMessages.PLAYBACK_FAILED)
            }
        }
    }

    override fun stop() {
        when (_ui.value.phase) {
            AssistantPhase.Listening -> discardRecording()
            AssistantPhase.Thinking -> {
                work?.cancel()
                // If the cancel landed before the recording was collected, the microphone is still open.
                discardRecording()
            }
            AssistantPhase.Speaking -> player.stop()
            AssistantPhase.Idle -> Unit
        }
        _ui.update { it.copy(phase = AssistantPhase.Idle) }
    }

    override fun microphoneDenied() = _ui.update { AssistantReducer.failed(it, AssistantMessages.MIC_DENIED) }

    private fun discardRecording() {
        limit?.cancel()
        viewModelScope.launch(io) { recorder.cancel() }
    }

    override fun onCleared() {
        // viewModelScope is already cancelled here, so release the microphone directly.
        runCatching { recorder.cancel() }
        player.stop()
    }
}
