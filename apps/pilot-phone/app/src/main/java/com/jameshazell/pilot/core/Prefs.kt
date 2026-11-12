package com.jameshazell.pilot.core

import android.content.Context
import androidx.annotation.WorkerThread

/** Non-secret Pilot settings. */
data class PilotConfig(
    val coreUrl: String = Endpoints.PILOT_CORE_DEFAULT_URL,
    val deviceId: String = "",
    val refreshSeconds: Int = DEFAULT_REFRESH_SECONDS,
    val keepScreenOn: Boolean = false,
) {
    companion object {
        const val DEFAULT_REFRESH_SECONDS = 15
        val REFRESH_RANGE = 5..300
    }
}

/**
 * SharedPreferences file `pilot_wall` (name frozen; shared with 1.x installs). Only the keys the
 * phone uses are read or written. Keys left behind by the wall-tablet code (`night_mode`,
 * `kiosk_mode`, `ambient_after_minutes`, `display_brightness_percent`) are ignored and untouched.
 */
class Prefs(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    @WorkerThread
    fun load(): PilotConfig = PilotConfig(
        coreUrl = prefs.getString(KEY_CORE_URL, null) ?: Endpoints.PILOT_CORE_DEFAULT_URL,
        deviceId = prefs.getString(KEY_DEVICE_ID, null).orEmpty(),
        refreshSeconds = prefs.getInt(KEY_REFRESH_SECONDS, PilotConfig.DEFAULT_REFRESH_SECONDS)
            .coerceIn(PilotConfig.REFRESH_RANGE),
        keepScreenOn = prefs.getBoolean(KEY_KEEP_SCREEN_ON, false),
    )

    /** @throws IllegalArgumentException when the Core URL fails [AddressPolicy]. */
    fun save(config: PilotConfig) {
        prefs.edit()
            .putString(KEY_CORE_URL, AddressPolicy.normalize(config.coreUrl))
            .putString(KEY_DEVICE_ID, config.deviceId.trim())
            .putInt(KEY_REFRESH_SECONDS, config.refreshSeconds.coerceIn(PilotConfig.REFRESH_RANGE))
            .putBoolean(KEY_KEEP_SCREEN_ON, config.keepScreenOn)
            .apply()
    }

    companion object {
        const val FILE = "pilot_wall"
        const val KEY_CORE_URL = "core_url"
        const val KEY_DEVICE_ID = "device_id"
        const val KEY_REFRESH_SECONDS = "refresh_seconds"
        const val KEY_KEEP_SCREEN_ON = "keep_screen_on"
    }
}
