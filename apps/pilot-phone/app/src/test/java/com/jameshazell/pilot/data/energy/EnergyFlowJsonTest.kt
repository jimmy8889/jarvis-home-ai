package com.jameshazell.pilot.data.energy

import java.time.Instant
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class EnergyFlowJsonTest {
    @Test fun malformedAndNegativeEdgesCannotCreateInventedFlows() {
        val graph = EnergyFlowJson.graph(
            JSONObject(
                """{"edges":[{"from":"solar","to":"house","kw":1},{"from":"grid","to":"battery","kw":-2},
                    {"from":"","to":"house","kw":4},{"from":"grid","to":"house"}]}""",
            ),
        )!!
        assertEquals(listOf(EnergyFlowEdge("solar", "house", 1.0)), graph.edges)
    }

    @Test fun graphKeepsOnlyReadingsTheControllerSent() {
        val graph = EnergyFlowJson.graph(
            JSONObject(
                """{"site_load_kw":6,"sources_kw":{"solar":10,"battery":null},"sinks_kw":{"ev":4,"grid":"oops"},
                    "submeters_kw":{"server_rack":0.3},"confidence":{"score":0.9,"label":"high"}}""",
            ),
        )!!
        assertEquals(6.0, graph.siteLoadKw!!, 0.0)
        assertEquals(mapOf("solar" to 10.0), graph.sourcesKw)
        assertEquals(mapOf("ev" to 4.0), graph.sinksKw)
        assertEquals(0.3, graph.submetersKw.getValue("server_rack"), 0.0)
        assertEquals("high", graph.confidenceLabel)
        assertNull(EnergyFlowJson.graph(null))
    }

    @Test fun liveGraphComesFromTheSnapshotAndPlannedGraphFromThePoint() {
        val bootstrap = EnergyJson.bootstrap(
            JSONObject(
                """{"snapshot":{"power_flow":{"site_load_kw":2}},
                    "plan":{"rolling":{"points":[{"start":"2026-11-12T02:00:00Z","flow":{"site_load_kw":5}},{"start":"2026-11-12T02:05:00Z"}]}}}""",
            ),
        )
        assertEquals(2.0, bootstrap.flowGraph()!!.siteLoadKw!!, 0.0)
        assertEquals(5.0, bootstrap.plan[0].flowGraph()!!.siteLoadKw!!, 0.0)
        assertNull(bootstrap.plan[1].flowGraph())
        assertNull(EnergyJson.bootstrap(JSONObject()).flowGraph())
    }

    @Test fun recordedFiveMinuteOutcomesDecodeAsHistory() {
        val rows = listOf(
            JSONObject(
                """{"interval_start":"2026-11-12T01:55:00Z","average_pv_kw":6.5,"average_pv1_kw":2.5,
                    "average_whole_house_load_kw":1.8,"average_house_load_kw":0.9,"average_grid_kw":-3.2,"average_battery_kw":-1.5}""",
            ),
            JSONObject("""{"interval_start":"2026-11-12T02:00:00Z"}"""),
        )
        val history = EnergyJson.history(rows)
        assertEquals(Instant.parse("2026-11-12T01:55:00Z"), history[0].measuredAt)
        assertEquals(6.5, history[0].pvKw!!, 0.0)
        assertEquals(listOf(2.5, null, null), history[0].pvStringsKw)
        assertEquals("whole-house load, not the ordinary-load share", 1.8, history[0].loadKw!!, 0.0)
        assertEquals(-3.2, history[0].gridKw!!, 0.0)
        assertEquals(-1.5, history[0].batteryKw!!, 0.0)
        assertNull("a gap in the recording stays a gap", history[1].pvKw)
        assertTrue(history[1].measuredAt != null)
    }

    @Test fun recordedDailyRowsUseTheStorageNames() {
        val day = EnergyJson.daily(
            listOf(JSONObject("""{"local_date":"2026-11-11","pv_kwh":40.5,"whole_house_load_kwh":21,"export_kwh":9.5,"house_load_kwh":12}""")),
        ).single()
        assertEquals("2026-11-11", day.date)
        assertEquals(40.5, day.solarGeneratedKwh!!, 0.0)
        assertEquals(21.0, day.houseConsumedKwh!!, 0.0)
        assertEquals(9.5, day.gridExportedKwh!!, 0.0)
    }
}
