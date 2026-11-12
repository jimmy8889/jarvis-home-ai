package com.jameshazell.pilot.data.control

import com.jameshazell.pilot.core.AppError
import com.jameshazell.pilot.core.ErrorKind
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.core.Outcome
import com.jameshazell.pilot.core.Service
import com.jameshazell.pilot.core.failedWith
import com.jameshazell.pilot.core.objects
import com.jameshazell.pilot.core.outcomeOf
import com.jameshazell.pilot.core.toAppError
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

/**
 * James Control: projects, tasks, workers, conversations, streamed replies and approvals.
 *
 * Lists are cached-then-live. The event socket runs only between [start] and [stop] and
 * reconnects by itself; watch [connection] for [ControlConnection.SessionExpired], which no
 * amount of retrying fixes.
 */
class ControlRepository(
    private val scope: CoroutineScope,
    private val client: ControlClient,
) {
    private val _overview = MutableStateFlow<LoadState<ControlOverview>>(LoadState.Loading)
    val overview: StateFlow<LoadState<ControlOverview>> = _overview.asStateFlow()

    private val _messages = MutableStateFlow<Map<String, String>>(emptyMap())
    /** Reply text by task id, growing as it streams. In memory only. */
    val messages: StateFlow<Map<String, String>> = _messages.asStateFlow()

    private val _approvals = MutableStateFlow<List<ControlApproval>>(emptyList())
    /** Approval requests received this session that have not been answered from this phone. */
    val approvals: StateFlow<List<ControlApproval>> = _approvals.asStateFlow()

    private val _events = MutableSharedFlow<ControlEvent>(extraBufferCapacity = 256, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    /** Every socket event, after this repository has applied it. Not replayed to late collectors. */
    val socketEvents: SharedFlow<ControlEvent> = _events.asSharedFlow()

    private val events = ControlEventStream(scope, client, ::onEvent, onConnected = ::refresh)
    val connection: StateFlow<ControlConnection> = events.connection

    private var started = false
    private var refreshJob: Job? = null

    /** Show saved lists, load live ones and open the event socket. Safe to call repeatedly. */
    fun start() {
        if (started) return
        started = true
        scope.launch {
            if (_overview.value !is LoadState.Content) loadSaved()
            refresh()
        }
        events.start()
    }

    fun stop() {
        started = false
        refreshJob?.cancel()
        events.stop()
    }

    /** The network came back: reconnect now instead of waiting out the backoff. */
    fun onNetworkAvailable() {
        if (!started || connection.value == ControlConnection.SessionExpired) return
        events.start()
    }

    /**
     * After the session has been renewed (new credentials provisioned): leave
     * [ControlConnection.SessionExpired] and connect again.
     */
    fun retryAfterSessionRenewal() {
        if (!started) return
        events.start()
        refresh()
    }

    /** Reload all four lists. A refresh already in flight is not duplicated. */
    fun refresh() {
        if (refreshJob?.isActive == true) return
        refreshJob = scope.launch {
            try {
                val (overview, stale) = coroutineScope {
                    val projects = async { client.read(ControlClient.PROJECTS_PATH) }
                    val tasks = async { client.read(ControlClient.TASKS_PATH) }
                    val workers = async { client.read(ControlClient.WORKERS_PATH) }
                    val conversations = async { client.read(ControlClient.CONVERSATIONS_PATH) }
                    val reads = listOf(projects.await(), tasks.await(), workers.await(), conversations.await())
                    decode(reads[0].json, reads[1].json, reads[2].json, reads[3].json) to reads.filter { it.stale }
                }
                _overview.value = LoadState.Content(
                    overview,
                    stale = stale.isNotEmpty(),
                    savedAt = stale.mapNotNull { it.savedAt }.minOrNull(),
                    problem = stale.firstNotNullOfOrNull { it.problem }?.toAppError(Service.Control),
                )
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                val appError = error.toAppError(Service.Control)
                if (appError.kind == ErrorKind.Unauthorized) events.markSessionExpired()
                _overview.update { it.failedWith(appError) }
            }
        }
    }

    /**
     * Sends a message; the reply streams into [messages] under the returned task id.
     *
     * @param idempotencyKey reuse the same key when retrying a send that may have reached the
     * server: James Control then returns the existing task instead of starting a second one.
     */
    suspend fun sendMessage(
        text: String,
        target: ControlTarget = ControlTarget.Auto,
        projectId: String? = null,
        idempotencyKey: String = UUID.randomUUID().toString(),
    ): Outcome<String?> =
        outcomeOf(Service.Control) {
            val body = ControlJson.messageBody(text.trim(), target, projectId, idempotencyKey)
            val reply = JSONObject(client.send(ControlClient.MESSAGES_PATH, "POST", body).ifBlank { "{}" })
            reply.optString("id").takeIf(String::isNotBlank)
                ?: reply.optJSONObject("task")?.optString("id")?.takeIf(String::isNotBlank)
        }.also { noteSession(it); if (it is Outcome.Success) refresh() }

    suspend fun decideApproval(approvalId: String, accept: Boolean): Outcome<Unit> =
        outcomeOf(Service.Control) {
            client.send(ControlClient.approvalPath(approvalId), "POST", ControlJson.approvalBody(accept))
            Unit
        }.also { result ->
            noteSession(result)
            if (result is Outcome.Success) _approvals.update { list -> list.filterNot { it.id == approvalId } }
        }

    /** Activity log of a task. Entries are returned raw: their shape varies by event type. */
    suspend fun taskEvents(taskId: String): Outcome<List<JSONObject>> =
        outcomeOf(Service.Control) {
            (client.read(ControlClient.taskEventsPath(taskId)).json as? JSONArray).objects()
        }.also(::noteSession)

    /** A conversation transcript, raw: its shape is the worker's own thread format. */
    suspend fun conversation(conversation: ControlConversation): Outcome<JSONObject> =
        outcomeOf(Service.Control) {
            client.read(ControlClient.conversationPath(conversation.id, conversation.hostId)).json as? JSONObject
                ?: JSONObject()
        }.also(::noteSession)

    /** [taskEvents], typed. */
    suspend fun taskTimeline(taskId: String): Outcome<List<ControlTaskEvent>> = when (val raw = taskEvents(taskId)) {
        is Outcome.Success -> Outcome.Success(raw.value.map(ControlJson::taskEvent))
        is Outcome.Failure -> raw
    }

    /** [conversation], flattened to a list of who said what. */
    suspend fun transcript(conversation: ControlConversation): Outcome<ControlTranscript> =
        when (val raw = conversation(conversation)) {
            is Outcome.Success -> Outcome.Success(ControlJson.transcript(raw.value, conversation))
            is Outcome.Failure -> raw
        }

    private fun onEvent(event: ControlEvent) {
        when (event) {
            is ControlEvent.MessageDelta -> _messages.update { it + (event.id to it[event.id].orEmpty() + event.text) }
            is ControlEvent.MessageCompleted -> _messages.update { it + (event.id to event.text) }
            is ControlEvent.ApprovalRequested -> _approvals.update { list ->
                if (list.any { it.id == event.approval.id }) list else list + event.approval
            }
            is ControlEvent.TaskUpdated -> {
                event.task?.let { task -> updateOverview { it.withTask(task) } }
                refresh()
            }
            is ControlEvent.WorkerUpdated -> {
                event.worker?.let { worker -> updateOverview { it.withWorker(worker) } }
                refresh()
            }
            is ControlEvent.Other -> Unit
        }
        _events.tryEmit(event)
    }

    /** Applies a pushed change straight away; the refresh that follows confirms it. */
    private fun updateOverview(change: (ControlOverview) -> ControlOverview) {
        _overview.update { state -> if (state is LoadState.Content) state.copy(value = change(state.value)) else state }
    }

    private fun noteSession(result: Outcome<*>) {
        if (result.errorOrNull()?.kind == ErrorKind.Unauthorized) events.markSessionExpired()
    }

    private suspend fun loadSaved() {
        val saved = listOf(
            ControlClient.PROJECTS_PATH, ControlClient.TASKS_PATH,
            ControlClient.WORKERS_PATH, ControlClient.CONVERSATIONS_PATH,
        ).map { client.saved(it) ?: return }
        runCatching { decode(saved[0].json, saved[1].json, saved[2].json, saved[3].json) }.getOrNull()?.let {
            _overview.value = LoadState.Content(it, stale = true, savedAt = saved.mapNotNull { s -> s.savedAt }.minOrNull())
        }
    }

    private fun decode(projects: Any, tasks: Any, workers: Any, conversations: Any): ControlOverview {
        val conversationRoot = conversations as? JSONObject ?: JSONObject()
        return ControlOverview(
            projects = ControlJson.projects(projects as? JSONArray),
            tasks = ControlJson.tasks(tasks as? JSONArray),
            workers = ControlJson.workers(workers as? JSONArray),
            conversations = ControlJson.conversations(conversationRoot),
            conversationsPartial = conversationRoot.optBoolean("partial", false),
        )
    }
}

/** Shown wherever Control content appears while the session is expired. */
val SessionExpiredError = AppError(
    ErrorKind.Unauthorized,
    "The James Control session has expired. Renew this phone's session to reconnect.",
)
