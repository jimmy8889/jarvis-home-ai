package com.jameshazell.pilot.ui.control

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LifecycleStartEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.jameshazell.pilot.core.ErrorKind
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.core.humanLabel
import com.jameshazell.pilot.data.control.ControlApproval
import com.jameshazell.pilot.data.control.ControlConnection
import com.jameshazell.pilot.data.control.ControlConversation
import com.jameshazell.pilot.data.control.ControlOverview
import com.jameshazell.pilot.data.control.ControlProject
import com.jameshazell.pilot.data.control.ControlTarget
import com.jameshazell.pilot.ui.adaptive.ListDetailLayout
import com.jameshazell.pilot.ui.adaptive.LocalPilotWindow
import com.jameshazell.pilot.ui.appViewModel
import com.jameshazell.pilot.ui.components.CardNote
import com.jameshazell.pilot.ui.components.Chip
import com.jameshazell.pilot.ui.components.ConfirmDialog
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.components.ScreenHeader
import com.jameshazell.pilot.ui.components.SectionHeader
import com.jameshazell.pilot.ui.components.StateScaffold
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens
import com.jameshazell.pilot.ui.theme.PilotIcons

/** Control: James Control chat, projects, tasks, workers and conversations. */
@Composable
fun ControlScreen() {
    val model = appViewModel { ControlViewModel(it.control) }
    val overview by model.overview.collectAsStateWithLifecycle()
    val connection by model.connection.collectAsStateWithLifecycle()
    val approvals by model.pendingApprovals.collectAsStateWithLifecycle()
    val ui by model.ui.collectAsStateWithLifecycle()

    LifecycleStartEffect(model) {
        model.onScreenStarted()
        onStopOrDispose { model.onScreenStopped() }
    }

    ControlContent(overview, connection, approvals, ui, model)
}

/** The whole destination, stateless: previews and the screen both render through here. */
@Composable
internal fun ControlContent(
    overview: LoadState<ControlOverview>,
    connection: ControlConnection,
    approvals: List<ControlApproval>,
    ui: ControlUiState,
    actions: ControlActions,
) {
    val banner = connectionBanner(connection)
    Column(Modifier.fillMaxSize()) {
        ScreenHeader(title = "Control", status = banner.title, statusColor = banner.tone.color()) {
            RoundIconButton(PilotIcons.Refresh, "Refresh lists", actions::refresh)
        }
        if (banner.visible) ConnectionBannerCard(banner, actions)
        SectionTabs(ui.section, approvals.size, actions::selectSection)
        Box(Modifier.weight(1f).fillMaxWidth()) {
            if (ui.section == ControlSection.Chat) {
                ChatSection(overview, connection, approvals, ui, actions)
            } else {
                StateScaffold(
                    overview,
                    onRetry = actions::refresh,
                    loadingLabel = "Loading from James Control…",
                    errorAction = { error ->
                        if (error.kind == ErrorKind.Unauthorized || connection == ControlConnection.SessionExpired) {
                            PrimaryButton("Session renewed — reconnect", actions::reconnectAfterRenewal)
                        } else if (error.kind != ErrorKind.NotPaired) {
                            PrimaryButton("Retry", actions::refresh)
                        }
                    },
                ) { value ->
                    when (ui.section) {
                        ControlSection.Projects -> ProjectsSection(value, ui, actions)
                        ControlSection.Tasks -> TasksSection(value, ui, actions)
                        ControlSection.Workers -> WorkersSection(value, ui, actions)
                        else -> ConversationsSection(value, ui, actions)
                    }
                }
            }
        }
    }

    ui.approvals.confirming?.let { approval ->
        ConfirmDialog(
            title = "Accept this request?",
            message = "${approval.title}\n\n${approval.detail.take(400)}\n\nThe worker will carry on as soon as you accept.",
            confirmLabel = "Accept request",
            onConfirm = { actions.decideApproval(approval, accept = true) },
            onDismiss = actions::dismissApprovalConfirm,
            busy = ui.approvals.busyId == approval.id,
            error = ui.approvals.errorFor(approval.id),
        )
    }
}

