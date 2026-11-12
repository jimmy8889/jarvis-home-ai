package com.jameshazell.pilot.data.energy


import org.json.JSONObject
import java.time.Instant
import java.time.ZoneId

/** Honest wording for Energy Manager health. Input is the bootstrap `snapshot` object ([EnergyBootstrap.snapshot]). */
object EnergyHealth {
    fun fresh(snapshot: JSONObject, now: Instant = Instant.now()): Boolean {
        val t = snapshot.optJSONObject("telemetry") ?: return false
        if (!t.optBoolean("healthy", false)) return false
        val service = snapshot.optJSONObject("service") ?: JSONObject()
        if (service.optJSONObject("workers")?.optBoolean("healthy", true) == false) return false
        return runCatching {
            val seconds = java.time.Duration.between(Instant.parse(t.getString("measured_at")), now).seconds
            seconds in 0..30
        }.getOrDefault(false)
    }
    fun hotWater(snapshot: JSONObject, now: Instant = Instant.now()): String {
        if (!fresh(snapshot, now)) return "Reading unavailable"
        val devices = snapshot.optJSONObject("devices") ?: return "Unavailable"
        if (!devices.optBoolean("hot_water_available", false)) return "Unavailable"
        val completion = snapshot.optJSONObject("service")?.optJSONObject("hot_water_thermostat_completion")
        val today = now.atZone(ZoneId.of("Australia/Brisbane")).toLocalDate().toString()
        if (completion?.optString("local_date") == today) return "Thermostat satisfied (inferred)"
        if (devices.optBoolean("hot_water_on", false)) return if (devices.optBoolean("hot_water_confirmed", false)) "Heating (inferred)" else "Checking element"
        return "Off"
    }
    fun confirmedMinutes(snapshot: JSONObject): String {
        val hours = snapshot.optJSONObject("devices")?.optDouble("hot_water_runtime_hours", Double.NaN) ?: Double.NaN
        return if (hours.isFinite()) "%.1f minutes of confirmed heating today".format(hours * 60) else "Confirmed heating time unavailable"
    }
    fun purchase(snapshot: JSONObject): String {
        val proof = snapshot.optJSONObject("service")?.optJSONObject("grid_purchase_evidence") ?: return "Grid purchase approval unavailable"
        return if (proof.optBoolean("approved", false)) "Battery purchase approved by forecast evidence" else "Deliberate grid purchase not approved"
    }
    fun fault(snapshot: JSONObject): String? {
        val service = snapshot.optJSONObject("service") ?: return null
        if (!service.isNull("inverter_fault_inhibit")) return "Inverter fault: forced battery dispatch paused pending review"
        if (service.optJSONObject("workers")?.optBoolean("healthy", true) == false) return "A manager worker needs attention"
        if (!service.isNull("storage_last_flush_error")) return "Energy history storage needs attention"
        if (!service.isNull("influx_error")) return "Energy history delivery is retrying"
        val notifications = service.optJSONObject("notifications") ?: return null
        return if (notifications.optInt("pending_deliveries", 0) > 0) "Fault notifications awaiting service acknowledgement" else null
    }
}
