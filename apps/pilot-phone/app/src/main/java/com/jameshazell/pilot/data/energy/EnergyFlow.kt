package com.jameshazell.pilot.data.energy

import com.jameshazell.pilot.core.arr
import com.jameshazell.pilot.core.doubleOrNull
import com.jameshazell.pilot.core.obj
import com.jameshazell.pilot.core.objects
import com.jameshazell.pilot.core.strOrNull
import org.json.JSONObject

/** One inferred transfer in the controller's power-flow graph, e.g. solar -> battery. */
data class EnergyFlowEdge(val from: String, val to: String, val kw: Double)

/**
 * The controller's conserved power-flow graph: `snapshot.power_flow` for live readings, or a
 * plan point's `flow`. Node ids are `solar`, `grid`, `battery`, `house`, `ev`, `hot_water`.
 * Entries the controller did not send are absent from the maps, never zero.
 */
data class EnergyFlowGraph(
    /** Whole-site load: ordinary house demand plus the car and hot water. */
    val siteLoadKw: Double?,
    val sourcesKw: Map<String, Double>,
    val sinksKw: Map<String, Double>,
    /** Loads measured inside the house total, e.g. `server_rack`. */
    val submetersKw: Map<String, Double>,
    /** Only well-formed transfers with a positive power. */
    val edges: List<EnergyFlowEdge>,
    /** "high" / "medium" / "low", when the controller rated its inference. */
    val confidenceLabel: String?,
)

object EnergyFlowJson {
    fun graph(value: JSONObject?): EnergyFlowGraph? {
        if (value == null) return null
        return EnergyFlowGraph(
            siteLoadKw = value.doubleOrNull("site_load_kw"),
            sourcesKw = numbers(value.obj("sources_kw")),
            sinksKw = numbers(value.obj("sinks_kw")),
            submetersKw = numbers(value.obj("submeters_kw")),
            edges = value.arr("edges").objects().mapNotNull { edge ->
                val kw = edge.doubleOrNull("kw")
                val from = edge.strOrNull("from")
                val to = edge.strOrNull("to")
                if (kw == null || kw <= 0 || from == null || to == null) null else EnergyFlowEdge(from, to, kw)
            },
            confidenceLabel = value.obj("confidence").strOrNull("label"),
        )
    }

    private fun numbers(value: JSONObject): Map<String, Double> =
        value.keys().asSequence().mapNotNull { key -> value.doubleOrNull(key)?.let { key to it } }.toMap()
}

/** The live power-flow graph, when the controller sent one. */
fun EnergyBootstrap.flowGraph(): EnergyFlowGraph? =
    EnergyFlowJson.graph(snapshot.optJSONObject("flow") ?: snapshot.optJSONObject("power_flow"))

/** The planned power-flow graph for this step of the plan. */
fun EnergyPlanPoint.flowGraph(): EnergyFlowGraph? = EnergyFlowJson.graph(raw.optJSONObject("flow"))
