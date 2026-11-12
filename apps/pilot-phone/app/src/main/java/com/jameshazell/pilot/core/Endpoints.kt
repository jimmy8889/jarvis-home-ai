package com.jameshazell.pilot.core

/**
 * Every hard-coded host in the app lives here. Stored credentials always win; these are
 * only defaults, the Control URL migration, and the one DNS pin.
 */
object Endpoints {
    /** Pre-filled in the pairing form; the saved `core_url` preference replaces it. */
    const val PILOT_CORE_DEFAULT_URL = "https://pilot.jameshomeautomation.work/"

    /** Used when the `unified.energy.url` field is absent. */
    const val ENERGY_DEFAULT_URL = "https://energy.jameshomeautomation.work"

    /** Used when the `unified.control.url` field is absent. */
    const val CONTROL_DEFAULT_URL = "https://services01.tail7af3e.ts.net:8448"

    /** 1.0.8 migration: credentials holding exactly this retired URL move to [CONTROL_DEFAULT_URL]. */
    const val CONTROL_RETIRED_URL = "https://hermes-control.tail7af3e.ts.net"

    /**
     * Android Private DNS cannot resolve MagicDNS names, so this enrolled tailnet peer is
     * resolved to its fixed tailnet address. TLS still verifies the hostname and certificate.
     * If the peer is replaced, update the address here.
     */
    const val PINNED_HOST = "services01.tail7af3e.ts.net"
    val PINNED_ADDRESS: ByteArray get() = byteArrayOf(100, 83, 177.toByte(), 79)

    const val CONTROL_EVENTS_PATH = "/v1/events"
}
