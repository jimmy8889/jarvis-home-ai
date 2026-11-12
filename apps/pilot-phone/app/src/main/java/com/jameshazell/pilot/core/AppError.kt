package com.jameshazell.pilot.core

import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLException
import kotlinx.coroutines.CancellationException

/** The backends the phone talks to; used to word error messages. */
enum class Service(val label: String) {
    Pilot("Pilot Core"),
    Energy("Energy Manager"),
    Control("James Control"),
}

enum class ErrorKind {
    /** No route to the service: offline, DNS, refused, dropped socket. */
    Offline,
    Timeout,
    /** Credentials were rejected (401). The user has to pair or renew the session. */
    Unauthorized,
    /** Authenticated but not allowed (403). */
    Forbidden,
    NotFound,
    /** The server refused the change (409/412/422/428), usually because data moved on. */
    Rejected,
    /** The service answered 5xx. */
    Server,
    /** TLS / certificate problems. Never retried. */
    Security,
    /** Nothing is paired for this service on this phone. */
    NotPaired,
    /** Bad user input caught before any request. */
    Invalid,
    /** The user dismissed or failed the phone unlock prompt. */
    AuthCancelled,
    Unknown,
}

/**
 * What the UI shows. [message] is always a complete, human-readable sentence; raw exception
 * text never reaches it (see [toAppError]).
 */
data class AppError(val kind: ErrorKind, val message: String, val status: Int? = null) {
    /** True when retrying later might work without the user changing anything. */
    val transient: Boolean get() = kind in setOf(ErrorKind.Offline, ErrorKind.Timeout, ErrorKind.Server)
}

/** Thrown inside the data layer for failures that already have a user-facing explanation. */
class AppException(val error: AppError, cause: Throwable? = null) : IOException(error.message, cause)

/** A non-2xx HTTP response. [detail] is the server's own `detail`/`error` text, if it sent one. */
class HttpFailure(val status: Int, val detail: String? = null) :
    IOException("HTTP $status")

sealed interface Outcome<out T> {
    data class Success<T>(val value: T) : Outcome<T>
    data class Failure(val error: AppError) : Outcome<Nothing>

    fun valueOrNull(): T? = (this as? Success)?.value
    fun errorOrNull(): AppError? = (this as? Failure)?.error
}

inline fun <T> Outcome<T>.onSuccess(block: (T) -> Unit): Outcome<T> {
    if (this is Outcome.Success) block(value)
    return this
}

inline fun <T> Outcome<T>.onFailure(block: (AppError) -> Unit): Outcome<T> {
    if (this is Outcome.Failure) block(error)
    return this
}

/** Runs [block], mapping every failure except cancellation to a readable [AppError]. */
suspend inline fun <T> outcomeOf(service: Service, block: () -> T): Outcome<T> =
    try {
        Outcome.Success(block())
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (error: Exception) {
        Outcome.Failure(error.toAppError(service))
    }

fun Throwable.toAppError(service: Service): AppError {
    val name = service.label
    return when (this) {
        is AppException -> error
        is HttpFailure -> httpError(service, status, detail)
        is SSLException -> AppError(
            ErrorKind.Security,
            "The secure connection to $name could not be verified. Nothing was sent.",
        )
        is SocketTimeoutException -> AppError(ErrorKind.Timeout, "$name took too long to answer.")
        is UnknownHostException, is ConnectException -> AppError(
            ErrorKind.Offline,
            "This phone can't reach $name. Check the network or VPN.",
        )
        is IOException -> AppError(ErrorKind.Offline, "The connection to $name was interrupted.")
        is IllegalArgumentException, is IllegalStateException ->
            // require()/check() messages in this app are written for people (see AddressPolicy).
            AppError(ErrorKind.Invalid, message?.takeIf(String::isNotBlank) ?: "That value isn't valid.")
        else -> AppError(ErrorKind.Unknown, "Something went wrong talking to $name.")
    }
}

private fun httpError(service: Service, status: Int, detail: String?): AppError {
    val name = service.label
    val said = detail?.trim()?.takeIf { it.isNotEmpty() && it.length <= 200 }
    return when (status) {
        401 -> AppError(
            ErrorKind.Unauthorized,
            when (service) {
                Service.Pilot -> "This phone's Pilot pairing was rejected. Pair it again."
                Service.Energy -> "This phone's Energy Manager session was rejected. Pair it again."
                Service.Control -> "The James Control session has expired. Renew it to reconnect."
            },
            status,
        )
        403 -> AppError(ErrorKind.Forbidden, "This phone isn't allowed to do that in $name.", status)
        404 -> AppError(
            ErrorKind.NotFound,
            if (service == Service.Pilot) "Pilot Core doesn't recognise this phone." else "$name couldn't find that.",
            status,
        )
        408, 504 -> AppError(ErrorKind.Timeout, "$name took too long to answer.", status)
        409, 412, 422, 428 -> AppError(
            ErrorKind.Rejected,
            said ?: "$name didn't accept that change. Refresh and try again.",
            status,
        )
        in 500..599 -> AppError(
            ErrorKind.Server,
            if (status == 503) "$name is running, but one of its services is unavailable."
            else "$name had a problem (error $status). Try again shortly.",
            status,
        )
        else -> AppError(ErrorKind.Unknown, said ?: "$name refused the request (error $status).", status)
    }
}
