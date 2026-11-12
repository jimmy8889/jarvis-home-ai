package com.jameshazell.pilot.data.energy

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import androidx.annotation.WorkerThread
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.util.Base64

/** Wire formats for Energy Manager command proofs. Pure JVM so they are unit-tested. */
object EnergyProof {
    const val CHALLENGE_HEADER = "X-House-Energy-Challenge"
    const val SIGNATURE_HEADER = "X-House-Energy-Signature"
    const val SIGNATURE_ALGORITHM = "SHA256withECDSA"

    /** `POST\n<path>\n<challenge>\n<lowercase hex SHA-256 of the exact request body>`. */
    fun signingString(path: String, challenge: String, body: String): String =
        "POST\n$path\n$challenge\n${sha256Hex(body)}"

    fun sha256Hex(text: String): String =
        MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }

    /** SubjectPublicKeyInfo as PEM: 64-column Base64 and a trailing newline. */
    fun publicKeyPem(encoded: ByteArray): String =
        "-----BEGIN PUBLIC KEY-----\n" +
            Base64.getEncoder().encodeToString(encoded).chunked(64).joinToString("\n") +
            "\n-----END PUBLIC KEY-----\n"

    /** Base64 (no line breaks) of the DER signature, as sent in [SIGNATURE_HEADER]. */
    fun encodeSignature(signature: ByteArray): String = Base64.getEncoder().encodeToString(signature)
}

/**
 * The phone's Energy Manager identity: Android Keystore EC key `energy-proof` (P-256, SHA-256,
 * sign only). The private key never leaves the Keystore and can be used only within 15 seconds
 * of the owner unlocking with biometrics or the screen lock. Alias and parameters are frozen:
 * the Energy Manager has this key's public half registered from pairing.
 */
class EnergyKey {
    @WorkerThread
    private fun keyStore(): KeyStore {
        val keyStore = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        if (!keyStore.containsAlias(ALIAS)) {
            KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, KEYSTORE).apply {
                initialize(
                    KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
                        .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                        .setDigests(KeyProperties.DIGEST_SHA256)
                        .setUserAuthenticationRequired(true)
                        .setUserAuthenticationParameters(
                            AUTH_VALIDITY_SECONDS,
                            KeyProperties.AUTH_BIOMETRIC_STRONG or KeyProperties.AUTH_DEVICE_CREDENTIAL,
                        )
                        .build(),
                )
            }.generateKeyPair()
        }
        return keyStore
    }

    /** Creates the key on first use (needs a screen lock to be set). */
    @WorkerThread
    fun publicKeyPem(): String = EnergyProof.publicKeyPem(keyStore().getCertificate(ALIAS).publicKey.encoded)

    /**
     * @throws java.security.GeneralSecurityException when the owner has not just authenticated
     * (see [com.jameshazell.pilot.core.authenticateOnPhone]).
     */
    @WorkerThread
    fun sign(message: String): String {
        val signature = Signature.getInstance(EnergyProof.SIGNATURE_ALGORITHM).apply {
            initSign(keyStore().getKey(ALIAS, null) as PrivateKey)
            update(message.toByteArray(Charsets.UTF_8))
        }.sign()
        return EnergyProof.encodeSignature(signature)
    }

    companion object {
        const val ALIAS = "energy-proof"
        const val AUTH_VALIDITY_SECONDS = 15
        private const val KEYSTORE = "AndroidKeyStore"
    }
}
