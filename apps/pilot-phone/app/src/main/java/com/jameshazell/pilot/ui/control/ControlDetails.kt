package com.jameshazell.pilot.ui.control

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.jameshazell.pilot.core.humanLabel
import com.jameshazell.pilot.data.control.ControlConversation
import com.jameshazell.pilot.data.control.ControlProject
import com.jameshazell.pilot.data.control.ControlTask
import com.jameshazell.pilot.data.control.ControlTaskEvent
import com.jameshazell.pilot.data.control.ControlTranscript
import com.jameshazell.pilot.data.control.ControlTranscriptEntry
import com.jameshazell.pilot.data.control.ControlWorker
import com.jameshazell.pilot.data.control.TranscriptRole
import com.jameshazell.pilot.ui.components.CardNote
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.SectionHeader
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens
import com.jameshazell.pilot.ui.theme.PilotIcons

private val DetailPadding = PaddingValues(start = PilotDimens.ScreenPadding, end = PilotDimens.ScreenPadding, bottom = PilotDimens.ScreenPadding)

@Composable
private fun Fact(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(PilotDimens.Gap)) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = PilotColors.TextDim, modifier = Modifier.weight(1f))
        Text(value, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1.4f))
    }
}

/** Loading and error rows shared by the task timeline and the transcript. */
private fun LazyListScope.loadStatus(load: DetailLoad<*>?, loadingLabel: String, onRetry: () -> Unit) {
    if (load == null || (load.loading && load.value == null)) {
        item(key = "loading") {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 8.dp)) {
                CircularProgressIndicator(color = PilotColors.Violet, strokeWidth = 2.dp, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(10.dp))
                CardNote(loadingLabel)
            }
        }
    }
    if (load?.error != null) {
        item(key = "error") {
            PilotCard(tint = PilotColors.Red) {
                CardNote(load.error, color = PilotColors.Text)
                TextButton(onClick = onRetry) { Text("Try again", color = PilotColors.Violet) }
            }
        }
    }
}

@Composable
internal fun ProjectDetail(project: ControlProject, tasks: List<ControlTask>, showBack: Boolean, actions: ControlActions) {
    DetailPane(project.name, showBack, onBack = { actions.selectProject(null) }, subtitle = project.host) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = DetailPadding, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item(key = "summary") {
                PilotCard {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (project.syncState.isNotBlank()) StatusPill(humanLabel(project.syncState), projectTone(project.syncState))
                        if (project.buildState.isNotBlank()) {
                            StatusPill("Build ${humanLabel(project.buildState).lowercase()}", if (project.buildState == "ready") Tone.Good else Tone.Warn)
                        }
                    }
                    Fact("Preferred worker", project.host ?: "None online")
                    PrimaryButton("Chat about this project", { actions.chatAboutProject(project.id) })
                }
            }
            item(key = "tasks") { SectionHeader("Tasks") }
            if (tasks.isEmpty()) item(key = "none") { CardNote("No tasks for this project.") }
            items(tasks, key = { it.id }) { task ->
                EntityRow(
                    title = task.title.ifBlank { "Untitled task" },
                    subtitle = task.host.orEmpty(),
                    selected = false,
                    onClick = { actions.openTask(task.id) },
                    pill = humanLabel(task.status),
                    pillTone = taskTone(task.status),
                )
            }
        }
    }
}

@Composable
internal fun TaskDetail(
    task: ControlTask,
    projectName: String?,
    reply: ChatItem.Reply?,
    load: DetailLoad<List<ControlTaskEvent>>?,
    showBack: Boolean,
    actions: ControlActions,
) {
    val rows = remember(load?.value) { timelineRows(load?.value.orEmpty()) }
    DetailPane(
        title = task.title.ifBlank { "Untitled task" },
        showBack = showBack,
        onBack = { actions.selectTask(null) },
        actions = { RoundIconButton(PilotIcons.Refresh, "Reload activity", { actions.reloadTimeline(task.id) }) },
    ) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = DetailPadding, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item(key = "summary") {
                PilotCard {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        StatusPill(humanLabel(task.status), taskTone(task.status))
                        if (task.progress.isNotBlank() && task.progress != task.status) CardNote(humanLabel(task.progress))
                    }
                    if (projectName != null) Fact("Project", projectName)
                    Fact("Worker", task.host ?: "Not assigned yet")
                }
            }
            if (reply != null && reply.streaming && reply.text.isNotBlank()) {
                item(key = "live") {
                    PilotCard(tint = PilotColors.Violet) {
                        Text("WRITING NOW", style = MaterialTheme.typography.labelSmall, color = PilotColors.Violet)
                        Text(reply.text, style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
            item(key = "activity") { SectionHeader("Activity") }
            loadStatus(load, "Loading activity…") { actions.reloadTimeline(task.id) }
            if (load?.value != null && rows.isEmpty()) item(key = "none") { CardNote("Nothing has been recorded for this task yet.") }
            itemsIndexed(rows) { index, row -> TimelineItem(row, last = index == rows.lastIndex) }
        }
    }
}

@Composable
private fun TimelineItem(row: TimelineRow, last: Boolean) {
    Row(Modifier.fillMaxWidth()) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.padding(top = 6.dp)) {
            Box(Modifier.size(10.dp).background(row.tone.color(), CircleShape))
            if (!last) Box(Modifier.padding(top = 4.dp).width(2.dp).size(width = 2.dp, height = 28.dp).background(PilotColors.Hairline))
        }
        Spacer(Modifier.width(PilotDimens.Gap))
        Column(Modifier.weight(1f).padding(bottom = 8.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(row.title, style = MaterialTheme.typography.labelLarge, modifier = Modifier.weight(1f))
                val at = relativeTime(row.at)
                if (at.isNotBlank()) Text(at, style = MaterialTheme.typography.labelMedium, color = PilotColors.TextFaint)
            }
            if (row.body.isNotBlank()) Text(row.body, style = MaterialTheme.typography.bodyMedium, color = PilotColors.TextDim)
        }
    }
}