@Composable
internal fun PrimaryButton(label: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier,
        colors = ButtonDefaults.buttonColors(containerColor = PilotColors.Violet, contentColor = PilotColors.OnAccent),
    ) { Text(label) }
}

/** Connecting / reconnecting / offline / session expired / not set up. Hidden while live. */
@Composable
private fun ConnectionBannerCard(banner: ConnectionBanner, actions: ControlActions) {
    val color = banner.tone.color()
    val important = banner.state == LinkState.SessionExpired
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = PilotDimens.ScreenPadding, vertical = 4.dp)
            .semantics { liveRegion = LiveRegionMode.Polite },
        shape = RoundedCornerShape(if (important) PilotDimens.CardRadius else 14.dp),
        color = if (important) color.copy(alpha = 0.14f).compositeOver(PilotColors.Panel) else PilotColors.PanelRaised,
        contentColor = PilotColors.Text,
        border = if (important) BorderStroke(1.dp, color.copy(alpha = 0.4f)) else null,
    ) {
        val onAction = when (banner.action) {
            BannerAction.RetryNow -> actions::retryConnection
            BannerAction.RenewSession -> actions::reconnectAfterRenewal
            BannerAction.None -> null
        }
        if (important) {
            Column(Modifier.padding(PilotDimens.CardPadding), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    androidx.compose.material3.Icon(PilotIcons.Warning, contentDescription = null, tint = color, modifier = Modifier.size(20.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(banner.title, style = MaterialTheme.typography.titleMedium)
                }
                banner.detail?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = PilotColors.TextDim) }
                if (onAction != null && banner.actionLabel != null) PrimaryButton(banner.actionLabel, onAction)
            }
        } else {
            Row(Modifier.padding(start = 12.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(10.dp).background(color, CircleShape))
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f).padding(vertical = 8.dp)) {
                    Text(banner.title, style = MaterialTheme.typography.labelLarge)
                    banner.detail?.let { Text(it, style = MaterialTheme.typography.labelMedium, color = PilotColors.TextDim) }
                }
                if (onAction != null && banner.actionLabel != null) {
                    TextButton(onClick = onAction) { Text(banner.actionLabel, color = PilotColors.Violet) }
                }
            }
        }
    }
}

@Composable
private fun SectionTabs(selected: ControlSection, approvalCount: Int, onSelect: (ControlSection) -> Unit) {
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = PilotDimens.ScreenPadding),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        ControlSection.entries.forEach { section ->
            val label = if (section == ControlSection.Chat && approvalCount > 0) "Chat · $approvalCount" else section.label
            Chip(label, selected = section == selected, onClick = { onSelect(section) })
        }
    }
}

// ---- Chat -----------------------------------------------------------------------------------

@Composable
private fun ChatSection(
    overview: LoadState<ControlOverview>,
    connection: ControlConnection,
    approvals: List<ControlApproval>,
    ui: ControlUiState,
    actions: ControlActions,
) {
    val value = overview.valueOrNull()
    if (!LocalPilotWindow.current.isTwoPane) {
        // Closed Fold: the live thread only. Earlier conversations are one tab away.
        ChatThread(value, connection, approvals, ui, actions)
        return
    }
    val open = value?.conversations?.firstOrNull { it.id == ui.chatConversationId }
    ListDetailLayout(
        hasDetail = true,
        onBack = {},
        list = { ChatConversationList(overview, ui.chatConversationId, actions) },
        detail = {
            if (open == null) ChatThread(value, connection, approvals, ui, actions)
            else TranscriptDetail(open, ui.transcripts[open.id], showBack = true, onBack = { actions.selectChatConversation(null) }, actions = actions)
        },
    )
}

