package com.jameshazell.pilot.ui.control

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.core.Outcome
import com.jameshazell.pilot.data.control.ControlApproval
import com.jameshazell.pilot.data.control.ControlConnection
import com.jameshazell.pilot.data.control.ControlConversation
import com.jameshazell.pilot.data.control.ControlEvent
import com.jameshazell.pilot.data.control.ControlOverview
import com.jameshazell.pilot.data.control.ControlRepository
import com.jameshazell.pilot.data.control.ControlTarget
import com.jameshazell.pilot.data.control.ControlTaskEvent
import com.jameshazell.pilot.data.control.ControlTranscript
import java.util.UUID
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** A detail pane's content, loaded on demand. Keeps the last [value] visible while reloading. */
data class DetailLoad<T>(val loading: Boolean = false, val value: T? = null, val error: String? = null)

/**
 * Everything the Control destination shows besides the repository's lists. It lives in the
 * activity-scoped ViewModel, so it survives switching destinations and folding / unfolding.
 */
data class ControlUiState(
    val section: ControlSection = ControlSection.Chat,
    val draft: String = "",
    val target: ControlTarget = ControlTarget.Auto,
    /** Project the next message is about; null lets James Control decide. */
    val projectId: String? = null,
    val chat: ChatState = ChatState(),
    val approvals: ApprovalUi = ApprovalUi(),
    val selectedProjectId: String? = null,
    val selectedTaskId: String? = null,
    val selectedWorkerId: String? = null,
    /** Open in the Conversations section. */
    val selectedConversationId: String? = null,
    /** Open beside the conversation list in Chat (two-pane only); null shows the live thread. */
    val chatConversationId: String? = null,
    val timelines: Map<String, DetailLoad<List<ControlTaskEvent>>> = emptyMap(),
    val transcripts: Map<String, DetailLoad<ControlTranscript>> = emptyMap(),
)

/** What the screen can ask for. The ViewModel implements it; previews use the no-op defaults. */
interface ControlActions {
    fun refresh() {}
    fun retryConnection() {}
    fun reconnectAfterRenewal() {}
    fun selectSection(section: ControlSection) {}
    fun setDraft(text: String) {}
    fun setTarget(target: ControlTarget) {}
    fun setProject(projectId: String?) {}
    fun send() {}
    fun retrySend(key: String) {}
    fun askAcceptApproval(approval: ControlApproval) {}
    fun dismissApprovalConfirm() {}
    fun decideApproval(approval: ControlApproval, accept: Boolean) {}
    fun selectProject(projectId: String?) {}
    fun chatAboutProject(projectId: String) {}
    fun selectTask(taskId: String?) {}
    fun openTask(taskId: String) {}
    fun reloadTimeline(taskId: String) {}
    fun selectWorker(workerId: String?) {}
    fun selectConversation(conversation: ControlConversation?) {}
    fun selectChatConversation(conversation: ControlConversation?) {}
    fun reloadTranscript(conversation: ControlConversation) {}
}

class ControlViewModel(private val control: ControlRepository) : ViewModel(), ControlActions {
    val overview: StateFlow<LoadState<ControlOverview>> = control.overview
    val connection: StateFlow<ControlConnection> = control.connection
    val pendingApprovals: StateFlow<List<ControlApproval>> = control.approvals

    private val _ui = MutableStateFlow(ControlUiState())
    val ui: StateFlow<ControlUiState> = _ui.asStateFlow()

    private val timelineJobs = mutableMapOf<String, Job>()
    private val transcriptJobs = mutableMapOf<String, Job>()

    init {
        _ui.update { it.copy(chat = ChatReducer.seed(it.chat, control.messages.value)) }
        viewModelScope.launch { control.socketEvents.collect(::onSocketEvent) }
        viewModelScope.launch {
            control.approvals.collect { pending -> _ui.update { it.copy(approvals = it.approvals.pruned(pending)) } }
        }
    }

    /** The event socket follows the screen: call from LifecycleStartEffect. */
    fun onScreenStarted() {
        control.start()
        // Anything that streamed while this screen was away is only in the repository.
        _ui.update { it.copy(chat = ChatReducer.seed(it.chat, control.messages.value)) }
    }

    fun onScreenStopped() = control.stop()

    override fun refresh() = control.refresh()

    override fun retryConnection() = control.onNetworkAvailable()

    override fun reconnectAfterRenewal() = control.retryAfterSessionRenewal()

    override fun selectSection(section: ControlSection) = _ui.update { it.copy(section = section) }

    // ---- Chat -------------------------------------------------------------------------------

    override fun setDraft(text: String) = _ui.update { it.copy(draft = text) }

    override fun setTarget(target: ControlTarget) = _ui.update { it.copy(target = target) }

    override fun setProject(projectId: String?) = _ui.update { it.copy(projectId = projectId) }

    override fun send() {
        val state = _ui.value
        val text = state.draft.trim()
        if (text.isEmpty() || sendBlockReason(connection.value) != null) return
        val key = UUID.randomUUID().toString()
        _ui.update { it.copy(draft = "", chat = ChatReducer.sending(it.chat, key, text, state.target, state.projectId)) }
        deliver(key)
    }

