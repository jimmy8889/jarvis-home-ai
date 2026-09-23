package com.jarvis.pilotwall

import java.io.IOException
import java.time.Instant
import org.json.JSONObject

/** Only successful reads are saved. Authentication failures and mutations never fall back. */
class SnapshotCache(private val read:(String)->String?,private val write:(String,String)->Unit,private val now:()->Instant={Instant.now()}) {
 data class Saved(val body:String,val savedAt:Instant?)
 fun get(path:String):Saved? = read("snapshot:$path")?.let { raw ->
  runCatching { val record=JSONObject(raw);Saved(record.getString("body"),Instant.parse(record.getString("savedAt"))) }.getOrNull()
 } ?: read("cache:$path")?.let{Saved(it,null)}
 fun put(path:String,body:String) { write("snapshot:$path",JSONObject().put("body",body).put("savedAt",now().toString()).toString()) }
 companion object {
  fun mayUseSaved(method:String,cache:Boolean,error:IOException):Boolean = method=="GET" && cache && (error !is HttpFailure || error.status in 500..599)
 }
}
