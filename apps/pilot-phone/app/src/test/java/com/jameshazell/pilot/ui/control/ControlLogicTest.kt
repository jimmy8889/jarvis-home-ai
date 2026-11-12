package com.jameshazell.pilot.ui.control

import com.jameshazell.pilot.data.control.ControlApproval
import com.jameshazell.pilot.data.control.ControlConnection
import com.jameshazell.pilot.data.control.ControlEvent
import com.jameshazell.pilot.data.control.ControlTarget
import com.jameshazell.pilot.data.control.ControlTask
import com.jameshazell.pilot.data.control.ControlTaskEvent
import com.jameshazell.pilot.data.control.TaskEventKind
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatReducerTest {
    private fun sent(key: String = "k1", taskId: String = "t1"): ChatState =
        ChatReducer.sent(ChatReducer.sending(ChatState(), key, "Hello", ControlTarget.Auto, null), key, taskId)

    @Test fun deltasAreAssembledInOrderUnderTheirMessage() {
        var state = sent()
        state = ChatReducer.delta(state, "t1", "Hel")
        state = ChatReducer.delta(state, "t1", "lo")
        assertEquals(listOf("k1", "reply:t1"), state.items.map { it.key })
        assertEquals(ChatItem.Reply("t1", "Hello", streaming = true), state.reply("t1"))
    }

    @Test fun completedReplacesWhatStreamed() {
        // The server sends the final text as one more delta and then as message.completed.
        var state = ChatReducer.delta(sent(), "t1", "thinking… ")
        state = ChatReducer.delta(state, "t1", "Done.")
        state = ChatReducer.completed(state, "t1", "Done.")
        assertEquals(ChatItem.Reply("t1", "Done.", streaming = false), state.reply("t1"))
        assertEquals(2, state.items.size)
    }

    @Test fun completedWithoutDeltasStillShowsTheReply() {
        val state = ChatReducer.completed(sent(), "t1", "Done.")
        assertEquals("Done.", state.reply("t1")?.text)
        assertFalse(state.reply("t1")!!.streaming)
    }

    @Test fun repliesOfInterleavedTasksStayApart() {
        var state = sent("k1", "t1")
        state = ChatReducer.sent(ChatReducer.sending(state, "k2", "Second", ControlTarget.Hermes, "p1"), "k2", "t2")
        state = ChatReducer.delta(state, "t2", "B")
        state = ChatReducer.delta(state, "t1", "A")
        state = ChatReducer.delta(state, "t2", "B")
        assertEquals(listOf("k1", "reply:t1", "k2", "reply:t2"), state.items.map { it.key })
        assertEquals("A", state.reply("t1")?.text)
        assertEquals("BB", state.reply("t2")?.text)
    }

    @Test fun aReplyThatArrivesBeforeTheSendReturnsMovesUnderItsMessage() {
        var state = ChatReducer.sending(sent("k0", "t0"), "k1", "Hello", ControlTarget.Auto, null)
        state = ChatReducer.delta(state, "t1", "early")
        assertEquals(listOf("k0", "k1", "reply:t1"), state.items.map { it.key })
        state = ChatReducer.sending(state, "k2", "Next", ControlTarget.Auto, null)
        state = ChatReducer.sent(state, "k1", "t1")
        assertEquals(listOf("k0", "k1", "reply:t1", "k2"), state.items.map { it.key })
        assertEquals(SendState.Sent, state.outgoing("k1")?.state)
    }

    @Test fun repliesToTasksStartedElsewhereGoToTheEnd() {
        val state = ChatReducer.delta(sent(), "other", "From the Mac")
        assertEquals(listOf("k1", "reply:other"), state.items.map { it.key })
    }

    @Test fun emptyAndAnonymousDeltasAreIgnored() {
        val state = sent()
        assertSame(state, ChatReducer.delta(state, "t1", ""))
        assertSame(state, ChatReducer.delta(state, "", "text"))
        assertSame(state, ChatReducer.completed(state, "", "text"))
    }

    @Test fun retryKeepsTheIdempotencyKeyAndTheMessagePosition() {
        var state = ChatReducer.sending(ChatState(), "k1", "Hello", ControlTarget.Codex, "p1")
        state = ChatReducer.sending(state, "k2", "Later", ControlTarget.Auto, null)
        state = ChatReducer.failed(state, "k1", "Offline.")
        assertEquals(SendState.Failed, state.outgoing("k1")?.state)
        assertEquals("Offline.", state.outgoing("k1")?.error)
        state = ChatReducer.sending(state, "k1", "Hello", ControlTarget.Codex, "p1")
        assertEquals(listOf("k1", "k2"), state.items.map { it.key })
        assertEquals(SendState.Sending, state.outgoing("k1")?.state)
        assertNull(state.outgoing("k1")?.error)
        assertEquals(ControlTarget.Codex, state.outgoing("k1")?.target)
    }

    @Test fun socketEventsDriveTheThread() {
        var state = sent()
        state = ChatReducer.onEvent(state, ControlEvent.MessageDelta("t1", "Hi"))
        state = ChatReducer.onEvent(state, ControlEvent.WorkerUpdated(null))
        state = ChatReducer.onEvent(state, ControlEvent.Other("route.choice_required"))
        assertTrue(state.reply("t1")!!.streaming)
        // The task ended without a message.completed (e.g. it failed): stop showing "Writing…".
        state = ChatReducer.onEvent(state, ControlEvent.TaskUpdated(ControlTask("t1", "Hello", null, null, "failed", "failed")))
        assertEquals(ChatItem.Reply("t1", "Hi", streaming = false), state.reply("t1"))
        state = ChatReducer.onEvent(state, ControlEvent.MessageCompleted("t1", "Hi there"))
        assertEquals("Hi there", state.reply("t1")?.text)
    }

    @Test fun aRunningTaskKeepsStreaming() {
        val state = ChatReducer.delta(sent(), "t1", "Hi")
        assertSame(state, ChatReducer.taskChanged(state, ControlTask("t1", "Hello", null, null, "running", "working")))
        assertSame(state, ChatReducer.taskChanged(state, ControlTask("zz", "Other", null, null, "completed", "")))
    }

    @Test fun seedingAddsOnlyRepliesNotAlreadyShown() {
        val state = ChatReducer.delta(sent(), "t1", "live")
        val seeded = ChatReducer.seed(state, mapOf("t1" to "older copy", "t9" to "From before", "t8" to ""))
        assertEquals("live", seeded.reply("t1")?.text)
        assertEquals(ChatItem.Reply("t9", "From before", streaming = false), seeded.reply("t9"))
        assertNull(seeded.reply("t8"))
    }
}

