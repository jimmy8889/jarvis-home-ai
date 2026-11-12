package com.jameshazell.pilot.ui.assistant

import androidx.lifecycle.ViewModel
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.data.pilot.PilotRepository
import com.jameshazell.pilot.data.pilot.PilotSnapshot
import kotlinx.coroutines.flow.StateFlow

class AssistantViewModel(private val pilot: PilotRepository) : ViewModel() {
    /** Rooms come from the snapshot; a question is always asked on behalf of a room. */
    val snapshot: StateFlow<LoadState<PilotSnapshot>> = pilot.snapshot
    val selectedRoomId: StateFlow<String?> = pilot.selectedRoomId

    fun refresh() = pilot.refresh()

    // FEATURE: the conversation. Text: pilot.ask(text, roomId, conversationId). Voice: record
    // 16 kHz 16-bit mono PCM (RECORD_AUDIO is declared; request it at runtime), send with
    // pilot.voice(pcm), then play pilot.audio(reply.audioDownloadUrl). Keep the chat list,
    // conversationId and phase (idle / listening / thinking / speaking) as state here.
}
