package com.jameshazell.pilot.core

import java.time.Instant

/**
 * What every repository flow emits. Repositories publish the saved copy first
 * (`Content(stale = true)`), then live data, and keep showing saved data when a refresh fails.
 */
sealed interface LoadState<out T> {
    /** Nothing to show yet. */
    data object Loading : LoadState<Nothing>

    /**
     * @param stale true when [value] came from the on-device cache rather than a live answer.
     * @param savedAt when a stale value was saved, if known.
     * @param problem why live data is missing while stale data is shown.
     */
    data class Content<T>(
        val value: T,
        val stale: Boolean = false,
        val savedAt: Instant? = null,
        val problem: AppError? = null,
    ) : LoadState<T>

    /** Nothing to show and the last attempt failed. */
    data class Error(val error: AppError) : LoadState<Nothing>

    fun valueOrNull(): T? = (this as? Content)?.value
    val isLive: Boolean get() = this is Content && !stale
}

/** After a failed refresh: keep whatever is on screen but mark it stale, else show the error. */
fun <T> LoadState<T>.failedWith(error: AppError): LoadState<T> = when (this) {
    is LoadState.Content -> copy(stale = true, problem = error)
    else -> LoadState.Error(error)
}

fun <T, R> LoadState<T>.map(transform: (T) -> R): LoadState<R> = when (this) {
    is LoadState.Loading -> LoadState.Loading
    is LoadState.Error -> this
    is LoadState.Content -> LoadState.Content(transform(value), stale, savedAt, problem)
}
