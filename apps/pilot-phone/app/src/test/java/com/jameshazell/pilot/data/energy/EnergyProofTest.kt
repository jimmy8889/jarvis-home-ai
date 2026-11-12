package com.jameshazell.pilot.data.energy

import java.security.KeyPairGenerator
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.util.Base64
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The Energy Manager verifies exactly these bytes. */
class EnergyProofTest {
    @Test fun signingStringIsMethodPathChallengeAndBodyHash() {
        assertEquals(
            "POST\n/mobile/v1/actions/stop-ev\nchallenge-123\n" +
                "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
            EnergyProof.signingString("/mobile/v1/actions/stop-ev", "challenge-123", "{}"),
        )
    }

    @Test fun actionBodyIsTheEmptyObjectThatWasHashed() {
        assertEquals("{}", JSONObject().toString())
        assertEquals(
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            EnergyProof.sha256Hex(""),
        )
    }

    @Test fun actionIdsAndPathsAreUnchanged() {
        assertEquals(
            listOf(
                "enable-automation", "disable-automation", "hot-water-enable", "hot-water-away",
                "stop-ev", "stop-hot-water", "safe-state",
            ),
            EnergyAction.entries.map { it.id },
        )
        assertEquals("/mobile/v1/actions/safe-state", EnergyClient.actionPath(EnergyAction.SafeState))
        assertEquals("energy-proof", EnergyKey.ALIAS)
        assertEquals("X-House-Energy-Challenge", EnergyProof.CHALLENGE_HEADER)
        assertEquals("X-House-Energy-Signature", EnergyProof.SIGNATURE_HEADER)
        assertEquals("X-House-Energy-Device-Token", EnergyClient.GATEWAY_HEADER)
        assertEquals("energy:/mobile/v1/bootstrap", EnergyClient.cacheId(EnergyClient.BOOTSTRAP_PATH))
    }

    @Test fun p256SignatureOverTheSigningStringVerifiesAndIsUnwrappedBase64() {
        val pair = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
        val message = EnergyProof.signingString("/mobile/v1/actions/safe-state", "c", "{}")
        val signature = Signature.getInstance(EnergyProof.SIGNATURE_ALGORITHM).apply {
            initSign(pair.private)
            update(message.toByteArray())
        }.sign()
        val header = EnergyProof.encodeSignature(signature)
        assertTrue(header.none { it == '\n' || it == '\r' })
        val verified = Signature.getInstance("SHA256withECDSA").apply {
            initVerify(pair.public)
            update(message.toByteArray())
        }.verify(Base64.getDecoder().decode(header))
        assertTrue(verified)
    }

    @Test fun publicKeyPemIsSixtyFourColumnsWithTrailingNewline() {
        val pair = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
        val pem = EnergyProof.publicKeyPem(pair.public.encoded)
        val lines = pem.split("\n")
        assertEquals("-----BEGIN PUBLIC KEY-----", lines.first())
        assertEquals("", lines.last())
        assertEquals("-----END PUBLIC KEY-----", lines[lines.size - 2])
        val body = lines.subList(1, lines.size - 2)
        assertTrue(body.dropLast(1).all { it.length == 64 } && body.last().length in 1..64)
        assertTrue(Base64.getDecoder().decode(body.joinToString("")).contentEquals(pair.public.encoded))
    }
}
