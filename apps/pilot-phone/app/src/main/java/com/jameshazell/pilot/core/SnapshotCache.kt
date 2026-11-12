package com.jameshazell.pilot.core

import java.io.IOException
import java.time.Instant
import org.json.JSONObject

/**
 * Saved copies of successful reads, kept in [SecretStore]. Format is frozen (shared with 1.x):
 * key `snapshot:<id>` holds `{"body": "<response text>", "savedAt": "<ISO instant>"}`;
 * the older `cache:<id>` key holds the bare body with no timestamp and is still read.
 *
 * For Energy Manager and James Control `<id>` is `energy:<path>` / `control:<path>`.
 */
/** A parsed GET response: live, or the saved copy ([stale]) with the reason live data is missing. */
data class ReadResult(val json: Any, val stale: Boolean, val savedAt: Instant?, val problem: IOException?)

class SnapshotCache(
    private val store: SecretStore,
    private val now: () -> Instant = { Instant.now() },
) {
    data class Saved(val body: String, val savedAt: Instant?)

    fun get(id: String): Saved? = runCatching {
        store.get("snapshot:$id")?.let { raw ->
            runCatching {
                val record = JSONObject(raw)
                Saved(record.getString("body"), Instant.parse(record.getString("savedAt")))
            }.getOrNull()
        } ?: store.get("cache:$id")?.let { Saved(it, null) }
    }.getOrNull()

    fun put(id: String, body: String) {
        runCatching {
            store.put(
                "snapshot:$id",
                JSONObject().put("body", body).put("savedAt", now().toString()).toString(),
                durable = false,
            )
        }
    }

    companion object {
        /**
         * Saved data may stand in only for reads that failed in transit or with a server (5xx)
         * error. Rejected credentials and every mutation never fall back.
         */
        fun mayUseSaved(method: String, error: IOException): Boolean =
            method == "GET" && error !is AppException &&
                (error !is HttpFailure || error.status in 500..599)

        /** Key of the combined Pilot Core snapshot (media + surface + dashboard). */
        fun pilotSnapshotKey(coreUrl: String, deviceId: String) = "pilot-snapshot:$coreUrl:$deviceId"
    }
}
