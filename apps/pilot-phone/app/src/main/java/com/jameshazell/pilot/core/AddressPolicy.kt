package com.jameshazell.pilot.core

import java.net.URI

/**
 * The manifest permits cleartext globally because Android cannot express "private ranges only";
 * this policy is the actual gate. HTTP is accepted only for loopback and RFC 1918 addresses.
 * (1.x name: CoreAddressPolicy.)
 */
object AddressPolicy {
    /** Validates a Pilot Core base URL and returns it with exactly one trailing slash. */
    fun normalize(value: String): String {
        val uri = runCatching { URI(value.trim()) }
            .getOrElse { throw IllegalArgumentException("Enter a valid Pilot Core URL") }
        require(uri.scheme == "https" || uri.scheme == "http") {
            "Pilot Core must use HTTP or HTTPS"
        }
        require(!uri.host.isNullOrBlank() && uri.userInfo == null && uri.query == null && uri.fragment == null) {
            "Enter a server URL without credentials, query, or fragment"
        }
        require(uri.path.isNullOrBlank() || uri.path == "/") {
            "Pilot Core URL must not contain a path"
        }
        if (uri.scheme == "http") {
            require(isPrivateOrLoopback(uri.host)) {
                "Unencrypted HTTP is only allowed for a private Pilot Core address"
            }
        }
        return value.trim().trimEnd('/') + "/"
    }

    fun isPrivateOrLoopback(host: String): Boolean {
        if (host == "localhost" || host == "127.0.0.1" || host == "::1") return true
        val octets = host.split('.').mapNotNull { it.toIntOrNull() }
        if (octets.size != 4 || octets.any { it !in 0..255 }) return false
        return octets[0] == 10 ||
            (octets[0] == 192 && octets[1] == 168) ||
            (octets[0] == 172 && octets[1] in 16..31)
    }

    /** Energy Manager and James Control are HTTPS only, with an absolute single-slash path. */
    fun requireSecure(baseUrl: String, path: String) {
        require(baseUrl.startsWith("https://")) { "This service must use HTTPS" }
        require(path.startsWith("/") && !path.startsWith("//")) { "Request path is not valid" }
    }
}
