package com.jameshazell.pilot.ui.assistant

import com.jameshazell.pilot.data.pilot.AssistantCard
import com.jameshazell.pilot.data.pilot.AssistantReply
import com.jameshazell.pilot.data.pilot.AssistantSource
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PcmTest {
    @Test fun formatIs16kHzMono16Bit() {
        assertEquals(16_000, Pcm.SAMPLE_RATE)
        assertEquals(2, Pcm.BYTES_PER_SAMPLE)
        assertEquals(32_000, Pcm.BYTES_PER_SECOND)
    }

    @Test fun uploadIsRawSamplesWithNoHeader() {
        assertEquals(32_000, Pcm.bytesFor(1_000))
        assertEquals(16_000, Pcm.bytesFor(Pcm.MIN_UPLOAD_MS))
        assertEquals(960_000, Pcm.bytesFor(Pcm.MAX_RECORDING_MS))
        assertEquals(0, Pcm.bytesFor(0))
        // 1 ms is 16 samples; sizes are always whole samples.
        assertEquals(32, Pcm.bytesFor(1))
        assertTrue((0L..2_000L).all { Pcm.bytesFor(it) % Pcm.BYTES_PER_SAMPLE == 0 })
    }

    @Test fun durationComesFromByteCount() {
        assertEquals(1_000, Pcm.durationMs(32_000))
        assertEquals(500, Pcm.durationMs(16_000))
        assertEquals(500, Pcm.durationMs(16_001))
        assertEquals(0, Pcm.durationMs(0))
    }

    @Test fun shortRecordingsAreNotSent() {
        assertFalse(Pcm.isLongEnough(0))
        assertFalse(Pcm.isLongEnough(15_998))
        assertTrue(Pcm.isLongEnough(16_000))
    }

    @Test fun bufferKeepsChunksInOrderAndOnlyTheBytesRead() {
        val buffer = PcmBuffer(maxBytes = 100)
        assertTrue(buffer.append(byteArrayOf(1, 2, 3, 4)))
        assertTrue(buffer.append(byteArrayOf(5, 6, 9, 9), length = 2))
        assertTrue(buffer.append(ByteArray(8), length = 0))
        assertArrayEquals(byteArrayOf(1, 2, 3, 4, 5, 6), buffer.toUpload())
    }

    @Test fun bufferStopsAtTheLimit() {
        val buffer = PcmBuffer(maxBytes = 6)
        assertTrue(buffer.append(ByteArray(4) { 1 }))
        assertFalse(buffer.append(ByteArray(4) { 2 }))
        assertTrue(buffer.isFull)
        assertEquals(6, buffer.size)
        assertFalse(buffer.append(ByteArray(4) { 3 }))
        assertArrayEquals(byteArrayOf(1, 1, 1, 1, 2, 2), buffer.toUpload())
        assertEquals(Pcm.bytesFor(Pcm.MAX_RECORDING_MS), PcmBuffer().let { it.append(ByteArray(1_000_000)); it.size })
    }

    @Test fun uploadDropsATrailingHalfSample() {
        val buffer = PcmBuffer()
        buffer.append(byteArrayOf(1, 2, 3))
        assertArrayEquals(byteArrayOf(1, 2), buffer.toUpload())
        assertEquals(0, PcmBuffer().toUpload().size)
    }

    @Test fun levelIsRmsOfLittleEndianSamples() {
        assertEquals(0f, Pcm.level(ByteArray(64)), 0f)
        assertEquals(0f, Pcm.level(ByteArray(0)), 0f)
        // 0x7fff twice: full scale.
        assertEquals(1f, Pcm.level(byteArrayOf(0xff.toByte(), 0x7f, 0xff.toByte(), 0x7f)), 0.001f)
        // -32768 (0x8000): also full scale, clamped.
        assertEquals(1f, Pcm.level(byteArrayOf(0x00, 0x80.toByte())), 0.001f)
        // 0x4000 = half scale.
        assertEquals(0.5f, Pcm.level(byteArrayOf(0x00, 0x40)), 0.001f)
        // Only the first `length` bytes count.
        assertEquals(0f, Pcm.level(byteArrayOf(0, 0, 0xff.toByte(), 0x7f), length = 2), 0f)
    }
}

class AssistantReducerTest {
    private fun reply(text: String = "It is shut.", conversationId: String? = "c1", transcript: String? = null) = AssistantReply(
        text = text, conversationId = conversationId, provider = "local", continueConversation = false, roomId = "lounge",
        transcript = transcript,
        cards = listOf(AssistantCard("device", "Garage door", "Closed")),
        sources = listOf(AssistantSource("Home Assistant", null)),
    )

    @Test fun typedQuestionThenReply() {
        var state = AssistantReducer.asked(AssistantUiState(draft = "Is the garage shut?", error = "old"), "Is the garage shut?")
        assertEquals(AssistantPhase.Thinking, state.phase)
        assertEquals("", state.draft)
        assertNull(state.error)
        state = AssistantReducer.replied(state, reply(), viaVoice = false)
        assertEquals(AssistantPhase.Idle, state.phase)
        assertEquals(listOf(true, false), state.messages.map { it.fromUser })
        assertEquals(listOf(1L, 2L), state.messages.map { it.id })
        assertEquals("c1", state.conversationId)
        assertEquals("Garage door", state.messages.last().cards.single().title)
        assertEquals("Home Assistant", state.messages.last().sources.single().label)
    }

