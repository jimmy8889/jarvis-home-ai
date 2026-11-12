package com.jameshazell.pilot.data.energy
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class EnergyHealthTest {
 private val now=Instant.parse("2026-10-11T02:00:00Z")
 private fun sample()=JSONObject("""{"telemetry":{"healthy":true,"measured_at":"2026-10-11T01:59:59Z"},"devices":{"hot_water_available":true,"hot_water_on":false,"hot_water_runtime_hours":0.52},"service":{"workers":{"healthy":true}}}""")
 @Test fun offDoesNotClaimWaterIsReady(){assertEquals("Off",EnergyHealth.hotWater(sample(),now))}
 @Test fun thermostatCompletionUsesBrisbaneDateAndDoesNotInventThreeHours(){val s=sample();s.getJSONObject("service").put("hot_water_thermostat_completion",JSONObject("""{"local_date":"2026-10-11"}"""));assertEquals("Thermostat satisfied (inferred)",EnergyHealth.hotWater(s,now));assertTrue(EnergyHealth.confirmedMinutes(s).contains("31"))}
 @Test fun priorDayCompletionDoesNotLatchToday(){val s=sample();s.getJSONObject("service").put("hot_water_thermostat_completion",JSONObject("""{"local_date":"2026-10-10"}"""));assertEquals("Off",EnergyHealth.hotWater(s,now))}
 @Test fun relayOnNeedsHeatingEvidence(){val s=sample();s.getJSONObject("devices").put("hot_water_on",true);assertEquals("Checking element",EnergyHealth.hotWater(s,now));s.getJSONObject("devices").put("hot_water_confirmed",true);assertEquals("Heating (inferred)",EnergyHealth.hotWater(s,now))}
 @Test fun oldOrRejectedTelemetryDoesNotAppearFresh(){val s=sample();assertFalse(EnergyHealth.fresh(s,now.plusSeconds(31)));s.getJSONObject("telemetry").put("healthy",false);assertEquals("Reading unavailable",EnergyHealth.hotWater(s,now))}
 @Test fun failedWorkerAndPendingNotificationAreVisible(){val s=sample();s.getJSONObject("service").getJSONObject("workers").put("healthy",false);assertFalse(EnergyHealth.fresh(s,now));assertNotNull(EnergyHealth.fault(s));s.getJSONObject("service").getJSONObject("workers").put("healthy",true);s.getJSONObject("service").put("notifications",JSONObject("""{"pending_deliveries":1}"""));assertTrue(EnergyHealth.fault(s)!!.contains("acknowledgement"))}
 @Test fun missingProfitEvidenceNeverAppearsApproved(){assertEquals("Grid purchase approval unavailable",EnergyHealth.purchase(sample()))}
}
