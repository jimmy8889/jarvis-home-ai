package com.jarvis.pilotwall

import android.database.ContentObserver
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext

internal fun animationsEnabledForScale(animatorDurationScale: Float): Boolean =
    animatorDurationScale.isFinite() && animatorDurationScale > 0f

@Composable
internal fun rememberSystemAnimationsEnabled(): Boolean {
    val resolver = LocalContext.current.applicationContext.contentResolver
    fun readSetting(): Boolean = animationsEnabledForScale(
        runCatching {
            Settings.Global.getFloat(
                resolver,
                Settings.Global.ANIMATOR_DURATION_SCALE,
                1f,
            )
        }.getOrDefault(1f),
    )

    var enabled by remember(resolver) { mutableStateOf(readSetting()) }
    DisposableEffect(resolver) {
        val observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
            override fun onChange(selfChange: Boolean) {
                enabled = readSetting()
            }
        }
        resolver.registerContentObserver(
            Settings.Global.getUriFor(Settings.Global.ANIMATOR_DURATION_SCALE),
            false,
            observer,
        )
        onDispose { resolver.unregisterContentObserver(observer) }
    }
    return enabled
}