class ApprovalUiTest {
    private val a1 = ControlApproval("a1", "git.push", "{}", "high")
    private val a2 = ControlApproval("a2", "shell", "{}", null)

    @Test fun acceptWaitsBehindTheConfirmation() {
        val asked = ApprovalUi().askAccept(a1)
        assertEquals(a1, asked.confirming)
        assertNull(asked.busyId)
        assertNull(asked.dismissConfirm().confirming)
    }

    @Test fun oneDecisionAtATime() {
        val busy = ApprovalUi().askAccept(a1).begin("a1")!!
        assertEquals("a1", busy.busyId)
        assertNull(busy.begin("a2"))
        assertSame(busy, busy.askAccept(a2))
        assertSame(busy, busy.dismissConfirm())
    }

    @Test fun successClosesTheDialogAndFailureKeepsItWithTheReason() {
        val busy = ApprovalUi().askAccept(a1).begin("a1")!!
        val done = busy.succeeded("a1")
        assertEquals(ApprovalUi(), done)
        val failed = busy.failed("a1", "James Control took too long to answer.")
        assertEquals(a1, failed.confirming)
        assertNull(failed.busyId)
        assertEquals("James Control took too long to answer.", failed.errorFor("a1"))
        assertNull(failed.errorFor("a2"))
        assertNotNull(failed.begin("a1"))
        assertNull(failed.begin("a1")!!.error)
    }