@Composable
private fun ChatConversationList(overview: LoadState<ControlOverview>, selectedId: String?, actions: ControlActions) {
    val conversations = overview.valueOrNull()?.conversations.orEmpty()
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = PilotDimens.ScreenPadding, top = 8.dp, bottom = PilotDimens.ScreenPadding),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item(key = "live") {
            EntityRow(
                title = "Current chat",
                subtitle = "Messages sent from this phone",
                selected = selectedId == null,
                onClick = { actions.selectChatConversation(null) },
            )
        }
        item(key = "header") { SectionHeader("Earlier conversations") }
        when {
            conversations.isNotEmpty() -> items(conversations, key = { "c:${it.hostId}:${it.id}" }) { conversation ->
                ConversationRow(conversation, selected = conversation.id == selectedId) { actions.selectChatConversation(conversation) }
            }
            overview is LoadState.Loading -> item { CardNote("Loading conversations…") }
            overview is LoadState.Error -> item { CardNote(overview.error.message) }
            else -> item { CardNote("No conversations on the online workers.") }
        }
    }
}

@Composable
private fun ChatThread(
    overview: ControlOverview?,
    connection: ControlConnection,
    approvals: List<ControlApproval>,
    ui: ControlUiState,
    actions: ControlActions,
) {
    val items = ui.chat.items
    val taskTitles = remember(overview?.tasks) { overview?.tasks.orEmpty().associate { it.id to it.title } }
    val projects = overview?.projects.orEmpty()
    val listState = rememberLazyListState()
    val count = items.size + approvals.size
    val tail = (items.lastOrNull() as? ChatItem.Reply)?.text?.length ?: 0
    LaunchedEffect(count) { if (count > 0) listState.scrollToItem(count - 1, Int.MAX_VALUE / 2) }
    LaunchedEffect(tail) {
        // Follow a streaming reply only while its end is already on screen.
        if (count > 0 && listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index == count - 1) {
            listState.scrollToItem(count - 1, Int.MAX_VALUE / 2)
        }
    }

    Column(Modifier.fillMaxSize().keyboardPadding()) {
        LazyColumn(
            Modifier.weight(1f).fillMaxWidth(),
            state = listState,
            contentPadding = PaddingValues(PilotDimens.ScreenPadding),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (count == 0) {
                item(key = "empty") {
                    PilotCard {
                        Text("Message James Control", style = MaterialTheme.typography.titleMedium)
                        CardNote("Ask Codex or Hermes to do something. Replies stream in here, and anything that needs your approval appears as a card.")
                    }
                }
            }
            items(items, key = { it.key }) { item ->
                when (item) {
                    is ChatItem.Outgoing -> OutgoingBubble(item, projects, canRetry = sendBlockReason(connection) == null, onRetry = { actions.retrySend(item.key) })
                    is ChatItem.Reply -> MessageBubble(
                        text = item.text,
                        mine = false,
                        label = taskTitles[item.taskId]?.takeIf { ui.chat.items.none { o -> o is ChatItem.Outgoing && o.taskId == item.taskId } },
                        footer = if (item.streaming) {
                            { Text("Writing…", style = MaterialTheme.typography.labelMedium, color = PilotColors.Violet) }
                        } else null,
                    )
                }
            }
            items(approvals, key = { "approval:${it.id}" }) { approval ->
                ApprovalCard(
                    approval,
                    busy = ui.approvals.busyId == approval.id,
                    anyBusy = ui.approvals.busyId != null,
                    // While the dialog is open the error is shown there.
                    error = ui.approvals.errorFor(approval.id).takeIf { ui.approvals.confirming?.id != approval.id },
                    onAccept = { actions.askAcceptApproval(approval) },
                    onDecline = { actions.decideApproval(approval, accept = false) },
                )
            }
        }
        ChatComposer(projects, connection, ui, actions)
    }
}

