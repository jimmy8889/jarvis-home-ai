package com.jameshazell.pilot.core

import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import java.time.Instant

/** String value, or [fallback] when the key is missing or JSON null. */
fun JSONObject.str(key: String, fallback: String = ""): String =
    if (isNull(key)) fallback else optString(key, fallback)

/** Non-blank string value, or null. Numbers and booleans are not coerced. */
fun JSONObject.strOrNull(key: String): String? = (opt(key) as? String)?.takeIf(String::isNotBlank)

/** Nested object, or an empty object so chained reads never fail. */
fun JSONObject.obj(key: String): JSONObject = optJSONObject(key) ?: JSONObject()

fun JSONObject.arr(key: String): JSONArray = optJSONArray(key) ?: JSONArray()

fun JSONObject.intOrNull(key: String): Int? = if (has(key) && !isNull(key)) optInt(key) else null

fun JSONObject.boolOrNull(key: String): Boolean? =
    if (has(key) && !isNull(key)) optBoolean(key) else null

fun JSONObject.instantOrNull(key: String): Instant? =
    strOrNull(key)?.let { runCatching { Instant.parse(it) }.getOrNull() }

/** Finite number from a JSON number or numeric string; null for missing, null, NaN or text. */
fun JSONObject.doubleOrNull(key: String): Double? {
    if (!has(key) || isNull(key)) return null
    val value = when (val raw = opt(key)) {
        is Number -> raw.toDouble()
        is String -> raw.toDoubleOrNull()
        else -> null
    }
    return value?.takeIf(Double::isFinite)
}

fun JSONObject.trueKeys(): Set<String> =
    keys().asSequence().filter { optBoolean(it, false) }.toSet()

fun JSONObject?.objectsWithKeys(): List<Pair<String, JSONObject>> =
    if (this == null) emptyList()
    else keys().asSequence().mapNotNull { key -> optJSONObject(key)?.let { key to it } }.toList()

fun JSONArray?.objects(): List<JSONObject> =
    if (this == null) emptyList() else (0 until length()).mapNotNull { optJSONObject(it) }

fun JSONArray?.strings(): List<String> =
    if (this == null) emptyList()
    else (0 until length()).mapNotNull { optString(it).takeIf(String::isNotBlank) }

/** Builds an object; Kotlin null becomes JSON null (the key is kept). */
fun jsonOf(vararg pairs: Pair<String, Any?>): JSONObject =
    JSONObject().apply { pairs.forEach { (key, value) -> put(key, value ?: JSONObject.NULL) } }

/** Parses a response body that may be an object, an array or blank (treated as `{}`). */
fun parseJson(text: String): Any = JSONTokener(text.ifBlank { "{}" }).nextValue()

fun parseJsonObject(text: String): JSONObject = if (text.isBlank()) JSONObject() else JSONObject(text)

/** "hot_water" / "hotWater" / "stop-ev" -> "Hot water" / "Hot Water" / "Stop ev". */
fun humanLabel(value: String): String =
    value.replace('_', ' ').replace('-', ' ')
        .replace(Regex("([a-z])([A-Z])"), "$1 $2")
        .replaceFirstChar { it.uppercase() }
