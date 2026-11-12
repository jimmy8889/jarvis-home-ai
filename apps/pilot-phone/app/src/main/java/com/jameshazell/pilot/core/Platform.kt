package com.jameshazell.pilot.core

import android.app.Activity
import android.content.Context
import android.hardware.biometrics.BiometricManager.Authenticators
import android.hardware.biometrics.BiometricPrompt
import android.net.ConnectivityManager
import android.net.Network
import android.os.CancellationSignal
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine

class AppDispatchers(
    val io: CoroutineDispatcher = Dispatchers.IO,
    val main: CoroutineDispatcher = Dispatchers.Main.immediate,
)

/**
 * Shows the system fingerprint / face / screen-lock prompt and returns once the owner is
 * confirmed. This is what unlocks the `energy-proof` signing key for the next 15 seconds.
 *
 * @throws AppException with [ErrorKind.AuthCancelled] when dismissed or not possible.
 */
suspend fun authenticateOnPhone(activity: Activity, title: String, subtitle: String? = null) {
    suspendCancellableCoroutine { continuation ->
        val signal = CancellationSignal()
        continuation.invokeOnCancellation { signal.cancel() }
        val prompt = BiometricPrompt.Builder(activity)
            .setTitle(title)
            .apply { subtitle?.let(::setSubtitle) }
            .setAllowedAuthenticators(Authenticators.BIOMETRIC_STRONG or Authenticators.DEVICE_CREDENTIAL)
            .build()
        prompt.authenticate(
            signal,
            activity.mainExecutor,
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    if (continuation.isActive) continuation.resume(Unit)
                }

                override fun onAuthenticationError(code: Int, message: CharSequence) {
                    if (continuation.isActive) {
                        continuation.resumeWithException(
                            AppException(AppError(ErrorKind.AuthCancelled, authErrorMessage(code))),
                        )
                    }
                }
            },
        )
    }
}

internal fun authErrorMessage(code: Int): String = when (code) {
    BiometricPrompt.BIOMETRIC_ERROR_USER_CANCELED,
    BiometricPrompt.BIOMETRIC_ERROR_CANCELED,
    -> "Phone unlock was cancelled. Nothing was sent."
    BiometricPrompt.BIOMETRIC_ERROR_LOCKOUT,
    BiometricPrompt.BIOMETRIC_ERROR_LOCKOUT_PERMANENT,
    -> "Too many attempts. Unlock the phone with its PIN, then try again."
    BiometricPrompt.BIOMETRIC_ERROR_NO_DEVICE_CREDENTIAL,
    BiometricPrompt.BIOMETRIC_ERROR_NO_BIOMETRICS,
    -> "Set a screen lock on this phone to authorise energy commands."
    else -> "This phone couldn't confirm it's you. Nothing was sent."
}

/** Reports when the default network (re)appears so repositories can restart their reads. */
class NetworkMonitor(context: Context) {
    private val manager = context.applicationContext.getSystemService(ConnectivityManager::class.java)
    private var callback: ConnectivityManager.NetworkCallback? = null

    /** [onAvailable] runs on a binder thread. Fires once immediately if a network is already up. */
    fun start(onAvailable: () -> Unit) {
        stop()
        val next = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) = onAvailable()
        }
        callback = next
        manager.registerDefaultNetworkCallback(next)
    }

    fun stop() {
        callback?.let { runCatching { manager.unregisterNetworkCallback(it) } }
        callback = null
    }
}