    /** Sends a failed message again under its original idempotency key. */
    override fun retrySend(key: String) {
        val message = _ui.value.chat.outgoing(key) ?: return
        if (message.state != SendState.Failed || sendBlockReason(connection.value) != null) return
        _ui.update { it.copy(chat = ChatReducer.sending(it.chat, key, message.text, message.target, message.projectId)) }
        deliver(key)
    }

    private fun deliver(key: String) {
        val message = _ui.value.chat.outgoing(key) ?: return
        viewModelScope.launch {
            val result = control.sendMessage(message.text, message.target, message.projectId, idempotencyKey = key)
            _ui.update {
                it.copy(
                    chat = when (result) {
                        is Outcome.Success -> ChatReducer.sent(it.chat, key, result.value)
                        is Outcome.Failure -> ChatReducer.failed(it.chat, key, result.error.message)
                    },
                )
            }
        }
    }

    private fun onSocketEvent(event: ControlEvent) {
        _ui.update { it.copy(chat = ChatReducer.onEvent(it.chat, event)) }
        // Keep an open task timeline in step with what just happened to that task.
        val taskId = when (event) {
            is ControlEvent.TaskUpdated -> event.task?.id
            is ControlEvent.MessageCompleted -> event.id
            else -> null
        }
        if (taskId != null && taskId == _ui.value.selectedTaskId) loadTimeline(taskId)
    }

    // ---- Approvals --------------------------------------------------------------------------

    override fun askAcceptApproval(approval: ControlApproval) = _ui.update { it.copy(approvals = it.approvals.askAccept(approval)) }

    override fun dismissApprovalConfirm() = _ui.update { it.copy(approvals = it.approvals.dismissConfirm()) }

    override fun decideApproval(approval: ControlApproval, accept: Boolean) {
        val begun = _ui.value.approvals.begin(approval.id) ?: return
        _ui.update { it.copy(approvals = begun) }
        viewModelScope.launch {
            val result = control.decideApproval(approval.id, accept)
            _ui.update {
                it.copy(
                    approvals = when (result) {
                        is Outcome.Success -> it.approvals.succeeded(approval.id)
                        is Outcome.Failure -> it.approvals.failed(approval.id, result.error.message)
                    },
                )
            }
        }
    }

    // ---- Lists and details ------------------------------------------------------------------

    override fun selectProject(projectId: String?) = _ui.update { it.copy(selectedProjectId = projectId) }

    override fun chatAboutProject(projectId: String) =
        _ui.update { it.copy(projectId = projectId, section = ControlSection.Chat, chatConversationId = null) }

    override fun selectTask(taskId: String?) {
        _ui.update { it.copy(selectedTaskId = taskId) }
        if (taskId != null) loadTimeline(taskId)
    }

    override fun openTask(taskId: String) {
        _ui.update { it.copy(section = ControlSection.Tasks) }
        selectTask(taskId)
    }

    override fun reloadTimeline(taskId: String) = loadTimeline(taskId)

    private fun loadTimeline(taskId: String) {
        timelineJobs[taskId]?.cancel()
        _ui.update { it.copy(timelines = it.timelines + (taskId to (it.timelines[taskId] ?: DetailLoad()).copy(loading = true, error = null))) }
        timelineJobs[taskId] = viewModelScope.launch {
            val result = control.taskTimeline(taskId)
            _ui.update {
                val previous = it.timelines[taskId] ?: DetailLoad()
                it.copy(
                    timelines = it.timelines + (
                        taskId to when (result) {
                            is Outcome.Success -> DetailLoad(value = result.value)
                            is Outcome.Failure -> previous.copy(loading = false, error = result.error.message)
                        }
                        ),
                )
            }
        }
    }

    override fun selectWorker(workerId: String?) = _ui.update { it.copy(selectedWorkerId = workerId) }

    override fun selectConversation(conversation: ControlConversation?) {
        _ui.update { it.copy(selectedConversationId = conversation?.id) }
        if (conversation != null) loadTranscript(conversation, force = false)
    }

    override fun selectChatConversation(conversation: ControlConversation?) {
        _ui.update { it.copy(chatConversationId = conversation?.id) }
        if (conversation != null) loadTranscript(conversation, force = false)
    }

    override fun reloadTranscript(conversation: ControlConversation) = loadTranscript(conversation, force = true)

    private fun loadTranscript(conversation: ControlConversation, force: Boolean) {
        val current = _ui.value.transcripts[conversation.id]
        if (!force && current != null && (current.loading || (current.value != null && current.error == null))) return
        transcriptJobs[conversation.id]?.cancel()
        _ui.update {
            it.copy(transcripts = it.transcripts + (conversation.id to (current ?: DetailLoad()).copy(loading = true, error = null)))
        }
        transcriptJobs[conversation.id] = viewModelScope.launch {
            val result = control.transcript(conversation)
            _ui.update {
                val previous = it.transcripts[conversation.id] ?: DetailLoad()
                it.copy(
                    transcripts = it.transcripts + (
                        conversation.id to when (result) {
                            is Outcome.Success -> DetailLoad(value = result.value)
                            is Outcome.Failure -> previous.copy(loading = false, error = result.error.message)
                        }
                        ),
                )
            }
        }
    }
}
