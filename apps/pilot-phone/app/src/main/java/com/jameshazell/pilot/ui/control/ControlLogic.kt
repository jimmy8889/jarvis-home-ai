package com.jameshazell.pilot.ui.control

import com.jameshazell.pilot.core.humanLabel
import com.jameshazell.pilot.data.control.ControlApproval
import com.jameshazell.pilot.data.control.ControlConnection
import com.jameshazell.pilot.data.control.ControlEvent
import com.jameshazell.pilot.data.control.ControlTarget
import com.jameshazell.pilot.data.control.ControlTask
import com.jameshazell.pilot.data.control.ControlTaskEvent
import com.jameshazell.pilot.data.control.TaskEventKind
import java.time.Duration
import java.time.Instant

/*
 * Everything in this file is plain Kotlin (no Android, no Compose) so it runs in JVM unit tests.
 */

enum class ControlSection(val label: String) {
    Chat("Chat"), Projects("Projects"), Tasks("Tasks"), Workers("Workers"), Conversations("Conversations"),
}

/** Semantic colour of a pill, dot or banner; the screen maps it to the palette. */
enum class Tone { Neutral, Good, Active, Warn, Bad }

// ---- Chat -----------------------------------------------------------------------------------

enum class SendState { Sending, Sent, Failed }

sealed interface ChatItem {
    /** Stable list key. */
    val key: String

    /**
     * A message typed on this phone. [key] doubles as the idempotency key, so retrying a failed
     * send can never start a second task.
     */
    data class Outgoing(
        override val key: String,
        val text: String,
        val target: ControlTarget,
        val projectId: String?,
        val state: SendState,
        val taskId: String? = null,
        val error: String? = null,
    ) : ChatItem

    /** The reply to task [taskId], growing while [streaming]. */
    data class Reply(val taskId: String, val text: String, val streaming: Boolean) : ChatItem {
        override val key: String get() = "reply:$taskId"
    }
}

data class ChatState(val items: List<ChatItem> = emptyList()) {
    fun outgoing(key: String): ChatItem.Outgoing? = items.firstOrNull { it.key == key } as? ChatItem.Outgoing
    fun reply(taskId: String): ChatItem.Reply? = items.firstOrNull { it is ChatItem.Reply && it.taskId == taskId } as? ChatItem.Reply
}

/** Builds the chat thread from sends on this phone and events from the socket. */
object ChatReducer {
    /** A new message, or a retry of the failed one with the same [key]. */
    fun sending(state: ChatState, key: String, text: String, target: ControlTarget, projectId: String?): ChatState =
        if (state.outgoing(key) != null) state.mapOutgoing(key) { it.copy(state = SendState.Sending, error = null) }
        else ChatState(state.items + ChatItem.Outgoing(key, text, target, projectId, SendState.Sending))

    /** The server accepted the message as task [taskId]; a reply that raced ahead moves under it. */
    fun sent(state: ChatState, key: String, taskId: String?): ChatState {
        val marked = state.mapOutgoing(key) { it.copy(state = SendState.Sent, taskId = taskId, error = null) }
        val early = taskId?.let(marked::reply) ?: return marked
        val rest = marked.items - early
        val at = rest.indexOfFirst { it.key == key }
        return ChatState(rest.subList(0, at + 1) + early + rest.subList(at + 1, rest.size))
    }

    fun failed(state: ChatState, key: String, message: String): ChatState =
        state.mapOutgoing(key) { it.copy(state = SendState.Failed, error = message) }

    /** `message.delta`: append. */
    fun delta(state: ChatState, taskId: String, text: String): ChatState {
        if (taskId.isBlank() || text.isEmpty()) return state
        val existing = state.reply(taskId) ?: return state.insertReply(ChatItem.Reply(taskId, text, streaming = true))
        return state.replace(existing, existing.copy(text = existing.text + text, streaming = true))
    }

    /** `message.completed`: the final text replaces whatever streamed. */
    fun completed(state: ChatState, taskId: String, text: String): ChatState {
        if (taskId.isBlank()) return state
        val existing = state.reply(taskId) ?: return state.insertReply(ChatItem.Reply(taskId, text, streaming = false))
        return state.replace(existing, existing.copy(text = text, streaming = false))
    }

    /** A task that has ended is no longer streaming, even if no `message.completed` arrived. */
    fun taskChanged(state: ChatState, task: ControlTask): ChatState {
        val existing = state.reply(task.id) ?: return state
        return if (existing.streaming && isFinished(task.status)) state.replace(existing, existing.copy(streaming = false)) else state
    }

    fun onEvent(state: ChatState, event: ControlEvent): ChatState = when (event) {
        is ControlEvent.MessageDelta -> delta(state, event.id, event.text)
        is ControlEvent.MessageCompleted -> completed(state, event.id, event.text)
        is ControlEvent.TaskUpdated -> event.task?.let { taskChanged(state, it) } ?: state
        else -> state
    }