    @Test fun decliningDoesNotOpenTheDialog() {
        val busy = ApprovalUi().begin("a2")!!
        assertNull(busy.confirming)
        assertEquals("Declined elsewhere", busy.failed("a2", "Declined elsewhere").errorFor("a2"))
    }

    @Test fun requestsAnsweredElsewhereAreForgotten() {
        val state = ApprovalUi().askAccept(a1).failed("a1", "x")
        assertEquals(a1, state.pruned(listOf(a1, a2)).confirming)
        assertEquals(ApprovalUi(), state.pruned(listOf(a2)))
        // Mid-send the repository has already dropped it; the dialog stays until the answer lands.
        val busy = ApprovalUi().askAccept(a1).begin("a1")!!
        assertEquals(a1, busy.pruned(emptyList()).confirming)
    }
}

class ConnectionMappingTest {
    @Test fun everyConnectionStateHasItsOwnBanner() {
        assertEquals(LinkState.Idle, connectionBanner(ControlConnection.Idle).state)
        assertEquals(LinkState.Connecting, connectionBanner(ControlConnection.Connecting).state)
        assertEquals(LinkState.Live, connectionBanner(ControlConnection.Live).state)
        assertEquals(LinkState.Reconnecting, connectionBanner(ControlConnection.Reconnecting(1, 1)).state)
        assertEquals(LinkState.Reconnecting, connectionBanner(ControlConnection.Reconnecting(2, 2)).state)
        assertEquals(LinkState.Offline, connectionBanner(ControlConnection.Reconnecting(OFFLINE_AFTER_ATTEMPTS, 4)).state)
        assertEquals(LinkState.SessionExpired, connectionBanner(ControlConnection.SessionExpired).state)
        assertEquals(LinkState.NotPaired, connectionBanner(ControlConnection.NotPaired).state)
    }

    @Test fun liveAndIdleShowNoStrip() {
        assertFalse(connectionBanner(ControlConnection.Live).visible)
        assertFalse(connectionBanner(ControlConnection.Idle).visible)
        assertTrue(connectionBanner(ControlConnection.Connecting).visible)
        assertEquals(Tone.Good, connectionBanner(ControlConnection.Live).tone)
    }

    @Test fun sessionExpiredExplainsItselfAndOffersRenewalNotRetry() {
        val banner = connectionBanner(ControlConnection.SessionExpired)
        assertEquals("Session expired", banner.title)
        assertEquals(BannerAction.RenewSession, banner.action)
        assertEquals(Tone.Bad, banner.tone)
        assertTrue(banner.detail!!.contains("Renew"))
        assertNotNull(banner.actionLabel)
    }

    @Test fun droppedConnectionsOfferRetryAndSayWhen() {
        val reconnecting = connectionBanner(ControlConnection.Reconnecting(1, 1))
        assertEquals(BannerAction.RetryNow, reconnecting.action)
        assertTrue(reconnecting.detail!!.contains("1 second."))
        val offline = connectionBanner(ControlConnection.Reconnecting(5, 30))
        assertEquals("Offline", offline.title)
        assertTrue(offline.detail!!.contains("30 seconds"))
        assertEquals(BannerAction.None, connectionBanner(ControlConnection.NotPaired).action)
    }

    @Test fun sendingIsOnlyAllowedWhileLiveAndSaysWhyOtherwise() {
        assertNull(sendBlockReason(ControlConnection.Live))
        val blocked = listOf(
            ControlConnection.Idle, ControlConnection.Connecting, ControlConnection.Reconnecting(1, 1),
            ControlConnection.SessionExpired, ControlConnection.NotPaired,
        ).map(::sendBlockReason)
        assertTrue(blocked.all { !it.isNullOrBlank() })
        assertTrue(sendBlockReason(ControlConnection.SessionExpired)!!.contains("expired"))
        assertEquals(4, blocked.toSet().size) // Idle and Connecting share one reason.
    }
}

