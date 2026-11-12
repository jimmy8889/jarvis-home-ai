package com.jameshazell.pilot.data.pilot

import java.io.IOException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * The request budget for `GET .../home?room_id=`, the call that overloaded Pilot Core. The gate
 * is the only place in the app that makes it, so these numbers are what Core can receive.
 */
class HomeProjectionGateTest {
    private val rooms = listOf("living", "kitchen", "bedroom", "garage")

    /** Counts calls and how many overlap. With [hold] set, calls wait until [release]. */
    private class FakeCore(private val hold: Boolean = false) {
        var nowMs = 1_000_000L
        val calls = mutableListOf<String>()
        var inFlight = 0
        var maxInFlight = 0
        var fail = false
        private val gates = ArrayDeque<CompletableDeferred<Unit>>()

        val gate = HomeProjectionGate(clock = { nowMs }) { roomId ->
            calls += roomId
            inFlight++
            maxInFlight = maxOf(maxInFlight, inFlight)
            try {
                if (hold) CompletableDeferred<Unit>().also { gates += it }.await()
                if (fail) throw IOException("boom")
                HomeProjection(roomId, roomId, emptyList())
            } finally {
                inFlight--
            }
        }

        fun release() = gates.removeFirst().complete(Unit)
    }

    private suspend fun settle() = repeat(20) { yield() }

    @Test fun homeOpenAndIdleForFiveMinutesMakesNoRequests() = runBlocking {
        val core = FakeCore()
        // Home is on screen with no room open. Every second for five minutes a live event
        // arrives or the snapshot refreshes, for any room the app knows about.
        repeat(300) {
            core.nowMs += 1_000
            assertNull(core.gate.onChangeHint())
            rooms.forEach { assertNull(core.gate.request(it, ProjectionReason.Changed)) }
        }
        assertEquals(emptyList<String>(), core.calls)
    }

    @Test fun openingOneRoomMakesExactlyOneRequest() = runBlocking {
        val core = FakeCore()
        core.gate.setVisibleRoom("living")
        assertNotNull(core.gate.request("living", ProjectionReason.UserOpened))
        assertEquals(listOf("living"), core.calls)

        // Left open and quiet (no events, no revision change): still exactly one.
        core.nowMs += 300_000
        assertEquals(1, core.calls.size)
    }

    @Test fun anOpenRoomIsRereadAtMostEveryThirtySecondsAndOnlyOnAHint() = runBlocking {
        val core = FakeCore()
        core.gate.setVisibleRoom("living")
        core.gate.request("living", ProjectionReason.UserOpened)
        // Five minutes of a hint every second.
        repeat(300) {
            core.nowMs += 1_000
            core.gate.onChangeHint()
        }
        assertEquals(1 + 10, core.calls.size)
        assertTrue(core.calls.all { it == "living" })

        // Closing the room stops it completely.
        core.gate.setVisibleRoom(null)
        repeat(300) {
            core.nowMs += 1_000
            core.gate.onChangeHint()
        }
        assertEquals(11, core.calls.size)
    }

    @Test fun rapidRoomSwitchingNeverOverlapsAndSkipsRoomsAlreadyLeft() = runBlocking {
        val core = FakeCore(hold = true)
        val results = rooms.map { room ->
            async { core.gate.request(room, ProjectionReason.UserOpened) }.also { settle() }
        }
        // The first is with Core; the others wait their turn.
        assertEquals(listOf("living"), core.calls)
        core.release()
        settle()
        // Only the room the user ended on is read next; the two in between are dropped.
        assertEquals(listOf("living", "garage"), core.calls)
        core.release()
        val values = results.awaitAll()
        assertEquals(listOf("living", null, null, "garage"), values.map { it?.roomId })
        assertEquals(1, core.maxInFlight)
        assertEquals(2, core.calls.size)
    }

    @Test fun hammeringManyRoomsAtOnceIsStillOneAtATime() = runBlocking {
        val core = FakeCore(hold = true)
        val jobs = (1..30).map { i ->
            async { core.gate.request(rooms[i % rooms.size], ProjectionReason.UserRetry) }.also { yield() }
        }
        settle()
        while (jobs.any { it.isActive }) {
            assertEquals(1, core.inFlight)
            core.release()
            settle()
        }
        assertEquals(1, core.maxInFlight)
        // 30 taps across 4 rooms: one read in flight plus at most one waiting per room at a time.
        assertTrue("calls=${core.calls.size}", core.calls.size <= rooms.size + 1)
    }

