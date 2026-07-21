package com.jarvis.pilotwall

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class PilotPreferences(context: Context) {
    private val preferences = context.getSharedPreferences("pilot_wall", Context.MODE_PRIVATE)
    private val tokenStore = SecureTokenStore(context)

    fun config(): PilotConfig = PilotConfig(
        coreUrl = preferences.getString("core_url", null) ?: PilotConfig().coreUrl,
        deviceId = preferences.getString("device_id", null) ?: PilotConfig().deviceId,
        refreshSeconds = preferences.getInt("refresh_seconds", 15).coerceIn(5, 300),
        keepScreenOn = preferences.getBoolean("keep_screen_on", true),
        nightMode = runCatching {
            NightMode.valueOf(preferences.getString("night_mode", NightMode.Automatic.name)!!)
        }.getOrDefault(NightMode.Automatic),
        kioskMode = preferences.getBoolean("kiosk_mode", true),
        ambientAfterMinutes = preferences.getInt("ambient_after_minutes", 5).coerceIn(1, 60),
    )

    fun token(): String? = tokenStore.read()

    fun save(config: PilotConfig, token: String? = null) {
        preferences.edit()
            .putString("core_url", CoreAddressPolicy.normalize(config.coreUrl))
            .putString("device_id", config.deviceId.trim())
            .putInt("refresh_seconds", config.refreshSeconds.coerceIn(5, 300))
            .putBoolean("keep_screen_on", config.keepScreenOn)
            .putString("night_mode", config.nightMode.name)
            .putBoolean("kiosk_mode", config.kioskMode)
            .putInt("ambient_after_minutes", config.ambientAfterMinutes.coerceIn(1, 60))
            .apply()
        token?.trim()?.takeIf(String::isNotEmpty)?.let(tokenStore::write)
    }

    fun clearCredentials() {
        tokenStore.clear()
    }
}

private class SecureTokenStore(context: Context) {
    private val preferences = context.getSharedPreferences("pilot_secure", Context.MODE_PRIVATE)
    private val alias = "pilot-wall-device-token"

    fun write(token: String) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, secretKey())
        val encrypted = cipher.doFinal(token.toByteArray(Charsets.UTF_8))
        preferences.edit()
            .putString("token_iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .putString("token_ciphertext", Base64.encodeToString(encrypted, Base64.NO_WRAP))
            .apply()
    }

    fun read(): String? = runCatching {
        val iv = Base64.decode(preferences.getString("token_iv", null), Base64.NO_WRAP)
        val encrypted = Base64.decode(
            preferences.getString("token_ciphertext", null),
            Base64.NO_WRAP,
        )
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(128, iv))
        cipher.doFinal(encrypted).toString(Charsets.UTF_8)
    }.getOrNull()

    fun clear() {
        preferences.edit().clear().apply()
    }

    private fun secretKey(): SecretKey {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keyStore.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
            .apply {
                init(
                    KeyGenParameterSpec.Builder(
                        alias,
                        KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                    )
                        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                        .build(),
                )
            }
            .generateKey()
    }
}
