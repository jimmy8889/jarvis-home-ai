package com.jameshazell.pilot.data.pilot

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** Why a room's devices are being asked for. Decides whether the request is allowed at all. */
enum class ProjectionReason {
    /** The user opened the room. Skipped when the same room was read under [HomeProjectionGate.FLOOR_MS] ago. */
    UserOpened,
    /** The user tapped Refresh or Retry in the room. Always allowed (but still one at a time). */
    UserRetry,
    /** A device command the user sent has finished. Always allowed; several in a row share one read. */
    AfterAction,
    /** A live event or snapshot revision hints that something changed. Only for the visible room, rarely. */
    Changed,
}

/**
 * The only way the app reads a room's devices (`GET .../home?room_id=`), which is very expensive
 * for Pilot Core. It guarantees, for the whole app:
 *
 * - at most ONE request in flight at any time (the rest wait their turn or are dropped);
 * - a request for a room that is already waiting (or, for non-command reasons, in flight) joins
 *   that request instead of adding another;
 * - nothing is ever read in the background: [ProjectionReason.Changed] only reads the room whose
 *   detail is visible ([setVisibleRoom]) and at most once every [CHANGED_INTERVAL_MS];
 * - unless the user explicitly asked, a room is not read again within [FLOOR_MS];
 * - when the user flicks through rooms, rooms they have already left are not read.
 *
 * There are no timers in here: a request happens only because a caller asked at that moment.
 * Thread-safe.
 */
class HomeProjectionGate(
    private val clock: () -> Long = { System.nanoTime() / 1_000_000 },
    private val fetch: suspend (roomId: String) -> HomeProjection,
) {
    private val single = Mutex()
    private val lock = Any()
    private var visibleRoom: String? = null
    private var latestOpened: String? = null
    private val waiting = HashMap<String, CompletableDeferred<HomeProjection?>>()
    private var inFlightRoom: String? = null
    private var inFlight: CompletableDeferred<HomeProjection?>? = null
    private val lastStarted = HashMap<String, Long>()
    /** Waiting reads that a retry or a finished command depends on; never skipped as superseded. */
    private val pinned = HashSet<CompletableDeferred<HomeProjection?>>()

    /** The room whose detail is on screen, or null. Only that room may be read for [ProjectionReason.Changed]. */
    fun setVisibleRoom(roomId: String?) = synchronized(lock) { visibleRoom = roomId }

    val visibleRoomId: String? get() = synchronized(lock) { visibleRoom }

    /** Forget all timing (after unpairing or pairing with another Core). */
    fun reset() = synchronized(lock) {
        visibleRoom = null
        latestOpened = null
        lastStarted.clear()
    }

    /** Something may have changed in the house: re-read the visible room if that is allowed now. */
    suspend fun onChangeHint(): HomeProjection? {
        val room = visibleRoomId ?: return null
        return request(room, ProjectionReason.Changed)
    }

    /**
     * @return the room's devices, or null when the request was not made (too soon, not visible,
     * or the user has moved to another room).
     * @throws Exception whatever [fetch] throws.
     */
    suspend fun request(roomId: String, reason: ProjectionReason): HomeProjection? {
        var join: CompletableDeferred<HomeProjection?>? = null
        var mine: CompletableDeferred<HomeProjection?>? = null
        synchronized(lock) {
            val sinceLast = lastStarted[roomId]?.let { clock() - it }
            val busyWithRoom = inFlightRoom == roomId || waiting.containsKey(roomId)
            when (reason) {
                ProjectionReason.Changed -> {
                    if (roomId != visibleRoom || busyWithRoom) return null
                    if (sinceLast != null && sinceLast < CHANGED_INTERVAL_MS) return null
                }
                ProjectionReason.UserOpened -> {
                    latestOpened = roomId
                    if (!busyWithRoom && sinceLast != null && sinceLast < FLOOR_MS) return null
                }
                ProjectionReason.UserRetry -> latestOpened = roomId
                ProjectionReason.AfterAction -> Unit
            }
            join = waiting[roomId]
                // A read already on its way is good enough, except after a command: that read
                // may have started before the command took effect.
                ?: inFlight.takeIf { inFlightRoom == roomId && reason != ProjectionReason.AfterAction }
            if (join == null) mine = CompletableDeferred<HomeProjection?>().also { waiting[roomId] = it }
            if (reason == ProjectionReason.UserRetry || reason == ProjectionReason.AfterAction) pinned += (join ?: mine)!!
        }
        join?.let { return it.await() }
        val own = mine!!
        try {
            single.withLock {
                val proceed = synchronized(lock) {
                    waiting.remove(roomId, own)
                    // Opened, then left for another room before its turn came: don't read it.
                    val superseded = reason == ProjectionReason.UserOpened && own !in pinned && latestOpened != roomId
                    if (!superseded) {
                        inFlightRoom = roomId
                        inFlight = own
                        lastStarted[roomId] = clock()
                    }
                    !superseded
                }
                own.complete(if (proceed) fetch(roomId) else null)
            }
        } catch (error: Throwable) {
            own.completeExceptionally(error)
        } finally {
            synchronized(lock) {
                waiting.remove(roomId, own)
                pinned -= own
                if (inFlight === own) {
                    inFlight = null
                    inFlightRoom = null
                }
            }
        }
        return own.await()
    }

    companion object {
        /** Minimum time between two reads of the same room unless the user explicitly asked. */
        const val FLOOR_MS = 5_000L
        /** Minimum time between change-driven reads of the visible room. */
        const val CHANGED_INTERVAL_MS = 30_000L
    }
}
