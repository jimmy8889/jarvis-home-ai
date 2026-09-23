package com.jarvis.pilotwall

import android.app.Activity
import android.hardware.biometrics.BiometricPrompt
import android.os.CancellationSignal
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import kotlinx.coroutines.*
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import java.security.*
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec
import org.json.JSONObject

suspend fun authenticate(activity:Activity,title:String)=suspendCancellableCoroutine<Unit>{c->
 val signal=CancellationSignal();c.invokeOnCancellation{signal.cancel()}
 val prompt=BiometricPrompt.Builder(activity).setTitle(title).setAllowedAuthenticators(android.hardware.biometrics.BiometricManager.Authenticators.BIOMETRIC_STRONG or android.hardware.biometrics.BiometricManager.Authenticators.DEVICE_CREDENTIAL).build()
 prompt.authenticate(signal,activity.mainExecutor,object:BiometricPrompt.AuthenticationCallback(){override fun onAuthenticationSucceeded(result:BiometricPrompt.AuthenticationResult){if(c.isActive)c.resume(Unit)};override fun onAuthenticationError(code:Int,message:CharSequence){if(c.isActive)c.resumeWithException(java.io.IOException(message.toString()))}})
}
