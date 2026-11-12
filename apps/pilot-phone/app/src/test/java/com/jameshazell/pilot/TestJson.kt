package com.jameshazell.pilot

import org.json.JSONObject

/** Field names of a JSON object (android.jar's JSONObject has no public keySet). */
fun JSONObject.fieldNames(): Set<String> = keys().asSequence().toSet()
