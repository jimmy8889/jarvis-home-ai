package com.jameshazell.pilot.data.control

import com.jameshazell.pilot.core.arr
import com.jameshazell.pilot.core.obj
import com.jameshazell.pilot.core.objects
import com.jameshazell.pilot.core.str
import com.jameshazell.pilot.core.strOrNull
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
)

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
    data object TaskUpdated : ControlEvent
    data object WorkerUpdated : ControlEvent
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
            "task.updated" -> ControlEvent.TaskUpdated
            "worker.updated" -> ControlEvent.WorkerUpdated
            else -> ControlEvent.Other(type)
        }
    }

    fun messageBody(text: String, target: ControlTarget, projectId: String?, idempotencyKey: String): JSONObject =
        JSONObject().put("text", text).put("target", target.id).put("idempotency_key", idempotencyKey)
            .apply { projectId?.takeIf(String::isNotBlank)?.let { put("project_id", it) } }

    fun approvalBody(accept: Boolean): JSONObject = JSONObject().put("decision", if (accept) "accept" else "decline")
}