    /** Replies the repository already holds (received before this state existed). */
    fun seed(state: ChatState, replies: Map<String, String>): ChatState =
        replies.entries.fold(state) { acc, (taskId, text) ->
            if (acc.reply(taskId) != null || text.isEmpty()) acc else acc.insertReply(ChatItem.Reply(taskId, text, streaming = false))
        }

    private fun ChatState.mapOutgoing(key: String, change: (ChatItem.Outgoing) -> ChatItem.Outgoing): ChatState =
        ChatState(items.map { if (it is ChatItem.Outgoing && it.key == key) change(it) else it })

    private fun ChatState.replace(old: ChatItem, new: ChatItem): ChatState = ChatState(items.map { if (it === old) new else it })

    /** Directly under the message that started the task, or at the end for tasks started elsewhere. */
    private fun ChatState.insertReply(reply: ChatItem.Reply): ChatState {
        val at = items.indexOfFirst { it is ChatItem.Outgoing && it.taskId == reply.taskId }
        return if (at < 0) ChatState(items + reply) else ChatState(items.subList(0, at + 1) + reply + items.subList(at + 1, items.size))
    }
}

fun isFinished(taskStatus: String): Boolean = taskStatus == "completed" || taskStatus == "failed"

// ---- Approvals ------------------------------------------------------------------------------

/**
 * Where the approval cards are in their flow.
 *
 * @param confirming the request whose Accept is waiting behind the confirmation dialog.
 * @param busyId the request whose answer is being sent.
 * @param errorId / [error] the request whose answer could not be sent, and why.
 */
data class ApprovalUi(
    val confirming: ControlApproval? = null,
    val busyId: String? = null,
    val errorId: String? = null,
    val error: String? = null,
) {
    fun errorFor(id: String): String? = error.takeIf { errorId == id }

    /** Accept was tapped: ask first. Ignored while another answer is being sent. */
    fun askAccept(approval: ControlApproval): ApprovalUi = if (busyId != null) this else copy(confirming = approval, errorId = null, error = null)

    fun dismissConfirm(): ApprovalUi = if (busyId != null) this else copy(confirming = null, errorId = null, error = null)

    /** Null when an answer is already on its way: one decision at a time. */
    fun begin(id: String): ApprovalUi? = if (busyId != null) null else copy(busyId = id, errorId = null, error = null)

    fun succeeded(id: String): ApprovalUi =
        copy(busyId = null, confirming = confirming?.takeIf { it.id != id }, errorId = null, error = null)

    /** The dialog (for Accept) stays open and shows [message]. */
    fun failed(id: String, message: String): ApprovalUi = copy(busyId = null, errorId = id, error = message)

    /** Requests answered elsewhere disappear from the list; forget any dialog about them. */
    fun pruned(pending: List<ControlApproval>): ApprovalUi {
        val ids = pending.map { it.id }.toSet()
        return copy(
            confirming = confirming?.takeIf { it.id in ids || busyId == it.id },
            errorId = errorId?.takeIf { it in ids },
            error = error.takeIf { errorId in ids },
        )
    }
}

// ---- Connection -----------------------------------------------------------------------------

enum class LinkState { Idle, Connecting, Live, Reconnecting, Offline, SessionExpired, NotPaired }

enum class BannerAction { None, RetryNow, RenewSession }

data class ConnectionBanner(
    val state: LinkState,
    /** Short status, also used under the screen title. */
    val title: String,
    val detail: String?,
    val tone: Tone,
    val action: BannerAction = BannerAction.None,
    val actionLabel: String? = null,
) {
    /** Live and idle need no strip; the header line says enough. */
    val visible: Boolean get() = state != LinkState.Live && state != LinkState.Idle
}

/** After this many failed attempts in a row the phone is called offline rather than reconnecting. */
const val OFFLINE_AFTER_ATTEMPTS = 3

fun connectionBanner(connection: ControlConnection): ConnectionBanner = when (connection) {
    ControlConnection.Idle -> ConnectionBanner(LinkState.Idle, "Not connected", null, Tone.Neutral)
    ControlConnection.Connecting -> ConnectionBanner(LinkState.Connecting, "Connecting", "Opening the live connection to James Control…", Tone.Neutral)
    ControlConnection.Live -> ConnectionBanner(LinkState.Live, "Live", null, Tone.Good)
    is ControlConnection.Reconnecting ->
        if (connection.attempt < OFFLINE_AFTER_ATTEMPTS) {
            ConnectionBanner(
                LinkState.Reconnecting, "Reconnecting",
                "The live connection dropped. Trying again in ${seconds(connection.retryInSeconds)}.",
                Tone.Warn, BannerAction.RetryNow, "Retry now",
            )
        } else {
            ConnectionBanner(
                LinkState.Offline, "Offline",
                "This phone can't reach James Control. Check the network or VPN. " +
                    "Trying again in ${seconds(connection.retryInSeconds)}.",
                Tone.Warn, BannerAction.RetryNow, "Retry now",
            )
        }
    ControlConnection.SessionExpired -> ConnectionBanner(
        LinkState.SessionExpired, "Session expired",
        "James Control no longer accepts this phone's session, so nothing can be sent or updated and " +
            "retrying won't help. Renew the Control session for this phone, then reconnect.",
        Tone.Bad, BannerAction.RenewSession, "Session renewed — reconnect",
    )
    ControlConnection.NotPaired -> ConnectionBanner(
        LinkState.NotPaired, "Not set up",
        "James Control isn't set up on this phone yet.", Tone.Neutral,
    )
}