    @Test fun duplicateRequestsForARoomShareOneCall() = runBlocking {
        val core = FakeCore(hold = true)
        val first = async { core.gate.request("living", ProjectionReason.UserOpened) }
        settle()
        val second = async { core.gate.request("living", ProjectionReason.UserOpened) }
        val third = async { core.gate.request("living", ProjectionReason.UserRetry) }
        settle()
        core.release()
        assertEquals(listOf("living", "living", "living"), listOf(first, second, third).awaitAll().map { it?.roomId })
        assertEquals(1, core.calls.size)
    }

    @Test fun fiveSecondFloorUnlessTheUserExplicitlyAsks() = runBlocking {
        val core = FakeCore()
        core.gate.setVisibleRoom("living")
        core.gate.request("living", ProjectionReason.UserOpened)

        core.nowMs += 2_000
        // Closing and reopening the room straight away uses what is already known.
        assertNull(core.gate.request("living", ProjectionReason.UserOpened))
        assertNull(core.gate.request("living", ProjectionReason.Changed))
        assertEquals(1, core.calls.size)
        // The Refresh button is explicit.
        assertNotNull(core.gate.request("living", ProjectionReason.UserRetry))
        assertEquals(2, core.calls.size)

        core.nowMs += HomeProjectionGate.FLOOR_MS
        assertNotNull(core.gate.request("living", ProjectionReason.UserOpened))
        assertEquals(3, core.calls.size)
        // The floor is per room.
        assertNotNull(core.gate.request("kitchen", ProjectionReason.UserOpened))
    }

    @Test fun oneReadAfterCommandsHoweverManyFinishTogether() = runBlocking {
        val core = FakeCore(hold = true)
        val opened = async { core.gate.request("living", ProjectionReason.UserOpened) }
        settle()
        // Four lights switched at once while the opening read is still in flight.
        val after = (1..4).map { async { core.gate.request("living", ProjectionReason.AfterAction) } }
        settle()
        core.release()
        settle()
        // The read that started before the commands is not trusted: exactly one more follows.
        assertEquals(2, core.calls.size)
        core.release()
        opened.await()
        assertTrue(after.awaitAll().all { it != null })
        assertEquals(2, core.calls.size)
        assertEquals(1, core.maxInFlight)
    }

    @Test fun aReadForAFinishedCommandIsNotDroppedWhenTheUserMovesOn() = runBlocking {
        val core = FakeCore(hold = true)
        val living = async { core.gate.request("living", ProjectionReason.UserOpened) }
        settle()
        val afterAction = async { core.gate.request("kitchen", ProjectionReason.AfterAction) }
        settle()
        val garage = async { core.gate.request("garage", ProjectionReason.UserOpened) }
        settle()
        repeat(3) {
            core.release()
            settle()
        }
        assertEquals(listOf("living", "kitchen", "garage"), core.calls)
        assertEquals("kitchen", afterAction.await()?.roomId)
        living.await()
        garage.await()
        Unit
    }

    @Test fun aFailureIsReportedAndFreesTheGate() = runBlocking {
        val core = FakeCore()
        core.fail = true
        try {
            core.gate.request("living", ProjectionReason.UserOpened)
            fail("expected the failure to reach the caller")
        } catch (_: IOException) {
        }
        core.fail = false
        assertNotNull(core.gate.request("living", ProjectionReason.UserRetry))
        assertEquals(0, core.inFlight)
        assertEquals(2, core.calls.size)
    }

    @Test fun onlyTheVisibleRoomReactsToChangesAndResetForgets() = runBlocking {
        val core = FakeCore()
        core.gate.setVisibleRoom("living")
        assertNull(core.gate.request("kitchen", ProjectionReason.Changed))
        assertNotNull(core.gate.onChangeHint())
        assertEquals(listOf("living"), core.calls)
        core.gate.reset()
        assertNull(core.gate.visibleRoomId)
        assertNull(core.gate.onChangeHint())
        assertEquals(1, core.calls.size)
    }

    @Test fun pollingBacksOffWhileCoreIsFailing() {
        assertEquals(15_000L, PilotRepository.pollDelayMs(15, 0))
        assertEquals(30_000L, PilotRepository.pollDelayMs(15, 1))
        assertEquals(60_000L, PilotRepository.pollDelayMs(15, 2))
        assertEquals(120_000L, PilotRepository.pollDelayMs(15, 3))
        assertEquals(120_000L, PilotRepository.pollDelayMs(15, 50))
        assertEquals(5_000L, PilotRepository.pollDelayMs(5, 0))
        // A configured interval longer than the cap is never shortened.
        assertEquals(300_000L, PilotRepository.pollDelayMs(300, 4))
    }
}
