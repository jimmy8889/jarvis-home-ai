package com.jameshazell.pilot.data.control

import com.jameshazell.pilot.core.AppException
import com.jameshazell.pilot.core.ErrorKind
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.random.Random
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

/** Reconnect delays: 1 s, 2 s, 4 s ... capped at 30 s, plus up to 20% jitter. */
object ControlBackoff {
    const val MAX_MS = 30_000L

    fun delayMs(attempt: Int, jitter: Double = Random.nextDouble()): Long {
        val base = (1_000L shl (attempt - 1).coerceIn(0, 5)).coerceAtMost(MAX_MS)
        return (base + base * 0.2 * jitter.coerceIn(0.0, 1.0)).toLong().coerceAtMost(MAX_MS)
    }
}

/**
 * Keeps one `/v1/events` websocket open between [start] and [stop], reconnecting with backoff.
 * A rejected session (HTTP 401/403 on the upgrade) ends the loop in
 * [ControlConnection.SessionExpired]; only [start] after the session is renewed resumes it.
 *
 * [onEvent] and [onConnected] run on [scope]'s dispatcher.
 */
class ControlEventStream(
    private val scope: CoroutineScope,
    private val client: ControlClient,
    private val onEvent: (ControlEvent) -> Unit,
    private val onConnected: () -> Unit,
) {
    private enum class End { Dropped, Rejected }

    private val _connection = MutableStateFlow<ControlConnection>(ControlConnection.Idle)
    val connection: StateFlow<ControlConnection> = _connection.asStateFlow()

    private var job: Job? = null

    /** Starts (or restarts, skipping any backoff wait) the connection loop. */
    fun start() {
        job?.cancel()
        job = scope.launch {
            var attempt = 0
            while (isActive) {
                if (attempt == 0) _connection.value = ControlConnection.Connecting
                val end = try {
                    runSocket { attempt = 0 }
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (error: AppException) {
                    if (error.error.kind != ErrorKind.NotPaired) End.Dropped else {
                        _connection.value = ControlConnection.NotPaired
                        return@launch
                    }
                } catch (_: Exception) {
                    End.Dropped
                }
                if (end == End.Rejected) {
                    _connection.value = ControlConnection.SessionExpired
                    return@launch
                }
                attempt++
                val wait = ControlBackoff.delayMs(attempt)
                _connection.value = ControlConnection.Reconnecting(attempt, ((wait + 999) / 1000).toInt())
                delay(wait)
            }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
        _connection.value = ControlConnection.Idle
    }

    /** Called when HTTP reads discover the session is no longer accepted. */
    fun markSessionExpired() {
        job?.cancel()
        job = null
        _connection.value = ControlConnection.SessionExpired
    }

    /** Suspends while the socket is open; returns why it ended. Cancelling closes the socket. */
    private suspend fun runSocket(onOpened: () -> Unit): End {
        val ended = CompletableDeferred<End>()
        val detached = AtomicBoolean(false)
        val listener = object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                scope.launch {
                    if (detached.get() || ended.isCompleted) return@launch
                    onOpened()
                    _connection.value = ControlConnection.Live
                    onConnected()
                }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val event = ControlJson.event(text) ?: return
                scope.launch { if (!detached.get()) onEvent(event) }
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                // 1008 (policy violation) is how a websocket server refuses credentials.
                ended.complete(if (code == 1008) End.Rejected else End.Dropped)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                ended.complete(if (response?.code == 401 || response?.code == 403) End.Rejected else End.Dropped)
            }
        }
        val socket = client.openEvents(listener)
        return try {
            ended.await()
        } finally {
            detached.set(true)
            socket.close(1000, "Screen hidden")
        }
    }
}