private fun seconds(count: Int): String = if (count == 1) "1 second" else "$count seconds"

/** Why Send is disabled, or null when a message can be sent. */
fun sendBlockReason(connection: ControlConnection): String? = when (connection) {
    ControlConnection.Live -> null
    ControlConnection.Idle, ControlConnection.Connecting -> "Connecting to James Control. You can send once it's live."
    is ControlConnection.Reconnecting -> "Not connected to James Control. Sending is paused until it reconnects."
    ControlConnection.SessionExpired -> "The Control session has expired. Renew it to send messages."
    ControlConnection.NotPaired -> "James Control isn't set up on this phone."
}

// ---- Lists and details ----------------------------------------------------------------------

fun taskTone(status: String): Tone = when (status) {
    "running" -> Tone.Active
    "completed" -> Tone.Good
    "failed" -> Tone.Bad
    "blocked" -> Tone.Warn
    else -> Tone.Neutral
}

fun workerTone(status: String): Tone = when (status) {
    "online" -> Tone.Good
    "busy" -> Tone.Active
    else -> Tone.Neutral
}

fun projectTone(syncState: String): Tone = when (syncState) {
    "clean", "synced" -> Tone.Good
    "dirty", "ahead", "behind", "diverged" -> Tone.Warn
    "error", "missing" -> Tone.Bad
    else -> Tone.Neutral
}

fun targetLabel(target: ControlTarget): String = when (target) {
    ControlTarget.Auto -> "Auto"
    ControlTarget.Codex -> "Codex"
    ControlTarget.Hermes -> "Hermes"
}

data class TimelineRow(val title: String, val body: String, val tone: Tone, val at: String? = null)

/**
 * A task's activity log as readable rows: consecutive output of the same stream is joined (it
 * was streamed in pieces), and a status that repeats the previous one is dropped.
 */
fun timelineRows(events: List<ControlTaskEvent>): List<TimelineRow> {
    val rows = mutableListOf<TimelineRow>()
    var lastStream: String? = null
    var lastStatus: String? = null
    for (event in events) {
        val stream = event.stream.takeIf { event.kind == TaskEventKind.Output }
        if (stream != null && stream == lastStream && rows.isNotEmpty()) {
            val previous = rows.removeAt(rows.lastIndex)
            rows += previous.copy(body = previous.body + event.text)
            continue
        }
        lastStream = stream
        when (event.kind) {
            TaskEventKind.Status -> {
                val status = event.status ?: "updated"
                val note = event.text.takeIf { it.isNotBlank() && it != status }.orEmpty()
                if ("$status|$note" == lastStatus) continue
                lastStatus = "$status|$note"
                rows += TimelineRow(humanLabel(status), note.let(::humanLabel), taskTone(status), event.at)
            }
            TaskEventKind.Output -> if (event.text.isNotBlank()) {
                rows += when (stream) {
                    "final" -> TimelineRow("Reply", event.text, Tone.Good)
                    "error" -> TimelineRow("Error", event.text, Tone.Bad)
                    else -> TimelineRow("Working notes", event.text, Tone.Neutral)
                }
            } else lastStream = null
            TaskEventKind.Approval -> rows += TimelineRow("Approval requested", listOfNotNull(event.text, event.detail).joinToString("\n"), Tone.Warn)
            TaskEventKind.RouteChoice -> rows += TimelineRow(
                "Needs a project choice",
                if (event.text.isBlank()) "James Control couldn't tell which project this is for." else "Could be: ${event.text}",
                Tone.Warn,
            )
            TaskEventKind.Other -> rows += TimelineRow(humanLabel(event.type.replace('.', ' ')), event.text, Tone.Neutral)
        }
    }
    return rows
}

/** "just now", "5 min ago", "3 h ago", "2 d ago"; blank for missing or placeholder dates. */
fun relativeTime(iso: String?, now: Instant = Instant.now()): String {
    val at = iso?.let { runCatching { Instant.parse(it) }.getOrNull() } ?: return ""
    if (at.epochSecond < 86_400) return "" // The server writes 1970 when it has no date.
    val minutes = Duration.between(at, now).toMinutes()
    return when {
        minutes < 1 -> "just now"
        minutes < 60 -> "$minutes min ago"
        minutes < 48 * 60 -> "${minutes / 60} h ago"
        else -> "${minutes / (24 * 60)} d ago"
    }
}