@Composable
private fun OutgoingBubble(item: ChatItem.Outgoing, projects: List<ControlProject>, canRetry: Boolean, onRetry: () -> Unit) {
    val project = item.projectId?.let { id -> projects.firstOrNull { it.id == id }?.name ?: id }
    val route = listOfNotNull("To ${targetLabel(item.target)}", project).joinToString(" · ")
    MessageBubble(text = item.text, mine = true, label = route) {
        when (item.state) {
            SendState.Sending -> Text("Sending…", style = MaterialTheme.typography.labelMedium, color = PilotColors.TextDim)
            SendState.Sent -> Unit
            SendState.Failed -> Column(Modifier.semantics { liveRegion = LiveRegionMode.Polite }) {
                Text(
                    "Not sent. ${item.error.orEmpty()}",
                    style = MaterialTheme.typography.labelMedium,
                    color = PilotColors.Red,
                )
                TextButton(onClick = onRetry, enabled = canRetry) { Text("Try again", color = PilotColors.Violet) }
            }
        }
    }
}

@Composable
private fun ApprovalCard(
    approval: ControlApproval,
    busy: Boolean,
    anyBusy: Boolean,
    error: String?,
    onAccept: () -> Unit,
    onDecline: () -> Unit,
) {
    PilotCard(tint = PilotColors.Amber) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("APPROVAL REQUESTED", style = MaterialTheme.typography.labelSmall, color = PilotColors.Amber, modifier = Modifier.weight(1f))
            approval.risk?.let { StatusPill("${humanLabel(it)} risk", if (it == "high") Tone.Bad else Tone.Warn) }
        }
        Text(approval.title, style = MaterialTheme.typography.titleMedium)
        if (approval.detail.isNotBlank() && approval.detail != "{}") {
            Text(
                approval.detail,
                style = MaterialTheme.typography.bodyMedium,
                fontFamily = FontFamily.Monospace,
                color = PilotColors.TextDim,
                maxLines = 8,
                overflow = TextOverflow.Ellipsis,
            )
        }
        if (error != null) {
            Text(error, style = MaterialTheme.typography.bodyMedium, color = PilotColors.Red, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            Spacer(Modifier.weight(1f))
            TextButton(onClick = onDecline, enabled = !anyBusy) { Text(if (busy) "Sending…" else "Decline", color = PilotColors.TextDim) }
            PrimaryButton("Accept…", onAccept, enabled = !anyBusy)
        }
    }
}

@Composable
private fun ChatComposer(projects: List<ControlProject>, connection: ControlConnection, ui: ControlUiState, actions: ControlActions) {
    val blocked = sendBlockReason(connection)
    Column(
        Modifier
            .fillMaxWidth()
            .padding(start = PilotDimens.ScreenPadding, end = PilotDimens.ScreenPadding, bottom = 8.dp),
    ) {
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ControlTarget.entries.forEach { target ->
                Chip(targetLabel(target), selected = ui.target == target, onClick = { actions.setTarget(target) })
            }
            ProjectPicker(projects, ui.projectId, actions::setProject)
        }
        Composer(
            value = ui.draft,
            onValueChange = actions::setDraft,
            onSend = actions::send,
            placeholder = "Message James Control",
            canSend = blocked == null && ui.draft.isNotBlank(),
            blockedReason = blocked,
        )
    }
}

@Composable
private fun ProjectPicker(projects: List<ControlProject>, selectedId: String?, onSelect: (String?) -> Unit) {
    var open by remember { mutableStateOf(false) }
    val selected = projects.firstOrNull { it.id == selectedId }
    Box {
        Chip(
            label = selected?.name ?: selectedId ?: "Any project",
            selected = selectedId != null,
            onClick = { open = true },
            accent = PilotColors.Teal,
            icon = ChatIcons.ArrowDown,
        )
        DropdownMenu(expanded = open, onDismissRequest = { open = false }, containerColor = PilotColors.PanelRaised) {
            DropdownMenuItem(
                text = { Text("Any project (let James Control decide)") },
                onClick = { onSelect(null); open = false },
            )
            projects.forEach { project ->
                DropdownMenuItem(text = { Text(project.name) }, onClick = { onSelect(project.id); open = false })
            }
        }
    }
}

