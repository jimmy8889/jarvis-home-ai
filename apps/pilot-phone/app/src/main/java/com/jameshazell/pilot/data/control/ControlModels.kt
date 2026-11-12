package com.jameshazell.pilot.data.control

import com.jameshazell.pilot.core.arr
import com.jameshazell.pilot.core.obj
import com.jameshazell.pilot.core.objects
import com.jameshazell.pilot.core.str
import com.jameshazell.pilot.core.strOrNull
import com.jameshazell.pilot.core.strings
import org.json.JSONArray
import org.json.JSONObject

data class ControlProject(
    val id: String,
    val name: String,
    val syncState: String,
    val buildState: String,
    val host: String?,
)

data class ControlTask(
    val id: String,
    val title: String,
    val projectId: String?,
    val host: String?,
    val status: String,
    val progress: String,
)

data class ControlWorker(
    val id: String,
    val name: String,
    val platform: String,
    val status: String,
    val currentTask: String?,
)

data class ControlConversation(
    val id: String,
    val title: String,
    val updatedAt: String,
    val preview: String,
    /** Needed to open the conversation: it lives on this worker. */
    val hostId: String,
)

data class ControlApproval(val id: String, val title: String, val detail: String, val risk: String?)

data class ControlOverview(
    val projects: List<ControlProject>,
    val tasks: List<ControlTask>,
    val workers: List<ControlWorker>,
    val conversations: List<ControlConversation>,
    /** True when some workers could not be asked for their conversations. */
    val conversationsPartial: Boolean = false,
) {
    /** The lists with [task] replaced in place, or put first when it is new. */
    fun withTask(task: ControlTask): ControlOverview =
        if (tasks.any { it.id == task.id }) copy(tasks = tasks.map { if (it.id == task.id) task else it })
        else copy(tasks = listOf(task) + tasks)

    fun withWorker(worker: ControlWorker): ControlOverview =
        if (workers.any { it.id == worker.id }) copy(workers = workers.map { if (it.id == worker.id) worker else it })
        else copy(workers = workers + worker)
}

/** What an entry in a task's activity log is about. */
enum class TaskEventKind { Status, Output, Approval, RouteChoice, Other }

/**
 * One entry of `/v1/tasks/{id}/events`.
 *
 * @param type the server's event type, e.g. `task.output`.
 * @param text progress note (Status), output text (Output), requested method (Approval),
 * candidate projects (RouteChoice).
 * @param status the task status for Status entries: queued, running, blocked, completed, failed.
 * @param stream for Output entries: commentary, final or error.
 * @param detail extra data, e.g. the parameters of an approval request.
 * @param at ISO timestamp when the entry carries one.
 */
data class ControlTaskEvent(
    val kind: TaskEventKind,
    val type: String,
    val text: String,
    val status: String? = null,
    val stream: String? = null,
    val detail: String? = null,
    val at: String? = null,
)

enum class TranscriptRole { User, Assistant, Reasoning, Tool, Other }

/** @param label what a Tool / Other entry is, e.g. "Command". */
data class ControlTranscriptEntry(val role: TranscriptRole, val text: String, val label: String? = null)

/** A worker conversation, flattened from the worker's own thread format. */
data class ControlTranscript(val id: String, val title: String, val entries: List<ControlTranscriptEntry>)

/** Who should handle a message. */
enum class ControlTarget(val id: String) { Auto("auto"), Codex("codex"), Hermes("hermes") }

/** State of the live `/v1/events` connection. */
sealed interface ControlConnection {
    /** Not started (screen hidden). */
    data object Idle : ControlConnection
    data object Connecting : ControlConnection
    data object Live : ControlConnection
    /** The connection dropped; attempt number [attempt] follows in [retryInSeconds] seconds. */
    data class Reconnecting(val attempt: Int, val retryInSeconds: Int) : ControlConnection
    /**
     * James Control rejected this phone's session. Reconnecting cannot fix this: the device
     * session has to be renewed (re-provisioned) before anything works again.
     */
    data object SessionExpired : ControlConnection
    /** No James Control credentials on this phone. */
    data object NotPaired : ControlConnection
}

/** A message from the `/v1/events` websocket. */
sealed interface ControlEvent {
    /** Streaming output for task [id]; append [text]. */
    data class MessageDelta(val id: String, val text: String) : ControlEvent
    /** Final output for task [id]; replace with [text]. */
    data class MessageCompleted(val id: String, val text: String) : ControlEvent
    data class ApprovalRequested(val approval: ControlApproval) : ControlEvent
    /** [task] is the new state when the frame carried one; the lists are reloaded either way. */
    data class TaskUpdated(val task: ControlTask? = null) : ControlEvent
    data class WorkerUpdated(val worker: ControlWorker? = null) : ControlEvent
    data class Other(val type: String) : ControlEvent
}

internal object ControlJson {
    fun projects(array: JSONArray?): List<ControlProject> = array.objects().map {
        ControlProject(it.str("id"), it.str("name"), it.str("sync_state"), it.str("build_state"), it.strOrNull("host"))
    }

    fun tasks(array: JSONArray?): List<ControlTask> = array.objects().map {
        ControlTask(
            id = it.str("id"), title = it.str("title"), projectId = it.strOrNull("project_id"),
            host = it.strOrNull("host"), status = it.str("status"), progress = it.str("progress"),
        )
    }

    fun workers(array: JSONArray?): List<ControlWorker> = array.objects().map {
        ControlWorker(
            id = it.str("id", it.str("name")), name = it.str("name"), platform = it.str("platform"),
            status = it.str("status"), currentTask = it.strOrNull("current_task"),
        )
    }

    fun conversations(root: JSONObject): List<ControlConversation> = root.arr("data").objects().map {
        ControlConversation(it.str("id"), it.str("title"), it.str("updated_at"), it.str("preview"), it.str("host_id"))
    }

