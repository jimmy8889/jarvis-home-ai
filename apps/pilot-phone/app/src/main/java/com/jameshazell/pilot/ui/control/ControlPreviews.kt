package com.jameshazell.pilot.ui.control

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.data.control.ControlApproval
import com.jameshazell.pilot.data.control.ControlConnection
import com.jameshazell.pilot.data.control.ControlConversation
import com.jameshazell.pilot.data.control.ControlOverview
import com.jameshazell.pilot.data.control.ControlProject
import com.jameshazell.pilot.data.control.ControlTarget
import com.jameshazell.pilot.data.control.ControlTask
import com.jameshazell.pilot.data.control.ControlTaskEvent
import com.jameshazell.pilot.data.control.ControlTranscript
import com.jameshazell.pilot.data.control.ControlTranscriptEntry
import com.jameshazell.pilot.data.control.ControlWorker
import com.jameshazell.pilot.data.control.TaskEventKind
import com.jameshazell.pilot.data.control.TranscriptRole
import com.jameshazell.pilot.ui.adaptive.LocalPilotWindow
import com.jameshazell.pilot.ui.adaptive.PilotWindow
import com.jameshazell.pilot.ui.adaptive.WindowSizeClass
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotTheme

/** Wraps a preview in the theme and a window of [widthDp] (360 = closed Fold, 752 = open). */
@Composable
internal fun PreviewFrame(widthDp: Int, content: @Composable () -> Unit) {
    PilotTheme {
        CompositionLocalProvider(
            LocalPilotWindow provides PilotWindow(WindowSizeClass.fromWidthDp(widthDp.toFloat()), widthDp = widthDp.toFloat(), heightDp = 800f),
        ) {
            Box(Modifier.fillMaxSize().background(PilotColors.Background)) { content() }
        }
    }
}

internal object ControlFixtures {
    val overview = ControlOverview(
        projects = listOf(
            ControlProject("pilot", "Pilot phone", "clean", "ready", "dell"),
            ControlProject("energy", "House energy", "dirty", "mac-queued", null),
        ),
        tasks = listOf(
            ControlTask("t1", "Add the Control screens to the Pilot phone app", "pilot", "dell", "running", "working"),
            ControlTask("t2", "Why did the battery stop charging at 2pm?", "energy", "dell", "completed", "completed"),
            ControlTask("t3", "Merge the dashboard branch", "pilot", "mac", "blocked", "waiting for approval"),
        ),
        workers = listOf(
            ControlWorker("dell", "dell", "linux", "busy", "t1"),
            ControlWorker("mac", "mac", "macos", "offline", null),
        ),
        conversations = listOf(
            ControlConversation("c1", "Rewrite the Fold client", "2026-11-12T01:10:00Z", "Start with the foundation module", "dell"),
            ControlConversation("c2", "Energy tariff comparison", "2026-11-10T05:00:00Z", "Compare the two plans", "dell"),
        ),
    )
    val approval = ControlApproval("a1", "git.mergePullRequest", """{"url":"https://example.invalid/pr/12","branch":"dashboard","base":"master"}""", "high")
    private val chat = ChatState(
        listOf(
            ChatItem.Outgoing("k1", "Why did the battery stop charging at 2pm?", ControlTarget.Auto, "energy", SendState.Sent, "t2"),
            ChatItem.Reply("t2", "It reached the 90% limit set for today, so the surplus went to the grid instead.", streaming = false),
            ChatItem.Outgoing("k2", "Add the Control screens to the Pilot phone app", ControlTarget.Codex, "pilot", SendState.Sent, "t1"),
            ChatItem.Reply("t1", "Reading the foundation module and the old screens first", streaming = true),
            ChatItem.Outgoing("k3", "And run the tests", ControlTarget.Codex, "pilot", SendState.Failed, error = "This phone can't reach James Control. Check the network or VPN."),
        ),
    )
    private val timeline = listOf(
        ControlTaskEvent(TaskEventKind.Status, "task.updated", "queued", status = "queued", at = "2026-11-12T01:00:00Z"),
        ControlTaskEvent(TaskEventKind.Status, "task.updated", "working", status = "running", at = "2026-11-12T01:00:05Z"),
        ControlTaskEvent(TaskEventKind.Output, "task.output", "Reading the foundation ", stream = "commentary"),
        ControlTaskEvent(TaskEventKind.Output, "task.output", "module and the old screens first", stream = "commentary"),
        ControlTaskEvent(TaskEventKind.Approval, "approval.requested", "git.push", detail = """{"branch":"pilot-rewrite-control"}"""),
    )
    private val transcript = ControlTranscript(
        "c1", "Rewrite the Fold client",
        listOf(
            ControlTranscriptEntry(TranscriptRole.User, "Rewrite the Fold client from scratch."),
            ControlTranscriptEntry(TranscriptRole.Reasoning, "Looking at what the old app does first."),
            ControlTranscriptEntry(TranscriptRole.Tool, "./gradlew :app:assembleDebug", "Command"),
            ControlTranscriptEntry(TranscriptRole.Assistant, "The foundation module is in place: theme, adaptive shell and the three repositories."),
        ),
    )

