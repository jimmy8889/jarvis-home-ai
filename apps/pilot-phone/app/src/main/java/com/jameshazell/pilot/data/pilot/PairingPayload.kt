package com.jameshazell.pilot.data.pilot

import com.jameshazell.pilot.core.AddressPolicy
import java.net.URI
import java.net.URLDecoder

/** A Pilot Core address plus a single-use grant. The grant is redeemed once and never stored. */
data class PairingPayload(val coreUrl: String, val grantToken: String) {
    companion object {
        /**
         * Accepts either the QR / deep-link form
         * `pilot://pair?core=http%3A%2F%2F10.0.1.64%3A8770&grant=single-use-token`
         * (`token=` is accepted as an alias for `grant=`), or a bare grant combined with
         * [fallbackCoreUrl].
         *
         * @throws IllegalArgumentException with a message suitable for the pairing form.
         */
        fun parse(value: String, fallbackCoreUrl: String? = null): PairingPayload {
            val trimmed = value.trim()
            require(trimmed.isNotEmpty()) { "Enter a one-time pairing grant" }
            if (trimmed.startsWith("pilot://", ignoreCase = true)) {
                val uri = runCatching { URI(trimmed) }
                    .getOrElse { throw IllegalArgumentException("This is not a Pilot pairing code") }
                require(uri.host == "pair") { "This is not a Pilot pairing code" }
                val query = uri.rawQuery.orEmpty().split('&').mapNotNull { part ->
                    val pair = part.split('=', limit = 2)
                    if (pair.size != 2) null else {
                        URLDecoder.decode(pair[0], Charsets.UTF_8.name()) to
                            URLDecoder.decode(pair[1], Charsets.UTF_8.name())
                    }
                }.toMap()
                val core = query["core"] ?: fallbackCoreUrl
                val grant = query["grant"] ?: query["token"]
                require(!core.isNullOrBlank() && !grant.isNullOrBlank()) {
                    "The pairing QR is incomplete"
                }
                return PairingPayload(AddressPolicy.normalize(core), grant)
            }
            require(!fallbackCoreUrl.isNullOrBlank()) {
                "Enter the Pilot Core address for this grant"
            }
            return PairingPayload(AddressPolicy.normalize(fallbackCoreUrl), trimmed)
        }
    }
}