    fun approval(value: JSONObject) =
        ControlApproval(value.str("id"), value.str("title"), value.str("detail"), value.strOrNull("risk"))

    /** Null for frames that are not JSON objects. */
    fun event(frame: String): ControlEvent? {
        val event = runCatching { JSONObject(frame) }.getOrNull() ?: return null
        return when (val type = event.str("type")) {
            "message.delta" -> ControlEvent.MessageDelta(event.str("id"), event.str("text"))
            "message.completed" -> ControlEvent.MessageCompleted(event.str("id"), event.str("text"))
            "approval.requested" -> ControlEvent.ApprovalRequested(approval(event.obj("approval")))
            "task.updated" -> ControlEvent.TaskUpdated(
                event.optJSONObject("task")?.takeIf { it.str("id").isNotBlank() }?.let { tasks(JSONArray().put(it)).single() },
            )
            "worker.updated" -> ControlEvent.WorkerUpdated(
                event.optJSONObject("worker")?.takeIf { it.str("id", it.str("name")).isNotBlank() }
                    ?.let { workers(JSONArray().put(it)).single() },
            )
            else -> ControlEvent.Other(type)
        }
    }

    /** Entries are stored broker events (camelCase), not the list views. */
    fun taskEvent(event: JSONObject): ControlTaskEvent {
        val type = event.str("type")
        return when (type) {
            "task.updated" -> {
                val task = event.obj("task")
                ControlTaskEvent(
                    TaskEventKind.Status, type,
                    text = task.str("providerStatus", task.str("progress")),
                    status = task.strOrNull("status"),
                    at = task.strOrNull("updatedAt") ?: task.strOrNull("updated_at"),
                )
            }
            "task.output" -> ControlTaskEvent(TaskEventKind.Output, type, event.str("text"), stream = event.strOrNull("stream"))
            "approval.requested" -> ControlTaskEvent(
                TaskEventKind.Approval, type, event.str("method"),
                detail = event.opt("params")?.takeIf { it != JSONObject.NULL }?.toString(),
            )
            "route.choice_required" -> ControlTaskEvent(
                TaskEventKind.RouteChoice, type,
                event.arr("alternatives").objects().mapNotNull { it.strOrNull("projectId") }.joinToString(", "),
            )
            else -> ControlTaskEvent(TaskEventKind.Other, type, event.str("text"))
        }
    }

    /**
     * Flattens a worker thread: `{thread:{turns:[{items:[...]}]}}` (Codex app-server), with a
     * fallback for a plain `{messages:[{role,content}]}` list. Entries without text are dropped.
     */
    fun transcript(root: JSONObject, fallback: ControlConversation? = null): ControlTranscript {
        val thread = root.optJSONObject("thread") ?: root
        val items = thread.arr("turns").objects().flatMap { it.arr("items").objects() }
        val entries = (if (items.isNotEmpty()) items.mapNotNull(::threadItem) else thread.arr("messages").objects().mapNotNull(::plainMessage))
        return ControlTranscript(
            id = thread.str("id", fallback?.id.orEmpty()),
            title = thread.strOrNull("name") ?: fallback?.title ?: thread.str("preview").take(100),
            entries = entries,
        )
    }

    private fun threadItem(item: JSONObject): ControlTranscriptEntry? {
        val type = item.str("type")
        val entry = when (type) {
            "userMessage" -> ControlTranscriptEntry(TranscriptRole.User, contentText(item))
            "agentMessage" -> ControlTranscriptEntry(TranscriptRole.Assistant, contentText(item))
            "reasoning" -> ControlTranscriptEntry(
                TranscriptRole.Reasoning,
                item.arr("summary").let { summary ->
                    (summary.strings() + summary.objects().map { it.str("text") }).joinToString("\n")
                }.ifBlank { contentText(item) },
            )
            "commandExecution" -> ControlTranscriptEntry(TranscriptRole.Tool, item.str("command"), "Command")
            "fileChange" -> ControlTranscriptEntry(
                TranscriptRole.Tool, item.arr("changes").objects().joinToString("\n") { it.str("path") }, "File change",
            )
            "mcpToolCall" -> ControlTranscriptEntry(
                TranscriptRole.Tool, listOf(item.str("server"), item.str("tool")).filter(String::isNotBlank).joinToString(" · "), "Tool",
            )
            else -> ControlTranscriptEntry(TranscriptRole.Other, contentText(item), type)
        }
        return entry.takeIf { it.text.isNotBlank() }
    }

    private fun plainMessage(message: JSONObject): ControlTranscriptEntry? {
        val role = when (message.str("role")) {
            "user" -> TranscriptRole.User
            "assistant", "agent" -> TranscriptRole.Assistant
            "tool" -> TranscriptRole.Tool
            else -> TranscriptRole.Other
        }
        return ControlTranscriptEntry(role, contentText(message)).takeIf { it.text.isNotBlank() }
    }

    /** `text`, or `content` as a string or a list of `{text}` parts. */
    private fun contentText(item: JSONObject): String {
        item.strOrNull("text")?.let { return it }
        (item.opt("content") as? String)?.let { return it }
        return item.arr("content").objects().mapNotNull { it.strOrNull("text") }.joinToString("\n")
    }

    fun messageBody(text: String, target: ControlTarget, projectId: String?, idempotencyKey: String): JSONObject =
        JSONObject().put("text", text).put("target", target.id).put("idempotency_key", idempotencyKey)
            .apply { projectId?.takeIf(String::isNotBlank)?.let { put("project_id", it) } }

    fun approvalBody(accept: Boolean): JSONObject = JSONObject().put("decision", if (accept) "accept" else "decline")
}