    fun ui(section: ControlSection, select: Boolean = true) = ControlUiState(
        section = section,
        target = ControlTarget.Codex,
        projectId = "pilot",
        chat = chat,
        selectedProjectId = "pilot".takeIf { select },
        selectedTaskId = "t1".takeIf { select },
        selectedWorkerId = "dell".takeIf { select },
        selectedConversationId = "c1".takeIf { select },
        timelines = mapOf("t1" to DetailLoad(value = timeline)),
        transcripts = mapOf("c1" to DetailLoad(value = transcript)),
    )
}

private val NoActions = object : ControlActions {}

@Composable
private fun ControlPreview(
    widthDp: Int,
    section: ControlSection,
    connection: ControlConnection = ControlConnection.Live,
    select: Boolean = true,
    approvals: List<ControlApproval> = emptyList(),
) {
    PreviewFrame(widthDp) {
        ControlContent(LoadState.Content(ControlFixtures.overview), connection, approvals, ControlFixtures.ui(section, select), NoActions)
    }
}

@Preview(name = "Chat · closed", widthDp = 360, heightDp = 800)
@Composable
private fun ChatClosedPreview() = ControlPreview(360, ControlSection.Chat, approvals = listOf(ControlFixtures.approval))

@Preview(name = "Chat · open", widthDp = 752, heightDp = 800)
@Composable
private fun ChatOpenPreview() = ControlPreview(752, ControlSection.Chat, approvals = listOf(ControlFixtures.approval))

@Preview(name = "Chat · session expired · closed", widthDp = 360, heightDp = 800)
@Composable
private fun ChatExpiredPreview() = ControlPreview(360, ControlSection.Chat, ControlConnection.SessionExpired)

@Preview(name = "Chat · reconnecting · open", widthDp = 752, heightDp = 800)
@Composable
private fun ChatReconnectingPreview() = ControlPreview(752, ControlSection.Chat, ControlConnection.Reconnecting(4, 16))

@Preview(name = "Tasks list · closed", widthDp = 360, heightDp = 800)
@Composable
private fun TasksClosedPreview() = ControlPreview(360, ControlSection.Tasks, select = false)

@Preview(name = "Task timeline · closed", widthDp = 360, heightDp = 800)
@Composable
private fun TaskDetailClosedPreview() = ControlPreview(360, ControlSection.Tasks)

@Preview(name = "Tasks · open", widthDp = 752, heightDp = 800)
@Composable
private fun TasksOpenPreview() = ControlPreview(752, ControlSection.Tasks)

@Preview(name = "Projects · open", widthDp = 752, heightDp = 800)
@Composable
private fun ProjectsOpenPreview() = ControlPreview(752, ControlSection.Projects)

@Preview(name = "Workers · closed", widthDp = 360, heightDp = 800)
@Composable
private fun WorkersClosedPreview() = ControlPreview(360, ControlSection.Workers, select = false)

@Preview(name = "Transcript · closed", widthDp = 360, heightDp = 800)
@Composable
private fun TranscriptClosedPreview() = ControlPreview(360, ControlSection.Conversations)

@Preview(name = "Conversations · open", widthDp = 752, heightDp = 800)
@Composable
private fun ConversationsOpenPreview() = ControlPreview(752, ControlSection.Conversations)