class ControlPresentationTest {
    @Test fun statusTones() {
        assertEquals(Tone.Active, taskTone("running"))
        assertEquals(Tone.Good, taskTone("completed"))
        assertEquals(Tone.Bad, taskTone("failed"))
        assertEquals(Tone.Warn, taskTone("blocked"))
        assertEquals(Tone.Neutral, taskTone("queued"))
        assertEquals(Tone.Good, workerTone("online"))
        assertEquals(Tone.Active, workerTone("busy"))
        assertEquals(Tone.Neutral, workerTone("offline"))
        assertTrue(isFinished("completed") && isFinished("failed") && !isFinished("running"))
    }

    @Test fun timelineJoinsStreamedOutputAndDropsRepeatedStatus() {
        val rows = timelineRows(
            listOf(
                ControlTaskEvent(TaskEventKind.Status, "task.updated", "queued", status = "queued"),
                ControlTaskEvent(TaskEventKind.Status, "task.updated", "queued", status = "queued"),
                ControlTaskEvent(TaskEventKind.Status, "task.updated", "working", status = "running", at = "2026-11-12T01:00:00Z"),
                ControlTaskEvent(TaskEventKind.Output, "task.output", "Reading ", stream = "commentary"),
                ControlTaskEvent(TaskEventKind.Output, "task.output", "files", stream = "commentary"),
                ControlTaskEvent(TaskEventKind.Approval, "approval.requested", "git.push", detail = """{"branch":"main"}"""),
                ControlTaskEvent(TaskEventKind.Output, "task.output", "More notes", stream = "commentary"),
                ControlTaskEvent(TaskEventKind.Output, "task.output", "Done.", stream = "final"),
                ControlTaskEvent(TaskEventKind.Output, "task.output", "boom", stream = "error"),
                ControlTaskEvent(TaskEventKind.RouteChoice, "route.choice_required", "p1, p2"),
                ControlTaskEvent(TaskEventKind.Other, "worker.note", "hello"),
                ControlTaskEvent(TaskEventKind.Status, "task.updated", "completed", status = "completed"),
            ),
        )
        assertEquals(
            listOf("Queued", "Running", "Working notes", "Approval requested", "Working notes", "Reply", "Error", "Needs a project choice", "Worker note", "Completed"),
            rows.map { it.title },
        )
        assertEquals("Reading files", rows[2].body)
        assertEquals("Working", rows[1].body)
        assertEquals("2026-11-12T01:00:00Z", rows[1].at)
        assertEquals("git.push\n{\"branch\":\"main\"}", rows[3].body)
        assertEquals(Tone.Good, rows[5].tone)
        assertEquals(Tone.Bad, rows[6].tone)
        assertEquals("Could be: p1, p2", rows[7].body)
        assertEquals("", rows.last().body)
        assertTrue(timelineRows(emptyList()).isEmpty())
    }

    @Test fun relativeTimes() {
        val now = Instant.parse("2026-11-12T02:00:00Z")
        assertEquals("just now", relativeTime("2026-11-12T01:59:40Z", now))
        assertEquals("5 min ago", relativeTime("2026-11-12T01:55:00Z", now))
        assertEquals("3 h ago", relativeTime("2026-11-11T23:00:00Z", now))
        assertEquals("4 d ago", relativeTime("2026-11-08T02:00:00Z", now))
        assertEquals("", relativeTime("1970-01-01T00:00:00.000Z", now))
        assertEquals("", relativeTime("yesterday", now))
        assertEquals("", relativeTime(null, now))
    }

    @Test fun targetsAndSections() {
        assertEquals(listOf("Auto", "Codex", "Hermes"), ControlTarget.entries.map(::targetLabel))
        assertEquals(listOf("Chat", "Projects", "Tasks", "Workers", "Conversations"), ControlSection.entries.map { it.label })
    }
}