@Composable
internal fun WorkerDetail(worker: ControlWorker, current: ControlTask?, tasks: List<ControlTask>, showBack: Boolean, actions: ControlActions) {
    DetailPane(worker.name, showBack, onBack = { actions.selectWorker(null) }, subtitle = humanLabel(worker.platform)) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = DetailPadding, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item(key = "summary") {
                PilotCard {
                    Row { StatusPill(humanLabel(worker.status), workerTone(worker.status)) }
                    CardNote(
                        when (worker.status) {
                            "offline" -> "This worker isn't connected, so it can't take tasks or show its conversations."
                            "busy" -> "This worker is running a task."
                            else -> "This worker is connected and free."
                        },
                    )
                }
            }
            if (current != null) {
                item(key = "current-header") { SectionHeader("Working on") }
                item(key = "current") {
                    EntityRow(current.title, humanLabel(current.progress), selected = false, onClick = { actions.openTask(current.id) }, pill = humanLabel(current.status), pillTone = taskTone(current.status))
                }
            }
            val others = tasks.filter { it.id != current?.id }
            if (others.isNotEmpty()) {
                item(key = "tasks-header") { SectionHeader("Its tasks") }
                items(others, key = { it.id }) { task ->
                    EntityRow(task.title, "", selected = false, onClick = { actions.openTask(task.id) }, pill = humanLabel(task.status), pillTone = taskTone(task.status))
                }
            }
        }
    }
}

@Composable
internal fun TranscriptDetail(
    conversation: ControlConversation,
    load: DetailLoad<ControlTranscript>?,
    showBack: Boolean,
    onBack: () -> Unit,
    actions: ControlActions,
) {
    val entries = load?.value?.entries.orEmpty()
    DetailPane(
        title = conversation.title,
        showBack = showBack,
        onBack = onBack,
        subtitle = listOf(conversation.hostId, relativeTime(conversation.updatedAt)).filter(String::isNotBlank).joinToString(" · "),
        actions = { RoundIconButton(PilotIcons.Refresh, "Reload conversation", { actions.reloadTranscript(conversation) }) },
    ) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = DetailPadding, verticalArrangement = Arrangement.spacedBy(10.dp)) {
            loadStatus(load, "Loading the conversation…") { actions.reloadTranscript(conversation) }
            if (load?.value != null && entries.isEmpty()) item(key = "none") { CardNote("This conversation has no readable messages.") }
            itemsIndexed(entries) { _, entry -> TranscriptItem(entry) }
        }
    }
}

@Composable
private fun TranscriptItem(entry: ControlTranscriptEntry) {
    when (entry.role) {
        TranscriptRole.User -> MessageBubble(entry.text, mine = true)
        TranscriptRole.Assistant -> MessageBubble(entry.text, mine = false)
        TranscriptRole.Reasoning -> MessageBubble(entry.text, mine = false, label = "Thinking", dim = true)
        TranscriptRole.Tool, TranscriptRole.Other -> Column(Modifier.fillMaxWidth().padding(horizontal = 4.dp)) {
            Text(
                (entry.label ?: "Step").let(::humanLabel).uppercase(),
                style = MaterialTheme.typography.labelSmall,
                color = PilotColors.TextFaint,
            )
            Text(
                entry.text,
                style = MaterialTheme.typography.bodyMedium,
                fontFamily = if (entry.role == TranscriptRole.Tool) FontFamily.Monospace else FontFamily.Default,
                color = PilotColors.TextDim,
                maxLines = 6,
            )
        }
    }
}
