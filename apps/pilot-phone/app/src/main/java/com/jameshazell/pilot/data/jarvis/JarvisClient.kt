package com.jameshazell.pilot.data.jarvis

import com.jameshazell.pilot.core.AppError
import com.jameshazell.pilot.core.AppException
import com.jameshazell.pilot.core.ErrorKind
import com.jameshazell.pilot.core.HttpClients
import com.jameshazell.pilot.core.HttpFailure
import com.jameshazell.pilot.core.JsonMediaType
import com.jameshazell.pilot.core.await
import com.jameshazell.pilot.core.serverDetail
import java.io.IOException
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CancellationException
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response

/** The bridge calls the repository needs; an interface so it can be faked. */
interface JarvisApi {
    /** Exchanges a one-time pairing code for the bearer token. */
    suspend fun pair(baseUrl: String, code: String): String
    suspend fun health(credentials: JarvisCredentials): JarvisHealth
    suspend fun telemetry(credentials: JarvisCredentials): JarvisTelemetry
    suspend fun startTurn(credentials: JarvisCredentials, text: String, history: List<JarvisMessage>, speak: Boolean, wav: ByteArray?): JarvisTurn
    suspend fun turn(credentials: JarvisCredentials, id: String): JarvisTurn
    suspend fun cancel(credentials: JarvisCredentials, id: String)
    suspend fun audio(credentials: JarvisCredentials, id: String): ByteArray
}

/**
 * HTTP client for the JARVIS laptop bridge. Same limits as the JARVIS app: 8 s to connect, 20 s
 * to read, no redirects, no silent retries (a replayed `POST /turns` would start a second reply),
 * responses capped at 10 MB. Every failure is thrown as [AppException] with a readable message.
 */
class JarvisClient(http: HttpClients) : JarvisApi {
    private val client = http.shared.newBuilder()
        .retryOnConnectionFailure(false)
        .followRedirects(false)
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()

    override suspend fun pair(baseUrl: String, code: String): String {
        val body = JarvisProtocol.pairBody(code).toString().toRequestBody(JsonMediaType)
        val text = text(baseUrl, null, JarvisProtocol.PAIR_PATH, body)
        return try {
            JarvisProtocol.pairToken(text)
        } catch (_: Exception) {
            throw AppException(AppError(ErrorKind.Server, "The laptop answered, but not with a pairing. Is this the JARVIS bridge?"))
        }
    }

    override suspend fun health(credentials: JarvisCredentials): JarvisHealth =
        parse(text(credentials.baseUrl, credentials.token, JarvisProtocol.HEALTH_PATH), JarvisProtocol::health)

    override suspend fun telemetry(credentials: JarvisCredentials): JarvisTelemetry =
        parse(text(credentials.baseUrl, credentials.token, JarvisProtocol.TELEMETRY_PATH), JarvisProtocol::telemetry)

    override suspend fun startTurn(credentials: JarvisCredentials, text: String, history: List<JarvisMessage>, speak: Boolean, wav: ByteArray?): JarvisTurn {
        val boundary = "Jarvis" + UUID.randomUUID()
        val body = JarvisMultipart.body(boundary, text, JarvisProtocol.historyJson(history), speak, wav)
            .toRequestBody(JarvisMultipart.contentType(boundary).toMediaType())
        return parse(text(credentials.baseUrl, credentials.token, JarvisProtocol.TURNS_PATH, body), JarvisProtocol::turn)
    }

    override suspend fun turn(credentials: JarvisCredentials, id: String): JarvisTurn =
        parse(text(credentials.baseUrl, credentials.token, JarvisProtocol.turnPath(id)), JarvisProtocol::turn)

    override suspend fun cancel(credentials: JarvisCredentials, id: String) {
        text(credentials.baseUrl, credentials.token, JarvisProtocol.cancelPath(id), ByteArray(0).toRequestBody(JsonMediaType))
    }

    override suspend fun audio(credentials: JarvisCredentials, id: String): ByteArray =
        bytes(credentials.baseUrl, credentials.token, JarvisProtocol.audioPath(id), null)

    private suspend fun text(baseUrl: String, token: String?, path: String, body: RequestBody? = null): String =
        String(bytes(baseUrl, token, path, body), Charsets.UTF_8)

    private suspend fun bytes(baseUrl: String, token: String?, path: String, body: RequestBody?): ByteArray {
        val request = Request.Builder().url(baseUrl + path)
            .header("Cache-Control", "no-store")
            .apply { if (token != null) header("Authorization", "Bearer $token") }
            .method(if (body == null) "GET" else "POST", body)
            .build()
        return try {
            client.await(request, ::read)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: Exception) {
            throw AppException(jarvisError(error), error)
        }
    }

    private fun read(response: Response): ByteArray {
        val source = response.body.source()
        if (!source.request(MAX_RESPONSE_BYTES + 1)) {
            val data = source.readByteArray()
            if (!response.isSuccessful) throw HttpFailure(response.code, serverDetail(String(data, Charsets.UTF_8)))
            return data
        }
        throw AppException(AppError(ErrorKind.Server, "Laptop response too large."))
    }

    private fun <T> parse(text: String, decode: (String) -> T): T = try {
        decode(text)
    } catch (_: Exception) {
        throw AppException(AppError(ErrorKind.Server, "The laptop sent an answer Pilot couldn't read."))
    }

    companion object {
        const val MAX_RESPONSE_BYTES = 10_000_000L
    }
}

/** The JARVIS app's wording for bridge failures. Raw exception text never reaches the screen. */
fun jarvisError(error: Throwable): AppError = when (error) {
    is AppException -> error.error
    is HttpFailure -> {
        val said = error.detail?.trim()?.takeIf { it.isNotEmpty() && it.length <= 200 }
        when (error.status) {
            401 -> AppError(ErrorKind.Unauthorized, said ?: "Pair this phone with your laptop again.", 401)
            409 -> AppError(ErrorKind.Rejected, said ?: "A reply is already running. Stop it first.", 409)
            404 -> AppError(ErrorKind.NotFound, said ?: "This reply has expired.", 404)
            413 -> AppError(ErrorKind.Rejected, said ?: "Recording is too long.", 413)
            422 -> AppError(ErrorKind.Rejected, said ?: "The laptop didn't accept that message.", 422)
            else -> AppError(ErrorKind.Server, said ?: "Laptop request failed (${error.status}).", error.status)
        }
    }
    is IllegalArgumentException -> AppError(ErrorKind.Invalid, error.message ?: "That address isn't valid.")
    is IOException -> AppError(ErrorKind.Offline, UNREACHABLE)
    else -> AppError(ErrorKind.Unknown, "Something went wrong. Please retry.")
}

const val UNREACHABLE = "Laptop unavailable. Check Tailscale and keep the laptop awake."
