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

/** Encrypted string storage. An interface so credential logic can be unit-tested on the JVM. */
interface SecretStore {
    /** @throws java.security.GeneralSecurityException if a stored value cannot be decrypted. */
    fun get(name: String): String?

    /**
     * @param durable true writes synchronously and fails loudly (credentials, rotated tokens);
     * false queues the write (snapshot caches, which are safe to lose).
     */
    fun put(name: String, value: String, durable: Boolean = true)

    fun remove(name: String)
}

/**
 * On-disk format is frozen (shared with 1.x installs):
 * SharedPreferences file `secure`; each value is Base64(NO_WRAP) of a 12-byte GCM IV followed by
 * the AES-256-GCM ciphertext+tag; the key is Android Keystore alias `app-v1`.
 *
 * Every call does disk and Keystore work: call from a background dispatcher.
 */
class SecureStore(context: Context) : SecretStore {
    private val prefs = context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    private fun key(): SecretKey {
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

    @WorkerThread
    @Synchronized
    override fun put(name: String, value: String, durable: Boolean) {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val encoded = Base64.encodeToString(
            cipher.iv + cipher.doFinal(value.toByteArray(Charsets.UTF_8)),
            Base64.NO_WRAP,
        )
        val edit = prefs.edit().putString(name, encoded)
        if (durable) check(edit.commit()) { "Secure storage could not be written" } else edit.apply()
    }

    @WorkerThread
    @Synchronized
    override fun get(name: String): String? {
        val encoded = prefs.getString(name, null) ?: return null
        val bytes = Base64.decode(encoded, Base64.NO_WRAP)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(TAG_BITS, bytes.copyOfRange(0, IV_BYTES)))
        return String(cipher.doFinal(bytes.copyOfRange(IV_BYTES, bytes.size)), Charsets.UTF_8)
    }

    @WorkerThread
    @Synchronized
    override fun remove(name: String) {
        prefs.edit().remove(name).apply()
    }

    companion object {
        const val FILE = "secure"
        const val KEY_ALIAS = "app-v1"
        private const val KEYSTORE = "AndroidKeyStore"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val IV_BYTES = 12
        private const val TAG_BITS = 128
    }
}
