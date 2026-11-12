package com.jameshazell.pilot.core

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.annotation.WorkerThread
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * The Pilot Core device token. On-disk format is frozen (shared with 1.x installs):
 * SharedPreferences file `pilot_secure`, keys `token_iv` and `token_ciphertext`
 * (each Base64 NO_WRAP), AES-GCM under Android Keystore alias `pilot-wall-device-token`.
 * The alias keeps its historical name on purpose: renaming it would unpair every phone.
 */
class DeviceTokenStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    @WorkerThread
    fun write(token: String) {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, secretKey())
        val encrypted = cipher.doFinal(token.toByteArray(Charsets.UTF_8))
        prefs.edit()
            .putString(KEY_IV, Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .putString(KEY_CIPHERTEXT, Base64.encodeToString(encrypted, Base64.NO_WRAP))
            .apply()
    }

    /** The token, or null when none is stored or it can no longer be decrypted. */
    @WorkerThread
    fun read(): String? = runCatching {
        val iv = Base64.decode(prefs.getString(KEY_IV, null), Base64.NO_WRAP)
        val encrypted = Base64.decode(prefs.getString(KEY_CIPHERTEXT, null), Base64.NO_WRAP)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(128, iv))
        cipher.doFinal(encrypted).toString(Charsets.UTF_8)
    }.getOrNull()?.takeIf(String::isNotBlank)

    @WorkerThread
    fun clear() {
        prefs.edit().clear().apply()
    }

    private fun secretKey(): SecretKey {
        val keyStore = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE).apply {
            init(
                KeyGenParameterSpec.Builder(
                    KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .build(),
            )
        }.generateKey()
    }

    companion object {
        const val FILE = "pilot_secure"
        const val KEY_IV = "token_iv"
        const val KEY_CIPHERTEXT = "token_ciphertext"
        const val KEY_ALIAS = "pilot-wall-device-token"
        private const val KEYSTORE = "AndroidKeyStore"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
    }
}
