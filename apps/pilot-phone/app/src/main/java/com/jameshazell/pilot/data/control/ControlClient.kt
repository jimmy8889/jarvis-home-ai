package com.jameshazell.pilot.data.control

import com.jameshazell.pilot.core.AddressPolicy
import com.jameshazell.pilot.core.AppDispatchers
import com.jameshazell.pilot.core.AppError
import com.jameshazell.pilot.core.AppException
import com.jameshazell.pilot.core.ControlCredentials
import com.jameshazell.pilot.core.CredentialStore
import com.jameshazell.pilot.core.Endpoints
import com.jameshazell.pilot.core.ErrorKind
import com.jameshazell.pilot.core.HttpClients
import com.jameshazell.pilot.core.ReadResult
import com.jameshazell.pilot.core.SnapshotCache
import com.jameshazell.pilot.core.jsonBody
import com.jameshazell.pilot.core.parseJson
import com.jameshazell.pilot.core.text
import java.io.IOException
import kotlinx.coroutines.withContext
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject

/**
 * James Control HTTP API and event socket. The stored URL is used as-is (after the one-time
 * retired-URL migration in CredentialStore); the pinned host resolution lives in HttpClients.
 */
class ControlClient(
    private val http: HttpClients,
    private val credentials: CredentialStore,
    private val cache: SnapshotCache,
    private val dispatchers: AppDispatchers,
) {
    /** @throws AppException with [ErrorKind.NotPaired] when no Control token is stored. */
    private suspend fun credentials(): ControlCredentials = withContext(dispatchers.io) {
        credentials.load().control ?: throw AppException(
            AppError(ErrorKind.NotPaired, "James Control isn't set up on this phone yet."),
        )
    }

    suspend fun saved(path: String): ReadResult? = withContext(dispatchers.io) {
        cache.get(cacheId(path))?.let { saved ->
            runCatching { ReadResult(parseJson(saved.body), stale = true, savedAt = saved.savedAt, problem = null) }.getOrNull()
        }
    }

    /** GET with read-through caching; see EnergyClient.read for the fallback rules. */
    suspend fun read(path: String): ReadResult {
        try {
            val text = send(path, "GET", null)
            withContext(dispatchers.io) { cache.put(cacheId(path), text) }
            return ReadResult(parseJson(text), stale = false, savedAt = null, problem = null)
        } catch (error: IOException) {
            if (SnapshotCache.mayUseSaved("GET", error)) {
                saved(path)?.let { return it.copy(problem = error) }
            }
            throw error
        }
    }

    suspend fun send(path: String, method: String, body: JSONObject?): String {
        val control = credentials()
        AddressPolicy.requireSecure(control.url, path)
        val request = Request.Builder().url(control.url + path)
            .header("Accept", "application/json")
            .header("Authorization", "Bearer ${control.token}")
            .method(method, if (method == "GET") null else jsonBody(body))
            .build()
        return http.shared.text(request)
    }

    /** Opens the event websocket. The caller owns closing it. */
    suspend fun openEvents(listener: WebSocketListener): WebSocket {
        val control = credentials()
        AddressPolicy.requireSecure(control.url, Endpoints.CONTROL_EVENTS_PATH)
        val request = Request.Builder().url(control.url + Endpoints.CONTROL_EVENTS_PATH)
            .header("Authorization", "Bearer ${control.token}")
            .build()
        return http.events.newWebSocket(request, listener)
    }

    companion object {
        const val PROJECTS_PATH = "/v1/projects"
        const val TASKS_PATH = "/v1/tasks"
        const val WORKERS_PATH = "/v1/workers"
        const val CONVERSATIONS_PATH = "/v1/conversations"
        const val MESSAGES_PATH = "/v1/messages"
        fun taskEventsPath(taskId: String) = "/v1/tasks/$taskId/events"
        fun approvalPath(approvalId: String) = "/v1/approvals/$approvalId"
        fun conversationPath(id: String, hostId: String) =
            "/v1/conversations/$id?host_id=${java.net.URLEncoder.encode(hostId, "UTF-8").replace("+", "%20")}"
        fun cacheId(path: String) = "control:$path"
    }
}
