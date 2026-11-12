package com.jameshazell.pilot.core

import java.io.IOException
import java.net.InetAddress
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLException
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Call
import okhttp3.Callback
import okhttp3.Dns
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONObject

/**
 * The single OkHttpClient (one connection pool, one dispatcher) for the whole app.
 * Variants are derived with `newBuilder()` so they share that pool.
 */
class HttpClients {
    /** No redirects, 10 s connect, 40 s read (Pilot Core holds event reads for up to 25 s). */
    val shared: OkHttpClient = OkHttpClient.Builder()
        .dns(PinnedDns)
        .followRedirects(false)
        .followSslRedirects(false)
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(40, TimeUnit.SECONDS)
        .build()

    /** Pilot Core: OkHttp's silent retry is off (commands must never be replayed) and calls are bounded. */
    val pilot: OkHttpClient = shared.newBuilder()
        .retryOnConnectionFailure(false)
        .callTimeout(50, TimeUnit.SECONDS)
        .build()

    /** Third-party artwork only: follows redirects and never carries credentials. */
    val external: OkHttpClient = shared.newBuilder()
        .followRedirects(true)
        .followSslRedirects(true)
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()

    /** Websocket keep-alive so a dead tunnel is noticed and the reconnect loop starts. */
    val events: OkHttpClient = shared.newBuilder()
        .pingInterval(20, TimeUnit.SECONDS)
        .build()
}

private object PinnedDns : Dns {
    override fun lookup(hostname: String): List<InetAddress> =
        if (hostname == Endpoints.PINNED_HOST) listOf(InetAddress.getByAddress(hostname, Endpoints.PINNED_ADDRESS))
        else Dns.SYSTEM.lookup(hostname)
}

val JsonMediaType = "application/json".toMediaType()

fun jsonBody(body: JSONObject?): RequestBody = (body?.toString() ?: "{}").toRequestBody(JsonMediaType)

/** Cancellable execution; the response is handed to [read] and always closed. */
suspend fun <T> OkHttpClient.await(request: Request, read: (Response) -> T): T =
    suspendCancellableCoroutine { continuation ->
        val call = newCall(request)
        continuation.invokeOnCancellation { call.cancel() }
        call.enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                if (continuation.isActive) continuation.resumeWithException(e)
            }

            override fun onResponse(call: Call, response: Response) {
                try {
                    val value = response.use(read)
                    if (continuation.isActive) continuation.resume(value)
                } catch (error: Exception) {
                    if (continuation.isActive) continuation.resumeWithException(error)
                }
            }
        })
    }

/** Body text of a successful response; otherwise [HttpFailure] carrying the server's explanation. */
fun Response.textOrThrow(): String {
    val text = body.string()
    if (!isSuccessful) throw HttpFailure(code, serverDetail(text))
    return text
}

/** `detail` (Pilot Core, Energy Manager) or `error` (James Control) from an error body. */
fun serverDetail(body: String): String? = runCatching {
    val root = JSONObject(body)
    root.strOrNull("detail") ?: root.strOrNull("error")
}.getOrNull()

suspend fun OkHttpClient.text(request: Request): String = await(request) { it.textOrThrow() }

/**
 * One bounded retry for reads only. Commands may have reached the server even when the response
 * was lost, so they are never replayed; neither are auth or certificate failures.
 */
suspend fun <T> retryRead(
    method: String,
    pause: suspend () -> Unit = { delay(600) },
    request: suspend () -> T,
): T {
    try {
        return request()
    } catch (error: IOException) {
        if (method != "GET" || error is SSLException || error is AppException ||
            (error is HttpFailure && error.status !in setOf(408, 502, 503, 504))
        ) throw error
        currentCoroutineContext().ensureActive()
        pause()
        return request()
    }
}
