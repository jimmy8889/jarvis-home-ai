package com.jarvis.pilotwall

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.*
import java.io.File
import java.io.IOException
import java.security.KeyStore
import java.time.Instant
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import androidx.compose.runtime.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.*
import androidx.compose.ui.unit.dp
import java.math.BigDecimal
import java.text.NumberFormat
import java.util.Locale

fun JSONObject.s(k:String, fallback:String=""):String = if(isNull(k)) fallback else optString(k,fallback)
fun JSONObject.obj(k:String)=optJSONObject(k)?:JSONObject()
fun JSONObject.arr(k:String)=optJSONArray(k)?:JSONArray()
fun JSONArray.objects()=(0 until length()).mapNotNull{optJSONObject(it)}
fun json(vararg pairs:Pair<String,Any?>)=JSONObject().apply{pairs.forEach{(k,v)->put(k,v?:JSONObject.NULL)}}
fun money(cents:Long)=NumberFormat.getCurrencyInstance(Locale.forLanguageTag("en-AU")).format(BigDecimal.valueOf(cents,2))
fun cents(text:String):Long=BigDecimal(text.trim()).movePointRight(2).longValueExact()
fun label(s:String)=s.replace('_',' ').replace(Regex("([a-z])([A-Z])"),"$1 $2").replaceFirstChar{it.uppercase()}
class HttpFailure(val status:Int,val payload:String):IOException("Request failed ($status): "+runCatching{JSONObject(payload).s("error",JSONObject(payload).s("detail"))}.getOrDefault("").take(200))
class SecureStore(context:Context){
 private val prefs=context.getSharedPreferences("secure",0)
 private fun key():SecretKey {val ks=KeyStore.getInstance("AndroidKeyStore").apply{load(null)};return (ks.getKey("app-v1",null) as? SecretKey)?:KeyGenerator.getInstance("AES","AndroidKeyStore").apply{init(KeyGenParameterSpec.Builder("app-v1",KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT).setBlockModes("GCM").setEncryptionPaddings("NoPadding").build())}.generateKey()}
 @Synchronized fun put(name:String,value:String){val c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.ENCRYPT_MODE,key());check(prefs.edit().putString(name,Base64.encodeToString(c.iv+c.doFinal(value.toByteArray()),Base64.NO_WRAP)).commit())}
 @Synchronized fun get(name:String):String? {val encoded=prefs.getString(name,null)?:return null;val b=Base64.decode(encoded,Base64.NO_WRAP);val c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.DECRYPT_MODE,key(),GCMParameterSpec(128,b.copyOfRange(0,12)));return String(c.doFinal(b.copyOfRange(12,b.size)))}
 fun remove(name:String){prefs.edit().remove(name).commit()}
 fun clear(){prefs.edit().clear().commit()}
}
class Api(val context:Context,val base:String,val holiday:Boolean=false){
 val store=SecureStore(context)
 val http=OkHttpClient.Builder().followRedirects(false).connectTimeout(15,java.util.concurrent.TimeUnit.SECONDS).readTimeout(40,java.util.concurrent.TimeUnit.SECONDS).build()
 var offline=false
 fun configured()=store.get("credentials")!=null
 fun provision(){val f=File(context.filesDir,"provision.json");if(f.exists()){val v=JSONObject(f.readText());store.put("credentials",v.toString());check(f.delete())}}
 @Synchronized fun call(path:String,method:String="GET",body:JSONObject?=null,cache:Boolean=method=="GET",key:String?=null):Any{
  offline=false
  try{
   var creds=JSONObject(store.get("credentials")?:throw IOException("Sign in to continue"))
   if(holiday && Instant.parse(creds.s("accessExpiresAt")).isBefore(Instant.now().plusSeconds(30))) {creds=refresh(creds)}
   var reply=wire(path,method,body?.toString()?.toByteArray(),creds, key)
   if(reply.first==401 && holiday){creds=refresh(creds);reply=wire(path,method,body?.toString()?.toByteArray(),creds,key)}
   if(reply.first !in 200..299)throw HttpFailure(reply.first,reply.second)
   val text=reply.second.ifBlank{"{}"};if(cache)store.put("cache:$path",text)
   return JSONTokener(text).nextValue()
  }catch(e:IOException){if(e !is HttpFailure && cache){store.get("cache:$path")?.let{offline=true;return JSONTokener(it).nextValue()}};throw e}
 }
 private fun refresh(c:JSONObject):JSONObject {val r=wire("/api/v1/mobile/auth/refresh","POST",json("refreshToken" to c.s("refreshToken")).toString().toByteArray(),JSONObject());if(r.first !in 200..299)throw HttpFailure(r.first,r.second);val next=JSONObject(r.second);store.put("credentials",next.toString());return next}
 fun login(email:String,password:String){val install=context.getSharedPreferences("install",0);val id=install.getString("id",null)?:UUID.randomUUID().toString().also{install.edit().putString("id",it).commit()};val r=wire("/api/v1/mobile/auth/login","POST",json("email" to email,"password" to password,"installationId" to id,"deviceName" to android.os.Build.MODEL,"platform" to "android").toString().toByteArray(),JSONObject());if(r.first !in 200..299)throw HttpFailure(r.first,r.second);store.put("credentials",r.second)}
 private fun wire(path:String,method:String,body:ByteArray?,creds:JSONObject,key:String?=null):Pair<Int,String>{
  require(path.startsWith("/")&&!path.startsWith("//"))
  val req=Request.Builder().url(base+path).header("Accept","application/json")
  val token=creds.s(if(holiday)"accessToken" else "token");if(token.isNotBlank())req.header("Authorization","Bearer $token")
  key?.let{req.header("Idempotency-Key",it)}
  req.method(method,if(method in listOf("GET","HEAD")) null else (body?:"{}".toByteArray()).toRequestBody("application/json".toMediaType()))
  return http.newCall(req.build()).execute().use{it.code to (it.body?.string()?:"")}
 }
 @Synchronized fun mutate(path:String,method:String,body:JSONObject,queue:Boolean=holiday):Boolean {
  val id=UUID.randomUUID().toString()
  try{call(path,method,body,false,id);return true}catch(e:IOException){if(!queue||e is HttpFailure)throw e
   val q=JSONArray(store.get("queue")?:"[]");q.put(json("path" to path,"method" to method,"body" to body,"id" to id));store.put("queue",q.toString());return false}
 }
 @Synchronized fun replay(){val q=JSONArray(store.get("queue")?:"[]");while(q.length()>0){val x=q.getJSONObject(0);call(x.s("path"),x.s("method"),x.obj("body"),false,x.s("id"));q.remove(0);store.put("queue",q.toString())}}
 @Synchronized fun media(path:String):ByteArray{call(if(holiday)"/api/v1/mobile/session" else "/accounts",cache=false);val c=JSONObject(store.get("credentials")!!);val req=Request.Builder().url(base+path).header("Authorization","Bearer "+c.s(if(holiday)"accessToken" else "token")).build();return http.newCall(req).execute().use{if(!it.isSuccessful)throw IOException("Download failed (${it.code})");it.body!!.bytes()}}
 @Synchronized fun upload(uri:android.net.Uri,entry:String?){call("/api/v1/mobile/session",cache=false);val c=JSONObject(store.get("credentials")!!);val bytes=context.contentResolver.openInputStream(uri)!!.use{input-> val data=input.readNBytes(25*1024*1024+1);require(data.size<=25*1024*1024){"Photo exceeds 25 MB"};data};val mime=context.contentResolver.getType(uri)?:"image/jpeg";require(mime.startsWith("image/"));val body=MultipartBody.Builder().setType(MultipartBody.FORM).addFormDataPart("file","photo.${mime.substringAfter('/')}",bytes.toRequestBody(mime.toMediaType())).apply{entry?.let{addFormDataPart("journalEntryId",it)}}.build();http.newCall(Request.Builder().url(base+"/api/v1/media").header("Authorization","Bearer "+c.s("accessToken")).header("Idempotency-Key",UUID.randomUUID().toString()).post(body).build()).execute().use{if(!it.isSuccessful)throw HttpFailure(it.code,it.body?.string()?:"")}}
}
@Composable fun AppTheme(content:@Composable ()->Unit){MaterialTheme(colorScheme=lightColorScheme(primary=Color(0xFF176E69),secondary=Color(0xFFBC7752),background=Color(0xFFF5F6F1),surface=Color.White),content=content)}
@Composable fun Head(title:String,subtitle:String=""){Column(Modifier.fillMaxWidth().padding(vertical=12.dp)){Text(title,style=MaterialTheme.typography.headlineMedium,fontWeight=FontWeight.Bold);if(subtitle.isNotBlank())Text(subtitle,color=MaterialTheme.colorScheme.onSurfaceVariant)}}
@Composable fun Tile(title:String,subtitle:String="",content:@Composable ColumnScope.()->Unit={}){Card(Modifier.fillMaxWidth()){Column(Modifier.padding(18.dp),verticalArrangement=Arrangement.spacedBy(8.dp)){Text(title,style=MaterialTheme.typography.titleMedium,fontWeight=FontWeight.SemiBold);if(subtitle.isNotBlank())Text(subtitle,color=MaterialTheme.colorScheme.onSurfaceVariant);content()}}}
@Composable fun Detail(o:JSONObject,exclude:Set<String> = emptySet()) {o.keys().asSequence().filter{it !in exclude && it!="id"&&!it.endsWith("_id")&&!it.endsWith("Id")&&!o.isNull(it)}.take(40).forEach{k->when(val v=o.get(k)){is JSONObject-> {Text(label(k),fontWeight=FontWeight.Bold);Detail(v)};is JSONArray->{if(v.length()>0){Text(label(k),fontWeight=FontWeight.Bold);v.objects().take(40).forEach{Detail(it);HorizontalDivider()}}};else->{val value=if(k.endsWith("_cents"))money(o.optLong(k))else if(v is Boolean)if(v)"Yes" else "No" else v.toString();Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(12.dp)){Text(label(k.removeSuffix("_cents")),Modifier.weight(1f),color=MaterialTheme.colorScheme.onSurfaceVariant);Text(value,Modifier.weight(1.3f))}}}}}
data class Field(val key:String,val title:String,val initial:String="",val numeric:Boolean=false,val required:Boolean=true)
@Composable fun EditDialog(title:String,fields:List<Field>,busy:Boolean=false,error:String?=null,onDismiss:()->Unit,onSave:(Map<String,String>)->Unit){val values=remember(title,fields){mutableStateMapOf<String,String>().apply{fields.forEach{put(it.key,it.initial)}}};AlertDialog(onDismissRequest={if(!busy)onDismiss()},title={Text(title)},text={Column(Modifier.verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(10.dp)){fields.forEach{f->OutlinedTextField(value=values[f.key]?:"",onValueChange={values[f.key]=it},label={Text(f.title)},keyboardOptions=KeyboardOptions(keyboardType=if(f.numeric)KeyboardType.Decimal else KeyboardType.Text),modifier=Modifier.fillMaxWidth())};error?.let{Text(it,color=MaterialTheme.colorScheme.error)}}},confirmButton={TextButton(enabled=!busy&&fields.filter{it.required}.all{!values[it.key].isNullOrBlank()},onClick={onSave(values.toMap())}){Text(if(busy)"Saving…" else "Save")}},dismissButton={TextButton(onClick=onDismiss,enabled=!busy){Text("Cancel")}})}