    @Test fun spokenQuestionShowsItsTranscript() {
        val state = AssistantReducer.replied(AssistantUiState(), reply(transcript = " is the garage shut "), viaVoice = true)
        assertEquals(2, state.messages.size)
        assertEquals(AssistantMessage(1, fromUser = true, text = "is the garage shut", spoken = true), state.messages.first())
        assertFalse(state.messages.last().fromUser)
        assertEquals(setOf(1L, 2L), state.messages.map { it.id }.toSet())
    }

    @Test fun aTranscriptIsNotRepeatedForTypedQuestionsOrWhenBlank() {
        assertEquals(1, AssistantReducer.replied(AssistantUiState(), reply(transcript = "typed"), viaVoice = false).messages.size)
        assertEquals(1, AssistantReducer.replied(AssistantUiState(), reply(transcript = "  "), viaVoice = true).messages.size)
    }

    @Test fun conversationIdIsKeptWhenAReplyHasNone() {
        val first = AssistantReducer.replied(AssistantUiState(), reply(conversationId = "c1"), viaVoice = false)
        assertEquals("c1", AssistantReducer.replied(first, reply(conversationId = null), viaVoice = true).conversationId)
        assertEquals("c2", AssistantReducer.replied(first, reply(conversationId = "c2"), viaVoice = true).conversationId)
    }

    @Test fun emptyRepliesStillSaySomethingAndFailuresKeepTheThread() {
        val state = AssistantReducer.replied(AssistantUiState(), reply(text = "  "), viaVoice = false)
        assertTrue(state.messages.single().text.isNotBlank())
        val failed = AssistantReducer.failed(state.copy(phase = AssistantPhase.Thinking), "Pilot Core took too long to answer.")
        assertEquals(AssistantPhase.Idle, failed.phase)
        assertEquals("Pilot Core took too long to answer.", failed.error)
        assertEquals(state.messages, failed.messages)
    }
}

class OrbGestureTest {
    @Test fun holdToTalk() {
        assertEquals(OrbAction.StartRecording, OrbGesture.onPress(AssistantPhase.Idle))
        assertEquals(OrbAction.FinishRecording, OrbGesture.onRelease(AssistantPhase.Listening, startedByThisPress = true, heldMs = 1_200))
        assertEquals(OrbAction.FinishRecording, OrbGesture.onRelease(AssistantPhase.Listening, startedByThisPress = true, heldMs = OrbGesture.HOLD_MS))
    }

    @Test fun tapToToggle() {
        assertEquals(OrbAction.None, OrbGesture.onRelease(AssistantPhase.Listening, startedByThisPress = true, heldMs = 120))
        assertEquals(OrbAction.None, OrbGesture.onPress(AssistantPhase.Listening))
        assertEquals(OrbAction.FinishRecording, OrbGesture.onRelease(AssistantPhase.Listening, startedByThisPress = false, heldMs = 80))
    }

    @Test fun touchingWhileBusyStopsAndNothingElse() {
        assertEquals(OrbAction.Stop, OrbGesture.onPress(AssistantPhase.Thinking))
        assertEquals(OrbAction.Stop, OrbGesture.onPress(AssistantPhase.Speaking))
        assertEquals(OrbAction.None, OrbGesture.onRelease(AssistantPhase.Idle, startedByThisPress = false, heldMs = 2_000))
        // The microphone permission prompt appeared instead of a recording: releasing does nothing.
        assertEquals(OrbAction.None, OrbGesture.onRelease(AssistantPhase.Idle, startedByThisPress = false, heldMs = 10))
        assertEquals(OrbAction.None, OrbGesture.onRelease(AssistantPhase.Thinking, startedByThisPress = true, heldMs = 900))
    }

    @Test fun accessibilityClickCyclesThroughTheSameActions() {
        assertEquals(OrbAction.StartRecording, OrbGesture.onClick(AssistantPhase.Idle))
        assertEquals(OrbAction.FinishRecording, OrbGesture.onClick(AssistantPhase.Listening))
        assertEquals(OrbAction.Stop, OrbGesture.onClick(AssistantPhase.Thinking))
        assertEquals(OrbAction.Stop, OrbGesture.onClick(AssistantPhase.Speaking))
    }

    @Test fun captionsAndMotion() {
        assertEquals(4, AssistantPhase.entries.map { orbCaption(it).title }.toSet().size)
        assertFalse(animationsEnabledForScale(0f))
        assertFalse(animationsEnabledForScale(Float.NaN))
        assertFalse(animationsEnabledForScale(-1f))
        assertTrue(animationsEnabledForScale(1f))
        assertTrue(animationsEnabledForScale(0.5f))
    }

    @Test fun assistantMessagesAreSentencesNotExceptionText() {
        val all = listOf(
            AssistantMessages.TOO_SHORT, AssistantMessages.MIC_DENIED, AssistantMessages.MIC_FAILED, AssistantMessages.MIC_BUSY,
            AssistantMessages.INTERRUPTED, AssistantMessages.BACKGROUNDED, AssistantMessages.PLAYBACK_FAILED, AssistantMessages.NO_ROOM,
        )
        assertTrue(all.all { it.endsWith(".") && !it.contains("Exception") && it.first().isUpperCase() })
        assertEquals(all.size, all.toSet().size)
    }
}