// ---- Lists ----------------------------------------------------------------------------------

/** A tappable list row: title, a line of detail and an optional status pill. */
@Composable
internal fun EntityRow(
    title: String,
    subtitle: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    pill: String? = null,
    pillTone: Tone = Tone.Neutral,
    note: String? = null,
) {
    PilotCard(modifier = modifier.fillMaxWidth(), tint = PilotColors.Violet.takeIf { selected }, onClick = onClick) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(title, style = MaterialTheme.typography.titleMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                if (subtitle.isNotBlank()) {
                    Text(subtitle, style = MaterialTheme.typography.bodyMedium, color = PilotColors.TextDim, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                if (!note.isNullOrBlank()) {
                    Text(note, style = MaterialTheme.typography.bodyMedium, color = PilotColors.TextFaint, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
            }
            if (pill != null) {
                Spacer(Modifier.width(PilotDimens.Gap))
                StatusPill(pill, pillTone)
            }
        }
    }
}

@Composable
private fun ConversationRow(conversation: ControlConversation, selected: Boolean, onClick: () -> Unit) {
    EntityRow(
        title = conversation.title,
        subtitle = listOf(conversation.hostId, relativeTime(conversation.updatedAt)).filter(String::isNotBlank).joinToString(" · "),
        selected = selected,
        onClick = onClick,
        note = conversation.preview.takeIf { it.isNotBlank() && it != conversation.title },
    )
}

private val ListPadding = PaddingValues(start = PilotDimens.ScreenPadding, end = PilotDimens.ScreenPadding, top = 8.dp, bottom = PilotDimens.ScreenPadding)

@Composable
private fun EmptyDetail(text: String) {
    Box(Modifier.fillMaxSize().padding(PilotDimens.ScreenPadding), contentAlignment = Alignment.Center) { CardNote(text) }
}

@Composable
private fun ProjectsSection(overview: ControlOverview, ui: ControlUiState, actions: ControlActions) {
    val selected = overview.projects.firstOrNull { it.id == ui.selectedProjectId }
    val twoPane = LocalPilotWindow.current.isTwoPane
    ListDetailLayout(
        hasDetail = selected != null,
        onBack = { actions.selectProject(null) },
        list = {
            LazyColumn(Modifier.fillMaxSize(), contentPadding = ListPadding, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (overview.projects.isEmpty()) item { CardNote("James Control has no projects yet.") }
                items(overview.projects, key = { it.id }) { project ->
                    EntityRow(
                        title = project.name,
                        subtitle = listOfNotNull("Build ${humanLabel(project.buildState).lowercase()}", project.host).joinToString(" · "),
                        selected = twoPane && project.id == selected?.id,
                        onClick = { actions.selectProject(project.id) },
                        pill = humanLabel(project.syncState).ifBlank { null },
                        pillTone = projectTone(project.syncState),
                    )
                }
            }
        },
        detail = {
            selected?.let { ProjectDetail(it, overview.tasks.filter { task -> task.projectId == it.id }, !twoPane, actions) }
        },
        emptyDetail = { EmptyDetail("Select a project to see its state and tasks.") },
    )
}

@Composable
private fun TasksSection(overview: ControlOverview, ui: ControlUiState, actions: ControlActions) {
    val selected = overview.tasks.firstOrNull { it.id == ui.selectedTaskId }
    val twoPane = LocalPilotWindow.current.isTwoPane
    val projectNames = remember(overview.projects) { overview.projects.associate { it.id to it.name } }
    ListDetailLayout(
        hasDetail = selected != null,
        onBack = { actions.selectTask(null) },
        list = {
            LazyColumn(Modifier.fillMaxSize(), contentPadding = ListPadding, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (overview.tasks.isEmpty()) item { CardNote("No tasks yet. Send a message from Chat to start one.") }
                items(overview.tasks, key = { it.id }) { task ->
                    EntityRow(
                        title = task.title.ifBlank { "Untitled task" },
                        subtitle = listOfNotNull(task.projectId?.let { projectNames[it] ?: it }, task.host).joinToString(" · "),
                        selected = twoPane && task.id == selected?.id,
                        onClick = { actions.selectTask(task.id) },
                        pill = humanLabel(task.status),
                        pillTone = taskTone(task.status),
                        note = task.progress.takeIf { it.isNotBlank() && it != task.status }?.let(::humanLabel),
                    )
                }
            }
        },
        detail = {
            selected?.let { task ->
                TaskDetail(
                    task = task,
                    projectName = task.projectId?.let { projectNames[it] ?: it },
                    reply = ui.chat.reply(task.id),
                    load = ui.timelines[task.id],
                    showBack = !twoPane,
                    actions = actions,
                )
            }
        },
        emptyDetail = { EmptyDetail("Select a task to see its activity.") },
    )
}

@Composable
private fun WorkersSection(overview: ControlOverview, ui: ControlUiState, actions: ControlActions) {
    val selected = overview.workers.firstOrNull { it.id == ui.selectedWorkerId }
    val twoPane = LocalPilotWindow.current.isTwoPane
    ListDetailLayout(
        hasDetail = selected != null,
        onBack = { actions.selectWorker(null) },
        list = {
            LazyColumn(Modifier.fillMaxSize(), contentPadding = ListPadding, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (overview.workers.isEmpty()) item { CardNote("No workers have connected to James Control.") }
                items(overview.workers, key = { it.id }) { worker ->
                    EntityRow(
                        title = worker.name,
                        subtitle = humanLabel(worker.platform),
                        selected = twoPane && worker.id == selected?.id,
                        onClick = { actions.selectWorker(worker.id) },
                        pill = humanLabel(worker.status),
                        pillTone = workerTone(worker.status),
                        note = worker.currentTask?.let { id -> overview.tasks.firstOrNull { it.id == id }?.title ?: "Working on a task" },
                    )
                }
            }
        },
        detail = {
            selected?.let { worker ->
                WorkerDetail(worker, overview.tasks.firstOrNull { it.id == worker.currentTask }, overview.tasks.filter { it.host == worker.id }, !twoPane, actions)
            }
        },
        emptyDetail = { EmptyDetail("Select a worker to see what it is doing.") },
    )
}

@Composable
private fun ConversationsSection(overview: ControlOverview, ui: ControlUiState, actions: ControlActions) {
    val selected = overview.conversations.firstOrNull { it.id == ui.selectedConversationId }
    val twoPane = LocalPilotWindow.current.isTwoPane
    ListDetailLayout(
        hasDetail = selected != null,
        onBack = { actions.selectConversation(null) },
        list = {
            LazyColumn(Modifier.fillMaxSize(), contentPadding = ListPadding, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (overview.conversationsPartial) {
                    item(key = "partial") { CardNote("Some workers didn't answer, so this list may be incomplete.", color = PilotColors.Amber) }
                }
                if (overview.conversations.isEmpty()) item { CardNote("No conversations on the online workers.") }
                items(overview.conversations, key = { "${it.hostId}:${it.id}" }) { conversation ->
                    ConversationRow(conversation, selected = twoPane && conversation.id == selected?.id) { actions.selectConversation(conversation) }
                }
            }
        },
        detail = {
            selected?.let { TranscriptDetail(it, ui.transcripts[it.id], !twoPane, { actions.selectConversation(null) }, actions) }
        },
        emptyDetail = { EmptyDetail("Select a conversation to read it.") },
    )
}
