package com.jarvis.pilotwall

import android.content.Context
import android.app.Activity
import android.security.keystore.*
import android.util.Base64
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.*
import java.io.File
import java.io.IOException
import java.security.*
import java.security.spec.ECGenParameterSpec
import java.time.Instant
import kotlinx.coroutines.*

class UnifiedClient(val context:Context){
 val store=SecureStore(context)
 private val snapshots=SnapshotCache(store::get,store::put)
 var offline=false;private set
 var savedAt:Instant?=null;private set
 fun cached(service:String,path:String):Any?=snapshots.get("$service:$path")?.let{JSONTokener(it.body).nextValue()}
 private fun readThrough(service:String,path:String,method:String,request:()->Any):Any{
  try{val result=request();if(method=="GET")snapshots.put("$service:$path",result.toString());offline=false;return result}
  catch(e:IOException){if(SnapshotCache.mayUseSaved(method,true,e)){snapshots.get("$service:$path")?.let{offline=true;savedAt=it.savedAt;return JSONTokener(it.body).nextValue()}};throw e}
 }

 val http=OkHttpClient.Builder().followRedirects(false).connectTimeout(10,java.util.concurrent.TimeUnit.SECONDS).readTimeout(40,java.util.concurrent.TimeUnit.SECONDS).build()
 fun credentials()=JSONObject(store.get("unified")?:"{}")
 fun provision(){val f=File(context.filesDir,"unified-provision.json");if(f.exists()){val c=JSONObject(f.readText());store.put("unified",c.toString());val p=c.obj("pilot");PilotPreferences(context).save(PilotConfig(coreUrl=p.s("url"),deviceId=p.s("device_id"),keepScreenOn=false,kioskMode=false),p.s("token"));check(f.delete())}}
 private fun wire(url:String,path:String,token:String="",method:String="GET",body:JSONObject?=null,headers:Map<String,String> = emptyMap()):Any {
  require(url.startsWith("https://") && path.startsWith("/")&&!path.startsWith("//"))
  val b=Request.Builder().url(url+path).header("Accept","application/json");if(token.isNotBlank())b.header("Authorization","Bearer $token");headers.forEach{(k,v)->b.header(k,v)}
  b.method(method,if(method=="GET") null else (body?.toString()?:"{}").toRequestBody("application/json".toMediaType()))
  return http.newCall(b.build()).execute().use{val text=it.body.string();if(!it.isSuccessful)throw HttpFailure(it.code,text);JSONTokener(text.ifBlank{"{}"}).nextValue()}
 }
 fun control(path:String,method:String="GET",body:JSONObject?=null):Any {val c=credentials().obj("control");return readThrough("control",path,method){wire(c.s("url","https://hermes-control.tail7af3e.ts.net"),path,c.s("token"),method,body)}}
 fun controlEvents(listener:WebSocketListener):WebSocket {val c=credentials().obj("control");return http.newWebSocket(Request.Builder().url(c.s("url","https://hermes-control.tail7af3e.ts.net")+"/v1/events").header("Authorization","Bearer "+c.s("token")).build(),listener)}
 fun safetyKey():KeyStore {val ks=KeyStore.getInstance("AndroidKeyStore").apply{load(null)};if(!ks.containsAlias("energy-proof")){KeyPairGenerator.getInstance("EC","AndroidKeyStore").apply{initialize(KeyGenParameterSpec.Builder("energy-proof",KeyProperties.PURPOSE_SIGN).setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1")).setDigests(KeyProperties.DIGEST_SHA256).setUserAuthenticationRequired(true).setUserAuthenticationParameters(15,KeyProperties.AUTH_BIOMETRIC_STRONG or KeyProperties.AUTH_DEVICE_CREDENTIAL).build())}.generateKeyPair()};return ks}
 @Synchronized fun energy(path:String,method:String="GET",body:JSONObject?=null,headers:Map<String,String> = emptyMap()):Any=readThrough("energy",path,method){energyLive(path,method,body,headers)}
 private fun energyLive(path:String,method:String,body:JSONObject?,headers:Map<String,String>):Any{
  val all=credentials();val c=all.obj("energy");val url=c.s("url","https://energy.jameshomeautomation.work");val transport=mapOf("X-House-Energy-Device-Token" to c.s("gateway_token"))
  var session=c.optJSONObject("session")
  if(session==null){val ks=safetyKey();val pem="-----BEGIN PUBLIC KEY-----\n"+Base64.encodeToString(ks.getCertificate("energy-proof").publicKey.encoded,Base64.NO_WRAP).chunked(64).joinToString("\n")+"\n-----END PUBLIC KEY-----\n";session=wire(url,"/mobile/v1/pairing/consume",method="POST",body=json("grant" to c.s("grant"),"device_name" to "Galaxy Fold · Pilot","public_key_pem" to pem),headers=transport) as JSONObject;c.put("session",session);c.remove("grant");all.put("energy",c);store.put("unified",all.toString())}
  if(Instant.parse(session.s("access_expires_at")).isBefore(Instant.now().plusSeconds(30))){val renewed=wire(url,"/mobile/v1/session/refresh",method="POST",body=json("device_id" to session.s("device_id"),"refresh_token" to session.s("refresh_token")),headers=transport) as JSONObject;session.put("access_token",renewed.s("access_token"));session.put("access_expires_at",renewed.s("access_expires_at"));c.put("session",session);all.put("energy",c);store.put("unified",all.toString())}
  return wire(url,path,session.s("access_token"),method,body,transport+headers)
 }
 suspend fun safeAction(activity:Activity,action:String):Any {
  val challenge=withContext(Dispatchers.IO){(energy("/mobile/v1/auth/challenge","POST",JSONObject()) as JSONObject).s("challenge")}
  authenticate(activity,"Authorize ${action.replace('-',' ')}")
  val path="/mobile/v1/actions/$action";val hash=MessageDigest.getInstance("SHA-256").digest("{}".toByteArray()).joinToString(""){"%02x".format(it)}
  val signature=Signature.getInstance("SHA256withECDSA").apply{initSign(safetyKey().getKey("energy-proof",null) as PrivateKey);update("POST\n$path\n$challenge\n$hash".toByteArray())}.sign()
  return withContext(Dispatchers.IO){energy(path,"POST",JSONObject(),mapOf("X-House-Energy-Challenge" to challenge,"X-House-Energy-Signature" to Base64.encodeToString(signature,Base64.NO_WRAP)))}
 }
}
